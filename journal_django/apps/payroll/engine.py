"""
Движок зарплат «Мотивации» — единственное место правил начисления по ставкам
школы (перенос из Eduson; спека
docs/superpowers/specs/2026-11-18-motivation-individual-design.md, §2–§3).

«Мотивация» управляет только ИНДИВИДУАЛЬНЫМИ занятиями (Group.is_individual) и
только на даты, для которых задана версия ставок (`governs`). Остальное —
групповые форматы и даты до первой версии — считает прежний движок
(apps/payroll/calculator.py) в местах записи урока, как раньше.

Здесь только чистый расчёт без БД — rates_on / format_rate / lesson_pay /
cancellation_pay / legacy_lesson_pay над простыми входными структурами: правила
проверяются таблицей случаев. Сбор входов из БД и запись начислений —
apps/payroll/recalc.py.

Деньги — Decimal; округление до копеек ОДИН раз на выходе каждого начисления.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from apps.core.utils.dates import MSK
from apps.payroll.calculator import (
    calculate_extra_lesson_payment,
    calculate_payment,
    PENALTY_PER_STUDENT,
)

__all__ = [
    'RateCard', 'LessonInput', 'CancellationDecision', 'MarkerInput', 'PersonalRateInput',
    'Result', 'rates_on', 'format_rate', 'governs', 'lesson_kind', 'lesson_pay',
    'legacy_lesson_pay', 'cancellation_pay',
]

_KOPECK = Decimal('0.01')
_ZERO = Decimal('0.00')
_HUNDRED = Decimal('100')
# Неразрывный пробел в разрядах: сумма не рвётся переносом строки на узком экране.
_NBSP = ' '

# Источники записи, которые делает сам преподаватель в кабинете: урок курса
# ('acct:<id>'), доп.урок сверх курса ('extra:<resolution>') и отработка
# ('makeup:<resolution>') — доп.уроки записывает только назначенный
# преподаватель. Админка ('admin-imported' и пр.) и сгорание ('burn:…') не
# штрафуются: это действия администратора.
_TEACHER_TOKEN_PREFIXES = ('acct:', 'extra:', 'makeup:')

# Виды занятия для ставки (lesson_kind).
KIND_LESSON = 'lesson'     # урок курса (в т.ч. замена/перенос)
KIND_EXTRA = 'extra'       # доп.урок сверх курса — по ставке урока
KIND_MAKEUP = 'makeup'     # отработка пропуска — ставка отработки
KIND_BURNED = 'burned'     # сгорание пропуска — ставка сгорания

_BURNED_TYPE = 'burned'
_EXTRA_TYPE = 'extra'
_EXTRA_TOKEN_PREFIX = 'extra:'
_HALF_MINUTES = 45


# ---------------------------------------------------------------------------
# Входные структуры чистого расчёта
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RateCard:
    """Версия ставок школы (индив) в виде, удобном для расчёта (без ORM).

    direction_rates: {direction_id: individual_rate}; направления без строки —
    «как по умолчанию»."""

    effective_from: datetime.date
    individual_rate: Decimal
    makeup_rate: Decimal
    burned_rate: Decimal
    cancel_mode: str
    cancel_value: Decimal
    penalty_enabled: bool = False
    penalty_mode: str = 'per_lesson'
    penalty_amount: Decimal = _ZERO
    direction_rates: dict = field(default_factory=dict)

    @classmethod
    def from_version(cls, version) -> 'RateCard':
        """PayRateVersion (directions уже prefetch'нуты) → RateCard."""
        return cls(
            effective_from=version.effective_from,
            individual_rate=version.individual_rate,
            makeup_rate=version.makeup_rate,
            burned_rate=version.burned_rate,
            cancel_mode=version.cancel_mode,
            cancel_value=version.cancel_value,
            penalty_enabled=version.penalty_enabled,
            penalty_mode=version.penalty_mode,
            penalty_amount=version.penalty_amount,
            direction_rates={d.direction_id: d.individual_rate
                             for d in version.directions.all()},
        )


@dataclass(frozen=True)
class LessonInput:
    teacher_id: int
    group_id: int
    lesson_date: datetime.date
    lesson_number: Decimal
    is_individual: bool
    direction_id: int | None
    direction_name: str | None
    submitted_at: datetime.datetime | None
    submitted_by_token: str | None
    present_count: int
    total_students: int = 0
    lesson_type: str = 'regular'
    duration_minutes: int = 60


@dataclass(frozen=True)
class CancellationDecision:
    """Снимок решения об отмене (LessonCancellation.compensated).

    reason — готовый текст причины из справочника (собирает
    apps/cancellations/repository.py). Движок текст не разбирает."""

    compensated: bool
    side_label: str
    reason: str


@dataclass(frozen=True)
class MarkerInput:
    """Маркер отмены (PlannedLesson status='cancelled', seq IS NULL)."""

    teacher_id: int
    group_id: int
    scheduled_date: datetime.date
    is_individual: bool
    direction_id: int | None
    direction_name: str | None
    # None — отмена без записи о причине (до фичи): прежний движок отмены не
    # оплачивал — начисления нет.
    decision: CancellationDecision | None = None


@dataclass(frozen=True)
class PersonalRateInput:
    """Период персональной ставки (PersonalRateTerm).

    Действует на дату d, если valid_from ≤ d < valid_until; None — без границы.
    Пустой период (valid_from == valid_until) не действует ни на одну дату."""

    teacher_id: int
    group_id: int
    lesson_from: Decimal | None
    lesson_to: Decimal | None
    kind: str
    value: Decimal
    valid_from: datetime.date | None = None
    valid_until: datetime.date | None = None

    @property
    def is_all_lessons(self) -> bool:
        return self.lesson_from is None and self.lesson_to is None

    def covers(self, day: datetime.date) -> bool:
        return ((self.valid_from is None or self.valid_from <= day)
                and (self.valid_until is None or day < self.valid_until))


@dataclass(frozen=True)
class Result:
    payment: Decimal
    rule_note: str
    penalty: Decimal = _ZERO


# ---------------------------------------------------------------------------
# Форматирование пояснений (без ПДн: ни имён, ни ФИО — только правило и числа)
# ---------------------------------------------------------------------------

def _num(value: Decimal, exact: bool = False) -> str:
    """Число для пояснения: 1250.5 → «1 250,50», 500.00 → «500».

    exact=True — без округления до копеек (0.505 → «0,505»): так печатается
    промежуточная база, от которой дальше берётся процент."""
    value = Decimal(value)
    if not exact or value == value.quantize(_KOPECK):
        value = value.quantize(_KOPECK, rounding=ROUND_HALF_UP)
    sign = '-' if value < 0 else ''
    value = abs(value)
    whole = int(value)
    grouped = f'{whole:,}'.replace(',', _NBSP)
    fraction = value - whole
    if not fraction:
        return f'{sign}{grouped}'
    digits = format(fraction, 'f').split('.')[1].rstrip('0')
    return f'{sign}{grouped},{digits.ljust(2, "0")}'


def _rub(value: Decimal, exact: bool = False) -> str:
    return f'{_num(value, exact)} ₽'


def _lesson_no(value: Decimal) -> str:
    """Номер урока без лишних нулей: 10.0 → «10», 10.5 → «10.5»."""
    return format(Decimal(value).normalize(), 'f')


def _date(value: datetime.date) -> str:
    return value.strftime('%d.%m.%Y')


def _round(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_KOPECK, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Чистый расчёт
# ---------------------------------------------------------------------------

def rates_on(cards: Iterable[RateCard], day: datetime.date) -> RateCard | None:
    """Версия, действующая на дату: последняя с effective_from ≤ day."""
    best = None
    for card in cards:
        if card.effective_from <= day and (best is None
                                           or card.effective_from > best.effective_from):
            best = card
    return best


def governs(is_individual: bool, card: RateCard | None) -> bool:
    """Считает ли занятие «Мотивация»: индивидуальный формат и есть версия ставок
    на дату. Иначе — прежний движок (групповые форматы — заглушка в настройках)."""
    return bool(is_individual) and card is not None


def _format_cell(card: RateCard, direction_id: int | None) -> tuple[Decimal, bool]:
    """(ставка индива, взята ли из строки направления)."""
    if direction_id is not None and direction_id in card.direction_rates:
        return card.direction_rates[direction_id], True
    return card.individual_rate, False


def format_rate(card: RateCard, direction_id: int | None) -> Decimal:
    """Ставка индива: строка направления, если задана, иначе «По умолчанию»."""
    return _format_cell(card, direction_id)[0]


def _format_note(card: RateCard, direction_id, direction_name) -> tuple[Decimal, str]:
    rate, from_direction = _format_cell(card, direction_id)
    if from_direction:
        head = f'Индивидуальный урок · {direction_name} · ставка с {_date(card.effective_from)}'
    else:
        head = f'Индивидуальный урок · ставка по умолчанию с {_date(card.effective_from)}'
    return rate, f'{head} — {_rub(rate)}'


def _apply_personal(base: Decimal, rate: PersonalRateInput,
                    exact: bool = False) -> tuple[Decimal, str]:
    """Персональная ставка поверх базы. Сумма НЕ округляется — округление одно, на выходе.
    exact — итог промежуточный (база отмены): печатается без округления."""
    if rate.is_all_lessons:
        scope = 'все уроки'
    else:
        scope = f'уроки {_lesson_no(rate.lesson_from)}–{_lesson_no(rate.lesson_to)}'
    if rate.kind == 'fixed':
        amount = rate.value
        tail = f'вместо ставки — {_rub(amount)}'
    elif rate.kind == 'plus_fixed':
        amount = base + rate.value
        tail = f'+{_rub(rate.value)} к {_rub(base)} = {_rub(amount, exact)}'
    elif rate.kind == 'plus_percent':
        amount = base * (1 + rate.value / _HUNDRED)
        tail = f'+{_num(rate.value)} % к {_rub(base)} = {_rub(amount, exact)}'
    else:  # CHECK в БД не пускает другие виды; защищаемся от тихого нуля
        raise ValueError(f'Неизвестный вид персональной ставки: {rate.kind!r}')
    return amount, f'Персональная ставка ({scope}): {tail}'


def _own_rates(personal_rates: Iterable[PersonalRateInput], teacher_id: int,
               group_id: int, day: datetime.date) -> list[PersonalRateInput]:
    # Персональная ставка действует, только когда занятие ведёт её преподаватель,
    # и только периодами, действующими на дату занятия: правка ставки сегодня не
    # меняет начислений за прошлые даты ни при каком пересчёте.
    return [r for r in personal_rates
            if r.teacher_id == teacher_id and r.group_id == group_id and r.covers(day)]


def _pick_lesson_rate(rates: list[PersonalRateInput],
                      number: Decimal) -> PersonalRateInput | None:
    """Диапазон, в который попал номер, точнее «все уроки» и побеждает его."""
    all_lessons = None
    for rate in rates:
        if rate.is_all_lessons:
            all_lessons = rate
        elif rate.lesson_from <= number <= rate.lesson_to:
            return rate
    return all_lessons


def lesson_kind(lesson_type: str, token: str | None) -> str:
    """Вид занятия для ставки. Доп.урок сверх курса и отработка оба записаны как
    lesson_type='extra' — различает их источник записи (extra_lessons.services.record)."""
    if lesson_type == _BURNED_TYPE:
        return KIND_BURNED
    if lesson_type == _EXTRA_TYPE:
        return KIND_EXTRA if (token or '').startswith(_EXTRA_TOKEN_PREFIX) else KIND_MAKEUP
    return KIND_LESSON


def _is_teacher_record(token: str | None) -> bool:
    return (token or '').startswith(_TEACHER_TOKEN_PREFIXES)


def _is_late_report(lesson: LessonInput) -> bool:
    """Отчёт преподавателя из кабинета не в день урока (дата submitted_at по МСК)."""
    if not _is_teacher_record(lesson.submitted_by_token) or lesson.submitted_at is None:
        return False
    return lesson.submitted_at.astimezone(MSK).date() > lesson.lesson_date


def lesson_pay(lesson: LessonInput, card: RateCard,
               personal_rates: Iterable[PersonalRateInput]) -> Result:
    """Начисление за проведённое индив-занятие по версии ставок на его дату.
    Звать только для занятий, которыми управляет «Мотивация» (governs)."""
    kind = lesson_kind(lesson.lesson_type, lesson.submitted_by_token)
    if kind == KIND_BURNED:
        # Сгорание — действие администратора: штрафа нет.
        return Result(_round(card.burned_rate),
                      f'Сгорание пропуска · ставка с {_date(card.effective_from)} — '
                      f'{_rub(card.burned_rate)}')
    if lesson.present_count == 0:
        return Result(_ZERO, 'Никто не присутствовал — не оплачивается')

    if kind == KIND_MAKEUP:
        amount = card.makeup_rate
        notes = [f'Отработка пропуска · ставка с {_date(card.effective_from)} — '
                 f'{_rub(amount)}']
    else:
        amount, note = _format_note(card, lesson.direction_id, lesson.direction_name)
        if kind == KIND_EXTRA:
            note = f'Доп.урок сверх курса · {note}'
        notes = [note]
        personal = _pick_lesson_rate(
            _own_rates(personal_rates, lesson.teacher_id, lesson.group_id, lesson.lesson_date),
            lesson.lesson_number)
        if personal is not None:
            amount, personal_note = _apply_personal(amount, personal)
            notes.append(personal_note)

    penalty = _ZERO
    if card.penalty_enabled and _is_late_report(lesson):
        if card.penalty_mode == 'per_student':
            penalty = card.penalty_amount * lesson.present_count
            penalty_note = (f'Штраф за отчёт не в день урока: '
                            f'{_rub(card.penalty_amount)} × {lesson.present_count}')
        else:
            penalty = card.penalty_amount
            penalty_note = f'Штраф за отчёт не в день урока: {_rub(card.penalty_amount)}'
        if penalty:
            notes.append(penalty_note)

    return Result(_round(amount), ' · '.join(notes), _round(penalty))


def legacy_lesson_pay(lesson: LessonInput) -> Result:
    """Сумма прежнего движка — для занятия, которое считала «Мотивация», а
    теперь не считает (удалили версию, начатую сегодня; группе сменили формат).
    Повторяет ветки мест записи урока (lessons.services.record_lesson,
    extra_lessons.services.record/burn) поверх calculator.py; rule_note пустой —
    пояснение такой строки строит explain.py сверкой с калькулятором."""
    kind = lesson_kind(lesson.lesson_type, lesson.submitted_by_token)
    is_half = lesson.duration_minutes == _HALF_MINUTES
    if kind == KIND_BURNED:
        return Result(_round(Decimal(calculate_extra_lesson_payment(1))), '')
    if kind == KIND_MAKEUP:
        payment = calculate_extra_lesson_payment(lesson.present_count)
    elif kind == KIND_EXTRA and lesson.is_individual:
        # Доп.урок сверх курса индива — обычное индив-занятие (total=1).
        payment = calculate_payment(1, lesson.present_count, is_half)
    elif kind == KIND_EXTRA:
        # В обычной группе — плоско 200 × присутствующих, без ветвления по
        # длительности и составу (extra_lessons.services.record, решение 2026-07-24).
        payment = calculate_extra_lesson_payment(lesson.present_count)
    else:
        payment = calculate_payment(lesson.total_students, lesson.present_count, is_half)
    penalty = (PENALTY_PER_STUDENT * lesson.present_count
               if _is_late_report(lesson) else 0)
    return Result(_round(Decimal(payment)), '', _round(Decimal(penalty)))


def cancellation_pay(marker: MarkerInput, card: RateCard,
                     personal_rates: Iterable[PersonalRateInput]) -> Result:
    """Начисление за отменённое индив-занятие с записью о причине по версии на
    его дату. Звать только для маркеров с решением (marker.decision) под
    управлением «Мотивации».

    «Без компенсации» — ноль, а строка остаётся с причиной, чтобы в «Зарплате»
    был виден и ноль, и почему. С компенсацией — сумма «Мотивации», причина —
    префиксом пояснения."""
    decision = marker.decision
    if decision is None:  # вызывающий обязан отсечь — защищаемся от тихой оплаты
        raise ValueError('Отмена без записи о причине «Мотивацией» не оплачивается')
    if not decision.compensated:
        return Result(_ZERO, f'Без компенсации: {decision.side_label} — {decision.reason}')
    res = _cancellation_amount(marker, card, personal_rates)
    return Result(res.payment, f'{decision.side_label} — {decision.reason} · {res.rule_note}')


def _cancellation_amount(marker: MarkerInput, card: RateCard,
                         personal_rates: Iterable[PersonalRateInput]) -> Result:
    """Сумма «Мотивации» за отмену: % от ставки индива (с персональной «все
    уроки») или фикс."""
    if card.cancel_mode == 'fixed':
        # Фикс не зависит ни от направления, ни от персональной ставки.
        return Result(_round(card.cancel_value), f'Отмена: фикс {_rub(card.cancel_value)}')

    base, note = _format_note(card, marker.direction_id, marker.direction_name)
    notes = [note]
    # У отмены нет номера урока — применима только ставка «все уроки».
    personal = next((r for r in _own_rates(personal_rates, marker.teacher_id, marker.group_id,
                                           marker.scheduled_date)
                     if r.is_all_lessons), None)
    if personal is not None:
        base, personal_note = _apply_personal(base, personal, exact=True)
        notes.append(personal_note)
    amount = base * card.cancel_value / _HUNDRED
    notes.append(f'Отмена: {_num(card.cancel_value)} % от {_rub(base, exact=True)} '
                 f'= {_rub(amount)}')
    return Result(_round(amount), ' · '.join(notes))
