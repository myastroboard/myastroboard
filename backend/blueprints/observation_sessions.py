"""Observation Log Blueprint. Routes: /api/observation-sessions/*

Response envelope follows the Equipment blueprint's convention: collection GET returns
``{key: [...], ...metadata}``, single GET returns the bare object, and mutating routes
return ``{"status": "success", "data": ...}`` or ``{"error": "..."}`` with the matching
HTTP status.

Cross-module resolution helpers (location/combination/rating validation, Astrodex
find-or-create) live here rather than in ``observation/observation_sessions.py``, exactly
mirroring where ``blueprints/astrodex.py`` keeps its own equivalents.
"""

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename

from astroweather.moon_planner import moon_illumination_percent
from equipment import equipment_profiles
from observation import astrodex
from observation import observation_sessions
from observation import plan_my_night
from utils.auth import login_required, user_required, get_current_user
from utils.i18n_utils import I18nManager
from utils.image_privacy import strip_image_metadata
from utils.logging_config import get_logger
from utils.repo_config import load_config, get_locations_for_user, get_location_by_id
from blueprints.plan_my_night import _resolve_requested_language

logger = get_logger(__name__)

observation_sessions_bp = Blueprint('observation_sessions', __name__)

_EMPTY_SESSION_LOCATION = {
    'location_id': None,
    'location_name': None,
    'location_latitude': None,
    'location_longitude': None,
    'location_elevation': None,
}


def _safe_session_coordinate(value, min_value, max_value):
    """Best-effort float parse for a manually-typed coordinate. Returns None for
    anything empty, unparseable, or out of range - a bad value is simply dropped (same
    low-stakes trust level as notes), not a 400."""
    if value is None or value == '':
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not (min_value <= parsed <= max_value):
        return None
    return parsed


def _validate_and_coerce_rating(entry_data: Dict) -> Any:
    """Validate entry_data['rating'] in place (0.0-5.0 in 0.5 steps) and coerce it to a
    clean float, or None if left blank. Returns an error message string on failure, else
    None.

    Identical contract to Astrodex's picture rating validator: a bad rating is rejected
    (400) rather than silently dropped, because it is a value the user explicitly set via
    the star widget - not a loosely-typed free-text field.
    """
    value = entry_data.get('rating')
    if value is None or value == '':
        entry_data['rating'] = None
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return 'rating must be a number between 0 and 5'
    if not (0 <= rating <= 5) or (rating * 2) != int(round(rating * 2)):
        return 'rating must be between 0 and 5 in 0.5 steps'
    entry_data['rating'] = rating
    return None


def _validate_and_coerce_picture_capture(picture_data: Dict) -> Any:
    """Validate/coerce picture_data['exposition_time'], ['frames'] and
    ['integration_minutes'] in place, mirroring Astrodex's own picture capture validator
    (``blueprints/astrodex.py``'s ``_validate_and_coerce_picture_capture``, duplicated
    rather than imported to avoid a cross-blueprint import - see
    ``_resolve_session_location_snapshot`` above for the same rationale).

    Only touches keys actually present. In practice the values reaching here already came
    from the entry's own validated frame_count/sub_exposure_seconds/integration_minutes,
    so this mostly guards a hypothetical direct API call that overrides them.
    """
    if 'exposition_time' in picture_data:  # pragma: no branch - caller always sets this key
        value = picture_data['exposition_time']
        if value is None or value == '':
            picture_data['exposition_time'] = None
        else:
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                return 'exposition_time must be a whole number of seconds'
            if seconds < 0:
                return 'exposition_time must be a whole number of seconds'
            picture_data['exposition_time'] = seconds

    if 'frames' in picture_data:  # pragma: no branch - caller always sets this key
        value = picture_data['frames']
        if value is None or value == '':
            picture_data['frames'] = None
        else:
            try:
                frames = int(value)
            except (TypeError, ValueError):
                return 'frames must be a whole number'
            if frames < 0:
                return 'frames must be a whole number'
            picture_data['frames'] = frames

    if 'integration_minutes' in picture_data:  # pragma: no branch - caller always sets this key
        value = picture_data['integration_minutes']
        if value is None or value == '':
            picture_data['integration_minutes'] = None
        else:
            try:
                integration = float(value)
            except (TypeError, ValueError):
                return 'integration_minutes must be a number'
            if integration < 0:
                return 'integration_minutes must be a number'
            picture_data['integration_minutes'] = integration

    return None


def _resolve_session_combination_reference(combination_id, user_id) -> Optional[str]:
    """Return combination_id if it resolves to an accessible (own or shared) combination
    for this user, else None - so a session (or, via the same check, one of its entries -
    see _apply_resolved_entry_combination below) can never be tagged with a combination
    the logger has no access to."""
    if not combination_id:
        return None
    if equipment_profiles.get_combination(user_id, combination_id):
        return combination_id
    shared = equipment_profiles.load_all_shared_combinations(user_id)
    if any(combo['id'] == combination_id for combo in shared):
        return combination_id
    return None


def _apply_resolved_entry_combination(payload: Dict, user) -> None:
    """Resolve an entry's optional per-target equipment override server-side, in place.

    Same contract as the combination half of _apply_resolved_session_fields (only
    touched when the payload explicitly includes ``combination_id``, so editing
    unrelated entry fields never disturbs an existing override), reusing
    _resolve_session_combination_reference since the access check is identical -
    entries don't need their own resolver, just their own call site. A null/absent
    result means "use the session's own equipment" (see observation_sessions.py's
    ENTRY_UPDATABLE_FIELDS docstring).
    """
    if 'combination_id' not in payload:
        return
    payload['combination_id'] = _resolve_session_combination_reference(payload.get('combination_id'), user.user_id)
    if payload['combination_id']:
        combination = equipment_profiles.get_combination(user.user_id, payload['combination_id'])
        if combination is None:
            combination = next(
                (
                    combo
                    for combo in equipment_profiles.load_all_shared_combinations(user.user_id)
                    if combo['id'] == payload['combination_id']
                ),
                None,
            )
        payload['combination_name'] = (combination or {}).get('name')
    else:
        payload['combination_name'] = None


def _resolve_session_location_snapshot(
    location_id, user, custom_name=None, custom_latitude=None, custom_longitude=None
):
    """Resolve a session's location into a frozen snapshot: either a preset (looked up +
    access-checked server-side) or a free-text "somewhere else" label the user typed.

    Same 3-state logic as ``blueprints/astrodex.py``'s
    ``_resolve_picture_location_snapshot`` - duplicated rather than imported to avoid a
    cross-blueprint import, and keyed on this module's own ``location_*`` field names.
    Preset coordinates are looked up server-side and never trusted from the client.
    """
    if location_id:
        config = load_config()
        accessible_ids = {loc['id'] for loc in get_locations_for_user(config, user)}
        if location_id in accessible_ids:
            location = get_location_by_id(config, location_id)
            if location:
                return {
                    'location_id': location['id'],
                    'location_name': location.get('name'),
                    'location_latitude': location.get('latitude'),
                    'location_longitude': location.get('longitude'),
                    'location_elevation': location.get('elevation'),
                }
        # location_id supplied but doesn't resolve to a real/accessible preset -
        # fall through; a custom label (if any) can still stand on its own.

    custom_name = (custom_name or '').strip()
    if custom_name:
        return {
            'location_id': None,
            'location_name': custom_name,
            'location_latitude': _safe_session_coordinate(custom_latitude, -90, 90),
            'location_longitude': _safe_session_coordinate(custom_longitude, -180, 180),
            'location_elevation': None,
        }

    return dict(_EMPTY_SESSION_LOCATION)


def _location_preset_sqm(location_id) -> Optional[float]:
    """Return a location preset's own configured SQM, used to pre-fill a new session."""
    if not location_id:
        return None
    try:
        location = get_location_by_id(load_config(), location_id)
    except Exception as error:  # pragma: no cover - config read failure
        logger.error(f'Error reading location preset {location_id} for SQM prefill: {error}')
        return None
    if not location:
        return None
    return _safe_session_coordinate(location.get('sqm'), 0, 30)


def _compute_moon_illumination_for_date(date_str: Optional[str]) -> Optional[float]:
    """Moon illumination (%) for a given calendar date.

    Unlike seeing/transparency (a 7Timer *forecast*, only available for today), this is
    a pure ephemeris computation - it works for any date, including the past, which
    matters since sessions are usually logged the morning after. Anchored at UTC noon:
    illumination changes by well under a percent across a single night, so the exact
    hour is immaterial. Always server-computed, never trusted from the client (see
    astroweather.moon_planner.moon_illumination_percent - the same engine already
    powering the 7-night Moon Planner forecast, for consistency app-wide).
    """
    if not date_str:
        return None
    try:
        parsed_date = datetime.strptime(str(date_str), '%Y-%m-%d')
    except (TypeError, ValueError):
        return None
    try:
        return round(moon_illumination_percent(parsed_date.replace(hour=12, tzinfo=timezone.utc)), 1)
    except Exception as error:  # pragma: no cover - ephemeris library failure
        logger.error(f'Error computing moon illumination for {date_str}: {error}')
        return None


def _apply_resolved_session_fields(payload: Dict, user) -> None:
    """Resolve the client-supplied combination/location of a create/update payload
    server-side, in place.

    Location is only touched when the payload explicitly mentions it, so editing an
    unrelated field (notes, seeing, ...) never disturbs an existing snapshot - same rule
    as Astrodex picture updates.
    """
    if 'combination_id' in payload:
        payload['combination_id'] = _resolve_session_combination_reference(payload.get('combination_id'), user.user_id)
        if payload['combination_id']:
            combination = equipment_profiles.get_combination(user.user_id, payload['combination_id'])
            if combination is None:
                combination = next(
                    (
                        combo
                        for combo in equipment_profiles.load_all_shared_combinations(user.user_id)
                        if combo['id'] == payload['combination_id']
                    ),
                    None,
                )
            payload['combination_name'] = (combination or {}).get('name')
        else:
            payload['combination_name'] = None

    if 'location_id' in payload or 'location_name' in payload:
        payload.update(
            _resolve_session_location_snapshot(
                payload.get('location_id'),
                user,
                custom_name=payload.get('location_name'),
                custom_latitude=payload.get('location_latitude'),
                custom_longitude=payload.get('location_longitude'),
            )
        )


def _validate_night_id(session: Dict, night_id: Optional[str]) -> Any:
    """Validate that *night_id* (if given) resolves to one of *session*'s nights.
    Returns an error message string on failure, else None (a blank night_id is valid -
    the caller defaults it, see _default_night_id())."""
    if not night_id:
        return None
    if any(isinstance(night, dict) and night.get('id') == night_id for night in session.get('nights', [])):
        return None
    return 'night_id does not resolve to a night in this session'


def _default_night_id(session: Dict) -> Optional[str]:
    """Which night a new entry defaults to when the client doesn't specify one: the
    most recently added night, so adding a target right after "Add night" lands it on
    that new night rather than always the first one."""
    nights = [night for night in session.get('nights', []) or [] if isinstance(night, dict)]
    return nights[-1]['id'] if nights else None


def _ensure_astrodex_item_for_entry(user, entry: Dict) -> Optional[str]:
    """Find-or-create the Astrodex item for this entry's target, idempotently.

    Returns the astrodex_item_id (existing or newly created), or None when the target
    has no usable name or the item could not be created. Never raises on a "duplicate":
    unlike the user-initiated add-item flow (which surfaces a 409 for the user to
    resolve), this is an automatic background link, so it always silently resolves to
    *some* item id.
    """
    item_name = str(entry.get('name') or '').strip()
    if not item_name:
        return None

    catalogue = str(entry.get('catalogue') or '')
    existing = astrodex.find_item_in_astrodex(user.user_id, item_name, catalogue)
    if existing:
        return existing.get('id')

    item_data = {
        'name': item_name,
        'type': entry.get('type') or 'Unknown',
        'catalogue': catalogue,
        'constellation': entry.get('constellation') or '',
        'notes': '',
    }
    aliases = entry.get('catalogue_aliases')
    if isinstance(aliases, dict) and aliases:
        item_data['external_aliases'] = aliases

    created = astrodex.create_astrodex_item(user.user_id, item_data, user.username)
    if created:
        return created.get('id')

    # create_astrodex_item returns None when its own duplicate check fired between our
    # lookup and the write - re-resolve rather than losing the link.
    fallback = astrodex.find_item_in_astrodex(user.user_id, item_name, catalogue)
    return fallback.get('id') if fallback else None


def _auto_link_astrodex_item(user, session_id: str, entry: Dict) -> Dict:
    """Register the entry's target in Astrodex as soon as it has real capture evidence.

    "Catch them all" is a keypoint of this app, so item-level catalogue membership is
    automatic rather than a button the user could forget. It is never auto-reversed:
    editing frame_count back down to 0 leaves astrodex_item_id in place (Astrodex item
    deletion stays a deliberate, guarded user action).
    """
    frame_count = entry.get('frame_count') or 0
    if frame_count <= 0 or entry.get('astrodex_item_id'):
        return entry

    try:
        item_id = _ensure_astrodex_item_for_entry(user, entry)
    except Exception as error:
        logger.error(f"Error auto-linking entry {entry.get('id')} to Astrodex: {error}")
        return entry

    if not item_id:
        return entry

    linked = observation_sessions.link_entry_to_astrodex(user.user_id, session_id, entry.get('id', ''), item_id)
    return linked or entry


@observation_sessions_bp.route('/api/observation-sessions', methods=['GET'])
@login_required
def list_observation_sessions():
    """List the current user's own sessions (newest observation date first) + stats."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = observation_sessions.load_user_sessions(user.user_id, user.username)
        return jsonify(
            {
                'sessions': observation_sessions.get_user_sessions(user.user_id),
                'stats': observation_sessions.get_session_stats(user.user_id),
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as error:
        logger.error(f'Error listing observation sessions: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>', methods=['GET'])
@login_required
def get_observation_session(session_id):
    """Get one session with its entries."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        return jsonify(session)
    except Exception as error:
        logger.error(f'Error getting observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions', methods=['POST'])
@user_required
def create_observation_session():
    """Create a session manually."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        if not str(payload.get('date') or '').strip():
            return jsonify({'error': 'Session date is required'}), 400

        _apply_resolved_session_fields(payload, user)

        # Sky quality defaults to the chosen preset's own configured value; the user can
        # always override it afterwards (measured SQM varies night to night).
        if payload.get('sqm') in (None, '') and payload.get('location_id'):
            payload['sqm'] = _location_preset_sqm(payload['location_id'])

        payload['moon_illumination_percent'] = _compute_moon_illumination_for_date(payload.get('date'))

        session = observation_sessions.create_session(user.user_id, user.username, payload)
        if not session:
            return jsonify({'error': 'Failed to create session'}), 500

        return jsonify({'status': 'success', 'data': session}), 201
    except Exception as error:
        logger.error(f'Error creating observation session: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>', methods=['PUT'])
@user_required
def update_observation_session(session_id):
    """Update session-level fields."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        _apply_resolved_session_fields(payload, user)

        session = observation_sessions.update_session(user.user_id, session_id, payload)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        return jsonify({'status': 'success', 'data': session})
    except Exception as error:
        logger.error(f'Error updating observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>', methods=['DELETE'])
@user_required
def delete_observation_session(session_id):
    """Delete a session and all of its entries (Astrodex is never touched)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not observation_sessions.delete_session(user.user_id, session_id):
            return jsonify({'error': 'Session not found'}), 404

        return jsonify({'status': 'success', 'data': {'id': session_id}})
    except Exception as error:
        logger.error(f'Error deleting observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/nights', methods=['POST'])
@user_required
def add_observation_session_night(session_id):
    """Add another night to a multi-night session. ``date`` is required."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        if not str(payload.get('date') or '').strip():
            return jsonify({'error': 'Night date is required'}), 400

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        # Same SQM-from-preset prefill as session creation, keyed off the session's own
        # (fixed-for-the-whole-trip) location rather than a per-night one.
        if payload.get('sqm') in (None, '') and session.get('location_id'):
            payload['sqm'] = _location_preset_sqm(session['location_id'])
        payload['moon_illumination_percent'] = _compute_moon_illumination_for_date(payload.get('date'))

        night = observation_sessions.add_night(user.user_id, session_id, payload)
        if not night:
            return jsonify({'error': 'Failed to add night'}), 500

        return jsonify({'status': 'success', 'data': night}), 201
    except Exception as error:
        logger.error(f'Error adding night to observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/nights/<night_id>', methods=['PUT'])
@user_required
def update_observation_session_night(session_id, night_id):
    """Update one night's conditions/notes."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        if payload.get('date'):
            payload['moon_illumination_percent'] = _compute_moon_illumination_for_date(payload.get('date'))

        night = observation_sessions.update_night(user.user_id, session_id, night_id, payload)
        if not night:
            return jsonify({'error': 'Night not found'}), 404

        return jsonify({'status': 'success', 'data': night})
    except Exception as error:
        logger.error(f'Error updating night {night_id} in observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/nights/<night_id>', methods=['DELETE'])
@user_required
def delete_observation_session_night(session_id, night_id):
    """Remove one night.

    Refused (400) while it's the session's last remaining night, or while any entry
    still points at it - see observation_sessions.delete_night()'s docstring.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        nights = session.get('nights', [])
        if not any(isinstance(night, dict) and night.get('id') == night_id for night in nights):
            return jsonify({'error': 'Night not found'}), 404

        if not observation_sessions.delete_night(user.user_id, session_id, night_id):
            if len(nights) <= 1:
                return jsonify({'error': "Cannot delete a session's last remaining night"}), 400
            return jsonify({'error': 'Cannot delete a night that still has entries - move or delete them first'}), 400

        return jsonify({'status': 'success', 'data': {'id': night_id}})
    except Exception as error:
        logger.error(f'Error deleting night {night_id} from observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/from-plan', methods=['POST'])
@user_required
def create_observation_session_from_plan():
    """Seed a new session from a Plan My Night plan, or merge into an existing one.

    Deliberately not gated on ``state == 'current'``: a plan flips to ``'previous'`` the
    moment ``night_end`` passes, which is exactly when the user sits down to log what
    they actually captured. Importing is a read operation from the plan's perspective,
    so only ``'none'`` (nothing to import) is refused.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        combination_id = data.get('combination_id') or None
        session_id = data.get('session_id') or None

        result = plan_my_night.get_plan_with_timeline(user.user_id, user.username, combination_id=combination_id)
        if result.get('state') == 'none' or not (result.get('plan') or {}).get('entries'):
            return jsonify({'error': 'No plan to import'}), 404

        session = observation_sessions.create_session_from_plan(user.user_id, user.username, result['plan'], session_id)
        if not session:
            # A supplied session_id that doesn't resolve is a 404; anything else is a
            # write failure inside the storage layer.
            status = 404 if session_id else 500
            return jsonify({'error': 'Failed to import plan'}), status

        return jsonify({'status': 'success', 'data': session}), 201
    except Exception as error:
        logger.error(f'Error importing plan into an observation session: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/entries', methods=['POST'])
@user_required
def add_observation_session_entry(session_id):
    """Add one target entry to a session.

    Side effect: registers the target in Astrodex when ``frame_count > 0`` (see
    _auto_link_astrodex_item).
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        if not str(payload.get('name') or '').strip():
            return jsonify({'error': 'Target name is required'}), 400

        rating_error = _validate_and_coerce_rating(payload)
        if rating_error:
            return jsonify({'error': rating_error}), 400

        _apply_resolved_entry_combination(payload, user)

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        night_error = _validate_night_id(session, payload.get('night_id'))
        if night_error:
            return jsonify({'error': night_error}), 400
        if not payload.get('night_id'):
            payload['night_id'] = _default_night_id(session)

        entry = observation_sessions.add_entry(user.user_id, session_id, payload)
        if not entry:
            return jsonify({'error': 'Session not found'}), 404

        entry = _auto_link_astrodex_item(user, session_id, entry)
        return jsonify({'status': 'success', 'data': entry}), 201
    except Exception as error:
        logger.error(f'Error adding entry to observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/entries/<entry_id>', methods=['PUT'])
@user_required
def update_observation_session_entry(session_id, entry_id):
    """Update one entry's actual-capture fields.

    Side effect: same automatic Astrodex item registration as the add route, whenever
    ``frame_count`` newly becomes > 0.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = dict(request.json or {})
        if 'rating' in payload:
            rating_error = _validate_and_coerce_rating(payload)
            if rating_error:
                return jsonify({'error': rating_error}), 400

        _apply_resolved_entry_combination(payload, user)

        if payload.get('night_id'):
            session = observation_sessions.get_session(user.user_id, session_id)
            if not session:
                return jsonify({'error': 'Session not found'}), 404
            night_error = _validate_night_id(session, payload.get('night_id'))
            if night_error:
                return jsonify({'error': night_error}), 400

        entry = observation_sessions.update_entry(user.user_id, session_id, entry_id, payload)
        if not entry:
            return jsonify({'error': 'Entry not found'}), 404

        entry = _auto_link_astrodex_item(user, session_id, entry)
        return jsonify({'status': 'success', 'data': entry})
    except Exception as error:
        logger.error(f'Error updating entry {entry_id} in observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/entries/<entry_id>', methods=['DELETE'])
@user_required
def delete_observation_session_entry(session_id, entry_id):
    """Remove one entry (its linked Astrodex item/picture is a soft reference, kept)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not observation_sessions.delete_entry(user.user_id, session_id, entry_id):
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'status': 'success', 'data': {'id': entry_id}})
    except Exception as error:
        logger.error(f'Error deleting entry {entry_id} from observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route(
    '/api/observation-sessions/<session_id>/entries/<entry_id>/astrodex-picture', methods=['POST']
)
@user_required
def attach_astrodex_picture_to_entry(session_id, entry_id):
    """Attach an already-uploaded image to this entry's Astrodex item.

    The image itself must have been uploaded through the existing, unchanged
    ``POST /api/astrodex/upload`` route: no picture ever lives in Observation Log
    storage, the only image directory involved is Astrodex's own. This stays a manual
    step (unlike item registration) because stacking/processing genuinely happens days
    after the session.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        entry = next(
            (item for item in session.get('entries', []) if isinstance(item, dict) and item.get('id') == entry_id),
            None,
        )
        if not entry:
            return jsonify({'error': 'Entry not found'}), 404

        payload = dict(request.json or {})
        filename = str(payload.get('filename') or '').strip()
        if not filename:
            return jsonify({'error': 'filename is required'}), 400

        # Covers the case where the photo is attached before frame_count was ever set -
        # a processed image is capture evidence in its own right.
        item_id = entry.get('astrodex_item_id') or _ensure_astrodex_item_for_entry(user, entry)
        if not item_id:
            return jsonify({'error': 'Failed to resolve Astrodex item'}), 500

        entry_night = observation_sessions.get_night(session, entry.get('night_id'))
        entry_date = entry_night.get('date') if entry_night else observation_sessions.session_date_range(session)[0]

        sub_exposure = entry.get('sub_exposure_seconds')
        picture_data = {
            'filename': filename,
            'date': payload.get('date') or entry_date or '',
            'frames': payload.get('frames') if 'frames' in payload else entry.get('frame_count'),
            'exposition_time': (
                payload.get('exposition_time')
                if 'exposition_time' in payload
                else (round(sub_exposure) if sub_exposure is not None else None)
            ),
            'integration_minutes': (
                payload.get('integration_minutes')
                if 'integration_minutes' in payload
                else entry.get('integration_minutes')
            ),
            'notes': payload.get('notes') if 'notes' in payload else entry.get('notes', ''),
            'location_id': session.get('location_id'),
            'location_name': session.get('location_name'),
            'latitude': session.get('location_latitude'),
            'longitude': session.get('location_longitude'),
            'elevation': session.get('location_elevation'),
            # Prefer the target's own equipment override, if it has one, over the
            # session's default - same precedence used everywhere else this entry's
            # effective combination is resolved (see the frontend's
            # _obsWireEntryEquipmentSection).
            'combination_id': entry.get('combination_id') or session.get('combination_id'),
            'combination_used_components': entry.get('combination_used_components'),
            'rating': payload.get('rating') if 'rating' in payload else entry.get('rating'),
        }

        rating_error = _validate_and_coerce_rating(picture_data)
        if rating_error:
            return jsonify({'error': rating_error}), 400

        capture_error = _validate_and_coerce_picture_capture(picture_data)
        if capture_error:
            return jsonify({'error': capture_error}), 400

        picture = astrodex.add_picture_to_item(user.user_id, item_id, picture_data)
        if not picture:
            return jsonify({'error': 'Failed to attach picture'}), 500

        observation_sessions.link_entry_to_astrodex(user.user_id, session_id, entry_id, item_id, picture.get('id'))

        return jsonify(
            {
                'status': 'success',
                'astrodex_item_id': item_id,
                'astrodex_picture_id': picture.get('id'),
            }
        )
    except Exception as error:
        logger.error(f'Error attaching picture to entry {entry_id} of session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Attachments (v1.3.1) - generic files (images/PDF/text/Word) attached to a session,
# unrelated to the entry -> Astrodex picture link above. Modeled on astrodex.py's own
# image upload (a narrower allow-list): extension allow-list, secure_filename() only to
# pull the extension, a regenerated {user_id}_{uuid}.{ext} storage name, and a
# realpath+startswith containment check.
# ---------------------------------------------------------------------------

ATTACHMENT_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'pdf', 'txt', 'doc', 'docx'}
ATTACHMENT_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/attachments', methods=['POST'])
@user_required
def upload_observation_session_attachment(session_id):
    """Upload a file and record it against a session, in one step (unlike Astrodex's
    two-step upload-then-attach, an attachment only ever belongs to one session)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not observation_sessions.get_session(user.user_id, session_id):
            return jsonify({'error': 'Session not found'}), 404

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        if not file or not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        original_filename = secure_filename(file.filename)
        if '.' not in original_filename:
            return jsonify({'error': 'Invalid file name'}), 400

        file_ext = original_filename.rsplit('.', 1)[1].lower()
        if file_ext not in ATTACHMENT_ALLOWED_EXTENSIONS:
            return jsonify({'error': 'Invalid file type'}), 400

        # Image attachments lose their EXIF/GPS metadata before being stored.
        image_bytes: Optional[bytes] = None
        if file_ext in ATTACHMENT_IMAGE_EXTENSIONS:
            try:
                image_bytes = strip_image_metadata(file.read())
            except ValueError as error:
                logger.warning(f'Rejected session attachment that is not a valid image: {error}')
                return jsonify({'error': 'Invalid image file'}), 400

        unique_filename = f'{user.user_id}_{uuid.uuid4()}.{file_ext}'

        observation_sessions.ensure_observation_sessions_directories()
        base_dir = os.path.realpath(observation_sessions.attachments_dir())
        file_path = os.path.realpath(os.path.join(base_dir, unique_filename))
        if not file_path.startswith(base_dir + os.sep):  # pragma: no cover
            logger.warning(f'Attempted path traversal attack: {file_path}')
            return jsonify({'error': 'Invalid file path'}), 400

        if image_bytes is None:
            file.save(file_path)
        else:
            with open(file_path, 'wb') as handle:
                handle.write(image_bytes)

        attachment = observation_sessions.add_attachment(
            user.user_id, session_id, unique_filename, original_filename, file.mimetype or ''
        )
        if not attachment:
            # Session vanished between the check above and the save (race) or the
            # write failed - don't leave an orphaned file behind.
            try:
                os.remove(file_path)
            except OSError:
                # Best-effort cleanup; the 500 below is returned either way.
                pass
            return jsonify({'error': 'Failed to attach file'}), 500

        return jsonify({'status': 'success', 'data': attachment}), 201
    except Exception as error:
        logger.error(f'Error uploading attachment for observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


def _attachment_download_name(attachment: Dict) -> str:
    """The filename a browser should save this attachment as: the custom display name
    (if the user set one) with the real extension re-attached when missing, else the
    original upload filename - never the regenerated on-disk `{uuid}.{ext}` name."""
    original_name = attachment.get('original_name') or attachment.get('filename') or 'attachment'
    display_name = (attachment.get('display_name') or '').strip()
    if not display_name:
        return original_name

    extension = original_name.rsplit('.', 1)[1] if '.' in original_name else None
    if extension and not display_name.lower().endswith(f'.{extension.lower()}'):
        return f'{display_name}.{extension}'
    return display_name


@observation_sessions_bp.route('/api/observation-sessions/attachments/<filename>', methods=['GET'])
@login_required
def get_observation_session_attachment(filename):
    """Serve an attachment file - ownership-checked (does this filename belong to one
    of the caller's own sessions), mirroring astrodex.py's can_user_view_image() but
    simplified to plain ownership since sessions (unlike Astrodex) are never shared."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        owned_attachment = next(
            (
                attachment
                for session in observation_sessions.get_user_sessions(user.user_id)
                for attachment in session.get('attachments', []) or []
                if isinstance(attachment, dict) and attachment.get('filename') == filename
            ),
            None,
        )
        if not owned_attachment:
            return jsonify({'error': 'File not accessible'}), 403

        return send_from_directory(
            observation_sessions.attachments_dir(),
            filename,
            download_name=_attachment_download_name(owned_attachment),
        )
    except Exception as error:
        logger.error(f'Error serving observation session attachment {filename}: {error}')
        return jsonify({'error': 'File not found'}), 404


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/attachments/<attachment_id>', methods=['PUT'])
@user_required
def rename_observation_session_attachment(session_id, attachment_id):
    """Set or clear an attachment's custom display name - never touches the file itself
    or its storage filename, only what the UI shows and what a download is named."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = request.get_json(silent=True) or {}
        attachment = observation_sessions.rename_attachment(
            user.user_id, session_id, attachment_id, payload.get('name')
        )
        if not attachment:
            return jsonify({'error': 'Attachment not found'}), 404

        return jsonify({'status': 'success', 'data': attachment})
    except Exception as error:
        logger.error(f'Error renaming attachment {attachment_id} of observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/attachments/<attachment_id>', methods=['DELETE'])
@user_required
def delete_observation_session_attachment(session_id, attachment_id):
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not observation_sessions.delete_attachment(user.user_id, session_id, attachment_id):
            return jsonify({'error': 'Attachment not found'}), 404

        return jsonify({'status': 'success', 'data': {'id': attachment_id}})
    except Exception as error:
        logger.error(f'Error deleting attachment {attachment_id} from observation session {session_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


def _resolve_entry_image_path(user, entry: Dict) -> Optional[str]:
    """Absolute path to an entry's attached Astrodex photo, or None when it has no photo,
    the linked item/picture no longer resolves, or the file is missing on disk.

    ``observation/observation_sessions.py`` never imports astrodex (see its module
    docstring), so this resolution - the only place a PDF page needs the actual image
    bytes - lives here, exactly like the astrodex-picture attach route above.
    """
    item_id = entry.get('astrodex_item_id')
    picture_id = entry.get('astrodex_picture_id')
    if not item_id or not picture_id:
        return None

    item = astrodex.get_astrodex_item(user.user_id, item_id)
    if not item:
        return None
    picture = next(
        (pic for pic in item.get('pictures', []) if isinstance(pic, dict) and pic.get('id') == picture_id), None
    )
    filename = (picture or {}).get('filename')
    if not filename:
        return None

    base_dir = os.path.realpath(astrodex.ASTRODEX_IMAGES_DIR)
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not file_path.startswith(base_dir + os.sep) or not os.path.isfile(file_path):
        return None
    return file_path


def _collect_image_paths(user, sessions: List[Dict]) -> Dict[str, str]:
    """entry id -> resolved image path, across every entry of every given session."""
    image_paths: Dict[str, str] = {}
    for session in sessions:
        for entry in session.get('entries', []):
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get('id')
            if not entry_id:
                continue
            path = _resolve_entry_image_path(user, entry)
            if path:
                image_paths[entry_id] = path
    return image_paths


def _session_overlaps_date_range(session: Dict, from_date: Optional[str], to_date: Optional[str]) -> bool:
    """True when *any* of the session's nights falls within [from_date, to_date]
    (either bound omitted = open-ended). A multi-night trip straddling a filter
    boundary still matches - the PDF renders every one of its nights regardless, this
    only decides whether the session as a whole is included."""
    for night in session.get('nights', []) or []:
        if not isinstance(night, dict):
            continue
        night_date = str(night.get('date') or '')
        if from_date and night_date < from_date:
            continue
        if to_date and night_date > to_date:
            continue
        return True
    return False


@observation_sessions_bp.route('/api/observation-sessions/<session_id>/export.pdf', methods=['GET'])
@login_required
def export_observation_session_pdf(session_id):
    """Export one session as a print-friendly PDF (common info + every logged target,
    with its attached photo when there is one)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        session = observation_sessions.get_session(user.user_id, session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        i18n = I18nManager(_resolve_requested_language())
        image_paths = _collect_image_paths(user, [session])
        buffer = observation_sessions.generate_session_pdf(session, image_paths, i18n)

        pdf_date = (observation_sessions.session_date_range(session)[0] or 'unknown').replace('-', '')
        return send_file(
            buffer, as_attachment=True, mimetype='application/pdf', download_name=f'observation-log_{pdf_date}.pdf'
        )
    except Exception as error:
        logger.error(f'Error exporting observation session {session_id} to PDF: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@observation_sessions_bp.route('/api/observation-sessions/export.pdf', methods=['GET'])
@login_required
def export_observation_sessions_pdf():
    """Export every own session in an optional date range as one PDF: a cover page, an
    aggregate summary table, then each session in full - oldest-to-newest by default."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        from_date = (request.args.get('from_date') or '').strip() or None
        to_date = (request.args.get('to_date') or '').strip() or None
        order = 'desc' if request.args.get('order') == 'desc' else 'asc'

        sessions = observation_sessions.get_user_sessions(user.user_id)
        if from_date or to_date:
            sessions = [session for session in sessions if _session_overlaps_date_range(session, from_date, to_date)]

        i18n = I18nManager(_resolve_requested_language())
        image_paths = _collect_image_paths(user, sessions)
        buffer = observation_sessions.generate_sessions_pdf(
            sessions, image_paths, i18n, from_date=from_date, to_date=to_date, order=order
        )

        if from_date or to_date:
            range_part = re.sub(r'[^\w\-]', '', f"{from_date or 'start'}_{to_date or 'end'}")
            pdf_name = f'observation-log_{range_part}.pdf'
        else:
            pdf_name = 'observation-log_all.pdf'

        return send_file(buffer, as_attachment=True, mimetype='application/pdf', download_name=pdf_name)
    except Exception as error:
        logger.error(f'Error exporting observation sessions to PDF: {error}')
        return jsonify({'error': 'Internal server error'}), 500
