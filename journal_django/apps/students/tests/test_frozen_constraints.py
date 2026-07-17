"""DB CHECK-инварианты новой пары frozen_from/frozen_until на модели Student."""
import datetime

import pytest
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.students.models import Student


@pytest.mark.django_db
def test_frozen_requires_both_dates():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__frz_no_dates__', enrollment_status='frozen',
                frozen_from=None, frozen_until=None, created_at=Now())


@pytest.mark.django_db
def test_non_frozen_forbids_dates():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__enr_with_dates__', enrollment_status='enrolled',
                frozen_from=datetime.date(2026, 1, 1),
                frozen_until=datetime.date(2026, 2, 1), created_at=Now())


@pytest.mark.django_db
def test_from_must_not_exceed_until():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__frz_bad_order__', enrollment_status='frozen',
                frozen_from=datetime.date(2026, 3, 1),
                frozen_until=datetime.date(2026, 2, 1), created_at=Now())


@pytest.mark.django_db
def test_valid_frozen_ok():
    s = Student.objects.create(
        full_name='__frz_ok__', enrollment_status='frozen',
        frozen_from=datetime.date(2026, 2, 1),
        frozen_until=datetime.date(2026, 4, 1), created_at=Now())
    assert s.id is not None
