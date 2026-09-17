"""Session Analytics Blueprint (v1.5). Routes: /api/session-analytics/*, /api/wishlist*

Every route is read-only and strictly self-scoped: a user only ever sees aggregates of
their own Observation Log and their own Astrodex, matching the Observation Log's own
permanently-private access rule.

The aggregation itself lives in ``observation/session_analytics.py``, which is pure and
does no I/O. This module is the layer that loads the user's files, resolves the request's
active location, and hands both to it - the same split
``blueprints/observation_sessions.py`` uses for its own cross-module resolution.

The four surfaces are separate routes rather than one payload so the ephemeris-backed one
does not hold up the three that are instant (see feature.md, decision D6).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify

from observation import astrodex
from observation import catalogue_collection
from observation import observation_sessions
from observation import session_analytics
from observation import target_coordinates
from observation import visibility_calendar
from observation import wishlist
from utils.auth import login_required, user_required, get_current_user
from utils.constants import MAX_WISHLIST_ITEMS
from utils.logging_config import get_logger
from utils.route_helpers import _resolve_active_location

logger = get_logger(__name__)

session_analytics_bp = Blueprint('session_analytics', __name__)

# How far the ?year= selector may reach from the current year. A log cannot predate the
# app by decades and cannot run into the future, so anything outside this is a typo or a
# probe, not a request worth computing.
_YEAR_MIN = 1900
_YEAR_MAX = 2200


def _observer_today(location: Dict[str, Any]) -> Any:
    """Today's date at the active location.

    "This month" has to mean the observer's month: a session logged at 01:30 local on the
    1st belongs to the month the user is in, not the one UTC happens to be in. Falls back
    to the UTC date when the preset carries no usable timezone.
    """
    timezone_name = str((location or {}).get('timezone') or '').strip()
    if timezone_name:
        try:
            return datetime.now(ZoneInfo(timezone_name)).date()
        except Exception:
            logger.debug(f'Unusable timezone on active location: {timezone_name!r}; falling back to UTC')
    return datetime.now(timezone.utc).date()


def _requested_year(default_year: int) -> Optional[int]:
    """Parse ``?year=``, or None when it is present but not a plausible year."""
    raw = request.args.get('year')
    if raw is None or str(raw).strip() == '':
        return default_year
    try:
        year = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return year if _YEAR_MIN <= year <= _YEAR_MAX else None


def _user_sessions(user) -> list:
    """The caller's own sessions. Never another user's - analytics are self-scoped."""
    data = observation_sessions.load_user_sessions(user.user_id, user.username)
    sessions = data.get('sessions', [])
    return sessions if isinstance(sessions, list) else []


def _user_astrodex_items(user) -> list:
    """The caller's own Astrodex items (the gallery half of the sky coverage map)."""
    data = astrodex.load_user_astrodex(user.user_id, user.username)
    items = data.get('items', [])
    return items if isinstance(items, list) else []


@session_analytics_bp.route('/api/session-analytics/summary', methods=['GET'])
@login_required
def get_session_analytics_summary():
    """Integration hours, objects, constellations, equipment usage and top targets."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        location = _resolve_active_location()
        today = _observer_today(location)
        year = _requested_year(today.year)
        if year is None:
            return jsonify({'error': 'Invalid year'}), 400

        summary = session_analytics.build_summary(
            _user_sessions(user),
            today,
            astrodex_item_count=len(_user_astrodex_items(user)),
            year=year,
        )
        summary['location_id'] = location.get('id')
        summary['today'] = today.isoformat()
        return jsonify(summary)
    except Exception as error:
        logger.error(f'Error building session analytics summary: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/session-analytics/sky-coverage', methods=['GET'])
@login_required
def get_session_analytics_sky_coverage():
    """Every captured object placed on an RA/Dec grid, plus what could not be placed."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        location = _resolve_active_location()
        coverage = session_analytics.build_sky_coverage(
            _user_sessions(user),
            _user_astrodex_items(user),
            latitude=location.get('latitude'),
        )
        coverage['location_id'] = location.get('id')
        coverage['location_name'] = location.get('name')
        return jsonify(coverage)
    except Exception as error:
        logger.error(f'Error building session analytics sky coverage: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/session-analytics/conditions', methods=['GET'])
@login_required
def get_session_analytics_conditions():
    """Rated entries joined to their night's seeing, transparency, SQM and moon phase."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        return jsonify(session_analytics.build_conditions(_user_sessions(user)))
    except Exception as error:
        logger.error(f'Error building session analytics conditions: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/session-analytics/best-months', methods=['GET'])
@login_required
def get_session_analytics_best_months():
    """Dark hours available per month at the active location, plus what the user logged.

    Two clearly separate series, never merged: the astronomical budget the site offers
    (computed live from the ephemeris) and the hours the user actually recorded. This is
    deliberately **not** a weather statistic - MyAstroBoard stores no historical weather,
    so it never claims to say when the sky is clear (see docs/SESSION_ANALYTICS.md).
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        location = _resolve_active_location()
        today = _observer_today(location)
        year = _requested_year(today.year)
        if year is None:
            return jsonify({'error': 'Invalid year'}), 400

        try:
            astronomical = visibility_calendar.dark_hours_by_month(location, year)
        except Exception as error:
            # An ephemeris failure must not take the whole dashboard down: the personal
            # half still renders, and the response says the other half is missing.
            logger.error(f'Could not compute dark hours for location {location.get("id")}: {error}')
            astronomical = []

        return jsonify(
            {
                'year': year,
                'location_id': location.get('id'),
                'location_name': location.get('name'),
                'astronomical': astronomical,
                'astronomical_available': bool(astronomical),
                'logged': session_analytics.build_logged_months(_user_sessions(user)),
            }
        )
    except Exception as error:
        logger.error(f'Error building session analytics best months: {error}')
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------


def _captured_index(user) -> set:
    """Identifiers of everything the user has already captured.

    Derived on every read, never stored (see ``observation/wishlist.py``). Two sources,
    both resolved here rather than inside the wishlist module, which must not depend on
    the Observation Log or Astrodex:

    * Observation Log entries carrying real capture evidence - the authoritative record;
    * Astrodex items, which also cover objects added straight to the gallery.
    """
    keys = []
    names = []

    for _session, _night, entry in session_analytics.iter_entries(_user_sessions(user)):
        if not session_analytics.entry_is_captured(entry):
            continue
        keys.append(session_analytics.object_key(entry))
        names.append(str(entry.get('name') or ''))
        aliases = entry.get('catalogue_aliases')
        if isinstance(aliases, dict):
            names.extend(str(value) for value in aliases.values())

    astrodex_items = _user_astrodex_items(user)
    # build_astrodex_index() keys every normalized name an item is known by, including
    # the identifier extracted from a display label such as "M31 - Andromeda Galaxy".
    names.extend(catalogue_collection.build_astrodex_index(astrodex_items).keys())
    for item in astrodex_items:
        if not isinstance(item, dict):
            continue
        group_id = target_coordinates.resolve_target(item.get('name'), item.get('catalogue'))['group_id']
        if group_id:
            keys.append(group_id)

    return wishlist.build_captured_index(keys, names)


def _request_flag(name: str, default: bool = True) -> bool:
    """Read a 0/1 query flag, keeping *default* when it is absent or unparseable."""
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    return str(raw).strip().lower() not in ('0', 'false', 'no')


def _attach_visibility(items, location) -> None:
    """Fold every wishlist item through one shared night grid per sampled night.

    The expensive part of a visibility sample is the Sun/Moon grid, which is identical for
    every target on a given night, so a 500-item wishlist costs the same few grids as a
    single object would (see observation/visibility_calendar.next_visibility_batch).
    Failure is non-fatal: the list still renders, the visibility cells just stay empty.
    """
    if not items:
        return
    try:
        rows = visibility_calendar.next_visibility_batch(items, location)
    except Exception as error:
        logger.error(f'Could not compute wishlist visibility: {error}')
        return
    for item, row in zip(items, rows):
        item.update(row)


@session_analytics_bp.route('/api/wishlist', methods=['GET'])
@login_required
def list_wishlist():
    """The user's wishlist, with derived captured state and progress counters."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = wishlist.load_user_wishlist(user.user_id, user.username)
        annotated = wishlist.annotate_captured(data['items'], _captured_index(user))
        sort = str(request.args.get('sort') or 'visibility').strip().lower()

        location = _resolve_active_location()
        with_visibility = _request_flag('visibility', default=True)
        if with_visibility:
            _attach_visibility(annotated, location)

        return jsonify(
            {
                'items': wishlist.sort_items(annotated, sort),
                'progress': wishlist.progress(annotated),
                'max_items': MAX_WISHLIST_ITEMS,
                'location_id': location.get('id'),
                'location_name': location.get('name'),
                'visibility_included': with_visibility,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as error:
        logger.error(f'Error listing wishlist: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/wishlist', methods=['POST'])
@user_required
def add_to_wishlist():
    """Add one or more targets. The body is always a targets list, length 1 or more."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = request.get_json(silent=True) or {}
        targets = payload.get('targets')
        if not isinstance(targets, list) or not targets:
            return jsonify({'error': 'A non-empty targets list is required'}), 400
        if len(targets) > MAX_WISHLIST_ITEMS:
            return jsonify({'error': 'Too many targets in one request'}), 400

        report = wishlist.add_targets(user.user_id, user.username, targets)
        if not report['saved']:
            return jsonify({'error': 'Failed to save wishlist'}), 500
        if not report['added'] and report['skipped_invalid'] and not report['skipped_duplicates']:
            return jsonify({'error': 'No valid target in request'}), 400

        return jsonify({'status': 'success', 'data': report}), 201
    except Exception as error:
        logger.error(f'Error adding to wishlist: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/wishlist/<item_id>', methods=['PATCH'])
@user_required
def update_wishlist_item(item_id):
    """Update one item's priority or notes."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = request.get_json(silent=True) or {}
        if not any(field in payload for field in wishlist.UPDATABLE_FIELDS):
            return jsonify({'error': 'Nothing to update'}), 400

        updated = wishlist.update_item(user.user_id, item_id, payload)
        if not updated:
            return jsonify({'error': 'Wishlist item not found or invalid update'}), 404
        return jsonify({'status': 'success', 'data': updated})
    except Exception as error:
        logger.error(f'Error updating wishlist item {item_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/wishlist/<item_id>', methods=['DELETE'])
@user_required
def delete_wishlist_item(item_id):
    """Remove one item from the wishlist."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not wishlist.delete_item(user.user_id, item_id):
            return jsonify({'error': 'Wishlist item not found'}), 404
        return jsonify({'status': 'success'})
    except Exception as error:
        logger.error(f'Error deleting wishlist item {item_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@session_analytics_bp.route('/api/wishlist/archive-captured', methods=['POST'])
@user_required
def archive_captured_wishlist_items():
    """Remove every item currently derived as captured.

    Captured items stay on the list by default so the progress counter keeps its
    denominator; this is the explicit opt-in for the user who wants them gone.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = wishlist.load_user_wishlist(user.user_id, user.username)
        annotated = wishlist.annotate_captured(data['items'], _captured_index(user))
        captured_ids = [item['id'] for item in annotated if item.get('captured')]
        removed = wishlist.remove_items(user.user_id, captured_ids)
        return jsonify({'status': 'success', 'removed': removed})
    except Exception as error:
        logger.error(f'Error archiving captured wishlist items: {error}')
        return jsonify({'error': 'Internal server error'}), 500
