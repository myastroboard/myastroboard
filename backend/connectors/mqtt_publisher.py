"""
MQTT publisher - the background thread behind the MQTT / Home Assistant connector.

Same runtime shape as the push scheduler: one daemon thread per install (a lock file under
``DATA_DIR/cache`` keeps the second gunicorn worker out), started from ``app.py``, stopped at
exit. It wakes every ``TICK_SECONDS`` and, when the connector is enabled, keeps a paho client
connected and runs a publish cycle every ``publish_interval_seconds``:

1. ``mqtt_payloads.collect`` builds the devices (locations, opted-in users, the board);
2. discovery messages are (re)published when they changed, states when their JSON changed,
   the image when the picture behind it changed - or everything on a *full* cycle (first
   connect, Home Assistant birth message, config change, "publish now", periodic refresh);
3. every topic published is recorded in a manifest; topics the previous cycle published and
   this one no longer wants (module off, user opted out, location gone) receive an empty
   retained payload, which is how a retained message is deleted and how Home Assistant drops
   a discovered device;
4. a status file is written for ``GET /api/connectors/mqtt/status`` (any worker can read it).

The routes talk to the thread through a trigger file (``publish`` / ``remove``), never
in-process: the worker that serves the request is not necessarily the one owning the thread.

Feature packages are only reached through ``mqtt_payloads`` (lazy imports) - see
``mqtt_connector.py`` for why ``connectors/`` must not import them at module level.
"""

import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from connectors.mqtt_connector import MqttConnector
from utils.connector_secrets import merge_secrets
from utils.constants import CONFIG_FILE, DATA_DIR_CACHE
from utils.logging_config import get_logger

# Windows-compatible file locking (same split as cache_scheduler.py)
if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover
    import fcntl

logger = get_logger(__name__)

TICK_SECONDS = 5
CONNECT_WAIT_SECONDS = 10  # how long a synchronous "remove" waits for the broker

LOCK_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_publisher.lock")
TRIGGER_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_publisher.trigger")
STATUS_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_publisher_status.json")
MANIFEST_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_publisher_manifest.json")

_ACTIONS = ("publish", "remove")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def _write_json(path: str, payload: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        logger.error(f"MQTT publisher: could not write {path}: {exc}")
        return False


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Cross-worker channel: trigger file (routes -> thread) and status file (thread -> routes)
# ---------------------------------------------------------------------------


def request_action(action: str) -> bool:
    """Ask the owning thread for a ``publish`` (full republish) or ``remove`` (purge)."""
    if action not in _ACTIONS:
        return False
    return _write_json(TRIGGER_FILE, {"action": action, "requested_at": _iso(_now())})


def _consume_trigger() -> Optional[str]:
    data = _read_json(TRIGGER_FILE)
    if data is None and not os.path.exists(TRIGGER_FILE):
        return None
    try:
        os.remove(TRIGGER_FILE)
    except OSError:
        pass
    action = (data or {}).get("action")
    return action if action in _ACTIONS else None


def default_status() -> Dict[str, Any]:
    return {
        "enabled": False,
        "configured": False,
        "connected": False,
        "broker": None,
        "client_id": None,
        "discovery_enabled": True,
        "user_modules_enabled": False,
        "last_publish_at": None,
        "last_error": None,
        "last_error_at": None,
        "devices": [],
        "messages_total": 0,
        "updated_at": None,
    }


def read_status() -> Dict[str, Any]:
    """The last status the publisher thread wrote, or an idle default."""
    status = default_status()
    stored = _read_json(STATUS_FILE)
    if stored:
        status.update({k: v for k, v in stored.items() if k in status})
    return status


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class MqttPublisher:
    """One instance per process; ``start()`` only wins in the worker that gets the lock."""

    def __init__(
        self,
        client_factory: Optional[Callable[[str], Any]] = None,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._client_factory = client_factory or self._default_client_factory
        self._config_loader = config_loader or self._default_config_loader
        self._clock = clock or _now

        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="mqtt-publisher")
        self._lock_file = None
        self._has_lock = False

        self._client: Any = None
        self._connected = False
        self._force_full = False
        self._connector: Optional[MqttConnector] = None
        self._config: Dict[str, Any] = {}
        self._source_signature: Any = None
        self._next_due: float = 0.0
        self._last_full: float = 0.0
        self._published: Dict[str, str] = {}
        self._image_ids: Dict[str, str] = {}
        self._manifest: Dict[str, List[str]] = {"discovery": [], "state": [], "image": []}
        self._generated_client_id: Optional[str] = None
        self._messages_total = 0
        self._last_publish: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_error_at: Optional[datetime] = None
        self._devices_summary: List[Dict[str, Any]] = []
        self._last_status_json: Optional[str] = None
        self._load_manifest()

    # ------------------------------------------------------------------
    # Defaults (overridable for tests)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_client_factory(client_id: str):
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion

        return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)

    @staticmethod
    def _default_config_loader() -> Dict[str, Any]:
        from utils.repo_config import load_config

        return load_config()

    @staticmethod
    def _current_source_signature() -> Any:
        """Cheap change detector for the config and the secrets sidecar (mtimes)."""
        from utils import connector_secrets

        stamps = []
        for path in (CONFIG_FILE, connector_secrets._SECRETS_FILE):
            try:
                stamps.append(os.stat(path).st_mtime_ns)
            except OSError:
                stamps.append(None)
        return tuple(stamps)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if not self._acquire_lock():
            logger.debug("MQTT publisher already running in another process")
            return False
        self.thread.start()
        logger.info("MQTT publisher started (tick %ss)", TICK_SECONDS)
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=TICK_SECONDS * 2)
        self._disconnect(publish_offline=True)
        self._release_lock()
        logger.info("MQTT publisher stopped")

    def _acquire_lock(self) -> bool:
        try:
            os.makedirs(DATA_DIR_CACHE, exist_ok=True)
            self._lock_file = open(LOCK_FILE, "w")
            if sys.platform == "win32":
                try:
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._lock_file.close()
                    self._lock_file = None
                    return False
            else:  # pragma: no cover
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
            self._has_lock = True
            return True
        except OSError:
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def _release_lock(self) -> None:
        if self._lock_file and self._has_lock:
            try:
                if sys.platform == "win32":
                    self._lock_file.seek(0)
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
                if os.path.exists(LOCK_FILE):
                    os.unlink(LOCK_FILE)
            except Exception as exc:
                try:
                    logger.error(f"Error releasing MQTT publisher lock: {exc}")
                except (ValueError, OSError):
                    pass  # log stream already closed during shutdown
            finally:
                self._lock_file = None
                self._has_lock = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.error(f"MQTT publisher tick failed: {exc}", exc_info=True)
                self._note_error(str(exc))
            if self._stop_event.wait(TICK_SECONDS):
                break

    # ------------------------------------------------------------------
    # One tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        action = _consume_trigger()
        changed = self._refresh_connector()
        connector = self._connector
        now_mono = time.monotonic()

        if action == "remove":
            self._remove_all(connector)

        if connector is None or not connector.is_enabled():
            if self._client is not None:
                self._disconnect(publish_offline=True)
            self._write_status()
            return

        if self._client is None or changed:
            self._connect(connector)
            self._write_status()
            return  # the first cycle runs once on_connect has flagged a full publish

        if not self._connected:
            self._write_status()
            return

        force = self._force_full or action == "publish"
        interval = connector.publish_interval_seconds()
        if not force and self._last_full and now_mono - self._last_full >= connector.FULL_REFRESH_MINUTES * 60:
            force = True
        if force or now_mono >= self._next_due:
            self._force_full = False
            self._publish_cycle(force_full=force)
            self._next_due = time.monotonic() + interval
            if force:
                self._last_full = time.monotonic()
        self._write_status()

    def _refresh_connector(self) -> bool:
        """Reload the connector when config.json or the secrets sidecar changed. True on change."""
        signature = self._current_source_signature()
        if self._connector is not None and signature == self._source_signature:
            return False
        self._source_signature = signature
        try:
            config = self._config_loader() or {}
        except Exception as exc:
            logger.error(f"MQTT publisher: could not load config: {exc}")
            return False
        block = (config.get("connectors") or {}).get("mqtt") or {}
        merged = merge_secrets(MqttConnector.name, block, MqttConnector.SECRET_FIELDS)
        connector = MqttConnector(merged)
        previous = self._connector
        self._config = config
        self._connector = connector
        if previous is None:
            return True
        # Only a change that matters to the connection or the payloads counts as a change;
        # an unrelated config save must not bounce the broker connection.
        return _relevant_config(previous) != _relevant_config(connector)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _effective_client_id(self, connector: MqttConnector) -> str:
        configured = connector.client_id()
        if configured:
            return configured
        if not self._generated_client_id:
            self._generated_client_id = MqttConnector.generate_client_id()
            self._save_manifest()
        return self._generated_client_id

    def _connect(self, connector: MqttConnector) -> None:
        self._disconnect(publish_offline=True)
        try:
            host, port, tls = connector.broker()
        except ValueError as exc:
            self._note_error(str(exc))
            return
        client_id = self._effective_client_id(connector)
        try:
            client = self._client_factory(client_id)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            username = str(connector.config.get("username") or "")
            if username:
                client.username_pw_set(username, str(connector.config.get("password") or "") or None)
            if tls:
                client.tls_set()
                if connector.tls_insecure():
                    client.tls_insecure_set(True)
            client.will_set(connector.availability_topic(), payload="offline", qos=1, retain=True)
            client.reconnect_delay_set(min_delay=1, max_delay=60)
            client.connect_timeout = float(connector.CONNECT_TIMEOUT_SECONDS)
            client.connect_async(host, port, keepalive=60)
            client.loop_start()
        except Exception as exc:
            logger.warning(f"MQTT publisher: connection to {host}:{port} failed to start: {exc}")
            self._note_error(f"connect: {exc}")
            return
        self._client = client
        self._connected = False
        # Nothing published on this connection yet: change detection starts from scratch.
        self._published = {}
        logger.info("MQTT publisher: connecting to %s:%s as %s", host, port, client_id)

    def _disconnect(self, publish_offline: bool) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            if publish_offline and self._connected and self._connector is not None:
                info = client.publish(self._connector.availability_topic(), payload="offline", qos=1, retain=True)
                try:
                    info.wait_for_publish(timeout=2)
                except Exception:
                    pass  # best effort: the will message covers an unclean exit
            client.loop_stop()
            client.disconnect()
        except Exception as exc:
            logger.debug("MQTT publisher: disconnect error ignored: %s", exc)
        self._connected = False

    # paho callbacks - run on paho's network thread
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        failed = getattr(reason_code, "is_failure", False) or (isinstance(reason_code, int) and reason_code != 0)
        if failed:
            self._connected = False
            self._note_error(f"broker refused the connection: {reason_code}")
            return
        connector = self._connector
        if connector is None:
            return
        try:
            client.publish(connector.availability_topic(), payload="online", qos=1, retain=True)
            client.subscribe(connector.ha_status_topic(), qos=0)
        except Exception as exc:
            logger.debug("MQTT publisher: on_connect publish/subscribe failed: %s", exc)
        self._connected = True
        self._force_full = True
        self._last_error = None
        logger.info("MQTT publisher: connected to the broker")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None):
        self._connected = False
        logger.info("MQTT publisher: disconnected from the broker (%s)", reason_code)

    def _on_message(self, _client, _userdata, message):
        connector = self._connector
        if connector is None:
            return
        try:
            if message.topic == connector.ha_status_topic() and message.payload == b"online":
                # Home Assistant just (re)started: replay discovery + every state.
                self._force_full = True
                logger.info("MQTT publisher: Home Assistant is online, replaying discovery")
        except Exception as exc:
            logger.debug("MQTT publisher: message handling failed: %s", exc)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload: Any, qos: int, retain: bool) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            info = client.publish(topic, payload=payload, qos=qos, retain=retain)
            rc = getattr(info, "rc", 0)
            if rc not in (0, None):
                self._note_error(f"publish {topic}: rc={rc}")
                return False
        except Exception as exc:
            self._note_error(f"publish {topic}: {exc}")
            return False
        self._messages_total += 1
        return True

    def _publish_if_changed(self, topic: str, payload: str, qos: int, retain: bool, force: bool) -> bool:
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        if not force and self._published.get(topic) == digest:
            return False
        if self._publish(topic, payload, qos, retain):
            self._published[topic] = digest
            return True
        return False

    def _publish_cycle(self, force_full: bool) -> None:
        from connectors import mqtt_payloads  # lazy: it reaches feature packages

        connector = self._connector
        if connector is None or self._client is None:
            return
        now = self._clock()
        info = {"last_publish": now}
        devices = mqtt_payloads.collect(connector, self._config, info, now)

        desired: Dict[str, set] = {"discovery": set(), "state": set(), "image": set()}
        discovery_on = connector.discovery_enabled()
        summary: List[Dict[str, Any]] = []
        for device in devices:
            if discovery_on:
                payload = json.dumps(device.discovery, sort_keys=True, separators=(",", ":"))
                self._publish_if_changed(device.discovery_topic, payload, qos=1, retain=True, force=force_full)
                desired["discovery"].add(device.discovery_topic)
            state_json = json.dumps(device.state, sort_keys=True, separators=(",", ":"), default=str)
            self._publish_if_changed(device.state_topic, state_json, qos=0, retain=True, force=force_full)
            desired["state"].add(device.state_topic)
            if device.image_topic:
                self._publish_image(device, desired, force_full)
            summary.append(
                {"kind": device.kind, "id": device.object_id, "name": device.name, "entities": device.entity_count}
            )

        self._cleanup(desired)
        self._manifest = {kind: sorted(topics) for kind, topics in desired.items()}
        self._save_manifest()
        self._devices_summary = summary
        self._last_publish = now
        logger.debug("MQTT publisher: cycle done, %d device(s), full=%s", len(devices), force_full)

    def _publish_image(self, device, desired: Dict[str, set], force_full: bool) -> None:
        topic = device.image_topic
        if not device.image_id or device.image_loader is None:
            return  # no picture: the topic is not desired, cleanup clears a previous one
        previously = self._image_ids.get(topic)
        if not force_full and previously == device.image_id:
            desired["image"].add(topic)
            return
        data = device.image_loader()
        if data:
            if self._publish(topic, data, qos=1, retain=True):
                self._image_ids[topic] = device.image_id
                desired["image"].add(topic)
        elif previously:
            desired["image"].add(topic)  # keep the last good picture rather than clearing it

    def _cleanup(self, desired: Dict[str, set]) -> None:
        for kind, topics in self._manifest.items():
            for topic in topics:
                if topic in desired.get(kind, set()):
                    continue
                self._publish(topic, None, qos=1, retain=True)
                self._published.pop(topic, None)
                self._image_ids.pop(topic, None)
                logger.info("MQTT publisher: cleared retained topic %s", topic)

    def _remove_all(self, connector: Optional[MqttConnector]) -> None:
        """Purge every topic the manifest knows about, connecting first if needed."""
        if connector is None:
            return
        if self._client is None or not self._connected:
            if not self._client:
                self._connect(connector)
            deadline = time.monotonic() + CONNECT_WAIT_SECONDS
            while not self._connected and time.monotonic() < deadline and self._client is not None:
                time.sleep(0.2)
        if not self._connected:
            self._note_error("remove: broker not reachable, retained topics not cleared")
            return
        self._cleanup({"discovery": set(), "state": set(), "image": set()})
        self._manifest = {"discovery": [], "state": [], "image": []}
        self._published = {}
        self._image_ids = {}
        self._devices_summary = []
        self._save_manifest()
        self._force_full = True  # if the connector stays enabled, the next cycle republishes
        logger.info("MQTT publisher: all retained topics removed from the broker")

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def _load_manifest(self) -> None:
        data = _read_json(MANIFEST_FILE) or {}
        manifest = {"discovery": [], "state": [], "image": []}
        for kind in manifest:
            values = data.get(kind)
            if isinstance(values, list):
                manifest[kind] = [str(t) for t in values if isinstance(t, str)]
        self._manifest = manifest
        ids = data.get("image_ids")
        self._image_ids = {str(k): str(v) for k, v in ids.items()} if isinstance(ids, dict) else {}
        cid = data.get("client_id")
        self._generated_client_id = str(cid) if isinstance(cid, str) and cid else None

    def _save_manifest(self) -> None:
        payload: Dict[str, Any] = dict(self._manifest)
        payload["image_ids"] = dict(self._image_ids)
        payload["client_id"] = self._generated_client_id
        payload["updated_at"] = _iso(self._clock())
        _write_json(MANIFEST_FILE, payload)

    def _note_error(self, message: str) -> None:
        self._last_error = message[:300]
        self._last_error_at = self._clock()
        logger.warning("MQTT publisher: %s", message)

    def status(self) -> Dict[str, Any]:
        connector = self._connector
        status = default_status()
        if connector is not None:
            broker = None
            try:
                host, port, tls = connector.broker()
                broker = f"{'mqtts' if tls else 'mqtt'}://{host}:{port}"
            except ValueError:
                pass
            status.update(
                {
                    "enabled": connector.is_enabled(),
                    "configured": connector.is_configured(),
                    "broker": broker,
                    "client_id": connector.client_id() or self._generated_client_id,
                    "discovery_enabled": connector.discovery_enabled(),
                    # Lets the card say "no user has opted in yet" instead of a silent absence
                    "user_modules_enabled": connector.is_module_enabled("user_activity")
                    or connector.is_module_enabled("astrodex_image"),
                }
            )
        status.update(
            {
                "connected": bool(self._connected and self._client is not None),
                "last_publish_at": _iso(self._last_publish),
                "last_error": self._last_error,
                "last_error_at": _iso(self._last_error_at),
                "devices": list(self._devices_summary),
                "messages_total": self._messages_total,
                "updated_at": _iso(self._clock()),
            }
        )
        return status

    def _write_status(self) -> None:
        status = self.status()
        comparable = json.dumps({k: v for k, v in status.items() if k != "updated_at"}, sort_keys=True)
        if comparable == self._last_status_json:
            return
        self._last_status_json = comparable
        _write_json(STATUS_FILE, status)


def _relevant_config(connector: MqttConnector) -> str:
    """The part of the connector config whose change warrants a reconnect / full republish."""
    cfg = connector.config
    relevant = {
        "url": connector.base_url,
        "enabled": connector.is_enabled(),
        "username": cfg.get("username"),
        "password": cfg.get("password"),
        "base_topic": connector.base_topic(),
        "discovery_enabled": connector.discovery_enabled(),
        "discovery_prefix": connector.discovery_prefix(),
        "client_id": connector.client_id(),
        "tls_insecure": connector.tls_insecure(),
        "modules": {m["slug"]: connector.is_module_enabled(m["slug"]) for m in connector.MODULES},
    }
    return json.dumps(relevant, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Module-level singleton, like push_scheduler
# ---------------------------------------------------------------------------

_publisher: Optional[MqttPublisher] = None
_publisher_lock = threading.Lock()


def start() -> bool:
    """Start the publisher in this process if no other process owns it."""
    global _publisher
    with _publisher_lock:
        if _publisher is not None and _publisher.thread.is_alive():
            return True
        publisher = MqttPublisher()
        if not publisher.start():
            return False
        _publisher = publisher
        return True


def stop() -> None:
    global _publisher
    with _publisher_lock:
        publisher, _publisher = _publisher, None
    if publisher is not None:
        publisher.stop()
