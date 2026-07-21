"""
Server-side cache management with TTL-based expiration and config change detection.
All cache management is handled server-side only.

Multi-location model (v1.2)
---------------------------
Caches are split into two buckets:

- **Location-scoped** caches (moon/sun/eclipses/horizon/sidereal/planetary/
  phenomena/solar-system/aurora/ISS/CSS passes/seeing/weather/best-window):
  one slot per location preset, keyed by the preset's immutable ``id``.
  On-disk keys in ``astro_cache.json`` are ``"<name>:<location_id>"``.
  Access them via :func:`get_location_cache_entry`, :func:`load_location_cache`
  and :func:`update_location_cache` - never via module-level singletons.

- **Global** caches (spaceflight, IERS, version check, AllSky connector):
  the external data does not vary by observer location; they keep the legacy
  single-slot module-level shape and plain on-disk keys.

Editing one preset's coordinates invalidates only that preset's caches
(:func:`reset_caches_for_location`), not the whole install.
"""

import time
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from utils.constants import (
    WEATHER_CACHE_TTL,
    DATA_DIR_CACHE,
    CACHE_TTL_MOON_REPORT,
    CACHE_TTL_DARK_WINDOW,
    CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_SUN_REPORT,
    CACHE_TTL_BEST_WINDOW,
    CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_LUNAR_ECLIPSE,
    CACHE_TTL_HORIZON_GRAPH,
    CACHE_TTL_AURORA,
    CACHE_TTL_ISS_PASSES,
    CACHE_TTL_CSS_PASSES,
    CACHE_TTL_PLANETARY_EVENTS,
    CACHE_TTL_SPECIAL_PHENOMENA,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS,
    CACHE_TTL_SIDEREAL_TIME,
    CACHE_TTL_SEEING_FORECAST,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES,
    CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
    CACHE_TTL_SPACEFLIGHT_EVENTS,
    CACHE_TTL_IERS,
    CACHE_TTL_ALLSKY_SENSOR,
    CACHE_TTL_ALLSKY_HEALTH,
)

# Windows-compatible file locking
if sys.platform == "win32":
    import msvcrt

    def _msvcrt_lock(fileno):
        """Acquire a 1-byte msvcrt lock, retrying past the default ~10s deadlock timeout.

        msvcrt.locking(LK_LOCK) raises OSError after ~10 blocked seconds; under brief
        contention between gunicorn workers that is a false failure rather than a real
        deadlock, so we retry a few times before giving up.
        """
        attempts = 6
        for attempt in range(attempts):  # pragma: no branch - attempts is a fixed positive literal, always ≥1 iteration
            try:
                msvcrt.locking(fileno, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)

else:  # pragma: no cover
    import fcntl

# ---------------------------------------------------------------------------
# Location-scoped cache registry
# ---------------------------------------------------------------------------

# Single source of truth: every location-scoped cache name and its TTL.
LOCATION_SCOPED_CACHE_TTLS = {
    "moon_report": CACHE_TTL_MOON_REPORT,
    "dark_window": CACHE_TTL_DARK_WINDOW,
    "moon_planner": CACHE_TTL_MOON_PLANNER,
    "sun_report": CACHE_TTL_SUN_REPORT,
    "best_window_strict": CACHE_TTL_BEST_WINDOW,
    "best_window_practical": CACHE_TTL_BEST_WINDOW,
    "best_window_illumination": CACHE_TTL_BEST_WINDOW,
    "solar_eclipse": CACHE_TTL_SOLAR_ECLIPSE,
    "lunar_eclipse": CACHE_TTL_LUNAR_ECLIPSE,
    "horizon_graph": CACHE_TTL_HORIZON_GRAPH,
    "aurora": CACHE_TTL_AURORA,
    "iss_passes": CACHE_TTL_ISS_PASSES,
    "css_passes": CACHE_TTL_CSS_PASSES,
    "planetary_events": CACHE_TTL_PLANETARY_EVENTS,
    "special_phenomena": CACHE_TTL_SPECIAL_PHENOMENA,
    "solar_system_events": CACHE_TTL_SOLAR_SYSTEM_EVENTS,
    "sidereal_time": CACHE_TTL_SIDEREAL_TIME,
    "seeing_forecast": CACHE_TTL_SEEING_FORECAST,
    "weather_forecast": WEATHER_CACHE_TTL,
}

# Names checked by is_astronomical_cache_ready() - weather is intentionally
# excluded (it has a live-fetch fallback path and must not gate readiness).
_READINESS_LOCATION_CACHES = tuple(n for n in LOCATION_SCOPED_CACHE_TTLS if n != "weather_forecast")

# name -> {location_id -> {"timestamp": float, "data": Any}}
_location_caches = {name: {} for name in LOCATION_SCOPED_CACHE_TTLS}

# Global caches (external data does not vary by observer location)
_spaceflight_launches_cache = {"timestamp": 0, "data": None}
_spaceflight_astronauts_cache = {"timestamp": 0, "data": None}
_spaceflight_events_cache = {"timestamp": 0, "data": None}

# IERS-A Earth-orientation data cache (managed by scheduler, long TTL)
_iers_cache = {"timestamp": 0, "data": None}

# Version update check cache (separate TTL)
_version_update_cache = {"timestamp": 0, "data": None}

# Connector caches
_allsky_sensor_cache = {"timestamp": 0, "data": None}
_allsky_health_cache = {"timestamp": 0, "data": None}

_GLOBAL_SHARED_CACHES = {
    "spaceflight_launches": _spaceflight_launches_cache,
    "spaceflight_astronauts": _spaceflight_astronauts_cache,
    "spaceflight_events": _spaceflight_events_cache,
    "iers": _iers_cache,
}

# Track the last known location signatures to detect changes, keyed by
# location preset id (legacy single-location callers use the __legacy__ slot).
# Loaded from disk to survive restarts.
_LOCATION_CACHE_FILE = os.path.join(DATA_DIR_CACHE, 'location_cache.json')
_LEGACY_SIGNATURE_KEY = "__legacy__"
_last_known_location_signatures = {}

# Shared cache file (cross-worker)
# Note: _cache_initialization_in_progress is now stored in the shared cache file
# to ensure visibility across all gunicorn worker processes
_SHARED_CACHE_FILE = os.path.join(DATA_DIR_CACHE, "astro_cache.json")
_SHARED_CACHE_LOCK = os.path.join(DATA_DIR_CACHE, "astro_cache.lock")


def _ensure_data_dir():
    """Ensure DATA_DIR exists before file operations"""
    os.makedirs(DATA_DIR_CACHE, exist_ok=True)


@contextmanager
def _cache_file_read_lock():
    """Cross-platform SHARED lock - multiple concurrent readers allowed."""
    _ensure_data_dir()
    lock_file = open(_SHARED_CACHE_LOCK, "a+")
    try:
        if sys.platform == "win32":
            # msvcrt has no native shared lock; fall back to exclusive on Windows.
            _msvcrt_lock(lock_file.fileno())
        else:  # pragma: no cover
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        yield
    finally:
        try:
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


@contextmanager
def _cache_file_write_lock():
    """Cross-platform EXCLUSIVE lock - for writes only."""
    _ensure_data_dir()
    lock_file = open(_SHARED_CACHE_LOCK, "a+")
    try:
        if sys.platform == "win32":
            _msvcrt_lock(lock_file.fileno())
        else:  # pragma: no cover
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


# Keep the old name as an alias so any external callers are unaffected.
_cache_file_lock = _cache_file_write_lock


def _read_shared_cache():
    """Read shared cache file safely"""
    _ensure_data_dir()
    if not os.path.exists(_SHARED_CACHE_FILE):
        return {}
    try:
        with open(_SHARED_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        # If file is corrupted, ignore and treat as empty
        return {}


def _write_shared_cache(shared_cache):
    """Write the shared cache file atomically (temp file + os.replace).

    Writers hold the exclusive lock, but an unlocked reader (e.g. get_cache_metrics)
    must never observe a half-written file, so the finished file is swapped in
    atomically instead of being truncated and rewritten in place.
    """
    _ensure_data_dir()
    tmp_path = f"{_SHARED_CACHE_FILE}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(shared_cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, _SHARED_CACHE_FILE)


def update_shared_cache_entry(key, data, timestamp):
    """Update a single shared cache entry"""
    with _cache_file_lock():
        shared_cache = _read_shared_cache()
        shared_cache[key] = {"timestamp": timestamp, "data": data}
        _write_shared_cache(shared_cache)


def load_shared_cache_entry(key):
    """Load a single cache entry from shared cache"""
    with _cache_file_read_lock():
        shared_cache = _read_shared_cache()
        entry = shared_cache.get(key)
        if not isinstance(entry, dict):
            return None
        if "timestamp" not in entry or "data" not in entry:
            return None
        return entry


def sync_cache_from_shared(key, cache_entry):
    """Sync in-memory cache entry from shared cache file"""
    entry = load_shared_cache_entry(key)
    if not entry or entry.get("data") is None:
        return False
    cache_entry["data"] = entry.get("data")
    cache_entry["timestamp"] = entry.get("timestamp", 0)
    return True


def get_version_update_cache_entry():
    """Return the mutable cache entry used by version checker."""
    return _version_update_cache


# ---------------------------------------------------------------------------
# Location-scoped cache accessors
# ---------------------------------------------------------------------------


def location_cache_key(name, location_id):
    """On-disk shared-cache key for a (cache name, location preset id) pair."""
    return f"{name}:{location_id}"


def get_location_cache_entry(name, location_id):
    """Return the mutable in-memory entry for (name, location), creating it if needed."""
    if name not in _location_caches:
        raise KeyError(f"Unknown location-scoped cache: {name}")
    slots = _location_caches[name]
    if location_id not in slots:
        slots[location_id] = {"timestamp": 0, "data": None}
    return slots[location_id]


def load_location_cache(name, location_id):
    """Return the (name, location) entry, syncing from the shared file when the
    in-memory copy is empty or older than the persisted one."""
    entry = get_location_cache_entry(name, location_id)
    shared = load_shared_cache_entry(location_cache_key(name, location_id))
    if shared and shared.get("data") is not None and shared.get("timestamp", 0) >= entry["timestamp"]:
        entry["data"] = shared["data"]
        entry["timestamp"] = shared.get("timestamp", 0)
    return entry


def update_location_cache(name, location_id, data, timestamp=None):
    """Write a (name, location) cache entry to memory and to the shared file."""
    entry = get_location_cache_entry(name, location_id)
    entry["data"] = data
    entry["timestamp"] = timestamp if timestamp is not None else time.time()
    update_shared_cache_entry(location_cache_key(name, location_id), entry["data"], entry["timestamp"])
    return entry


def reset_caches_for_location(location_id):
    """Invalidate every location-scoped cache slot for one preset only.

    Called when a preset's coordinates/timezone change - other presets' caches
    are untouched (this replaces the pre-v1.2 wipe-everything behavior).
    """
    for name in _location_caches:
        _location_caches[name][location_id] = {"timestamp": 0, "data": None}
    with _cache_file_write_lock():
        shared = _read_shared_cache()
        removed = [key for key in shared if isinstance(key, str) and key.endswith(f":{location_id}")]
        for key in removed:
            del shared[key]
        _write_shared_cache(shared)


def drop_location_caches(location_id):
    """Remove all cache slots and the tracked signature for a deleted preset."""
    for name in _location_caches:
        _location_caches[name].pop(location_id, None)
    with _cache_file_write_lock():
        shared = _read_shared_cache()
        removed = [key for key in shared if isinstance(key, str) and key.endswith(f":{location_id}")]
        for key in removed:
            del shared[key]
        _write_shared_cache(shared)
    remove_location_signature(location_id)


def migrate_legacy_cache_keys(location_id):
    """One-time upgrade: move pre-v1.2 global cache keys onto a location id.

    Renames plain keys (e.g. ``"sun_report"``) to ``"sun_report:<id>"`` in the
    shared file so an upgraded install keeps its warm cache instead of
    triggering a full recompute/refetch storm on first boot.
    """
    migrated = 0
    with _cache_file_write_lock():
        shared = _read_shared_cache()
        for name in LOCATION_SCOPED_CACHE_TTLS:
            keyed = location_cache_key(name, location_id)
            if name in shared and keyed not in shared:
                shared[keyed] = shared.pop(name)
                migrated += 1
        if migrated:
            _write_shared_cache(shared)
    return migrated


# ---------------------------------------------------------------------------
# Location signature tracking (per-preset change detection)
# ---------------------------------------------------------------------------


def _load_location_signatures():
    """Load persisted location signatures from disk (migrating the legacy flat shape)."""
    global _last_known_location_signatures
    try:
        _ensure_data_dir()
        if os.path.exists(_LOCATION_CACHE_FILE):
            with open(_LOCATION_CACHE_FILE, 'r') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and "latitude" in loaded:
                # Pre-v1.2 flat single-location signature - keep it under the
                # legacy slot; check_and_handle_config_changes() transfers it
                # onto the migrated preset's id on the first scheduler cycle.
                _last_known_location_signatures = {_LEGACY_SIGNATURE_KEY: loaded}
            elif isinstance(loaded, dict):
                _last_known_location_signatures = loaded
    except Exception:
        # If loading fails, keep the default empty dict
        pass


def _save_location_signatures():
    """Persist location signatures to disk"""
    try:
        _ensure_data_dir()
        with open(_LOCATION_CACHE_FILE, 'w') as f:
            json.dump(_last_known_location_signatures, f, indent=2, ensure_ascii=False)
    except Exception:
        # Not critical if save fails, just means next restart might trigger false positive
        pass


# Load persisted signatures on module import
_load_location_signatures()


def get_current_location_signature(location_config):
    """Create a signature of location parameters for change detection"""
    if not location_config:
        return None
    return {
        "latitude": location_config.get("latitude"),
        "longitude": location_config.get("longitude"),
        "elevation": location_config.get("elevation"),
        "timezone": location_config.get("timezone"),
    }


def _signature_slot(location_config):
    """Signature dict key for a location payload: its preset id, or the legacy slot."""
    if isinstance(location_config, dict) and location_config.get("id"):
        return location_config["id"]
    return _LEGACY_SIGNATURE_KEY


def has_location_changed(new_location_config):
    """Check if location parameters have changed (per preset id).

    Accepts either a v1.2 preset dict (compared against its own id's stored
    signature) or a legacy flat location dict (compared against the legacy slot).
    """
    current_signature = get_current_location_signature(new_location_config)

    # If current signature is None (invalid config), consider it as changed
    if current_signature is None:
        return True

    stored = _last_known_location_signatures.get(_signature_slot(new_location_config))

    # If last config was not set, location has "changed" (first time)
    if not stored or stored.get("latitude") is None:
        return True

    return (
        stored.get("latitude") != current_signature["latitude"]
        or stored.get("longitude") != current_signature["longitude"]
        or stored.get("elevation") != current_signature["elevation"]
        or stored.get("timezone") != current_signature["timezone"]
    )


def is_location_tracked(location_config):
    """Return True when a signature is already stored for this location."""
    stored = _last_known_location_signatures.get(_signature_slot(location_config))
    return bool(stored) and stored.get("latitude") is not None


def update_location_config(new_location_config):
    """Update the tracked signature for this location and persist to disk"""
    signature = get_current_location_signature(new_location_config)
    if signature:
        _last_known_location_signatures[_signature_slot(new_location_config)] = signature.copy()
        _save_location_signatures()


def remove_location_signature(location_id):
    """Forget the tracked signature of a deleted preset."""
    if _last_known_location_signatures.pop(location_id, None) is not None:
        _save_location_signatures()


def pop_legacy_location_signature():
    """Return and clear the pre-v1.2 flat signature (upgrade path helper)."""
    legacy = _last_known_location_signatures.pop(_LEGACY_SIGNATURE_KEY, None)
    if legacy is not None:
        _save_location_signatures()
    return legacy


def reset_all_caches():
    """Reset all astronomical caches (every location slot + refreshable globals).

    Global cache entries are mutated IN PLACE (never rebound): other modules
    and _GLOBAL_SHARED_CACHES hold references to these dicts, and rebinding
    would silently detach them from all future syncs/reads.
    """
    for name in _location_caches:
        for location_id in list(_location_caches[name]):
            _location_caches[name][location_id] = {"timestamp": 0, "data": None}

    for entry in (
        _spaceflight_launches_cache,
        _spaceflight_astronauts_cache,
        _spaceflight_events_cache,
        _allsky_sensor_cache,
        _allsky_health_cache,
    ):
        entry["timestamp"] = 0
        entry["data"] = None

    with _cache_file_write_lock():
        shared = _read_shared_cache()
        for key in list(shared):
            if not isinstance(key, str) or key.startswith("_"):
                continue
            base_name = key.split(":", 1)[0]
            if base_name in LOCATION_SCOPED_CACHE_TTLS or base_name in (
                "spaceflight_launches",
                "spaceflight_astronauts",
                "spaceflight_events",
            ):
                shared[key] = {"timestamp": 0, "data": None}
        _write_shared_cache(shared)


def is_cache_valid(cache_entry, ttl_seconds):
    """Check if a cache entry is still valid based on TTL"""
    if not cache_entry or cache_entry["data"] is None:
        return False

    current_time = time.time()
    elapsed = current_time - cache_entry["timestamp"]

    return elapsed < ttl_seconds


def is_cache_valid_for_today(cache_entry, ttl_seconds, tz_name=None):
    """Like is_cache_valid, but also invalidates when the calendar day has changed.

    Use this for caches that are computed for 'today' (sun report, horizon graph,
    moon report, etc.) - a 6h TTL would otherwise serve stale day-N data well into
    day N+1 if the cache was last populated late in the evening.

    ``tz_name`` selects the calendar the day boundary is evaluated in. Pass the
    observer location's IANA timezone so the boundary matches the day the data was
    actually computed for; when omitted it falls back to the server's local time
    (legacy behaviour), which can flip a day early/late for far-away observers.
    """
    if not is_cache_valid(cache_entry, ttl_seconds):
        return False
    tz = None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None  # unknown timezone — fall back to server-local day boundary
    cache_date = datetime.fromtimestamp(cache_entry["timestamp"], tz).date()
    return cache_date == datetime.now(tz).date()


def _default_status_location_ids():
    """Location ids the readiness/status checks should cover (lazy config read)."""
    try:
        from utils.repo_config import load_config, get_scheduler_locations

        config = load_config()
        ids = [loc["id"] for loc in get_scheduler_locations(config) if loc.get("id")]
        if ids:
            return ids
    except Exception:
        # Status checks must degrade gracefully when config can't be loaded.
        return []
    return []


def _allsky_job_availability():
    """Whether each AllSky job can ever actually run (lazy config read).

    Mirrors the exact scheduling gate in cache_updater.fully_initialize_caches:
    allsky_health only needs the connector enabled+url, allsky_sensor also
    needs its own module toggle. A job that can never run must not appear in
    the metrics table - it would just sit "stale" forever with no explanation.
    Returns (sensor_available, health_available).
    """
    try:
        from utils.repo_config import load_config

        allsky_cfg = load_config().get("connectors", {}).get("allsky", {})
    except Exception:
        return False, False
    connector_ready = bool(allsky_cfg.get("enabled") and allsky_cfg.get("url"))
    sensor_ready = connector_ready and bool(allsky_cfg.get("modules", {}).get("sensor_data", {}).get("enabled"))
    return sensor_ready, connector_ready


def _sync_all_from_shared():
    """Read astro_cache.json ONCE and sync all in-memory caches in a single pass."""
    with _cache_file_read_lock():
        shared = _read_shared_cache()

    for key, cache_entry in _GLOBAL_SHARED_CACHES.items():
        entry = shared.get(key)
        if isinstance(entry, dict) and entry.get("data") is not None:
            cache_entry["data"] = entry["data"]
            cache_entry["timestamp"] = entry.get("timestamp", 0)

    for key, entry in shared.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(entry, dict):
            continue
        name, location_id = key.split(":", 1)
        if name in _location_caches and entry.get("data") is not None:
            slot = get_location_cache_entry(name, location_id)
            if entry.get("timestamp", 0) >= slot["timestamp"]:
                slot["data"] = entry["data"]
                slot["timestamp"] = entry.get("timestamp", 0)
    return shared


def is_astronomical_cache_ready(location_ids=None):
    """Check if all astronomical caches are valid and ready.

    Covers every location the scheduler keeps warm (or the explicit
    *location_ids*) plus the global spaceflight caches.
    """
    _sync_all_from_shared()
    if location_ids is None:
        location_ids = _default_status_location_ids()
    if not location_ids:
        return False

    for location_id in location_ids:
        for name in _READINESS_LOCATION_CACHES:
            entry = get_location_cache_entry(name, location_id)
            if not is_cache_valid(entry, LOCATION_SCOPED_CACHE_TTLS[name]):
                return False

    return (
        is_cache_valid(_spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES)
        and is_cache_valid(_spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS)
        and is_cache_valid(_spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS)
    )


def _is_execution_metrics_valid(job_name, ttl):
    """Check cache validity from persisted execution metrics.

    Allsky caches are in-memory only (no shared-file sync), so in multi-worker
    setups the web worker's in-memory timestamp stays at 0 even after the
    scheduler runs.  The execution_metrics written by record_cache_execution()
    are stored in the shared JSON file and are visible to all workers, making
    this the correct source for cross-process validity checks.
    """
    entry = get_cache_metrics().get(job_name, {})
    if not entry.get("last_success"):
        return False
    last_run_str = entry.get("last_run_at")
    if not last_run_str:
        return False
    try:
        dt = datetime.fromisoformat(last_run_str)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age < ttl
    except Exception:
        return False


def get_cache_init_status(location_ids=None):
    """Get detailed cache initialization status.

    Top-level per-cache booleans reflect the install default location (first id
    of the scheduler set) so the existing Metrics UI keeps its layout; the
    ``locations`` block details every scheduler location.
    """
    shared_cache = _sync_all_from_shared()
    if location_ids is None:
        location_ids = _default_status_location_ids()
    primary_id = location_ids[0] if location_ids else None

    # Read in_progress status from shared cache for cross-worker visibility
    in_progress = False
    current_step = 0
    total_steps = 0
    step_name = ""
    progress_percent = 0

    if "_cache_in_progress" in shared_cache:
        progress_info = shared_cache["_cache_in_progress"]
        in_progress = progress_info.get("status", False)
        current_step = progress_info.get("current_step", 0)
        total_steps = progress_info.get("total_steps", 0)
        step_name = progress_info.get("step_name", "")
        if total_steps > 0:
            progress_percent = int((current_step / total_steps) * 100)

    def _loc_valid(name, location_id):
        if location_id is None:
            return False
        return is_cache_valid(get_location_cache_entry(name, location_id), LOCATION_SCOPED_CACHE_TTLS[name])

    allsky_sensor_available, allsky_health_available = _allsky_job_availability()

    status = {name: _loc_valid(name, primary_id) for name in LOCATION_SCOPED_CACHE_TTLS}
    status.update(
        {
            "spaceflight_launches": is_cache_valid(_spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES),
            "spaceflight_astronauts": is_cache_valid(_spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS),
            "spaceflight_events": is_cache_valid(_spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS),
            "iers": is_cache_valid(_iers_cache, CACHE_TTL_IERS),
        }
    )
    if allsky_sensor_available:
        status["allsky_sensor"] = _is_execution_metrics_valid("allsky_sensor", CACHE_TTL_ALLSKY_SENSOR)
    if allsky_health_available:
        status["allsky_health"] = _is_execution_metrics_valid("allsky_health", CACHE_TTL_ALLSKY_HEALTH)

    per_location = {
        location_id: {name: _loc_valid(name, location_id) for name in LOCATION_SCOPED_CACHE_TTLS}
        for location_id in location_ids
    }

    status.update(
        {
            "all_ready": is_astronomical_cache_ready(location_ids) if location_ids else False,
            "locations": per_location,
            "in_progress": in_progress,
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "progress_percent": progress_percent,
            "ttls": {
                # best_window has no entry of its own: LOCATION_SCOPED_CACHE_TTLS
                # already covers it as 3 separate rows (strict/practical/
                # illumination) - one Astropy night-scan computes all three, but
                # each has its own cache slot and its own staleness.
                **{name: ttl for name, ttl in LOCATION_SCOPED_CACHE_TTLS.items()},
                "dark_window": CACHE_TTL_DARK_WINDOW,
                "spaceflight_launches": CACHE_TTL_SPACEFLIGHT_LAUNCHES,
                "spaceflight_astronauts": CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
                "spaceflight_events": CACHE_TTL_SPACEFLIGHT_EVENTS,
                "iers": CACHE_TTL_IERS,
                # Jobs that can never run (connector/module not configured)
                # must not appear in the metrics table as permanently "stale".
                **({"allsky_sensor": CACHE_TTL_ALLSKY_SENSOR} if allsky_sensor_available else {}),
                **({"allsky_health": CACHE_TTL_ALLSKY_HEALTH} if allsky_health_available else {}),
            },
            "execution_metrics": get_cache_metrics(),
        }
    )
    return status


def set_cache_initialization_in_progress(value, current_step=0, total_steps=0, step_name=""):
    """Set the cache initialization progress flag in shared cache for cross-worker visibility"""
    with _cache_file_write_lock():
        shared_cache = _read_shared_cache()
        shared_cache["_cache_in_progress"] = {
            "status": value,
            "timestamp": time.time(),
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
        }
        _write_shared_cache(shared_cache)


def record_cache_execution(job_name, duration_seconds, success, location_id=None):
    """Persist per-job execution timing and result to shared cache for metrics reporting.

    ``job_name`` is the (possibly location-suffixed) job label used across the
    scheduler and metrics UI. ``location_id`` is recorded alongside it so
    consumers can group per-location executions back under their base job
    without having to reverse-engineer the label's slug.
    """
    with _cache_file_write_lock():
        shared = _read_shared_cache()
        if "_cache_metrics" not in shared:
            shared["_cache_metrics"] = {}
        shared["_cache_metrics"][job_name] = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_duration_s": round(duration_seconds, 3),
            "last_success": success,
            "location_id": location_id,
        }
        _write_shared_cache(shared)


def get_cache_metrics():
    """Return per-job execution metrics from shared cache."""
    with _cache_file_read_lock():
        shared = _read_shared_cache()
    return shared.get("_cache_metrics", {})
