"""Live SkyTonight progress must reach the shared status file, not only this worker's memory.

The calculation runs in the scheduler's worker, but status polls are answered by
any gunicorn worker; the others read the status file the scheduler writes.
"""

import pytest

from skytonight import skytonight_calculator as calc


@pytest.fixture(autouse=True)
def _clear_listener():
    calc.set_progress_listener(None)
    yield
    calc.set_progress_listener(None)
    calc._calculation_progress.clear()


def test_progress_update_calls_listener():
    calls = []
    calc.set_progress_listener(lambda: calls.append(calc.get_calculation_progress()))

    calc._set_progress('bodies', 3, 10)

    assert calls == [{'phase': 'bodies', 'phase_processed': 3, 'phase_total': 10}]


def test_listener_calls_are_throttled(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(calc.time, 'monotonic', lambda: clock[0])
    calls = []
    calc.set_progress_listener(lambda: calls.append(1))

    calc._set_progress('bodies', 1, 10)
    clock[0] += calc._PROGRESS_PUBLISH_INTERVAL_SECONDS / 2
    calc._set_progress('bodies', 2, 10)
    clock[0] += calc._PROGRESS_PUBLISH_INTERVAL_SECONDS
    calc._set_progress('bodies', 3, 10)

    assert len(calls) == 2


def test_failing_listener_never_breaks_the_calculation():
    def _broken():
        raise OSError('disk full')

    calc.set_progress_listener(_broken)
    calc._set_progress('comets', 0, 5)  # must not raise
    assert calc.get_calculation_progress()['phase'] == 'comets'


def test_no_listener_only_updates_memory():
    calc._set_progress('moon_init')
    assert calc.get_calculation_progress()['phase'] == 'moon_init'


def test_scheduler_publishes_progress_only_while_executing(monkeypatch):
    from skytonight import skytonight_scheduler as sched_module

    registered = []
    monkeypatch.setattr(calc, 'set_progress_listener', lambda listener: registered.append(listener))

    scheduler = sched_module.SkyTonightScheduler.__new__(sched_module.SkyTonightScheduler)
    seen_during_run = []

    def _runner():
        seen_during_run.append(registered[-1])
        return {}

    monkeypatch.setattr(scheduler, '_write_status', lambda *a, **kw: None, raising=False)
    scheduler.config_loader = lambda: {'skytonight': {'enabled': True}}
    scheduler.runner = _runner
    scheduler.app = None
    scheduler._execution_lock = sched_module.threading.Lock()
    scheduler.execution_start_time = None
    scheduler._triggered_mode = None
    scheduler._triggered_reason = None

    scheduler._execute_cycle()

    assert seen_during_run == [scheduler._write_status]
    assert registered[-1] is None
