"""
Вычисление номера цикла продления и признака «окно продления».

Цикл = 1 оплаченный месяц = 4 урока (LESSONS_PER_CYCLE). Half-lesson (0.5)
уже учтён в attended (numeric), поэтому floor по 4 корректен.
"""
from __future__ import annotations

import math

LESSONS_PER_CYCLE = 4


def cycle_no_from_attended(attended: float) -> int:
    """attended отработанных уроков по направлению → номер текущего цикла (1-based)."""
    return math.floor(float(attended) / LESSONS_PER_CYCLE) + 1


def in_renewal_window(remaining: float, balance: float) -> bool:
    """Окно продления: остался ≤1 урок ИЛИ баланс отработан (≤0)."""
    return float(remaining) <= 1 or float(balance) <= 0
