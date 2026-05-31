"""
Server-side push notification scheduler.

Runs every POLL_INTERVAL_SECONDS in a background thread.
Evaluates N1-N7 trigger conditions using cached data, then sends Web Push
to subscribed users whose notifications are enabled and cooldown has elapsed.

Cooldown is tracked in-memory (resets on server restart, acceptable for a
5-minute scheduler - the worst case is one duplicate notification per restart).
"""

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from logging_config import get_logger

logger = get_logger(__name__)

POLL_INTERVAL_SLOW = 5 * 60  # 5 min - default
POLL_INTERVAL_FAST = 60      # 1 min - during/near active observation sessions

# {user_id: {trigger_id: last_sent_epoch_seconds}}
_last_sent: Dict[str, Dict[str, float]] = {}
_lock = threading.Lock()

# {user_id: set_of_entry_ids} - prevents re-sending N2 for the same plan entry
_n2_notified: Dict[str, set] = {}

# True when any user has an active or near (≤30 min) observation session
_any_active_night: bool = False

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


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

def _send(user: Any, trigger_id: str, title: str, body: str, url: str) -> None:
    """Send push to all subscriptions of a user and mark as notified."""
    if not user.push_subscriptions:
        return

    from push_manager import send_push

    icon  = '/static/ico/android/launchericon-192x192.png'
    badge = '/static/ico/android/launchericon-72x72.png'
    payload = {
        'title': title,
        'body':  body,
        'icon':  icon,
        'badge': badge,
        'tag':   f'{trigger_id}-{datetime.now(timezone.utc).strftime("%Y%m%d")}',
        'data':  {'url': url},
    }

    dead_endpoints = []
    for sub in user.push_subscriptions:
        endpoint = sub.get('endpoint', '')
        subscription_info = {'endpoint': endpoint, 'keys': sub.get('keys', {})}
        ok = send_push(subscription_info, payload)
        if not ok:
            dead_endpoints.append(endpoint)

    if dead_endpoints:
        _cleanup_dead_subscriptions(user, dead_endpoints)

    _mark_notified(user.user_id, trigger_id)


def _cleanup_dead_subscriptions(user: Any, endpoints: list) -> None:
    """Remove expired/invalid push subscriptions from the user."""
    try:
        from auth import user_manager
        user.push_subscriptions = [
            s for s in user.push_subscriptions
            if s.get('endpoint') not in endpoints
        ]
        user_manager.save_users()
    except Exception as e:
        logger.warning(f"Failed to clean dead subscriptions for {user.username}: {e}")


# ---------------------------------------------------------------------------
# Trigger evaluation (per-user)
# ---------------------------------------------------------------------------

def _get_notif_prefs(user: Any) -> dict:
    """Extract notification trigger config from user preferences."""
    return user.preferences.get('notifications', {}).get('triggers', {})


def _check_n7_aurora(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N7', {})
    if not t.get('enabled', True):
        return

    kp = cache_data.get('current', {}).get('kp_index')
    if not isinstance(kp, (int, float)):
        return
    if kp < t.get('kp_threshold', 5):
        return
    if _was_recently_notified(user.user_id, 'N7', 60 * 60):
        return

    visibility = cache_data.get('current', {}).get('visibility_level', '')
    _send(user, 'N7',
          'Aurora Alert',
          f'Kp {kp:.1f} detected - {visibility}',
          '/#forecast-astro/aurora')


def _check_n1_plan_start(user: Any, plan_payload: Optional[dict]) -> None:
    if not plan_payload or plan_payload.get('state') == 'none':
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N1', {})
    if not t.get('enabled', True):
        return
    if plan_payload.get('timeline', {}).get('is_inside_night'):
        return  # already started

    plan = plan_payload.get('plan') or {}
    night_start_str = plan.get('night_start')
    if not night_start_str:
        return

    try:
        night_start = datetime.fromisoformat(night_start_str)
        if night_start.tzinfo is None:
            night_start = night_start.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        ms_until = (night_start - now).total_seconds()
        lead_s = t.get('lead_minutes', 15) * 60
        if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, 'N1', 2 * 60 * 60):
            minutes = round(ms_until / 60)
            _send(user, 'N1',
                  'Plan My Night',
                  f'Your session starts in {minutes} min',
                  '/#astrodex/plan-my-night')
    except Exception as e:
        logger.debug(f"N1 check error for {user.username}: {e}")


def _check_n2_next_target(user: Any, plan_payload: Optional[dict]) -> None:
    if not plan_payload or plan_payload.get('state') == 'none':
        return
    if not plan_payload.get('timeline', {}).get('is_inside_night'):
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N2', {})
    if not t.get('enabled', True):
        return

    entries = (plan_payload.get('plan') or {}).get('entries', [])
    lead_s  = t.get('lead_minutes', 5) * 60
    now     = datetime.now(timezone.utc)

    notified_set = _n2_notified.setdefault(user.user_id, set())

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
                break  # entries are chronological

            entry_id = entry.get('id') or entry.get('target_name') or entry.get('name', '?')
            if entry_id in notified_set:
                break
            notified_set.add(entry_id)
            minutes = round(ms_until / 60)
            name    = entry.get('name') or entry.get('target_name', '?')
            _send(user, 'N2',
                  'Next target',
                  f'{name} starts in {minutes} min',
                  '/#astrodex/plan-my-night')
            break
        except Exception as e:
            logger.debug(f"N2 entry check error for {user.username}: {e}")


def _check_n6_darkness(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N6', {})
    if not t.get('enabled', True):
        return

    dusk_str = cache_data.get('sun', {}).get('astronomical_dusk')
    if not dusk_str:
        return
    try:
        dusk = datetime.fromisoformat(dusk_str)
        if dusk.tzinfo is None:
            dusk = dusk.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        ms_until = (dusk - now).total_seconds()
        lead_s = t.get('lead_minutes', 20) * 60
        if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, 'N6', 8 * 60 * 60):
            minutes = round(ms_until / 60)
            _send(user, 'N6',
                  'Astronomical darkness',
                  f'Night begins in {minutes} min - time to get ready',
                  '/#forecast-astro/astro-weather')
    except Exception as e:
        logger.debug(f"N6 check error for {user.username}: {e}")


def _check_n3_iss(user: Any, cache_data: Optional[dict]) -> None:
    if not cache_data:
        return
    triggers = _get_notif_prefs(user)
    t = triggers.get('N3', {})
    if not t.get('enabled', True):
        return

    lead_s = t.get('lead_minutes', 10) * 60
    now    = datetime.now(timezone.utc)

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
            except Exception:
                pass
    for transit in cache_data.get('lunar_transits', []):
        start_str = transit.get('start_time')
        if start_str:
            try:
                dt = datetime.fromisoformat(start_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now:
                    candidates.append((dt, 'lunar'))
            except Exception:
                pass

    if not candidates:
        return
    candidates.sort(key=lambda x: x[0])
    next_dt, transit_type = candidates[0]
    ms_until = (next_dt - now).total_seconds()
    if ms_until > lead_s:
        return
    if _was_recently_notified(user.user_id, 'N3', 60 * 60):
        return

    minutes = round(ms_until / 60)
    body = (f'ISS solar transit in {minutes} min' if transit_type == 'solar'
            else f'ISS lunar transit in {minutes} min')
    _send(user, 'N3', 'ISS Transit', body, '/#spaceflight/iss')


def _check_n4_n5_eclipse(user: Any, solar_data: Optional[dict], lunar_data: Optional[dict]) -> None:
    triggers = _get_notif_prefs(user)
    now = datetime.now(timezone.utc)

    for trigger_id, cache_data, title in (
        ('N4', lunar_data, 'Lunar Eclipse'),
        ('N5', solar_data, 'Solar Eclipse'),
    ):
        t = triggers.get(trigger_id, {})
        if not t.get('enabled', True) or not cache_data:
            continue

        peak_str = (cache_data.get('eclipse') or {}).get('peak_time')
        if not peak_str:
            continue
        try:
            peak = datetime.fromisoformat(peak_str)
            if peak.tzinfo is None:
                peak = peak.replace(tzinfo=timezone.utc)
            ms_until = (peak - now).total_seconds()
            lead_s = t.get('lead_minutes', 30) * 60
            if 0 < ms_until <= lead_s and not _was_recently_notified(user.user_id, trigger_id, 4 * 60 * 60):
                minutes = round(ms_until / 60)
                body = (f'Totality begins in {minutes} min' if trigger_id == 'N4'
                        else f'Maximum in {minutes} min')
                _send(user, trigger_id, title, body, '/#forecast-astro/moon')
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


def _poll() -> None:
    """Single poll cycle: evaluate all triggers for all users."""
    global _any_active_night
    any_active = False

    try:
        from auth import user_manager

        # Load shared caches once per cycle
        aurora_data  = _load_cache('aurora')
        sun_data     = _load_cache('sun_report')
        iss_data     = _load_cache('iss_passes')
        solar_data   = _load_cache('solar_eclipse')
        lunar_data   = _load_cache('lunar_eclipse')

        user_manager._reload_users_if_changed()
        for user in user_manager.users.values():
            notif_prefs = user.preferences.get('notifications', {})
            if not notif_prefs.get('enabled', True):
                continue
            if not user.push_subscriptions:
                continue

            # Plan data is per-user - load individually
            plan_payload = None
            try:
                from plan_my_night import get_plan_with_timeline
                plan_payload = get_plan_with_timeline(user.user_id, user.username)
            except Exception as e:
                logger.debug(f"Could not load plan for {user.username}: {e}")

            # Fast-mode detection: active night OR night starting within 30 min
            if plan_payload and plan_payload.get('state') != 'none':
                timeline = plan_payload.get('timeline', {})
                plan     = plan_payload.get('plan') or {}
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

def start() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_run, name='push-scheduler', daemon=True)
    _scheduler_thread.start()


def stop() -> None:
    _stop_event.set()
