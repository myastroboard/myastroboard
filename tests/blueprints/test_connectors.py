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
        assert [c['name'] for c in data] == ['allsky', 'myastroshine']

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
        with patch.dict('connectors.REGISTRY', registry, clear=True), patch(
            'blueprints.connectors.load_config', return_value=_config()
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
