"""API-тесты записи renewals: move (валидация переходов), patch, comment, activity."""
import pytest

from apps.renewals import engine
from apps.renewals.models import RenewalStage

BASE = '/api/admin/renewals'


def _stage_id(key):
    return RenewalStage.objects.get(key=key, pipeline__is_default=True).id


@pytest.mark.django_db
def test_move_to_decision(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('awaiting_payment')}, format='json')
    assert resp.status_code == 200
    assert resp.json()['stage_key'] == 'awaiting_payment'


@pytest.mark.django_db
def test_move_from_terminal_409(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/move', {'to_stage_id': _stage_id('churned')}, format='json')
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_onto_progress_stage_409(admin_client, make_student, make_direction):
    """Прогресс-стадии («Не было урока»/«Урок N») двигает только движок по
    событиям — ручной move на них запрещён, даже суперадмином."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/move',
                      {'to_stage_id': _stage_id('thinking')}, format='json')
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('lesson_1')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_off_progress_stage_still_allowed(admin_client, make_student, make_direction):
    """А увести сделку С прогресс-стадии вручную (например, сразу
    заморозить свежесозданную) — по-прежнему можно."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.stage.key == 'no_lesson_yet'
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 200
    assert resp.json()['stage_key'] == 'thinking'


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
    спавнит открытую сделку следующего цикла.
    """
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
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
    from django.utils import timezone
    from apps.renewals.models import RenewalDeal, RenewalPipeline
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    pipe = RenewalPipeline.objects.get(is_default=True)
    lost = RenewalStage.objects.filter(pipeline=pipe, kind='lost').first()
    RenewalDeal.objects.create(student_id=sid, cycle_no=2, pipeline=pipe,
                               stage=lost, outcome_at=timezone.now())

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
def test_comment_then_activity(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/comment', {'body': 'позвонил, думает'}, format='json')
    acts = admin_client.get(f'{BASE}/{deal.id}/activity').json()
    assert any(a['kind'] == 'comment' and a['body'] == 'позвонил, думает' for a in acts)


@pytest.mark.django_db
def test_reopen_closed_deal(admin_client, make_student, make_direction):
    """Закрытую сделку можно переоткрыть: outcome_at сбрасывается, стадия — авто."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/move',
                      {'to_stage_id': _stage_id('churned')}, format='json')
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
