"""Tests for the MQTT connector routes (blueprints/connectors_mqtt.py).

  GET      /api/connectors/mqtt/health
  GET      /api/connectors/mqtt/status
  POST     /api/connectors/mqtt/publish
  POST     /api/connectors/mqtt/remove

The broker is never contacted: ``MqttConnector.probe`` is replaced by a recorder.
"""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from connectors.mqtt_connector import MqttConnector


def _cfg(**overrides):
    block = {
        'mqtt_connection_id': 'conn1',
        'enabled': True,
        'modules': {'sky_conditions': {'enabled': True}},
    }
    block.update(overrides)
    connections = [
        {'id': 'conn1', 'name': 'Home', 'url': 'mqtt://broker.lan:1883', 'username': 'saved-user'},
        {'id': 'conn2', 'name': 'Other', 'url': 'mqtts://other.lan', 'username': '', 'tls_insecure': True},
    ]
    return {'connectors': {'mqtt': block}, 'mqtt_connections': connections}


@pytest.fixture
def probe(monkeypatch):
    """Record every probe call and answer with a scripted result."""
    calls = []
    result = {'reachable': True, 'error': None}

    def fake_probe(self, url=None, username=None, password=None, tls_insecure=None, client_factory=None):
        calls.append({'url': url, 'username': username, 'password': password, 'tls_insecure': tls_insecure})
        return dict(result)

    monkeypatch.setattr(MqttConnector, 'probe', fake_probe)
    return {'calls': calls, 'result': result}


@pytest.fixture
def saved(monkeypatch):
    from utils.connector_secrets import save_secrets

    state = {'config': _cfg()}
    monkeypatch.setattr('blueprints.connectors_mqtt.load_config', lambda: state['config'])
    monkeypatch.setattr('blueprints.connectors_mqtt.save_config', lambda cfg: state.update(saved_cfg=cfg) or True)
    save_secrets('mqtt_connection:conn1', {'password': 'saved-pw'})
    return state


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class TestAccess:
    @pytest.mark.parametrize(
        'method, path',
        [
            ('GET', '/api/connectors/mqtt/health'),
            ('POST', '/api/connectors/mqtt/publish'),
            ('POST', '/api/connectors/mqtt/remove'),
        ],
    )
    def test_admin_only_routes(self, client, client_user, method, path):
        assert client.open(path, method=method, json={}).status_code == 401
        assert client_user.open(path, method=method, json={}).status_code == 403

    def test_status_needs_login_only(self, client, client_user, saved):
        assert client.get('/api/connectors/mqtt/status').status_code == 401
        assert client_user.get('/api/connectors/mqtt/status').status_code == 200


# ---------------------------------------------------------------------------
# Health / probe
# ---------------------------------------------------------------------------


class TestHealth:
    def test_get_probes_the_saved_connection_with_its_stored_credentials(self, client_admin, saved, probe):
        """GET probes the broker of the connection the saved connector picks, with its password."""
        resp = client_admin.get('/api/connectors/mqtt/health')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['reachable'] is True
        assert body['modules']['sky_conditions'] == {'ok': True, 'detail': 'enabled'}
        assert body['modules']['weather_now'] == {'ok': False, 'detail': 'disabled'}
        # health_check() forwards the saved password explicitly - the connector's own config
        # is deliberately secret-free (see _saved_connector()'s docstring)
        assert probe['calls'] == [{'url': None, 'username': None, 'password': 'saved-pw', 'tls_insecure': None}]

    def test_get_without_a_connection_reports_url_required(self, client_admin, saved, probe):
        """A connector that picks no connection has no broker to probe."""
        saved['config'] = _cfg(mqtt_connection_id='')
        body = client_admin.get('/api/connectors/mqtt/health').get_json()
        assert body == {'reachable': False, 'modules': {}, 'error': 'url required'}
        assert probe['calls'] == []

    def test_post_is_not_allowed(self, client_admin, saved, probe):
        """Testing a picked connection before saving is /api/mqtt-connections/health's job."""
        assert client_admin.post('/api/connectors/mqtt/health', json={}).status_code == 405
        assert probe['calls'] == []

    def test_saved_connector_reads_the_broker_from_the_connection(self, saved):
        """The routing connector gets url / username / TLS from its connection, never the password.

        Regression guard for the CodeQL finding: mixing the password into the same dict that
        url/client_id/etc. are read from taints every one of those reads as a credential to
        static analysis. The caller fetches the password separately (_saved_password())."""
        from blueprints.connectors_mqtt import _saved_connector, _saved_password

        connector = _saved_connector()
        assert connector.base_url == 'mqtt://broker.lan:1883'
        assert connector.username() == 'saved-user'
        assert 'password' not in connector.config and 'password' not in (connector.connection or {})
        assert _saved_password() == 'saved-pw'

    def test_unexpected_failure_is_a_500(self, client_admin, saved, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError('boom')

        monkeypatch.setattr(MqttConnector, 'probe', boom)
        assert client_admin.get('/api/connectors/mqtt/health').status_code == 500


# ---------------------------------------------------------------------------
# Status / publish / remove
# ---------------------------------------------------------------------------


class TestPublisherRoutes:
    def test_status_returns_the_publisher_status(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        monkeypatch.setattr(mqtt_publisher, 'read_status', lambda: {'connected': True, 'devices': []})
        assert client_admin.get('/api/connectors/mqtt/status').get_json() == {'connected': True, 'devices': []}

    def test_status_failure_is_a_500(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        def boom():
            raise RuntimeError('boom')

        monkeypatch.setattr(mqtt_publisher, 'read_status', boom)
        assert client_admin.get('/api/connectors/mqtt/status').status_code == 500

    def test_publish_writes_the_trigger(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        actions = []
        monkeypatch.setattr(mqtt_publisher, 'request_action', lambda action: actions.append(action) or True)
        resp = client_admin.post('/api/connectors/mqtt/publish')
        assert resp.status_code == 200
        assert resp.get_json() == {'status': 'requested', 'action': 'publish'}
        assert actions == ['publish']

    def test_publish_signal_failure_is_a_500(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        monkeypatch.setattr(mqtt_publisher, 'request_action', lambda action: False)
        assert client_admin.post('/api/connectors/mqtt/publish').status_code == 500

        def boom(action):
            raise RuntimeError('boom')

        monkeypatch.setattr(mqtt_publisher, 'request_action', boom)
        assert client_admin.post('/api/connectors/mqtt/publish').status_code == 500
        assert client_admin.post('/api/connectors/mqtt/remove').status_code == 500

    def test_remove_disables_the_connector_then_signals(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        actions = []
        monkeypatch.setattr(mqtt_publisher, 'request_action', lambda action: actions.append(action) or True)
        resp = client_admin.post('/api/connectors/mqtt/remove')
        assert resp.status_code == 200
        assert resp.get_json() == {'status': 'requested', 'action': 'remove', 'enabled': False}
        assert saved['saved_cfg']['connectors']['mqtt']['enabled'] is False
        assert saved['saved_cfg']['connectors']['mqtt']['mqtt_connection_id'] == 'conn1'  # the rest is kept
        assert actions == ['remove']

    def test_remove_on_an_already_disabled_connector_does_not_save(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        saved['config'] = _cfg(enabled=False)
        monkeypatch.setattr(mqtt_publisher, 'request_action', lambda action: True)
        assert client_admin.post('/api/connectors/mqtt/remove').status_code == 200
        assert 'saved_cfg' not in saved

    def test_remove_save_failure_is_a_500(self, client_admin, saved, monkeypatch):
        monkeypatch.setattr('blueprints.connectors_mqtt.save_config', lambda cfg: False)
        assert client_admin.post('/api/connectors/mqtt/remove').status_code == 500

    def test_remove_signal_failure_is_a_500(self, client_admin, saved, monkeypatch):
        from connectors import mqtt_publisher

        monkeypatch.setattr(mqtt_publisher, 'request_action', lambda action: False)
        assert client_admin.post('/api/connectors/mqtt/remove').status_code == 500
