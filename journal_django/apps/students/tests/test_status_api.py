"""API смены статуса: POST /status (frozen/declined/...), POST /resume. Права
IsManagerOrAdmin; frozen требует обе даты (400 иначе)."""
import datetime

import pytest
from django.db.models.functions import Now

from apps.students.models import Student

BASE = '/api/admin/students'


@pytest.mark.django_db
def test_freeze_requires_both_dates_400(admin_client):
    s = Student.objects.create(full_name='__api_frz__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status',
                             {'status': 'frozen', 'frozen_from': '2026-07-08'},
                             format='json')
    assert resp.status_code == 400
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_change_declined_200(admin_client):
    s = Student.objects.create(full_name='__api_dec__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 200
    assert Student.objects.get(id=s.id).enrollment_status == 'declined'
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_404_unknown_student(admin_client):
    resp = admin_client.post(f'{BASE}/99999999/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_resume_requires_frozen(admin_client):
    s = Student.objects.create(full_name='__api_res__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/resume',
                             {'actual_resume_date': '2026-08-05'}, format='json')
    assert resp.status_code == 404  # не заморожен → нечего размораживать
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_enrolled_on_frozen_returns_400(admin_client):
    """change_student_status запрещает прямой frozen→enrolled (ValueError) —
    API обязан вернуть 400, а не 500."""
    s = Student.objects.create(
        full_name='__api_frz2enr__', enrollment_status='frozen',
        frozen_from=datetime.date(2026, 7, 8), frozen_until=datetime.date(2026, 8, 5),
        created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status', {'status': 'enrolled'}, format='json')
    assert resp.status_code == 400
    Student.objects.filter(id=s.id).delete()
