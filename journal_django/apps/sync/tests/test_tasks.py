# journal_django/apps/sync/tests/test_tasks.py
import pytest

from apps.sync import tasks


@pytest.mark.django_db
def test_backfill_teachers_task_delegates(monkeypatch):
    monkeypatch.setattr(
        'apps.sync.backfills.teachers.run',
        lambda dry_run=False: {'entity': 'teachers', 'dry_run': dry_run},
    )
    result = tasks.backfill_teachers_task.run(dry_run=True)
    assert result == {'entity': 'teachers', 'dry_run': True}


@pytest.mark.django_db
def test_run_all_task_delegates(monkeypatch):
    monkeypatch.setattr(
        'apps.sync.backfills.run_all.run',
        lambda dry_run=False: {'dry_run': dry_run, 'steps': []},
    )
    result = tasks.run_all_task.run(dry_run=False)
    assert result == {'dry_run': False, 'steps': []}


@pytest.mark.django_db
def test_rebuild_planned_lessons_task_delegates(monkeypatch):
    monkeypatch.setattr(
        'apps.sync.backfills.rebuild_planned_lessons.run',
        lambda dry_run=False: {'entity': 'planned-lessons-rebuild', 'dry_run': dry_run},
    )
    result = tasks.rebuild_planned_lessons_task.run(dry_run=True)
    assert result == {'entity': 'planned-lessons-rebuild', 'dry_run': True}
