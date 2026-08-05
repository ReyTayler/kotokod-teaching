"""
Тесты «Отчёта по переходимости» (apps.reports.builders.retention).

Как и остальные тесты reports, идут по свежей мигрированной test_journal_test
(django_db_setup НЕ переопределён — см. conftest.py пакета).
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.reports.builders import retention


@pytest.fixture
def world(renewals_fixture):
    """Мир отчёта: направления, преподаватели, группы, ученики, членства.

    Возвращает фабрики поверх renewals_fixture — сделки создаём его методами,
    а обвязку (кто у кого учится) своими: она отчёту и нужна.
    """
    created = {'membership': [], 'group': [], 'teacher': [], 'direction': []}

    class W:
        def __init__(self, base):
            self.base = base
            self.pipeline = base.pipeline()
            self.won = base.stage(self.pipeline, 'renewed', 'Продлён', 'won', sort_order=9)
            self.lost = base.stage(self.pipeline, 'churned', 'Ушёл', 'lost', sort_order=10)
            self.open = base.stage(self.pipeline, 'awaiting_renewal', 'Ждём продление',
                                   'decision', sort_order=5)

        def teacher(self, name, is_service=False):
            with connection.cursor() as cur:
                cur.execute(
                    'INSERT INTO teachers (name, active, is_service, created_at) '
                    'VALUES (%s, true, %s, now()) RETURNING id', [name, is_service])
                tid = cur.fetchone()[0]
            created['teacher'].append(tid)
            return tid

        def direction(self, name):
            with connection.cursor() as cur:
                cur.execute(
                    'INSERT INTO directions (name, total_lessons, active) '
                    'VALUES (%s, 36, true) RETURNING id', [name])
                did = cur.fetchone()[0]
            created['direction'].append(did)
            return did

        def group(self, name, teacher_id, direction_id, active=True):
            with connection.cursor() as cur:
                cur.execute(
                    'INSERT INTO groups (name, direction_id, teacher_id, is_individual, '
                    'lesson_duration_minutes, active, lesson_number_offset) '
                    'VALUES (%s, %s, %s, false, 90, %s, 0) RETURNING id',
                    [name, direction_id, teacher_id, active])
                gid = cur.fetchone()[0]
            created['group'].append(gid)
            return gid

        def enrol(self, group_id, student_id, active=True):
            with connection.cursor() as cur:
                cur.execute(
                    'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                    'VALUES (%s, %s, 0, %s) RETURNING id', [group_id, student_id, active])
                created['membership'].append(cur.fetchone()[0])

        @staticmethod
        def days_ago(days: int) -> datetime.date:
            """Опорная дата открытой сделки в прошлом — так проверяется «застряло»."""
            return datetime.date.today() - datetime.timedelta(days=days)

    yield W(renewals_fixture)

    with connection.cursor() as cur:
        for mid in created['membership']:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [mid])
        for gid in created['group']:
            cur.execute('DELETE FROM groups WHERE id = %s', [gid])
        for tid in created['teacher']:
            cur.execute('DELETE FROM teachers WHERE id = %s', [tid])
        for did in created['direction']:
            cur.execute('DELETE FROM directions WHERE id = %s', [did])


def _row(rows: list[dict], name: str) -> dict:
    return next(r for r in rows if r['name'] == name)


@pytest.mark.django_db
def test_deal_counted_for_teacher_of_students_group(world, renewals_fixture):
    teacher = world.teacher('__ret_teacher__')
    direction = world.direction('__ret_dir__')
    group = world.group('__ret_group__', teacher, direction)
    student = renewals_fixture.student('__ret_student__')
    world.enrol(group, student)
    renewals_fixture.deal(student, world.pipeline, world.won, 1, closed_at='2026-07-15')

    data = retention.collect()
    row = _row(data['teachers'], '__ret_teacher__')

    assert row['students'] == 1
    assert row['won'] == 1
    assert row['lost'] == 0
    assert row['pct'] == 100


@pytest.mark.django_db
def test_student_of_two_teachers_counts_for_both(world, renewals_fixture):
    """Осознанная неэксклюзивность: сделка привязана к ученику, а не к группе,
    поэтому разделить её между преподавателями данные не позволяют."""
    t1 = world.teacher('__ret_t1__')
    t2 = world.teacher('__ret_t2__')
    direction = world.direction('__ret_dir_two__')
    student = renewals_fixture.student('__ret_student_two__')
    world.enrol(world.group('__ret_g1__', t1, direction), student)
    world.enrol(world.group('__ret_g2__', t2, direction), student)
    renewals_fixture.deal(student, world.pipeline, world.won, 1, closed_at='2026-07-15')

    data = retention.collect()

    assert _row(data['teachers'], '__ret_t1__')['won'] == 1
    assert _row(data['teachers'], '__ret_t2__')['won'] == 1


@pytest.mark.django_db
def test_former_student_still_counted(world, renewals_fixture):
    """Неактивное членство и архивная группа считаются: ушедший ученик — часть
    истории переходимости, иначе показываем только выживших."""
    teacher = world.teacher('__ret_t_former__')
    direction = world.direction('__ret_dir_former__')
    group = world.group('__ret_g_former__', teacher, direction, active=False)
    student = renewals_fixture.student('__ret_student_former__')
    world.enrol(group, student, active=False)
    renewals_fixture.deal(student, world.pipeline, world.lost, 1, closed_at='2026-07-15')

    row = _row(retention.collect()['teachers'], '__ret_t_former__')

    assert row['students'] == 1
    assert row['lost'] == 1
    assert row['pct'] == 0


@pytest.mark.django_db
def test_open_deals_not_in_pct_but_stuck_counted(world, renewals_fixture):
    """Открытая сделка не «не продлилась» — она в работе. Но если висит дольше
    порога, попадает в «застряло»: именно эта колонка честнее доли."""
    teacher = world.teacher('__ret_t_stuck__')
    direction = world.direction('__ret_dir_stuck__')
    group = world.group('__ret_g_stuck__', teacher, direction)
    student = renewals_fixture.student('__ret_student_stuck__')
    world.enrol(group, student)
    renewals_fixture.deal(student, world.pipeline, world.open, 1,
                          due_at=world.days_ago(1))
    renewals_fixture.deal(student, world.pipeline, world.open, 2,
                          due_at=world.days_ago(retention.STUCK_AFTER_DAYS + 10))

    row = _row(retention.collect()['teachers'], '__ret_t_stuck__')

    assert row['open'] == 2
    assert row['stuck'] == 1
    assert row['closed'] == 0
    assert row['pct'] is None


@pytest.mark.django_db
def test_directions_grouped_through_groups(world, renewals_fixture):
    """Направление берётся через группы ученика — тем же путём, что преподаватель,
    иначе листы разошлись бы между собой."""
    teacher = world.teacher('__ret_t_dir__')
    d1 = world.direction('__ret_dir_a__')
    d2 = world.direction('__ret_dir_b__')
    student = renewals_fixture.student('__ret_student_dir__')
    world.enrol(world.group('__ret_g_a__', teacher, d1), student)
    world.enrol(world.group('__ret_g_b__', teacher, d2), student)
    renewals_fixture.deal(student, world.pipeline, world.won, 1, closed_at='2026-07-15')

    data = retention.collect()

    assert _row(data['directions'], '__ret_dir_a__')['won'] == 1
    assert _row(data['directions'], '__ret_dir_b__')['won'] == 1


@pytest.mark.django_db
def test_monthly_breakdown_uses_outcome_month(world, renewals_fixture):
    teacher = world.teacher('__ret_t_month__')
    direction = world.direction('__ret_dir_month__')
    group = world.group('__ret_g_month__', teacher, direction)
    student = renewals_fixture.student('__ret_student_month__')
    world.enrol(group, student)
    renewals_fixture.deal(student, world.pipeline, world.won, 1, closed_at='2026-06-10')
    renewals_fixture.deal(student, world.pipeline, world.lost, 2, closed_at='2026-07-10')

    row = _row(retention.collect()['teachers'], '__ret_t_month__')

    assert row['by_month']['2026-06'] == {'won': 1, 'lost': 0}
    assert row['by_month']['2026-07'] == {'won': 0, 'lost': 1}


@pytest.mark.django_db
def test_service_teacher_flagged_and_sorted_last(world, renewals_fixture):
    """Служебная запись «Архив (импорт истории)» несёт ~80 % сделок школы —
    в общем зачёте она забивает живых, поэтому помечена и уходит вниз."""
    service = world.teacher('__ret_service__', is_service=True)
    live = world.teacher('__ret_live__')
    direction = world.direction('__ret_dir_service__')
    s1 = renewals_fixture.student('__ret_s_service__')
    s2 = renewals_fixture.student('__ret_s_live__')
    world.enrol(world.group('__ret_g_service__', service, direction), s1)
    world.enrol(world.group('__ret_g_live__', live, direction), s2)
    # У служебной записи сделок БОЛЬШЕ — иначе тест прошёл бы и при сортировке
    # просто по объёму, не различая флаг.
    for cycle in (1, 2, 3):
        renewals_fixture.deal(s1, world.pipeline, world.won, cycle, closed_at='2026-07-15')
    renewals_fixture.deal(s2, world.pipeline, world.won, 1, closed_at='2026-07-15')

    rows = retention.collect()['teachers']
    names = [r['name'] for r in rows]

    assert names.index('__ret_service__') > names.index('__ret_live__')
    assert _row(rows, '__ret_service__')['is_service'] is True
    assert _row(rows, '__ret_live__')['is_service'] is False


@pytest.mark.django_db
def test_build_produces_workbook_with_five_sheets(world, renewals_fixture):
    import io

    from openpyxl import load_workbook

    teacher = world.teacher('__ret_t_wb__')
    direction = world.direction('__ret_dir_wb__')
    student = renewals_fixture.student('__ret_student_wb__')
    world.enrol(world.group('__ret_g_wb__', teacher, direction), student)
    renewals_fixture.deal(student, world.pipeline, world.won, 1, closed_at='2026-07-15')

    content, rows, filename = retention.build()

    assert filename.startswith('retention_') and filename.endswith('.xlsx')
    assert rows >= 1
    wb = load_workbook(io.BytesIO(content))
    assert wb.sheetnames == [
        'Свод — преподаватели', 'Свод — направления',
        'Помесячно — преподаватели', 'Помесячно — направления', 'Детализация',
    ]
