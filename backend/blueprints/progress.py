"""My Progress Blueprint (v1.9). Routes: /api/session-analytics/year-review, /api/achievements*

The year in review and the badges are read-only and strictly self-scoped, like the rest of
Session Analytics: a user only ever sees what their own Observation Log and Astrodex say.
Nothing is stored except two preferences (the badges already pointed out, and the year
whose review highlight was dismissed), which live on the account like every other
preference and so are covered by account erasure and the personal data export.

The aggregation is pure (``observation/achievements.py``, ``observation/year_review.py``);
the ephemeris-backed challenges (``observation/challenges.py``) are a separate route so the
badges, which are instant, never wait for them.
"""

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request

from blueprints.session_analytics import _observer_today, _requested_year, _user_astrodex_items, _user_sessions
from observation import achievement_definitions, achievements, challenges, year_review
from utils import demo_mode as _demo_mode
from utils.auth import get_current_user, login_required, user_manager
from utils.logging_config import get_logger
from utils.repo_config import get_all_locations, load_config
from utils.route_helpers import _resolve_active_location

if TYPE_CHECKING:
    from utils.auth import User

logger = get_logger(__name__)

progress_bp = Blueprint('progress', __name__)

_MISSING_TONIGHT_MAX = 30


def _location_bortle() -> dict[str, Any]:
    """Bortle class per location preset id - sessions store only the preset id."""
    try:
        return {
            str(location.get('id')): location.get('bortle')
            for location in get_all_locations(load_config())
            if location.get('id') is not None and location.get('bortle') is not None
        }
    except Exception as error:
        logger.warning(f'Could not read the location presets for the dark-site badge: {error}')
        return {}


def _user_facts(user: User) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """The caller's sessions, Astrodex items and the progress facts built from both."""
    sessions = _user_sessions(user)
    items = _user_astrodex_items(user)
    facts = achievements.collect_progress(sessions, items, location_bortle=_location_bortle())
    return sessions, items, facts


def _user_preferences(user: User) -> dict[str, Any]:
    preferences = user_manager.get_user_preferences(user.user_id)
    if _demo_mode.is_demo_session():
        preferences = _demo_mode.visitor_preferences(preferences)
    return preferences


@progress_bp.route('/api/session-analytics/year-review', methods=['GET'])
@login_required
def get_year_review():
    """Every screen of one year's review (``?year=``; default: the year just ending).

    Without ``?year=``, January still shows the year that just ended, and a default year
    with no data falls back to the most recent year that has some.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        today = _observer_today(_resolve_active_location())
        default_year = today.year - 1 if today.month == 1 else today.year
        year = _requested_year(default_year)
        if year is None:
            return jsonify({'error': 'Invalid year'}), 400

        sessions, items, facts = _user_facts(user)
        if request.args.get('year') in (None, ''):
            years = year_review.available_years(facts)
            if years and year not in years:
                year = years[0]

        review = year_review.build_year_review(sessions, items, year, facts, achievements.catalogue_totals())
        review['today'] = today.isoformat()
        return jsonify(review)
    except Exception as error:
        logger.error(f'Error building the year in review: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@progress_bp.route('/api/achievements', methods=['GET'])
@login_required
def get_achievements():
    """Every badge with its progress, the next ones within reach, and catalogue counters."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        _sessions, items, facts = _user_facts(user)
        totals = achievements.catalogue_totals()
        badges = achievements.evaluate_badges(facts, totals)
        catalogues = achievements.catalogue_progress(facts, totals, achievement_definitions.BADGE_CATALOGUES)
        for row in catalogues:
            row['pictures'] = achievements.catalogue_pictures(facts, items, row['catalogue'])
        preferences = _user_preferences(user)
        seen = preferences.get('achievements_seen') or []
        summary = achievements.summarize(badges, seen)
        new_ids = set(summary['new_ids'])
        for badge in badges:
            badge['new'] = badge['id'] in new_ids

        return jsonify(
            {
                'enabled': preferences.get('achievements_enabled') is not False,
                'badges': badges,
                'groups': list(achievement_definitions.GROUP_ORDER),
                'next_within_reach': achievements.next_within_reach(badges),
                'catalogues': catalogues,
                'summary': summary,
                'objects_captured': len(facts['captures']),
            }
        )
    except Exception as error:
        logger.error(f'Error building achievements: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@progress_bp.route('/api/achievements/seen', methods=['POST'])
@login_required
def mark_achievements_seen():
    """Remember that the user has seen these earned badges (body ``{"ids": [...]}``).

    Unknown ids are ignored rather than rejected: a badge retired in a later version must
    not make an older open page fail.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = request.get_json(silent=True) or {}
        ids = payload.get('ids')
        if not isinstance(ids, list):
            return jsonify({'error': 'An ids list is required'}), 400
        wanted = {str(badge_id) for badge_id in ids if isinstance(badge_id, str)}
        wanted &= achievement_definitions.BADGE_IDS

        preferences = _user_preferences(user)
        current = [badge_id for badge_id in preferences.get('achievements_seen') or [] if isinstance(badge_id, str)]
        merged = sorted((set(current) & achievement_definitions.BADGE_IDS) | wanted)
        if merged != sorted(current):
            if _demo_mode.is_demo_session():
                _demo_mode.store_session_preferences({'achievements_seen': merged})
            else:
                user_manager.update_user_preferences(user.user_id, {'achievements_seen': merged})
        return jsonify({'status': 'success', 'seen': merged})
    except Exception as error:
        logger.error(f'Error saving the badges seen: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@progress_bp.route('/api/achievements/challenges', methods=['GET'])
@login_required
def get_challenges():
    """Seasonal challenges and the next Messier marathon, for the active location."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        location = _resolve_active_location()
        today = _observer_today(location)
        _sessions, _items, facts = _user_facts(user)
        captured = set(facts['captures'])

        try:
            seasonal = challenges.seasonal_challenges(location, today, captured)
        except Exception as error:
            logger.error(f'Could not compute the seasonal challenges for location {location.get("id")}: {error}')
            seasonal = None
        try:
            marathon = challenges.messier_marathon(location, today, captured)
        except Exception as error:
            logger.error(f'Could not compute the Messier marathon for location {location.get("id")}: {error}')
            marathon = None

        return jsonify(
            {
                'location_id': location.get('id'),
                'location_name': location.get('name'),
                'today': today.isoformat(),
                'seasonal': seasonal,
                'marathon': marathon,
            }
        )
    except Exception as error:
        logger.error(f'Error building challenges: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@progress_bp.route('/api/achievements/missing-tonight', methods=['GET'])
@login_required
def get_missing_tonight():
    """Objects of a badge catalogue not captured yet and observable tonight (``?catalogue=``)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        catalogue = str(request.args.get('catalogue') or '').strip()
        if catalogue not in achievement_definitions.BADGE_CATALOGUES:
            return jsonify({'error': 'Unknown catalogue'}), 400
        try:
            limit = int(request.args.get('limit') or 12)
        except TypeError, ValueError:
            return jsonify({'error': 'Invalid limit'}), 400
        limit = max(1, min(limit, _MISSING_TONIGHT_MAX))

        location = _resolve_active_location()
        today = _observer_today(location)
        _sessions, _items, facts = _user_facts(user)
        targets = challenges.missing_tonight(catalogue, location, today, set(facts['captures']), limit=limit)
        return jsonify(
            {
                'catalogue': catalogue,
                'date': today.isoformat(),
                'location_id': location.get('id'),
                'location_name': location.get('name'),
                'targets': targets,
            }
        )
    except Exception as error:
        logger.error(f'Error listing the missing objects visible tonight: {error}')
        return jsonify({'error': 'Internal server error'}), 500
