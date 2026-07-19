"""
build_calendar() — сервисный тест (не API): groupId в occurrence-payload.
Нужен для ссылки «Открыть группу» в попапе admin-календаря (см.
docs/superpowers/specs/2026-07-13-admin-calendar-design.md).
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

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


@pytest.mark.django_db
def test_substitute_shows_in_substitute_calendar_on_its_date(sched_setup):
    """Занятие с заменой попадает в календарь ПОДМЕНЯЮЩЕГО (B) на свою дату, а не
    преподавателя контента (A); occurrence несёт teacherOverride = имя B."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])
    target_date = D(2026, 6, 15)   # понедельник — курсовая строка группы A
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET substitute_teacher_id=%s "
            "WHERE group_id=%s AND scheduled_date=%s AND seq IS NOT NULL",
            [s['teacher_b'], s['group_a'], target_date],
        )

    # Календарь ПОДМЕНЯЮЩЕГО (B) на эту дату — строка есть, эффективный препод = B.
    cal_b = services.build_calendar(target_date, target_date, teacher_id=s['teacher_b'])
    b_rows = [o for o in cal_b['occurrences'] if o['groupId'] == s['group_a']]
    assert len(b_rows) == 1
    assert b_rows[0]['teacher'] == '__sched_B__'
    assert b_rows[0]['teacherOverride'] == '__sched_B__'

    # Календарь преподавателя КОНТЕНТА (A) на эту дату — строки с заменой нет.
    cal_a = services.build_calendar(target_date, target_date, teacher_id=s['teacher_a'])
    a_rows = [o for o in cal_a['occurrences']
              if o['groupId'] == s['group_a'] and o['date'] == '2026-06-15']
    assert a_rows == []


@pytest.mark.django_db
def test_substitute_equal_group_teacher_no_override_badge(sched_setup):
    """Замена на того же преподавателя, что ведёт группу, НЕ показывает бейдж «замена»."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])
    target_date = D(2026, 6, 15)
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET substitute_teacher_id=%s "
            "WHERE group_id=%s AND scheduled_date=%s AND seq IS NOT NULL",
            [s['teacher_a'], s['group_a'], target_date],   # заместитель = препод группы A
        )
    cal = services.build_calendar(target_date, target_date, teacher_id=s['teacher_a'])
    rows = [o for o in cal['occurrences'] if o['groupId'] == s['group_a']]
    assert len(rows) == 1
    assert rows[0]['teacher'] == '__sched_A__'
    assert rows[0]['teacherOverride'] is None   # тот же препод — бейджа нет
