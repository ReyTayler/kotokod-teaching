"""Проверяем, что дефолтная воронка и её стадии засеяны data-миграцией."""
from __future__ import annotations

import pytest

from apps.renewals.models import RenewalPipeline, RenewalStage


@pytest.mark.django_db
def test_default_pipeline_seeded():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(pipeline=pipe).order_by('sort_order'))
    assert [s.key for s in stages][0] == 'lesson_progress'
    assert {s.kind for s in stages} >= {'progress', 'decision', 'won', 'lost'}
    assert next(s for s in stages if s.key == 'lesson_progress').is_auto is True
