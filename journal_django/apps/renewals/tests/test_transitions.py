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


def test_move_to_won_requires_positive_balance():
    # Цикл завершён, но баланс <= 0 (долг или ровно 0) — «Продлён» запрещён:
    # продление должно быть подкреплено оплатой на следующий цикл.
    assert not is_allowed(from_kind='decision', to_kind='won',
                          cycle_completed=True, balance=0)
    assert not is_allowed(from_kind='decision', to_kind='won',
                          cycle_completed=True, balance=-2)
    assert is_allowed(from_kind='decision', to_kind='won',
                      cycle_completed=True, balance=0.5)


def test_move_to_decision_or_lost_ignores_balance():
    # Балансовый гейт относится только к «Продлён» — на прочие ручные стадии
    # долг не влияет.
    assert is_allowed(from_kind='decision', to_kind='decision',
                      cycle_completed=True, balance=-5)
    assert is_allowed(from_kind='decision', to_kind='lost',
                      cycle_completed=True, balance=-5)


def test_can_move_off_awaiting_renewal_to_won_when_cycle_completed():
    # «Ждём продление» (авто, decision) — ЕДИНСТВЕННАЯ авто-стадия, с которой
    # менеджер может уйти руками: подтвердить продление при отработанном цикле.
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='won',
                      cycle_completed=True)


def test_can_move_off_awaiting_renewal_to_manual_decision_when_completed():
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='decision',
                      cycle_completed=True)


def test_awaiting_renewal_to_lost_allowed_even_before_cycle_completed():
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='lost',
                      cycle_completed=False)


def test_awaiting_renewal_to_won_still_gated_by_cycle():
    # Даже с «Ждём продление» продлить нельзя, пока цикл не отработан.
    assert not is_allowed(from_kind='decision', from_is_auto=True,
                          from_key='awaiting_renewal', to_kind='won',
                          cycle_completed=False)


def test_other_auto_stages_still_locked_off():
    # «Ждём оплату» (авто, decision, но НЕ awaiting_renewal) — уходить руками нельзя.
    assert not is_allowed(from_kind='decision', from_is_auto=True,
                          from_key='awaiting_payment', to_kind='won',
                          cycle_completed=True)
    # progress-авто — тоже нельзя.
    assert not is_allowed(from_kind='progress', from_is_auto=True,
                          from_key='lesson_1', to_kind='lost', cycle_completed=True)


def test_frozen_allowed_mid_cycle():
    """В «Заморожен» можно уйти, не докрутив цикл — как и в «Ушёл»."""
    assert is_allowed(from_kind='progress', to_kind='decision',
                      from_is_auto=True, to_is_auto=False,
                      from_key='lesson_2', to_key='frozen',
                      cycle_completed=False) is True


def test_other_decision_still_blocked_mid_cycle():
    """Послабление касается ТОЛЬКО заморозки: «Думает» посреди цикла по-прежнему нет."""
    assert is_allowed(from_kind='progress', to_kind='decision',
                      from_is_auto=True, to_is_auto=False,
                      from_key='lesson_2', to_key='thinking',
                      cycle_completed=False) is False


def test_frozen_to_lost_allowed():
    """Со «Заморожен» всегда можно закрыть сделку как «Ушёл»."""
    assert is_allowed(from_kind='decision', to_kind='lost',
                      from_is_auto=False, to_is_auto=False,
                      from_key='frozen', to_key='churned',
                      cycle_completed=False) is True


def test_freeze_pass_requires_decision_kind():
    """Поблажки заморозке даны ей как ПРОМЕЖУТОЧНОЙ стадии, не по одному ключу.

    superadmin может сменить kind стадии key='frozen' на 'won' через настройку
    стадий. Если бы проверка шла по одному ключу, это открыло бы путь закрыть
    сделку как «Продлён» посреди цикла и с нулевым балансом, минуя оба гейта.
    """
    assert is_allowed(from_kind='progress', to_kind='won',
                      from_is_auto=True, to_is_auto=False,
                      from_key='lesson_2', to_key='frozen',
                      cycle_completed=False, balance=0) is False
    # И при завершённом цикле «Продлён» с нулевым балансом тоже не проходит.
    assert is_allowed(from_kind='decision', to_kind='won',
                      from_is_auto=False, to_is_auto=False,
                      from_key='thinking', to_key='frozen',
                      cycle_completed=True, balance=0) is False
