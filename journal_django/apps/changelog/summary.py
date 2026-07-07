"""
Человекочитаемые описания операций журнала изменений.

Вход: ключ операции + события контекста (pgh_data/pgh_diff из Events) +
bulk-словари имён (группы/ученики/преподаватели — собираются repository
одним IN-запросом на страницу, без N+1).

Принцип: специфичные шаблоны для планирования/уроков/оплат (самые частые и
самые «нечитаемые» без контекста), generic-фолбэк по имени записи — для
остального. Описание НИКОГДА не пустое.
"""
from __future__ import annotations

from typing import Any, Optional

# Статусы plansнного занятия (apps/scheduling/occurrences.py) → русский.
STATUS_RU = {
    'pending':   'запланирован',
    'overdue':   'просрочен',
    'done':      'проведён',
    'cancelled': 'отменён',
    'moved':     'перенесён',
}

_LABEL_RU = {'insert': 'создание', 'update': 'изменение', 'delete': 'удаление'}


def _fmt_time(t: Any) -> str:
    """'12:00:00' → '12:00'."""
    s = str(t or '')
    return s[:5] if len(s) >= 5 else s


def _fmt_num(n: Any) -> str:
    """20.0 → '20', 20.5 → '20.5'."""
    if n is None:
        return '?'
    try:
        f = float(n)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(n)


def _fmt_dt(date: Any, time: Any) -> str:
    return f'{date} {_fmt_time(time)}'.strip()


class Lookups:
    """Имена сущностей по id (наполняется repository bulk-запросами)."""

    def __init__(self, groups=None, students=None, teachers=None, directions=None):
        self.groups: dict[int, str] = groups or {}
        self.students: dict[int, str] = students or {}
        self.teachers: dict[int, str] = teachers or {}
        self.directions: dict[int, str] = directions or {}

    def group(self, gid) -> str:
        return self.groups.get(_as_int(gid)) or f'группа #{gid}'

    def student(self, sid) -> str:
        return self.students.get(_as_int(sid)) or f'ученик #{sid}'

    def teacher(self, tid) -> str:
        return self.teachers.get(_as_int(tid)) or f'преп. #{tid}'

    def direction(self, did) -> str:
        return self.directions.get(_as_int(did)) or f'направление #{did}'


# Связанная модель pghistory (related_model._meta.label) → атрибут-словарь Lookups.
# Используется humanize._fk_name для показа имени вместо id у любого FK-поля.
_FK_BUCKET = {
    'groups.Group': 'groups',
    'students.Student': 'students',
    'teachers.Teacher': 'teachers',
    'directions.Direction': 'directions',
}

# attname FK-полей → атрибут-словарь Lookups (для сбора id, которые надо разрешить
# в имена: и из снапшота data, и из обеих сторон diff).
_FK_ATTNAME_BUCKET = {
    'group_id': 'groups',
    'student_id': 'students',
    'teacher_id': 'teachers',
    'direction_id': 'directions',
}


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def collect_lookup_ids(events: list[dict]) -> dict[str, set]:
    """Какие имена понадобятся summary/humanize для этой пачки событий."""
    ids: dict[str, set] = {b: set() for b in _FK_ATTNAME_BUCKET.values()}
    for ev in events:
        data = ev.get('pgh_data') or {}
        diff = ev.get('pgh_diff') or {}
        for attname, bucket in _FK_ATTNAME_BUCKET.items():
            v = _as_int(data.get(attname))
            if v is not None:
                ids[bucket].add(v)
            # обе стороны diff: humanize показывает и старое, и новое имя FK
            if attname in diff:
                for side in diff[attname]:
                    sv = _as_int(side)
                    if sv is not None:
                        ids[bucket].add(sv)
    return ids


# ---------------------------------------------------------------------------
# Шаблоны по типам событий
# ---------------------------------------------------------------------------

def _planned_lesson_phrase(ev: dict, lk: Lookups) -> Optional[str]:
    data = ev.get('pgh_data') or {}
    diff = ev.get('pgh_diff') or {}
    group = lk.group(data.get('group_id'))
    num = _fmt_num(data.get('lesson_number'))

    if ev['pgh_label'] == 'insert':
        return f'Доп. занятие {group}: {_fmt_dt(data.get("scheduled_date"), data.get("scheduled_time"))}' \
            if data.get('seq') is None else None  # курсовые insert'ы описывает plan.generate

    if ev['pgh_label'] == 'update':
        if 'scheduled_date' in diff or 'scheduled_time' in diff:
            old_d, new_d = diff.get('scheduled_date', [data.get('scheduled_date')] * 2)
            old_t, new_t = diff.get('scheduled_time', [data.get('scheduled_time')] * 2)
            return (f'Перенос {group} №{num}: '
                    f'{_fmt_dt(old_d, old_t)} → {_fmt_dt(new_d, new_t)}')
        if 'teacher_id' in diff:
            old_t, new_t = diff['teacher_id']
            return (f'Смена преподавателя {group} №{num}: '
                    f'{lk.teacher(old_t)} → {lk.teacher(new_t)}')
        if 'status' in diff:
            old_s, new_s = diff['status']
            return (f'Статус {group} №{num}: '
                    f'{STATUS_RU.get(old_s, old_s)} → {STATUS_RU.get(new_s, new_s)}')
    return None


def _generic_name(data: dict) -> Optional[str]:
    for key in ('name', 'full_name', 'email', 'username'):
        if data.get(key):
            return str(data[key])
    return None


def _generic_phrase(ev: dict, entity_label: str) -> str:
    data = ev.get('pgh_data') or {}
    diff = ev.get('pgh_diff') or {}
    name = _generic_name(data)
    ident = f'«{name}»' if name else f'#{ev.get("pgh_obj_id")}'
    if ev['pgh_label'] == 'update':
        # soft-delete через active=False читаем как удаление/восстановление
        if diff.get('active') == [True, False]:
            return f'{entity_label} {ident}: в архив'
        if diff.get('active') == [False, True]:
            return f'{entity_label} {ident}: восстановление'
        fields = ', '.join(sorted(diff.keys())) or '—'
        return f'{entity_label} {ident}: изменено ({fields})'
    return f'{entity_label} {ident}: {_LABEL_RU[ev["pgh_label"]]}'


_ENTITY_RU = {
    'direction': 'Направление', 'teacher': 'Преподаватель', 'student': 'Ученик',
    'discount': 'Скидка', 'settings': 'Настройки', 'account': 'Учётка',
    'group': 'Группа', 'schedule_slot': 'Слот расписания', 'membership': 'Членство',
    'planned_lesson': 'Плановое занятие', 'lesson': 'Урок',
    'attendance': 'Посещаемость', 'payment': 'Оплата', 'payroll': 'Начисление',
}


# Русские подписи полей для generic-описаний (модалка деталей). Ключи — реальные
# attname трекаемых моделей (registry.py); неизвестные поля показываем как есть.
FIELD_RU = {
    'name': 'название', 'full_name': 'ФИО', 'email': 'email', 'phone': 'телефон',
    'username': 'логин', 'active': 'активность', 'color': 'цвет',
    'sheet_name': 'лист', 'sheet_row': 'строка листа', 'is_individual': 'индивидуальное',
    'birth_date': 'дата рождения', 'age': 'возраст', 'school_grade': 'класс',
    'parent_name': 'родитель', 'pm': 'ПМ', 'platform_id': 'ID платформы',
    'vk_chat': 'VK-чат', 'note': 'комментарий', 'comment': 'комментарий',
    'record_url': 'ссылка на запись',
    'direction': 'направление', 'direction_id': 'направление',
    'teacher': 'преподаватель', 'teacher_id': 'преподаватель',
    'original_teacher': 'исходный преподаватель',
    'group': 'группа', 'group_id': 'группа',
    'student': 'ученик', 'student_id': 'ученик',
    'price': 'цена', 'subscription_price': 'цена абонемента',
    'unit_price': 'цена за единицу', 'total_amount': 'сумма', 'amount': 'сумма',
    'subscriptions_count': 'кол-во абонементов', 'penalty': 'штраф',
    'paid_at': 'дата оплаты', 'first_purchase_date': 'дата первой покупки',
    'duration': 'длительность', 'lesson_duration_minutes': 'длительность',
    'day_of_week': 'день недели', 'start_time': 'время начала',
    'effective_from': 'действует с', 'effective_to': 'действует по',
    'scheduled_date': 'плановая дата', 'scheduled_time': 'плановое время',
    'moved_from_date': 'перенесено с', 'moved_to_date': 'перенесено на',
    'status': 'статус', 'lesson_number': 'номер занятия', 'seq': 'порядковый номер',
    'lesson_date': 'дата урока', 'lesson_type': 'тип урока',
    'lessons_done': 'проведено занятий', 'lessons_per_week': 'занятий в неделю',
    'total_lessons': 'всего занятий', 'remaining': 'осталось',
    'present': 'присутствие', 'present_count': 'присутствовало',
    'total_students': 'всего учеников', 'start_date': 'дата начала',
    'group_start_date': 'дата старта группы',
    'enrollment_status': 'статус зачисления', 'frozen_until_month': 'заморозка до месяца',
    'created_at': 'создано', 'updated_at': 'обновлено',
}


def _fields_ru(keys) -> str:
    """Список изменённых полей русскими подписями (неизвестные — как есть)."""
    return ', '.join(FIELD_RU.get(k, k) for k in sorted(keys)) or '—'


def _describe_generic(ev: dict, entity_label: str) -> str:
    """Фолбэк-описание события: имя записи + русские подписи изменённых полей."""
    data = ev.get('pgh_data') or {}
    diff = ev.get('pgh_diff') or {}
    name = _generic_name(data)
    ident = f'«{name}»' if name else f'#{ev.get("pgh_obj_id")}'
    label = ev['pgh_label']
    if label == 'update':
        if diff.get('active') == [True, False]:
            return f'{entity_label} {ident}: в архив'
        if diff.get('active') == [False, True]:
            return f'{entity_label} {ident}: восстановление'
        return f'{entity_label} {ident}: изменено — {_fields_ru(diff.keys())}'
    return f'{entity_label} {ident}: {_LABEL_RU[label]}'


def describe_event(ev: dict, lk: Lookups) -> str:
    """
    Человекочитаемое описание ОДНОГО события (для модалки деталей).

    ev — dict со структурой ev_rows из repository.get_operation: pgh_label /
    pgh_data / pgh_diff / pgh_obj_id + entity. Никогда не возвращает пустую
    строку: незнакомое событие описывает generic-фолбэком.
    """
    entity = ev.get('entity')
    label = ev['pgh_label']
    data = ev.get('pgh_data') or {}
    diff = ev.get('pgh_diff') or {}

    # --- Плановое занятие ---
    if entity == 'planned_lesson':
        phrase = _planned_lesson_phrase(ev, lk)
        if phrase:
            return phrase
        # курсовой insert (seq не None) _planned_lesson_phrase не описывает
        if label == 'insert':
            group = lk.group(data.get('group_id'))
            num = _fmt_num(data.get('lesson_number'))
            return (f'Занятие {group} №{num}: '
                    f'{_fmt_dt(data.get("scheduled_date"), data.get("scheduled_time"))}')
        return _describe_generic(ev, 'Плановое занятие')

    # --- Урок (факт) ---
    if entity == 'lesson':
        group = lk.group(data.get('group_id'))
        num = _fmt_num(data.get('lesson_number'))
        if label == 'insert':
            return f'Проведён урок {group} №{num} ({data.get("lesson_date")})'
        if label == 'delete':
            return f'Удалён урок {group} №{num} ({data.get("lesson_date")})'
        return f'Урок {group} №{num}: изменено — {_fields_ru(diff.keys())}'

    # --- Посещаемость ---
    if entity == 'attendance':
        student = lk.student(data.get('student_id'))
        if label == 'delete':
            return f'Посещаемость удалена: {student}'
        if label == 'insert':
            state = 'был' if data.get('present') else 'не был'
            return f'Отмечен: {student} — {state}'
        present = diff.get('present')
        if present == [False, True]:
            state = 'был'
        elif present == [True, False]:
            state = 'не был'
        else:
            state = 'был' if data.get('present') else 'не был'
        return f'{student}: {state}'

    # --- Оплата ---
    if entity == 'payment':
        student = lk.student(data.get('student_id'))
        amount = _fmt_num(data.get('total_amount'))
        if label == 'delete':
            return f'Удалена оплата {amount} ₽: {student}'
        if label == 'insert':
            return f'Оплата {amount} ₽: {student}'
        return f'Оплата {student}: изменено — {_fields_ru(diff.keys())}'

    # --- Членство ---
    if entity == 'membership':
        student = lk.student(data.get('student_id'))
        group = lk.group(data.get('group_id'))
        if label == 'insert':
            return f'Зачисление: {student} → {group}'
        if label == 'delete':
            return f'Отчисление: {student} из {group}'
        return _describe_generic(ev, 'Членство')

    # --- Всё остальное: имя записи + русские подписи полей ---
    return _describe_generic(ev, _ENTITY_RU.get(entity, entity or 'Запись'))


def build_summary(operation: str, events: list[dict], lk: Lookups) -> str:
    """Описание операции по её событиям. events — dict'ы из Events.values()."""
    if not events:
        return 'Без изменений данных'

    by_entity: dict[str, list[dict]] = {}
    for ev in events:
        by_entity.setdefault(ev['entity'], []).append(ev)

    # --- Планирование занятий ---
    planned = by_entity.get('planned_lesson', [])
    if operation == 'plan.generate' and planned:
        inserts = sum(1 for e in planned if e['pgh_label'] == 'insert')
        group = lk.group((planned[0].get('pgh_data') or {}).get('group_id'))
        return f'План {group}: создано занятий — {inserts}'
    if operation == 'plan.permanent_change' and planned:
        group = lk.group((planned[0].get('pgh_data') or {}).get('group_id'))
        return f'Смена расписания {group}: занятий изменено — {len(planned)}'
    if planned:
        # перенос/отмена/смена препода/статус — описываем самым значимым событием
        for ev in planned:
            phrase = _planned_lesson_phrase(ev, lk)
            if phrase:
                if operation == 'plan.cancel' and 'Статус' in phrase:
                    data = ev.get('pgh_data') or {}
                    group = lk.group(data.get('group_id'))
                    num = _fmt_num(data.get('lesson_number'))
                    return (f'Отмена занятия {group} №{num} '
                            f'({_fmt_dt(data.get("scheduled_date"), data.get("scheduled_time"))})')
                return phrase

    # --- Уроки (факты) ---
    lessons = by_entity.get('lesson', [])
    if lessons:
        ev = lessons[0]
        data = ev.get('pgh_data') or {}
        group = lk.group(data.get('group_id'))
        num = _fmt_num(data.get('lesson_number'))
        att = by_entity.get('attendance', [])
        if ev['pgh_label'] == 'insert':
            present = sum(1 for a in att if (a.get('pgh_data') or {}).get('present'))
            tail = f': отмечено {present} из {len(att)}' if att else ''
            return f'Проведён урок {group} №{num} ({data.get("lesson_date")}){tail}'
        if ev['pgh_label'] == 'delete':
            return f'Удалён урок {group} №{num} ({data.get("lesson_date")})'
        diff = ev.get('pgh_diff') or {}
        return f'Урок {group} №{num}: изменено ({", ".join(sorted(diff.keys()))})'

    # --- Правка посещаемости (без урока в контексте) ---
    att = by_entity.get('attendance', [])
    if att and operation == 'lesson.attendance_update':
        data = att[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        present = (att[0].get('pgh_diff') or {}).get('present')
        arrow = ' → был' if present == [False, True] else (' → не был' if present == [True, False] else '')
        return f'Посещаемость: {student}{arrow}'

    # --- Членства ---
    memberships = by_entity.get('membership', [])
    if memberships and operation.startswith('membership.'):
        data = memberships[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        group = lk.group(data.get('group_id'))
        if operation == 'membership.create':
            return f'Зачисление: {student} → {group}'
        if operation == 'membership.delete':
            return f'Отчисление: {student} из {group}'
        return _generic_phrase(memberships[0], 'Членство')

    # --- Оплаты ---
    payments = by_entity.get('payment', [])
    if payments:
        data = payments[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        amount = data.get('total_amount')
        verb = 'Удалена оплата' if payments[0]['pgh_label'] == 'delete' else 'Оплата'
        return f'{verb} {amount} ₽: {student}'

    # --- Откат ---
    if operation == 'changelog.revert':
        return f'Откат операции: отменено изменений — {len(events)}'

    # --- Generic: первое событие + счётчик остальных ---
    ev = events[0]
    phrase = _generic_phrase(ev, _ENTITY_RU.get(ev['entity'], ev['entity']))
    if len(events) > 1:
        phrase += f' (+ ещё изменений: {len(events) - 1})'
    return phrase
