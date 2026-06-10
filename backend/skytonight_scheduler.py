"""SkyTonight scheduler for internal dataset refresh and calculation orchestration."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo

from logging_config import get_logger
from skytonight_storage import (
    append_scheduler_log,
    ensure_skytonight_directories,
    get_scheduler_trigger_file,
    has_calculation_results,
    load_scheduler_status,
    save_scheduler_status,
)
from skytonight_calculator import load_calculation_results
from sun_phases import SunService

logger = get_logger(__name__)

SKYTONIGHT_FALLBACK_INTERVAL_SECONDS = 6 * 60 * 60
SKYTONIGHT_PRE_NIGHT_OFFSET = timedelta(hours=1)
SKYTONIGHT_POST_NIGHT_OFFSET = timedelta(hours=1)


@dataclass(frozen=True)
class SkyTonightSchedule:
    mode: str
    next_run: Optional[datetime]
    server_time_valid: bool
    reason: str
    server_time: datetime
    timezone: str


def _parse_local_datetime(value: str, timezone_name: str) -> Optional[datetime]:
    text = str(value or '').strip()
    if not text or text == 'Not found':
        return None
    try:
        parsed = datetime.strptime(text, '%Y-%m-%d %H:%M')
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo(timezone_name))


def _is_server_time_valid(current_time: datetime, timezone_name: str) -> bool:
    if current_time.year < 2024:
        return False
    try:
        ZoneInfo(timezone_name)
    except Exception:
        return False
    return True


def resolve_schedule(config: Dict[str, Any], now: Optional[datetime] = None) -> SkyTonightSchedule:
    """Resolve the next SkyTonight run according to scheduler requirements."""
    location = config.get('location', {}) if isinstance(config, dict) else {}
    timezone_name = str(location.get('timezone') or 'UTC')
    zone = ZoneInfo(timezone_name)
    current_time = now.astimezone(zone) if now else datetime.now(zone)
    valid_time = _is_server_time_valid(current_time, timezone_name)

    if not valid_time:
        return SkyTonightSchedule(
            mode='fallback-6h',
            next_run=current_time + timedelta(seconds=SKYTONIGHT_FALLBACK_INTERVAL_SECONDS),
            server_time_valid=False,
            reason='Server time or timezone is not trusted; using 6-hour fallback cadence.',
            server_time=current_time,
            timezone=timezone_name,
        )

    candidates = []

    latitude = location.get('latitude')
    longitude = location.get('longitude')
    if latitude is not None and longitude is not None:
        sun_service = SunService(latitude=latitude, longitude=longitude, timezone=timezone_name)
        for report in (sun_service.get_today_report(), sun_service.get_tomorrow_report()):
            # Post-nautical-night run: 1 hour after nautical dawn
            dawn_time = _parse_local_datetime(report.nautical_dawn, timezone_name)
            if dawn_time is not None:
                candidate = dawn_time + SKYTONIGHT_POST_NIGHT_OFFSET
                if candidate > current_time:
                    candidates.append(
                        ('post-nautical-night', candidate, 'One hour after nautical night ends.'),
                    )
            # Pre-nautical-night run: 1 hour before nautical dusk
            dusk_time = _parse_local_datetime(report.nautical_dusk, timezone_name)
            if dusk_time is None:
                continue
            candidate = dusk_time - SKYTONIGHT_PRE_NIGHT_OFFSET
            if candidate > current_time:
                candidates.append(
                    ('pre-nautical-night', candidate, 'One hour before nautical night.'),
                )

    if not candidates:
        # Fallback if location is not configured or no dawn/dusk times are available
        candidates.append(
            (
                'fallback-6h',
                current_time + timedelta(seconds=SKYTONIGHT_FALLBACK_INTERVAL_SECONDS),
                'No twilight times available; using 6-hour fallback cadence.',
            )
        )

    selected_mode, selected_time, reason = min(candidates, key=lambda item: item[1])
    return SkyTonightSchedule(
        mode=selected_mode,
        next_run=selected_time,
        server_time_valid=True,
        reason=reason,
        server_time=current_time,
        timezone=timezone_name,
    )


class SkyTonightScheduler:
    """Internal scheduler that refreshes the SkyTonight dataset and writes shared status."""

    def __init__(
        self,
        config_loader: Callable[[], Dict[str, Any]],
        runner: Callable[[], Dict[str, Any]],
        app=None,
        cache_ready_event: Optional[threading.Event] = None,
    ):
        self.config_loader = config_loader
        self.runner = runner
        self.app = app
        self.running = False
        self.thread = None
        self.last_run: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_result: Dict[str, Any] = {}
        self.execution_start_time: Optional[datetime] = None
        self.is_executing = False
        self.current_mode = 'idle'
        self.current_reason = ''
        self._triggered_mode: Optional[str] = None
        self._triggered_reason: Optional[str] = None
        self._execution_lock = threading.Lock()
        self._scheduler_started = False
        self.last_execution_duration_seconds: Optional[int] = None
        # Optional event set by CacheScheduler after first successful update.
        # When present, the first automatic run is delayed until caches are warm.
        self._cache_ready_event: Optional[threading.Event] = cache_ready_event
        self._cache_ready_waited = False
        # The next scheduled run time that the loop commits to.  Persisted to
        # the status file so it survives restarts and is shown in the UI.
        self._committed_next_run: Optional[datetime] = None
        ensure_skytonight_directories()

        stored_status = load_scheduler_status(default={})
        last_run_text = str(stored_status.get('last_run') or '').strip()
        if last_run_text:
            try:
                self.last_run = datetime.fromisoformat(last_run_text)
            except ValueError:
                self.last_run = None
        stored_last_error = stored_status.get('last_error')
        if isinstance(stored_last_error, str) and stored_last_error.strip():
            self.last_error = stored_last_error
        elif stored_last_error is None:
            self.last_error = None
        else:
            self.last_error = str(stored_last_error)

        stored_last_result = stored_status.get('last_result')
        if isinstance(stored_last_result, dict):
            self.last_result = stored_last_result
        elif stored_last_result:
            self.last_result = {'result': stored_last_result}

        stored_last_duration = stored_status.get('progress', {}).get('last_execution_duration_seconds')
        try:
            if stored_last_duration is not None:
                self.last_execution_duration_seconds = int(stored_last_duration)
        except (TypeError, ValueError):
            self.last_execution_duration_seconds = None

        if not self.last_result:
            # Defensive backfill for workers restarted with an older/incomplete status file.
            try:
                calc_cache = load_calculation_results()
                metadata = calc_cache.get('metadata', {}) if isinstance(calc_cache, dict) else {}
                night_start = metadata.get('night_start')
                night_end = metadata.get('night_end')
                counts = metadata.get('counts', {}) if isinstance(metadata, dict) else {}
                if night_start or night_end or counts:
                    self.last_result = {
                        'calculation': {
                            'counts': {
                                'deep_sky': counts.get('deep_sky', 0),
                                'bodies': counts.get('bodies', 0),
                                'comets': counts.get('comets', 0),
                            },
                            'night_start': night_start,
                            'night_end': night_end,
                            'night_found': bool(night_start and night_end),
                        },
                    }
            except Exception:
                pass  # stale or malformed results cache — leave last_result unset
        next_run_text = str(stored_status.get('next_run') or '').strip()
        if next_run_text:
            try:
                self._committed_next_run = datetime.fromisoformat(next_run_text)
            except ValueError:
                pass  # malformed ISO timestamp in stored status — ignore it

    def start(self):
        if self._scheduler_started:
            logger.warning('SkyTonight scheduler already started')
            return
        self._scheduler_started = True
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info('SkyTonight scheduler started')
        self._write_status()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
        logger.info('SkyTonight scheduler stopped')
        self._write_status()

    def _run_loop(self):
        # _committed_next_run is now an instance variable initialised in
        # __init__ from the persisted status file.  Use a local alias for
        # readability; writes go back through self._committed_next_run so that
        # _write_status always has access to the real committed value.

        # Missed-run recovery: if the app was restarted while a
        # post-nautical-night run was pending (status file holds the
        # *evening* next_run that was written after midnight when
        # resolve_schedule stopped seeing the morning dawn), detect the skipped
        # morning slot via last_result.calculation.night_end and restore it.
        if self.last_run is not None and self._committed_next_run is not None:
            try:
                startup_now = datetime.now().astimezone()
                stored = load_scheduler_status(default={})
                last_result = stored.get('last_result') or {}
                calculation = last_result.get('calculation') or {}
                night_end_str = str(calculation.get('night_end') or '').strip()
                if night_end_str:
                    night_end_dt = datetime.fromisoformat(night_end_str)
                    missed_slot = night_end_dt + SKYTONIGHT_POST_NIGHT_OFFSET
                    if (
                        self.last_run < missed_slot
                        and missed_slot < startup_now
                        and missed_slot < self._committed_next_run
                    ):
                        logger.info(
                            'Missed post-night run detected on startup: expected slot %s '
                            'is in the past (committed=%s, last_run=%s). Restoring missed slot.',
                            missed_slot.isoformat(),
                            self._committed_next_run.isoformat(),
                            self.last_run.isoformat(),
                        )
                        self._committed_next_run = missed_slot
                        logger.debug(
                            'next_run changed (startup missed-run recovery): %s',
                            self._committed_next_run.isoformat(),
                        )
            except Exception as exc:
                logger.warning('Could not check for missed post-night run on startup: %s', exc)

        while self.running:
            config = self.config_loader()
            skytonight_config = config.get('skytonight', {}) if isinstance(config, dict) else {}
            if not bool(skytonight_config.get('enabled', False)):
                self.current_mode = 'disabled'
                self.current_reason = 'SkyTonight is disabled in configuration.'
                self._write_status()
                time.sleep(5)
                continue

            trigger_file = get_scheduler_trigger_file()
            manual_trigger = False
            if os.path.exists(trigger_file):
                try:
                    os.remove(trigger_file)
                    manual_trigger = True
                    logger.info('SkyTonight manual trigger detected')
                except Exception as error:
                    logger.error(f'Failed to remove SkyTonight trigger file: {error}')

            schedule = resolve_schedule(config)
            self.current_mode = schedule.mode
            self.current_reason = schedule.reason

            should_run = manual_trigger or self.last_run is None
            if not should_run and not has_calculation_results():
                logger.info(
                    'SkyTonight calculation results are missing; ' 'triggering run regardless of last_run timestamp.'
                )
                should_run = True
            # Use the committed next_run (set in a previous iteration when it
            # was still in the future) instead of the freshly-computed one so
            # the comparison can actually become True once time advances past it.
            if not should_run and self._committed_next_run is not None:
                should_run = schedule.server_time >= self._committed_next_run and (
                    self.last_run is None or self.last_run < self._committed_next_run
                )

            # Advance the committed run time only once the previous run has
            # actually fired (last_run has reached the committed slot).
            # Advancing unconditionally every iteration would overwrite a
            # pending morning post-night slot with the evening pre-night slot
            # whenever the calendar date rolls over at midnight: the dawn slot
            # lives in the previous day's noon-noon computation window and
            # disappears from resolve_schedule results after midnight.
            if schedule.next_run is not None:
                if self._committed_next_run is None or (
                    self.last_run is not None and self.last_run >= self._committed_next_run
                ):
                    previous_next_run = self._committed_next_run
                    self._committed_next_run = schedule.next_run
                    if previous_next_run != self._committed_next_run:
                        logger.debug(
                            'next_run changed: %s -> %s (mode=%s)',
                            previous_next_run.isoformat() if previous_next_run else 'None',
                            self._committed_next_run.isoformat(),
                            schedule.mode,
                        )

            if should_run and not self._execution_lock.locked():
                # On the first automatic run, wait for the cache scheduler to finish
                # its initial update so SkyTonight calculations use warm caches.
                if (
                    not manual_trigger
                    and not self._cache_ready_waited
                    and self._cache_ready_event is not None
                    and not self._cache_ready_event.is_set()
                ):
                    self._cache_ready_waited = True
                    logger.info('Waiting up to 5 minutes for initial cache update ' 'before first SkyTonight run...')
                    ready = self._cache_ready_event.wait(timeout=300)
                    if not ready:  # pragma: no cover  # race-condition path: event set between is_set() check and wait()
                        logger.warning('Cache ready timeout exceeded; proceeding with SkyTonight run anyway.')
                self._cache_ready_waited = True
                # Set is_executing optimistically before the thread lands so the
                # status file never shows is_executing=False during pending start.
                self.is_executing = True
                self.execution_start_time = datetime.now().astimezone()
                # Preserve the mode/reason that triggered this run so the status
                # file continues to show it while the calculation runs (the loop
                # calls resolve_schedule every 5 s and would otherwise overwrite
                # mode with whatever the NEXT schedule is).
                self._triggered_mode = 'manual' if manual_trigger else schedule.mode
                self._triggered_reason = 'Manually triggered.' if manual_trigger else schedule.reason
                threading.Thread(
                    target=self._execute_cycle,
                    kwargs={'manual_trigger': manual_trigger},
                    daemon=True,
                ).start()

            # Always write status every loop iteration so progress duration
            # stays live in the status file while execution is running.
            self._write_status(schedule=schedule)
            time.sleep(5)

    def _execute_cycle(self, manual_trigger: bool = False):
        config = self.config_loader()
        if not bool(config.get('skytonight', {}).get('enabled', False)):
            self.current_mode = 'disabled'
            self.current_reason = 'SkyTonight is disabled in configuration.'
            self._write_status()
            return

        if self._execution_lock.locked():
            logger.warning('SkyTonight execution already in progress, skipping new run')
            self.is_executing = False
            self.execution_start_time = None
            return

        with self._execution_lock:
            self.is_executing = True
            self.execution_start_time = datetime.now().astimezone()
            self.last_error = None
            self._write_status()

            try:
                logger.info('Starting SkyTonight execution cycle')
                if self.app is not None:
                    with self.app.app_context():
                        result = self.runner()
                else:
                    result = self.runner()

                self.last_result = result if isinstance(result, dict) else {'result': result}
                self.last_run = datetime.now().astimezone()
                self.current_mode = 'manual' if manual_trigger else 'scheduled'
                self._triggered_mode = None
                self._triggered_reason = None
                append_scheduler_log(f"[{self.last_run.isoformat()}] SkyTonight run completed: {self.last_result}\n")
                logger.info('SkyTonight execution cycle completed successfully')
            except Exception as error:
                self.last_error = str(error)
                self.last_result = {}
                failure_time = datetime.now().astimezone()
                append_scheduler_log(f'[{failure_time.isoformat()}] SkyTonight run failed: {error}\n')
                logger.error(f'SkyTonight execution cycle failed: {error}')
            finally:
                if self.execution_start_time:  # pragma: no branch
                    self.last_execution_duration_seconds = int(
                        (datetime.now().astimezone() - self.execution_start_time).total_seconds()
                    )
                self.is_executing = False
                self.execution_start_time = None
                self._triggered_mode = None
                self._triggered_reason = None
                self._write_status()

    def _write_status(self, schedule: Optional[SkyTonightSchedule] = None):
        config = self.config_loader()
        enabled = bool(config.get('skytonight', {}).get('enabled', False))

        if schedule is None:
            schedule = resolve_schedule(config)

        if not enabled:
            schedule = SkyTonightSchedule(
                mode='disabled',
                next_run=None,
                server_time_valid=schedule.server_time_valid,
                reason='SkyTonight is disabled in configuration.',
                server_time=schedule.server_time,
                timezone=schedule.timezone,
            )

        execution_duration_seconds = None
        if self.is_executing and self.execution_start_time:
            execution_duration_seconds = int((datetime.now().astimezone() - self.execution_start_time).total_seconds())

        try:
            from skytonight_calculator import get_calculation_progress

            calc_progress = get_calculation_progress()
        except Exception:
            calc_progress = {}

        payload = {
            'running': self.running,
            'enabled': enabled,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            # Use the committed next_run (the actual slot the loop will fire on)
            # rather than the freshly-computed schedule.next_run, which can
            # diverge after midnight when the dawn slot leaves the computation
            # window.  Fall back to schedule.next_run when no commit exists yet.
            # When disabled, always return None regardless of any previously committed run.
            'next_run': (
                None
                if not enabled
                else (
                    self._committed_next_run.isoformat()
                    if self._committed_next_run is not None
                    else (schedule.next_run.isoformat() if schedule.next_run else None)
                )
            ),
            'is_executing': self.is_executing,
            # While a run is executing, report the mode/reason that *triggered*
            # it rather than the freshly-computed next schedule (which drifts to
            # the following slot as soon as the triggered time passes).
            'mode': self._triggered_mode if self.is_executing and self._triggered_mode else schedule.mode,
            'reason': self._triggered_reason if self.is_executing and self._triggered_reason else schedule.reason,
            'server_time_valid': schedule.server_time_valid,
            'server_time': schedule.server_time.isoformat(),
            'timezone': schedule.timezone,
            'last_error': self.last_error,
            'last_result': self.last_result,
            'progress': {
                'execution_duration_seconds': execution_duration_seconds,
                'last_execution_duration_seconds': self.last_execution_duration_seconds,
                **calc_progress,
            },
        }
        save_scheduler_status(payload)

    def get_status(self) -> Dict[str, Any]:
        config = self.config_loader()
        schedule = resolve_schedule(config)
        self._write_status(schedule=schedule)
        status = load_scheduler_status(default={})
        status.setdefault('running', self.running)
        status.setdefault('enabled', bool(config.get('skytonight', {}).get('enabled', False)))
        return status

    def trigger_now(self) -> Dict[str, Any]:
        if self._execution_lock.locked():
            return {'status': 'skipped', 'reason': 'execution already in progress'}
        threading.Thread(target=self._execute_cycle, kwargs={'manual_trigger': True}, daemon=True).start()
        return {'status': 'triggered'}
