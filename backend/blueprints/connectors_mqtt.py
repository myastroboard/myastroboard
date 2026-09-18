"""MQTT / Home Assistant connector Blueprint. Routes: /api/connectors/mqtt/*

Backed by connectors/mqtt_connector.py (declaration + probe) and
connectors/mqtt_publisher.py (the background publisher). The registry listing and the
config save are the shared routes in blueprints/connectors.py.

Every route here is admin-only, unlike the AllSky / MyAstroShine probes: a broker probe
carries credentials, and only an admin can save the connector anyway.
"""

from flask import Blueprint, jsonify, request

from connectors.mqtt_connector import MqttConnector
from utils.auth import admin_required, login_required
from utils.connector_secrets import merge_secrets
from utils.logging_config import get_logger
from utils.repo_config import load_config, save_config

logger = get_logger(__name__)

connectors_mqtt_bp = Blueprint('connectors_mqtt', __name__)


def _saved_connector() -> MqttConnector:
    """The connector built from the saved config block plus its sidecar credentials."""
    config = load_config()
    block = config.get('connectors', {}).get('mqtt', {}) or {}
    return MqttConnector(merge_secrets(MqttConnector.name, block, MqttConnector.SECRET_FIELDS))


def _is_masked_or_blank(value: str) -> bool:
    return not value or value.startswith('****')


@connectors_mqtt_bp.route('/api/connectors/mqtt/health', methods=['GET', 'POST'])
@admin_required
def mqtt_health_api():
    """Connect to the broker once and report the outcome.

    POST ``{"url", "username"?, "password"?, "tls_insecure"?}`` - probe the broker as typed in
    the card, before saving. A blank or still-masked password is replaced by the stored one
    **only when the URL is the saved one**: the stored credential is never sent to a host the
    caller just typed.

    GET - probe the saved configuration; also reports each module's toggle.

    A failed probe is a 200 with ``reachable: false`` and an ``error`` string the card can show;
    400 is reserved for a missing URL.
    """
    try:
        connector = _saved_connector()
        if request.method == 'GET':
            return jsonify(connector.health_check())

        data = request.get_json(silent=True) or {}
        url = str(data.get('url') or '').strip().rstrip('/')
        if not url:
            return jsonify({'reachable': False, 'modules': {}, 'error': 'url required'}), 400

        username = str(data.get('username') or '').strip()
        password = str(data.get('password') or '').strip()
        if _is_masked_or_blank(password):
            password = str(connector.config.get('password') or '') if url == connector.base_url else ''
        tls_insecure = data.get('tls_insecure')
        if tls_insecure is None:
            tls_insecure = connector.tls_insecure()

        result = connector.probe(url=url, username=username, password=password, tls_insecure=bool(tls_insecure))
        payload = {'reachable': bool(result['reachable']), 'modules': {}}
        if result.get('error'):
            payload['error'] = result['error']
        return jsonify(payload)
    except Exception as exc:
        logger.error(f"Error probing MQTT broker: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@connectors_mqtt_bp.route('/api/connectors/mqtt/status', methods=['GET'])
@login_required
def mqtt_status_api():
    """What the publisher is doing right now: connection, last publish, published devices.

    Read from the status file the publisher thread writes each cycle, so it works from any
    gunicorn worker, not only the one owning the thread.
    """
    try:
        from connectors import mqtt_publisher

        return jsonify(mqtt_publisher.read_status())
    except Exception as exc:
        logger.error(f"Error reading MQTT publisher status: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@connectors_mqtt_bp.route('/api/connectors/mqtt/publish', methods=['POST'])
@admin_required
def mqtt_publish_now_api():
    """Ask the publisher for a full republish (discovery + every state) on its next tick."""
    try:
        from connectors import mqtt_publisher

        if not mqtt_publisher.request_action('publish'):
            return jsonify({'error': 'Could not signal the publisher'}), 500
        return jsonify({'status': 'requested', 'action': 'publish'})
    except Exception as exc:
        logger.error(f"Error requesting MQTT publish: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@connectors_mqtt_bp.route('/api/connectors/mqtt/remove', methods=['POST'])
@admin_required
def mqtt_remove_api():
    """Switch the connector off and purge every retained discovery / state / image topic.

    Home Assistant drops the devices as the empty retained payloads arrive. The connector is
    disabled in the same call - otherwise the next publish cycle would recreate everything;
    the rest of its configuration (broker, credentials, modules) is kept, so enabling it
    again republishes everything.
    """
    try:
        from connectors import mqtt_publisher

        config = load_config()
        block = config.setdefault('connectors', {}).setdefault('mqtt', {})
        if block.get('enabled'):
            block['enabled'] = False
            if not save_config(config):
                return jsonify({'error': 'Failed to save configuration'}), 500
        if not mqtt_publisher.request_action('remove'):
            return jsonify({'error': 'Could not signal the publisher'}), 500
        return jsonify({'status': 'requested', 'action': 'remove', 'enabled': False})
    except Exception as exc:
        logger.error(f"Error requesting MQTT removal: {exc}")
        return jsonify({'error': 'Internal server error'}), 500
