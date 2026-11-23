"""Чистые версионированные правила групповой мотивации, без ORM."""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from apps.payroll.engine import (
    KIND_BURNED, KIND_EXTRA, KIND_MAKEUP, LessonInput, Result,
    _date, _is_late_report, _round, _rub, lesson_kind,
)


@dataclass(frozen=True)
class GroupRateCard:
    id: int
    effective_from: date
    calculation_method: str = 'attendance_v1'
    small_group_limit: int = 2
    small_full_rate: Decimal = Decimal('500')
    small_partial_rate: Decimal = Decimal('300')
    per_student_rate: Decimal = Decimal('200')
    half_lesson_rate: Decimal = Decimal('250')
    makeup_rate: Decimal = Decimal('200')
    burned_rate: Decimal = Decimal('200')
    penalty_enabled: bool = True
    penalty_mode: str = 'per_student'
    penalty_amount: Decimal = Decimal('40')

    @classmethod
    def from_version(cls, version):
        return cls(**{name: getattr(version, name) for name in cls.__dataclass_fields__})


def group_lesson_pay(lesson: LessonInput, card: GroupRateCard) -> Result:
    if card.calculation_method != 'attendance_v1':
        raise ValueError(f'Неизвестная схема групповой мотивации: {card.calculation_method}')
    kind = lesson_kind(lesson.lesson_type, lesson.submitted_by_token)
    present = lesson.present_count
    total = lesson.total_students
    prefix = f'Групповая ставка с {_date(card.effective_from)}'
    if kind == KIND_BURNED:
        return Result(_round(card.burned_rate), f'{prefix} · сгорание — {_rub(card.burned_rate)}')
    if not present:
        return Result(Decimal('0.00'), f'{prefix} · никто не присутствовал — 0 ₽')
    if kind == KIND_MAKEUP:
        amount = card.makeup_rate * present
        note = f'отработка: {present} × {_rub(card.makeup_rate)}'
    elif kind == KIND_EXTRA:
        # Доп.урок сверх курса в обычной группе исторически плоский: ставка за
        # ученика × присутствующих, без ветвления по 45 минутам и составу
        # (extra_lessons.services.record, решение владельца 2026-07-24).
        # Ставка «как за индив» (total=1) — только у индив-групп, их ведёт
        # индивидуальная «Мотивация», не этот движок.
        amount = card.per_student_rate * present
        note = f'{present} × {_rub(card.per_student_rate)}'
    elif lesson.duration_minutes == 45:
        amount = card.half_lesson_rate * present
        note = f'45 минут: {present} × {_rub(card.half_lesson_rate)}'
    elif total <= card.small_group_limit:
        full = present == total
        amount = card.small_full_rate if full else card.small_partial_rate
        note = f'малая группа, {"все пришли" if full else "пришла часть"}: {_rub(amount)}'
    else:
        amount = card.per_student_rate * present
        note = f'{present} × {_rub(card.per_student_rate)}'
    penalty = Decimal('0')
    penalty_note = ''
    if card.penalty_enabled and _is_late_report(lesson):
        penalty = card.penalty_amount * (present if card.penalty_mode == 'per_student' else 1)
        penalty_note = f' · штраф за отчёт: {_rub(penalty)}'
    label = 'доп.урок сверх курса · ' if kind == KIND_EXTRA else ''
    return Result(_round(amount),
                  f'{prefix} · {label}состав {total}, присутствовали {present} · '
                  f'{note} = {_rub(_round(amount))}{penalty_note}', _round(penalty))


def group_snapshot(lesson: LessonInput, card: GroupRateCard) -> dict:
    def serial(value):
        if isinstance(value, (Decimal, date)):
            return str(value)
        return value
    return {
        'version_id': card.id,
        'rates': {key: serial(value) for key, value in asdict(card).items()},
        'inputs': {key: serial(value) for key, value in asdict(lesson).items()},
    }
