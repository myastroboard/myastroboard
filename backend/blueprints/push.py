"""Web Push notifications Blueprint. Routes: /api/push/*"""

from flask import Blueprint, request, jsonify

from utils.auth import user_manager, login_required, get_current_user
from utils.logging_config import get_logger

logger = get_logger(__name__)

push_bp = Blueprint('push', __name__)


@push_bp.route('/api/push/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    """Return the VAPID public key needed by the browser to subscribe."""
    try:
        from utils.push_manager import get_vapid_public_key as _get_key

        return jsonify({'public_key': _get_key()})
    except Exception as e:
        logger.error(f"Failed to get VAPID public key: {e}")
        return jsonify({'error': 'Push not available'}), 503


@push_bp.route('/api/push/vapid-config-status', methods=['GET'])
@login_required
def get_vapid_config_status():
    """Return whether the VAPID contact email is properly configured."""
    try:
        from utils.push_manager import get_vapid_contact_status

        return jsonify(get_vapid_contact_status())
    except Exception as e:
        logger.error(f"Failed to get VAPID config status: {e}")
        return jsonify({'ok': False, 'reason': 'error'}), 500


@push_bp.route('/api/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    """Store a push subscription for the current user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        data = request.json or {}
        subscription = data.get('subscription')
        if not isinstance(subscription, dict) or not subscription.get('endpoint'):
            return jsonify({'error': 'Invalid subscription object'}), 400

        endpoint = subscription['endpoint']
        existing = current_user.push_subscriptions
        if not any(s.get('endpoint') == endpoint for s in existing):
            from datetime import datetime as _dt

            existing.append(
                {
                    'endpoint': endpoint,
                    'keys': subscription.get('keys', {}),
                    'created_at': _dt.now().isoformat(),
                }
            )
            user_manager.save_users()
            logger.info(f"Push subscription added for user {current_user.username}")

        return jsonify({'status': 'subscribed'})
    except Exception as e:
        logger.error(f"Error storing push subscription: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/api/push/subscriptions', methods=['GET'])
@login_required
def push_list_subscriptions():
    """List push subscriptions for the current user (safe summary, no full endpoints)."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        def _provider(endpoint):
            from urllib.parse import urlparse

            try:
                host = urlparse(endpoint).hostname or ''
            except Exception:  # pragma: no cover  # urlparse is robust; can't raise on string input
                host = ''
            if host == 'web.push.apple.com' or host.endswith('.push.apple.com'):
                return 'apple'
            if host == 'fcm.googleapis.com' or host.endswith('.googleapis.com'):
                return 'google'
            if host == 'push.services.mozilla.com' or host.endswith('.mozilla.com'):
                return 'mozilla'
            return 'other'

        subs = [
            {
                'index': i,
                'provider': _provider(s.get('endpoint', '')),
                'created_at': s.get('created_at', ''),
                'endpoint_tail': s.get('endpoint', '')[-20:],
            }
            for i, s in enumerate(current_user.push_subscriptions)
        ]
        return jsonify({'subscriptions': subs})
    except Exception as e:
        logger.error(f"Error listing push subscriptions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/api/push/subscriptions', methods=['DELETE'])
@login_required
def push_delete_all_subscriptions():
    """Remove push subscription(s) for the current user.

    With no body (or no ``index``), removes all subscriptions. With a JSON
    body ``{"index": N}`` (matching the ``index`` returned by the GET list),
    removes only that one subscription.
    """
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        data = request.get_json(silent=True) or {}
        index = data.get('index')

        if index is None:
            count = len(current_user.push_subscriptions)
            current_user.push_subscriptions = []
            user_manager.save_users()
            logger.info(f"All {count} push subscription(s) removed for {current_user.username}")
            return jsonify({'removed': count})

        if not isinstance(index, int) or not (0 <= index < len(current_user.push_subscriptions)):
            return jsonify({'error': 'Invalid subscription index'}), 400

        del current_user.push_subscriptions[index]
        user_manager.save_users()
        logger.info(f"Push subscription at index {index} removed for {current_user.username}")
        return jsonify({'removed': 1})
    except Exception as e:
        logger.error(f"Error removing push subscriptions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/api/push/test/<trigger_id>', methods=['POST'])
@login_required
def push_test_trigger(trigger_id):
    """Fire a realistic test push for a specific trigger (N1–N7), bypassing condition checks."""
    _TRIGGER_PAYLOADS = {
        'N1': ('push_n1_title', 'push_n1_body', {'minutes': 14}, '/#astrodex/plan-my-night', 'normal'),
        'N2': ('push_n2_title', 'push_n2_body', {'name': 'M42', 'minutes': 4}, '/#astrodex/plan-my-night', 'normal'),
        'N3': ('push_n3_title', 'push_n3_solar_body', {'minutes': 8}, '/#spaceflight/iss', 'high'),
        'N4': ('push_n4_title', 'push_n4_body', {'minutes': 28}, '/#forecast-astro/moon', 'normal'),
        'N5': ('push_n5_title', 'push_n5_body', {'minutes': 22}, '/#forecast-astro/sun', 'normal'),
        'N6': (
            'push_n6_title',
            'push_n6_body',
            {'minutes': 18, 'time': '23:45'},
            '/#forecast-astro/astro-weather',
            'normal',
        ),
        'N7': ('push_n7_title', 'push_n7_body', {'kp': '6.3', 'visibility': 'Good'}, '/#forecast-astro/aurora', 'high'),
        'N9': (
            'push_n9_title',
            'push_n9_body',
            {'title': 'Perseids Meteor Shower', 'days': 2},
            '/#forecast-astro/calendar',
            'normal',
        ),
    }
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401
        if trigger_id not in _TRIGGER_PAYLOADS:
            return jsonify({'error': f'Unknown trigger. Valid: {list(_TRIGGER_PAYLOADS)}'}), 400
        if not current_user.push_subscriptions:
            return jsonify({'error': 'No push subscriptions for this user'}), 400

        from utils.push_manager import send_push
        from utils.i18n_utils import get_translated_message

        lang = current_user.preferences.get('language', 'en')

        def t(key, **params):
            return get_translated_message(f'settings.{key}', language=lang, **params)

        title_key, body_key, body_params, url, urgency = _TRIGGER_PAYLOADS[trigger_id]
        payload = {
            'title': t(title_key),
            'body': t(body_key, **body_params),
            'icon': '/static/ico/android/launchericon-192x192.png',
            'badge': '/static/ico/android/launchericon-72x72.png',
            'tag': f'{trigger_id}-test',
            'data': {'url': url},
        }

        n = len(current_user.push_subscriptions)
        delivered = 0
        dead_endpoints = []
        for sub in current_user.push_subscriptions:
            ok = send_push(
                {'endpoint': sub['endpoint'], 'keys': sub.get('keys', {})}, payload, ttl=300, urgency=urgency
            )
            if ok:
                delivered += 1
            else:
                dead_endpoints.append(sub['endpoint'])

        if dead_endpoints:
            current_user.push_subscriptions = [
                s for s in current_user.push_subscriptions if s.get('endpoint') not in dead_endpoints
            ]
            user_manager.save_users()

        logger.info(
            f"Test push [{trigger_id}] for {current_user.username}: {delivered}/{n} delivered — {payload['body']}"
        )
        return jsonify(
            {
                'trigger': trigger_id,
                'delivered': delivered,
                'total': n,
                'title': payload['title'],
                'body': payload['body'],
            }
        )
    except Exception as e:
        logger.error(f"Error sending test push [{trigger_id}]: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/api/push/test', methods=['POST'])
@login_required
def push_test():
    """Send an immediate test push to the current user (all subscriptions)."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401
        if not current_user.push_subscriptions:
            return jsonify({'error': 'No push subscriptions for this user'}), 400

        from utils.push_manager import send_push

        n = len(current_user.push_subscriptions)
        delivered = 0
        dead_endpoints = []
        for sub in current_user.push_subscriptions:
            ok = send_push(
                {'endpoint': sub['endpoint'], 'keys': sub.get('keys', {})},
                {
                    'title': 'MyAstroBoard test',
                    'body': 'Push notifications are working!',
                    'icon': '/static/ico/android/launchericon-192x192.png',
                    'badge': '/static/ico/android/launchericon-72x72.png',
                    'tag': 'push-test',
                    'data': {'url': '/#my-settings/notifications'},
                },
                ttl=60,
                urgency='high',
            )
            if ok:
                delivered += 1
            else:
                dead_endpoints.append(sub['endpoint'])
        if dead_endpoints:
            current_user.push_subscriptions = [
                s for s in current_user.push_subscriptions if s.get('endpoint') not in dead_endpoints
            ]
            user_manager.save_users()
            logger.info(f"Removed {len(dead_endpoints)} dead subscription(s) for {current_user.username}")
        logger.info(f"Test push for {current_user.username}: {delivered}/{n} delivered")
        return jsonify({'delivered': delivered, 'total': n, 'cleaned': len(dead_endpoints)})
    except Exception:
        logger.error("Error sending test push", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/api/push/unsubscribe', methods=['DELETE'])
@login_required
def push_unsubscribe():
    """Remove a push subscription for the current user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        data = request.json or {}
        endpoint = data.get('endpoint')
        if not endpoint:
            return jsonify({'error': 'endpoint is required'}), 400

        before = len(current_user.push_subscriptions)
        current_user.push_subscriptions = [s for s in current_user.push_subscriptions if s.get('endpoint') != endpoint]
        if len(current_user.push_subscriptions) < before:
            user_manager.save_users()
            logger.info(f"Push subscription removed for user {current_user.username}")

        return jsonify({'status': 'unsubscribed'})
    except Exception as e:
        logger.error(f"Error removing push subscription: {e}")
        return jsonify({'error': 'Internal server error'}), 500
