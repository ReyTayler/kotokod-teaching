"""
Чистый генератор плановых занятий (occurrences) — БЕЗ доступа к БД, полностью
тестируемый в изоляции.

Модель (см. дизайн в памяти project-lesson-scheduling):
  RECURRENCE (start_date + версионируемые слоты + длина курса)
    → OCCURRENCES (вычисляемые плановые занятия)
    ← накладываются EXCEPTIONS (перенос/отмена/доп.) и факты (даты уроков).

Конвенция day_of_week — **Вс=0** (JS getDay), проверено на данных БД.
Даты — datetime.date; время — datetime.time; сравнение «сейчас» — по МСК (ZoneInfo).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from apps.core.utils.dates import MSK

# Статусы плановых занятий.
PENDING = 'pending'      # факта нет, время ещё не наступило
OVERDUE = 'overdue'      # факта нет, время прошло (надо заполнить)
DONE = 'done'            # есть факт (урок записан) на эту дату
CANCELLED = 'cancelled'  # отменён разовым исключением
MOVED = 'moved'          # исходное занятие перенесено (показываем «перенесён на …»)

# Предохранитель от бесконечного цикла на битых данных (10 лет недель).
_CAP_WEEKS = 520


@dataclass
class Slot:
    """Версионированный слот расписания (день недели Вс=0 + время + период действия)."""
    day_of_week: int
    start_time: datetime.time
    effective_from: datetime.date
    effective_to: Optional[datetime.date] = None

    def active_on(self, d: datetime.date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)


@dataclass
class ScheduleException:
    """Разовое переопределение (kind: reschedule|cancel|extra)."""
    kind: str
    original_date: Optional[datetime.date] = None
    original_time: Optional[datetime.time] = None
    new_date: Optional[datetime.date] = None
    new_start_time: Optional[datetime.time] = None
    new_teacher_id: Optional[int] = None


@dataclass
class Occurrence:
    """Плановое занятие (проекция правила на календарь)."""
    date: datetime.date
    time: Optional[datetime.time]
    seq: int                                  # порядковый номер в курсе (-1 для extra)
    lesson_number: Optional[Decimal]          # seq*step; None для extra
    status: str = PENDING
    moved_to: Optional[datetime.date] = None      # у MOVED-оригинала: куда перенесён
    moved_from: Optional[datetime.date] = None    # у перенесённого: откуда
    teacher_override_id: Optional[int] = None
    is_extra: bool = False


def _offset_from_monday(dow_sun0: int) -> int:
    """Смещение (в днях) от понедельника недели до дня недели в конвенции Вс=0.
    Пн(1)→0, Вт(2)→1, … Сб(6)→5, Вс(0)→6."""
    return 6 if dow_sun0 == 0 else dow_sun0 - 1


def _step_for(duration_minutes: int) -> Decimal:
    """Half-lesson: 45 мин → 0.5 занятия, иначе 1 (структурно, не из имени группы)."""
    return Decimal('0.5') if duration_minutes == 45 else Decimal('1')


def _walk(
    start: datetime.date,
    slots: list[Slot],
    step: Decimal,
    total: Optional[int],
    generate_until: datetime.date,
) -> list[Occurrence]:
    """
    Перебор курса по неделям от даты старта. На каждой неделе берём слоты,
    активные на конкретную дату, упорядоченные по (дата, время), инкрементим
    seq/lesson_number. Останавливаемся, когда номер превысил длину курса
    (total) ИЛИ прошли generate_until (для открытых курсов total=None).
    """
    occ: list[Occurrence] = []
    num = Decimal('0')
    seq = 0
    monday = start - datetime.timedelta(days=start.weekday())  # Пн недели старта
    weeks = 0
    while weeks < _CAP_WEEKS:
        week_cands: list[tuple[datetime.date, datetime.time]] = []
        for s in slots:
            d = monday + datetime.timedelta(days=_offset_from_monday(s.day_of_week))
            if d < start:
                continue
            if s.active_on(d):
                week_cands.append((d, s.start_time))
        week_cands.sort()
        for d, t in week_cands:
            num += step
            if total is not None and num > total:
                return occ  # курс завершён
            seq += 1
            occ.append(Occurrence(date=d, time=t, seq=seq, lesson_number=num))
        if monday > generate_until:
            break
        monday += datetime.timedelta(days=7)
        weeks += 1
    return occ


def _find(occ: list[Occurrence], date: datetime.date, time: Optional[datetime.time]):
    """Первое плановое занятие на дату (и время, если задано — дизамбигуация)."""
    for o in occ:
        if o.date == date and o.moved_from is None and not o.is_extra:
            if time is None or o.time == time:
                return o
    return None


def _apply_exceptions(base: list[Occurrence], exceptions: list[ScheduleException]) -> list[Occurrence]:
    """Наложить переносы/отмены/доп. занятия поверх базовых occurrences."""
    result = list(base)
    for e in exceptions:
        if e.kind == CANCELLED or e.kind == 'cancel':
            src = _find(result, e.original_date, e.original_time)
            if src is not None:
                src.status = CANCELLED
        elif e.kind == 'reschedule':
            src = _find(result, e.original_date, e.original_time)
            if src is not None:
                src.status = MOVED
                src.moved_to = e.new_date
            result.append(Occurrence(
                date=e.new_date,
                time=e.new_start_time or (src.time if src else None),
                seq=src.seq if src else -1,
                lesson_number=src.lesson_number if src else None,
                moved_from=e.original_date,
                teacher_override_id=e.new_teacher_id,
            ))
        elif e.kind == 'extra':
            result.append(Occurrence(
                date=e.new_date,
                time=e.new_start_time,
                seq=-1,
                lesson_number=None,
                is_extra=True,
                teacher_override_id=e.new_teacher_id,
            ))
    return result


def _attach_status(o: Occurrence, fact_dates: set, now_msk: datetime.datetime) -> None:
    """Статус занятия: cancelled/moved уже проставлены исключениями; иначе done
    (есть факт на дату) / overdue (время прошло) / pending."""
    if o.status in (CANCELLED, MOVED):
        return
    if o.date in fact_dates:
        o.status = DONE
        return
    occ_dt = datetime.datetime.combine(o.date, o.time or datetime.time(0, 0), tzinfo=MSK)
    o.status = OVERDUE if now_msk >= occ_dt else PENDING


def build_occurrences(
    *,
    start_date: Optional[datetime.date],
    duration_minutes: int,
    total_lessons: Optional[int],
    slots: list[Slot],
    exceptions: list[ScheduleException],
    fact_dates: set,
    window_from: datetime.date,
    window_to: datetime.date,
    now_msk: datetime.datetime,
) -> list[Occurrence]:
    """
    Полный конвейер для одной группы: recurrence → exceptions → статусы,
    отфильтрованный по окну [window_from, window_to] по дате отображения.

    Пустой список, если группу нельзя запланировать (нет старта/слотов) —
    признак «unscheduled» определяет вызывающий (services), чтобы отдать причину.
    """
    if start_date is None or not slots:
        return []

    step = _step_for(duration_minutes)

    # Базовые occurrences нужны минимум до конца окна И до дат, упомянутых в
    # исключениях (перенос может занести занятие в окно извне).
    ex_dates = [d for e in exceptions for d in (e.original_date, e.new_date) if d]
    generate_until = max([window_to, *ex_dates])

    base = _walk(start_date, slots, step, total_lessons, generate_until)
    occ = _apply_exceptions(base, exceptions)
    occ = [o for o in occ if window_from <= o.date <= window_to]
    for o in occ:
        _attach_status(o, fact_dates, now_msk)
    occ.sort(key=lambda o: (o.date, o.time or datetime.time(0, 0)))
    return occ
