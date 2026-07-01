"""
Models for payments — managed=False, поверх существующей БД.

Таблица:
  payments — финансовые записи оплат (immutable: только POST/DELETE)

Схема из db/migrations/008_payments.sql + 009_payments_legacy.sql.
После 009 direction_id и subscriptions_count nullable (легаси-оплаты без направления).
FK student_id/direction_id → ON DELETE RESTRICT (защита истории оплат от хард-удаления).
"""
from __future__ import annotations

from django.db import models


class Payment(models.Model):
    """
    Оплата. Соответствует таблице `payments`.

    Инварианты БД (CHECK): subscriptions_count > 0 (если задан);
    total_amount = unit_price * subscriptions_count (если subscriptions_count NOT NULL).
    """

    id = models.AutoField(primary_key=True)
    # FK → students(id), ON DELETE RESTRICT.
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.RESTRICT,
        db_column='student_id',
        related_name='payments',
    )
    # FK → directions(id), ON DELETE RESTRICT, nullable (легаси-оплаты).
    direction = models.ForeignKey(
        'directions.Direction',
        on_delete=models.RESTRICT,
        db_column='direction_id',
        related_name='payments',
        null=True,
        blank=True,
    )
    subscriptions_count = models.IntegerField(null=True, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_at = models.DateField()
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()
    created_by = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'payments'
        indexes = [
            models.Index(fields=['student'], name='payments_student_idx'),
            models.Index(fields=['direction'], name='payments_direction_idx'),
            models.Index(fields=['paid_at'], name='payments_paid_at_idx'),
            models.Index(fields=['-paid_at', '-id'], name='payments_paid_at_desc_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='payments_subscriptions_count_check',
                condition=models.Q(subscriptions_count__gt=0),
            ),
            models.CheckConstraint(
                name='payments_unit_price_check',
                condition=models.Q(unit_price__gte=0),
            ),
            models.CheckConstraint(
                name='payments_direction_count_match',
                condition=(
                    (models.Q(direction__isnull=True) & models.Q(subscriptions_count__isnull=True))
                    | (models.Q(direction__isnull=False) & models.Q(subscriptions_count__isnull=False)
                       & models.Q(subscriptions_count__gt=0))
                ),
            ),
            models.CheckConstraint(
                name='payments_total_match',
                condition=(
                    models.Q(subscriptions_count__isnull=True)
                    | models.Q(total_amount=models.F('unit_price') * models.F('subscriptions_count'))
                ),
            ),
        ]
