"""
Модели зарплат преподавателей.

`Payroll` — начисление за проведённый урок (1:1 с lessons), исторически
managed=False поверх таблицы `payroll` (db/migrations/001_initial_schema.sql),
сейчас managed=True. numeric-поля рендерятся строкой с масштабом ('500.00') —
DateSafeJSONRenderer.

Слой «Мотивации» (перенос из Eduson, спека
docs/superpowers/specs/2026-11-18-motivation-individual-design.md).
Индивидуальные занятия используют PayRateVersion, групповые — независимую
GroupPayRateVersion; обе действуют только с даты первой соответствующей версии.
Даты без соответствующей версии считает прежний движок
(apps/payroll/calculator.py):
  PayRateVersion / PayRateDirection — датированные ставки школы для индива;
  PersonalRate / PersonalRateTerm — персональные ставки «преподаватель × группа»
    и их периоды действия (правки не меняют прошлое);
  CancellationPay — начисление за отменённое занятие индива (1:1 с маркером отмены).
Правил расчёта здесь нет — только данные и их инварианты в БД: движок пишет
строки bulk-операциями мимо full_clean, поэтому деньги ≥ 0, диапазоны и режимы
держат CHECK-ограничения PostgreSQL.
"""
from __future__ import annotations

import pghistory
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import (
    DateRangeField,
    DecimalRangeField,
    RangeBoundary,
    RangeOperators,
)
from django.db import models
from django.utils import timezone
from apps.core.db_fields import TolerantJSONField

# Имена ограничений персональных ставок — по ним сервис узнаёт нарушение
# (apps/payroll/motivation.py) и отвечает 400 с понятным текстом.
PERSONAL_ALL_EXCLUDE = 'payroll_personal_terms_all_excl'
PERSONAL_RANGES_EXCLUDE = 'payroll_personal_terms_ranges_excl'
PERSONAL_RANGE_CHECK = 'payroll_personal_terms_range_check'
PERSONAL_PERIOD_CHECK = 'payroll_personal_terms_period_check'


class NumRange(models.Func):
    """numrange(from, to, '[]') — замкнутый диапазон номеров уроков."""

    function = 'NUMRANGE'
    output_field = DecimalRangeField()


class TermPeriod(models.Func):
    """daterange(valid_from, valid_until, '[)') — период действия терма;
    NULL-граница бесконечна. Без аргументов: выражение одно на оба EXCLUDE."""

    function = 'DATERANGE'
    output_field = DateRangeField()

    def __init__(self, **extra):
        super().__init__('valid_from', 'valid_until', RangeBoundary(
            inclusive_lower=True, inclusive_upper=False), **extra)


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Payroll(models.Model):
    """Запись расчётного листа по уроку (1:1 с lessons)."""

    id = models.AutoField(primary_key=True)
    # FK → lessons(id), UNIQUE в БД → 1:1 (OneToOne). NO ACTION → DO_NOTHING.
    lesson = models.OneToOneField(
        'lessons.Lesson',
        on_delete=models.DO_NOTHING,
        db_column='lesson_id',
        related_name='payroll',
    )
    # FK → teachers(id). NO ACTION в БД → DO_NOTHING (managed=False).
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='teacher_id',
        related_name='payroll_entries',
    )
    total_students = models.IntegerField()
    present_count = models.IntegerField()
    payment = models.DecimalField(max_digits=10, decimal_places=2)
    penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Ручная правка суммы (PATCH из админки) урока «Мотивации»: пересчёт такую
    # строку не трогает, обновляет только calc_* — рядом с правкой видна
    # расчётная сумма. У уроков прежнего движка флаг не ставится.
    # db_default у всех четырёх полей: таблица уже с данными, NOT NULL-колонке
    # нужен DEFAULT в самой БД (его же получат сырые INSERT старых путей).
    is_manual = models.BooleanField(default=False, db_default=False)
    calc_payment = models.DecimalField(max_digits=10, decimal_places=2,
                                       default=0, db_default=0)
    calc_penalty = models.DecimalField(max_digits=10, decimal_places=2,
                                       default=0, db_default=0)
    # Какое правило «Мотивации» сработало. Пусто — урок посчитан прежним
    # движком (дата без версии ставок); пояснение тогда
    # строит apps/payroll/explain.py сверкой с калькулятором.
    rule_note = models.TextField(default='', db_default='')
    # Снимок группового расчёта: версия, параметры и исходные данные урока.
    group_rate_snapshot = TolerantJSONField(default=dict, db_default={})

    class Meta:
        managed = True
        db_table = 'payroll'
        indexes = [
            models.Index(fields=['teacher', 'lesson'], name='payroll_teacher_lesson_idx'),
            models.Index(fields=['lesson'], name='payroll_lesson_id_idx'),
        ]


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class PayRateVersion(models.Model):
    """
    Версия ставок школы для индивидуального формата, действующая с
    effective_from до следующей версии.

    Урок и отмена индива считаются по версии, действовавшей на их дату. Сами поля —
    строка «По умолчанию»; ставки направлений — PayRateDirection. Отработка,
    сгорание, отмена и штраф — общие для школы, по направлениям не делятся.
    Групповые ставки хранятся отдельно в GroupPayRateVersion.
    """

    class CancelMode(models.TextChoices):
        PERCENT = 'percent', 'Процент от ставки'
        FIXED = 'fixed', 'Фиксированная сумма'

    class PenaltyMode(models.TextChoices):
        PER_LESSON = 'per_lesson', 'За урок'
        PER_STUDENT = 'per_student', 'За каждого присутствовавшего'

    id = models.AutoField(primary_key=True)
    # UNIQUE: две версии с одной датой сделали бы выбор «действующей» неоднозначным.
    # Индекс уникальности заодно обслуживает поиск «последняя версия ≤ даты».
    effective_from = models.DateField(unique=True)
    # Урок индива (и доп.урок сверх курса) — фикс за занятие, длительность не влияет.
    individual_rate = models.DecimalField(max_digits=10, decimal_places=2)
    # Отработка пропуска (доп.урок за пропущенное занятие) — фикс за занятие.
    makeup_rate = models.DecimalField(max_digits=10, decimal_places=2)
    # Сгорание пропуска (урок списан без занятия) — фикс за сгорание.
    burned_rate = models.DecimalField(max_digits=10, decimal_places=2)
    cancel_mode = models.TextField(choices=CancelMode.choices)
    # percent — проценты (0..100) от ставки урока; fixed — рубли.
    cancel_value = models.DecimalField(max_digits=10, decimal_places=2)
    penalty_enabled = models.BooleanField(default=False)
    penalty_mode = models.TextField(choices=PenaltyMode.choices,
                                    default=PenaltyMode.PER_LESSON)
    penalty_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # SET_NULL: удаление учётки не должно уносить ставки, по которым считаны деньги.
    created_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='created_by_id', related_name='+',
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = 'payroll_rate_versions'
        ordering = ['-effective_from']
        constraints = [
            models.CheckConstraint(
                name='payroll_rate_versions_rates_check',
                condition=(models.Q(individual_rate__gte=0) & models.Q(makeup_rate__gte=0)
                           & models.Q(burned_rate__gte=0)),
            ),
            models.CheckConstraint(
                name='payroll_rate_versions_cancel_mode_check',
                condition=models.Q(cancel_mode__in=['percent', 'fixed']),
            ),
            # Потолок 100 — только у процента: фиксированная сумма в рублях
            # законно больше 100.
            models.CheckConstraint(
                name='payroll_rate_versions_cancel_value_check',
                condition=models.Q(cancel_value__gte=0) & (
                    ~models.Q(cancel_mode='percent') | models.Q(cancel_value__lte=100)
                ),
            ),
            models.CheckConstraint(
                name='payroll_rate_versions_penalty_mode_check',
                condition=models.Q(penalty_mode__in=['per_lesson', 'per_student']),
            ),
            models.CheckConstraint(
                name='payroll_rate_versions_penalty_amount_check',
                condition=models.Q(penalty_amount__gte=0),
            ),
        ]

    def __str__(self) -> str:
        return f'Ставки с {self.effective_from}'


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class PayRateDirection(models.Model):
    """
    Ставка индива направления внутри версии. Строки нет = «как по умолчанию»:
    так новое направление сразу считается по ставке версии.
    """

    id = models.AutoField(primary_key=True)
    version = models.ForeignKey(
        PayRateVersion, on_delete=models.CASCADE,
        db_column='version_id', related_name='directions',
        # Покрыт префиксом UNIQUE(version, direction).
        db_index=False,
    )
    # PROTECT: направление со ставкой в истории версий молча не удаляется —
    # пересчёт прошлых периодов потерял бы ставку. Направления и так архивируют.
    direction = models.ForeignKey(
        'directions.Direction', on_delete=models.PROTECT,
        db_column='direction_id', related_name='pay_rates',
    )
    individual_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = True
        db_table = 'payroll_rate_directions'
        constraints = [
            models.UniqueConstraint(fields=['version', 'direction'],
                                    name='payroll_rate_directions_version_direction_uniq'),
            models.CheckConstraint(
                name='payroll_rate_directions_rates_check',
                condition=models.Q(individual_rate__gte=0),
            ),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class GroupPayRateVersion(models.Model):
    """Независимая история групповых ставок. Схема v1 повторяет calculator.py."""

    effective_from = models.DateField(unique=True)
    calculation_method = models.CharField(max_length=40, default='attendance_v1',
                                         choices=[('attendance_v1', 'По составу и посещаемости')])
    small_group_limit = models.PositiveSmallIntegerField(default=2)
    small_full_rate = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    small_partial_rate = models.DecimalField(max_digits=10, decimal_places=2, default=300)
    per_student_rate = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    half_lesson_rate = models.DecimalField(max_digits=10, decimal_places=2, default=250)
    makeup_rate = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    burned_rate = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    penalty_enabled = models.BooleanField(default=True)
    penalty_mode = models.CharField(max_length=20, default='per_student',
                                   choices=PayRateVersion.PenaltyMode.choices)
    penalty_amount = models.DecimalField(max_digits=10, decimal_places=2, default=40)
    created_by = models.ForeignKey('accounts.Account', on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'payroll_group_rate_versions'
        ordering = ['-effective_from']
        constraints = [
            models.CheckConstraint(name='group_rates_method_check',
                                   condition=models.Q(calculation_method='attendance_v1')),
            models.CheckConstraint(name='group_rates_limit_check',
                                   condition=models.Q(small_group_limit__gte=1)),
            models.CheckConstraint(name='group_rates_money_check', condition=(
                models.Q(small_full_rate__gte=0) & models.Q(small_partial_rate__gte=0)
                & models.Q(per_student_rate__gte=0) & models.Q(half_lesson_rate__gte=0)
                & models.Q(makeup_rate__gte=0) & models.Q(burned_rate__gte=0)
                & models.Q(penalty_amount__gte=0))),
            models.CheckConstraint(name='group_rates_penalty_check',
                                   condition=models.Q(penalty_mode__in=['per_student', 'per_lesson'])),
        ]


class PersonalRateKind(models.TextChoices):
    FIXED = 'fixed', 'Вместо ставки'
    PLUS_FIXED = 'plus_fixed', 'Надбавка, ₽'
    PLUS_PERCENT = 'plus_percent', 'Надбавка, %'


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class PersonalRate(models.Model):
    """
    Персональная ставка — сущность «преподаватель × индивидуальная группа».

    Сами параметры (уроки, вид, значение) живут в периодах PersonalRateTerm:
    правка, выключение и удаление ставки действуют только с сегодняшнего дня,
    поэтому прежние параметры не перезаписываются, а закрываются датой — прошлые
    начисления при любом последующем пересчёте считаются по ним же. Колонок
    параметров здесь нет намеренно: два источника правды разошлись бы.

    is_active — переключатель «включена / выключена» (у включённой последний
    период открыт, у выключенной закрыт). deleted_at — мягкое удаление: ставка
    скрыта из списка, а её закрытые периоды продолжают считать прошлое.
    Преподаватель и группа неизменны: у истории другой смысл, для другой пары
    заводят новую ставку.
    """

    Kind = PersonalRateKind

    id = models.AutoField(primary_key=True)
    # CASCADE: жёсткое удаление преподавателя уносит его персональные ставки —
    # начислений в них нет (деньги живут в Payroll/CancellationPay), а ставка
    # без преподавателя бессмысленна.
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.CASCADE,
        db_column='teacher_id', related_name='personal_rates',
    )
    group = models.ForeignKey(
        'groups.Group', on_delete=models.CASCADE,
        db_column='group_id', related_name='personal_rates',
        # Покрыт префиксом составного payroll_personal_group_tch_idx.
        db_index=False,
    )
    note = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='created_by_id', related_name='+',
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = 'payroll_personal_rates'
        indexes = [
            # Список фильтрует по группе и преподавателю.
            models.Index(fields=['group', 'teacher'],
                         name='payroll_personal_group_tch_idx'),
        ]


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class PersonalRateTerm(models.Model):
    """
    Период действия персональной ставки.

    Действует на дату d, если valid_from ≤ d < valid_until; NULL-граница — без
    границы. valid_until НЕ включительно: закрытие «сегодня» значит, что
    сегодняшние уроки уже считаются без этого периода. Пустой период
    (valid_from = valid_until) допустим: так хранятся параметры ставки,
    созданной и выключенной в один день, — иначе при включении их неоткуда
    было бы взять. Пустой период не действует ни на одну дату и ни с чем не
    пересекается.

    lesson_from/lesson_to — диапазон номеров урока курса (numeric 5,1, как
    Lesson.lesson_number); оба NULL — «все уроки группы».

    teacher и group — копия пары из ставки: по ним БД держит непересечение
    периодов пары преподаватель × группа (EXCLUDE видит только свою строку).
    Копию пишет только сервис (apps/payroll/motivation.py), пара у ставки
    неизменна. Непересечение:
      * два периода «все уроки» не пересекаются по датам — EXCLUDE …_all_excl;
      * два периода с диапазоном не пересекаются одновременно по урокам и по
        датам — EXCLUDE …_ranges_excl.
    «Все уроки» + диапазон на одни даты — законно: диапазон точнее и побеждает.
    """

    Kind = PersonalRateKind

    id = models.AutoField(primary_key=True)
    rate = models.ForeignKey(
        PersonalRate, on_delete=models.CASCADE,
        db_column='rate_id', related_name='terms',
    )
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.CASCADE,
        db_column='teacher_id', related_name='+',
        # Покрыт gist-индексами ограничений непересечения.
        db_index=False,
    )
    group = models.ForeignKey(
        'groups.Group', on_delete=models.CASCADE,
        db_column='group_id', related_name='+',
        # Покрыт префиксом составного payroll_personal_term_grp_idx.
        db_index=False,
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    lesson_from = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    lesson_to = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    kind = models.TextField(choices=PersonalRateKind.choices)
    # fixed / plus_fixed — рубли; plus_percent — проценты от ставки формата.
    value = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = True
        db_table = 'payroll_personal_rate_terms'
        indexes = [
            # Движок грузит периоды по группам пересчёта.
            models.Index(fields=['group', 'teacher'],
                         name='payroll_personal_term_grp_idx'),
        ]
        constraints = [
            # «Все уроки» (оба NULL) либо замкнутый диапазон from ≤ to, from ≥ 0.
            models.CheckConstraint(
                name=PERSONAL_RANGE_CHECK,
                condition=(
                    models.Q(lesson_from__isnull=True, lesson_to__isnull=True)
                    | models.Q(lesson_from__isnull=False, lesson_to__isnull=False,
                               lesson_from__gte=0, lesson_from__lte=models.F('lesson_to'))
                ),
            ),
            # ≤, а не <: пустой период законен (см. docstring).
            models.CheckConstraint(
                name=PERSONAL_PERIOD_CHECK,
                condition=(models.Q(valid_from__isnull=True) | models.Q(valid_until__isnull=True)
                           | models.Q(valid_from__lte=models.F('valid_until'))),
            ),
            models.CheckConstraint(
                name='payroll_personal_terms_kind_check',
                condition=models.Q(kind__in=['fixed', 'plus_fixed', 'plus_percent']),
            ),
            models.CheckConstraint(
                name='payroll_personal_terms_value_check',
                condition=models.Q(value__gte=0),
            ),
            # Равенство по teacher/group в gist-индексе — расширение btree_gist
            # (миграция 0005). daterange(NULL, …) — граница бесконечна.
            ExclusionConstraint(
                name=PERSONAL_ALL_EXCLUDE,
                expressions=[
                    ('teacher', RangeOperators.EQUAL),
                    ('group', RangeOperators.EQUAL),
                    (TermPeriod(), RangeOperators.OVERLAPS),
                ],
                condition=models.Q(lesson_from__isnull=True),
            ),
            ExclusionConstraint(
                name=PERSONAL_RANGES_EXCLUDE,
                expressions=[
                    ('teacher', RangeOperators.EQUAL),
                    ('group', RangeOperators.EQUAL),
                    (NumRange('lesson_from', 'lesson_to', RangeBoundary(
                        inclusive_lower=True, inclusive_upper=True)),
                     RangeOperators.OVERLAPS),
                    (TermPeriod(), RangeOperators.OVERLAPS),
                ],
                condition=models.Q(lesson_from__isnull=False),
            ),
        ]


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class CancellationPay(models.Model):
    """
    Начисление за отменённое занятие индива с компенсацией, привязанное к маркеру
    отмены (PlannedLesson status='cancelled', seq IS NULL).

    Маркеры не вечны: их удаляют пересборка плана (reset_plan — перевод ученика)
    и wipe_one_offs (смена расписания), в том числе прошлые. Поэтому у
    начисления свой естественный ключ — группа + lesson_date + scheduled_time: по
    нему движок заново привязывает «сироту» к новому маркеру (ручная правка
    переживает пересборку), а прошлую сироту без маркера не трогает —
    выплаченный месяц не должен меняться задним числом.

    teacher — эффективный преподаватель маркера (замена учтена).
    """

    id = models.AutoField(primary_key=True)
    # SET_NULL, не CASCADE: удаление маркера не должно молча уносить оплату за
    # уже выплаченный месяц. ON DELETE SET NULL продублирован на уровне БД
    # (миграция 0006, RunSQL): маркеры чистят и сырым SQL.
    # ⚠️ AlterField этого поля пересоздаст FK без ON DELETE — после него нужна
    # повторная RunSQL (как extra_lessons/0012).
    planned_lesson = models.OneToOneField(
        'scheduling.PlannedLesson', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='planned_lesson_id', related_name='cancellation_pay',
    )
    # PROTECT: жёсткое удаление преподавателя с начислениями запрещено.
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.PROTECT,
        db_column='teacher_id', related_name='cancellation_pays',
        # Покрыт префиксом составного payroll_cancel_tch_date_idx.
        db_index=False,
    )
    group = models.ForeignKey(
        'groups.Group', on_delete=models.CASCADE,
        db_column='group_id', related_name='cancellation_pays',
        # Покрыт префиксом составного payroll_cancel_key_idx.
        db_index=False,
    )
    lesson_date = models.DateField()
    # Время отменённого занятия: в один день у группы может быть два слота.
    scheduled_time = models.TimeField()
    payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    calc_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_manual = models.BooleanField(default=False)
    rule_note = models.TextField(default='')

    class Meta:
        managed = True
        db_table = 'payroll_cancellations'
        indexes = [
            # Сводка/кабинет: начисления преподавателя за период.
            models.Index(fields=['teacher', 'lesson_date'],
                         name='payroll_cancel_tch_date_idx'),
            # Естественный ключ: привязка сирот к маркерам и пересчёт по группам.
            models.Index(fields=['group', 'lesson_date', 'scheduled_time'],
                         name='payroll_cancel_key_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='payroll_cancellations_calc_payment_check',
                condition=models.Q(calc_payment__gte=0),
            ),
        ]
