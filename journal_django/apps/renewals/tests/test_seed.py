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
