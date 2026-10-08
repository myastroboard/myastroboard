"""Tests for the connectors registry endpoint (blueprints/connectors.py).

  GET /api/connectors

Each connector's own routes are tested in the sibling module named after it -
test_connectors_allsky.py, test_connectors_myastroshine.py.
"""

import sys
import types
from unittest.mock import patch

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_CFG_ALLSKY_ENABLED = {
    "url": "http://allsky.local",
    "enabled": True,
    "modules": {
        "live_image": {"enabled": True},
        "sensor_data": {"enabled": True},
    },
}

_CFG_ALLSKY_URL_ONLY = {
    "url": "http://allsky.local",
    "enabled": False,
    "modules": {},
}


def _config(allsky_cfg=None):
    return {"connectors": {"allsky": allsky_cfg} if allsky_cfg else {}}


# ---------------------------------------------------------------------------
# GET /api/connectors
# ---------------------------------------------------------------------------


class TestListConnectors:
    def test_requires_login(self, client):
        resp = client.get('/api/connectors')
        assert resp.status_code == 401

    def test_returns_list(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert [c['name'] for c in data] == ['allsky', 'myastroshine', 'mqtt', 'astrodex_stream']

    def test_every_registered_connector_is_listed(self, client_user):
        """The listing is the registry - a connector is not special-cased out of it."""
        from connectors import REGISTRY

        with patch('blueprints.connectors.load_config', return_value=_config()):
            data = client_user.get('/api/connectors').get_json()
        assert {c['name'] for c in data} == set(REGISTRY)

    def test_connector_not_installed_when_no_url(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is False
        assert data[0]['enabled'] is False

    def test_connector_installed_not_enabled(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_URL_ONLY)):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is True
        assert data[0]['enabled'] is False

    def test_connector_installed_and_enabled(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is True
        assert data[0]['enabled'] is True

    def test_response_includes_homepage(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert 'homepage' in data[0]
        assert 'github.com/AllskyTeam' in data[0]['homepage']

    def test_response_includes_target_modules(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['target_modules'] == ['observatory']

    def test_target_modules_defaults_to_empty_list(self, client_user):
        """A connector that declares no target module is valid - it feeds no app tab."""
        from connectors.base_connector import BaseConnector

        class _StandaloneConnector(BaseConnector):
            name = 'standalone'
            label = 'Standalone'
            description = ''
            MODULES = []

            def health_check(self):
                return {}

            def get_module_urls(self, date_str=None):
                return {}

            def fetch_sensor_data(self):
                return {}

        registry = {'standalone': _StandaloneConnector}
        with (
            patch.dict('connectors.REGISTRY', registry, clear=True),
            patch('blueprints.connectors.load_config', return_value=_config()),
        ):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['target_modules'] == []


# ---------------------------------------------------------------------------
# POST /api/connectors/<name>/config - the shared save path
#
# Most of this endpoint is exercised through MyAstroShine in
# test_connectors_myastroshine.py, but that connector declares no MODULES and no
# plain-string CONFIG_FIELDS, so the module-merge and generic-string-field branches
# need a connector that actually has them - AllSky does.
# ---------------------------------------------------------------------------


class TestSaveConnectorConfig:
    def test_known_module_is_merged_and_unknown_or_malformed_entries_are_ignored(self, client_admin, monkeypatch):
        saved = {}
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: {'connectors': {}})
        monkeypatch.setattr('blueprints.connectors.save_config', lambda cfg: saved.update(cfg) or True)

        resp = client_admin.post(
            '/api/connectors/allsky/config',
            json={
                'url': 'http://allsky.local',
                'modules': {
                    'live_image': {'enabled': True},
                    'not_a_real_module': {'enabled': True},
                    'sensor_data': 'not-a-dict',
                },
            },
        )
        assert resp.status_code == 200
        assert saved['connectors']['allsky']['modules'] == {'live_image': {'enabled': True}}

    def test_plain_string_config_field_is_trimmed_or_falls_back_to_default(self, client_admin, monkeypatch):
        saved = {}
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: {'connectors': {}})
        monkeypatch.setattr('blueprints.connectors.save_config', lambda cfg: saved.update(cfg) or True)

        resp = client_admin.post(
            '/api/connectors/allsky/config',
            json={'url': 'http://allsky.local', 'image_path': '  custom/path  ', 'image_filename': ''},
        )
        assert resp.status_code == 200
        stored = saved['connectors']['allsky']
        assert stored['image_path'] == 'custom/path'
        assert stored['image_filename'] == 'image.jpg'  # blank falls back to the field's default


# ---------------------------------------------------------------------------
# Typed CONFIG_FIELDS and the credentials sidecar - exercised with a stub connector so
# the contract is pinned independently of any real connector's field list.
# ---------------------------------------------------------------------------


def _stub_registry():
    from connectors.base_connector import BaseConnector

    class _StubConnector(BaseConnector):
        name = 'stub'
        label = 'Stub'
        description = ''
        MODULES = []
        SECRET_FIELDS = ('password',)
        CONFIG_FIELDS = {'password': '', 'interval': 60, 'flag': False, 'note': 'n/a', 'choice': 'a'}
        ENUM_FIELDS = {'choice': ('a', 'b', 'c')}

        def is_configured(self):
            return bool(self.base_url and self.config.get('password'))

        def health_check(self):
            return {'reachable': False, 'modules': {}}

    return {'stub': _StubConnector}


class TestTypedFieldsAndSecrets:
    def _save(self, client_admin, monkeypatch, payload, stored_cfg=None):
        saved = {}
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: {'connectors': dict(stored_cfg or {})})
        monkeypatch.setattr('blueprints.connectors.save_config', lambda cfg: saved.update(cfg) or True)
        with patch.dict('connectors.REGISTRY', _stub_registry(), clear=True):
            resp = client_admin.post('/api/connectors/stub/config', json=payload)
        return resp, saved

    def test_int_field_is_coerced_and_falls_back_to_default(self, client_admin, monkeypatch):
        resp, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'interval': '120'})
        assert resp.status_code == 200
        assert saved['connectors']['stub']['interval'] == 120

        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'interval': ''})
        assert saved['connectors']['stub']['interval'] == 60

        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'interval': 'abc'})
        assert saved['connectors']['stub']['interval'] == 60

        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'interval': 45.9})
        assert saved['connectors']['stub']['interval'] == 45

        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'interval': True})
        assert saved['connectors']['stub']['interval'] == 60  # a bool is not a number here

    def test_secret_goes_to_the_sidecar_never_to_config(self, client_admin, monkeypatch):
        from utils.connector_secrets import load_secrets

        resp, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'password': 'hunter2'})
        assert resp.status_code == 200
        assert 'password' not in saved['connectors']['stub']
        assert load_secrets('stub') == {'password': 'hunter2'}
        # The response reflects the effective state (URL + credential -> installed)
        assert resp.get_json()['installed'] is True

    def test_blank_or_masked_secret_keeps_the_sidecar_value(self, client_admin, monkeypatch):
        from utils.connector_secrets import load_secrets, save_secrets

        save_secrets('stub', {'password': 'keepme'})
        for echoed in ('', '****epme'):
            resp, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'password': echoed})
            assert resp.status_code == 200
            assert 'password' not in saved['connectors']['stub']
            assert load_secrets('stub') == {'password': 'keepme'}
            assert resp.get_json()['installed'] is True

    def test_legacy_secret_in_config_is_migrated_on_save(self, client_admin, monkeypatch):
        from utils.connector_secrets import load_secrets

        resp, saved = self._save(
            client_admin, monkeypatch, {'note': 'x'}, stored_cfg={'stub': {'url': 'http://x', 'password': 'legacy'}}
        )
        assert resp.status_code == 200
        assert 'password' not in saved['connectors']['stub']
        assert load_secrets('stub') == {'password': 'legacy'}

    def test_enum_field_accepts_an_allowed_value_and_rejects_anything_else(self, client_admin, monkeypatch):
        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'choice': 'b'})
        assert saved['connectors']['stub']['choice'] == 'b'

        for not_allowed in ('z', '', 'A'):
            _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'choice': not_allowed})
            assert saved['connectors']['stub']['choice'] == 'a'  # falls back to the field's default

        # Surrounding whitespace is trimmed before the allowed-values check, same as every
        # other plain string field in this endpoint - ' b ' is accepted as 'b', not rejected.
        _, saved = self._save(client_admin, monkeypatch, {'url': 'http://x', 'choice': ' b '})
        assert saved['connectors']['stub']['choice'] == 'b'

    def test_listing_exposes_enum_fields_for_the_frontend_select(self, client_user, monkeypatch):
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: {'connectors': {'stub': {'url': 'http://x'}}})
        with patch.dict('connectors.REGISTRY', _stub_registry(), clear=True):
            entry = client_user.get('/api/connectors').get_json()[0]
        assert entry['enum_fields'] == {'choice': ['a', 'b', 'c']}

    def test_listing_masks_a_sidecar_secret_and_reports_installed(self, client_user, monkeypatch):
        from utils.connector_secrets import save_secrets

        save_secrets('stub', {'password': 'hunter2'})
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: {'connectors': {'stub': {'url': 'http://x'}}})
        with patch.dict('connectors.REGISTRY', _stub_registry(), clear=True):
            entry = client_user.get('/api/connectors').get_json()[0]
        assert entry['config']['password'] == '****ter2'
        assert entry['config']['has_password'] is True
        assert entry['installed'] is True
        assert 'hunter2' not in str(entry)

    def test_sidecar_write_failure_is_a_500(self, client_admin, monkeypatch):
        monkeypatch.setattr('blueprints.connectors.save_secrets', lambda name, values: False)
        resp, _ = self._save(client_admin, monkeypatch, {'url': 'http://x', 'password': 'hunter2'})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Connectors on a shared MQTT connection (CONNECTION_FIELD)
# ---------------------------------------------------------------------------


def _connection_registry():
    from connectors.base_connector import BaseConnector

    class _OnConnection(BaseConnector):
        label = 'On connection'
        description = ''
        MODULES = []
        CONNECTION_FIELD = 'mqtt_connection_id'
        CONFIG_FIELDS = {'mqtt_connection_id': '', 'client_id': ''}

        def is_configured(self):
            return bool(self.connection)

        def health_check(self):
            return {'reachable': False, 'modules': {}}

    class _First(_OnConnection):
        name = 'first'

    class _Second(_OnConnection):
        name = 'second'

    return {'first': _First, 'second': _Second}


_CONNECTIONS = [
    {'id': 'c1', 'name': 'Home', 'url': 'mqtt://broker.lan', 'username': 'u'},
    {'id': 'c2', 'name': 'Spare', 'url': 'mqtt://spare.lan', 'username': ''},
]


class TestSharedConnection:
    def _save(self, client_admin, monkeypatch, name, payload, connectors_cfg=None):
        saved = {}
        config = {'connectors': dict(connectors_cfg or {}), 'mqtt_connections': list(_CONNECTIONS)}
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: config)
        monkeypatch.setattr('blueprints.connectors.save_config', lambda cfg: saved.update(cfg) or True)
        with patch.dict('connectors.REGISTRY', _connection_registry(), clear=True):
            resp = client_admin.post(f'/api/connectors/{name}/config', json=payload)
        return resp, saved

    def test_listing_offers_the_connections_and_reads_the_broker_from_them(self, client_user, monkeypatch):
        """The card gets the connection names to pick from; installed follows the picked connection."""
        config = {'connectors': {'first': {'mqtt_connection_id': 'c1'}}, 'mqtt_connections': list(_CONNECTIONS)}
        monkeypatch.setattr('blueprints.connectors.load_config', lambda: config)
        with patch.dict('connectors.REGISTRY', _connection_registry(), clear=True):
            data = {c['name']: c for c in client_user.get('/api/connectors').get_json()}
        assert data['first']['connection_field'] == 'mqtt_connection_id'
        assert data['first']['connection_options'] == [{'id': 'c1', 'name': 'Home'}, {'id': 'c2', 'name': 'Spare'}]
        assert data['first']['installed'] is True
        assert data['second']['installed'] is False

    def test_save_keeps_the_connection_id_and_never_a_url(self, client_admin, monkeypatch):
        """The block stores the picked connection; a submitted URL is ignored."""
        resp, saved = self._save(client_admin, monkeypatch, 'first', {'mqtt_connection_id': 'c2', 'url': 'mqtt://x'})
        assert resp.status_code == 200
        assert resp.get_json()['installed'] is True
        assert saved['connectors']['first']['mqtt_connection_id'] == 'c2'
        assert 'url' not in saved['connectors']['first']

    def test_save_rejects_an_unknown_connection(self, client_admin, monkeypatch):
        """A connection id that does not exist is refused."""
        resp, saved = self._save(client_admin, monkeypatch, 'first', {'mqtt_connection_id': 'gone'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'unknown connection'
        assert saved == {}

    def test_save_rejects_a_client_id_already_used_on_the_same_connection(self, client_admin, monkeypatch):
        """Two connectors on one broker cannot share a client id - the broker would kick one off."""
        others = {'first': {'mqtt_connection_id': 'c1', 'client_id': 'board'}}
        resp, saved = self._save(
            client_admin, monkeypatch, 'second', {'mqtt_connection_id': 'c1', 'client_id': 'board'}, others
        )
        assert resp.status_code == 400
        assert resp.get_json() == {'error': 'client id already used on this connection', 'used_by': 'first'}
        assert saved == {}

    def test_same_client_id_on_another_connection_is_fine(self, client_admin, monkeypatch):
        """Client ids only have to differ per broker."""
        others = {'first': {'mqtt_connection_id': 'c1', 'client_id': 'board'}}
        resp, _ = self._save(
            client_admin, monkeypatch, 'second', {'mqtt_connection_id': 'c2', 'client_id': 'board'}, others
        )
        assert resp.status_code == 200
