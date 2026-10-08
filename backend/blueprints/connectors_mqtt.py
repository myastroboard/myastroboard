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
from utils.logging_config import get_logger
from utils.mqtt_connections import connection_password, get_connection, overlay_connection
from utils.repo_config import load_config, save_config

logger = get_logger(__name__)

connectors_mqtt_bp = Blueprint('connectors_mqtt', __name__)


def _saved_connector() -> MqttConnector:
    """The connector built from the saved config block and its connection - deliberately secret-free.

    The password never goes into this connector's ``config``: mixing it into the same dict
    that ``base_url``/``client_id``/etc. are read from makes every one of those routine reads
    indistinguishable from a credential to a static analysis, and CodeQL flags it as such (a
    real finding once seen, even though this dict is never logged directly). Callers that need
    the password fetch it separately with ``_saved_password()`` and pass it explicitly.
    """
    config = load_config()
    block = config.get('connectors', {}).get('mqtt', {}) or {}
    return MqttConnector(overlay_connection(block, config, MqttConnector.CONNECTION_FIELD))


def _saved_password() -> str:
    """The password of the connection the saved connector points at."""
    block = load_config().get('connectors', {}).get('mqtt', {}) or {}
    return connection_password(block.get(MqttConnector.CONNECTION_FIELD))


@connectors_mqtt_bp.route('/api/connectors/mqtt/health', methods=['GET', 'POST'])
@admin_required
def mqtt_health_api():
    """Connect to the broker once and report the outcome.

    GET - probe the saved configuration (its connection, with that connection's stored
    credentials); also reports each module's toggle.

    POST ``{"mqtt_connection_id"}`` - probe the connection picked in the card, before saving.
    Testing a broker as typed is the connections' own route (/api/mqtt-connections/health).

    A failed probe is a 200 with ``reachable: false`` and an ``error`` string the card can show;
    400 is reserved for a missing or unknown connection.
    """
    try:
        if request.method == 'GET':
            return jsonify(_saved_connector().health_check(password=_saved_password()))

        data = request.get_json(silent=True) or {}
        connection_id = str(data.get(MqttConnector.CONNECTION_FIELD) or '').strip()
        if not connection_id:
            return jsonify({'reachable': False, 'modules': {}, 'error': 'connection required'}), 400
        config = load_config()
        if get_connection(config, connection_id) is None:
            return jsonify({'reachable': False, 'modules': {}, 'error': 'unknown connection'}), 400

        block = {MqttConnector.CONNECTION_FIELD: connection_id}
        connector = MqttConnector(overlay_connection(block, config, MqttConnector.CONNECTION_FIELD))
        result = connector.probe(password=connection_password(connection_id))
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
    the rest of its configuration (connection, modules) is kept, so enabling it
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
