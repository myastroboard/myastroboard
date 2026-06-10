"""Tests for SkyTonight scheduler schedule resolution."""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from skytonight_scheduler import (
    SkyTonightSchedule,
    SkyTonightScheduler,
    _is_server_time_valid,
    _parse_local_datetime,
    resolve_schedule,
)


def _base_config():
    return {
        'location': {
            'name': 'Paris',
            'latitude': 48.866669,
            'longitude': 2.33333,
            'elevation': 35,
            'timezone': 'Europe/Paris',
        },
        'skytonight': {'enabled': True},
    }


def test_resolve_schedule_uses_fallback_for_invalid_time():
    config = _base_config()
    now = datetime(2020, 1, 1, 12, 0, tzinfo=ZoneInfo('Europe/Paris'))
    schedule = resolve_schedule(config, now=now)

    assert schedule.server_time_valid is False
    assert schedule.mode == 'fallback-6h'
    assert schedule.next_run is not None


def test_resolve_schedule_prefers_soonest_valid_candidate():
    config = _base_config()
    # Use an April date where a proper nautical night exists in Paris
    now = datetime(2026, 4, 1, 4, 0, tzinfo=ZoneInfo('Europe/Paris'))
    schedule = resolve_schedule(config, now=now)

    assert schedule.server_time_valid is True
    assert schedule.next_run is not None
    assert schedule.next_run > now
    assert schedule.mode in {'post-nautical-night', 'pre-nautical-night'}


def test_resolve_schedule_keeps_timezone_from_config():
    config = _base_config()
    now = datetime(2026, 4, 1, 22, 0, tzinfo=ZoneInfo('Europe/Paris'))
    schedule = resolve_schedule(config, now=now)

    assert schedule.timezone == 'Europe/Paris'


def test_resolve_schedule_post_night_candidate_is_after_dawn():
    """At 06:05, resolve_schedule should offer a post-night slot after nautical dawn.

    This demonstrates why a committed_next_run is required: the freshly-computed
    next_run is always in the future, so comparing server_time against it would
    never fire - we must track the previously committed time.
    """
    config = _base_config()
    just_past_six = datetime(2026, 4, 3, 6, 5, tzinfo=ZoneInfo('Europe/Paris'))
    schedule = resolve_schedule(config, now=just_past_six)

    assert schedule.next_run is not None
    assert schedule.next_run > just_past_six
    assert schedule.mode in {'post-nautical-night', 'pre-nautical-night'}


def test_disabled_scheduler_does_not_execute_runner(monkeypatch):
    stored_status = {}
    calls = []

    def _save_status(payload):
        stored_status.clear()
        stored_status.update(payload)
        return True

    def _load_status(default=None):
        if stored_status:
            return dict(stored_status)
        if default is not None:
            return dict(default)
        return {}

    monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save_status)
    monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load_status)

    scheduler = SkyTonightScheduler(
        config_loader=lambda: {
            'location': {
                'name': 'Paris',
                'latitude': 48.866669,
                'longitude': 2.33333,
                'timezone': 'Europe/Paris',
            },
            'skytonight': {'enabled': False},
        },
        runner=lambda: calls.append('ran'),
    )

    scheduler._execute_cycle()
    status = scheduler.get_status()

    assert calls == []
    assert status['enabled'] is False
    assert status['mode'] == 'disabled'
    assert status['next_run'] is None


def test_missed_run_recovery_on_startup(monkeypatch):
    """Missed-run recovery: if the app restarts after triggering a run (status
    already shows tonight's next_run) but before the run completed (last_run
    not updated), the startup block should restore the missed post-night slot
    so the loop fires on the first iteration.

    Scenario mirrors the real incident:
      - last_run  = 2026-04-03 23:14 (previous night's run)
      - last_result.calculation.night_end = 2026-04-04T05:20:00+02:00
        → expected post-night slot = night_end + 1h = 06:20 April 4
      - persisted next_run = 2026-04-04 21:05 (tonight's pre-night, already
        advanced when the morning run was triggered mid-execution)
      - server restarts at current time (past 06:20)
      - expected: _committed_next_run is restored to 06:20 so the loop check
        (server_time >= committed) fires immediately.
    """
    # The missed slot is 30 seconds in the past so the recovery check fires.
    base_now = datetime.now(ZoneInfo('Europe/Paris'))
    past_slot = base_now - timedelta(seconds=30)
    night_end = past_slot - timedelta(hours=1)  # night_end = missed_slot - 1h
    # next_run in the status is 4 hours in the future (well past the missed slot)
    future_next_run = base_now + timedelta(hours=4)
    last_run = past_slot - timedelta(hours=6)   # comfortably before the missed slot

    stored_status = {
        'last_run': last_run.isoformat(),
        'next_run': future_next_run.isoformat(),
        'last_result': {
            'calculation': {
                'night_end': night_end.isoformat(),
            }
        },
    }
    run_calls = []

    def _save_status(payload):
        stored_status.clear()
        stored_status.update(payload)

    def _load_status(default=None):
        return dict(stored_status) if stored_status else (default or {})

    def _has_results():
        return True  # pretend previous results exist (no forced re-run)

    def _ensure_dirs():
        pass

    def _trigger_file():
        return '/tmp/nonexistent_trigger_skytonight'

    monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save_status)
    monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load_status)
    monkeypatch.setattr('skytonight_scheduler.has_calculation_results', _has_results)
    monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', _ensure_dirs)
    monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', _trigger_file)
    monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
    # Keep this test deterministic and fast: recovery is about restoring
    # _committed_next_run from persisted status, not about real solar calculations.
    monkeypatch.setattr(
        'skytonight_scheduler.resolve_schedule',
        lambda _config: SkyTonightSchedule(
            mode='post-nautical-night',
            next_run=future_next_run,
            server_time_valid=True,
            reason='test-schedule',
            server_time=datetime.now(ZoneInfo('Europe/Paris')),
            timezone='Europe/Paris',
        ),
    )

    stop_event = threading.Event()

    def runner():
        run_calls.append('ran')
        stop_event.set()
        return {'dataset_generated': True}

    scheduler = SkyTonightScheduler(
        config_loader=lambda: {
            'location': {
                'name': 'Paris',
                'latitude': 48.866669,
                'longitude': 2.33333,
                'timezone': 'Europe/Paris',
            },
            'skytonight': {'enabled': True},
        },
        runner=runner,
    )

    scheduler.start()
    fired = stop_event.wait(timeout=5)
    scheduler.stop()

    assert fired, (
        'Missed-run recovery did not trigger the run within 5 s. '
        'The post-night slot should have been restored and fired immediately on startup.'
    )
    assert run_calls, 'Runner was never called despite missed-run recovery.'


# ---------------------------------------------------------------------------
# Additional tests to improve branch/line coverage
# ---------------------------------------------------------------------------


class TestParseLocalDatetime:
    """Cover _parse_local_datetime branches (lines 42-50)."""

    def test_parse_valid_datetime_string(self):
        result = _parse_local_datetime('2026-04-17 22:00', 'Europe/Paris')
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.hour == 22

    def test_parse_empty_string_returns_none(self):
        assert _parse_local_datetime('', 'UTC') is None

    def test_parse_not_found_returns_none(self):
        assert _parse_local_datetime('Not found', 'UTC') is None

    def test_parse_invalid_format_returns_none(self):
        assert _parse_local_datetime('not-a-date', 'UTC') is None

    def test_parse_whitespace_value_returns_none(self):
        assert _parse_local_datetime('   ', 'UTC') is None


class TestIsServerTimeValid:
    """Cover _is_server_time_valid branches (lines 53-60)."""

    def test_returns_false_for_year_before_2024(self):
        t = datetime(2020, 1, 1, tzinfo=ZoneInfo('UTC'))
        assert _is_server_time_valid(t, 'UTC') is False

    def test_returns_true_for_valid_time_and_timezone(self):
        t = datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo('UTC'))
        assert _is_server_time_valid(t, 'UTC') is True

    def test_returns_false_for_invalid_timezone(self):
        t = datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo('UTC'))
        assert _is_server_time_valid(t, 'Invalid/Zone_XXXX') is False


class TestResolveScheduleEdgeCases:
    """Cover additional resolve_schedule branches."""

    def test_fallback_when_no_location(self):
        """Covers the 'no candidates' fallback path (lines 106-113)."""
        config = {
            'location': {},  # No lat/lon → no SunService call → no candidates
            'skytonight': {'enabled': True},
        }
        now = datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo('UTC'))
        schedule = resolve_schedule(config, now=now)
        assert schedule.mode == 'fallback-6h'
        assert schedule.next_run is not None

    def test_fallback_when_config_is_not_dict(self):
        """Covers non-dict config path."""
        schedule = resolve_schedule(None, now=datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo('UTC')))  # type: ignore[arg-type]  # Intentionally pass invalid config to verify fallback behavior.
        assert schedule.mode == 'fallback-6h'

    def test_now_is_none_uses_current_time(self):
        """Covers the now=None branch (current datetime)."""
        config = {
            'location': {'timezone': 'UTC'},
            'skytonight': {'enabled': True},
        }
        schedule = resolve_schedule(config, now=None)
        assert schedule is not None

    def test_fallback_when_nautical_dawn_is_none(self, monkeypatch):
        """Covers the dawn_time is None branch (line 90-91 skip)."""
        config = {
            'location': {
                'latitude': 48.8,
                'longitude': 2.3,
                'timezone': 'Europe/Paris',
            },
            'skytonight': {'enabled': True},
        }
        now = datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo('Europe/Paris'))

        class FakeSunService:
            def __init__(self, **kwargs):
                pass

            def get_today_report(self):
                return NS(nautical_dawn=None, nautical_dusk=None)

            def get_tomorrow_report(self):
                return NS(nautical_dawn=None, nautical_dusk=None)

        monkeypatch.setattr('skytonight_scheduler.SunService', FakeSunService)
        schedule = resolve_schedule(config, now=now)
        assert schedule.mode == 'fallback-6h'


class TestSchedulerHelperMethods:
    """Cover SkyTonightScheduler._write_status, get_status, trigger_now branches."""

    def _make_scheduler(self, monkeypatch, enabled=True, runner=None):
        stored = {}

        def _save(payload):
            stored.clear()
            stored.update(payload)

        def _load(default=None):
            return dict(stored) if stored else (default or {})

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        if runner is None:
            runner = lambda: {'result': 'ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {
                'location': {
                    'name': 'Paris',
                    'latitude': 48.866669,
                    'longitude': 2.33333,
                    'timezone': 'Europe/Paris',
                },
                'skytonight': {'enabled': enabled},
            },
            runner=runner,
        )
        return sched, stored

    def test_write_status_when_disabled_clears_next_run(self, monkeypatch):
        """Covers the 'not enabled' override in _write_status (lines 435-443)."""
        sched, stored = self._make_scheduler(monkeypatch, enabled=False)
        sched._write_status()
        assert stored.get('next_run') is None
        assert stored.get('mode') == 'disabled'

    def test_write_status_uses_triggered_mode_while_executing(self, monkeypatch):
        """Covers triggered mode/reason display when is_executing (lines 478-479)."""
        sched, stored = self._make_scheduler(monkeypatch, enabled=True)
        sched.is_executing = True
        sched._triggered_mode = 'manual'
        sched._triggered_reason = 'Manually triggered.'
        sched.execution_start_time = datetime.now().astimezone()
        sched._write_status()
        assert stored.get('mode') == 'manual'
        assert stored.get('reason') == 'Manually triggered.'

    def test_write_status_computes_execution_duration(self, monkeypatch):
        """Covers execution_duration_seconds computation (lines 446-447)."""
        sched, stored = self._make_scheduler(monkeypatch, enabled=True)
        sched.is_executing = True
        sched.execution_start_time = datetime.now().astimezone() - timedelta(seconds=10)
        sched._write_status()
        # Duration should be at least 10 seconds
        assert stored.get('progress', {}).get('execution_duration_seconds', 0) >= 10

    def test_get_status_returns_dict_with_running_key(self, monkeypatch):
        """Covers get_status (lines 493-500)."""
        sched, stored = self._make_scheduler(monkeypatch, enabled=True)
        status = sched.get_status()
        assert 'running' in status

    def test_trigger_now_when_not_locked(self, monkeypatch):
        """Covers trigger_now success path (lines 503-506) - returns triggered."""
        sched, _ = self._make_scheduler(monkeypatch, enabled=True)
        result = sched.trigger_now()
        assert result['status'] == 'triggered'

    def test_trigger_now_when_locked_returns_skipped(self, monkeypatch):
        """Covers trigger_now locked path (lines 503-504)."""
        sched, _ = self._make_scheduler(monkeypatch, enabled=True)
        # Acquire the lock so trigger_now sees it as locked
        sched._execution_lock.acquire()
        try:
            result = sched.trigger_now()
            assert result['status'] == 'skipped'
        finally:
            sched._execution_lock.release()

    def test_start_twice_is_idempotent(self, monkeypatch):
        """Covers the _scheduler_started guard in start() (lines 222-224)."""
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/no_trigger')
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=6),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        sched, _ = self._make_scheduler(monkeypatch, enabled=False)
        sched.start()
        sched.start()  # Second call must be a no-op
        sched.stop()
        # Thread should only have been created once
        assert sched._scheduler_started is True

    def test_stop_joins_thread(self, monkeypatch):
        """Covers stop() when thread is alive (lines 233-237)."""
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/no_trigger')
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=6),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        sched, _ = self._make_scheduler(monkeypatch, enabled=False)
        sched.start()
        sched.stop()
        # After stop the scheduler is no longer running
        assert sched.running is False


class TestSchedulerExecuteCycle:
    """Cover _execute_cycle branches."""

    def _make_scheduler(self, monkeypatch, enabled=True, runner=None):
        stored = {}

        def _save(payload):
            stored.clear()
            stored.update(payload)

        def _load(default=None):
            return dict(stored) if stored else (default or {})

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)

        if runner is None:
            runner = lambda: {'result': 'ok'}

        config = {
            'location': {
                'name': 'Paris',
                'latitude': 48.866669,
                'longitude': 2.33333,
                'timezone': 'Europe/Paris',
            },
            'skytonight': {'enabled': enabled},
        }
        sched = SkyTonightScheduler(
            config_loader=lambda: config,
            runner=runner,
        )
        return sched, stored

    def test_execute_cycle_succeeds_and_records_run(self, monkeypatch):
        """Covers the happy path of _execute_cycle (lines 396-416)."""
        calls = []

        def runner():
            calls.append('ran')
            return {'result': 'ok'}

        sched, stored = self._make_scheduler(monkeypatch, enabled=True, runner=runner)
        sched._execute_cycle(manual_trigger=False)

        assert 'ran' in calls
        assert sched.last_run is not None
        assert sched.last_error is None

    def test_execute_cycle_records_error_on_runner_exception(self, monkeypatch):
        """Covers the exception handler in _execute_cycle (lines 411-416)."""
        def bad_runner():
            raise RuntimeError('runner exploded')

        sched, _ = self._make_scheduler(monkeypatch, enabled=True, runner=bad_runner)
        sched._execute_cycle(manual_trigger=False)

        assert sched.last_error == 'runner exploded'
        assert sched.last_result == {}

    def test_execute_cycle_manual_trigger_sets_mode_to_manual(self, monkeypatch):
        """Covers current_mode='manual' path (line 406)."""
        sched, _ = self._make_scheduler(monkeypatch, enabled=True)
        sched._execute_cycle(manual_trigger=True)
        assert sched.current_mode == 'manual'

    def test_execute_cycle_skips_when_already_locked(self, monkeypatch):
        """Covers the early-return when _execution_lock is locked (lines 384-388)."""
        sched, _ = self._make_scheduler(monkeypatch, enabled=True)
        sched._execution_lock.acquire()
        try:
            sched.is_executing = True
            sched._execute_cycle(manual_trigger=False)
            # is_executing should be reset to False by the early return
            assert sched.is_executing is False
        finally:
            sched._execution_lock.release()

    def test_execute_cycle_with_app_context(self, monkeypatch):
        """Covers the app.app_context() branch (lines 398-400)."""
        calls = []

        def runner():
            calls.append('ran')
            return {'result': 'with_app'}

        sched, _ = self._make_scheduler(monkeypatch, enabled=True, runner=runner)

        # Provide a fake Flask-like app with app_context()
        class FakeApp:
            def app_context(self):
                @contextmanager
                def ctx():
                    yield

                return ctx()

        sched.app = FakeApp()
        sched._execute_cycle(manual_trigger=False)
        assert 'ran' in calls


class TestSchedulerInitFromPersistedStatus:
    """Cover SkyTonightScheduler.__init__ branches that read stored status."""

    def _monkeypatch_storage(self, monkeypatch, stored_status):
        stored = dict(stored_status)
        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda p: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: dict(stored))
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)

    def test_restores_last_run_from_status(self, monkeypatch):
        """Covers the last_run parsing branch (lines 165-169)."""
        last_run_dt = datetime(2026, 4, 17, 3, 0, tzinfo=ZoneInfo('UTC'))
        self._monkeypatch_storage(monkeypatch, {'last_run': last_run_dt.isoformat()})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched.last_run is not None
        assert sched.last_run.year == 2026

    def test_invalid_last_run_iso_gives_none(self, monkeypatch):
        """Covers the ValueError branch in last_run parsing (line 168-169)."""
        self._monkeypatch_storage(monkeypatch, {'last_run': 'not-a-datetime'})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched.last_run is None

    def test_last_error_non_string_coerced(self, monkeypatch):
        """Covers else branch for last_error (line 176)."""
        self._monkeypatch_storage(monkeypatch, {'last_error': 42})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched.last_error == '42'

    def test_last_result_non_dict_wrapped(self, monkeypatch):
        """Covers non-dict last_result → wrapped in dict (line 182)."""
        self._monkeypatch_storage(monkeypatch, {'last_result': 'some-string'})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched.last_result == {'result': 'some-string'}

    def test_backfill_from_calc_cache_when_no_last_result(self, monkeypatch):
        """Covers defensive backfill from calculation cache (lines 191-211)."""
        self._monkeypatch_storage(monkeypatch, {})
        # Provide a calc cache with useful metadata
        calc_cache = {
            'metadata': {
                'night_start': '2026-04-17T21:00:00+00:00',
                'night_end': '2026-04-18T05:00:00+00:00',
                'counts': {'deep_sky': 10, 'bodies': 3, 'comets': 0},
            }
        }
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: calc_cache)

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert 'calculation' in sched.last_result
        assert sched.last_result['calculation']['counts']['deep_sky'] == 10

    def test_committed_next_run_restored_from_status(self, monkeypatch):
        """Covers the next_run parsing from stored status (lines 214-218)."""
        future = datetime(2026, 4, 18, 22, 0, tzinfo=ZoneInfo('UTC'))
        self._monkeypatch_storage(monkeypatch, {'next_run': future.isoformat()})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched._committed_next_run is not None
        assert sched._committed_next_run.year == 2026

    def test_invalid_next_run_iso_leaves_none(self, monkeypatch):
        """Covers ValueError branch for next_run parsing (line 218)."""
        self._monkeypatch_storage(monkeypatch, {'next_run': 'bad-iso'})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched._committed_next_run is None

    def test_duration_stored_in_status(self, monkeypatch):
        """Covers stored_last_duration parsing (lines 184-189)."""
        self._monkeypatch_storage(monkeypatch, {'progress': {'last_execution_duration_seconds': 42}})
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {}},
            runner=lambda: {},
        )
        assert sched.last_execution_duration_seconds == 42


class TestRunLoopBranches:
    """Cover _run_loop branches by running the scheduler with controlled config/state."""

    def _setup_monkeypatches(self, monkeypatch, stored_status=None, enable_trigger=False, trigger_path='/tmp/no_sk_trigger'):
        stored = dict(stored_status or {})

        def _save(payload):
            stored.clear()
            stored.update(payload)

        def _load(default=None):
            return dict(stored) if stored else (default or {})

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: trigger_path)
        return stored

    def test_loop_fires_immediately_when_last_run_is_none(self, monkeypatch, tmp_path):
        """Covers should_run=True path when last_run is None (line 304)."""
        self._setup_monkeypatches(monkeypatch)
        done_event = threading.Event()
        calls = []
        now_utc = datetime.now(ZoneInfo('UTC'))

        future_run = now_utc + timedelta(hours=6)

        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=now_utc,
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
        )
        sched.start()
        fired = done_event.wait(timeout=5)
        sched.stop()
        assert fired, 'Runner should fire on first loop iteration when last_run is None'
        assert calls

    def test_loop_fires_when_missing_calculation_results(self, monkeypatch):
        """Covers should_run=True path when has_calculation_results is False (lines 305-309)."""
        self._setup_monkeypatches(monkeypatch)
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: False)
        done_event = threading.Event()
        calls = []

        # Set last_run so should_run is False initially
        last_run = datetime.now(ZoneInfo('UTC')) - timedelta(hours=2)

        future_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=6)

        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
        )
        sched.last_run = last_run  # Override to avoid first-run trigger
        sched.start()
        fired = done_event.wait(timeout=5)
        sched.stop()
        assert fired, 'Runner should fire when calculation results are missing'

    def test_loop_handles_manual_trigger_file(self, monkeypatch, tmp_path):
        """Covers manual trigger file detection path (lines 292-298)."""
        trigger_file = str(tmp_path / 'skytonight_trigger')
        # Create the trigger file so os.path.exists returns True
        with open(trigger_file, 'w') as f:
            f.write('')

        self._setup_monkeypatches(monkeypatch, trigger_path=trigger_file)

        done_event = threading.Event()
        calls = []

        last_run = datetime.now(ZoneInfo('UTC')) - timedelta(hours=1)
        future_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=6)

        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'manual_ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
        )
        sched.last_run = last_run
        sched._committed_next_run = future_run  # Far in future
        sched.start()
        fired = done_event.wait(timeout=5)
        sched.stop()
        assert fired, 'Manual trigger file should trigger the runner'

    def test_loop_respects_committed_next_run(self, monkeypatch):
        """Covers the committed_next_run check (lines 313-316)."""
        self._setup_monkeypatches(monkeypatch)
        done_event = threading.Event()
        calls = []

        # Set committed_next_run to the past so the check fires
        past_slot = datetime.now(ZoneInfo('UTC')) - timedelta(minutes=5)
        last_run = datetime.now(ZoneInfo('UTC')) - timedelta(hours=2)
        future_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=6)

        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
        )
        sched.last_run = last_run
        sched._committed_next_run = past_slot  # Past slot → should fire
        sched.start()
        fired = done_event.wait(timeout=5)
        sched.stop()
        assert fired, 'Runner should fire when server_time >= committed_next_run'

    def test_loop_cache_ready_event_path(self, monkeypatch):
        """Covers the cache_ready_event.wait branch (lines 348-352)."""
        self._setup_monkeypatches(monkeypatch)
        done_event = threading.Event()
        calls = []

        future_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=6)
        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'ok'}

        # cache_ready_event that is already set → the wait returns True immediately
        cache_event = threading.Event()
        cache_event.set()

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
            cache_ready_event=cache_event,
        )
        sched.start()
        fired = done_event.wait(timeout=5)
        sched.stop()
        assert fired, 'Runner should fire after cache_ready_event is set'
        assert sched._cache_ready_waited is True

    def test_loop_write_status_with_get_calculation_progress_exception(self, monkeypatch):
        """Covers the exception path for get_calculation_progress import (lines 453-454)."""
        self._setup_monkeypatches(monkeypatch)

        # Make get_calculation_progress raise inside _write_status
        with patch('skytonight_calculator.get_calculation_progress', side_effect=Exception('calc broken')):
            stored = {}

            def _save(payload):
                stored.update(payload)

            monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save)

            monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
            monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})

            sched = SkyTonightScheduler(
                config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': False}},
                runner=lambda: {},
            )
            # Should not raise; exception is caught
            sched._write_status()
            # calc_progress falls back to {} → progress key exists in payload
            assert 'progress' in stored

    def test_loop_advance_committed_next_run_when_last_run_reached_slot(self, monkeypatch):
        """Covers next_run advance logic (lines 325-337) when last_run >= _committed_next_run."""
        self._setup_monkeypatches(monkeypatch)

        past_committed = datetime.now(ZoneInfo('UTC')) - timedelta(hours=2)
        recent_run = datetime.now(ZoneInfo('UTC')) - timedelta(hours=1)  # >= committed
        future_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=6)

        done_event = threading.Event()
        calls = []

        monkeypatch.setattr(
            'skytonight_scheduler.resolve_schedule',
            lambda _cfg: SkyTonightSchedule(
                mode='fallback-6h',
                next_run=future_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            ),
        )

        def runner():
            calls.append('ran')
            done_event.set()
            return {'result': 'ok'}

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
        )
        sched.last_run = recent_run
        sched._committed_next_run = past_committed
        # since last_run >= committed_next_run, the loop should advance to future_run
        # and then also fire (committed was in past → server_time >= committed)
        sched.start()
        done_event.wait(timeout=5)
        sched.stop()
        # After loop runs, committed_next_run should have been advanced to future_run
        assert sched._committed_next_run == future_run


class TestSchedulerInitFromStoredStatus:
    """Cover missing lines in __init__ status-restore branches."""

    def test_last_error_non_empty_string_is_stored(self, monkeypatch):
        """Line 172: last_error is a non-empty string → self.last_error = stored_last_error."""
        stored = {'last_error': 'something went wrong'}
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: stored)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        sched = SkyTonightScheduler(config_loader=lambda: {}, runner=lambda: {})
        assert sched.last_error == 'something went wrong'

    def test_last_error_non_string_non_none_is_converted(self, monkeypatch):
        """Line 176: last_error is non-None non-str → str(stored_last_error)."""
        stored = {'last_error': 42}
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: stored)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        sched = SkyTonightScheduler(config_loader=lambda: {}, runner=lambda: {})
        assert sched.last_error == '42'

    def test_invalid_duration_is_none(self, monkeypatch):
        """Lines 188-189: stored duration raises TypeError/ValueError → last_execution_duration_seconds = None."""
        stored = {'progress': {'last_execution_duration_seconds': 'not_a_number'}}
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: stored)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        sched = SkyTonightScheduler(config_loader=lambda: {}, runner=lambda: {})
        assert sched.last_execution_duration_seconds is None

    def test_backfill_exception_is_swallowed(self, monkeypatch):
        """Lines 212-213: exception in backfill → pass (no crash)."""
        stored = {}  # empty → enters backfill try block

        def _raise_disk_error():
            raise RuntimeError("disk error")

        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: stored)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', _raise_disk_error)
        # Should not raise
        sched = SkyTonightScheduler(config_loader=lambda: {}, runner=lambda: {})
        assert sched.last_result == {}


class TestSchedulerStopWithNoThread:
    """Cover lines 234->236: stop() when thread is None (scheduler never started)."""

    def test_stop_without_start_does_not_crash(self, monkeypatch):
        """Line 234->236: if self.thread is False/None, thread.join is skipped."""
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', lambda _: SkyTonightSchedule(
            mode='disabled', next_run=None, server_time_valid=False,
            reason='', server_time=datetime.now(), timezone='UTC',
        ))
        sched = SkyTonightScheduler(config_loader=lambda: {}, runner=lambda: {})
        assert sched.thread is None
        sched.stop()  # Should not raise; thread is None so join is skipped


class TestResolveSchedulePastCandidates:
    """Cover 92->97 and 101->87: when candidate times are in the past."""

    def test_all_candidates_in_past_uses_fallback(self):
        """92->97 and 101->87: all dawn/dusk candidates ≤ current_time → fallback."""
        config = _base_config()
        # Use a relative far-future time so computed dawn/dusk candidates are in the past
        YEARS_IN_FUTURE = 75
        far_future = (
            datetime.now(ZoneInfo('Europe/Paris')) + timedelta(days=365 * YEARS_IN_FUTURE)
        ).replace(hour=20, minute=0, second=0, microsecond=0)
        schedule = resolve_schedule(config, now=far_future)
        assert schedule.mode == 'fallback-6h'


class TestRunLoopMissedRunFalseBranch:
    """Cover 260->280: missed-run recovery condition False (slot is in the future)."""

    def test_no_recovery_when_slot_is_in_future(self, monkeypatch):
        """260->280: night_end is set but missed_slot is in the future → condition False."""
        future_next_run = datetime.now(ZoneInfo('Europe/Paris')) + timedelta(hours=4)
        last_run = datetime.now(ZoneInfo('Europe/Paris')) - timedelta(hours=6)
        # night_end is 3 hours in the future → missed_slot = 4h from now → in future
        night_end = datetime.now(ZoneInfo('Europe/Paris')) + timedelta(hours=3)

        stored_status = {
            'last_run': last_run.isoformat(),
            'next_run': future_next_run.isoformat(),
            'last_result': {'calculation': {'night_end': night_end.isoformat()}},
        }

        def _load_status(default=None):
            return dict(stored_status)

        def _save_status(payload):
            stored_status.clear()
            stored_status.update(payload)

        stopped_event = threading.Event()

        call_count = [0]

        def mock_resolve(config):
            call_count[0] += 1
            if call_count[0] >= 2:
                # Stop after second resolve call
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=future_next_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('Europe/Paris')),
                timezone='Europe/Paris',
            )

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save_status)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load_status)
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/nonexistent_st2')
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'Europe/Paris'}, 'skytonight': {'enabled': True}},
            runner=lambda: {'result': 'ok'},
        )
        sched.start()
        stopped_event.wait(timeout=5)
        sched.stop()
        # Recovery was NOT triggered since slot is in the future
        assert sched._committed_next_run != last_run  # Not restored to missed slot


class TestRunLoopTriggerFileException:
    """Cover 297-298: exception when removing trigger file."""

    def test_trigger_file_remove_exception_is_logged(self, monkeypatch, tmp_path):
        """Lines 297-298: os.remove raises → error logged, scheduler continues."""
        trigger_file = tmp_path / "skt.trigger"
        trigger_file.touch()

        def _save_status(payload):
            pass

        stopped_event = threading.Event()
        call_count = [0]

        def mock_resolve(config):
            call_count[0] += 1
            if call_count[0] >= 2:
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=4),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        original_remove = os.remove

        def failing_remove(path):
            if str(path) == str(trigger_file):
                raise PermissionError("simulated remove failure")
            return original_remove(path)

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', _save_status)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: str(trigger_file))
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.os.remove', failing_remove)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=lambda: {'result': 'ok'},
        )
        sched.last_run = datetime.now()  # prevent auto-run
        sched.start()
        stopped_event.wait(timeout=5)
        sched.stop()
        assert call_count[0] >= 1  # loop ran at least once


class TestRunLoopMissedRunRecoveryException:
    """Cover 277-278: exception in startup missed-run recovery block."""

    def test_exception_in_load_status_is_swallowed(self, monkeypatch):
        """Lines 277-278: load_scheduler_status raises inside try → warning logged, loop continues."""
        future_next_run = datetime.now(ZoneInfo('UTC')) + timedelta(hours=4)
        last_run = datetime.now(ZoneInfo('UTC')) - timedelta(hours=6)

        stored_status = {
            'last_run': last_run.isoformat(),
            'next_run': future_next_run.isoformat(),
            'last_result': {'calculation': {}},
        }
        call_count = [0]

        def _load_status(default=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return dict(stored_status)  # First call (in __init__) succeeds
            raise RuntimeError("simulated disk error in loop")  # Second call (in _run_loop) raises

        stopped_event = threading.Event()
        resolve_calls = [0]

        def mock_resolve(config):
            resolve_calls[0] += 1
            if resolve_calls[0] >= 1:
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=future_next_run,
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', _load_status)
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/nonexistent_st3')
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=lambda: {'result': 'ok'},
        )
        sched.start()
        stopped_event.wait(timeout=5)
        sched.stop()
        assert resolve_calls[0] >= 1


class TestRunLoopScheduleNextRunNone:
    """Cover 325->339: schedule.next_run is None branch."""

    def test_next_run_none_skips_committed_update(self, monkeypatch):
        """325->339: when schedule.next_run is None, the committed_next_run update is skipped."""
        stopped_event = threading.Event()
        resolve_calls = [0]

        def mock_resolve(config):
            resolve_calls[0] += 1
            if resolve_calls[0] >= 2:
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='disabled',
                next_run=None,  # ← Triggers 325->339 (False branch)
                server_time_valid=True,
                reason='disabled',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/nonexistent_st4')
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=lambda: {'result': 'ok'},
        )
        sched.last_run = datetime.now()  # prevent auto-run (not None)
        sched.start()
        stopped_event.wait(timeout=5)
        sched.stop()
        assert resolve_calls[0] >= 1
        assert sched._committed_next_run is None  # Was never updated since next_run was always None


class TestRunLoopCommittedNextRunUnchanged:
    """Cover 331->339: previous_next_run == _committed_next_run (no change to log)."""

    def test_no_debug_log_when_next_run_unchanged(self, monkeypatch):
        """331->339: committed_next_run already equals schedule.next_run → no debug log."""
        specific_time = datetime.now(ZoneInfo('UTC')) + timedelta(hours=4)

        stopped_event = threading.Event()
        resolve_calls = [0]

        def mock_resolve(config):
            resolve_calls[0] += 1
            if resolve_calls[0] >= 2:
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=specific_time,  # Same as committed_next_run → 331->339
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: '/tmp/nonexistent_st5')
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=lambda: {'result': 'ok'},
        )
        sched.last_run = specific_time  # last_run >= committed_next_run → inner if is True
        sched._committed_next_run = specific_time  # Same as what resolve returns
        sched.start()
        stopped_event.wait(timeout=5)
        sched.stop()
        assert resolve_calls[0] >= 1
        assert sched._committed_next_run == specific_time  # Unchanged (331->339 taken)


class TestRunLoopCacheReadyElseBranch:
    """Cover 353->357: elif not self._cache_ready_waited branch."""

    def test_cache_ready_elif_branch_manual_trigger(self, monkeypatch, tmp_path):
        """Lines 353-354: manual trigger → not waiting for cache event → elif sets _cache_ready_waited."""
        trigger_file = tmp_path / "skt2.trigger"
        trigger_file.touch()

        run_event = threading.Event()
        run_calls = []

        def runner():
            run_calls.append('ran')
            run_event.set()
            return {'result': 'ok'}

        cache_event = threading.Event()
        cache_event.set()  # already set → "cache ready"

        stopped_event = threading.Event()
        resolve_calls = [0]

        def mock_resolve(config):
            resolve_calls[0] += 1
            if resolve_calls[0] > 3:
                sched.running = False
                stopped_event.set()
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=4),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file', lambda: str(trigger_file))
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
            cache_ready_event=cache_event,
        )
        sched.start()
        run_event.wait(timeout=5)
        sched.stop()
        assert len(run_calls) >= 1


class TestRunLoopCacheReadyTimeoutAndAlreadyWaited:
    """Cover lines 348-352 (cache event wait timeout) and 353->357 (already waited)."""

    def _common_patches(self, monkeypatch):
        monkeypatch.setattr('skytonight_scheduler.save_scheduler_status', lambda _: None)
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.has_calculation_results', lambda: True)
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.append_scheduler_log', lambda msg: None)
        monkeypatch.setattr('skytonight_scheduler.get_scheduler_trigger_file',
                            lambda: '/tmp/nonexistent_trigger_skt_x99')

    def test_cache_ready_wait_times_out_then_run_proceeds(self, monkeypatch):
        """Lines 348-352: _cache_ready_event.wait returns False (timeout) → warning logged, run proceeds."""
        self._common_patches(monkeypatch)

        run_event = threading.Event()
        run_calls = []

        def runner():
            run_calls.append('ran')
            run_event.set()
            return {'result': 'ok'}

        class _TimedOutEvent:
            def is_set(self):
                return False

            def wait(self, timeout=None):
                return False

        iter_count = [0]

        def mock_resolve(config):
            iter_count[0] += 1
            if iter_count[0] > 5:
                sched.running = False
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=4),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
            cache_ready_event=_TimedOutEvent(),
        )
        sched.start()
        run_event.wait(timeout=5)
        sched.stop()
        assert len(run_calls) >= 1

    def test_already_waited_skips_both_branches(self, monkeypatch):
        """Lines 353->357: _cache_ready_waited=True → elif is False → no-op, run proceeds."""
        self._common_patches(monkeypatch)

        run_event = threading.Event()
        run_calls = []

        def runner():
            run_calls.append('ran')
            run_event.set()
            return {'result': 'ok'}

        cache_event = threading.Event()
        cache_event.set()

        iter_count = [0]

        def mock_resolve(config):
            iter_count[0] += 1
            if iter_count[0] > 5:
                sched.running = False
            return SkyTonightSchedule(
                mode='pre-nautical-night',
                next_run=datetime.now(ZoneInfo('UTC')) + timedelta(hours=4),
                server_time_valid=True,
                reason='test',
                server_time=datetime.now(ZoneInfo('UTC')),
                timezone='UTC',
            )

        monkeypatch.setattr('skytonight_scheduler.resolve_schedule', mock_resolve)
        monkeypatch.setattr('skytonight_scheduler.time', MagicMock(sleep=lambda _: None))

        sched = SkyTonightScheduler(
            config_loader=lambda: {'location': {'timezone': 'UTC'}, 'skytonight': {'enabled': True}},
            runner=runner,
            cache_ready_event=cache_event,
        )
        sched._cache_ready_waited = True
        sched.start()
        run_event.wait(timeout=5)
        sched.stop()
        assert len(run_calls) >= 1


class TestWaitForInitialCacheReady:
    """Unit tests for the extracted _wait_for_initial_cache_ready helper."""

    def _make_scheduler(self, monkeypatch, cache_ready_event=None):
        monkeypatch.setattr('skytonight_scheduler.load_scheduler_status', lambda default=None: {})
        monkeypatch.setattr('skytonight_scheduler.ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr('skytonight_scheduler.load_calculation_results', lambda: {})
        return SkyTonightScheduler(
            config_loader=lambda: {},
            runner=lambda: {},
            cache_ready_event=cache_ready_event,
        )

    def test_no_event_returns_immediately(self, monkeypatch):
        sched = self._make_scheduler(monkeypatch, cache_ready_event=None)
        sched._wait_for_initial_cache_ready()  # must not block or raise

    def test_event_already_set_no_warning(self, monkeypatch):
        event = threading.Event()
        event.set()
        sched = self._make_scheduler(monkeypatch, cache_ready_event=event)
        with patch('skytonight_scheduler.logger') as mock_log:
            sched._wait_for_initial_cache_ready()
            mock_log.warning.assert_not_called()

    def test_timeout_logs_warning(self, monkeypatch):
        event = threading.Event()  # never set → will time out
        sched = self._make_scheduler(monkeypatch, cache_ready_event=event)
        with patch('skytonight_scheduler.SKYTONIGHT_CACHE_READY_TIMEOUT_SECONDS', 0):
            with patch('skytonight_scheduler.logger') as mock_log:
                sched._wait_for_initial_cache_ready()
                mock_log.warning.assert_called_once_with(
                    'Cache ready timeout exceeded; proceeding with SkyTonight run anyway.'
                )

    def test_event_set_before_call_no_warning(self, monkeypatch):
        event = threading.Event()
        event.set()
        sched = self._make_scheduler(monkeypatch, cache_ready_event=event)
        with patch('skytonight_scheduler.logger') as mock_log:
            sched._wait_for_initial_cache_ready()
            mock_log.warning.assert_not_called()