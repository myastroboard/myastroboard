"""Member directory and profiles.

A member appears to the others only once they join the Community (``profile.community.listed``)
and only through the blocks they turn on (``user_identity.COMMUNITY_BLOCKS``). Each block is
built from data the member already has - the progress facts of their Observation Log and
Astrodex, their Astrodex pictures, their equipment combinations - and never from anything
more precise: no location, no session notes, no coordinates.

The Observation Log itself stays private. Only figures derived from it (counts, hours,
badges, the day an object was first captured) leave it, and only when the member shows them.
"""

from collections.abc import Callable
from typing import Any

from observation import achievement_definitions, achievements
from utils import user_identity
from utils.logging_config import get_logger

logger = get_logger(__name__)

PROFILE_PICTURES_LIMIT = 12
PROFILE_EQUIPMENT_LIMIT = 12


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ''


def _dicts(values: Any) -> list[dict[str, Any]]:
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


# ---------------------------------------------------------------------------
# Loading one member's data
# ---------------------------------------------------------------------------


def load_member_data(user: Any, location_bortle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sessions, Astrodex items and progress facts of one member (empty on any read error)."""
    from observation import astrodex, observation_sessions

    user_id = str(user.user_id)
    try:
        sessions = observation_sessions.load_user_sessions(user_id, user.username).get('sessions', [])
    except Exception as error:
        logger.warning(f'Community: could not read the sessions of {user.username}: {error}')
        sessions = []
    try:
        items = astrodex.load_user_astrodex(user_id, user.username).get('items', [])
    except Exception as error:
        logger.warning(f'Community: could not read the Astrodex of {user.username}: {error}')
        items = []
    sessions = sessions if isinstance(sessions, list) else []
    items = items if isinstance(items, list) else []
    facts = achievements.collect_progress(sessions, items, location_bortle=location_bortle or {})
    return {'user': user, 'sessions': sessions, 'items': items, 'facts': facts}


def badges_allowed(user: Any) -> bool:
    """Badges are shown only when the member shows them and has not turned badges off."""
    preferences = getattr(user, 'preferences', None) or {}
    return user_identity.shows_block(user, 'badges') and preferences.get('achievements_enabled') is not False


# ---------------------------------------------------------------------------
# Profile blocks
# ---------------------------------------------------------------------------


def stats_block(facts: dict[str, Any], totals: dict[str, int]) -> dict[str, Any]:
    """Headline figures: objects, integration time, nights, constellations, catalogues."""
    captures = list(facts.get('captures', {}).values())
    catalogues = [
        row
        for row in achievements.catalogue_progress(facts, totals, achievement_definitions.BADGE_CATALOGUES)
        if row['captured'] > 0
    ]
    return {
        'objects': len(captures),
        'integration_minutes': round(sum(minutes for _day, minutes, _key in facts.get('integration', [])), 1),
        'nights': len({night.get('date') for night in facts.get('nights', []) if night.get('date')}),
        'constellations': len({capture['constellation'] for capture in captures if capture.get('constellation')}),
        'catalogues': catalogues,
    }


def earned_badges(facts: dict[str, Any], totals: dict[str, int]) -> list[dict[str, Any]]:
    """The member's earned badges, most recent first (the fields the badge texts need)."""
    earned = [badge for badge in achievements.evaluate_badges(facts, totals) if badge.get('earned')]
    earned.sort(key=lambda badge: badge.get('earned_on') or '', reverse=True)
    keep = ('id', 'family', 'group', 'rule', 'icon', 'tier', 'catalogue', 'object_class', 'complete_catalogue')
    return [
        {**{key: badge.get(key) for key in keep}, 'target': badge.get('target'), 'earned_on': badge.get('earned_on')}
        for badge in earned
    ]


def _picture_day(picture: dict[str, Any]) -> str:
    for field in ('date', 'created_at', 'uploaded_at'):
        value = _text(picture.get(field))
        if value:
            return value[:10]
    return ''


def member_pictures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every Astrodex picture of the member, newest first: file name, object, day."""
    pictures = []
    for item in _dicts(items):
        name = _text(item.get('name'))
        for picture in _dicts(item.get('pictures')):
            filename = _text(picture.get('filename'))
            if not filename:
                continue
            pictures.append(
                {
                    'filename': filename,
                    'item_name': name,
                    'date': _picture_day(picture),
                    'is_main': bool(picture.get('is_main')),
                }
            )
    pictures.sort(key=lambda picture: picture['date'], reverse=True)
    return pictures


def equipment_block(user_id: str) -> list[dict[str, Any]]:
    """The member's active combinations: name, telescope and camera names (never settings)."""
    from equipment import equipment_profiles

    try:
        combinations = _dicts(equipment_profiles.load_user_combinations(user_id).get('items'))
        telescopes = {
            _text(item.get('id')): _text(item.get('name'))
            for item in _dicts(equipment_profiles.load_user_telescopes(user_id).get('items'))
        }
        cameras = {
            _text(item.get('id')): _text(item.get('name'))
            for item in _dicts(equipment_profiles.load_user_cameras(user_id).get('items'))
        }
    except Exception as error:
        logger.warning(f'Community: could not read the equipment of {user_id}: {error}')
        return []
    rows = []
    for combination in combinations:
        if combination.get('is_disabled'):
            continue
        rows.append(
            {
                'name': _text(combination.get('name')),
                'telescope': telescopes.get(_text(combination.get('telescope_id'))) or None,
                'camera': cameras.get(_text(combination.get('camera_id'))) or None,
            }
        )
    return rows[:PROFILE_EQUIPMENT_LIMIT]


# ---------------------------------------------------------------------------
# Directory and profile payloads
# ---------------------------------------------------------------------------


def member_summary(user: Any) -> dict[str, Any]:
    """A directory card: identity, bio and membership date. No figures - nothing to compare."""
    profile = user_identity.sanitize_profile(getattr(user, 'profile', None))
    return {
        **user_identity.public_identity(user),
        'bio': profile.get('bio') or '',
        'member_since': _text(getattr(user, 'created_at', ''))[:10] or None,
    }


def directory(users: list[Any], viewer_id: str | None = None) -> list[dict[str, Any]]:
    """Listed members in alphabetical order; the viewer is flagged so the page can say "you"."""
    members = [member_summary(user) for user in users if user_identity.is_listed(user)]
    for member in members:
        member['is_you'] = bool(viewer_id) and member['user_id'] == viewer_id
    members.sort(key=lambda member: (member['display_name'].casefold(), member['user_id'] or ''))
    return members


def can_view_profile(user: Any, viewer_id: str | None) -> bool:
    """Members see listed profiles; everyone may preview their own."""
    return user_identity.is_listed(user) or (bool(viewer_id) and str(user.user_id) == viewer_id)


def build_profile(
    user: Any,
    data_loader: Callable[[Any], dict[str, Any]],
    totals: dict[str, int],
    *,
    pictures_shared: bool,
    activity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The profile as the other members see it: only the blocks the member shows.

    ``pictures_shared`` is the instance's Astrodex sharing (off in private Astrodex mode,
    where no picture is ever shown to another user). ``activity`` is the member's own part
    of the feed, built by the caller.
    """
    profile = user_identity.sanitize_profile(getattr(user, 'profile', None))
    community = profile['community']
    payload: dict[str, Any] = {**member_summary(user), 'listed': bool(community.get('listed')), 'blocks': {}}
    shown = {block: bool(community.get(f'show_{block}')) for block in user_identity.COMMUNITY_BLOCKS}
    preferences = getattr(user, 'preferences', None) or {}
    shown['badges'] = shown['badges'] and preferences.get('achievements_enabled') is not False
    shown['pictures'] = shown['pictures'] and pictures_shared

    needs_data = shown['stats'] or shown['badges'] or shown['pictures']
    data = data_loader(user) if needs_data else {'facts': {}, 'items': []}
    blocks = payload['blocks']
    if shown['stats']:
        blocks['stats'] = stats_block(data['facts'], totals)
    if shown['badges']:
        blocks['badges'] = earned_badges(data['facts'], totals)
    if shown['pictures']:
        blocks['pictures'] = member_pictures(data['items'])[:PROFILE_PICTURES_LIMIT]
    if shown['equipment']:
        blocks['equipment'] = equipment_block(str(user.user_id))
    if shown['activity'] and activity is not None:
        blocks['activity'] = activity
    return payload
