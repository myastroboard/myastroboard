"""
MQTT subscriber - the background thread that listens to the topics the MQTT connectors read.

Counterpart of ``mqtt_publisher.py``, with the same runtime shape: one daemon thread per install
(a lock file under ``DATA_DIR/cache`` keeps the other gunicorn workers out), started from
``app.py``, stopped at exit. Every ``TICK_SECONDS`` it rebuilds the wanted subscriptions when the
config or the secrets store changed:

- each registered connector with a ``CONNECTION_FIELD`` is built with its shared connection and
  asked for its ``mqtt_subscriptions()`` (AllSky: its Publish Data topic);
- one paho client per connector - its own client id (``mqtt_client_id()`` or a generated
  ``myastroboard-<name>-<hex>``), so two connectors on the same broker never share a session;
- each message is checked (size, JSON object, scalar values) and its payload kept as the
  connector's **last message**, in a file any worker can read (``read_last_message``). Nothing
  is retained by the senders we know (AllSky's Publish Data), so the file is also what bridges a
  restart until the next message.

A status file carries the subscriptions' state back to the routes (``read_status``).

Feature packages are never imported here: ``connectors/`` is imported at module level by
``cache/`` and ``observation/`` (see ``mqtt_connector.py``).
"""

import json
import os
import re
import secrets
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from connectors.mqtt_connector import parse_broker_url
from utils.constants import DATA_DIR_CACHE
from utils.logging_config import get_logger
from utils.mqtt_connections import connection_for, connection_password

# Windows-compatible file locking (same split as mqtt_publisher.py)
if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover
    import fcntl

logger = get_logger(__name__)

TICK_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 5
SHUTDOWN_JOIN_SECONDS = 3

# A message larger than this, or with more keys, is dropped: the senders we read publish a few
# hundred bytes (AllSky's Publish Data: one flat object of the variables the admin listed).
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_KEYS = 500

LOCK_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_subscriber.lock")
STATUS_FILE = os.path.join(DATA_DIR_CACHE, "mqtt_subscriber_status.json")

# Connector names are registry keys; anything else never reaches a file name.
_SAFE_NAME = re.compile(r"^[a-z0-9_]{1,64}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        logger.error(f"MQTT subscriber: could not write {path}: {exc}")
        return False


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except OSError, ValueError:
        return None


def last_message_file(name: str) -> str | None:
    """Where the last message of connector *name* is kept, or None for an unsafe name."""
    if not _SAFE_NAME.match(str(name or "")):
        return None
    return os.path.join(DATA_DIR_CACHE, f"mqtt_last_{name}.json")


def read_last_message(name: str) -> dict[str, Any] | None:
    """``{"topic", "received_at", "payload"}`` of the last message connector *name* received."""
    path = last_message_file(name)
    data = _read_json(path) if path else None
    if not data or not isinstance(data.get("payload"), dict):
        return None
    return data


def read_status() -> dict[str, Any]:
    """The last status the subscriber thread wrote: ``{"connectors": {name: {...}}, "updated_at"}``."""
    stored = _read_json(STATUS_FILE) or {}
    connectors = stored.get("connectors")
    return {
        "connectors": connectors if isinstance(connectors, dict) else {},
        "updated_at": stored.get("updated_at"),
    }


def parse_payload(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """A received payload as a flat dict of scalar values, or ``(None, reason)``.

    Nested values are dropped rather than kept: every consumer reads plain variables, and a
    nested structure from an unexpected sender would only be carried around for nothing.
    """
    if len(raw) > MAX_PAYLOAD_BYTES:
        return None, "message too large"
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None, "message is not JSON"
    if not isinstance(data, dict):
        return None, "message is not a JSON object"
    if len(data) > MAX_PAYLOAD_KEYS:
        return None, "message has too many keys"
    flat = {
        str(key): value for key, value in data.items() if value is None or isinstance(value, (str, int, float, bool))
    }
    return flat, None


class _Subscription:
    """What one connector wants: a broker, credentials, a client id and topics."""

    def __init__(self, name: str, connection: dict[str, Any], password: str, client_id: str, topics: list[str]):
        self.name = name
        self.connection = connection
        self.password = password
        self.client_id = client_id
        self.topics = tuple(sorted(set(topics)))

    def key(self) -> tuple:
        """Everything whose change needs a new client."""
        return (
            self.connection.get("url"),
            self.connection.get("username"),
            bool(self.connection.get("tls_insecure")),
            self.password,
            self.client_id,
            self.topics,
        )


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------


class MqttSubscriber:
    """One instance per process; ``start()`` only wins in the worker that gets the lock."""

    def __init__(
        self,
        client_factory: Callable[[str], Any] | None = None,
        config_loader: Callable[[], dict[str, Any]] | None = None,
        registry: dict[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._client_factory = client_factory or self._default_client_factory
        self._config_loader = config_loader or self._default_config_loader
        self._registry = registry
        self._clock = clock or _now

        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="mqtt-subscriber")
        self._lock_file = None
        self._has_lock = False

        self._source_signature: Any = None
        self._subscriptions: dict[str, _Subscription] = {}
        self._clients: dict[str, Any] = {}
        self._generated_ids: dict[str, str] = {}
        self._state: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.Lock()
        self._last_status_json: str | None = None

    # ------------------------------------------------------------------
    # Defaults (overridable for tests)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_client_factory(client_id: str):
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion

        return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)

    @staticmethod
    def _default_config_loader() -> dict[str, Any]:
        from utils.repo_config import load_config

        return load_config()

    @staticmethod
    def _current_source_signature() -> Any:
        """Cheap change detector for the config and the secrets store (store revisions)."""
        from utils import connector_secrets, repo_config

        try:
            return (repo_config.config_revision(), connector_secrets.secrets_revision())
        except Exception:
            return (None, None)

    def _registry_items(self) -> list[tuple[str, Any]]:
        if self._registry is None:
            # Lazy: the registry imports every connector module.
            from connectors import REGISTRY

            return list(REGISTRY.items())
        return list(self._registry.items())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if not self._acquire_lock():
            logger.debug("MQTT subscriber already running in another process")
            return False
        self.thread.start()
        logger.info("MQTT subscriber started (tick %ss)", TICK_SECONDS)
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=SHUTDOWN_JOIN_SECONDS)
        for name in list(self._clients):
            self._disconnect(name)
        self._release_lock()
        logger.info("MQTT subscriber stopped")

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
                    logger.error(f"Error releasing MQTT subscriber lock: {exc}")
                except ValueError, OSError:
                    pass  # log stream already closed during shutdown
            finally:
                self._lock_file = None
                self._has_lock = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.error(f"MQTT subscriber tick failed: {exc}", exc_info=True)
            if self._stop_event.wait(TICK_SECONDS):
                break

    # ------------------------------------------------------------------
    # One tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        signature = self._current_source_signature()
        if signature != self._source_signature:
            self._source_signature = signature
            self._reconcile(self._wanted_subscriptions())
        self._write_status()

    def _wanted_subscriptions(self) -> dict[str, _Subscription]:
        try:
            config = self._config_loader() or {}
        except Exception as exc:
            logger.error(f"MQTT subscriber: could not load config: {exc}")
            return dict(self._subscriptions)
        connectors_cfg = config.get("connectors") or {}
        wanted: dict[str, _Subscription] = {}
        for name, cls in self._registry_items():
            if not getattr(cls, "CONNECTION_FIELD", "") or not _SAFE_NAME.match(name):
                continue
            block = connectors_cfg.get(name) or {}
            connection = connection_for(cls, block, config)
            if connection is None:
                continue
            try:
                connector = cls(block, connection=connection)
                topics = [t for t in connector.mqtt_subscriptions() if isinstance(t, str) and t]
                client_id = connector.mqtt_client_id()
            except Exception as exc:
                logger.warning(f"MQTT subscriber: connector '{name}' could not list its topics: {exc}")
                continue
            if not topics:
                continue
            if not client_id:
                client_id = self._generated_ids.setdefault(name, f"myastroboard-{name}-{secrets.token_hex(3)}")
            wanted[name] = _Subscription(name, connection, connection_password(connection["id"]), client_id, topics)
        return wanted

    def _reconcile(self, wanted: dict[str, _Subscription]) -> None:
        for name in list(self._subscriptions):
            current = self._subscriptions[name]
            if name not in wanted or wanted[name].key() != current.key():
                self._disconnect(name)
                del self._subscriptions[name]
                if name not in wanted:
                    with self._state_lock:
                        self._state.pop(name, None)
        for name, subscription in wanted.items():
            if name not in self._subscriptions:
                self._subscriptions[name] = subscription
                self._connect(subscription)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _state_for(self, name: str) -> dict[str, Any]:
        return self._state.setdefault(
            name,
            {
                "connected": False,
                "broker": None,
                "topics": [],
                "client_id": None,
                "last_message_at": None,
                "messages_total": 0,
                "last_error": None,
                "last_error_at": None,
            },
        )

    def _note_error(self, name: str, message: str) -> None:
        with self._state_lock:
            state = self._state_for(name)
            state["last_error"] = message[:300]
            state["last_error_at"] = _iso(self._clock())
        logger.warning("MQTT subscriber (%s): %s", name, message)

    def _connect(self, subscription: _Subscription) -> None:
        name = subscription.name
        host, port, tls, error = parse_broker_url(subscription.connection.get("url", ""))
        with self._state_lock:
            state = self._state_for(name)
            state.update(
                {
                    "connected": False,
                    "topics": list(subscription.topics),
                    "client_id": subscription.client_id,
                    "broker": f"{'mqtts' if tls else 'mqtt'}://{host}:{port}" if host else None,
                }
            )
        if error or host is None or port is None:
            self._note_error(name, error or "invalid broker url")
            return
        try:
            client = self._client_factory(subscription.client_id)
            client.on_connect = lambda c, u, f, rc, p=None: self._on_connect(name, c, rc)
            client.on_disconnect = lambda c, u, f, rc, p=None: self._on_disconnect(name, rc)
            client.on_message = lambda c, u, msg: self._on_message(name, msg)
            username = str(subscription.connection.get("username") or "")
            if username:
                client.username_pw_set(username, subscription.password or None)
            if tls:
                client.tls_set()
                if subscription.connection.get("tls_insecure"):
                    client.tls_insecure_set(True)
            client.reconnect_delay_set(min_delay=1, max_delay=60)
            client.connect_timeout = float(CONNECT_TIMEOUT_SECONDS)
            client.connect_async(host, port, keepalive=60)
            client.loop_start()
        except Exception as exc:
            # Only the exception type, never its message: this block hands the broker
            # credentials to paho, and some libraries echo a failing argument back.
            logger.warning("MQTT subscriber (%s): connection to %s:%s failed to start", name, host, port)
            self._note_error(name, f"connect: {type(exc).__name__}")
            return
        self._clients[name] = client
        logger.info("MQTT subscriber (%s): connecting to %s:%s as %s", name, host, port, subscription.client_id)

    def _disconnect(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass  # best effort - the socket may already be gone
        with self._state_lock:
            if name in self._state:
                self._state[name]["connected"] = False

    # ------------------------------------------------------------------
    # paho callbacks (network thread)
    # ------------------------------------------------------------------

    def _on_connect(self, name: str, client, reason_code) -> None:
        if getattr(reason_code, "is_failure", False) or (isinstance(reason_code, int) and reason_code != 0):
            self._note_error(name, f"broker refused the connection: {reason_code}")
            return
        subscription = self._subscriptions.get(name)
        with self._state_lock:
            self._state_for(name)["connected"] = True
        if subscription is None:
            return
        try:
            for topic in subscription.topics:
                # Subscribed again on every connect: the session is not persistent.
                client.subscribe(topic, qos=1)
        except Exception as exc:
            self._note_error(name, f"subscribe failed: {type(exc).__name__}")

    def _on_disconnect(self, name: str, reason_code) -> None:
        with self._state_lock:
            self._state_for(name)["connected"] = False
        if getattr(reason_code, "is_failure", False):
            logger.info("MQTT subscriber (%s): disconnected (%s), paho reconnects on its own", name, reason_code)

    def _on_message(self, name: str, message) -> None:
        try:
            payload, reason = parse_payload(bytes(message.payload or b""))
            if payload is None:
                # The payload itself is never logged: it is whatever the broker carried.
                self._note_error(name, f"ignored a message on {message.topic}: {reason}")
                return
            received_at = self._clock()
            path = last_message_file(name)
            if path:
                _write_json(path, {"topic": message.topic, "received_at": _iso(received_at), "payload": payload})
            with self._state_lock:
                state = self._state_for(name)
                state["last_message_at"] = _iso(received_at)
                state["messages_total"] += 1
        except Exception as exc:
            logger.error(f"MQTT subscriber ({name}): message handling failed: {exc}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            connectors = {name: dict(state) for name, state in self._state.items()}
        return {"connectors": connectors, "updated_at": _iso(self._clock())}

    def _write_status(self) -> None:
        status = self.status()
        comparable = json.dumps(status["connectors"], sort_keys=True)
        if comparable == self._last_status_json:
            return
        self._last_status_json = comparable
        _write_json(STATUS_FILE, status)


# ---------------------------------------------------------------------------
# Module-level singleton, like mqtt_publisher
# ---------------------------------------------------------------------------

_subscriber: MqttSubscriber | None = None
_subscriber_lock = threading.Lock()


def start() -> bool:
    """Start the subscriber in this process if no other process owns it."""
    global _subscriber
    with _subscriber_lock:
        if _subscriber is not None and _subscriber.thread.is_alive():
            return True
        subscriber = MqttSubscriber()
        if not subscriber.start():
            return False
        _subscriber = subscriber
        return True


def stop() -> None:
    global _subscriber
    with _subscriber_lock:
        subscriber, _subscriber = _subscriber, None
    if subscriber is not None:
        subscriber.stop()
