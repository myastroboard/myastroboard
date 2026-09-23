"""Tests for connectors/mqtt_publisher.py - the background publisher.

The thread is normally never started: ``_tick()`` is driven by hand with a fake paho
client, a scripted config loader, synthetic devices in place of ``mqtt_payloads.collect``
and every file (lock, trigger, status, manifest) pointed at a per-test directory. The one
exception is the thread-lifecycle test itself, which needs a real ``start()``/``stop()``
round trip to prove the thread actually runs and joins cleanly.
"""

import json
import os
import time
from datetime import datetime, timezone

import pytest

from connectors import mqtt_publisher as pub
from connectors.mqtt_payloads import Device

NOW = datetime(2026, 9, 17, 20, 30, tzinfo=timezone.utc)


class _Reason:
    def __init__(self, failure=False, name="Success"):
        self.is_failure = failure
        self._name = name

    def __str__(self):
        return self._name


class _Info:
    def __init__(self, rc=0):
        self.rc = rc

    def wait_for_publish(self, timeout=None):
        return None


class FakeClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.published = []  # (topic, payload, qos, retain)
        self.subscribed = []
        self.will = None
        self.credentials = None
        self.tls = False
        self.insecure = False
        self.connect_target = None
        self.loop_started = False
        self.disconnected = False
        self.publish_rc = 0
        self.on_connect = self.on_disconnect = self.on_message = None
        self.connect_timeout = None

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def tls_set(self):
        self.tls = True

    def tls_insecure_set(self, value):
        self.insecure = value

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

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

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return _Info(self.publish_rc)

    # helpers
    def topics(self):
        return [p[0] for p in self.published]

    def last(self, topic):
        for entry in reversed(self.published):
            if entry[0] == topic:
                return entry
        return None

    def clear(self):
        self.published = []


def _device(kind, object_id, state, image_topic=None, image_id=None, image=None):
    base = "mab"
    dev_id = f"{base}_board" if kind == "board" else f"{base}_{'loc' if kind == 'location' else 'user'}_{object_id}"
    state_topic = f"{base}/board/state" if kind == "board" else f"{base}/{kind}/{object_id}/state"
    return Device(
        kind=kind,
        object_id=object_id,
        name=f"MyAstroBoard - {object_id or 'board'}",
        device_id=dev_id,
        discovery_topic=f"ha/device/{dev_id}/config",
        state_topic=state_topic,
        discovery={"dev": {"ids": [dev_id]}, "cmps": {k: {"p": "sensor"} for k in state}},
        state=dict(state),
        entity_count=len(state),
        image_topic=image_topic,
        image_id=image_id,
        image_loader=(lambda: image) if image_topic else None,
    )


def _config(enabled=True, **overrides):
    block = {
        "url": "mqtt://broker.lan:1883",
        "enabled": enabled,
        "username": "u",
        "base_topic": "mab",
        "discovery_prefix": "ha",
        "discovery_enabled": True,
        "publish_interval_seconds": 60,
        "modules": {"sky_conditions": {"enabled": True}, "board_diagnostics": {"enabled": True}},
    }
    block.update(overrides)
    return {"connectors": {"mqtt": block}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated files + a publisher whose collaborators are all scripted."""
    monkeypatch.setattr(pub, "LOCK_FILE", str(tmp_path / "lock"))
    monkeypatch.setattr(pub, "TRIGGER_FILE", str(tmp_path / "trigger.json"))
    monkeypatch.setattr(pub, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(pub, "MANIFEST_FILE", str(tmp_path / "manifest.json"))
    monkeypatch.setattr(pub, "DATA_DIR_CACHE", str(tmp_path))

    from utils import connector_secrets

    connector_secrets.save_secrets("mqtt", {"password": "pw"})

    state = {"config": _config(), "signature": ("a",), "devices": [], "clients": []}

    def factory(client_id):
        client = FakeClient(client_id)
        state["clients"].append(client)
        return client

    publisher = pub.MqttPublisher(client_factory=factory, config_loader=lambda: state["config"], clock=lambda: NOW)
    monkeypatch.setattr(publisher, "_current_source_signature", lambda: state["signature"])

    from connectors import mqtt_payloads

    monkeypatch.setattr(mqtt_payloads, "collect", lambda connector, config, info, now=None: list(state["devices"]))
    state["publisher"] = publisher
    return state


def _connect(env):
    """Run the tick that opens the connection, then simulate the broker's CONNACK."""
    publisher = env["publisher"]
    publisher._tick()
    client = env["clients"][-1]
    client.on_connect(client, None, {}, _Reason())
    return client


# ---------------------------------------------------------------------------
# Trigger / status file channel
# ---------------------------------------------------------------------------


class TestChannel:

    def test_request_action_writes_and_consume_reads_once(self, env):
        assert pub.request_action("publish") is True
        assert json.load(open(pub.TRIGGER_FILE))["action"] == "publish"
        assert pub._consume_trigger() == "publish"
        assert not os.path.exists(pub.TRIGGER_FILE)
        assert pub._consume_trigger() is None

    def test_unknown_action_is_refused_and_bad_file_is_dropped(self, env):
        assert pub.request_action("format-disk") is False
        with open(pub.TRIGGER_FILE, "w") as handle:
            handle.write("{broken")
        assert pub._consume_trigger() is None
        assert not os.path.exists(pub.TRIGGER_FILE)

    def test_read_status_defaults_and_merges_known_keys(self, env):
        assert pub.read_status() == pub.default_status()
        pub._write_json(pub.STATUS_FILE, {"connected": True, "devices": [{"kind": "board"}], "unknown_key": 1})
        status = pub.read_status()
        assert status["connected"] is True and status["devices"] == [{"kind": "board"}]
        assert "unknown_key" not in status

    def test_write_json_failure_is_reported(self, env, tmp_path):
        path = str(tmp_path / "file-not-dir" / "x.json")
        with open(str(tmp_path / "file-not-dir"), "w") as handle:
            handle.write("x")
        assert pub._write_json(path, {}) is False

    def test_consume_trigger_swallows_a_remove_failure(self, env, monkeypatch):
        pub.request_action("publish")
        monkeypatch.setattr(pub.os, "remove", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))

        assert pub._consume_trigger() == "publish"  # still reports the action it read


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:

    def test_disabled_connector_never_connects_but_writes_status(self, env):
        env["config"] = _config(enabled=False)
        env["publisher"]._tick()
        assert env["clients"] == []
        status = pub.read_status()
        assert status["enabled"] is False and status["configured"] is True
        assert status["broker"] == "mqtt://broker.lan:1883"
        assert status["user_modules_enabled"] is False

    def test_status_reports_whether_user_modules_are_enabled(self, env):
        env["config"] = _config(modules={"user_activity": {"enabled": True}})
        env["publisher"]._tick()
        assert pub.read_status()["user_modules_enabled"] is True
        env["config"] = _config(modules={"astrodex_image": {"enabled": True}})
        env["signature"] = ("img",)
        env["publisher"]._tick()
        assert pub.read_status()["user_modules_enabled"] is True

    def test_first_tick_connects_with_will_credentials_and_generated_client_id(self, env):
        env["publisher"]._tick()
        client = env["clients"][0]
        assert client.connect_target == ("broker.lan", 1883)
        assert client.loop_started is True
        assert client.credentials == ("u", "pw")  # password from the sidecar
        assert client.will == ("mab/status", "offline", 1, True)
        assert client.client_id.startswith("myastroboard-")
        assert client.tls is False
        assert client.connect_timeout == 5.0
        # The generated id is persisted so restarts reuse it
        assert json.load(open(pub.MANIFEST_FILE))["client_id"] == client.client_id
        assert pub.read_status()["connected"] is False

    def test_on_connect_publishes_online_subscribes_and_flags_a_full_cycle(self, env):
        client = _connect(env)
        assert client.last("mab/status") == ("mab/status", "online", 1, True)
        assert client.subscribed == [("ha/status", 0)]
        assert env["publisher"]._force_full is True

    def test_configured_client_id_and_tls_options_are_applied(self, env):
        env["config"] = _config(url="mqtts://broker.lan", client_id="my-board", tls_insecure=True)
        env["publisher"]._tick()
        client = env["clients"][0]
        assert client.client_id == "my-board" and client.tls is True and client.insecure is True
        assert client.connect_target == ("broker.lan", 8883)

    def test_tls_without_insecure_does_not_disable_certificate_verification(self, env):
        env["config"] = _config(url="mqtts://broker.lan", tls_insecure=False)
        env["publisher"]._tick()
        client = env["clients"][0]
        assert client.tls is True and client.insecure is False

    def test_anonymous_connection_sets_no_credentials(self, env):
        env["config"] = _config(username="")
        env["publisher"]._tick()
        client = env["clients"][0]
        assert client.credentials is None

    def test_refused_connack_records_an_error(self, env):
        env["publisher"]._tick()
        client = env["clients"][0]
        client.on_connect(client, None, {}, _Reason(failure=True, name="Not authorized"))
        env["publisher"]._tick()
        status = pub.read_status()
        assert status["connected"] is False
        assert "Not authorized" in status["last_error"]

    def test_disable_after_connect_publishes_offline_and_disconnects(self, env):
        client = _connect(env)
        env["config"] = _config(enabled=False)
        env["signature"] = ("b",)
        env["publisher"]._tick()
        assert client.last("mab/status") == ("mab/status", "offline", 1, True)
        assert client.disconnected is True and client.loop_started is False
        assert env["publisher"]._client is None
        assert pub.read_status()["connected"] is False

    def test_disconnect_swallows_a_wait_for_publish_timeout(self, env):
        client = _connect(env)
        publisher = env["publisher"]

        class _SlowInfo:
            rc = 0

            def wait_for_publish(self, timeout=None):
                raise RuntimeError("timed out")

        client.publish = lambda *a, **k: _SlowInfo()

        publisher._disconnect(publish_offline=True)  # must not raise

        assert publisher._connected is False

    def test_disconnect_swallows_loop_stop_or_disconnect_errors(self, env):
        client = _connect(env)
        publisher = env["publisher"]
        client.disconnect = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

        publisher._disconnect(publish_offline=True)  # must not raise

        assert publisher._client is None

    def test_unrelated_config_change_does_not_reconnect(self, env):
        client = _connect(env)
        env["config"] = _config(label="Renamed")
        env["signature"] = ("c",)
        env["publisher"]._tick()
        assert env["clients"] == [client]

    def test_relevant_config_change_reconnects(self, env):
        client = _connect(env)
        env["config"] = _config(base_topic="other")
        env["signature"] = ("d",)
        env["publisher"]._tick()
        assert len(env["clients"]) == 2
        assert client.disconnected is True

    def test_broken_url_records_error_without_client(self, env):
        env["config"] = _config(url="http://nope")
        env["publisher"]._tick()
        assert env["clients"] == []
        status = pub.read_status()
        assert status["configured"] is False and status["enabled"] is False

    def test_connect_records_a_broker_parse_error(self, env):
        """_tick() itself only ever calls _connect() once is_enabled() (which already
        validates the url) has passed, so this exercises _connect()'s own parse-error
        handling directly rather than through a URL that would never get this far."""
        from connectors.mqtt_connector import MqttConnector

        publisher = env["publisher"]
        connector = MqttConnector(_config()["connectors"]["mqtt"])
        connector.broker = lambda: (_ for _ in ()).throw(ValueError("bad url"))

        publisher._connect(connector)

        assert publisher._last_error == "bad url"
        assert publisher._client is None

    def test_client_factory_failure_is_an_error_not_a_crash(self, env, monkeypatch):
        def boom(client_id):
            raise RuntimeError("no paho")

        env["publisher"]._client_factory = boom
        env["publisher"]._tick()
        # The exception type is reported, never its message - this try block also hands the
        # broker credentials to paho, so the raw text must never reach the log or the status file.
        assert "RuntimeError" in pub.read_status()["last_error"]
        assert "no paho" not in pub.read_status()["last_error"]

    def test_config_loader_failure_keeps_going(self, env):
        def boom():
            raise RuntimeError("bad json")

        env["publisher"]._config_loader = boom
        env["publisher"]._tick()  # no connector yet -> nothing to do, nothing raised
        assert env["clients"] == []

    def test_on_connect_swallows_publish_or_subscribe_errors(self, env):
        publisher = env["publisher"]
        publisher._tick()
        client = env["clients"][0]
        client.subscribe = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))

        client.on_connect(client, None, {}, _Reason())  # must not raise

        assert publisher._connected is True  # still marked connected despite the subscribe failure

    def test_on_connect_without_a_connector_does_nothing(self, env):
        client = _connect(env)
        publisher = env["publisher"]
        publisher._connector = None
        client.clear()

        client.on_connect(client, None, {}, _Reason())  # must not raise

        assert client.published == []

    def test_on_message_ignored_without_a_connector(self, env):
        client = _connect(env)
        publisher = env["publisher"]
        publisher._connector = None

        # must not raise
        client.on_message(client, None, type("Msg", (), {"topic": "ha/status", "payload": b"online"})())

    def test_on_message_swallows_unexpected_errors(self, env):
        client = _connect(env)

        client.on_message(client, None, object())  # no .topic attribute - must not raise

    def test_on_disconnect_and_ha_birth_message(self, env):
        client = _connect(env)
        publisher = env["publisher"]
        publisher._force_full = False
        client.on_message(client, None, type("Msg", (), {"topic": "ha/status", "payload": b"online"})())
        assert publisher._force_full is True
        publisher._force_full = False
        client.on_message(client, None, type("Msg", (), {"topic": "ha/status", "payload": b"offline"})())
        assert publisher._force_full is False
        client.on_disconnect(client, None, {}, _Reason())
        assert publisher._connected is False

    def test_stop_publishes_offline_and_releases_lock(self, env):
        client = _connect(env)
        publisher = env["publisher"]
        assert publisher._acquire_lock() is True
        publisher.stop()
        assert client.last("mab/status") == ("mab/status", "offline", 1, True)
        assert client.disconnected is True
        assert not os.path.exists(pub.LOCK_FILE)

    def test_second_instance_cannot_take_the_lock(self, env):
        first = env["publisher"]
        assert first._acquire_lock() is True
        second = pub.MqttPublisher(
            client_factory=lambda cid: FakeClient(cid), config_loader=lambda: {}, clock=lambda: NOW
        )
        assert second._acquire_lock() is False
        assert second.start() is False
        first._release_lock()

    def test_acquire_lock_failure_is_reported(self, env, monkeypatch, tmp_path):
        monkeypatch.setattr(pub, "LOCK_FILE", str(tmp_path / "missing-dir" / "lock"))
        publisher = env["publisher"]

        assert publisher._acquire_lock() is False
        assert publisher._lock_file is None

    def test_acquire_lock_failure_after_opening_closes_the_file(self, env, monkeypatch):
        """A failure after open() (here, while writing the pid) must still close and
        drop the already-opened file handle, not leak it."""
        publisher = env["publisher"]
        monkeypatch.setattr(pub.os, "getpid", lambda: (_ for _ in ()).throw(OSError("pid unavailable")))

        assert publisher._acquire_lock() is False
        assert publisher._lock_file is None

    def test_release_lock_is_a_noop_when_never_acquired(self, env):
        publisher = env["publisher"]

        publisher._release_lock()  # must not raise

        assert publisher._has_lock is False

    def test_release_lock_skips_unlink_when_the_file_is_already_gone(self, env, monkeypatch):
        publisher = env["publisher"]
        assert publisher._acquire_lock() is True
        real_exists = os.path.exists
        monkeypatch.setattr(pub.os.path, "exists", lambda p: False if p == pub.LOCK_FILE else real_exists(p))

        publisher._release_lock()

        assert publisher._has_lock is False

    def test_release_lock_swallows_unlock_errors(self, env, monkeypatch):
        publisher = env["publisher"]
        assert publisher._acquire_lock() is True
        monkeypatch.setattr(pub.msvcrt, "locking", lambda *a, **k: (_ for _ in ()).throw(OSError("unlock failed")))

        publisher._release_lock()  # must not raise

        assert publisher._has_lock is False

    def test_release_lock_swallows_a_broken_logger_too(self, env, monkeypatch):
        """Best-effort logging during release: a log stream already closed at shutdown
        must not turn a harmless cleanup failure into a crash."""
        publisher = env["publisher"]
        assert publisher._acquire_lock() is True
        monkeypatch.setattr(pub.msvcrt, "locking", lambda *a, **k: (_ for _ in ()).throw(OSError("unlock failed")))
        monkeypatch.setattr(pub.logger, "error", lambda *a, **k: (_ for _ in ()).throw(ValueError("stream closed")))

        publisher._release_lock()  # must not raise even though logging itself fails

        assert publisher._has_lock is False

    def test_start_runs_the_background_thread_and_stop_joins_it(self, env):
        publisher = env["publisher"]

        assert publisher.start() is True
        assert publisher.thread.is_alive() is True

        publisher.stop()

        assert publisher.thread.is_alive() is False
        assert not os.path.exists(pub.LOCK_FILE)

    def test_run_exits_immediately_when_already_stopped(self, env):
        publisher = env["publisher"]
        publisher._stop_event.set()

        assert publisher.start() is True
        publisher.thread.join(timeout=2)

        assert publisher.thread.is_alive() is False
        publisher.stop()  # thread already finished; this just releases the lock

    def test_run_logs_and_continues_after_a_tick_exception(self, env, monkeypatch):
        monkeypatch.setattr(pub, "TICK_SECONDS", 0.02)
        publisher = env["publisher"]
        original_tick = publisher._tick
        calls = {"n": 0}

        def flaky_tick():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return original_tick()

        monkeypatch.setattr(publisher, "_tick", flaky_tick)

        assert publisher.start() is True
        for _ in range(100):
            if calls["n"] >= 3:
                break
            time.sleep(0.02)
        publisher.stop()

        assert calls["n"] >= 3  # the loop kept going past the first tick's exception
        assert "boom" in (publisher._last_error or "")

    def test_module_start_and_stop(self, env, monkeypatch):
        started = {}

        class _Fake:
            def __init__(self):
                self.thread = type("T", (), {"is_alive": lambda self: False})()

            def start(self):
                started["yes"] = True
                return True

            def stop(self):
                started["stopped"] = True

        monkeypatch.setattr(pub, "MqttPublisher", _Fake)
        monkeypatch.setattr(pub, "_publisher", None)
        assert pub.start() is True
        assert started["yes"] is True
        pub.stop()
        assert started["stopped"] is True
        assert pub._publisher is None

    def test_module_start_is_a_noop_when_already_running(self, env, monkeypatch):
        publisher = env["publisher"]
        assert publisher.start() is True
        monkeypatch.setattr(pub, "_publisher", publisher)

        try:
            assert pub.start() is True  # sees the already-alive thread, starts nothing new
        finally:
            publisher.stop()

    def test_module_start_returns_false_when_the_lock_is_held_elsewhere(self, env, monkeypatch):
        holder = env["publisher"]
        assert holder._acquire_lock() is True  # simulates another process/instance owning it
        monkeypatch.setattr(pub, "_publisher", None)

        try:
            assert pub.start() is False
            assert pub._publisher is None
        finally:
            holder._release_lock()

    def test_module_stop_is_a_noop_when_nothing_is_running(self, monkeypatch):
        monkeypatch.setattr(pub, "_publisher", None)

        pub.stop()  # must not raise

        assert pub._publisher is None


# ---------------------------------------------------------------------------
# Publish cycles
# ---------------------------------------------------------------------------


class TestPublishCycle:

    def test_publish_cycle_is_a_noop_without_a_connector_or_client(self, env):
        publisher = env["publisher"]
        publisher._connector = None

        publisher._publish_cycle(force_full=True)  # must not raise

    def test_publish_with_no_client_returns_false(self, env):
        publisher = env["publisher"]
        assert publisher._client is None

        assert publisher._publish("some/topic", "x", qos=0, retain=False) is False

    def test_first_cycle_publishes_discovery_states_and_manifest(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1}), _device("board", "", {"version": "1.6.0"})]
        client = _connect(env)
        client.clear()
        env["publisher"]._tick()
        assert client.last("ha/device/mab_loc_loc-1/config")[2:] == (1, True)
        assert json.loads(client.last("ha/device/mab_loc_loc-1/config")[1])["dev"] == {"ids": ["mab_loc_loc-1"]}
        assert client.last("mab/location/loc-1/state") == ("mab/location/loc-1/state", '{"a":1}', 0, True)
        assert client.last("mab/board/state")[1] == '{"version":"1.6.0"}'
        manifest = json.load(open(pub.MANIFEST_FILE))
        assert manifest["discovery"] == ["ha/device/mab_board/config", "ha/device/mab_loc_loc-1/config"]
        assert manifest["state"] == ["mab/board/state", "mab/location/loc-1/state"]
        status = pub.read_status()
        assert status["connected"] is True
        assert status["last_publish_at"] == "2026-09-17T20:30:00+00:00"
        assert [d["kind"] for d in status["devices"]] == ["location", "board"]
        assert status["messages_total"] == 4  # 2 discovery + 2 states (availability is sent from on_connect, uncounted)

    def test_unchanged_second_cycle_publishes_nothing(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        publisher._next_due = 0  # force "due" without waiting the interval
        publisher._tick()
        assert client.published == []

    def test_changed_state_publishes_only_the_state(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        env["devices"] = [_device("location", "loc-1", {"a": 2})]
        publisher._next_due = 0
        publisher._tick()
        assert client.topics() == ["mab/location/loc-1/state"]

    def test_not_due_means_no_cycle(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        env["devices"] = [_device("location", "loc-1", {"a": 2})]
        publisher._tick()  # next_due is 60 s away
        assert client.published == []

    def test_ha_birth_forces_a_full_republish(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        client.on_message(client, None, type("Msg", (), {"topic": "ha/status", "payload": b"online"})())
        publisher._tick()
        assert set(client.topics()) == {"ha/device/mab_loc_loc-1/config", "mab/location/loc-1/state"}

    def test_publish_trigger_forces_a_full_republish(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        pub.request_action("publish")
        publisher._tick()
        assert "ha/device/mab_loc_loc-1/config" in client.topics()

    def test_periodic_full_refresh(self, env, monkeypatch):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        publisher._last_full -= 31 * 60
        publisher._tick()
        assert "ha/device/mab_loc_loc-1/config" in client.topics()

    def test_removed_device_gets_empty_retained_payloads(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1}), _device("location", "loc-2", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        publisher._next_due = 0
        publisher._tick()
        assert client.last("ha/device/mab_loc_loc-2/config") == ("ha/device/mab_loc_loc-2/config", None, 1, True)
        assert client.last("mab/location/loc-2/state") == ("mab/location/loc-2/state", None, 1, True)
        manifest = json.load(open(pub.MANIFEST_FILE))
        assert manifest["discovery"] == ["ha/device/mab_loc_loc-1/config"]

    def test_discovery_off_publishes_states_only_and_clears_old_discovery(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        env["config"] = _config(discovery_enabled=False)
        env["signature"] = ("e",)
        publisher._tick()  # reconnect
        client2 = env["clients"][-1]
        client2.on_connect(client2, None, {}, _Reason())
        publisher._tick()
        assert client2.last("ha/device/mab_loc_loc-1/config") == ("ha/device/mab_loc_loc-1/config", None, 1, True)
        assert client2.last("mab/location/loc-1/state")[1] == '{"a":1}'

    def test_manifest_survives_a_restart_for_cleanup(self, env, tmp_path):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        env["publisher"]._tick()
        # A fresh publisher (new process) loads the manifest and clears what is no longer wanted
        env["devices"] = []
        fresh = pub.MqttPublisher(
            client_factory=lambda cid: FakeClient(cid), config_loader=lambda: env["config"], clock=lambda: NOW
        )
        fresh._current_source_signature = lambda: ("z",)
        assert fresh._manifest["discovery"] == ["ha/device/mab_loc_loc-1/config"]
        assert fresh._generated_client_id == client.client_id
        fresh._tick()
        c2 = fresh._client
        c2.on_connect(c2, None, {}, _Reason())
        fresh._tick()
        assert c2.last("ha/device/mab_loc_loc-1/config") == ("ha/device/mab_loc_loc-1/config", None, 1, True)

    def test_publish_error_is_recorded(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        client.publish_rc = 4
        env["publisher"]._tick()
        assert "rc=4" in pub.read_status()["last_error"]

    def test_publish_exception_is_recorded(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)

        def boom(*a, **k):
            raise RuntimeError("socket gone")

        client.publish = boom
        env["publisher"]._tick()
        assert "socket gone" in pub.read_status()["last_error"]

    def test_state_json_is_compact_sorted_and_survives_non_json_values(self, env):
        env["devices"] = [_device("location", "loc-1", {"b": NOW, "a": None})]
        client = _connect(env)
        env["publisher"]._tick()
        assert client.last("mab/location/loc-1/state")[1] == '{"a":null,"b":"2026-09-17 20:30:00+00:00"}'


class TestImages:

    def test_image_published_once_per_picture_id(self, env):
        env["devices"] = [
            _device(
                "user", "u-1", {"x": 1}, image_topic="mab/user/u-1/astrodex/latest_image", image_id="p1", image=b"JPG1"
            )
        ]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        assert client.last("mab/user/u-1/astrodex/latest_image") == (
            "mab/user/u-1/astrodex/latest_image",
            b"JPG1",
            1,
            True,
        )
        client.clear()
        publisher._next_due = 0
        publisher._tick()
        assert client.published == []  # same picture id -> nothing
        env["devices"] = [
            _device(
                "user", "u-1", {"x": 1}, image_topic="mab/user/u-1/astrodex/latest_image", image_id="p2", image=b"JPG2"
            )
        ]
        publisher._next_due = 0
        publisher._tick()
        assert client.last("mab/user/u-1/astrodex/latest_image")[1] == b"JPG2"
        assert json.load(open(pub.MANIFEST_FILE))["image_ids"] == {"mab/user/u-1/astrodex/latest_image": "p2"}

    def test_failed_encoding_keeps_the_previous_picture(self, env):
        topic = "mab/user/u-1/astrodex/latest_image"
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p1", image=b"JPG1")]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p2", image=None)]
        publisher._next_due = 0
        publisher._tick()
        assert client.last(topic) is None  # neither republished nor cleared
        assert json.load(open(pub.MANIFEST_FILE))["image"] == [topic]

    def test_first_ever_failed_encoding_leaves_the_topic_out_entirely(self, env):
        """Distinct from the case above: with no previous picture to keep, there is
        nothing to add to 'desired' either - the topic must simply be absent."""
        topic = "mab/user/u-1/astrodex/latest_image"
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p1", image=None)]
        client = _connect(env)
        publisher = env["publisher"]

        publisher._tick()

        assert client.last(topic) is None
        assert topic not in publisher._manifest.get("image", [])

    def test_image_publish_failure_does_not_record_the_picture_id(self, env, monkeypatch):
        topic = "mab/user/u-1/astrodex/latest_image"
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p1", image=b"JPG1")]
        _connect(env)
        publisher = env["publisher"]
        monkeypatch.setattr(publisher, "_publish", lambda *a, **k: False)

        publisher._tick()

        assert publisher._image_ids.get(topic) is None

    def test_no_picture_anymore_clears_the_retained_image(self, env):
        topic = "mab/user/u-1/astrodex/latest_image"
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p1", image=b"JPG1")]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic)]
        publisher._next_due = 0
        publisher._tick()
        assert client.last(topic) == (topic, None, 1, True)

    def test_full_cycle_republishes_the_image(self, env):
        topic = "mab/user/u-1/astrodex/latest_image"
        env["devices"] = [_device("user", "u-1", {"x": 1}, image_topic=topic, image_id="p1", image=b"JPG1")]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        pub.request_action("publish")
        publisher._tick()
        assert client.last(topic)[1] == b"JPG1"


class TestRemove:

    def test_remove_trigger_purges_everything_and_republishes_if_still_enabled(self, env):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        client.clear()
        pub.request_action("remove")
        publisher._tick()
        cleared = [p for p in client.published if p[1] is None]
        assert {p[0] for p in cleared} == {"ha/device/mab_loc_loc-1/config", "mab/location/loc-1/state"}
        # still enabled: the same tick republished after the purge
        assert client.last("mab/location/loc-1/state")[1] == '{"a":1}'
        assert json.load(open(pub.MANIFEST_FILE))["discovery"] == ["ha/device/mab_loc_loc-1/config"]

    def test_remove_when_disabled_connects_purges_then_disconnects(self, env, monkeypatch):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        client = _connect(env)
        publisher = env["publisher"]
        publisher._tick()
        # Disable and request removal in the same round (what the route does)
        env["config"] = _config(enabled=False)
        env["signature"] = ("f",)
        pub.request_action("remove")
        monkeypatch.setattr(pub, "CONNECT_WAIT_SECONDS", 0.01)
        # The publisher is still connected from before, so the purge runs immediately
        publisher._tick()
        cleared = {p[0] for p in client.published if p[1] is None}
        assert "ha/device/mab_loc_loc-1/config" in cleared
        assert client.disconnected is True
        assert json.load(open(pub.MANIFEST_FILE))["discovery"] == []

    def test_remove_without_broker_records_error(self, env, monkeypatch):
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        publisher = env["publisher"]
        monkeypatch.setattr(pub, "CONNECT_WAIT_SECONDS", 0.01)
        pub.request_action("remove")
        publisher._tick()  # connects, but no CONNACK ever arrives
        assert "not reachable" in pub.read_status()["last_error"]

    def test_remove_without_connector_is_ignored(self, env):
        env["publisher"]._remove_all(None)  # no crash

    def test_remove_waits_for_an_already_connecting_client_without_reconnecting(self, env, monkeypatch):
        """A client object can already exist but not be connected yet (CONNACK still
        pending) - remove must just wait for it, not throw it away and reconnect."""
        env["devices"] = [_device("location", "loc-1", {"a": 1})]
        publisher = env["publisher"]
        publisher._tick()  # opens a client, but CONNACK is never simulated
        client = env["clients"][-1]
        monkeypatch.setattr(pub, "CONNECT_WAIT_SECONDS", 0.01)

        pub.request_action("remove")
        publisher._tick()

        assert env["clients"] == [client]  # no second client was created
        assert "not reachable" in pub.read_status()["last_error"]


# ---------------------------------------------------------------------------
# Real (non-injected) defaults
# ---------------------------------------------------------------------------


class TestDefaults:

    def test_default_client_factory_builds_a_real_paho_client(self):
        import paho.mqtt.client as mqtt

        client = pub.MqttPublisher._default_client_factory("test-client-id")

        assert isinstance(client, mqtt.Client)

    def test_default_config_loader_reads_real_config(self):
        config = pub.MqttPublisher._default_config_loader()

        assert isinstance(config, dict)

    def test_current_source_signature_reflects_file_mtimes(self, tmp_path, monkeypatch):
        from utils import connector_secrets

        monkeypatch.setattr(pub, "CONFIG_FILE", str(tmp_path / "config.json"))
        monkeypatch.setattr(connector_secrets, "_SECRETS_FILE", str(tmp_path / "secrets.json"))

        assert pub.MqttPublisher._current_source_signature() == (None, None)

        (tmp_path / "config.json").write_text("{}")

        signature = pub.MqttPublisher._current_source_signature()
        assert signature[0] is not None and signature[1] is None
