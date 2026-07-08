"""
Импорт истории направлений учеников из внешней таблицы «Переходимость по курсам».

Парсинг/классификация/агрегация — чистые функции (без БД), легко тестируемые.
import_to_db() — единственная функция с побочными эффектами (пишет в БД).

См. docs/superpowers/specs/2026-07-08-direction-history-import-design.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SHEET_NAME = 'Переходимость по курсам'
ARCHIVE_TEACHER_NAME = 'Архив (импорт истории)'
LEGACY_LESSON_DATE = '2023-01-01'

# Статусы «Переход N», которые означают, что направление ЗАВЕРШЕНО и переносится в архив.
STATUS_ARCHIVE = {
    'Закончил и перешёл',
    'Недоучился и перешёл',
    'Ожидание перехода',
    'Отказ',
}
# Статус «Продолжает учиться» — точное совпадение; «Заморозка*» — по префиксу
# (в таблице встречаются варианты «Заморозка Сентябрь», «Заморозка Июль» и т.п.).
STATUS_SKIP_CURRENT_EXACT = {'Продолжает учиться'}


def is_skip_current(status: str) -> bool:
    """Статус означает «направление ещё текущее» — не архивируем, не считаем ошибкой."""
    return status in STATUS_SKIP_CURRENT_EXACT or status.startswith('Заморозка')


# Порядок важен только визуально — паттерны не пересекаются по смыслу.
_COURSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'питон|python', re.I), 'Python'),
    (re.compile(r'роблокс|roblox', re.I), 'Roblox Группа'),
    (re.compile(r'скретч|scratch', re.I), 'Scratch'),
    (re.compile(r'майнкрафт|minecraft', re.I), 'Minecraft'),
    (re.compile(r'блендер|blender', re.I), 'Blender'),
    (re.compile(r'веб-дизайн', re.I), 'Веб-дизайн'),
    (re.compile(r'веб-разработка|web-разработка', re.I), 'Web-разработка'),
]


def normalize_course_name(raw: str | None) -> str | None:
    """
    Сырое название курса из таблицы -> каноничное имя направления в системе.

    Всегда возвращает ГРУППОВУЮ версию направления, даже если в исходном названии
    явно написано «ИНДИВ» — приписки (Старый/ИНДИВ/Особые Условия/N уроков)
    игнорируются по решению пользователя (см. спеку, раздел «Нормализация»).
    None, если ни один паттерн не подошёл (нераспознанный курс).
    """
    text = (raw or '').strip()
    if not text:
        return None
    for pattern, canonical in _COURSE_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


@dataclass
class TransitionSlot:
    course_raw: str
    lessons: int
    status: str


@dataclass
class StudentRow:
    full_name: str
    transitions: list[TransitionSlot]


# 0-indexed колонка «Курс» для каждого слота «Переход N» (лессонс/месяцев/статус —
# следующие 3 колонки подряд). До 6 слотов в реальном файле, но парсер не ограничивает
# их число жёстко — читает все группы по 4 колонки начиная с индекса 3.
_SLOT_START_COLUMNS = [3, 7, 11, 15, 19, 23]


def parse_sheet(path: str) -> list[StudentRow]:
    """
    Читает лист SHEET_NAME файла path. Строки 1-2 (1-indexed) — заголовки
    (групповые + колоночные), данные — с 3-й строки. Строка без ФИ (col A) —
    пропускается (хвостовые пустые шаблонные строки в реальном файле).
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[SHEET_NAME]

        rows: list[StudentRow] = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            full_name_raw = row[0] if len(row) > 0 else None
            if full_name_raw is None or str(full_name_raw).strip() == '':
                continue

            transitions: list[TransitionSlot] = []
            for start in _SLOT_START_COLUMNS:
                course = row[start] if start < len(row) else None
                lessons_raw = row[start + 1] if start + 1 < len(row) else None
                status_raw = row[start + 3] if start + 3 < len(row) else None
                if course is None or lessons_raw is None:
                    continue
                try:
                    lessons = int(round(float(lessons_raw)))
                except (TypeError, ValueError):
                    continue
                if lessons <= 0:
                    continue
                transitions.append(TransitionSlot(
                    course_raw=str(course), lessons=lessons, status=str(status_raw or ''),
                ))

            if transitions:
                rows.append(StudentRow(full_name=str(full_name_raw).strip(), transitions=transitions))

        return rows
    finally:
        wb.close()


@dataclass
class SkipRecord:
    full_name: str
    course_raw: str
    status: str


@dataclass
class UnrecognizedStatusRecord:
    full_name: str
    course_raw: str
    status: str


@dataclass
class UnmatchedCourseRecord:
    full_name: str
    course_raw: str


def classify_and_aggregate(
    rows: list[StudentRow],
) -> tuple[
    dict[tuple[str, str], int],
    list[SkipRecord],
    list[UnrecognizedStatusRecord],
    list[UnmatchedCourseRecord],
]:
    """
    Классифицирует и суммирует слоты «Переход N» по всем ученикам.

    Возвращает:
      aggregated: {(full_name, direction_name): сумма_уроков} — только архивируемые
      skipped: слоты со статусом «текущее направление» (осознанный пропуск)
      unrecognized: слоты с нераспознанным статусом (пропуск + нужен отчёт)
      unmatched: слоты с нераспознанным названием курса (пропуск + нужен отчёт)
    """
    aggregated: dict[tuple[str, str], int] = {}
    skipped: list[SkipRecord] = []
    unrecognized: list[UnrecognizedStatusRecord] = []
    unmatched: list[UnmatchedCourseRecord] = []

    for row in rows:
        for slot in row.transitions:
            if is_skip_current(slot.status):
                skipped.append(SkipRecord(row.full_name, slot.course_raw, slot.status))
                continue
            if slot.status not in STATUS_ARCHIVE:
                unrecognized.append(UnrecognizedStatusRecord(row.full_name, slot.course_raw, slot.status))
                continue
            direction_name = normalize_course_name(slot.course_raw)
            if direction_name is None:
                unmatched.append(UnmatchedCourseRecord(row.full_name, slot.course_raw))
                continue
            key = (row.full_name, direction_name)
            aggregated[key] = aggregated.get(key, 0) + slot.lessons

    return aggregated, skipped, unrecognized, unmatched


@dataclass
class ImportReport:
    dry_run: bool
    total_pairs: int = 0
    imported_pairs: int = 0
    lessons_written: int = 0
    already_imported: int = 0
    unmatched_students: list = field(default_factory=list)
    unmatched_directions_in_db: list = field(default_factory=list)
    idempotency_anomalies: list = field(default_factory=list)


def import_to_db(aggregated: dict, *, dry_run: bool) -> ImportReport:
    """
    Пишет архивные группы/уроки/посещения/членства по агрегированным парам
    (ФИ ученика, имя направления) -> сумма уроков.

    Идемпотентно: для пары с уже записанными N уроками (по submitted_by_token)
    — пропуск (already_imported). Если записано другое количество — не трогаем,
    в idempotency_anomalies (нужна ручная проверка).
    """
    from django.db import transaction
    from django.utils import timezone

    from apps.directions.models import Direction
    from apps.groups.models import Group
    from apps.lessons.models import Lesson, LessonAttendance
    from apps.memberships.models import GroupMembership
    from apps.students.models import Student
    from apps.teachers.models import Teacher

    report = ImportReport(dry_run=dry_run, total_pairs=len(aggregated))

    teacher = None
    if not dry_run:
        teacher, _ = Teacher.objects.get_or_create(
            name=ARCHIVE_TEACHER_NAME, defaults={'created_at': timezone.now()},
        )

    group_cache: dict[int, Group] = {}

    for (full_name, direction_name), lessons_count in aggregated.items():
        student = Student.objects.filter(full_name=full_name).first()
        if student is None:
            report.unmatched_students.append(full_name)
            continue

        direction = Direction.objects.filter(name=direction_name).first()
        if direction is None:
            report.unmatched_directions_in_db.append(
                f'{full_name}: направление «{direction_name}» не найдено в БД'
            )
            continue

        token = f'legacy-import:{student.id}:{direction.id}'
        existing = Lesson.objects.filter(submitted_by_token=token).count()

        if existing == lessons_count:
            report.already_imported += 1
            continue
        if existing:
            report.idempotency_anomalies.append(
                f'{full_name} / {direction_name}: в БД {existing} уроков, ожидалось {lessons_count}'
            )
            continue

        if dry_run:
            report.imported_pairs += 1
            report.lessons_written += lessons_count
            continue

        with transaction.atomic():
            group = group_cache.get(direction.id)
            if group is None:
                group, _ = Group.objects.get_or_create(
                    name=f'{direction.name} — архив',
                    defaults={
                        'direction': direction, 'teacher': teacher, 'active': False,
                        'is_individual': False, 'lesson_duration_minutes': 60,
                        'lessons_per_week': 1, 'created_at': timezone.now(),
                    },
                )
                group_cache[direction.id] = group

            lesson_ids = []
            for n in range(1, lessons_count + 1):
                lesson = Lesson.objects.create(
                    group=group, teacher=teacher, lesson_date=LEGACY_LESSON_DATE,
                    lesson_number=n, lesson_duration_minutes=60, lesson_type='regular',
                    submitted_at=timezone.now(), submitted_by_token=token,
                )
                lesson_ids.append(lesson.id)

            LessonAttendance.objects.bulk_create([
                LessonAttendance(lesson_id=lid, student=student, present=True)
                for lid in lesson_ids
            ])

            GroupMembership.objects.update_or_create(
                group=group, student=student,
                defaults={
                    'lessons_done': lessons_count, 'remaining': 0,
                    'active': False, 'start_date': LEGACY_LESSON_DATE,
                },
            )

        report.imported_pairs += 1
        report.lessons_written += lessons_count

    return report
