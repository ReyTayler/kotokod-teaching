import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

from apps.accounts.models import Account
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
def test_reminder_digest_sends(make_student, make_direction, manager_client):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)

    manager = Account.objects.get(email='__root_manager__@test.local')
    RenewalDeal.objects.filter(id=deal.id).update(
        assignee_id=manager.id, next_touch_at='2020-01-01')

    call_command('send_renewal_reminders')

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [manager.email]
    assert '__renew_test_student__' in mail.outbox[0].body


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
def test_reminder_skips_future_touch(make_student, make_direction, manager_client):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)

    manager = Account.objects.get(email='__root_manager__@test.local')
    RenewalDeal.objects.filter(id=deal.id).update(
        assignee_id=manager.id, next_touch_at='2999-01-01')

    call_command('send_renewal_reminders')

    assert len(mail.outbox) == 0
