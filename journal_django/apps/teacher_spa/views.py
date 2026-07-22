"""
Тонкие APIView для teacher SPA (role=teacher).

Эндпоинты (все под /api, НЕ /api/admin):
  POST /api/getData          → данные учителя
  POST /api/getAllData        → все данные (для замен)
  POST /api/submitLesson     → атомарная запись урока
  GET  /api/report           → отчёт за текущую неделю (статусы)
  GET  /api/schedule         → расписание всех групп
  GET  /api/report/refresh   → 302 → /api/report
  GET  /api/schedule/refresh → 302 → /api/schedule
  POST /api/refreshData      → {success:true}

Права: только role='teacher' (IsTeacher).

Вся бизнес-логика — в services.py; date-math для report/schedule — здесь,
реплицирует JS-семантику Date() из routes/teacher.js в точности.
"""
from __future__ import annotations

import datetime
import re

from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import F

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsTeacher
from apps.core.utils.dates import msk_now
from apps.groups.models import Group
from apps.lessons.models import Lesson
from apps.teacher_spa import repository, services
from apps.teacher_spa.serializers import MyLessonSerializer, SubmitLessonSerializer

# ---------------------------------------------------------------------------
# Константы для парсинга расписания (дословно из routes/teacher.js)
# ---------------------------------------------------------------------------

_DAY_MAP: dict[str, int] = {
    'понедельник': 1, 'вторник': 2, 'среда': 3, 'четверг': 4,
    'пятница': 5, 'суббота': 6, 'воскресенье': 0,
    'пн': 1, 'вт': 2, 'ср': 3, 'чт': 4, 'пт': 5, 'сб': 6, 'вс': 0,
}

_DAY_NAMES = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
_DAY_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

# Regex ТОЧНО из teacher.js line 185 (gi)
_TIME_REGEX = re.compile(
    r'(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье'
    r'|пн|вт|ср|чт|пт|сб|вс)[^0-9]*(\d{1,2})[:.\-](\d{2})',
    re.IGNORECASE,
)

# Порядок сортировки дней (Mon=0 .. Sun=6) — из routes/teacher.js
_DAY_ORDER = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 0: 6}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _get_week_start() -> tuple[datetime.date, str]:
    """
    Вычисляет дату понедельника текущей недели по МСК.

    Порт routes/teacher.js lines 149-162 (Date.UTC + МСК-время).

    Python-эквивалент:
      now (UTC) + 3h → MSK datetime
      dow = msk.isoweekday() % 7  (Mon→1..Sun→7%7=0, совпадает с JS getUTCDay)
      days_to_monday = 6 if dow==0 else dow-1
      week_start = MSK-дата - timedelta(days=days_to_monday)

    Возвращает (week_start_date, week_start_str).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    msk = now + datetime.timedelta(hours=3)
    # JS getUTCDay: 0=Sun, 1=Mon, ... 6=Sat
    # Python isoweekday: 1=Mon, 7=Sun → % 7 = 0=Sun, 1=Mon, ..., 6=Sat
    dow = msk.isoweekday() % 7
    days_to_monday = 6 if dow == 0 else dow - 1
    week_start_date = datetime.date(msk.year, msk.month, msk.day) - datetime.timedelta(days=days_to_monday)
    return week_start_date, week_start_date.isoformat()


def _parse_group_times(group_name: str) -> list[dict]:
    """
    Парсит время занятий из названия группы с помощью _TIME_REGEX.

    Возвращает список {'dayNum', 'dayName', 'dayShort', 'hour', 'minute'}.
    Только совпадения с известными днями (dayNum не None).
    """
    matches = []
    for m in _TIME_REGEX.finditer(group_name):
        day_key = m.group(1).lower()
        day_num = _DAY_MAP.get(day_key)
        if day_num is None:
            continue
        matches.append({
            'dayNum': day_num,
            'dayName': _DAY_NAMES[day_num],
            'dayShort': _DAY_SHORT[day_num],
            'hour': int(m.group(2)),
            'minute': int(m.group(3)),
        })
    return matches


def _lesson_local_dt(
    week_start_date: datetime.date,
    day_num: int,
    hour: int,
    minute: int,
) -> datetime.datetime:
    """
    Вычисляет локальный datetime урока для сравнения статуса с now.

    Порт routes/teacher.js lines 237-242:
      lessonDate = copy(weekStartUTC); setDate(+offset); setHours(hour,minute,0,0)
      — setHours использует СЕРВЕРНОЕ локальное время (не UTC).

    Python-эквивалент: week_start_date трактуем как локальную дату,
    прибавляем offset дней, ставим hour:minute в локальном времени.
    """
    offset = 6 if day_num == 0 else day_num - 1
    lesson_date = week_start_date + datetime.timedelta(days=offset)
    # Без tzinfo → «наивный» datetime в локальном времени сервера (как JS setHours)
    return datetime.datetime(lesson_date.year, lesson_date.month, lesson_date.day, hour, minute)


def _format_cached_at() -> str:
    """
    Порт new Date().toLocaleString('ru-RU', {timeZone:'Europe/Moscow'}).

    Формат: '05.01.2026, 14:30:05'. ru-RU ЗАШИВАЕТ ведущие нули в день/месяц/часы —
    проверено на живом Node. (cachedAt в e2e-diff исключён как wall-clock, но
    формат держим точным для одноцифровых дат.)
    """
    now_msk = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    return f'{now_msk.day:02d}.{now_msk.month:02d}.{now_msk.year}, {now_msk.strftime("%H:%M:%S")}'


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class GetDataView(APIView):
    """POST /api/getData — данные учителя."""

    permission_classes = [IsTeacher]

    def post(self, request: Request) -> Response:
        result = services.get_data(request.user.id)
        if '_error' in result:
            return Response(
                {'error': result['_error']},
                status=result['_status'],
            )
        return Response(result)


class GetAllDataView(APIView):
    """POST /api/getAllData — все данные (для замен)."""

    permission_classes = [IsTeacher]

    def post(self, request: Request) -> Response:
        result = services.get_all_data(request.user.id)
        if '_error' in result:
            return Response(
                {'error': result['_error']},
                status=result['_status'],
            )
        return Response(result)


class SubmitLessonView(APIView):
    """POST /api/submitLesson — атомарная запись урока."""

    permission_classes = [IsTeacher]

    def post(self, request: Request) -> Response:
        serializer = SubmitLessonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = services.submit_lesson(request.user.id, serializer.validated_data)
        if '_error' in result:
            return Response(
                {'error': result['_error']},
                status=result['_status'],
            )
        return Response(result)


class ReportView(APIView):
    """
    GET /api/report — отчёт за текущую неделю с статусами (done/pending/overdue).

    Полный порт routes/teacher.js lines 142-291.

    LEGACY (после Ф1–Ф4 планирования): расписание здесь выводится regex-парсингом
    времени из ИМЕНИ группы (_parse_group_times). Актуальный источник — структурные
    слоты через GET /api/calendar (apps/scheduling). Эндпоинт оставлен ради parity и
    пока используется старыми потребителями; новый фронт-календарь уже на /api/calendar.
    """

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        unified = repository.read_all_students()

        # 2. Начало недели (понедельник по МСК).
        #    Необязательный ?week=YYYY-MM-DD — для навигации по неделям в календаре.
        #    Без параметра поведение идентично прежнему (parity-контракт).
        week_param = request.query_params.get('week')
        if week_param:
            try:
                wd = datetime.date.fromisoformat(week_param)
            except ValueError:
                return Response(
                    {'error': 'Некорректный параметр week (ожидается YYYY-MM-DD)'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if wd.weekday() != 0:
                return Response(
                    {'error': 'week должен быть понедельником'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            week_start_date, week_start_str = wd, wd.isoformat()
        else:
            week_start_date, week_start_str = _get_week_start()

        # 3. Заполненные уроки из журнала
        filled_map = repository.read_filled_lessons(week_start_str)

        # Текущий момент по МСК, наивный (для сравнения с lessonDate — тоже
        # наивный, построен из week_start_date/hour/minute как московское
        # время). ВАЖНО: не datetime.datetime.now() — это часы СЕРВЕРА, не
        # обязательно МСК (тот же класс бага, что был в engine.py due_at).
        now_local = msk_now().replace(tzinfo=None)

        # Необязательный ?mine=true — вернуть ТОЛЬКО данные текущего преподавателя
        # (кабинет учителя не должен показывать чужие расписания). Скоуп на СЕРВЕРЕ:
        # чужие данные не уходят клиенту. Без параметра — прежнее поведение (parity).
        mine = request.query_params.get('mine') in ('true', '1')
        if mine:
            own = services.get_current_teacher(request.user.id)
            data_scope = {own: unified['data'].get(own, {})} if own else {}
        else:
            data_scope = unified['data']

        lessons = []
        no_time = []

        for teacher, groups in data_scope.items():
            for group_name, group_data in groups.items():

                matches = _parse_group_times(group_name)

                # Базовая информация группы (students: только {name})
                base_info = {
                    'teacher': teacher,
                    'group': group_name,
                    'pm': group_data.get('pm') or '',
                    'vkChat': group_data.get('vkChat') or '',
                    'startDate': group_data.get('startDate') or '',
                    'isGroup': group_data.get('isGroup'),
                    'students': [{'name': s['name']} for s in group_data.get('students', [])],
                }

                if not matches:
                    # Без времени
                    no_time.append({
                        **base_info,
                        'groupDisplay': group_name,
                        'day': None,
                        'dayName': None,
                        'dayShort': None,
                        'time': None,
                        'status': 'notime',
                        'label': 'Время не указано',
                    })
                else:
                    for idx, m in enumerate(matches):
                        time_str = (
                            str(m['hour']).zfill(2) + ':' + str(m['minute']).zfill(2)
                        )

                        # Вычисляем дату урока на этой неделе (серверное локальное время)
                        lesson_dt = _lesson_local_dt(
                            week_start_date, m['dayNum'], m['hour'], m['minute']
                        )

                        # Определяем статус
                        week_key = group_name + '|||' + week_start_str
                        fill_info = filled_map.get(week_key)

                        if fill_info is not None:
                            lesson_status = 'done'
                            label = 'Заполнено ' + fill_info
                        elif now_local < lesson_dt:
                            lesson_status = 'pending'
                            label = 'Пока урока не было'
                        else:
                            lesson_status = 'overdue'
                            label = 'Надо заполнить'

                        sort_key = m['dayNum'] * 10000 + m['hour'] * 100 + m['minute']

                        lessons.append({
                            **base_info,
                            'groupDisplay': (
                                group_name + f' ({idx + 1})'
                                if len(matches) > 1
                                else group_name
                            ),
                            'day': m['dayNum'],
                            'dayName': m['dayName'],
                            'dayShort': m['dayShort'],
                            'time': time_str,
                            'sortKey': sort_key,
                            'status': lesson_status,
                            'label': label,
                        })

        # Сортировка: dayOrder Mon=0..Sun=6, внутри — sortKey
        lessons.sort(key=lambda x: (_DAY_ORDER.get(x['day'], 7), x.get('sortKey', 0)))

        return Response({
            'lessons': lessons,
            'noTime': no_time,
            'weekStart': week_start_str,
            'cachedAt': _format_cached_at(),
        })


class ReportRefreshView(APIView):
    """GET /api/report/refresh — legacy backward-compat, редирект на /api/report.

    Паритет: статус 302 и заголовок Location идентичны Express (res.redirect).
    Тело редиректа у Express непустое ("Found. Redirecting to ..."), у Django пустое —
    это functionally-equivalent: клиент следует за 302, тело 3xx не потребляется.
    """

    permission_classes = [IsTeacher]

    def get(self, request: Request):
        return HttpResponseRedirect('/api/report')


class ScheduleView(APIView):
    """
    GET /api/schedule — расписание всех групп.

    Порт routes/teacher.js lines 300-398.
    Отличие от report: нет статусов/status/label/weekStart; students включают
    {name,lessonsDone,remaining,age}; каждый слот имеет allTimes[]; noTime items
    имеют sortKey=99999 (нет dayShort).
    """

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        unified = repository.read_all_students()

        lessons = []
        no_time = []

        for teacher, groups in unified['data'].items():
            for group_name, group_data in groups.items():

                matches = _parse_group_times(group_name)

                # Базовая информация (students полные — с lessonsDone/remaining/age)
                base_info = {
                    'teacher': teacher,
                    'group': group_name,
                    'pm': group_data.get('pm') or '',
                    'vkChat': group_data.get('vkChat') or '',
                    'startDate': group_data.get('startDate') or '',
                    'isGroup': group_data.get('isGroup'),
                    'students': [
                        {
                            'name': s['name'],
                            'lessonsDone': s['lessonsDone'],
                            'remaining': s['remaining'],
                            'age': s['age'],
                        }
                        for s in group_data.get('students', [])
                    ],
                }

                if not matches:
                    # Без времени — sortKey=99999, нет dayShort
                    no_time.append({
                        **base_info,
                        'groupDisplay': group_name,
                        'day': None,
                        'dayName': None,
                        'time': None,
                        'sortKey': 99999,
                    })
                else:
                    # allTimes — список строк вида 'Понедельник HH:MM'
                    all_times = [
                        m['dayName'] + ' ' + str(m['hour']).zfill(2) + ':' + str(m['minute']).zfill(2)
                        for m in matches
                    ]

                    for idx, m in enumerate(matches):
                        time_str = (
                            str(m['hour']).zfill(2) + ':' + str(m['minute']).zfill(2)
                        )
                        sort_key = m['dayNum'] * 10000 + m['hour'] * 100 + m['minute']

                        lessons.append({
                            **base_info,
                            'groupDisplay': (
                                group_name + f' ({idx + 1})'
                                if len(matches) > 1
                                else group_name
                            ),
                            'day': m['dayNum'],
                            'dayName': m['dayName'],
                            'dayShort': m['dayShort'],
                            'time': time_str,
                            'sortKey': sort_key,
                            'allTimes': all_times,
                        })

        # Сортировка только по sortKey (asc)
        lessons.sort(key=lambda x: x.get('sortKey', 0))

        return Response({
            'lessons': lessons,
            'noTime': no_time,
            'cachedAt': _format_cached_at(),
        })


class ScheduleRefreshView(APIView):
    """GET /api/schedule/refresh — legacy backward-compat, редирект на /api/schedule."""

    permission_classes = [IsTeacher]

    def get(self, request: Request):
        return HttpResponseRedirect('/api/schedule')


class RefreshDataView(APIView):
    """POST /api/refreshData — legacy no-op, возвращает {success:true}."""

    permission_classes = [IsTeacher]

    def post(self, request: Request) -> Response:
        return Response({'success': True})


class MyLessonsView(ListAPIView):
    """
    GET /api/lessons — история проведённых уроков ТЕКУЩЕГО преподавателя.

    Скоуп по teacher_id из JWT (request.user.teacher_id), НИКОГДА из запроса —
    иначе RBAC-дыра. Пагинация StandardPagination ({rows,total,page,page_size}).
    Порядок: свежие сверху (-lesson_date, -id). Опциональные фильтры:
      ?from=YYYY-MM-DD  ?to=YYYY-MM-DD  ?group=<точное имя>
    """

    permission_classes = [IsTeacher]
    pagination_class = StandardPagination
    serializer_class = MyLessonSerializer

    def get_queryset(self):
        qs = (
            Lesson.objects
            .filter(teacher_id=self.request.user.teacher_id)
            .select_related('group', 'group__direction', 'original_teacher', 'payroll')
            .order_by('-lesson_date', '-id')
        )
        p = self.request.query_params
        d_from = p.get('from')
        d_to = p.get('to')
        group = p.get('group')
        if d_from:
            qs = qs.filter(lesson_date__gte=d_from)
        if d_to:
            qs = qs.filter(lesson_date__lte=d_to)
        if group:
            qs = qs.filter(group__name=group)
        return qs


class GroupProgressView(APIView):
    """
    GET /api/group-progress?group=<name> — матрица посещаемости группы для
    страницы группы в teacher SPA. Контракт ответа = admin
    /api/admin/groups/:id/progress; доступ гейтит services.get_group_progress
    (владелец группы или назначенный заменщик).
    """

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        group_name = request.query_params.get('group')
        if not group_name:
            return Response({'error': 'Параметр group обязателен'}, status=status.HTTP_400_BAD_REQUEST)
        result = services.get_group_progress(request.user.id, group_name)
        if '_error' in result:
            return Response({'error': result['_error']}, status=result['_status'])
        return Response(result)


class GroupDirectionsView(APIView):
    """
    GET /api/group-directions — карта {имя группы → направление+цвет} для ВСЕХ
    активных групп. Точный источник предмета/цвета (из БД `directions.color`)
    для календаря/отчёта, где /api/report (заморожен) направление не отдаёт.
    Фронт джойнит по имени группы. Роль teacher (данные не чувствительные —
    только справочник направлений; имена групп фронт и так видит в /api/report).
    """

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        rows = (
            Group.objects
            .filter(active=True)
            .values(
                'name',
                dir_name=F('direction__name'),
                color=F('direction__color'),
                is_ind=F('is_individual'),
                duration=F('lesson_duration_minutes'),
                total=F('direction__total_lessons'),
            )
        )
        groups = {
            r['name']: {
                'direction': r['dir_name'],
                'color': r['color'],
                'isIndividual': r['is_ind'],
                # Ф4: half-lesson и лимит курса — структурно (не regex по имени).
                'lessonDurationMinutes': r['duration'],
                'totalLessons': r['total'],
            }
            for r in rows
        }
        return Response({'groups': groups})
