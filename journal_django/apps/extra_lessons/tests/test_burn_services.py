"""Тесты «Сжечь» (Фаза 1c-2): статус burned, repository.mark_burned, сервис
burn() и обобщённый delete_fact (откат сгорания). Реальная БД (journal_test)."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.extra_lessons import repository, services
from apps.extra_lessons.models import (
    BURNED, MAKEUP_DONE, PENDING, STATUS_CHOICES, AbsenceResolution,
)
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll

pytestmark = pytest.mark.django_db


class _FakeRequest:
    """Минимальная заглушка request для log_event (без HTTP-контекста)."""
    META: dict = {}
    user = None


def _cleanup_fact(lesson_id):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


@pytest.fixture
def absence_pending(missed_lesson_fixture, student_fixture):
    """pending-резолюция реально отсутствовавшего ученика.

    missed_lesson_fixture записан через create_lesson_full → record_lesson УЖЕ
    авто-создал pending (regular-урок, present=false). Берём существующую строку,
    НЕ создаём вторую (UNIQUE(missed_lesson, student)). Teardown сносит созданный
    burned-факт и все резолюции пропуска ДО teardown missed_lesson_fixture
    (absence_resolutions.missed_lesson — реальный DB-level FK)."""
    res = AbsenceResolution.objects.get(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture, status=PENDING)
    yield res
    with connection.cursor() as cur:
        cur.execute(
            'SELECT fact_lesson_id FROM absence_resolutions WHERE missed_lesson_id = %s '
            'AND fact_lesson_id IS NOT NULL', [missed_lesson_fixture])
        fact_ids = [r[0] for r in cur.fetchall()]
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [missed_lesson_fixture])
        for fid in fact_ids:
            cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [fid])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [fid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [fid])


def test_burned_status_registered():
    assert BURNED == 'burned'
    assert BURNED in STATUS_CHOICES


# --- Task 2: repository ---------------------------------------------------

def test_mark_burned_sets_status_and_fact(absence_pending):
    # fact_lesson_id = missed_lesson_id — валидная строка lessons (для проверки
    # апдейта достаточно; настоящий burned-факт создаёт сервис в Task 3).
    repository.mark_burned(absence_pending.id, fact_lesson_id=absence_pending.missed_lesson_id)
    absence_pending.refresh_from_db()
    assert absence_pending.status == BURNED
    assert absence_pending.fact_lesson_id == absence_pending.missed_lesson_id


def test_has_active_resolution_true_for_burned(absence_pending):
    assert repository.has_active_resolution(
        absence_pending.missed_lesson_id, absence_pending.student_id) is False
    repository.mark_burned(absence_pending.id, fact_lesson_id=absence_pending.missed_lesson_id)
    assert repository.has_active_resolution(
        absence_pending.missed_lesson_id, absence_pending.student_id) is True
