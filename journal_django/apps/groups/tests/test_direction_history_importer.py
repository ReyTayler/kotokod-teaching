"""
Тесты импортёра истории направлений (apps/groups/importers/direction_history.py).

normalize_course_name / classify_and_aggregate — чистые функции, без БД.
parse_sheet — читает синтетический .xlsx (без сети/реального файла школы).
import_to_db — интеграционные тесты, реальная БД (managed=False, journal_test).
"""
from __future__ import annotations

import pytest

from apps.groups.importers.direction_history import normalize_course_name


@pytest.mark.parametrize('raw,expected', [
    ('Питон', 'Python'),
    ('Питон 52 урока', 'Python'),
    ('Питон Старый (16 ур)', 'Python'),
    ('Питон Старый (32 урока)', 'Python'),
    ('Python', 'Python'),
    ('Python ИНДИВ', 'Python'),
    ('Роблокс', 'Roblox Группа'),
    ('Роблокс Старый (16 ур)', 'Roblox Группа'),
    ('Роблокс Особые Условия', 'Roblox Группа'),
    ('Roblox ИНДИВ', 'Roblox Группа'),
    ('Скретч', 'Scratch'),
    ('Скретч Старый (16 ур)', 'Scratch'),
    ('Майнкрафт', 'Minecraft'),
    ('Блендер', 'Blender'),
    ('Веб-дизайн', 'Веб-дизайн'),
    ('Веб-дизайн ИНДИВ', 'Веб-дизайн'),
    ('Веб-дизайн Особые Условия', 'Веб-дизайн'),
    ('Веб-разработка', 'Web-разработка'),
])
def test_normalize_course_name_maps_to_canonical_direction(raw, expected):
    assert normalize_course_name(raw) == expected


def test_normalize_course_name_unrecognized_returns_none():
    assert normalize_course_name('Плавание') is None
    assert normalize_course_name('') is None
    assert normalize_course_name(None) is None


def _build_test_workbook(path):
    """Синтетический .xlsx, повторяющий структуру реального листа «Переходимость по курсам»:
    строка 1 — групповые заголовки «Переход N», строка 2 — заголовки колонок,
    строка 3+ — данные. Хвостовая пустая строка должна отфильтровываться."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'

    ws.append([None, None, None, 'Переход 1', None, None, None, 'Переход 2', None, None, None])
    ws.append([
        'ФИ РЕБ', 'Сколько отзанимался', None,
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
    ])
    ws.append([
        'Иванов Пётр', 45, None,
        'Питон', 32, 8, 'Закончил и перешёл',
        'Роблокс', 13, 3.25, 'Продолжает учиться',
    ])
    ws.append([
        'Сидорова Анна', 20, None,
        'Скретч', 20, 5, 'Заморозка Сентябрь',
        None, None, 0, None,
    ])
    # Хвостовая «пустая» строка — как в реальном файле (шаблон без ученика).
    ws.append([None, 0, 0.0, None, None, 0, None, None, None, 0, None])

    wb.save(path)


def test_parse_sheet_reads_students_and_filters_empty_rows(tmp_path):
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test.xlsx'
    _build_test_workbook(path)

    rows = parse_sheet(str(path))

    assert len(rows) == 2

    ivanov = rows[0]
    assert ivanov.full_name == 'Иванов Пётр'
    assert len(ivanov.transitions) == 2
    assert ivanov.transitions[0].course_raw == 'Питон'
    assert ivanov.transitions[0].lessons == 32
    assert ivanov.transitions[0].status == 'Закончил и перешёл'
    assert ivanov.transitions[1].course_raw == 'Роблокс'
    assert ivanov.transitions[1].lessons == 13
    assert ivanov.transitions[1].status == 'Продолжает учиться'

    sidorova = rows[1]
    assert sidorova.full_name == 'Сидорова Анна'
    # Второй слот пуст (course=None) -> не попадает в transitions.
    assert len(sidorova.transitions) == 1
    assert sidorova.transitions[0].course_raw == 'Скретч'
    assert sidorova.transitions[0].lessons == 20
    assert sidorova.transitions[0].status == 'Заморозка Сентябрь'


def test_parse_sheet_strips_whitespace_from_full_name(tmp_path):
    import openpyxl
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test2.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'
    ws.append([None, None, None, 'Переход 1', None, None, None])
    ws.append(['ФИ РЕБ', 'Сколько отзанимался', None, 'Курс', 'прошёл ур', 'месяцев', 'Статус перехода'])
    ws.append(['  Петров Иван  ', 10, None, 'Питон', 10, 2.5, 'Отказ'])
    wb.save(path)

    rows = parse_sheet(str(path))
    assert rows[0].full_name == 'Петров Иван'


def _row(full_name, *slots):
    """slots: list of (course_raw, lessons, status) tuples."""
    from apps.groups.importers.direction_history import StudentRow, TransitionSlot
    return StudentRow(
        full_name=full_name,
        transitions=[TransitionSlot(course_raw=c, lessons=n, status=s) for c, n, s in slots],
    )


def test_classify_and_aggregate_sums_repeated_direction():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [
        _row(
            'Столярова Анастасия',
            ('Питон', 20, 'Закончил и перешёл'),
            ('Веб-разработка', 15, 'Продолжает учиться'),
            ('Питон', 10, 'Ожидание перехода'),  # повторный заход на то же направление
        ),
    ]

    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated[('Столярова Анастасия', 'Python')] == 30
    assert ('Столярова Анастасия', 'Web-разработка') not in aggregated
    assert len(skipped) == 1
    assert skipped[0].course_raw == 'Веб-разработка'
    assert unrecognized == []
    assert unmatched == []


def test_classify_and_aggregate_skips_current_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Продолжает учиться'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1
    assert skipped[0].full_name == 'Иванов Пётр'
    assert skipped[0].status == 'Продолжает учиться'


def test_classify_and_aggregate_skips_frozen_status_variants():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Заморозка Сентябрь'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1


def test_classify_and_aggregate_reports_unrecognized_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Кокорин Владимир', ('Веб-дизайн', 12, 'Что с ним'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert skipped == []
    assert len(unrecognized) == 1
    assert unrecognized[0].full_name == 'Кокорин Владимир'
    assert unrecognized[0].status == 'Что с ним'


def test_classify_and_aggregate_reports_unmatched_course_name():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Петров Иван', ('Плавание', 8, 'Закончил и перешёл'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(unmatched) == 1
    assert unmatched[0].full_name == 'Петров Иван'
    assert unmatched[0].course_raw == 'Плавание'


# ---------------------------------------------------------------------------
# import_to_db — интеграционные тесты (реальная БД, managed=False)
# ---------------------------------------------------------------------------

from django.db import connection


def _make_student(full_name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) VALUES (%s, 'enrolled') RETURNING id",
            [full_name],
        )
        return cur.fetchone()[0]


def _make_direction(name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, sheet_name, is_individual, active) "
            "VALUES (%s, %s, false, true) RETURNING id",
            [name, f'__sheet_{name}__'],
        )
        return cur.fetchone()[0]


def _cleanup_import(student_id=None, direction_id=None):
    with connection.cursor() as cur:
        if direction_id is not None:
            cur.execute(
                "SELECT id FROM groups WHERE direction_id = %s", [direction_id],
            )
            group_ids = [r[0] for r in cur.fetchall()]
            for gid in group_ids:
                cur.execute("DELETE FROM lesson_attendance WHERE lesson_id IN "
                            "(SELECT id FROM lessons WHERE group_id = %s)", [gid])
                cur.execute("DELETE FROM group_memberships WHERE group_id = %s", [gid])
                cur.execute("DELETE FROM lessons WHERE group_id = %s", [gid])
            cur.execute("DELETE FROM groups WHERE direction_id = %s", [direction_id])
            cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
        if student_id is not None:
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])


@pytest.fixture
def import_teacher_cleanup():
    """Удаляет служебного 'Архив (импорт истории)' учителя после теста, если он появился."""
    yield
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM teachers WHERE name = 'Архив (импорт истории)' "
            "AND id NOT IN (SELECT DISTINCT teacher_id FROM groups)"
        )


@pytest.mark.django_db
class TestImportToDb:

    def test_creates_teacher_group_lessons_attendance_membership(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_1__')
        did = _make_direction('__import_test_direction_1__')
        try:
            aggregated = {('__import_test_student_1__', '__import_test_direction_1__'): 5}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 1
            assert report.lessons_written == 5
            assert report.already_imported == 0
            assert report.unmatched_students == []

            with connection.cursor() as cur:
                cur.execute("SELECT id FROM teachers WHERE name = 'Архив (импорт истории)'")
                teacher_row = cur.fetchone()
                assert teacher_row is not None

                cur.execute(
                    "SELECT id, active, teacher_id FROM groups WHERE direction_id = %s", [did],
                )
                group_row = cur.fetchone()
                assert group_row is not None
                gid, active, teacher_id = group_row
                assert active is False
                assert teacher_id == teacher_row[0]

                cur.execute("SELECT COUNT(*) FROM lessons WHERE group_id = %s", [gid])
                assert cur.fetchone()[0] == 5

                cur.execute(
                    "SELECT COUNT(*) FROM lesson_attendance la JOIN lessons l ON l.id = la.lesson_id "
                    "WHERE l.group_id = %s AND la.student_id = %s AND la.present = true",
                    [gid, sid],
                )
                assert cur.fetchone()[0] == 5

                cur.execute(
                    "SELECT lessons_done, active FROM group_memberships WHERE group_id = %s AND student_id = %s",
                    [gid, sid],
                )
                membership = cur.fetchone()
                assert membership == (5, False)
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_dry_run_writes_nothing(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_2__')
        did = _make_direction('__import_test_direction_2__')
        try:
            aggregated = {('__import_test_student_2__', '__import_test_direction_2__'): 3}
            report = import_to_db(aggregated, dry_run=True)

            assert report.imported_pairs == 1
            assert report.lessons_written == 3

            with connection.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM groups WHERE direction_id = %s", [did])
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT COUNT(*) FROM teachers WHERE name = 'Архив (импорт истории)'")
                assert cur.fetchone()[0] == 0
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_rerun_is_idempotent_noop(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_3__')
        did = _make_direction('__import_test_direction_3__')
        try:
            aggregated = {('__import_test_student_3__', '__import_test_direction_3__'): 4}
            import_to_db(aggregated, dry_run=False)

            report2 = import_to_db(aggregated, dry_run=False)
            assert report2.imported_pairs == 0
            assert report2.already_imported == 1

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 4  # не задвоилось
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_unmatched_student_is_reported_and_skipped(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        did = _make_direction('__import_test_direction_4__')
        try:
            aggregated = {('__nonexistent_student_xyz__', '__import_test_direction_4__'): 2}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 0
            assert '__nonexistent_student_xyz__' in report.unmatched_students

            with connection.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM groups WHERE direction_id = %s", [did])
                assert cur.fetchone()[0] == 0
        finally:
            _cleanup_import(direction_id=did)

    def test_unmatched_direction_is_reported_and_skipped(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_5__')
        try:
            aggregated = {('__import_test_student_5__', '__nonexistent_direction_xyz__'): 2}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 0
            assert any('__nonexistent_direction_xyz__' in s for s in report.unmatched_directions_in_db)
        finally:
            _cleanup_import(student_id=sid)

    def test_idempotency_anomaly_when_count_mismatches(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_6__')
        did = _make_direction('__import_test_direction_6__')
        try:
            import_to_db({('__import_test_student_6__', '__import_test_direction_6__'): 4}, dry_run=False)

            # Другое ожидаемое количество для той же пары -> не совпадает с уже записанными 4.
            report = import_to_db(
                {('__import_test_student_6__', '__import_test_direction_6__'): 7}, dry_run=False,
            )
            assert report.imported_pairs == 0
            assert report.already_imported == 0
            assert len(report.idempotency_anomalies) == 1

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 4  # не тронуто
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_one_pair_failure_does_not_abort_run(self, import_teacher_cleanup):
        """
        Пара, упавшая с неожиданным исключением при записи (например обрыв
        соединения/constraint-конфликт), не должна прерывать весь прогон и
        обнулять счётчики уже обработанных пар. Исключение имитируется через
        patch на GroupMembership.objects.update_or_create — единственный вызов
        внутри per-pair atomic-блока, который срабатывает последним, поэтому
        его отказ откатывает только записи «плохой» пары (Lesson/LessonAttendance),
        не трогая уже закоммиченную «хорошую» пару.
        """
        from unittest.mock import patch

        from apps.groups.importers.direction_history import import_to_db
        from apps.memberships.models import GroupMembership

        sid_good = _make_student('__import_test_student_7_good__')
        sid_bad = _make_student('__import_test_student_7_bad__')
        did = _make_direction('__import_test_direction_7__')
        try:
            aggregated = {
                ('__import_test_student_7_good__', '__import_test_direction_7__'): 3,
                ('__import_test_student_7_bad__', '__import_test_direction_7__'): 2,
            }

            original_update_or_create = GroupMembership.objects.update_or_create

            def flaky_update_or_create(*args, **kwargs):
                student = kwargs.get('student')
                if student is not None and student.full_name == '__import_test_student_7_bad__':
                    raise RuntimeError('simulated failure for bad pair')
                return original_update_or_create(*args, **kwargs)

            with patch.object(
                GroupMembership.objects, 'update_or_create', side_effect=flaky_update_or_create,
            ):
                report = import_to_db(aggregated, dry_run=False)

            # Хорошая пара обработана и учтена в отчёте несмотря на падение соседней.
            assert report.imported_pairs == 1
            assert report.lessons_written == 3
            assert len(report.failed_pairs) == 1
            assert '__import_test_student_7_bad__' in report.failed_pairs[0]

            with connection.cursor() as cur:
                # Только уроки «хорошей» пары — «плохая» откатилась целиком (atomic).
                cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 3

                cur.execute(
                    "SELECT COUNT(*) FROM group_memberships WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 1
        finally:
            _cleanup_import(student_id=sid_good, direction_id=did)
            _cleanup_import(student_id=sid_bad)


@pytest.mark.django_db
def test_command_dry_run_smoke(tmp_path, capsys):
    """Команда читает файл, ничего не пишет в БД в --dry-run, печатает отчёт."""
    from django.core.management import call_command

    path = tmp_path / 'smoke.xlsx'
    _build_test_workbook(path)

    call_command('import_direction_history', str(path), '--dry-run')

    captured = capsys.readouterr()
    assert 'DRY-RUN' in captured.out
    assert 'Учеников в листе' in captured.out


# ---------------------------------------------------------------------------
# verify_active_enrollments — read-only сверка «текущее» ↔ платформа
# ---------------------------------------------------------------------------

def _make_group(direction_id, teacher_id, name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES (%s, %s, %s, false, 60, true) RETURNING id",
            [name, direction_id, teacher_id],
        )
        return cur.fetchone()[0]


def _make_membership(group_id, student_id, active=True):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active) "
            "VALUES (%s, %s, 0, 0, %s) RETURNING id",
            [group_id, student_id, active],
        )
        return cur.fetchone()[0]


def _get_teacher_id():
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No teachers in DB — skipping verify_active_enrollments tests')
    return row[0]


def _cleanup_verify(student_id=None, direction_id=None, group_id=None, membership_id=None):
    with connection.cursor() as cur:
        if membership_id is not None:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
        if group_id is not None:
            cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
        if direction_id is not None:
            cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
        if student_id is not None:
            cur.execute('DELETE FROM students WHERE id = %s', [student_id])


@pytest.mark.django_db
class TestVerifyActiveEnrollments:

    def test_active_membership_is_not_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        teacher_id = _get_teacher_id()
        sid = _make_student('__verify_active_student_1__')
        did = _make_direction('Python')  # совпадает с normalize_course_name('Питон')
        gid = _make_group(did, teacher_id, '__verify_active_group_1__')
        mid = _make_membership(gid, sid, active=True)
        try:
            skipped = [SkipRecord('__verify_active_student_1__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert mismatches == []
        finally:
            _cleanup_verify(student_id=sid, direction_id=did, group_id=gid, membership_id=mid)

    def test_no_active_membership_is_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_2__')
        did = _make_direction('Python')
        try:
            skipped = [SkipRecord('__verify_active_student_2__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
            assert mismatches[0].full_name == '__verify_active_student_2__'
            assert mismatches[0].direction_name == 'Python'
        finally:
            _cleanup_verify(student_id=sid, direction_id=did)

    def test_inactive_membership_is_a_mismatch(self):
        """active=False membership не считается — ребёнок формально не на направлении сейчас."""
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        teacher_id = _get_teacher_id()
        sid = _make_student('__verify_active_student_3__')
        did = _make_direction('Python')
        gid = _make_group(did, teacher_id, '__verify_active_group_3__')
        mid = _make_membership(gid, sid, active=False)
        try:
            skipped = [SkipRecord('__verify_active_student_3__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
        finally:
            _cleanup_verify(student_id=sid, direction_id=did, group_id=gid, membership_id=mid)

    def test_frozen_status_is_not_checked(self):
        """«Заморозка*» не проверяется вообще — это статус ученика, не направления."""
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_5__')
        try:
            # Нет ни группы, ни членства — но статус «Заморозка» должен быть
            # полностью проигнорирован, а не считаться расхождением.
            skipped = [SkipRecord('__verify_active_student_5__', 'Питон', 'Заморозка Сентябрь')]
            mismatches = verify_active_enrollments(skipped)
            assert mismatches == []
        finally:
            _cleanup_verify(student_id=sid)

    def test_unmatched_student_is_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        skipped = [SkipRecord('__nonexistent_verify_student__', 'Питон', 'Продолжает учиться')]
        mismatches = verify_active_enrollments(skipped)
        assert len(mismatches) == 1
        assert mismatches[0].full_name == '__nonexistent_verify_student__'

    def test_unrecognized_course_is_a_mismatch_with_none_direction(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_4__')
        try:
            skipped = [SkipRecord('__verify_active_student_4__', 'Плавание', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
            assert mismatches[0].direction_name is None
        finally:
            _cleanup_verify(student_id=sid)


@pytest.mark.django_db
def test_command_reports_active_enrollment_mismatches(tmp_path, capsys):
    """Команда печатает секцию расхождений «текущее» ↔ платформа для непроверенных детей."""
    from django.core.management import call_command

    path = tmp_path / 'mismatch.xlsx'
    _build_test_workbook(path)  # Иванов Пётр: Роблокс/«Продолжает учиться», нет такого ученика в БД

    call_command('import_direction_history', str(path), '--dry-run')

    captured = capsys.readouterr()
    assert 'текущее' in captured.out.lower() or 'расхожден' in captured.out.lower()
    assert 'Иванов Пётр' in captured.out
