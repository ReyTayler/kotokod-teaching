"""
calculator.py — порт services/calculator.js для teacher SPA.

Ставки и логика расчёта оплаты/штрафа точно копируют Node-оригинал.
Все функции работают с int (рублями), никаких Decimal — оплата у преподавателя
всегда целая (нет копеек).
"""
from __future__ import annotations

from apps.core.utils.dates import msk_today

# ---------------------------------------------------------------------------
# Ставки (PAY_RATES из calculator.js)
# ---------------------------------------------------------------------------

PAY_RATES = {
    'halfLesson': 250,    # за каждого присутствующего в полуурочном занятии
    'smallGroup': 500,    # малая группа (1-2 чел.) — все пришли
    'smallPartial': 300,  # малая группа — пришли не все
    'perStudent': 200,    # большая группа (3+ чел.) — за каждого пришедшего
}


def calculate_payment(total: int, present: int, is_half: bool = False) -> int:
    """
    Порт calculatePayment(total, present, isHalf) из calculator.js.

    Правила:
      present == 0            → 0
      isHalf                  → 250 * present
      total <= 2, все пришли  → 500
      total <= 2, часть       → 300
      total > 2               → 200 * present
    """
    if present == 0:
        return 0
    if is_half:
        return PAY_RATES['halfLesson'] * present
    if total <= 2:
        return PAY_RATES['smallGroup'] if present == total else PAY_RATES['smallPartial']
    return PAY_RATES['perStudent'] * present


def calculate_penalty(lesson_date: str, submit_date: str) -> int:
    """
    Порт calculatePenalty(lessonDate, submitDate) из calculator.js.

    Тот же день → 0, иначе → 40 ₽.
    Оба аргумента в формате 'YYYY-MM-DD'.
    """
    if lesson_date == submit_date:
        return 0
    return 40


def format_msk_date() -> str:
    """
    Порт formatMskDate() из calculator.js — сегодняшняя дата в МСК как 'YYYY-MM-DD'.

    Переиспользует apps.core.utils.dates.msk_today().
    """
    return msk_today()
