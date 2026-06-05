"""
Server-side push notification scheduler.

Runs every POLL_INTERVAL_SECONDS in a background thread.
Evaluates N1-N7 trigger conditions using cached data, then sends Web Push
to subscribed users whose notifications are enabled and cooldown has elapsed.

Cooldown is tracked in-memory (resets on server restart, acceptable for a
5-minute scheduler - the worst case is one duplicate notification per restart).

Multi-worker safety: a process-level lock file (push_scheduler.lock) ensures
only one Gunicorn worker runs the scheduler. The OS releases the lock
automatically when the worker process exits, letting another worker take over.
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from logging_config import get_logger

if sys.platform == 'win32':
    import msvcrt
else:
    import fcntl

logger = get_logger(__name__)

POLL_INTERVAL_SLOW = 5 * 60  # 5 min - default
POLL_INTERVAL_FAST = 60  # 1 min - during/near active observation sessions

# {user_id: {trigger_id: last_sent_epoch_seconds}}
_last_sent: Dict[str, Dict[str, float]] = {}
_lock = threading.Lock()

# {user_id: set_of_entry_ids} - prevents re-sending N2 for the same plan entry
_n2_notified: Dict[str, set] = {}

# True when any user has an active or near (≤30 min) observation session
_any_active_night: bool = False

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_lock_file = None  # held open for the lifetime of the process that wins the lock


# ---------------------------------------------------------------------------
# Cooldown helpers
# ---------------------------------------------------------------------------


def _was_recently_notified(user_id: str, trigger_id: str, cooldown_s: float) -> bool:
    with _lock:
        last = _last_sent.get(user_id, {}).get(trigger_id)
    return last is not None and (time.monotonic() - last) < cooldown_s


def _mark_notified(user_id: str, trigger_id: str) -> None:
    with _lock:
        _last_sent.setdefault(user_id, {})[trigger_id] = time.monotonic()


# ---------------------------------------------------------------------------
# Push delivery
# ---------------------------------------------------------------------------


def _send(user: Any, trigger_id: str, title: str, body: str, url: str, ttl: int = 0, urgency: str = 'normal') -> None:
    """Send push to all subscriptions of a user and mark as notified.

    ttl:     seconds the push service keeps the message if the device is offline.
             Set to the trigger's lead time so offline devices still receive the
             alert when they come back within the relevant window.
    urgency: RFC 8030 urgency header. 'normal' (default) respects device Doze
             batching. Use 'high' only for very short windows (N3, N7) where
             immediate delivery matters and 'normal' might miss the event.
    """
    if not user.push_subscriptions:
        return

    from push_manager import send_push

    icon = '/static/ico/android/launchericon-192x192.png'
    badge = '/static/ico/android/launchericon-72x72.png'
    payload = {
        'title': title,
        'body': body,
        'icon': icon,
        'badge': badge,
        'tag': trigger_id,
        'data': {'url': url},
    }

    n_subs = len(user.push_subscriptions)
    logger.info(f"[{trigger_id}] Sending push to {user.username} ({n_subs} sub(s)): {title} - {body}")

    dead_endpoints = []
    delivered = 0
    for sub in user.push_subscriptions:
        endpoint = sub.get('endpoint', '')
        subscription_info = {'endpoint': endpoint, 'keys': sub.get('keys', {})}
        ok = send_push(subscription_info, payload, ttl=ttl, urgency=urgency)
        if ok:
            delivered += 1
        else:
            dead_endpoints.append(endpoint)

    logger.info(f"[{trigger_id}] Delivered to {delivered}/{n_subs} subscription(s) for {user.username}")

    if dead_endpoints:
        _cleanup_dead_subscriptions(user, dead_endpoints)

    # Only record the cooldown when at least one device actually received the push.
    # If every subscription failed, skip marking so the next poll can retry once
    # the user re-subscribes (page-load auto-resubscription).
    if delivered > 0:
        _mark_notified(user.user_id, trigger_id)


def _cleanup_dead_subscriptions(user: Any, endpoints: list) -> None:
    """Remove expired/invalid push subscriptions from the user."""
    try:
        from auth import user_manager

        user.push_subscriptions = [s for s in user.push_subscriptions if s.get('endpoint') not in endpoints]
        user_manager.save_users()
    except Exception as e:
        logger.warning(f"Failed to clean dead subscriptions for {user.username}: {e}")


# ---------------------------------------------------------------------------
# Trigger evaluation (per-user)
# ---------------------------------------------------------------------------


def _get_notif_prefs(user: Any) -> dict:
    """Extract notification trigger config from user preferences."""
    return user.preferences.get('notifications', {}).get('triggers', {})


def _t(user: Any, key: str, **params) -> str:
    """Translate a push notification string using the user's preferred language."""
    from i18n_utils import get_translated_message

    lang = user.preferences.get('language', 'en')
    return get_translated_message(f'settings.{key}', language=lang, **params)


def _check_n7_aurora(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        logger.debug(f"N7 skip {user.username}: no aurora cache")
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N7', {})
    if not t.get('enabled', True):
        logger.debug(f"N7 skip {user.username}: trigger disabled")
        return

    kp = cache_data.get('current', {}).get('kp_index')
    if not isinstance(kp, (int, float)):
        logger.debug(f"N7 skip {user.username}: kp_index missing or non-numeric ({kp!r})")
        return
    threshold = t.get('kp_threshold', 5)
    if kp < threshold:
        logger.debug(f"N7 skip {user.username}: kp={kp:.1f} below threshold={threshold}")
        return
    if _was_recently_notified(user.user_id, 'N7', 4 * 60 * 60):
        logger.debug(f"N7 skip {user.username}: cooldown active")
        return

    visibility_raw = cache_data.get('current', {}).get('visibility_level', '')
    vis_key = f'push_kp_visibility_{visibility_raw.lower().replace(" ", "_")}'
    translated_vis = _t(user, vis_key)
    visibility = visibility_raw if translated_vis.startswith('settings.') else translated_vis
    _send(
        user,
        'N7',
        _t(user, 'push_n7_title'),
        _t(user, 'push_n7_body', kp=f'{kp:.1f}', visibility=visibility),
        '/#forecast-astro/aurora',
        ttl=3600,
        urgency='high',
    )  # aurora: immediate delivery, can last ~1 h


def _check_n1_plan_start(user: Any, plan_payload: Optional[dict]) -> None:
    if not plan_payload or plan_payload.get('state') == 'none':
        logger.debug(f"N1 skip {user.username}: no active plan")
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N1', {})
    if not t.get('enabled', True):
        logger.debug(f"N1 skip {user.username}: trigger disabled")
        return
    if plan_payload.get('timeline', {}).get('is_inside_night'):
        logger.debug(f"N1 skip {user.username}: session already started")
        return

    plan = plan_payload.get('plan') or {}
    night_start_str = plan.get('night_start')
    if not night_start_str:
        logger.debug(f"N1 skip {user.username}: no night_start in plan")
        return

    try:
        night_start = datetime.fromisoformat(night_start_str)
        if night_start.tzinfo is None:
            night_start = night_start.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        ms_until = (night_start - now).total_seconds()
        lead_s = t.get('lead_minutes', 15) * 60
        logger.debug(f"N1 {user.username}: night_start in {ms_until:.0f}s, lead={lead_s}s")
        if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, 'N1', 2 * 60 * 60):
            minutes = round(ms_until / 60)
            _send(
                user,
                'N1',
                _t(user, 'push_n1_title'),
                _t(user, 'push_n1_body', minutes=minutes),
                '/#astrodex/plan-my-night',
                ttl=int(ms_until),
            )
    except Exception as e:
        logger.debug(f"N1 check error for {user.username}: {e}")


def _check_n2_next_target(user: Any, plan_payload: Optional[dict]) -> None:
    if not plan_payload or plan_payload.get('state') == 'none':
        logger.debug(f"N2 skip {user.username}: no active plan")
        return
    if not plan_payload.get('timeline', {}).get('is_inside_night'):
        logger.debug(f"N2 skip {user.username}: not inside night window")
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N2', {})
    if not t.get('enabled', True):
        logger.debug(f"N2 skip {user.username}: trigger disabled")
        return

    entries = (plan_payload.get('plan') or {}).get('entries', [])
    lead_s = t.get('lead_minutes', 5) * 60
    now = datetime.now(timezone.utc)

    notified_set = _n2_notified.setdefault(user.user_id, set())

    notified = False
    for entry in entries:
        if entry.get('done'):
            continue
        start_str = entry.get('timeline_start')
        if not start_str:
            continue
        try:
            start = datetime.fromisoformat(start_str)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            ms_until = (start - now).total_seconds()
            if ms_until <= 0:
                continue
            if ms_until > lead_s:
                logger.debug(f"N2 skip {user.username}: next undone target in {ms_until:.0f}s, outside lead={lead_s}s")
                notified = True  # treated as handled — suppress the fallthrough log
                break  # entries are chronological

            entry_id = entry.get('id') or entry.get('target_name') or entry.get('name', '?')
            if entry_id in notified_set:
                logger.debug(f"N2 skip {user.username}: already notified for {entry_id!r}")
                notified = True
                break
            notified_set.add(entry_id)
            minutes = round(ms_until / 60)
            name = entry.get('name') or entry.get('target_name', '?')
            _send(
                user,
                'N2',
                _t(user, 'push_n2_title'),
                _t(user, 'push_n2_body', name=name, minutes=minutes),
                '/#astrodex/plan-my-night',
                ttl=int(ms_until),
            )
            notified = True
            break
        except Exception as e:
            logger.debug(f"N2 entry check error for {user.username}: {e}")
    if not notified:
        logger.debug(f"N2 skip {user.username}: no undone targets with a future start time")


def _check_n6_darkness(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        logger.debug(f"N6 skip {user.username}: no sun_report cache")
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N6', {})
    if not t.get('enabled', True):
        logger.debug(f"N6 skip {user.username}: trigger disabled")
        return

    # Use the pre-computed UTC field to avoid timezone and cache-reset bugs.
    # (astronomical_dusk in sun.* is naive local time and the cache can refresh
    # after midnight UTC - before local dusk passes - resetting the countdown.)
    dusk_str = cache_data.get('next_astronomical_dusk_utc')
    if not dusk_str:
        logger.debug(f"N6 skip {user.username}: no next_astronomical_dusk_utc in cache")
        return
    try:
        dusk = datetime.fromisoformat(dusk_str)
        if dusk.tzinfo is None:
            dusk = dusk.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        ms_until = (dusk - now).total_seconds()
        lead_s = t.get('lead_minutes', 20) * 60
        logger.debug(f"N6 {user.username}: dusk in {ms_until:.0f}s, lead={lead_s}s")
        if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, 'N6', 8 * 60 * 60):
            minutes = round(ms_until / 60)
            try:
                from zoneinfo import ZoneInfo

                tz_name = cache_data.get('location', {}).get('timezone', 'UTC')
                dusk_local_time = dusk.astimezone(ZoneInfo(tz_name)).strftime('%H:%M')
            except Exception:
                dusk_local_time = ''
            _send(
                user,
                'N6',
                _t(user, 'push_n6_title'),
                _t(user, 'push_n6_body', minutes=minutes, time=dusk_local_time),
                '/#forecast-astro/astro-weather',
                ttl=int(ms_until),
            )
    except Exception as e:
        logger.debug(f"N6 check error for {user.username}: {e}")


def _check_n3_iss(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        logger.debug(f"N3 skip {user.username}: no iss_passes cache")
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N3', {})
    if not t.get('enabled', True):
        logger.debug(f"N3 skip {user.username}: trigger disabled")
        return

    lead_s = t.get('lead_minutes', 10) * 60
    now = datetime.now(timezone.utc)

    candidates = []
    for transit in cache_data.get('solar_transits', []):
        start_str = transit.get('start_time')
        if start_str:
            try:
                dt = datetime.fromisoformat(start_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now:
                    candidates.append((dt, 'solar'))
            except Exception as e:
                logger.debug(f"N3 {user.username}: bad solar transit timestamp {start_str!r}: {e}")
    for transit in cache_data.get('lunar_transits', []):
        start_str = transit.get('start_time')
        if start_str:
            try:
                dt = datetime.fromisoformat(start_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now:
                    candidates.append((dt, 'lunar'))
            except Exception as e:
                logger.debug(f"N3 {user.username}: bad lunar transit timestamp {start_str!r}: {e}")

    if not candidates:
        logger.debug(f"N3 skip {user.username}: no upcoming ISS transits")
        return
    candidates.sort(key=lambda x: x[0])
    next_dt, transit_type = candidates[0]
    ms_until = (next_dt - now).total_seconds()
    logger.debug(f"N3 {user.username}: next {transit_type} transit in {ms_until:.0f}s, lead={lead_s}s")
    if ms_until > lead_s:
        return
    if _was_recently_notified(user.user_id, 'N3', 60 * 60):
        logger.debug(f"N3 skip {user.username}: cooldown active")
        return

    minutes = round(ms_until / 60)
    body_key = 'push_n3_solar_body' if transit_type == 'solar' else 'push_n3_lunar_body'
    _send(
        user,
        'N3',
        _t(user, 'push_n3_title'),
        _t(user, body_key, minutes=minutes),
        '/#spaceflight/iss',
        ttl=int(ms_until),
        urgency='high',
    )  # short window (≤10 min): needs immediate delivery


def _check_n4_n5_eclipse(user: Any, solar_data: Optional[dict], lunar_data: Optional[dict]) -> None:
    triggers = _get_notif_prefs(user)
    now = datetime.now(timezone.utc)

    for trigger_id, cache_data, title_key, body_key, url in (
        ('N4', lunar_data, 'push_n4_title', 'push_n4_body', '/#forecast-astro/moon'),
        ('N5', solar_data, 'push_n5_title', 'push_n5_body', '/#forecast-astro/sun'),
    ):
        t = triggers.get(trigger_id, {})
        if not t.get('enabled', True):
            logger.debug(f"{trigger_id} skip {user.username}: trigger disabled")
            continue
        if not cache_data:
            logger.debug(f"{trigger_id} skip {user.username}: no cache data")
            continue

        peak_str = (cache_data.get('eclipse') or {}).get('peak_time')
        if not peak_str:
            logger.debug(f"{trigger_id} skip {user.username}: no peak_time in cache")
            continue
        try:
            peak = datetime.fromisoformat(peak_str)
            if peak.tzinfo is None:
                peak = peak.replace(tzinfo=timezone.utc)
            ms_until = (peak - now).total_seconds()
            lead_s = t.get('lead_minutes', 30) * 60
            logger.debug(f"{trigger_id} {user.username}: peak in {ms_until:.0f}s, lead={lead_s}s")
            if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, trigger_id, 4 * 60 * 60):
                minutes = round(ms_until / 60)
                _send(
                    user, trigger_id, _t(user, title_key), _t(user, body_key, minutes=minutes), url, ttl=int(ms_until)
                )
        except Exception as e:
            logger.debug(f"{trigger_id} check error for {user.username}: {e}")


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def _load_cache(key: str) -> Optional[dict]:
    try:
        from cache_store import load_shared_cache_entry

        entry = load_shared_cache_entry(key)
        return entry['data'] if entry else None
    except Exception:
        return None


def _pick_active_plan(user_id: str, username: str) -> Optional[dict]:
    """Return the most relevant plan payload across all of the user's plan files.

    The scheduler must check every plan file (default and telescope-specific)
    because plans are stored per telescope and the scheduler has no way to know
    which telescope the user had selected when they built the plan.

    Priority: plan where is_inside_night is True > any 'current' plan > first
    non-'none' plan found.
    """
    try:
        from plan_my_night import get_all_plan_files, get_plan_with_timeline
    except Exception as e:
        logger.debug(f"Could not import plan_my_night for {username}: {e}")
        return None

    plan_files = get_all_plan_files(user_id)
    if not plan_files:
        logger.debug(f"No plan files found for {username}")
        return None

    prefix = f'{user_id}_plan_'
    suffix = '.json'

    candidates = []
    for file_path in plan_files:
        fname = os.path.basename(file_path)
        if not (fname.startswith(prefix) and fname.endswith(suffix)):
            continue
        raw_tid = fname[len(prefix) : -len(suffix)]
        telescope_id = None if raw_tid == 'my_night' else raw_tid
        try:
            payload = get_plan_with_timeline(user_id, username, telescope_id=telescope_id)
            state = payload.get('state', 'none')
            if state == 'none':
                logger.debug(f"Plan (telescope={telescope_id}) for {username}: state=none, skipping")
                continue
            logger.debug(
                f"Plan (telescope={telescope_id}) for {username}: state={state}, "
                f"inside_night={payload.get('timeline', {}).get('is_inside_night')}"
            )
            candidates.append(payload)
        except Exception as e:
            logger.debug(f"Could not load plan (telescope={telescope_id}) for {username}: {e}")

    if not candidates:
        logger.debug(f"No active plan found for {username}")
        return None

    for p in candidates:
        if p.get('timeline', {}).get('is_inside_night'):
            return p
    for p in candidates:
        if p.get('state') == 'current':
            return p
    return candidates[0]


def _poll() -> None:
    """Single poll cycle: evaluate all triggers for all users."""
    global _any_active_night
    any_active = False

    try:
        from auth import user_manager

        # Load shared caches once per cycle
        aurora_data = _load_cache('aurora')
        sun_data = _load_cache('sun_report')
        iss_data = _load_cache('iss_passes')
        solar_data = _load_cache('solar_eclipse')
        lunar_data = _load_cache('lunar_eclipse')

        user_manager._reload_users_if_changed()
        logger.debug(f"Poll cycle: {len(user_manager.users)} user(s) loaded")
        for user in user_manager.users.values():
            notif_prefs = user.preferences.get('notifications', {})
            if not notif_prefs.get('enabled', True):
                logger.debug(f"Skipping {user.username}: notifications disabled")
                continue
            if not user.push_subscriptions:
                logger.debug(f"Skipping {user.username}: no push subscriptions")
                continue
            logger.debug(f"Evaluating {user.username}: {len(user.push_subscriptions)} subscription(s)")

            # Plan data is per-user - pick the most active plan across all
            # telescope-specific plan files (not just the default one).
            plan_payload = _pick_active_plan(user.user_id, user.username)

            # Fast-mode detection: active night OR night starting within 30 min
            if plan_payload and plan_payload.get('state') != 'none':
                timeline = plan_payload.get('timeline', {})
                plan = plan_payload.get('plan') or {}
                if timeline.get('is_inside_night'):
                    any_active = True
                else:
                    night_start_str = plan.get('night_start')
                    if night_start_str:
                        try:
                            from datetime import timezone

                            ns = datetime.fromisoformat(night_start_str)
                            if ns.tzinfo is None:
                                ns = ns.replace(tzinfo=timezone.utc)
                            secs_until = (ns - datetime.now(timezone.utc)).total_seconds()
                            if 0 < secs_until < 30 * 60:
                                any_active = True
                        except Exception:
                            pass

            _check_n7_aurora(user, aurora_data)
            _check_n1_plan_start(user, plan_payload)
            _check_n2_next_target(user, plan_payload)
            _check_n6_darkness(user, sun_data)
            _check_n3_iss(user, iss_data)
            _check_n4_n5_eclipse(user, solar_data, lunar_data)

    except Exception as e:
        logger.error(f"Push scheduler poll error: {e}")
    finally:
        _any_active_night = any_active


def _run() -> None:
    logger.info("Push notification scheduler started")
    while not _stop_event.is_set():
        _poll()
        delay = POLL_INTERVAL_FAST if _any_active_night else POLL_INTERVAL_SLOW
        _stop_event.wait(delay)
    logger.info("Push notification scheduler stopped")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _acquire_lock() -> bool:
    """Try to acquire the push_scheduler lock file (non-blocking).

    Returns True if this process now owns the scheduler lock.
    The lock is held by keeping the file open; the OS releases it when the
    process exits, allowing another worker to take over automatically.
    """
    global _lock_file
    from constants import DATA_DIR_CACHE

    lock_path = os.path.join(DATA_DIR_CACHE, 'push_scheduler.lock')
    try:
        _lock_file = open(lock_path, 'w')
        if sys.platform == 'win32':
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except (IOError, OSError):
        if _lock_file:
            _lock_file.close()
            _lock_file = None
        return False


def _release_lock() -> None:
    global _lock_file
    if not _lock_file:
        return
    try:
        if sys.platform == 'win32':
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
        _lock_file.close()
    except Exception as e:
        try:
            logger.error(f"Error releasing push scheduler lock: {e}")
        except (ValueError, OSError):
            pass  # Log stream already closed during process shutdown
    finally:
        _lock_file = None


def start() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    if not _acquire_lock():
        logger.debug("Push scheduler already running in another worker — skipping")
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_run, name='push-scheduler', daemon=True)
    _scheduler_thread.start()


def stop() -> None:
    _stop_event.set()
    _release_lock()
