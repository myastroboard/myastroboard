"""Tests for connectors/mqtt_connector.py - declaration, topic layout and the connection probe.

The probe is exercised with a fake paho client injected through ``client_factory``: no broker,
no network. Host resolution is patched so the tests do not depend on DNS either.
"""

import socket
import ssl

import pytest

from connectors import mqtt_connector as mc
from connectors.mqtt_connector import MqttConnector


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Reason:
    """Mimics paho's ReasonCode: str() is the name, is_failure says whether CONNACK refused."""

    def __init__(self, name, failure):
        self._name = name
        self.is_failure = failure

    def __str__(self):
        return self._name


class FakeClient:
    """A paho-shaped client whose connect() outcome is scripted per test."""

    def __init__(self, client_id, behaviour='ok'):
        self.client_id = client_id
        self.behaviour = behaviour
        self.on_connect = None
        self.calls = []
        self.connect_timeout = None
        self.username = None
        self.password = None
        self.tls = False
        self.insecure = False
        self.connected_to = None

    def username_pw_set(self, username, password=None):
        self.username, self.password = username, password

    def tls_set(self):
        self.tls = True

    def tls_insecure_set(self, value):
        self.insecure = value

    def connect(self, host, port, keepalive=60):
        self.connected_to = (host, port)
        self.calls.append('connect')
        if self.behaviour == 'refused':
            raise ConnectionRefusedError()
        if self.behaviour == 'socket-timeout':
            raise socket.timeout()
        if self.behaviour == 'ssl':
            raise _SSLError('certificate verify failed')
        if self.behaviour == 'valueerror':
            raise ValueError('bad argument')

    def loop(self, timeout=1.0):
        self.calls.append('loop')
        if self.behaviour == 'ok' and self.on_connect:
            self.on_connect(self, None, {}, _Reason('Success', False), None)
        elif self.behaviour == 'auth' and self.on_connect:
            self.on_connect(self, None, {}, _Reason('Not authorized', True), None)
        elif self.behaviour == 'int-rc' and self.on_connect:
            self.on_connect(self, None, {}, 5, None)
        # 'silent': never answers -> the probe times out

    def disconnect(self):
        self.calls.append('disconnect')
        if self.behaviour == 'disconnect-raises':
            raise RuntimeError('already gone')


class _SSLError(ssl.SSLError):
    pass  # the real base class - a bare OSError is not enough to exercise isinstance(exc, ssl.SSLError)


def _factory(behaviour, created):
    def make(client_id):
        client = FakeClient(client_id, behaviour)
        created.append(client)
        return client

    return make


@pytest.fixture(autouse=True)
def _resolve_ok(monkeypatch):
    monkeypatch.setattr(mc, 'resolve_broker_host', lambda host, port: ('192.0.2.10', None))
    monkeypatch.setattr(MqttConnector, 'CONNECT_TIMEOUT_SECONDS', 0.2)


# ---------------------------------------------------------------------------
# URL parsing and helpers
# ---------------------------------------------------------------------------


class TestParseBrokerUrl:
    """parse_broker_url() returns an (host, port, tls, error) tuple - never raises - so a bad
    URL never needs an exception object that could later reach an HTTP response (CWE-209)."""

    def test_plain_and_tls_defaults(self):
        assert mc.parse_broker_url('mqtt://broker.lan') == ('broker.lan', 1883, False, None)
        assert mc.parse_broker_url('mqtts://broker.lan') == ('broker.lan', 8883, True, None)
        assert mc.parse_broker_url('MQTT://192.168.1.10:1884/') == ('192.168.1.10', 1884, False, None)

    @pytest.mark.parametrize(
        'bad',
        ['', 'http://broker.lan', 'broker.lan:1883', 'mqtt://', 'mqtt://broker.lan/path', 'mqtt://broker.lan?x=1',
         'mqtt://broker.lan:notaport'],
    )
    def test_rejects_anything_that_is_not_a_bare_mqtt_url(self, bad):
        host, port, tls, error = mc.parse_broker_url(bad)
        assert host is None and port is None and error


class TestResolveBrokerHost:

    def test_refuses_dangerous_ranges_after_resolution(self, monkeypatch):
        monkeypatch.undo()
        for ip in ('127.0.0.1', '169.254.169.254', '0.0.0.0', '224.0.0.1', '::1'):
            monkeypatch.setattr(mc.socket, 'getaddrinfo', lambda *a, _ip=ip, **k: [(None, None, None, None, (_ip, 0))])
            assert mc.resolve_broker_host('x', 1883) == (None, 'url host is not allowed')

    def test_returns_the_resolved_ip(self, monkeypatch):
        monkeypatch.undo()
        monkeypatch.setattr(mc.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('192.168.1.10', 0))])
        assert mc.resolve_broker_host('broker.lan', 1883) == ('192.168.1.10', None)

    def test_unresolvable_host(self, monkeypatch):
        monkeypatch.undo()

        def boom(*a, **k):
            raise socket.gaierror()

        monkeypatch.setattr(mc.socket, 'getaddrinfo', boom)
        assert mc.resolve_broker_host('nope.invalid', 1883) == (None, 'unable to resolve host')


class TestSanitizers:

    def test_object_id_keeps_only_ha_safe_characters(self):
        assert mc.sanitize_object_id('My Board/#1') == 'My_Board_1'
        assert mc.sanitize_object_id('') == 'myastroboard'
        assert mc.sanitize_object_id('___') == 'myastroboard'

    def test_topic_level_strips_wildcards_and_separators(self):
        assert mc.sanitize_topic_level('a/b+c#') == 'a_b_c_'
        assert mc.sanitize_topic_level('  ') == 'myastroboard'


# ---------------------------------------------------------------------------
# Declaration and accessors
# ---------------------------------------------------------------------------


class TestDeclaration:

    def test_registered_and_standalone(self):
        from connectors import REGISTRY

        assert REGISTRY['mqtt'] is MqttConnector
        assert MqttConnector.target_modules == []
        assert MqttConnector.SECRET_FIELDS == ('password',)
        assert 'password' in MqttConnector.CONFIG_FIELDS
        assert isinstance(MqttConnector.CONFIG_FIELDS['publish_interval_seconds'], int)
        slugs = [m['slug'] for m in MqttConnector.MODULES]
        assert slugs == [
            'sky_conditions', 'weather_now', 'upcoming_events', 'user_activity', 'astrodex_image', 'board_diagnostics'
        ]

    def test_is_configured_needs_a_parseable_mqtt_url_only(self):
        assert MqttConnector({}).is_configured() is False
        assert MqttConnector({'url': 'http://broker'}).is_configured() is False
        assert MqttConnector({'url': 'mqtt://broker'}).is_configured() is True
        assert MqttConnector({'url': 'mqtt://broker', 'enabled': True}).is_enabled() is True

    def test_accessors_apply_defaults_sanitizing_and_clamping(self):
        c = MqttConnector({'url': 'mqtt://b', 'base_topic': ' my/base# ', 'discovery_prefix': '',
                           'publish_interval_seconds': '3', 'client_id': ' abc ', 'tls_insecure': 1})
        assert c.base_topic() == 'my_base_'
        assert c.discovery_prefix() == 'homeassistant'
        assert c.publish_interval_seconds() == MqttConnector.MIN_PUBLISH_INTERVAL_SECONDS
        assert c.client_id() == 'abc'
        assert c.tls_insecure() is True
        assert c.discovery_enabled() is True
        assert MqttConnector({'publish_interval_seconds': 'x'}).publish_interval_seconds() == 60
        assert MqttConnector({'publish_interval_seconds': 600}).publish_interval_seconds() == 600
        assert MqttConnector({'discovery_enabled': False}).discovery_enabled() is False

    def test_generate_client_id_shape(self):
        cid = MqttConnector.generate_client_id()
        assert cid.startswith('myastroboard-') and len(cid) == len('myastroboard-') + 8


class TestTopicLayout:

    def test_topics_follow_the_documented_layout(self):
        c = MqttConnector({'url': 'mqtt://b', 'base_topic': 'mab', 'discovery_prefix': 'ha'})
        assert c.availability_topic() == 'mab/status'
        assert c.state_topic('board') == 'mab/board/state'
        assert c.state_topic('location', 'loc-1') == 'mab/location/loc-1/state'
        assert c.state_topic('user', 'u/1') == 'mab/user/u_1/state'
        assert c.image_topic('u1') == 'mab/user/u1/astrodex/latest_image'
        assert c.device_object_id('board') == 'mab_board'
        assert c.device_object_id('location', 'loc-1') == 'mab_loc_loc-1'
        assert c.device_object_id('user', 'u 1') == 'mab_user_u_1'
        assert c.discovery_topic('board') == 'ha/device/mab_board/config'
        assert c.discovery_topic('user', 'u1') == 'ha/device/mab_user_u1/config'
        assert c.ha_status_topic() == 'ha/status'


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:

    def test_successful_connect_uses_credentials_and_the_vetted_ip(self):
        created = []
        c = MqttConnector({'url': 'mqtt://broker.lan:1884', 'username': 'u', 'password': 'p'})
        result = c.probe(client_factory=_factory('ok', created))
        assert result == {'reachable': True, 'error': None}
        client = created[0]
        assert client.connected_to == ('192.0.2.10', 1884)
        assert (client.username, client.password) == ('u', 'p')
        assert client.tls is False
        assert client.connect_timeout == pytest.approx(0.2)
        assert client.calls[-1] == 'disconnect'
        assert client.client_id.startswith('myastroboard-probe-')

    def test_tls_url_connects_by_hostname_and_honours_insecure(self):
        created = []
        c = MqttConnector({'url': 'mqtts://broker.lan', 'tls_insecure': True})
        assert c.probe(client_factory=_factory('ok', created))['reachable'] is True
        client = created[0]
        assert client.connected_to == ('broker.lan', 8883)
        assert client.tls is True and client.insecure is True

    def test_explicit_arguments_override_the_configured_ones(self):
        created = []
        c = MqttConnector({'url': 'mqtt://saved', 'username': 'saved-u', 'password': 'saved-p'})
        c.probe(url='mqtt://other', username='typed', password='typed-p', tls_insecure=False,
                client_factory=_factory('ok', created))
        assert created[0].username == 'typed' and created[0].password == 'typed-p'

    def test_anonymous_probe_sets_no_credentials(self):
        created = []
        MqttConnector({'url': 'mqtt://b'}).probe(client_factory=_factory('ok', created))
        assert created[0].username is None

    def test_bad_url_and_unresolvable_host(self, monkeypatch):
        c = MqttConnector({'url': 'http://b'})
        assert c.probe(client_factory=_factory('ok', [])) == {'reachable': False, 'error': 'url must start with mqtt:// or mqtts://'}
        monkeypatch.setattr(mc, 'resolve_broker_host', lambda host, port: (None, 'url host is not allowed'))
        assert MqttConnector({'url': 'mqtt://b'}).probe(client_factory=_factory('ok', []))['error'] == 'url host is not allowed'

    @pytest.mark.parametrize(
        'behaviour, expected',
        [
            ('refused', 'connection refused'),
            ('socket-timeout', 'timeout - no answer from the broker'),
            ('ssl', 'TLS handshake failed - check the certificate or enable the insecure option'),
            ('valueerror', 'connection failed'),  # generic fallback - never derived from the exception at all
            ('silent', 'timeout - no answer from the broker'),
            ('auth', 'broker refused the connection: Not authorized'),
            ('int-rc', 'broker refused the connection: 5'),
        ],
    )
    def test_failure_modes_are_reported_without_raising(self, behaviour, expected):
        created = []
        result = MqttConnector({'url': 'mqtt://b'}).probe(client_factory=_factory(behaviour, created))
        assert result['reachable'] is False
        assert result['error'] == expected
        assert created[0].calls[-1] == 'disconnect'

    def test_disconnect_failure_is_swallowed(self):
        result = MqttConnector({'url': 'mqtt://b'}).probe(client_factory=_factory('disconnect-raises', []))
        assert result['reachable'] is False  # the fake never answered, and disconnect raising did not propagate

    def test_default_factory_builds_a_paho_v2_client(self):
        import paho.mqtt.client as mqtt

        client = MqttConnector._default_client_factory('probe-x')
        assert isinstance(client, mqtt.Client)


class TestDescribeProbeError:
    """_describe_probe_error() must never leak anything read off the exception object itself
    (not even its class name) into its return value - that return value flows into an HTTP
    response, and CodeQL's exception-exposure check (CWE-209) treats any exception-derived
    data reaching one as a finding, regardless of how harmless the content looks."""

    @pytest.mark.parametrize(
        'exc',
        [
            ConnectionRefusedError('some detail that must never surface'),
            socket.timeout('some detail that must never surface'),
            ssl.SSLError('some detail that must never surface'),
            ValueError('some detail that must never surface'),
            RuntimeError('some detail that must never surface'),
        ],
    )
    def test_return_value_never_contains_the_exception_message_or_type(self, exc):
        description = mc._describe_probe_error(exc)
        assert 'some detail' not in description
        assert type(exc).__name__ not in description


class TestHealthCheck:

    def test_requires_a_url(self):
        assert MqttConnector({}).health_check() == {'reachable': False, 'modules': {}, 'error': 'url required'}

    def test_reports_reachability_and_module_toggles(self, monkeypatch):
        c = MqttConnector({'url': 'mqtt://b', 'modules': {'sky_conditions': {'enabled': True}}})
        monkeypatch.setattr(c, 'probe', lambda **kw: {'reachable': True, 'error': None})
        health = c.health_check()
        assert health['reachable'] is True
        assert health['modules']['sky_conditions'] == {'ok': True, 'detail': 'enabled'}
        assert health['modules']['weather_now'] == {'ok': False, 'detail': 'disabled'}
        assert 'error' not in health

    def test_unreachable_carries_the_probe_error(self, monkeypatch):
        c = MqttConnector({'url': 'mqtt://b', 'modules': {'sky_conditions': {'enabled': True}}})
        monkeypatch.setattr(c, 'probe', lambda **kw: {'reachable': False, 'error': 'connection refused'})
        health = c.health_check()
        assert health['reachable'] is False
        assert health['error'] == 'connection refused'
        assert health['modules']['sky_conditions']['ok'] is False


class TestImportBoundary:

    def test_connectors_package_imports_cleanly_after_cache_store(self):
        """cache/ and observation/ import connectors/ at module level; the MQTT modules must not
        import them back at module level, or a fresh interpreter hits a circular import."""
        import os
        import subprocess
        import sys

        backend = os.path.join(os.path.dirname(__file__), '..', '..', 'backend')
        code = (
            "import cache.cache_store, cache.cache_updater, observation.myastroshine_integration, "
            "connectors, connectors.mqtt_publisher, connectors.mqtt_payloads; print('ok')"
        )
        env = dict(os.environ)
        env.setdefault('DATA_DIR', os.environ.get('DATA_DIR', ''))
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=os.path.abspath(backend), capture_output=True, text=True, timeout=120, env=env
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().endswith('ok')

    def test_mqtt_connector_module_has_no_feature_package_imports(self):
        import ast
        import inspect

        from connectors import mqtt_connector

        tree = ast.parse(inspect.getsource(mqtt_connector))
        forbidden = ('cache', 'observation', 'skytonight', 'equipment', 'astroweather', 'weather', 'space', 'utils.auth')
        for node in tree.body:  # module level only - lazy imports inside functions are fine
            if isinstance(node, ast.ImportFrom):
                assert not node.module.startswith(forbidden), node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), alias.name
