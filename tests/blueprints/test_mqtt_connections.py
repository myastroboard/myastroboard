"""Tests for the shared MQTT connection routes (blueprints/mqtt_connections.py).

  GET    /api/mqtt-connections
  POST   /api/mqtt-connections
  PUT    /api/mqtt-connections/<connection_id>
  DELETE /api/mqtt-connections/<connection_id>
  POST   /api/mqtt-connections/health

The config is a dict held by the test (load_config / save_config are replaced); the broker is
never contacted (``MqttConnector.probe`` is replaced by a recorder).
"""

import pytest

from connectors.mqtt_connector import MqttConnector
from utils.connector_secrets import load_secrets, save_secrets


@pytest.fixture
def store(monkeypatch):
    state = {
        'config': {
            'connectors': {'mqtt': {'mqtt_connection_id': 'c1', 'enabled': True}},
            'mqtt_connections': [
                {'id': 'c1', 'name': 'Home', 'url': 'mqtt://broker.lan:1883', 'username': 'u', 'tls_insecure': False},
                {'id': 'c2', 'name': 'Spare', 'url': 'mqtt://spare.lan', 'username': '', 'tls_insecure': False},
            ],
        },
        'saves': 0,
    }

    def _save(cfg):
        state['config'] = cfg
        state['saves'] += 1
        return True

    monkeypatch.setattr('blueprints.mqtt_connections.load_config', lambda: state['config'])
    monkeypatch.setattr('blueprints.mqtt_connections.save_config', _save)
    save_secrets('mqtt_connection:c1', {'password': 'saved-pw'})
    return state


@pytest.fixture
def probe(monkeypatch):
    calls = []
    result = {'reachable': True, 'error': None}

    def fake_probe(self, url=None, username=None, password=None, tls_insecure=None, client_factory=None):
        calls.append({'url': url, 'username': username, 'password': password, 'tls_insecure': tls_insecure})
        return dict(result)

    monkeypatch.setattr(MqttConnector, 'probe', fake_probe)
    return {'calls': calls, 'result': result}


class TestAccess:
    @pytest.mark.parametrize(
        'method, path',
        [
            ('GET', '/api/mqtt-connections'),
            ('POST', '/api/mqtt-connections'),
            ('PUT', '/api/mqtt-connections/c1'),
            ('DELETE', '/api/mqtt-connections/c1'),
            ('POST', '/api/mqtt-connections/health'),
        ],
    )
    def test_admin_only(self, client, client_user, method, path):
        """A connection carries broker credentials: every route is for admins only."""
        assert client.open(path, method=method, json={}).status_code == 401
        assert client_user.open(path, method=method, json={}).status_code == 403


class TestList:
    def test_list_masks_passwords_and_names_users(self, client_admin, store):
        """Each connection comes with a masked password and the connectors using it."""
        body = client_admin.get('/api/mqtt-connections').get_json()
        assert [c['id'] for c in body] == ['c1', 'c2']
        assert body[0]['password'] == '********' and body[0]['has_password'] is True
        assert body[0]['used_by'] == ['mqtt']
        assert body[1]['has_password'] is False and body[1]['used_by'] == []
        assert 'saved-pw' not in str(body) and 'd-pw' not in str(body)

    def test_list_failure_is_a_500(self, client_admin, monkeypatch):
        """An unexpected error is logged and reported generically."""

        def boom():
            raise RuntimeError('boom')

        monkeypatch.setattr('blueprints.mqtt_connections.load_config', boom)
        assert client_admin.get('/api/mqtt-connections').status_code == 500


class TestCreate:
    def test_create_returns_201_and_saves(self, client_admin, store):
        """A valid connection is saved and returned in its public form."""
        resp = client_admin.post(
            '/api/mqtt-connections', json={'name': 'AllSky', 'url': 'mqtt://sky.lan', 'username': 'a', 'password': 'p'}
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['name'] == 'AllSky' and body['has_password'] is True and body['used_by'] == []
        assert store['saves'] == 1
        assert [c['name'] for c in store['config']['mqtt_connections']] == ['Home', 'Spare', 'AllSky']
        assert load_secrets(f'mqtt_connection:{body["id"]}') == {'password': 'p'}

    def test_invalid_create_is_a_400(self, client_admin, store):
        """Validation errors come back as 400 with the reason, and nothing is saved."""
        resp = client_admin.post('/api/mqtt-connections', json={'name': 'Home', 'url': 'mqtt://x'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'a connection with this name already exists'
        assert store['saves'] == 0

    def test_create_save_failure_is_a_500(self, client_admin, store, monkeypatch):
        """A config that cannot be saved is reported."""
        monkeypatch.setattr('blueprints.mqtt_connections.save_config', lambda cfg: False)
        resp = client_admin.post('/api/mqtt-connections', json={'name': 'New', 'url': 'mqtt://x'})
        assert resp.status_code == 500


class TestUpdate:
    def test_update_keeps_a_masked_password(self, client_admin, store):
        """Saving the form unchanged (masked password) keeps the stored password."""
        resp = client_admin.put(
            '/api/mqtt-connections/c1', json={'name': 'Home 2', 'url': 'mqtt://broker.lan:1884', 'password': '********'}
        )
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'Home 2'
        assert store['config']['mqtt_connections'][0]['url'] == 'mqtt://broker.lan:1884'
        assert load_secrets('mqtt_connection:c1') == {'password': 'saved-pw'}

    def test_update_unknown_is_a_404_and_invalid_a_400(self, client_admin, store):
        """An unknown id and an invalid field are told apart."""
        assert client_admin.put('/api/mqtt-connections/nope', json={}).status_code == 404
        resp = client_admin.put('/api/mqtt-connections/c1', json={'url': ''})
        assert resp.status_code == 400 and resp.get_json()['error'] == 'url required'

    def test_update_save_failure_is_a_500(self, client_admin, store, monkeypatch):
        """A config that cannot be saved is reported."""
        monkeypatch.setattr('blueprints.mqtt_connections.save_config', lambda cfg: False)
        assert client_admin.put('/api/mqtt-connections/c1', json={'name': 'X'}).status_code == 500


class TestDelete:
    def test_delete_unused_connection(self, client_admin, store):
        """An unused connection is removed."""
        resp = client_admin.delete('/api/mqtt-connections/c2')
        assert resp.status_code == 200
        assert [c['id'] for c in store['config']['mqtt_connections']] == ['c1']

    def test_delete_in_use_is_a_409_naming_the_connectors(self, client_admin, store):
        """A connection a connector picks is kept; the answer says which connector."""
        resp = client_admin.delete('/api/mqtt-connections/c1')
        assert resp.status_code == 409
        assert resp.get_json() == {'error': 'connection in use', 'used_by': ['mqtt']}
        assert store['saves'] == 0

    def test_delete_unknown_is_a_404(self, client_admin, store):
        """Deleting an id that does not exist is a 404."""
        assert client_admin.delete('/api/mqtt-connections/nope').status_code == 404

    def test_delete_save_failure_is_a_500(self, client_admin, store, monkeypatch):
        """A config that cannot be saved is reported."""
        monkeypatch.setattr('blueprints.mqtt_connections.save_config', lambda cfg: False)
        assert client_admin.delete('/api/mqtt-connections/c2').status_code == 500


class TestHealth:
    def test_requires_a_url(self, client_admin, store, probe):
        """Without a URL there is nothing to probe."""
        resp = client_admin.post('/api/mqtt-connections/health', json={})
        assert resp.status_code == 400 and resp.get_json()['error'] == 'url required'
        assert probe['calls'] == []

    def test_typed_credentials_are_used_as_is(self, client_admin, store, probe):
        """The form's values are probed, before anything is saved."""
        resp = client_admin.post(
            '/api/mqtt-connections/health',
            json={'url': 'mqtts://new.lan/', 'username': 'x', 'password': 'typed', 'tls_insecure': True},
        )
        assert resp.get_json() == {'reachable': True}
        assert probe['calls'] == [
            {'url': 'mqtts://new.lan', 'username': 'x', 'password': 'typed', 'tls_insecure': True}
        ]

    def test_stored_password_only_for_the_saved_url(self, client_admin, store, probe):
        """A blank or masked password uses the stored one only toward the connection's own URL."""
        client_admin.post('/api/mqtt-connections/health', json={'id': 'c1', 'url': 'mqtt://broker.lan:1883'})
        client_admin.post(
            '/api/mqtt-connections/health', json={'id': 'c1', 'url': 'mqtt://broker.lan:1883', 'password': '********'}
        )
        client_admin.post('/api/mqtt-connections/health', json={'id': 'c1', 'url': 'mqtt://attacker.lan:1883'})
        client_admin.post('/api/mqtt-connections/health', json={'url': 'mqtt://broker.lan:1883'})
        assert [c['password'] for c in probe['calls']] == ['saved-pw', 'saved-pw', '', '']

    def test_unreachable_is_a_200_with_the_error(self, client_admin, store, probe):
        """A failed probe is reported in the body."""
        probe['result'].update(reachable=False, error='connection refused')
        resp = client_admin.post('/api/mqtt-connections/health', json={'url': 'mqtt://x'})
        assert resp.status_code == 200
        assert resp.get_json() == {'reachable': False, 'error': 'connection refused'}

    def test_unexpected_failure_is_a_500(self, client_admin, store, monkeypatch):
        """An unexpected error is logged and reported generically."""

        def boom(*a, **k):
            raise RuntimeError('boom')

        monkeypatch.setattr(MqttConnector, 'probe', boom)
        assert client_admin.post('/api/mqtt-connections/health', json={'url': 'mqtt://x'}).status_code == 500
