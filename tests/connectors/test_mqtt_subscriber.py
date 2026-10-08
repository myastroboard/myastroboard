"""Tests for connectors/mqtt_subscriber.py - the background thread that listens to MQTT topics.

The thread is normally never started: ``_tick()`` is driven by hand with a fake paho client, a
scripted config loader, a stub registry and every file (lock, status, last messages) pointed at a
per-test directory. The lifecycle test alone runs a real ``start()`` / ``stop()``.
"""

import json
import types

import pytest

from connectors import mqtt_subscriber as sub
from connectors.base_connector import BaseConnector


class _Reason:
    def __init__(self, failure=False, name="Success"):
        self.is_failure = failure
        self._name = name

    def __str__(self):
        return self._name


class FakeClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.credentials = None
        self.tls = False
        self.insecure = False
        self.connect_target = None
        self.loop_started = False
        self.disconnected = False
        self.subscribed = []
        self.connect_timeout = None
        self.on_connect = self.on_disconnect = self.on_message = None

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def tls_set(self):
        self.tls = True

    def tls_insecure_set(self, value):
        self.insecure = value

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self.reconnect = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive=60):
        self.connect_target = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_started = False

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))


class _Listener(BaseConnector):
    """A connector that reads one topic through its connection while enabled."""

    name = "listener"
    CONNECTION_FIELD = "mqtt_connection_id"
    CONFIG_FIELDS = {"mqtt_connection_id": "", "topic": "sky", "client_id": ""}

    def is_configured(self):
        return bool(self.connection)

    def health_check(self):
        return {"reachable": False, "modules": {}}

    def mqtt_subscriptions(self):
        return [self.config.get("topic", "sky")] if self.config.get("enabled") else []


class _Plain(BaseConnector):
    """A connector without a connection: never subscribed."""

    name = "plain"

    def health_check(self):
        return {"reachable": False, "modules": {}}


class _Broken(_Listener):
    name = "broken"

    def mqtt_subscriptions(self):
        raise RuntimeError("boom")


REGISTRY = {"listener": _Listener, "plain": _Plain}


def _config(enabled=True, url="mqtt://broker.lan:1883", username="u", tls_insecure=False, **block):
    listener = {"mqtt_connection_id": "c1", "enabled": enabled}
    listener.update(block)
    return {
        "connectors": {"listener": listener, "plain": {"url": "http://x"}},
        "mqtt_connections": [
            {"id": "c1", "name": "Home", "url": url, "username": username, "tls_insecure": tls_insecure}
        ],
    }


class _Message:
    def __init__(self, payload, topic="sky"):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.topic = topic


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sub, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(sub, "LOCK_FILE", str(tmp_path / "lock"))
    monkeypatch.setattr(sub, "STATUS_FILE", str(tmp_path / "status.json"))

    from utils.connector_secrets import save_secrets

    save_secrets("mqtt_connection:c1", {"password": "pw"})

    state = {"config": _config(), "signature": ("a",), "clients": [], "registry": dict(REGISTRY)}

    def factory(client_id):
        client = FakeClient(client_id)
        state["clients"].append(client)
        return client

    subscriber = sub.MqttSubscriber(
        client_factory=factory, config_loader=lambda: state["config"], registry=state["registry"]
    )
    monkeypatch.setattr(subscriber, "_current_source_signature", lambda: state["signature"])
    state["subscriber"] = subscriber
    return state


def _connected(env):
    """Tick once, then simulate the broker's CONNACK on the new client."""
    env["subscriber"]._tick()
    client = env["clients"][-1]
    client.on_connect(client, None, {}, _Reason())
    return client


# ---------------------------------------------------------------------------
# Payload parsing and files
# ---------------------------------------------------------------------------


class TestParsePayload:
    def test_flat_object_keeps_scalars_only(self):
        payload, reason = sub.parse_payload(
            json.dumps(
                {"AS_TEMP": 20.5, "ok": True, "name": "x", "none": None, "nested": {"a": 1}, "list": [1]}
            ).encode()
        )
        assert reason is None
        assert payload == {"AS_TEMP": 20.5, "ok": True, "name": "x", "none": None}

    @pytest.mark.parametrize(
        "raw, reason",
        [
            (b"x" * (sub.MAX_PAYLOAD_BYTES + 1), "message too large"),
            (b"not json", "message is not JSON"),
            (b"\xff\xfe", "message is not JSON"),
            (b"[1, 2]", "message is not a JSON object"),
            (json.dumps({f"k{i}": i for i in range(sub.MAX_PAYLOAD_KEYS + 1)}).encode(), "message has too many keys"),
        ],
        ids=["too-large", "not-json", "not-utf8", "not-object", "too-many-keys"],
    )
    def test_refused_payloads(self, raw, reason):
        assert sub.parse_payload(raw) == (None, reason)


class TestFiles:
    def test_last_message_file_only_for_safe_names(self, env):
        assert sub.last_message_file("allsky").endswith("mqtt_last_allsky.json")
        assert sub.last_message_file("../etc") is None
        assert sub.last_message_file("") is None

    def test_read_last_message_round_trip_and_rejections(self, env):
        assert sub.read_last_message("allsky") is None
        sub._write_json(sub.last_message_file("allsky"), {"topic": "t", "received_at": "x", "payload": {"a": 1}})
        assert sub.read_last_message("allsky")["payload"] == {"a": 1}
        sub._write_json(sub.last_message_file("allsky"), {"topic": "t", "payload": "not a dict"})
        assert sub.read_last_message("allsky") is None
        assert sub.read_last_message("../x") is None

    def test_read_status_defaults(self, env):
        assert sub.read_status() == {"connectors": {}, "updated_at": None}
        sub._write_json(sub.STATUS_FILE, {"connectors": "junk", "updated_at": "t"})
        assert sub.read_status() == {"connectors": {}, "updated_at": "t"}

    def test_write_failure_is_reported_not_raised(self, env, monkeypatch):
        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(sub.os, "replace", _boom)
        assert sub._write_json(sub.STATUS_FILE, {"a": 1}) is False


# ---------------------------------------------------------------------------
# Wanted subscriptions
# ---------------------------------------------------------------------------


class TestWantedSubscriptions:
    def test_connector_with_a_connection_and_topics_is_wanted(self, env):
        wanted = env["subscriber"]._wanted_subscriptions()
        assert list(wanted) == ["listener"]
        subscription = wanted["listener"]
        assert subscription.topics == ("sky",)
        assert subscription.password == "pw"
        assert subscription.connection["url"] == "mqtt://broker.lan:1883"

    def test_generated_client_id_is_per_connector_and_stable(self, env):
        first = env["subscriber"]._wanted_subscriptions()["listener"].client_id
        again = env["subscriber"]._wanted_subscriptions()["listener"].client_id
        assert first == again and first.startswith("myastroboard-listener-")

    def test_configured_client_id_wins(self, env):
        env["config"] = _config(client_id="sky-1")
        assert env["subscriber"]._wanted_subscriptions()["listener"].client_id == "sky-1"

    def test_nothing_wanted_without_topics_or_connection(self, env):
        env["config"] = _config(enabled=False)
        assert env["subscriber"]._wanted_subscriptions() == {}
        env["config"] = _config(mqtt_connection_id="gone")
        assert env["subscriber"]._wanted_subscriptions() == {}

    def test_a_failing_connector_is_skipped(self, env):
        env["registry"]["broken"] = _Broken
        env["config"]["connectors"]["broken"] = {"mqtt_connection_id": "c1", "enabled": True}
        assert list(env["subscriber"]._wanted_subscriptions()) == ["listener"]

    def test_unsafe_registry_names_are_skipped(self, env):
        env["registry"]["Bad-Name"] = _Listener
        env["config"]["connectors"]["Bad-Name"] = {"mqtt_connection_id": "c1", "enabled": True}
        assert list(env["subscriber"]._wanted_subscriptions()) == ["listener"]

    def test_config_load_failure_keeps_the_current_subscriptions(self, env):
        env["subscriber"]._tick()

        def _boom():
            raise RuntimeError("db gone")

        env["subscriber"]._config_loader = _boom
        assert list(env["subscriber"]._wanted_subscriptions()) == ["listener"]

    def test_default_registry_is_the_connectors_registry(self):
        from connectors import REGISTRY

        names = [name for name, _cls in sub.MqttSubscriber()._registry_items()]
        assert names == list(REGISTRY)


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnection:
    def test_tick_connects_with_credentials_then_subscribes_on_connack(self, env):
        client = _connected(env)
        assert client.connect_target == ("broker.lan", 1883)
        assert client.credentials == ("u", "pw")
        assert client.tls is False and client.loop_started is True
        assert client.subscribed == [("sky", 1)]
        state = env["subscriber"].status()["connectors"]["listener"]
        assert state["connected"] is True
        assert state["broker"] == "mqtt://broker.lan:1883"
        assert state["topics"] == ["sky"]

    def test_tls_and_insecure_follow_the_connection(self, env):
        env["config"] = _config(url="mqtts://broker.lan", tls_insecure=True)
        client = _connected(env)
        assert client.connect_target == ("broker.lan", 8883)
        assert client.tls is True and client.insecure is True

    def test_anonymous_connection_sets_no_credentials(self, env):
        env["config"] = _config(username="")
        assert _connected(env).credentials is None

    def test_bad_broker_url_records_an_error(self, env):
        env["config"] = _config(url="http://nope")
        env["subscriber"]._tick()
        assert env["clients"] == []
        assert env["subscriber"].status()["connectors"]["listener"]["last_error"].startswith("url must start with")

    def test_client_factory_failure_is_an_error_not_a_crash(self, env):
        def _boom(client_id):
            raise ValueError("bad id")

        env["subscriber"]._client_factory = _boom
        env["subscriber"]._tick()
        assert env["subscriber"].status()["connectors"]["listener"]["last_error"] == "connect: ValueError"

    def test_unchanged_signature_does_nothing(self, env):
        env["subscriber"]._tick()
        env["subscriber"]._tick()
        assert len(env["clients"]) == 1

    def test_relevant_change_reconnects(self, env):
        first = _connected(env)
        env["config"] = _config(topic="sky/other")
        env["signature"] = ("b",)
        env["subscriber"]._tick()
        assert first.disconnected is True
        assert len(env["clients"]) == 2

    def test_unrelated_config_change_keeps_the_client(self, env):
        first = _connected(env)
        env["config"]["connectors"]["plain"]["url"] = "http://y"
        env["signature"] = ("b",)
        env["subscriber"]._tick()
        assert first.disconnected is False and len(env["clients"]) == 1

    def test_connector_turned_off_disconnects_and_forgets_its_state(self, env):
        first = _connected(env)
        env["config"] = _config(enabled=False)
        env["signature"] = ("b",)
        env["subscriber"]._tick()
        assert first.disconnected is True
        assert env["subscriber"].status()["connectors"] == {}

    def test_refused_connack_records_an_error(self, env):
        env["subscriber"]._tick()
        client = env["clients"][-1]
        client.on_connect(client, None, {}, _Reason(failure=True, name="Not authorized"))
        state = env["subscriber"].status()["connectors"]["listener"]
        assert state["connected"] is False
        assert state["last_error"] == "broker refused the connection: Not authorized"
        assert client.subscribed == []

    def test_integer_refusal_code_is_an_error_too(self, env):
        env["subscriber"]._tick()
        client = env["clients"][-1]
        client.on_connect(client, None, {}, 5)
        assert env["subscriber"].status()["connectors"]["listener"]["last_error"].endswith(": 5")

    def test_subscribe_failure_is_recorded(self, env):
        env["subscriber"]._tick()
        client = env["clients"][-1]

        def _boom(topic, qos=0):
            raise OSError("socket closed")

        client.subscribe = _boom
        client.on_connect(client, None, {}, _Reason())
        assert env["subscriber"].status()["connectors"]["listener"]["last_error"] == "subscribe failed: OSError"

    def test_on_connect_after_the_subscription_went_away_does_nothing_more(self, env):
        env["subscriber"]._tick()
        client = env["clients"][-1]
        env["subscriber"]._subscriptions.clear()
        client.on_connect(client, None, {}, _Reason())
        assert client.subscribed == []

    def test_disconnect_callback_marks_disconnected(self, env):
        client = _connected(env)
        client.on_disconnect(client, None, {}, _Reason(failure=True, name="Unspecified error"))
        assert env["subscriber"].status()["connectors"]["listener"]["connected"] is False

    def test_disconnect_swallows_client_errors(self, env):
        client = _connected(env)

        def _boom():
            raise OSError("gone")

        client.loop_stop = _boom
        env["subscriber"]._disconnect("listener")
        assert "listener" not in env["subscriber"]._clients
        env["subscriber"]._disconnect("listener")  # already gone: no-op


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TestMessages:
    def test_valid_message_is_stored_as_the_last_one(self, env):
        client = _connected(env)
        client.on_message(client, None, _Message({"AS_TEMP": 20.5, "utc": 1}))
        stored = sub.read_last_message("listener")
        assert stored["topic"] == "sky"
        assert stored["payload"] == {"AS_TEMP": 20.5, "utc": 1}
        assert stored["received_at"]
        state = env["subscriber"].status()["connectors"]["listener"]
        assert state["messages_total"] == 1 and state["last_message_at"] == stored["received_at"]

    def test_invalid_message_is_ignored_and_reported(self, env):
        client = _connected(env)
        client.on_message(client, None, _Message(b"not json"))
        assert sub.read_last_message("listener") is None
        assert env["subscriber"].status()["connectors"]["listener"]["last_error"] == (
            "ignored a message on sky: message is not JSON"
        )

    def test_handling_failure_never_reaches_paho(self, env, monkeypatch):
        client = _connected(env)
        monkeypatch.setattr(sub, "parse_payload", lambda raw: (_ for _ in ()).throw(RuntimeError("boom")))
        client.on_message(client, None, _Message({"a": 1}))  # must not raise
        assert sub.read_last_message("listener") is None


# ---------------------------------------------------------------------------
# Status file, defaults, lifecycle
# ---------------------------------------------------------------------------


class TestStatusAndLifecycle:
    def test_status_file_written_only_when_it_changes(self, env, monkeypatch):
        writes = []
        real = sub._write_json
        monkeypatch.setattr(sub, "_write_json", lambda path, payload: writes.append(path) or real(path, payload))
        env["subscriber"]._tick()
        env["subscriber"]._tick()
        assert writes.count(sub.STATUS_FILE) == 1
        assert sub.read_status()["connectors"]["listener"]["client_id"].startswith("myastroboard-listener-")

    def test_source_signature_reflects_the_stores_and_survives_errors(self, monkeypatch):
        from utils import repo_config

        assert sub.MqttSubscriber._current_source_signature() != (None, None)
        monkeypatch.setattr(repo_config, "config_revision", lambda: (_ for _ in ()).throw(OSError("db gone")))
        assert sub.MqttSubscriber._current_source_signature() == (None, None)

    def test_default_config_loader_reads_the_real_config(self):
        assert isinstance(sub.MqttSubscriber._default_config_loader(), dict)

    def test_default_factory_builds_a_paho_v2_client(self):
        import paho.mqtt.client as mqtt

        assert isinstance(sub.MqttSubscriber._default_client_factory("x"), mqtt.Client)

    def test_tick_failure_is_logged_and_the_loop_goes_on(self, env, monkeypatch):
        subscriber = env["subscriber"]
        calls = []

        def _tick():
            calls.append(1)
            subscriber._stop_event.set()
            raise RuntimeError("boom")

        monkeypatch.setattr(subscriber, "_tick", _tick)
        subscriber._run()
        assert calls == [1]

    def test_start_stop_holds_the_lock_and_disconnects(self, env):
        subscriber = env["subscriber"]
        assert subscriber.start() is True
        other = sub.MqttSubscriber(client_factory=FakeClient, config_loader=lambda: {}, registry={})
        assert other.start() is False  # the lock is held
        subscriber._subscriptions.clear()
        subscriber.stop()
        assert not subscriber.thread.is_alive()
        assert subscriber._has_lock is False

    def test_module_level_start_and_stop(self, env, monkeypatch):
        started = []

        class _Fake:
            def __init__(self):
                self.thread = types.SimpleNamespace(is_alive=lambda: True)

            def start(self):
                started.append(self)
                return True

            def stop(self):
                started.remove(self)

        monkeypatch.setattr(sub, "MqttSubscriber", _Fake)
        monkeypatch.setattr(sub, "_subscriber", None)
        assert sub.start() is True
        assert sub.start() is True  # already running: no second instance
        assert len(started) == 1
        sub.stop()
        assert started == []

    def test_module_level_start_reports_a_lost_lock(self, monkeypatch):
        class _Loser:
            def __init__(self):
                self.thread = types.SimpleNamespace(is_alive=lambda: False)

            def start(self):
                return False

        monkeypatch.setattr(sub, "MqttSubscriber", _Loser)
        monkeypatch.setattr(sub, "_subscriber", None)
        assert sub.start() is False
