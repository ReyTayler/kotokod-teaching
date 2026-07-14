# journal_django/apps/sync/tests/test_run_all.py
from apps.sync.backfills import run_all


def test_run_all_calls_steps_in_order(monkeypatch):
    call_order = []

    def make_fake(name):
        def fake_run(dry_run=False):
            call_order.append(name)
            return {'entity': name, 'dry_run': dry_run}
        return fake_run

    for step_name, module in run_all.STEPS:
        monkeypatch.setattr(module, 'run', make_fake(step_name))

    result = run_all.run(dry_run=True)

    assert call_order == ['teachers', 'groups', 'students', 'lessons', 'payroll']
    assert result['dry_run'] is True
    assert len(result['steps']) == 5
    assert all(step['dry_run'] is True for step in result['steps'])


def test_run_all_does_not_include_payments():
    step_names = [name for name, _ in run_all.STEPS]
    assert 'payments' not in step_names
