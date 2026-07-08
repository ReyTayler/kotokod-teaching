"""
Метки операций журнала: (HTTP-метод, url) → машинный ключ операции.

Русские названия — на фронте (lib/labels.ts). Ключ 'other' — fallback
для незамапленных мутаций: журнал остаётся читаемым, событие не теряется.
Порядок правил важен: более специфичные пути выше.
"""
from __future__ import annotations

import re

# (method, compiled regex, operation)
RULES: list[tuple[str, re.Pattern, str]] = [
    # scheduling (план занятий) — до generic groups-правил
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/generate$'), 'plan.generate'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/permanent-change$'), 'plan.permanent_change'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/change-teacher-permanent$'), 'plan.change_teacher_permanent'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/extra$'), 'plan.extra'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/reschedule$'), 'plan.reschedule'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/change-teacher$'), 'plan.change_teacher'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/cancel$'), 'plan.cancel'),
    # groups
    ('POST', re.compile(r'^/api/admin/groups/\d+/schedule-change$'), 'group.schedule_change'),
    ('POST', re.compile(r'^/api/admin/groups$'), 'group.create'),
    ('PATCH', re.compile(r'^/api/admin/groups/\d+$'), 'group.update'),
    ('DELETE', re.compile(r'^/api/admin/groups/\d+$'), 'group.delete'),
    # справочники
    ('POST', re.compile(r'^/api/admin/directions$'), 'direction.create'),
    ('PATCH', re.compile(r'^/api/admin/directions/\d+$'), 'direction.update'),
    ('DELETE', re.compile(r'^/api/admin/directions/\d+$'), 'direction.delete'),
    ('POST', re.compile(r'^/api/admin/teachers$'), 'teacher.create'),
    ('PATCH', re.compile(r'^/api/admin/teachers/\d+$'), 'teacher.update'),
    ('DELETE', re.compile(r'^/api/admin/teachers/\d+$'), 'teacher.delete'),
    ('POST', re.compile(r'^/api/admin/students$'), 'student.create'),
    ('PATCH', re.compile(r'^/api/admin/students/\d+$'), 'student.update'),
    ('DELETE', re.compile(r'^/api/admin/students/\d+$'), 'student.delete'),
    ('POST', re.compile(r'^/api/admin/discounts$'), 'discount.create'),
    ('PATCH', re.compile(r'^/api/admin/discounts/\d+$'), 'discount.update'),
    ('DELETE', re.compile(r'^/api/admin/discounts/\d+$'), 'discount.delete'),
    # memberships
    ('POST', re.compile(r'^/api/admin/memberships$'), 'membership.create'),
    ('PATCH', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.update'),
    ('DELETE', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.delete'),
    # payments (immutable: только create/delete)
    ('POST', re.compile(r'^/api/admin/payments$'), 'payment.create'),
    ('DELETE', re.compile(r'^/api/admin/payments/\d+$'), 'payment.delete'),
    # lessons
    ('PATCH', re.compile(r'^/api/admin/lessons/\d+/attendance/\d+$'), 'lesson.attendance_update'),
    ('POST', re.compile(r'^/api/admin/lessons$'), 'lesson.create'),
    ('PATCH', re.compile(r'^/api/admin/lessons/\d+$'), 'lesson.update'),
    ('DELETE', re.compile(r'^/api/admin/lessons/\d+$'), 'lesson.delete'),
    # payroll / settings
    ('PATCH', re.compile(r'^/api/admin/payroll/\d+$'), 'payroll.update'),
    ('PUT', re.compile(r'^/api/admin/settings$'), 'settings.update'),
    # accounts
    ('POST', re.compile(r'^/api/admin/accounts/\d+/reset-password$'), 'account.reset_password'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/reset-2fa$'), 'account.reset_2fa'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/invite/revoke$'), 'account.invite_revoke'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/invite$'), 'account.invite_create'),
    ('POST', re.compile(r'^/api/admin/accounts$'), 'account.create'),
    ('PATCH', re.compile(r'^/api/admin/accounts/\d+$'), 'account.update'),
    ('DELETE', re.compile(r'^/api/admin/accounts/\d+$'), 'account.delete'),
    # renewals (стадии-справочник — до generic deal-правил)
    ('POST', re.compile(r'^/api/admin/renewals/stages/reorder$'), 'renewal.stage_reorder'),
    ('POST', re.compile(r'^/api/admin/renewals/stages$'), 'renewal.stage_create'),
    ('PATCH', re.compile(r'^/api/admin/renewals/stages/\d+$'), 'renewal.stage_update'),
    ('DELETE', re.compile(r'^/api/admin/renewals/stages/\d+$'), 'renewal.stage_delete'),
    ('POST', re.compile(r'^/api/admin/renewals/rebuild$'), 'renewal.rebuild'),
    ('POST', re.compile(r'^/api/admin/renewals/\d+/move$'), 'renewal.move'),
    ('POST', re.compile(r'^/api/admin/renewals/\d+/comment$'), 'renewal.comment'),
    ('PATCH', re.compile(r'^/api/admin/renewals/\d+$'), 'renewal.update'),
    # teacher SPA
    ('POST', re.compile(r'^/api/submitLesson$'), 'lesson.submit'),
    # auth-мутации данных (2FA-поля Account меняет сам пользователь)
    ('POST', re.compile(r'^/api/auth/2fa/enable$'), 'account.twofa_enable'),
    ('POST', re.compile(r'^/api/auth/2fa/disable$'), 'account.twofa_disable'),
    ('POST', re.compile(r'^/api/auth/invite/accept$'), 'account.invite_accept'),
]

FALLBACK = 'other'


def resolve_operation(method: str, url: str) -> str:
    """Ключ операции по методу и пути. У вызывающего metadata['operation']
    имеет приоритет (например 'changelog.revert' проставляется сервисом)."""
    for rule_method, pattern, operation in RULES:
        if method == rule_method and pattern.match(url):
            return operation
    return FALLBACK


def rule_for_operation(operation: str):
    """Обратный поиск для фильтра ленты: operation → (method, regex) или None."""
    for rule_method, pattern, rule_operation in RULES:
        if rule_operation == operation:
            return rule_method, pattern
    return None
