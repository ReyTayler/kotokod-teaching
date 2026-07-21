"""
Тесты автогенерации плана при первичной настройке группы (Механизм 1).

repository.plan_exists — guard first-time-only (+active).
services.autogenerate_plan_on_setup — оркестратор: генерит план ОДИН раз, когда
у активной группы впервые есть старт+слот+total; пишет аудит plan_auto_generate.

Опора на фикстуру sched_setup (conftest): group_a активна, старт 2026-06-01,
слот Пн 10:00, total_lessons=8 → 8 курсовых строк.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.scheduling import repository, services
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db


@pytest.fixture
def autogen_setup(sched_setup):
    """sched_setup + очистка аудита plan_auto_generate перед удалением групп."""
    yield sched_setup
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM security_audit_log WHERE target_id IN (%s, %s)',
            [sched_setup['group_a'], sched_setup['group_b']],
        )


class TestPlanExists:
    def test_false_when_no_plan(self, autogen_setup):
        assert repository.plan_exists(autogen_setup['group_a']) is False

    def test_true_when_plan_present(self, autogen_setup):
        repository.generate_for_group(autogen_setup['group_a'])
        assert repository.plan_exists(autogen_setup['group_a']) is True

    def test_active_only_skips_inactive_group(self, autogen_setup):
        gid = autogen_setup['group_a']
        with connection.cursor() as cur:
            cur.execute('UPDATE groups SET active=false WHERE id=%s', [gid])
        # неактивная группа без плана → active_only считает «план есть» (пропустить)
        assert repository.plan_exists(gid, active_only=True) is True
        assert repository.plan_exists(gid, active_only=False) is False


class TestAutogenerate:
    def _audit(self, gid):
        from apps.audit.models import SecurityAuditLog
        return SecurityAuditLog.objects.filter(event='plan_auto_generate', target_id=gid)

    def test_generates_plan_and_audits(self, autogen_setup):
        gid = autogen_setup['group_a']
        services.autogenerate_plan_on_setup(gid, source='group_create')
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8
        ev = self._audit(gid).first()
        assert ev is not None
        assert ev.meta['source'] == 'group_create'
        assert ev.meta['written'] == 8

    def test_noop_when_plan_already_exists(self, autogen_setup):
        gid = autogen_setup['group_a']
        repository.generate_for_group(gid)
        services.autogenerate_plan_on_setup(gid, source='group_update')
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8  # без дублей
        assert not self._audit(gid).exists()                            # без события

    def test_noop_for_inactive_group(self, autogen_setup):
        gid = autogen_setup['group_a']
        with connection.cursor() as cur:
            cur.execute('UPDATE groups SET active=false WHERE id=%s', [gid])
        services.autogenerate_plan_on_setup(gid, source='group_create')
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0
        assert not self._audit(gid).exists()

    def test_noop_when_no_slots_yet(self, autogen_setup):
        """Старт есть, слота ещё нет → generate вернёт reason, план пуст, аудита нет
        (сработает позже, когда слот появится)."""
        gid = autogen_setup['group_a']
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_schedule_slots WHERE group_id=%s', [gid])
        services.autogenerate_plan_on_setup(gid, source='schedule_change')
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0
        assert not self._audit(gid).exists()


class TestAutogenerateWiring:
    """Интеграция триггера через groups.services (Фаза E). Проверяет оба порядка
    ввода и то, что генерация срабатывает при слотах, созданных bulk_create
    (доказывает, что мы НЕ на post_save-сигналах)."""

    @pytest.fixture
    def wiring(self, sched_setup):
        created: list[int] = []
        yield sched_setup, created
        with connection.cursor() as cur:
            for gid in created:
                cur.execute('DELETE FROM planned_lessons WHERE group_id=%s', [gid])
                cur.execute('DELETE FROM group_schedule_slots WHERE group_id=%s', [gid])
                cur.execute('DELETE FROM security_audit_log WHERE target_id=%s', [gid])
                cur.execute('DELETE FROM groups WHERE id=%s', [gid])

    def _base(self, s, name):
        return {
            'name': name, 'direction_id': s['direction_id'], 'teacher_id': s['teacher_a'],
            'lesson_duration_minutes': 60,
        }

    def test_create_with_start_and_slot_autogenerates(self, wiring):
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_create__')
        data['group_start_date'] = '2026-06-01'
        data['slots'] = [{'day_of_week': 1, 'start_time': '10:00'}]  # bulk_create путь
        group = groups_services.create_group(data)
        created.append(group['id'])
        # план сгенерирован, несмотря на bulk_create слотов (не сигналы)
        assert PlannedLesson.objects.filter(group_id=group['id']).count() == 8

    def test_start_then_slot_via_schedule_change(self, wiring):
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_startfirst__')
        data['group_start_date'] = '2026-06-01'
        data['slots'] = []
        group = groups_services.create_group(data)
        gid = group['id']
        created.append(gid)
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # нет слота — пусто

        groups_services.apply_schedule_change(gid, {
            'effective_from': '2026-06-01',
            'slots': [{'day_of_week': 1, 'start_time': '10:00'}],
        })
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8  # слот появился → план

    def test_slot_then_start_via_update(self, wiring):
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_slotfirst__')
        data['group_start_date'] = None
        data['slots'] = [{'day_of_week': 1, 'start_time': '10:00'}]
        group = groups_services.create_group(data)
        gid = group['id']
        created.append(gid)
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # нет старта — пусто

        groups_services.update_group(gid, {'group_start_date': '2026-06-01'})
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8  # старт появился → план

    def test_bootstrap_start_and_slots_via_actions(self, wiring):
        """Группа создана без даты старта И без слотов (план пуст). Сценарий кнопки
        «Задать расписание» на вкладке расписания: сначала update_group ставит дату
        начала, затем apply_schedule_change задаёт слоты → план генерируется."""
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_bootstrap__')
        data['group_start_date'] = None
        data['slots'] = []
        group = groups_services.create_group(data)
        gid = group['id']
        created.append(gid)
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # ни старта, ни слота

        groups_services.update_group(gid, {'group_start_date': '2026-06-01'})
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # старт есть, слотов нет
        groups_services.apply_schedule_change(gid, {
            'effective_from': '2026-06-01',
            'slots': [{'day_of_week': 1, 'start_time': '10:00'}],
        })
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8  # оба заданы → план

    def test_second_update_does_not_regenerate(self, wiring):
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_once__')
        data['group_start_date'] = '2026-06-01'
        data['slots'] = [{'day_of_week': 1, 'start_time': '10:00'}]
        group = groups_services.create_group(data)
        gid = group['id']
        created.append(gid)
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8

        groups_services.update_group(gid, {'name': '__ag_once_renamed__'})
        assert PlannedLesson.objects.filter(group_id=gid).count() == 8  # без перегенерации

    def test_45min_generates_double_and_snaps_to_slot(self, wiring):
        """Верификация «Задать расписание» (уже реализовано, план Task 11):
        45-минутная группа → half-lesson step=0.5, план направления с
        total_lessons=8 разворачивается в 2×8=16 курсовых строк. Старт 2026-07-20
        (Пн) со слотом Пт(5) → первое занятие встаёт на первый слот-день ≥ старта
        (2026-07-24), а не на сам понедельник старта."""
        from apps.groups import services as groups_services
        s, created = wiring
        data = self._base(s, '__ag_45__')
        data['lesson_duration_minutes'] = 45
        data['group_start_date'] = None
        data['slots'] = []
        group = groups_services.create_group(data)
        gid = group['id']
        created.append(gid)
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # ни старта, ни слота

        groups_services.update_group(gid, {'group_start_date': '2026-07-20'})
        assert PlannedLesson.objects.filter(group_id=gid).count() == 0  # старт есть, слотов нет
        groups_services.apply_schedule_change(gid, {
            'effective_from': '2026-07-20',
            'slots': [{'day_of_week': 5, 'start_time': '17:00'}],
        })
        rows = list(
            PlannedLesson.objects.filter(group_id=gid, seq__isnull=False).order_by('seq')
        )
        assert len(rows) == 16  # 2 × total_lessons(8) направления sched_setup
        assert str(rows[0].scheduled_date) == '2026-07-24'
