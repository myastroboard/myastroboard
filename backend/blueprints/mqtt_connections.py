"""MQTT connections Blueprint. Routes: /api/mqtt-connections/*

The broker profiles shared by the MQTT connectors (utils/mqtt_connections.py), managed from
Parameters -> Configuration. Every route is admin-only: a connection carries broker credentials.
The password is never returned - only masked, with a ``has_password`` flag.
"""

from flask import Blueprint, jsonify, request

from connectors.mqtt_connector import MqttConnector
from utils.auth import admin_required
from utils.logging_config import get_logger
from utils.mqtt_connections import (
    connection_password,
    create_connection,
    delete_connection,
    get_connection,
    list_connections,
    public_connection,
    update_connection,
)
from utils.repo_config import load_config, save_config

logger = get_logger(__name__)

mqtt_connections_bp = Blueprint('mqtt_connections', __name__)


@mqtt_connections_bp.route('/api/mqtt-connections', methods=['GET'])
@admin_required
def list_mqtt_connections_api():
    """Every saved connection, password masked, with the connectors using it."""
    try:
        config = load_config()
        return jsonify([public_connection(config, c) for c in list_connections(config)])
    except Exception as exc:
        logger.error(f"Error listing MQTT connections: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@mqtt_connections_bp.route('/api/mqtt-connections', methods=['POST'])
@admin_required
def create_mqtt_connection_api():
    """Create a connection from ``{name, url, username?, password?, tls_insecure?}``."""
    try:
        config = load_config()
        connection, error = create_connection(config, request.get_json(silent=True) or {})
        if error or connection is None:
            return jsonify({'error': error or 'invalid connection'}), 400
        if not save_config(config):
            return jsonify({'error': 'Failed to save configuration'}), 500
        return jsonify(public_connection(config, connection)), 201
    except Exception as exc:
        logger.error(f"Error creating MQTT connection: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@mqtt_connections_bp.route('/api/mqtt-connections/<connection_id>', methods=['PUT'])
@admin_required
def update_mqtt_connection_api(connection_id):
    """Edit a connection. A blank or still-masked password keeps the stored one."""
    try:
        config = load_config()
        connection, error = update_connection(config, connection_id, request.get_json(silent=True) or {})
        if error == 'not found':
            return jsonify({'error': error}), 404
        if error or connection is None:
            return jsonify({'error': error or 'invalid connection'}), 400
        if not save_config(config):
            return jsonify({'error': 'Failed to save configuration'}), 500
        return jsonify(public_connection(config, connection))
    except Exception as exc:
        logger.error(f"Error updating MQTT connection: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@mqtt_connections_bp.route('/api/mqtt-connections/<connection_id>', methods=['DELETE'])
@admin_required
def delete_mqtt_connection_api(connection_id):
    """Delete a connection; 409 with ``used_by`` (connector names) while a connector uses it."""
    try:
        config = load_config()
        users, error = delete_connection(config, connection_id)
        if error == 'not found':
            return jsonify({'error': error}), 404
        if error:
            return jsonify({'error': error, 'used_by': users}), 409
        if not save_config(config):
            return jsonify({'error': 'Failed to save configuration'}), 500
        return jsonify({'status': 'deleted', 'id': connection_id})
    except Exception as exc:
        logger.error(f"Error deleting MQTT connection: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@mqtt_connections_bp.route('/api/mqtt-connections/health', methods=['POST'])
@admin_required
def mqtt_connection_health_api():
    """Connect to a broker once, as typed in the form or as saved.

    ``{"url", "username"?, "password"?, "tls_insecure"?, "id"?}``. A blank or still-masked
    password is replaced by the stored one of connection ``id`` **only when the URL is that
    connection's saved URL**: a stored credential is never sent to a host the caller just typed.

    A failed probe is a 200 with ``reachable: false`` and an ``error`` string; 400 is reserved
    for a missing URL.
    """
    try:
        data = request.get_json(silent=True) or {}
        url = str(data.get('url') or '').strip().rstrip('/')
        if not url:
            return jsonify({'reachable': False, 'error': 'url required'}), 400

        username = str(data.get('username') or '').strip()
        password = str(data.get('password') or '').strip()
        if not password or password.startswith('****'):
            saved = get_connection(load_config(), data.get('id'))
            password = connection_password(saved['id']) if saved and saved['url'] == url else ''

        result = MqttConnector({}).probe(
            url=url, username=username, password=password, tls_insecure=bool(data.get('tls_insecure', False))
        )
        payload = {'reachable': bool(result['reachable'])}
        if result.get('error'):
            payload['error'] = result['error']
        return jsonify(payload)
    except Exception as exc:
        logger.error(f"Error probing MQTT connection: {exc}")
        return jsonify({'error': 'Internal server error'}), 500
