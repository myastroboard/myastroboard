"""Profile and Community Blueprint. Routes: /api/profile*, /api/users/<id>/avatar, /api/community/*

- ``/api/profile`` is self-service: the caller's display name, bio, avatar and Community
  choices. It works even when the admin turned the Community off, since the display name
  and avatar are used everywhere a member is named.
- ``/api/community/*`` is the Community tab: the member directory, one member's profile,
  the activity feed and the "together" totals. Only members who joined are listed, and only
  the blocks they show leave their account (see ``community/members.py``). The whole tab
  answers 404 when the admin turned it off.

Nothing here ranks members: the directory is alphabetical, the feed chronological.
"""

import time
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file

from blueprints.progress import _location_bortle
from blueprints.session_analytics import _observer_today
from community import activity, members
from db import users_store
from observation import achievements
from utils import demo_mode as _demo_mode
from utils import user_identity
from utils.auth import admin_required, get_current_user, login_required, user_manager
from utils.logging_config import get_logger
from utils.repo_config import load_config
from utils.route_helpers import _resolve_active_location

logger = get_logger(__name__)

community_bp = Blueprint('community', __name__)

_activity_cache = activity.TtlCache(ttl=60.0)


def clear_caches() -> None:
    """Drop the cached Community payloads (tests, and after a profile change)."""
    _activity_cache.clear()


def _own_profile_payload(user) -> dict[str, Any]:
    config = load_config()
    return {
        'username': user.username,
        'profile': user_identity.sanitize_profile(user.profile),
        'identity': user_identity.public_identity(user),
        'community_enabled': user_identity.community_enabled(config),
        # In private Astrodex mode no picture is ever shown to another member
        'pictures_shared': _pictures_shared(config),
        'limits': {
            'display_name': user_identity.DISPLAY_NAME_MAX_LENGTH,
            'bio': user_identity.BIO_MAX_LENGTH,
            'avatar_bytes': user_identity.AVATAR_MAX_UPLOAD_BYTES,
        },
    }


def _profile_error(error: user_identity.ProfileError):
    return jsonify({'error': str(error), 'error_key': error.key}), 400


# ---------------------------------------------------------------------------
# Self-service profile
# ---------------------------------------------------------------------------


@community_bp.route('/api/profile', methods=['GET'])
@login_required
def get_own_profile():
    """The caller's profile, as stored, with the identity the others see."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        return jsonify(_own_profile_payload(user))
    except Exception as error:
        logger.error(f'Error reading the profile: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/profile', methods=['PUT'])
@login_required
def update_own_profile():
    """Change the caller's display name, bio or Community choices (partial update)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': 'A JSON object is required', 'error_key': 'profile.error_invalid'}), 400
        updates = {key: payload[key] for key in ('display_name', 'bio', 'community') if key in payload}
        user_manager.update_user_profile(user.user_id, updates)
        clear_caches()
        return jsonify({'status': 'success', **_own_profile_payload(user_manager.get_user_by_id(user.user_id))})
    except user_identity.ProfileError as error:
        return _profile_error(error)
    except Exception as error:
        logger.error(f'Error updating the profile: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/profile/avatar', methods=['POST'])
@login_required
def upload_own_avatar():
    """Replace the caller's avatar (multipart ``file``): cropped square, re-encoded, no metadata."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        upload = request.files.get('file')
        if upload is None or not upload.filename:
            return jsonify({'error': 'No file provided', 'error_key': 'profile.error_avatar_invalid'}), 400
        extension = upload.filename.rsplit('.', 1)[-1].lower() if '.' in upload.filename else ''
        if extension not in user_identity.AVATAR_EXTENSIONS:
            return jsonify({'error': 'Invalid file type', 'error_key': 'profile.error_avatar_invalid'}), 400
        data = upload.read(user_identity.AVATAR_MAX_UPLOAD_BYTES + 1)
        processed = user_identity.process_avatar(data)
        filename = user_identity.store_avatar(user.user_id, processed)
        previous = user_manager.set_user_avatar(user.user_id, filename)
        if previous and previous != filename:
            user_identity.remove_avatar_file(previous)
        clear_caches()
        logger.info(f'Avatar updated for user {user.username}')
        return jsonify({'status': 'success', **_own_profile_payload(user_manager.get_user_by_id(user.user_id))})
    except user_identity.ProfileError as error:
        logger.warning(f'Avatar upload rejected for user {getattr(get_current_user(), "username", "?")}: {error}')
        return _profile_error(error)
    except Exception as error:
        logger.error(f'Error storing the avatar: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/profile/avatar', methods=['DELETE'])
@login_required
def delete_own_avatar():
    """Remove the caller's avatar; the initials picture takes its place."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        previous = user_manager.set_user_avatar(user.user_id, None)
        user_identity.remove_avatar_file(previous)
        clear_caches()
        return jsonify({'status': 'success', **_own_profile_payload(user_manager.get_user_by_id(user.user_id))})
    except Exception as error:
        logger.error(f'Error removing the avatar: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/users/<user_id>/avatar', methods=['GET'])
@login_required
def get_user_avatar(user_id):
    """A member's avatar: the uploaded picture, else a generated initials picture.

    Any signed-in member may load it: it stands next to a name that is already shown to
    them (a shared picture, shared equipment, the Community).
    """
    try:
        user = user_manager.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'Unknown user'}), 404
        # A versioned address (?v=, from avatar_url) never changes content: cache it long.
        # A bare one (built from a user id alone) may, so only briefly.
        max_age = 86400 if request.args.get('v') else 300
        avatar = user.profile.get('avatar') or {}
        path = user_identity.avatar_path(avatar.get('filename', '')) if avatar else None
        if path:
            try:
                response = send_file(path, mimetype='image/webp', max_age=max_age)
                response.headers['X-Content-Type-Options'] = 'nosniff'
                return response
            except FileNotFoundError:
                logger.warning(f'Avatar file of user {user.username} is missing; serving initials')
        response = Response(user_identity.initials_svg(user), mimetype='image/svg+xml')
        response.headers['Cache-Control'] = f'private, max-age={max_age}'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'"
        return response
    except Exception as error:
        logger.error(f'Error serving an avatar: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/users/<user_id>/profile', methods=['DELETE'])
@admin_required
def admin_reset_profile(user_id):
    """Moderation: clear a member's display name, bio and avatar."""
    try:
        if not user_manager.get_user_by_id(user_id):
            return jsonify({'error': 'Unknown user'}), 404
        previous = user_manager.reset_user_profile(user_id)
        user_identity.remove_avatar_file(previous)
        clear_caches()
        return jsonify({'status': 'success'})
    except Exception as error:
        logger.error(f'Error resetting a profile: {error}')
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Community tab
# ---------------------------------------------------------------------------


def _community_disabled():
    return jsonify({'error': 'Community is turned off', 'error_key': 'community.disabled'}), 404


def _pictures_shared(config: dict[str, Any]) -> bool:
    """Pictures leave a member's Astrodex only when the instance shares Astrodex pictures."""
    return not bool((config.get('astrodex') or {}).get('private', False))


def _member_data(user, location_bortle: dict[str, Any]) -> dict[str, Any]:
    data = members.load_member_data(user, location_bortle)
    data['badges'] = (
        members.earned_badges(data['facts'], achievements.catalogue_totals()) if members.badges_allowed(user) else []
    )
    return data


def _community_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    """The feed and the totals for every listed member, cached for a minute."""
    today = _observer_today(_resolve_active_location())
    pictures_shared = _pictures_shared(config)
    key = (users_store.users_revision(), today.isoformat(), pictures_shared)
    now = time.monotonic()
    cached = _activity_cache.get(key, now)
    if cached is not None:
        return cached
    location_bortle = _location_bortle()
    listed = [user for user in user_manager.all_users() if user_identity.is_listed(user)]
    member_data = [_member_data(user, location_bortle) for user in listed]
    totals = achievements.catalogue_totals()
    snapshot = {
        'today': today.isoformat(),
        'feed': activity.build_feed(member_data, today, pictures_shared=pictures_shared),
        'together': activity.build_together(member_data, totals),
    }
    _activity_cache.put(key, snapshot, now)
    return snapshot


@community_bp.route('/api/community/members', methods=['GET'])
@login_required
def list_members():
    """Members who joined, alphabetically; plus whether the caller joined."""
    try:
        config = load_config()
        if not user_identity.community_enabled(config):
            return _community_disabled()
        viewer = get_current_user()
        if not viewer:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        return jsonify(
            {
                'members': members.directory(user_manager.all_users(), viewer.user_id),
                'you_listed': user_identity.is_listed(viewer),
                'demo_mode': _demo_mode.is_demo_session(),
            }
        )
    except Exception as error:
        logger.error(f'Error listing the Community members: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@community_bp.route('/api/community/members/<user_id>', methods=['GET'])
@login_required
def get_member_profile(user_id):
    """One member's profile, with only the blocks they show (404 for a member not listed).

    The caller may always open their own, to preview what the others see.
    """
    try:
        config = load_config()
        if not user_identity.community_enabled(config):
            return _community_disabled()
        viewer = get_current_user()
        if not viewer:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        user = user_manager.get_user_by_id(user_id)
        if not user or not members.can_view_profile(user, viewer.user_id):
            return jsonify({'error': 'Profile not found', 'error_key': 'community.profile_not_found'}), 404

        location_bortle = _location_bortle()
        pictures_shared = _pictures_shared(config)
        today = _observer_today(_resolve_active_location())
        cache: dict[str, Any] = {}

        def loader(member):
            if 'data' not in cache:
                cache['data'] = _member_data(member, location_bortle)
            return cache['data']

        profile = user_identity.sanitize_profile(user.profile)
        own_activity = None
        if profile['community'].get('show_activity'):
            # The preview shows the blocks as they will look once listed.
            previewed = _as_listed(user)
            own_activity = activity.build_feed(
                [loader(previewed)], today, pictures_shared=pictures_shared, limit=activity.PROFILE_FEED_LIMIT
            )
        payload = members.build_profile(
            _as_listed(user),
            loader,
            achievements.catalogue_totals(),
            pictures_shared=pictures_shared,
            activity=own_activity,
        )
        payload['listed'] = user_identity.is_listed(user)
        payload['is_you'] = str(user.user_id) == viewer.user_id
        payload['today'] = today.isoformat()
        return jsonify(payload)
    except Exception as error:
        logger.error(f'Error building a Community profile: {error}')
        return jsonify({'error': 'Internal server error'}), 500


class _ListedView:
    """A read-only stand-in of a user whose profile reads as listed (the owner's preview).

    For a member who is listed it changes nothing; for the owner previewing an unlisted
    profile, it renders the blocks exactly as the others would see them after joining.
    """

    def __init__(self, user):
        self._user = user
        profile = user_identity.sanitize_profile(user.profile)
        profile['community']['listed'] = True
        self.profile = profile

    def __getattr__(self, name):
        return getattr(self._user, name)


def _as_listed(user):
    return _ListedView(user)


@community_bp.route('/api/community/activity', methods=['GET'])
@login_required
def get_community_activity():
    """The activity feed (newest day first) and the "together" totals."""
    try:
        config = load_config()
        if not user_identity.community_enabled(config):
            return _community_disabled()
        viewer = get_current_user()
        if not viewer:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        snapshot = _community_snapshot(config)
        return jsonify({**snapshot, 'you_listed': user_identity.is_listed(viewer)})
    except Exception as error:
        logger.error(f'Error building the Community activity: {error}')
        return jsonify({'error': 'Internal server error'}), 500
