"""
Manage configuration loading and saving, plus the multi-location preset model (v1.2).

Location presets are stored as an admin-managed ``locations`` list inside
``data/config.json``. Per-user selection (attribution, default, active, order)
lives in ``users.json`` under ``preferences.location`` (see auth.py).
This module owns:

- the one-time migration of the legacy singular ``location`` key,
- ``get_active_location()`` - the single resolver every backend consumer uses
  instead of raw ``config["location"]`` reads,
- helpers to look up / list presets for a given user or for the cache scheduler.
"""

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from constants import CONFIG_FILE, MAX_LOCATIONS  # noqa: F401  (MAX_LOCATIONS re-exported for API/UI use)
from config_defaults import DEFAULT_CONFIG, DEFAULT_LOCATION, LOCATION_PRESET_EXTRA_FIELDS
from utils import load_json_file, save_json_file, safe_file_exists


def _merge_defaults(config, defaults):
    """Recursively merge missing default keys into a config payload."""
    if not isinstance(defaults, dict):
        return deepcopy(defaults)

    merged = deepcopy(defaults)
    if not isinstance(config, dict):
        return merged

    for key, value in config.items():
        default_value = merged.get(key)
        if isinstance(value, dict) and isinstance(default_value, dict):
            merged[key] = _merge_defaults(value, default_value)
        else:
            merged[key] = value

    return merged


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def new_location_preset(base=None, is_install_default=False):
    """Build a full location preset dict from a base location payload.

    ``id`` is server-generated (uuid4), never client-supplied, and immutable
    for the life of the preset - it is the foreign key used by user
    preferences, Astrodex items and Plan My Night entries.
    """
    preset = deepcopy(DEFAULT_LOCATION)
    preset.update(deepcopy(LOCATION_PRESET_EXTRA_FIELDS))
    if isinstance(base, dict):
        for key in ("name", "latitude", "longitude", "elevation", "timezone", "bortle", "sqm", "horizon_profile"):
            if key in base and base[key] is not None:
                preset[key] = deepcopy(base[key])
        # bortle/sqm may legitimately be null - carry explicit nulls through
        for key in ("bortle", "sqm"):
            if key in base:
                preset[key] = base[key]
    preset["id"] = str(uuid.uuid4())
    preset["is_install_default"] = bool(is_install_default)
    preset["created_at"] = _utcnow_iso()
    preset["updated_at"] = preset["created_at"]
    return preset


def _ensure_locations(config):
    """Guarantee the ``locations`` list invariants; migrate legacy shape in place.

    Returns True when the config dict was modified (caller should persist).

    Invariants enforced:
    - ``locations`` is a non-empty list (seeded from the legacy singular
      ``location`` dict, or from DEFAULT_LOCATION on brand-new installs),
    - every preset has an ``id`` and the preset extra fields,
    - exactly one preset carries ``is_install_default: True``,
    - the legacy ``location`` key and legacy global
      ``skytonight.constraints.horizon_profile`` are migrated then removed.
    """
    changed = False

    locations = config.get("locations")
    if not isinstance(locations, list):
        locations = []
        changed = True
    else:
        # Sanitize hand-edited configs up front: non-dict entries are dropped
        # so every downstream step can rely on a list of preset dicts.
        cleaned = [preset for preset in locations if isinstance(preset, dict)]
        if len(cleaned) != len(locations):
            locations = cleaned
            changed = True

    legacy_location = config.pop("location", None)
    if legacy_location is not None:
        changed = True

    # Legacy global horizon profile moves onto the migrated preset
    legacy_horizon = None
    skytonight_cfg = config.get("skytonight")
    if isinstance(skytonight_cfg, dict):
        constraints = skytonight_cfg.get("constraints")
        if isinstance(constraints, dict) and "horizon_profile" in constraints:
            legacy_horizon = constraints.pop("horizon_profile", None)
            changed = True

    if not locations:
        base = legacy_location if isinstance(legacy_location, dict) else DEFAULT_LOCATION
        first = new_location_preset(base=base, is_install_default=True)
        if legacy_horizon:
            first["horizon_profile"] = legacy_horizon
        locations = [first]
        changed = True
        # Attribute explicitly to whoever already exists (a real migration's
        # prior users, or just the bootstrap admin on a brand new install) -
        # don't rely on admin bypass alone. Bypass covers *reads* (which
        # locations a user can pick), but scheduling/warm-cache logic and any
        # future consumer must each remember to check is_admin() too; a
        # location with no explicit attribution record only works by
        # accident if every one of them does.
        _attribute_new_location_to_all_users(first["id"])
    else:
        # Backfill preset fields on existing entries (defensive - e.g. hand-edited config)
        for preset in locations:
            if not preset.get("id"):
                preset["id"] = str(uuid.uuid4())
                changed = True
            for key, default_value in LOCATION_PRESET_EXTRA_FIELDS.items():
                if key not in preset:
                    preset[key] = deepcopy(default_value)
                    changed = True
        if legacy_horizon and not any(p.get("horizon_profile") for p in locations):
            # Attach the orphaned global horizon to the install default (or first) preset
            target = next((p for p in locations if p.get("is_install_default")), locations[0])
            target["horizon_profile"] = legacy_horizon
            changed = True

    # Exactly one install default
    defaults = [p for p in locations if p.get("is_install_default")]
    if len(defaults) == 0:
        locations[0]["is_install_default"] = True
        changed = True
    elif len(defaults) > 1:
        for extra in defaults[1:]:
            extra["is_install_default"] = False
        changed = True

    config["locations"] = locations
    return changed


def _attribute_new_location_to_all_users(location_id):
    """Attach *location_id* to every existing user's attribution list.

    Lazy import to avoid a module-load-time cycle with auth.py (which itself
    lazily imports repo_config in get_scheduler_locations et al). Best-effort:
    if user storage isn't available yet (e.g. import order during startup, or
    a unit test with no auth module loaded), the migration itself must still
    succeed - a location that ends up unattributed can always be fixed by an
    admin afterward.
    """
    try:
        from auth import user_manager

        user_manager.set_location_attribution(location_id, list(user_manager.users.keys()))
    except Exception:
        pass


def load_config():
    """Load configuration from file (migrating the legacy location shape once)."""
    if not safe_file_exists(CONFIG_FILE):
        # No config file yet — brand-new install, keep location_configured=False.
        # Persist immediately so the seeded preset's uuid stays stable across
        # loads/workers (cache slots and user prefs are keyed by that id).
        config = deepcopy(DEFAULT_CONFIG)
        _ensure_locations(config)
        save_config(config)
        return config
    raw = load_json_file(CONFIG_FILE, {})
    merged = _merge_defaults(raw, DEFAULT_CONFIG)
    # Strip legacy top-level 'constraints' key - constraints live exclusively
    # under skytonight.constraints from now on.
    merged.pop('constraints', None)
    # Existing installs pre-date the location_configured flag; treat them as configured
    if 'location_configured' not in raw:
        merged['location_configured'] = True

    if _ensure_locations(merged):
        # One-time legacy migration (or invariant repair) - persist immediately so
        # preset ids are stable across workers/restarts.
        save_config(merged)
    return merged


def save_config(config):
    """Save configuration to file"""
    return save_json_file(CONFIG_FILE, config)


# ---------------------------------------------------------------------------
# Location preset helpers (v1.2 multi-location profiles)
# ---------------------------------------------------------------------------


def get_all_locations(config):
    """Return the full preset list (admin view)."""
    locations = config.get("locations", [])
    return [loc for loc in locations if isinstance(loc, dict) and loc.get("id")]


def get_location_by_id(config, location_id):
    """Return the preset with the given id, or None."""
    if not location_id:
        return None
    for loc in get_all_locations(config):
        if loc.get("id") == location_id:
            return loc
    return None


def get_install_default_location(config):
    """Return the preset flagged is_install_default (always exists post-migration)."""
    locations = get_all_locations(config)
    if not locations:
        return deepcopy(DEFAULT_LOCATION)  # defensive - should not happen post-migration
    for loc in locations:
        if loc.get("is_install_default"):
            return loc
    return locations[0]


def get_user_location_prefs(user):
    """Return the (possibly missing) per-user location preference block, normalized."""
    prefs = {}
    if user is not None and isinstance(getattr(user, "preferences", None), dict):
        prefs = user.preferences.get("location") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    return {
        "attributed_location_ids": [lid for lid in prefs.get("attributed_location_ids", []) if isinstance(lid, str)],
        "default_location_id": prefs.get("default_location_id"),
        "active_location_id": prefs.get("active_location_id"),
        "order": [lid for lid in prefs.get("order", []) if isinstance(lid, str)],
    }


def get_locations_for_user(config, user):
    """Return the presets accessible to *user*, in the user's preferred order.

    Admins bypass attribution entirely - every preset is implicitly theirs.
    A user with no attributed presets falls back to the install default only.
    """
    locations = get_all_locations(config)
    if not locations:
        return []

    prefs = get_user_location_prefs(user)
    if user is not None and hasattr(user, "is_admin") and user.is_admin():
        accessible = list(locations)
    else:
        attributed = set(prefs["attributed_location_ids"])
        accessible = [loc for loc in locations if loc["id"] in attributed]
        if not accessible:
            accessible = [get_install_default_location(config)]

    order = prefs["order"]
    if order:
        rank = {lid: idx for idx, lid in enumerate(order)}
        accessible.sort(key=lambda loc: rank.get(loc["id"], len(rank)))
    return accessible


def get_active_location(config, user=None):
    """Resolve the location dict that should drive calculations for this request.

    Fallback chain: user's active -> user's default -> install default ->
    first accessible. Only ids that still exist in config["locations"] are
    trusted (deleted presets are cleaned up eagerly, but this stays defensive).
    """
    locations = {loc["id"]: loc for loc in get_all_locations(config)}
    if not locations:
        return deepcopy(DEFAULT_LOCATION)  # should not happen post-migration, defensive fallback

    install_default = get_install_default_location(config)
    prefs = get_user_location_prefs(user)

    # Admins bypass attribution entirely - every preset is implicitly "theirs".
    if user is not None and hasattr(user, "is_admin") and user.is_admin():
        accessible = dict(locations)
    else:
        accessible = {lid: loc for lid, loc in locations.items() if lid in set(prefs["attributed_location_ids"])}
    if not accessible:
        return install_default

    active_id = prefs["active_location_id"]
    if active_id in accessible:
        return accessible[active_id]

    # fall back chain: user's default -> install default -> first attributed
    default_id = prefs["default_location_id"]
    if default_id in accessible:
        return accessible[default_id]
    if install_default and install_default.get("id") in accessible:
        return install_default
    return next(iter(accessible.values()))


def get_scheduler_locations(config):
    """Return the presets the cache scheduler must keep warm.

    The install default + every preset attributed to at least one user +
    every preset that is currently some user's active/default location +
    every preset at all, if any admin exists (admins bypass attribution
    everywhere else - see get_active_location). In practice this means every
    admin-created preset stays warm: an admin can always see any preset they
    made, so its metrics shouldn't go stale just because nobody happens to
    have it selected as active right now.
    """
    locations = get_all_locations(config)
    if not locations:
        return []
    by_id = {loc["id"]: loc for loc in locations}

    wanted = {get_install_default_location(config).get("id")}
    try:
        from auth import user_manager  # lazy - avoid import cycle at module load

        for user in user_manager.users.values():
            if hasattr(user, "is_admin") and user.is_admin():
                wanted.update(by_id.keys())
                continue
            prefs = get_user_location_prefs(user)
            wanted.update(prefs["attributed_location_ids"])
            if prefs["active_location_id"]:
                wanted.add(prefs["active_location_id"])
            if prefs["default_location_id"]:
                wanted.add(prefs["default_location_id"])
    except Exception:
        # If user storage is unavailable (e.g. unit tests), fall back to install default only
        pass

    return [by_id[lid] for lid in by_id if lid in wanted]
