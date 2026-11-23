"""Датированные групповые ставки. Изменения действуют с сегодня (МСК)."""
import datetime

from rest_framework.exceptions import ValidationError
from django.db import transaction

from apps.payroll.group_engine import GroupRateCard, group_lesson_pay
from apps.payroll.engine import LessonInput
from apps.payroll.models import GroupPayRateVersion
from apps.payroll.motivation import (
    DUPLICATE_VERSION_DATE, _check_not_past, _check_not_started, _creator_name,
    _guarded, _lock_rate_versions, _today,
)
from apps.payroll.recalc import recalculate_group_rates

FIELDS = tuple(name for name in GroupRateCard.__dataclass_fields__ if name != 'id')


def _row(version, today, current_id):
    return {**{name: getattr(version, name) for name in ('id', *FIELDS)},
            'is_current': version.id == current_id,
            'editable': version.effective_from >= today,
            'created_by_name': _creator_name(version.created_by),
            'created_at': version.created_at}


def list_versions():
    versions = list(GroupPayRateVersion.objects.select_related('created_by'))
    today = _today()
    current = next((v.id for v in versions if v.effective_from <= today), None)
    return {'results': [_row(v, today, current) for v in versions]}


def _error(name):
    if name and 'effective_from' in name:
        return {'effective_from': [DUPLICATE_VERSION_DATE]}
    return None


def _period_end(day, exclude_id):
    nxt = (GroupPayRateVersion.objects.filter(effective_from__gt=day)
           .exclude(id=exclude_id).order_by('effective_from').first())
    return nxt.effective_from - datetime.timedelta(days=1) if nxt else None


def save_version(data, account=None, version_id=None):
    with transaction.atomic():
        # Общий с индивидуальными ставками замок — до чтения соседей и уроков.
        _lock_rate_versions()
        today = _today()
        if version_id is None:
            version = GroupPayRateVersion(created_by=account)
            old_from = data['effective_from']
        else:
            version = GroupPayRateVersion.objects.filter(id=version_id).first()
            if version is None:
                return None
            _check_not_started(version, today)
            old_from = version.effective_from
        for name, value in data.items():
            setattr(version, name, value)
        _check_not_past(version.effective_from, today)
        _guarded(version.save, _error)
        stats = recalculate_group_rates(
            date_from=min(old_from, version.effective_from),
            date_to=_period_end(max(old_from, version.effective_from), version.id), today=today)
        current = (GroupPayRateVersion.objects.filter(effective_from__lte=today)
                   .order_by('-effective_from').values_list('id', flat=True).first())
        result = _row(version, today, current)
    return {**result, 'recalculated': stats['changed']}


def delete_version(version_id):
    with transaction.atomic():
        _lock_rate_versions()
        today = _today()
        version = GroupPayRateVersion.objects.filter(id=version_id).first()
        if version is None:
            return None
        _check_not_started(version, today)
        start = version.effective_from
        end = _period_end(start, version.id)
        version.delete()
        stats = recalculate_group_rates(date_from=start, date_to=end, today=today)
    return {'recalculated': stats['changed']}


def preview(data):
    """Примеры считает тот же движок, который начисляет зарплату."""
    card = GroupRateCard.from_version(GroupPayRateVersion(id=0, **data))
    limit = card.small_group_limit
    cases = [(limit, limit, 60)]
    if limit > 1:
        # «Пришла часть» малой группы возможна только при limit ≥ 2: при limit=1
        # это ноль присутствующих — повтор случая «никто не пришёл» ниже.
        cases.append((limit, limit - 1, 60))
    cases += [(limit + 1, limit, 60), (limit + 1, limit, 45), (limit + 1, 0, 60)]
    results = []
    # dict.fromkeys — дедуп с сохранением порядка на случай совпадения примеров.
    for total, present, minutes in dict.fromkeys(cases):
        lesson = LessonInput(teacher_id=0, group_id=0, lesson_date=card.effective_from,
                             lesson_number=1, is_individual=False, direction_id=None,
                             direction_name=None, submitted_at=None, submitted_by_token=None,
                             present_count=present, total_students=total, duration_minutes=minutes)
        result = group_lesson_pay(lesson, card)
        results.append({'total': total, 'present': present, 'minutes': minutes,
                        'payment': result.payment, 'rule_note': result.rule_note})
    return {'results': results}
