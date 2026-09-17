"""Tests for BaseConnector's own default method bodies.

Every real connector overrides get_module_urls/fetch_sensor_data (or not, when it
truly has neither), so a minimal stub subclass is the only way to exercise the
base defaults themselves rather than a concrete connector's own implementation.
"""

from connectors.base_connector import BaseConnector


class _MinimalConnector(BaseConnector):
    name = 'minimal'
    label = 'Minimal'

    def health_check(self):
        return {'reachable': True, 'modules': {}}


class TestDefaultHooks:

    def test_get_module_urls_defaults_to_empty(self):
        connector = _MinimalConnector({'url': 'http://x'})
        assert connector.get_module_urls() == {}
        assert connector.get_module_urls(date_str='20260101') == {}

    def test_fetch_sensor_data_defaults_to_empty(self):
        connector = _MinimalConnector({'url': 'http://x'})
        assert connector.fetch_sensor_data() == {}
