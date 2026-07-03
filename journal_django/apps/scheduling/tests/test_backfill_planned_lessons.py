"""
Тесты бэкфилла planned_lessons: команда + repository (persist_plan/link_facts).

Опираются на фикстуру sched_setup (conftest): группа A преподавателя A со стартом
2026-06-01 (пн), слот Пн 10:00, direction.total_lessons=8, duration 60 → 8 курсовых
строк seq 1..8. Проверяем: план разворачивается, прошлые строки линкуются с фактом
(status='done'), повторный прогон идемпотентен (без дублей и без перезаписи done).

managed-схема journal_test; planned_lessons чистим в teardown локальной фикстуры
ДО того, как sched_setup удалит группы (FK planned_lessons.group_id).
"""
from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import connection

from apps.scheduling import repository
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import DONE

pytestmark = pytest.mark.django_db


@pytest.fixture
def backfill_setup(sched_setup):
    """sched_setup + гарантированная очистка planned_lessons перед удалением групп."""
    yield sched_setup
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM planned_lessons WHERE group_id IN (%s, %s)',
            [sched_setup['group_a'], sched_setup['group_b']],
        )


def _insert_fact(group_id: int, teacher_id: int, date: str, number) -> int:
    """Вставить проведённый урок (факт) и вернуть его id."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, 60, 'regular', NOW(), 'test-backfill') RETURNING id",
            [group_id, teacher_id, date, number],
        )
        return cur.fetchone()[0]


class TestBackfillCommand:
    def test_generates_plan_for_scheduled_group(self, backfill_setup):
        call_command('backfill_planned_lessons')

        rows = list(
            PlannedLesson.objects
            .filter(group_id=backfill_setup['group_a'])
            .order_by('seq')
        )
        assert [r.seq for r in rows] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert rows[0].scheduled_date == datetime.date(2026, 6, 1)
        assert rows[1].scheduled_date == datetime.date(2026, 6, 8)
        assert all(r.scheduled_time == datetime.time(10, 0) for r in rows)
        assert all(r.teacher_id == backfill_setup['teacher_a'] for r in rows)

    def test_links_past_fact_and_marks_done(self, backfill_setup):
        _insert_fact(backfill_setup['group_a'], backfill_setup['teacher_a'],
                     '2026-06-01', Decimal('1'))

        call_command('backfill_planned_lessons')

        seq1 = PlannedLesson.objects.get(group_id=backfill_setup['group_a'], seq=1)
        assert seq1.status == DONE
        assert seq1.fact_lesson_id is not None
        # Непроведённые строки остаются не-done.
        seq2 = PlannedLesson.objects.get(group_id=backfill_setup['group_a'], seq=2)
        assert seq2.status != DONE
        assert seq2.fact_lesson_id is None

    def test_dry_run_writes_nothing(self, backfill_setup):
        call_command('backfill_planned_lessons', '--dry-run')
        assert not PlannedLesson.objects.filter(
            group_id=backfill_setup['group_a'],
        ).exists()

    def test_idempotent_second_run_no_duplicates(self, backfill_setup):
        _insert_fact(backfill_setup['group_a'], backfill_setup['teacher_a'],
                     '2026-06-01', Decimal('1'))

        call_command('backfill_planned_lessons')
        count_after_first = PlannedLesson.objects.filter(
            group_id=backfill_setup['group_a'],
        ).count()
        assert count_after_first == 8

        call_command('backfill_planned_lessons')
        count_after_second = PlannedLesson.objects.filter(
            group_id=backfill_setup['group_a'],
        ).count()
        assert count_after_second == 8

        # done-строка сохранена, ровно одна привязка к факту.
        assert PlannedLesson.objects.filter(
            group_id=backfill_setup['group_a'], status=DONE,
        ).count() == 1


class TestRepositoryWrite:
    def _rows(self):
        from apps.scheduling import planner
        from apps.scheduling.occurrences import Slot
        return planner.generate(
            start_date=datetime.date(2026, 6, 1),
            slots=[Slot(day_of_week=1, start_time=datetime.time(10, 0),
                        effective_from=datetime.date(2026, 6, 1))],
            total_lessons=8, duration_minutes=60, default_teacher_id=None,
        )

    def test_persist_plan_idempotent(self, backfill_setup):
        gid = backfill_setup['group_a']
        rows = self._rows()
        # Проставим реального преподавателя, иначе teacher_id=None (для чистоты FK).
        rows = [replace(r, teacher_id=backfill_setup['teacher_a']) for r in rows]

        first = repository.persist_plan(gid, rows)
        assert first == 8  # все созданы
        second = repository.persist_plan(gid, rows)
        assert second == 0  # ничего не изменилось

    def test_link_facts_idempotent_and_respects_done(self, backfill_setup):
        gid = backfill_setup['group_a']
        rows = self._rows()
        rows = [replace(r, teacher_id=backfill_setup['teacher_a']) for r in rows]
        repository.persist_plan(gid, rows)

        _insert_fact(gid, backfill_setup['teacher_a'], '2026-06-08', Decimal('2'))

        linked_first = repository.link_facts(gid)
        assert linked_first == 1
        linked_second = repository.link_facts(gid)
        assert linked_second == 0

        # persist_plan после линковки не перезаписывает done-строку.
        assert repository.persist_plan(gid, rows) == 0
        seq2 = PlannedLesson.objects.get(group_id=gid, seq=2)
        assert seq2.status == DONE
