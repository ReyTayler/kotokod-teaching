"""Правило переходов: НИ ОДНА авто-стадия не достижима и не покидается руками —
их двигает только движок. Ручные decision→decision/won/lost — при завершённом цикле."""
from apps.renewals.transitions import is_allowed


def test_cannot_move_onto_any_auto_stage():
    # decision-авто (Ждём оплату/Ждём продление/Заморожен) — руками нельзя
    assert not is_allowed(from_kind='decision', to_kind='decision',
                          to_is_auto=True, cycle_completed=True)
    # progress-авто — тоже нельзя
    assert not is_allowed(from_kind='decision', to_kind='progress',
                          to_is_auto=True, cycle_completed=True)


def test_cannot_move_off_auto_stage_even_to_lost():
    # с авто-стадии (напр. Урок 1) руками никуда, включая Ушёл
    assert not is_allowed(from_kind='progress', from_is_auto=True,
                          to_kind='lost', to_is_auto=False, cycle_completed=True)


def test_manual_decision_to_lost_allowed_anytime():
    assert is_allowed(from_kind='decision', from_is_auto=False,
                      to_kind='lost', to_is_auto=False, cycle_completed=False)


def test_manual_decision_to_decision_needs_completed_cycle():
    assert not is_allowed(from_kind='decision', from_is_auto=False,
                          to_kind='decision', to_is_auto=False, cycle_completed=False)
    assert is_allowed(from_kind='decision', from_is_auto=False,
                      to_kind='decision', to_is_auto=False, cycle_completed=True)


def test_manual_decision_to_won_needs_completed_cycle():
    # «Продлён» из ручной decision-стадии — тоже под гейтом cycle_completed,
    # не только decision→decision (test_api_write.py проверяет это end-to-end
    # с авто-стадии, где срабатывает from_is_auto раньше — здесь закрываем
    # ветку decision→won напрямую, минуя auto-lockout).
    assert not is_allowed(from_kind='decision', from_is_auto=False,
                          to_kind='won', cycle_completed=False)
    assert is_allowed(from_kind='decision', from_is_auto=False,
                      to_kind='won', cycle_completed=True)


def test_from_terminal_never_allowed():
    assert not is_allowed(from_kind='won', to_kind='decision', cycle_completed=True)
