"""Заморозка как обычная стадия воронки (спека 2026-07-25)."""

from datetime import date

import pytest
from django.db import connection

from apps.renewals.migrations._frozen_month_backfill import BACKFILL_SQL
from apps.renewals.models import RenewalDeal, RenewalStage
from apps.students.models import Student


@pytest.mark.django_db
def test_backfill_sql_takes_month_from_student_frozen_until():
    """Бэкфил (миграция 0013) переносит месяц заморозки с ученика на его открытую
    сделку, стоящую на стадии 'frozen'. Тот же SQL гоняем повторно — он
    идемпотентен (WHERE frozen_until_month IS NULL)."""
    student = Student.objects.create(
        full_name='__bf_frozen__', enrollment_status='frozen',
        frozen_from=date(2026, 7, 1), frozen_until=date(2026, 9, 20),
        created_at='2026-07-01T00:00:00Z')
    stage = RenewalStage.objects.get(pipeline__is_default=True, key='frozen')
    deal = RenewalDeal.objects.create(
        student=student, cycle_no=1, pipeline=stage.pipeline, stage=stage)

    with connection.cursor() as cur:
        cur.execute(BACKFILL_SQL)

    deal.refresh_from_db()
    assert deal.frozen_until_month == date(2026, 9, 1)
