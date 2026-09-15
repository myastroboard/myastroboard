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
        "live_image":  {"enabled": True},
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
        assert len(data) == 1
        assert data[0]['name'] == 'allsky'

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
