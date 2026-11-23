"""
Чистый расчёт «Мотивации» (apps/payroll/engine.py) — таблица случаев без БД.

Охват KOTOKOD: только индивидуальные занятия на даты с версией ставок; урок —
фикс без учёта длительности; доп.урок сверх курса — по ставке урока; отработка и
сгорание — свои ставки; отмена — только с записью о причине.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.core.utils.dates import MSK
from apps.payroll.engine import (
    CancellationDecision,
    LessonInput,
    MarkerInput,
    PersonalRateInput,
    RateCard,
    cancellation_pay,
    governs,
    legacy_lesson_pay,
    lesson_kind,
    lesson_pay,
    rates_on,
)

D = Decimal
DAY = datetime.date(2026, 12, 1)


def card(**kw) -> RateCard:
    base = dict(
        effective_from=datetime.date(2026, 11, 18), individual_rate=D('600'),
        makeup_rate=D('250'), burned_rate=D('150'), cancel_mode='percent',
        cancel_value=D('50'), penalty_enabled=False, penalty_mode='per_lesson',
        penalty_amount=D('0'), direction_rates={},
    )
    base.update(kw)
    return RateCard(**base)


def lesson(**kw) -> LessonInput:
    base = dict(
        teacher_id=1, group_id=10, lesson_date=DAY, lesson_number=D('5'),
        is_individual=True, direction_id=7, direction_name='Python',
        submitted_at=None, submitted_by_token='acct:1', present_count=1,
        total_students=1, lesson_type='regular', duration_minutes=60,
    )
    base.update(kw)
    return LessonInput(**base)


def marker(decision=None, **kw) -> MarkerInput:
    base = dict(teacher_id=1, group_id=10, scheduled_date=DAY, is_individual=True,
                direction_id=7, direction_name='Python', decision=decision)
    base.update(kw)
    return MarkerInput(**base)


def personal(**kw) -> PersonalRateInput:
    base = dict(teacher_id=1, group_id=10, lesson_from=None, lesson_to=None,
                kind='plus_fixed', value=D('100'))
    base.update(kw)
    return PersonalRateInput(**base)


# ── охват ──────────────────────────────────────────────────────────────────

def test_governs_only_individual_with_card():
    assert governs(True, card())
    assert not governs(False, card())   # групповой формат — движок
    assert not governs(True, None)      # дата до первой версии — движок


def test_rates_on_picks_latest_not_after_day():
    old = card(effective_from=datetime.date(2026, 11, 18))
    new = card(effective_from=datetime.date(2026, 12, 5), individual_rate=D('700'))
    assert rates_on([old, new], DAY) is old
    assert rates_on([old, new], datetime.date(2026, 12, 5)) is new
    assert rates_on([new], DAY) is None


def test_lesson_kind_by_type_and_token():
    assert lesson_kind('regular', 'acct:1') == 'lesson'
    assert lesson_kind('substitution', 'acct:1') == 'lesson'
    assert lesson_kind('extra', 'extra:5') == 'extra'
    assert lesson_kind('extra', 'makeup:5') == 'makeup'
    assert lesson_kind('burned', 'burn:5') == 'burned'


# ── урок ───────────────────────────────────────────────────────────────────

def test_lesson_fixed_rate_ignores_duration():
    full = lesson_pay(lesson(duration_minutes=90), card(), [])
    half = lesson_pay(lesson(duration_minutes=45), card(), [])
    assert full.payment == half.payment == D('600.00')
    assert 'ставка по умолчанию' in full.rule_note


def test_direction_rate_overrides_default():
    res = lesson_pay(lesson(), card(direction_rates={7: D('800')}), [])
    assert res.payment == D('800.00')
    assert 'Python' in res.rule_note


def test_nobody_present_pays_zero():
    res = lesson_pay(lesson(present_count=0), card(), [])
    assert res.payment == D('0.00')


def test_extra_beyond_course_uses_lesson_rate():
    res = lesson_pay(lesson(lesson_type='extra', submitted_by_token='extra:9'), card(), [])
    assert res.payment == D('600.00')
    assert res.rule_note.startswith('Доп.урок сверх курса')


def test_makeup_and_burned_use_own_rates():
    makeup = lesson_pay(lesson(lesson_type='extra', submitted_by_token='makeup:9'), card(), [])
    burned = lesson_pay(lesson(lesson_type='burned', submitted_by_token='burn:9'), card(), [])
    assert makeup.payment == D('250.00')
    assert burned.payment == D('150.00')


def test_makeup_ignores_personal_rate():
    res = lesson_pay(lesson(lesson_type='extra', submitted_by_token='makeup:9'), card(),
                     [personal(kind='fixed', value=D('999'))])
    assert res.payment == D('250.00')


# ── персональные ставки ────────────────────────────────────────────────────

@pytest.mark.parametrize('kind,value,expected', [
    ('fixed', D('900'), D('900.00')),
    ('plus_fixed', D('100'), D('700.00')),
    ('plus_percent', D('10'), D('660.00')),
])
def test_personal_kinds(kind, value, expected):
    assert lesson_pay(lesson(), card(), [personal(kind=kind, value=value)]).payment == expected


def test_range_beats_all_lessons_and_other_teacher_ignored():
    rates = [personal(kind='fixed', value=D('700')),
             personal(kind='fixed', value=D('900'), lesson_from=D('4'), lesson_to=D('6')),
             personal(teacher_id=2, kind='fixed', value=D('5000'))]
    assert lesson_pay(lesson(), card(), rates).payment == D('900.00')
    assert lesson_pay(lesson(lesson_number=D('8')), card(), rates).payment == D('700.00')


def test_personal_period_respects_dates():
    closed = personal(kind='fixed', value=D('900'), valid_until=DAY)
    assert lesson_pay(lesson(), card(), [closed]).payment == D('600.00')


# ── штраф ──────────────────────────────────────────────────────────────────

def _late(token='acct:1'):
    return lesson(submitted_by_token=token,
                  submitted_at=datetime.datetime(2026, 12, 2, 10, 0, tzinfo=MSK))


def test_penalty_off_by_default():
    assert lesson_pay(_late(), card(), []).penalty == D('0.00')


def test_penalty_per_student_for_teacher_record():
    c = card(penalty_enabled=True, penalty_mode='per_student', penalty_amount=D('40'))
    assert lesson_pay(_late(), c, []).penalty == D('40.00')
    # Доп.урок записывает тоже преподаватель — штрафуется.
    assert lesson_pay(_late('makeup:3'), c, []).penalty == D('40.00')
    # Запись админки — не штрафуется.
    assert lesson_pay(_late('admin-imported'), c, []).penalty == D('0.00')


def test_same_day_report_not_penalized():
    c = card(penalty_enabled=True, penalty_amount=D('100'))
    on_time = lesson(submitted_at=datetime.datetime(2026, 12, 1, 23, 30, tzinfo=MSK))
    assert lesson_pay(on_time, c, []).penalty == D('0.00')


# ── отмена ─────────────────────────────────────────────────────────────────

COMP = CancellationDecision(compensated=True, side_label='Клиент', reason='Заболел')
NO_COMP = CancellationDecision(compensated=False, side_label='Преподаватель', reason='Отпуск')


def test_cancel_percent_of_rate_with_all_lessons_personal():
    res = cancellation_pay(marker(COMP), card(), [personal(kind='plus_fixed', value=D('200'))])
    assert res.payment == D('400.00')   # 50 % от (600 + 200)
    assert res.rule_note.startswith('Клиент — Заболел')


def test_cancel_fixed_and_not_compensated():
    assert cancellation_pay(marker(COMP), card(cancel_mode='fixed', cancel_value=D('300')),
                            []).payment == D('300.00')
    res = cancellation_pay(marker(NO_COMP), card(), [])
    assert res.payment == D('0.00')
    assert res.rule_note.startswith('Без компенсации')


def test_cancel_without_decision_is_refused():
    with pytest.raises(ValueError):
        cancellation_pay(marker(None), card(), [])


# ── возврат к прежнему движку ──────────────────────────────────────────────

def test_legacy_lesson_pay_matches_calculator_rules():
    assert legacy_lesson_pay(lesson(duration_minutes=60)).payment == D('500.00')
    assert legacy_lesson_pay(lesson(duration_minutes=45)).payment == D('250.00')
    assert legacy_lesson_pay(lesson(lesson_type='extra', submitted_by_token='makeup:1')).payment == D('200.00')
    assert legacy_lesson_pay(lesson(lesson_type='burned', submitted_by_token='burn:1')).payment == D('200.00')
    assert legacy_lesson_pay(_late()).penalty == D('40.00')
