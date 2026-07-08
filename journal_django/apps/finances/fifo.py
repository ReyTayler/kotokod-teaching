"""
FIFO-оценка денег по партиям-оплатам. Чистая функция, без БД и побочных эффектов.

Дословный порт services/fifo.js computeFifo на Decimal (бухгалтерская точность,
см. память feedback_financial_accounting_precision):
  • все суммы — Decimal, через to_decimal(str(x));
  • деления/умножения точные, округление до копеек (ROUND_HALF_UP) — один раз на выходе;
  • цена урока партии = total_amount / (subscriptions_count × 4) (считает вызывающий);
  • строгий FIFO: старая партия гасится первой;
  • месяц — полуинтервал [month_start, month_end) (month_end эксклюзивный, как в Node).

ИЗВЕСТНОЕ РАСХОЖДЕНИЕ С EXPRESS (решение пользователя 2026-06-10): Express копит
суммы во float и округляет один раз; этот порт копит в точном Decimal. На ~4 из 248
ключей student:direction worked_off_by_month расходится с Express на ≤1 копейку в
ИСТОРИЧЕСКИХ месяцах (текущий месяц, balance, remaining_value совпадают). Django —
арифметически точнее; разница float-артефакт Express. По брифу 02 и памяти
feedback_financial_accounting_precision выбран Decimal. Следствие: e2e-diff
dashboard getMonthlyFinance не будет байт-пустым в нескольких исторических ячейках.

lots:         [{ 'lessons': n, 'price_per_lesson': Decimal }]  — в порядке оплаты (старые первыми).
consumptions: [{ 'units': 1|0.5, 'date': 'YYYY-MM-DD', 'direction_id': int|None }] — в порядке даты урока.
              direction_id — направление УРОКА (не оплаты), опционально (может отсутствовать).

Возврат (Decimal, округлены до копеек):
  worked_off_total, worked_off_month, remaining_value, over_consumed_lessons,
  worked_off_by_month: { 'YYYY-MM': Decimal }, worked_off_by_direction: { direction_id: Decimal }.
"""
from __future__ import annotations

from decimal import Decimal

from apps.core.utils.decimal import round_kopecks, to_decimal

_ZERO = Decimal('0')


def compute_fifo(lots, consumptions, month_start: str, month_end: str) -> dict:
    """
    Порт computeFifo (services/fifo.js) на Decimal.

    Семантика идентична Node: индекс текущей партии lot_idx, остаток lot_remaining;
    каждое посещение гасится из партий по FIFO, недостача → over_consumed_lessons.
    Каждая запись consumption может нести 'direction_id' (направление урока) —
    используется только для атрибуции worked_off_by_direction в отчётах, партию
    FIFO-очереди это не меняет (лоты и посещения уже приходят единым пулом на
    ученика — см. apps/finances/repository.py::fifo_inputs).
    """
    lot_idx = 0
    lot_remaining = to_decimal(lots[0]['lessons']) if lots else _ZERO
    worked_off_total = _ZERO
    worked_off_month = _ZERO
    over_consumed_lessons = _ZERO
    by_month: dict[str, Decimal] = {}
    by_direction: dict = {}

    for c in consumptions:
        need = to_decimal(c['units'])
        # Полуинтервал [month_start, month_end); сравнение строк 'YYYY-MM-DD' = хронологическое.
        in_month = month_start <= c['date'] < month_end
        direction_id = c.get('direction_id')
        while need > 0 and lot_idx < len(lots):
            if lot_remaining <= 0:
                lot_idx += 1
                if lot_idx >= len(lots):
                    break
                lot_remaining = to_decimal(lots[lot_idx]['lessons'])
                continue
            take = need if need < lot_remaining else lot_remaining  # min(need, lot_remaining)
            value = take * to_decimal(lots[lot_idx]['price_per_lesson'])
            worked_off_total += value
            ym = c['date'][:7]
            by_month[ym] = by_month.get(ym, _ZERO) + value
            if direction_id is not None:
                by_direction[direction_id] = by_direction.get(direction_id, _ZERO) + value
            if in_month:
                worked_off_month += value
            lot_remaining -= take
            need -= take
        if need > 0:
            over_consumed_lessons += need

    remaining_value = _ZERO
    if lot_idx < len(lots):
        remaining_value += lot_remaining * to_decimal(lots[lot_idx]['price_per_lesson'])
        for i in range(lot_idx + 1, len(lots)):
            remaining_value += to_decimal(lots[i]['lessons']) * to_decimal(lots[i]['price_per_lesson'])

    return {
        'worked_off_total': round_kopecks(worked_off_total),
        'worked_off_month': round_kopecks(worked_off_month),
        'remaining_value': round_kopecks(remaining_value),
        'over_consumed_lessons': round_kopecks(over_consumed_lessons),
        'worked_off_by_month': {k: round_kopecks(v) for k, v in by_month.items()},
        'worked_off_by_direction': {k: round_kopecks(v) for k, v in by_direction.items()},
    }
