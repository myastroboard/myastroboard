"""
SkyTonight Scheduler Management
Handles the SkyTonight scheduler lifecycle, including creation, status, and refresh logic.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from constants import SKYTONIGHT_CALCULATION_LOG_FILE
from logging_config import get_logger
from repo_config import load_config
from skytonight_catalogue_builder import build_and_save_default_dataset
from skytonight_calculator import run_calculations, load_calculation_results
from skytonight_targets import invalidate_targets_dataset_cache
from skytonight_storage import (
    ensure_skytonight_directories,
    get_scheduler_lock_file as get_skytonight_scheduler_lock_file,
    get_scheduler_status_file as get_skytonight_scheduler_status_file,
)

# Windows-compatible file locking
if sys.platform == 'win32':
    import msvcrt
else:  # pragma: no cover
    import fcntl

logger = get_logger(__name__)


# ============================================================
# Log helpers
# ============================================================


def _append_skytonight_calculation_log(status: str, payload: Dict[str, Any]) -> None:
    """Append a single line to the SkyTonight calculation log."""
    ensure_skytonight_directories()
    log_entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'payload': payload,
    }
    try:
        with open(SKYTONIGHT_CALCULATION_LOG_FILE, 'a', encoding='utf-8') as file_obj:
            file_obj.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        _trim_calculation_log(SKYTONIGHT_CALCULATION_LOG_FILE, max_runs=5)
    except Exception as exc:
        logger.warning(f'Failed to append SkyTonight calculation log: {exc}')


def _trim_calculation_log(log_path: str, max_runs: int = 5) -> None:
    """Keep only the last *max_runs* runs (2 lines each) in the calculation log."""
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = [line for line in f.readlines() if line.strip()]
        max_lines = max_runs * 2
        if len(lines) > max_lines:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-max_lines:])
    except Exception:
        pass  # log rotation is best-effort; failure must not abort the scheduler


# ============================================================
# Refresh pipeline
# ============================================================


def _run_skytonight_refresh() -> Dict[str, Any]:
    """Run the current SkyTonight refresh pipeline.

    Two phases:
    1. Rebuild the targets dataset (catalogue ingestion from PyOngc, MPC…).
    2. Run observability calculations for tonight and write the results cache.
    """
    ensure_skytonight_directories()
    config = load_config()
    comet_source_mode = str(
        config.get('skytonight', {}).get('datasets', {}).get('comets', {}).get('source') or 'mpc+jpl'
    )

    # --- Phase 1: catalogue dataset ---
    try:
        from skytonight_calculator import _set_progress as _calc_set_progress

        _calc_set_progress('build_dataset')
    except Exception:
        pass  # progress reporting is optional — build proceeds regardless

    try:
        dataset_result = build_and_save_default_dataset(comet_source_mode=comet_source_mode)
        metadata = dataset_result.get('metadata', {}) if isinstance(dataset_result, dict) else {}
        dataset_counts = metadata.get('counts', {}) if isinstance(metadata, dict) else {}
        dataset_payload = {
            'dataset_generated': True,
            'generated_at': metadata.get('generated_at'),
            'sources': metadata.get('sources', []),
            'counts': dataset_counts,
        }
        _append_skytonight_calculation_log('dataset_success', dataset_payload)
    except Exception as exc:
        _append_skytonight_calculation_log('dataset_error', {'error': str(exc), 'comet_source_mode': comet_source_mode})
        raise

    # Invalidate the in-memory dataset cache so run_calculations() loads the
    # freshly built file instead of the previous run's stale objects.  This
    # also releases the old ~13 000-target list from RAM.
    invalidate_targets_dataset_cache()

    # --- Phase 2: observability calculations ---
    try:
        calc_result = run_calculations(config=config)
        _append_skytonight_calculation_log('calculation_success', calc_result)
    except Exception as exc:
        _append_skytonight_calculation_log('calculation_error', {'error': str(exc)})
        # Calculations failing is not fatal - the dataset is still usable.
        logger.error(f'SkyTonight observability calculations failed: {exc}')
        calc_result = {}

    return {**dataset_payload, 'calculation': calc_result}


# ============================================================
# Scheduler lifecycle
# ============================================================


def get_or_create_skytonight_scheduler(app, cache_ready_event=None):
    """Get the SkyTonight scheduler instance, creating it if necessary.

    *app* must be the Flask application instance (the real object, not a proxy).
    """
    if 'skytonight_scheduler' not in app.config:
        lock_file_path = get_skytonight_scheduler_lock_file()
        lock_file = None

        try:
            lock_file = open(lock_file_path, 'w')

            if sys.platform == 'win32':
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    if not app.config.get('skytonight_scheduler_lock_logged'):
                        logger.debug(
                            'SkyTonight scheduler already running in another worker process, skipping creation'
                        )
                        app.config['skytonight_scheduler_lock_logged'] = True
                    app.config['is_skytonight_scheduler_worker'] = False
                    lock_file.close()
                    return None
            else:  # pragma: no cover
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            logger.debug('Creating SkyTonight scheduler instance (acquired lock)...')
            from skytonight_scheduler import SkyTonightScheduler

            scheduler = SkyTonightScheduler(
                config_loader=load_config,
                runner=_run_skytonight_refresh,
                app=app,
                cache_ready_event=cache_ready_event,
            )
            scheduler.start()
            app.config['skytonight_scheduler'] = scheduler
            app.config['skytonight_scheduler_lock_file'] = lock_file
            app.config['is_skytonight_scheduler_worker'] = True
            logger.debug('SkyTonight scheduler created and started successfully.')

        except (IOError, OSError):
            if not app.config.get('skytonight_scheduler_lock_logged'):
                logger.debug('SkyTonight scheduler already running in another worker process, skipping creation')
                app.config['skytonight_scheduler_lock_logged'] = True
            app.config['is_skytonight_scheduler_worker'] = False
            if lock_file is not None:
                try:
                    lock_file.close()
                except Exception:
                    pass
            return None
        except Exception as e:
            if lock_file is not None:
                try:
                    lock_file.close()
                except Exception:
                    pass
            logger.error(f'Failed to create SkyTonight scheduler: {e}')
            app.config['is_skytonight_scheduler_worker'] = False
            return None

    return app.config.get('skytonight_scheduler')


def get_skytonight_scheduler_for_api():
    """Get SkyTonight scheduler for API endpoints (call inside a request context)."""
    from flask import current_app

    scheduler = get_or_create_skytonight_scheduler(current_app)
    if scheduler:
        return scheduler

    lock_file_path = get_skytonight_scheduler_lock_file()
    if os.path.exists(lock_file_path):
        test_file = None
        try:
            test_file = open(lock_file_path, 'r')
            if sys.platform == 'win32':
                try:
                    msvcrt.locking(test_file.fileno(), msvcrt.LK_NBLCK, 1)
                    return None
                except OSError:
                    return 'remote_scheduler'
            else:  # pragma: no cover
                fcntl.flock(test_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None
        except (IOError, OSError):
            return 'remote_scheduler'
        finally:
            if test_file is not None:
                test_file.close()

    return None


def get_remote_skytonight_scheduler_status() -> Dict[str, Any]:
    """Get SkyTonight scheduler status from shared file (used by remote workers)."""
    status_file = get_skytonight_scheduler_status_file()
    try:
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as file_obj:
                status = json.load(file_obj)
                if not isinstance(status.get('last_result'), dict):
                    status['last_result'] = {}

                # Backfill minimal last_result details when worker restarted and
                # persisted status lacks payload despite existing calculation cache.
                if not status['last_result']:
                    try:
                        calc_cache = load_calculation_results()
                        metadata = calc_cache.get('metadata', {}) if isinstance(calc_cache, dict) else {}
                        night_start = metadata.get('night_start')
                        night_end = metadata.get('night_end')
                        counts = metadata.get('counts', {}) if isinstance(metadata, dict) else {}
                        if night_start or night_end or counts:
                            status['last_result'] = {
                                'calculation': {
                                    'counts': {
                                        'deep_sky': counts.get('deep_sky', 0),
                                        'bodies': counts.get('bodies', 0),
                                        'comets': counts.get('comets', 0),
                                    },
                                    'night_start': night_start,
                                    'night_end': night_end,
                                    'night_found': bool(night_start and night_end),
                                }
                            }
                    except Exception:
                        pass  # stale or malformed results cache — leave last_result unset

                progress = status.get('progress')
                if not isinstance(progress, dict):
                    status['progress'] = {
                        'execution_duration_seconds': None,
                        'last_execution_duration_seconds': None,
                    }
                else:
                    progress.setdefault('execution_duration_seconds', None)
                    progress.setdefault('last_execution_duration_seconds', None)

                status['worker'] = 'remote'
                return status
    except Exception as e:
        logger.error(f'Failed to read remote SkyTonight scheduler status: {e}')

    config = load_config()
    return {
        'running': True,
        'enabled': bool(config.get('skytonight', {}).get('enabled', False)),
        'last_run': None,
        'next_run': None,
        'is_executing': False,
        'mode': 'remote',
        'reason': 'SkyTonight scheduler status unavailable from remote worker',
        'server_time_valid': False,
        'server_time': None,
        'timezone': str(config.get('location', {}).get('timezone') or 'UTC'),
        'worker': 'remote',
        'last_error': None,
        'last_result': {},
        'progress': {
            'execution_duration_seconds': None,
        },
    }
