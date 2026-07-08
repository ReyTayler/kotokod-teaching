import pytest
from apps.renewals import cycle


@pytest.mark.django_db
def test_cycle_no_from_attended():
    assert cycle.cycle_no_from_attended(0) == 1
    assert cycle.cycle_no_from_attended(3.5) == 1
    assert cycle.cycle_no_from_attended(4) == 2
    assert cycle.cycle_no_from_attended(7.5) == 2
    assert cycle.cycle_no_from_attended(8) == 3


def test_in_renewal_window():
    assert cycle.in_renewal_window(remaining=1, balance=5) is True
    assert cycle.in_renewal_window(remaining=3, balance=0) is True
    assert cycle.in_renewal_window(remaining=3, balance=5) is False
