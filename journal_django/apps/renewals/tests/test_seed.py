"""Проверяем, что дефолтная воронка и её стадии засеяны data-миграцией."""
from __future__ import annotations

import pytest

from apps.renewals.models import RenewalPipeline, RenewalStage


@pytest.mark.django_db
def test_default_pipeline_seeded():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(pipeline=pipe).order_by('sort_order'))
    # Первая по sort_order — «Урок 1» (миграция 0003 разбила lesson_progress на 4 стадии,
    # см. apps/renewals/tests/test_lesson_progress.py::test_default_pipeline_has_four_lesson_stages).
    assert [s.key for s in stages][0] == 'lesson_1'
    assert {s.kind for s in stages} >= {'progress', 'decision', 'won', 'lost'}
    assert next(s for s in stages if s.key == 'lesson_1').is_auto is True


@pytest.mark.django_db
def test_awaiting_renewal_stage_seeded():
    """Миграция 0005: «Ждём продление» сразу после «Ждём оплату», обе — авто."""
    pipe = RenewalPipeline.objects.get(is_default=True)
    ar = RenewalStage.objects.get(pipeline=pipe, key='awaiting_renewal')
    ap = RenewalStage.objects.get(pipeline=pipe, key='awaiting_payment')
    assert ar.is_auto and ap.is_auto and ar.kind == 'decision'
    assert ar.sort_order == ap.sort_order + 1
