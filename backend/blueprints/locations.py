"""Config + multi-location profiles Blueprint. Routes: /api/config, /api/locations/*"""

from datetime import datetime, timezone
from zoneinfo import available_timezones

from flask import Blueprint, request, jsonify

from observation import astrodex
from cache import cache_store
from observation import plan_my_night
from utils.auth import user_manager, login_required, admin_required, get_current_user
from utils.constants import MAX_LOCATIONS
from utils.logging_config import get_logger
from utils.repo_config import (
    load_config,
    save_config,
    get_all_locations,
    get_location_by_id,
    get_install_default_location,
    get_locations_for_user,
    get_active_location,
    get_user_location_prefs,
    new_location_preset,
)
from skytonight.skytonight_storage import drop_location_results as drop_skytonight_location_results

logger = get_logger(__name__)

locations_bp = Blueprint('locations', __name__)


@locations_bp.route('/api/config', methods=['GET'])
@login_required
def get_config_api():
    """Get current configuration.

    Compatibility shim (v1.2): the response still exposes the caller's
    *active* location under the legacy ``location`` key so unmigrated frontend
    code keeps working; the authoritative store is the ``locations`` list.
    """
    config = load_config()
    response = dict(config)
    response['location'] = get_active_location(config, get_current_user())
    return jsonify(response)


def _validate_location_payload(payload, partial=False):
    """Validate an incoming location preset payload. Returns (cleaned, error)."""
    if not isinstance(payload, dict):
        return None, "Invalid payload"
    cleaned = {}

    if not partial or 'name' in payload:
        name = str(payload.get('name') or '').strip()
        if not name:
            return None, "location name is required"
        cleaned['name'] = name

    for key in ('latitude', 'longitude'):
        if not partial or key in payload:
            try:
                raw_value = payload.get(key)
                if raw_value is None:
                    raise TypeError()
                value = float(raw_value)
            except (TypeError, ValueError):
                return None, f"location.{key} must be a number"
            limit = 90 if key == 'latitude' else 180
            if not (-limit <= value <= limit):
                return None, f"location.{key} out of range"
            cleaned[key] = value

    if not partial or 'elevation' in payload:
        try:
            raw_elevation = payload.get('elevation')
            if raw_elevation is None:
                raise TypeError()
            cleaned['elevation'] = float(raw_elevation)
        except (TypeError, ValueError):
            return None, "location.elevation must be a number"

    if not partial or 'timezone' in payload:
        tz_name = str(payload.get('timezone') or '').strip()
        if tz_name not in available_timezones():
            return None, "location.timezone is not a valid IANA timezone"
        cleaned['timezone'] = tz_name

    if 'bortle' in payload:
        _bortle_val = payload.get('bortle')
        if _bortle_val is None:
            cleaned['bortle'] = None
        else:
            try:
                _b = int(_bortle_val)
                if not (1 <= _b <= 9):
                    raise ValueError()
                cleaned['bortle'] = _b
            except (TypeError, ValueError):
                return None, "location.bortle must be an integer between 1 and 9"

    if 'sqm' in payload:
        _sqm_val = payload.get('sqm')
        if _sqm_val is None:
            cleaned['sqm'] = None
        else:
            try:
                _s = float(_sqm_val)
                if _s <= 0:
                    raise ValueError()
                cleaned['sqm'] = _s
            except (TypeError, ValueError):
                return None, "location.sqm must be a positive float (mag/arcsec²)"

    if 'horizon_profile' in payload:
        horizon = payload.get('horizon_profile')
        if horizon is None:
            horizon = []
        if not isinstance(horizon, list):
            return None, "location.horizon_profile must be a list"
        cleaned['horizon_profile'] = horizon

    return cleaned, None


@locations_bp.route('/api/config', methods=['POST'])
@admin_required
def update_config_api():
    """
    Update configuration (global app settings).

    v1.2: location presets are managed via /api/locations. For backward
    compatibility (setup wizard, older clients), an incoming legacy
    ``location`` payload is applied to the *install default* preset; a change
    of its coordinates resets that preset's caches only.
    """
    config = request.json

    # Load old config to detect changes
    old_config = load_config()

    # Ensure Astrodex config exists with defaults
    if 'astrodex' not in config:
        config['astrodex'] = {"private": False}

    # Migrate legacy top-level 'constraints' → skytonight.constraints
    legacy_constraints = config.pop('constraints', None)

    # Ensure SkyTonight block exists; deep-merge partial incoming skytonight
    # with the full existing skytonight config so that settings not controlled
    # by the settings UI (scheduler, datasets, preferred_name_order …) are
    # never silently discarded.
    old_skytonight = old_config.get('skytonight') if isinstance(old_config, dict) else None
    if not isinstance(old_skytonight, dict):
        old_skytonight = {}

    incoming_skytonight = config.get('skytonight')
    if not isinstance(incoming_skytonight, dict):
        config['skytonight'] = dict(old_skytonight)
    else:
        merged_st = dict(old_skytonight)
        for _k, _v in incoming_skytonight.items():
            if isinstance(_v, dict) and isinstance(merged_st.get(_k), dict):
                merged_st[_k] = {**merged_st[_k], **_v}
            else:
                merged_st[_k] = _v
        config['skytonight'] = merged_st

    # horizon_profile is per-location since v1.2 - never persist it under
    # skytonight.constraints again (legacy clients may still send it there).
    constraints_block = config['skytonight'].get('constraints')
    incoming_constraints_raw = (
        (incoming_skytonight or {}).get('constraints', {}) if isinstance(incoming_skytonight, dict) else {}
    )
    legacy_horizon_payload = incoming_constraints_raw.get('horizon_profile')
    legacy_horizon_cleared = bool(incoming_constraints_raw.get('_horizon_cleared', False))
    if isinstance(constraints_block, dict):
        constraints_block.pop('horizon_profile', None)
        constraints_block.pop('_horizon_cleared', None)

    # Apply migrated legacy constraints when skytonight.constraints was absent
    if legacy_constraints and not config['skytonight'].get('constraints'):
        legacy_constraints.pop('horizon_profile', None)
        config['skytonight']['constraints'] = legacy_constraints

    config['skytonight']['enabled'] = True

    # --- Legacy location payload -> install default preset (compat path) ---
    location_changed = False
    incoming_location = config.pop('location', None)
    locations = old_config.get('locations', [])
    if isinstance(incoming_location, dict) and incoming_location:
        cleaned, error = _validate_location_payload(incoming_location, partial=True)
        if error:
            return jsonify({"error": error}), 400
        install_default = get_install_default_location(old_config)
        for preset in locations:
            if preset.get('id') == install_default.get('id'):
                before = cache_store.get_current_location_signature(preset)
                preset.update(cleaned)
                if legacy_horizon_payload or legacy_horizon_cleared:
                    preset['horizon_profile'] = legacy_horizon_payload or []
                preset['updated_at'] = datetime.now(timezone.utc).isoformat()
                location_changed = before != cache_store.get_current_location_signature(preset)
                if location_changed:
                    cache_store.reset_caches_for_location(preset['id'])
                    cache_store.update_location_config(preset)
                    # Stale night table: drop so the scheduler recomputes for the new coordinates
                    drop_skytonight_location_results(preset['id'])
                break
    config['locations'] = locations

    # Preserve location_configured flag if not explicitly provided
    if 'location_configured' not in config:
        config['location_configured'] = old_config.get('location_configured', False)

    # Save the new config
    save_config(config)

    if location_changed:
        logger.warning("Install default location changed! Its astronomical caches were reset.")

    return jsonify(
        {
            "status": "success",
            "config": config,
            "cache_reset": location_changed,
            "message": "Configuration updated" + (" and cache reset" if location_changed else ""),
        }
    )


# ---------------------------------------------------------------------------
# Multi-location profiles (v1.2) - admin CRUD + attribution + user switcher
# ---------------------------------------------------------------------------


def _location_admin_view(config, preset):
    """Admin-facing serialization of a preset, including attribution info."""
    attributed_to = []
    for user in user_manager.users.values():
        prefs = get_user_location_prefs(user)
        if preset.get('id') in prefs['attributed_location_ids']:
            attributed_to.append({'user_id': user.user_id, 'username': user.username})
    view = dict(preset)
    view['attributed_to'] = attributed_to
    # Lets the admin UI show "N attributed, M excluded" instead of naming
    # every user - unusable once an install has more than a handful of them.
    view['total_users'] = len(user_manager.users)
    return view


@locations_bp.route('/api/locations', methods=['GET'])
@admin_required
def list_locations_api():
    """List all location presets with attribution info (admin management view)."""
    try:
        config = load_config()
        locations = [_location_admin_view(config, preset) for preset in get_all_locations(config)]
        return jsonify({'locations': locations, 'max_locations': MAX_LOCATIONS})
    except Exception as e:
        logger.error(f"Error listing locations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations', methods=['POST'])
@admin_required
def create_location_api():
    """Create a location preset (admin only, hard-capped at MAX_LOCATIONS)."""
    try:
        config = load_config()
        locations = get_all_locations(config)
        if len(locations) >= MAX_LOCATIONS:
            return (
                jsonify(
                    {
                        'error': f'Maximum number of locations reached ({MAX_LOCATIONS})',
                        'error_key': 'locations.max_reached',
                    }
                ),
                400,
            )

        cleaned, error = _validate_location_payload(request.json or {})
        if error:
            return jsonify({'error': error}), 400

        preset = new_location_preset(base=cleaned)
        config['locations'].append(preset)
        save_config(config)

        # Start signature tracking now; cache slots fill on the next scheduler tick
        cache_store.update_location_config(preset)

        # New locations are attributed to everyone by default - an admin can
        # manually exclude specific users afterward. Saves re-attributing by
        # hand on larger installs (e.g. an astro club with 100+ users).
        user_manager.set_location_attribution(preset['id'], list(user_manager.users.keys()))

        logger.info(f"Location preset created: {preset['name']} ({preset['id']})")
        return jsonify({'status': 'success', 'location': _location_admin_view(config, preset)}), 201
    except Exception as e:
        logger.error(f"Error creating location: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations/<location_id>', methods=['PUT'])
@admin_required
def update_location_api(location_id):
    """Edit a location preset. Coordinate/timezone changes reset only that preset's caches."""
    try:
        config = load_config()
        preset = get_location_by_id(config, location_id)
        if preset is None:
            return jsonify({'error': 'Location not found', 'error_key': 'locations.not_found'}), 404

        payload = request.json or {}
        cleaned, error = _validate_location_payload(payload, partial=True)
        if error:
            return jsonify({'error': error}), 400

        before_signature = cache_store.get_current_location_signature(preset)
        preset.update(cleaned)

        if payload.get('is_install_default') is True and not preset.get('is_install_default'):
            # Promote atomically: exactly one preset carries the flag
            for other in get_all_locations(config):
                other['is_install_default'] = other.get('id') == location_id

        preset['updated_at'] = datetime.now(timezone.utc).isoformat()
        save_config(config)

        cache_reset = before_signature != cache_store.get_current_location_signature(preset)
        if cache_reset:
            logger.warning(f"Location preset '{preset['name']}' coordinates changed - resetting its caches")
            cache_store.reset_caches_for_location(location_id)
            cache_store.update_location_config(preset)
            # Stale night table: drop so the scheduler recomputes for the new coordinates
            drop_skytonight_location_results(location_id)

        return jsonify(
            {'status': 'success', 'location': _location_admin_view(config, preset), 'cache_reset': cache_reset}
        )
    except Exception as e:
        logger.error(f"Error updating location {location_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations/<location_id>/references', methods=['GET'])
@admin_required
def location_references_api(location_id):
    """Lightweight pre-delete check: who/what references this preset."""
    try:
        config = load_config()
        preset = get_location_by_id(config, location_id)
        if preset is None:
            return jsonify({'error': 'Location not found', 'error_key': 'locations.not_found'}), 404

        attributed_users = _location_admin_view(config, preset)['attributed_to']
        astrodex_count = astrodex.count_pictures_for_location(location_id)
        plan_count = plan_my_night.count_plans_for_location(location_id)
        return jsonify(
            {
                'location_id': location_id,
                'is_install_default': bool(preset.get('is_install_default')),
                'attributed_users': attributed_users,
                'astrodex_pictures': astrodex_count,
                'plan_my_night_plans': plan_count,
            }
        )
    except Exception as e:
        logger.error(f"Error checking location references {location_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations/<location_id>', methods=['DELETE'])
@admin_required
def delete_location_api(location_id):
    """Delete a preset.

    Blocked while the preset is the install default (promote another one
    first). User pointers are cleaned eagerly; Plan My Night entries pinned to
    the preset are cascade-deleted by default (?plans=orphan keeps them with a
    stale-location banner); Astrodex items are NEVER touched - they keep their
    frozen location_name snapshot.
    """
    try:
        config = load_config()
        preset = get_location_by_id(config, location_id)
        if preset is None:
            return jsonify({'error': 'Location not found', 'error_key': 'locations.not_found'}), 404

        if preset.get('is_install_default'):
            return (
                jsonify(
                    {
                        'error': 'Cannot delete the install default location - promote another preset first',
                        'error_key': 'locations.cannot_delete_default',
                    }
                ),
                400,
            )

        plans_mode = (request.args.get('plans') or 'cascade').lower()
        if plans_mode not in ('cascade', 'orphan'):
            return jsonify({'error': "plans must be 'cascade' or 'orphan'"}), 400

        config['locations'] = [loc for loc in get_all_locations(config) if loc.get('id') != location_id]
        save_config(config)

        install_default = get_install_default_location(config)
        user_manager.cleanup_location_references(location_id, install_default.get('id'))
        cache_store.drop_location_caches(location_id)
        drop_skytonight_location_results(location_id)

        deleted_plans = 0
        if plans_mode == 'cascade':
            deleted_plans = plan_my_night.delete_plans_for_location(location_id)

        logger.info(f"Location preset deleted: {preset.get('name')} ({location_id}), plans={plans_mode}")
        return jsonify({'status': 'success', 'deleted_plans': deleted_plans, 'plans_mode': plans_mode})
    except Exception as e:
        logger.error(f"Error deleting location {location_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations/<location_id>/attribute', methods=['POST'])
@admin_required
def attribute_location_api(location_id):
    """Attach/detach a preset to a set of user ids (admin-controlled many-to-many)."""
    try:
        config = load_config()
        preset = get_location_by_id(config, location_id)
        if preset is None:
            return jsonify({'error': 'Location not found', 'error_key': 'locations.not_found'}), 404

        data = request.json or {}
        user_ids = data.get('user_ids')
        if not isinstance(user_ids, list) or not all(isinstance(uid, str) for uid in user_ids):
            return jsonify({'error': 'user_ids must be a list of user id strings'}), 400

        known_ids = set(user_manager.users.keys())
        unknown = [uid for uid in user_ids if uid not in known_ids]
        if unknown:
            return jsonify({'error': f"Unknown user ids: {', '.join(unknown)}"}), 400

        user_manager.set_location_attribution(location_id, user_ids)
        return jsonify({'status': 'success', 'location': _location_admin_view(config, preset)})
    except Exception as e:
        logger.error(f"Error attributing location {location_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _cached_location_score(location_id):
    """Best-effort current observation score (0-10) for a location, from the
    already-warm weather_forecast cache - never triggers a live Open-Meteo call.

    Mirrors the 0-10 scale used by the sky widget's own score badge (derived
    from cloudless/seeing/transparency), just read from the cheaper per-location
    forecast cache instead of weather_astro's live analysis pipeline.
    """
    try:
        entry = cache_store.load_location_cache('weather_forecast', location_id)
        hourly = (entry.get('data') or {}).get('hourly') or []
        if not hourly:
            return None
        condition = hourly[0].get('condition')
        return round(float(condition) / 10, 1) if condition is not None else None
    except Exception:
        return None


@locations_bp.route('/api/locations/mine', methods=['GET'])
@login_required
def my_locations_api():
    """The caller's attributed locations (cheap - no live sky data), for the switcher."""
    try:
        config = load_config()
        user = get_current_user()
        accessible = get_locations_for_user(config, user)
        active = get_active_location(config, user)
        prefs = get_user_location_prefs(user)
        return jsonify(
            {
                'locations': [
                    {
                        'id': loc['id'],
                        'name': loc.get('name'),
                        'latitude': loc.get('latitude'),
                        'longitude': loc.get('longitude'),
                        'bortle': loc.get('bortle'),
                        'sqm': loc.get('sqm'),
                        'timezone': loc.get('timezone'),
                        'is_install_default': bool(loc.get('is_install_default')),
                        'score': _cached_location_score(loc['id']),
                    }
                    for loc in accessible
                ],
                'active_location_id': active.get('id'),
                'default_location_id': prefs['default_location_id'] or active.get('id'),
            }
        )
    except Exception as e:
        logger.error(f"Error listing user locations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@locations_bp.route('/api/locations/active', methods=['POST'])
@login_required
def set_active_location_api():
    """Set the caller's active location (drives all calculations this session)."""
    try:
        data = request.json or {}
        location_id = data.get('location_id')
        if not isinstance(location_id, str) or not location_id:
            return jsonify({'error': 'location_id is required'}), 400

        config = load_config()
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessible_ids = {loc['id'] for loc in get_locations_for_user(config, user)}
        if location_id not in accessible_ids:
            return jsonify({'error': 'Location not accessible', 'error_key': 'locations.not_accessible'}), 403

        user_manager.set_user_location_prefs(user.user_id, active_location_id=location_id)
        location = get_location_by_id(config, location_id)
        return jsonify(
            {
                'status': 'success',
                'active_location_id': location_id,
                'name': location.get('name') if location else None,
            }
        )
    except Exception as e:
        logger.error(f"Error setting active location: {e}")
        return jsonify({'error': 'Internal server error'}), 500
