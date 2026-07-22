"""API-тесты записи renewals: move (валидация переходов), patch, comment, activity."""
import pytest

from apps.renewals import engine
from apps.renewals.models import RenewalStage

BASE = '/api/admin/renewals'


def _stage_id(key):
    return RenewalStage.objects.get(key=key, pipeline__is_default=True).id


@pytest.mark.django_db
def test_move_off_auto_stage_blocked(admin_client, make_student, make_direction):
    """Свежая сделка стоит на авто-стадии `no_lesson_yet` — увести её руками
    (даже в ручную decision «Думает») теперь нельзя: авто-стадии двигает
    только движок (решение пользователя 2026-07-17)."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.stage.key == 'no_lesson_yet'
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_from_terminal_409(admin_client, make_student, make_direction):
    """С терминальной стадии (lost) руками никуда — 409. Доводим сделку до
    lost напрямую через ORM: штатный путь закрытия (engine.decline_deal)
    добавляется в более поздней задаче плана, а руками на lost с авто-стадии
    больше не встать."""
    from django.utils import timezone
    from apps.renewals.models import RenewalDeal
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    deal.stage = RenewalStage.objects.get(key='churned', pipeline=deal.pipeline)
    deal.outcome_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at'])
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_onto_progress_stage_409(admin_client, make_student, make_direction):
    """Прогресс-стадии («Не было урока»/«Урок N») двигает только движок по
    событиям — ручной move на них запрещён, даже суперадмином."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('lesson_1')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_off_progress_stage_to_manual_decision_409(admin_client, make_student, make_direction):
    """А вот в РУЧНУЮ decision-стадию («Думает» и т.п.) со свежесозданной
    (цикл не завершён) сделки перевести нельзя — 409 (решение пользователя
    2026-07-17). Авто-стадии (в т.ч. «Ждём оплату», is_auto=True) руками не
    достижимы вовсе — их двигает только движок."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_to_won_before_cycle_completed_409(admin_client, make_student, make_direction):
    """Нельзя вручную закрыть сделку как «Продлён», пока цикл (4 урока)
    не отработан — ни с progress-стадии, ни с «Ждём оплату» (решение
    пользователя 2026-07-17)."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('renewed')}, format='json')
    assert resp.status_code == 409

    # Ставим сделку на 'Ждём оплату' напрямую через ORM (руками туда больше
    # не попасть — is_auto=True): проверяем, что и оттуда 'Продлён' до
    # завершения цикла запрещён.
    deal.stage = RenewalStage.objects.get(key='awaiting_payment', pipeline=deal.pipeline)
    deal.save(update_fields=['stage'])
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('renewed')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_to_stage_outside_pipeline_409(admin_client, make_student, make_direction):
    """to_stage_id, которого нет в воронке сделки → InvalidTransition → 409, не 500."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': 999999999}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_to_won_respawns_next_cycle(admin_client, make_student, make_direction):
    """
    Ручное продление (drag/диалог → won) — единственный путь закрытия сделки
    (оплата больше не закрывает её сама, см. signals.py): ставит outcome_at и
    спавнит открытую сделку следующего цикла. Move→won разрешён только когда
    цикл отработан (см. test_move_to_won_before_cycle_completed_409) — здесь
    это не тестируем, поэтому мокаем cycle_completed, а не городим реальную
    посещаемость (группа/членство/4 урока) ради несвязанной проверки респавна.
    """
    from unittest.mock import patch
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    # На авто-стадии move→won запрещён (from_is_auto); реальный путь «Продлён» —
    # с ручной decision-стадии. Ставим 'Думает' напрямую через ORM.
    deal.stage = RenewalStage.objects.get(key='thinking', pipeline=deal.pipeline)
    deal.save(update_fields=['stage'])
    with patch('apps.renewals.engine.cycle_completed', return_value=True):
        resp = admin_client.post(f'{BASE}/{deal.id}/move',
                                 {'to_stage_id': _stage_id('renewed')}, format='json')
    assert resp.status_code == 200
    body = resp.json()
    assert body['stage_key'] == 'renewed'
    assert body['outcome_at'] is not None
    from apps.renewals.models import RenewalDeal
    assert RenewalDeal.objects.filter(
        student_id=sid, cycle_no=2, outcome_at__isnull=True).exists()


@pytest.mark.django_db
def test_move_to_won_skips_taken_closed_cycle(admin_client, make_student, make_direction):
    """Если цикл N+1 уже занят закрытой сделкой (после reopen/возврата),
    респавн перешагивает его — открытая сделка не теряется."""
    from unittest.mock import patch
    from django.utils import timezone
    from apps.renewals.models import RenewalDeal, RenewalPipeline
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    pipe = RenewalPipeline.objects.get(is_default=True)
    lost = RenewalStage.objects.filter(pipeline=pipe, kind='lost').first()
    RenewalDeal.objects.create(student_id=sid, cycle_no=2, pipeline=pipe,
                               stage=lost, outcome_at=timezone.now())

    # На авто-стадии move→won запрещён (from_is_auto) — ставим 'Думает' через ORM.
    deal.stage = RenewalStage.objects.get(key='thinking', pipeline=pipe)
    deal.save(update_fields=['stage'])
    with patch('apps.renewals.engine.cycle_completed', return_value=True):
        resp = admin_client.post(f'{BASE}/{deal.id}/move',
                                 {'to_stage_id': _stage_id('renewed')}, format='json')
    assert resp.status_code == 200
    assert RenewalDeal.objects.filter(
        student_id=sid, cycle_no=3, outcome_at__isnull=True).exists()


@pytest.mark.django_db
def test_patch_next_touch(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.patch(f'{BASE}/{deal.id}',
                              {'next_touch_at': '2026-07-15'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['next_touch_at'] == '2026-07-15'


@pytest.mark.django_db
def test_patch_ignores_assignee_id(admin_client, make_student, make_direction):
    """assignee_id больше не патчится напрямую на сделке — единственный путь
    смены ответственного теперь через Student.manager (жёсткая синхронизация)."""
    from apps.accounts.models import Account
    from django.contrib.auth.hashers import make_password
    import uuid

    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    email = f'__test_patch_ignore_assignee__{uuid.uuid4().hex[:8]}@test.local'
    acc = Account.objects.create(
        email=email, password=make_password('x'), role='manager', is_active=True)
    resp = admin_client.patch(f'{BASE}/{deal.id}', {'assignee_id': acc.id}, format='json')
    assert resp.status_code == 200
    assert resp.json()['assignee_id'] is None


@pytest.mark.django_db
def test_comment_then_activity(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/comment', {'body': 'позвонил, думает'}, format='json')
    acts = admin_client.get(f'{BASE}/{deal.id}/activity').json()
    assert any(a['kind'] == 'comment' and a['body'] == 'позвонил, думает' for a in acts)


@pytest.mark.django_db
def test_reopen_closed_deal(admin_client, make_student, make_direction):
    """Закрытую сделку можно переоткрыть: outcome_at сбрасывается, стадия — авто."""
    from django.utils import timezone
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    # Закрываем сделку напрямую через ORM (на lost с авто-стадии руками больше не
    # встать — from_is_auto): проверяем именно переоткрытие закрытой сделки.
    deal.stage = RenewalStage.objects.get(key='churned', pipeline=deal.pipeline)
    deal.outcome_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at'])
    resp = admin_client.post(f'{BASE}/{deal.id}/reopen')
    assert resp.status_code == 200
    assert resp.json()['outcome_at'] is None


@pytest.mark.django_db
def test_reopen_open_deal_409(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/reopen')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_reopen_missing_deal_404(admin_client):
    resp = admin_client.post(f'{BASE}/999999999/reopen')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_assignees_list(manager_client):
    resp = manager_client.get(f'{BASE}/assignees')
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert all({'id', 'full_name'} <= set(r) for r in rows)


@pytest.mark.django_db
def test_assignees_forbidden_for_teacher(teacher_client):
    assert teacher_client.get(f'{BASE}/assignees').status_code == 403
