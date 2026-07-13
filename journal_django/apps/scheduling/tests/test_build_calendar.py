"""
build_calendar() — сервисный тест (не API): groupId в occurrence-payload.
Нужен для ссылки «Открыть группу» в попапе admin-календаря (см.
docs/superpowers/specs/2026-07-13-admin-calendar-design.md).
"""
from __future__ import annotations

import datetime

import pytest

from apps.scheduling import repository, services

D = datetime.date
W_FROM = D(2026, 6, 1)
W_TO = D(2026, 6, 30)


@pytest.mark.django_db
def test_occurrence_includes_group_id(sched_setup):
    s = sched_setup
    repository.generate_for_group(s['group_a'])

    cal = services.build_calendar(W_FROM, W_TO, teacher_id=s['teacher_a'])

    assert len(cal['occurrences']) > 0
    assert cal['occurrences'][0]['groupId'] == s['group_a']
