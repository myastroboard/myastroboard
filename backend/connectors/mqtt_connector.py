"""
MQTT / Home Assistant connector - publish MyAstroBoard state to an MQTT broker.

Publish-only: the board pushes sky conditions, weather, tonight's plan, upcoming events and
(per opted-in user) Astrodex / Plan My Night activity to a broker, with Home Assistant MQTT
Discovery so the entities appear on an existing HA dashboard without YAML. Nothing is read back
from the broker except Home Assistant's own birth message, used to replay discovery after an HA
restart. See docs/HOME_ASSISTANT.md.

This module is the *declaration* of the connector (config fields, modules, topic layout and the
connection probe behind the card's test button). The background publisher thread and the
payload builders live in ``connectors/mqtt_publisher.py`` / ``connectors/mqtt_payloads.py``,
which are not imported by ``connectors/__init__``: that package is imported at module level by
``cache/cache_store.py``, ``cache/cache_updater.py`` and ``observation/myastroshine_integration.py``,
so this file must stay free of any feature-package import to avoid a circular import.
"""

import ipaddress
import re
import secrets
import socket
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from connectors.base_connector import BaseConnector
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Characters Home Assistant accepts in a discovery object id / unique id.
_OBJECT_ID_SAFE = re.compile(r'[^a-zA-Z0-9_-]+')

# MQTT topic levels must not contain the wildcard characters nor a NUL.
_TOPIC_LEVEL_UNSAFE = re.compile(r'[+#/\x00]')

DEFAULT_PORT = 1883
DEFAULT_TLS_PORT = 8883


def parse_broker_url(url: str) -> tuple[str, int, bool]:
    """``mqtt://host[:port]`` / ``mqtts://host[:port]`` -> ``(host, port, tls)``.

    Raises ValueError for anything else, with a message the card can show as-is.
    """
    parsed = urlparse(str(url or '').strip())
    scheme = (parsed.scheme or '').lower()
    if scheme not in ('mqtt', 'mqtts'):
        raise ValueError('url must start with mqtt:// or mqtts://')
    if not parsed.hostname:
        raise ValueError('url must include a broker host')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('url must be host and port only, e.g. mqtt://192.168.1.10:1883')
    tls = scheme == 'mqtts'
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('url port is not a valid number') from exc
    if port is None:
        port = DEFAULT_TLS_PORT if tls else DEFAULT_PORT
    return parsed.hostname, int(port), tls


def resolve_broker_host(host: str, port: int) -> tuple[Optional[str], Optional[str]]:
    """Resolve *host* and refuse the address ranges the other connector probes refuse.

    Returns ``(ip, None)`` or ``(None, error)``. Loopback, link-local (cloud metadata
    endpoints), unspecified and multicast targets are rejected after resolution, so a hostname
    cannot be used to point the probe somewhere its literal IP would be refused.
    """
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        resolved_ip = str(addrinfo[0][4][0])
        ip_obj = ipaddress.ip_address(resolved_ip)
    except (socket.gaierror, ValueError, IndexError):
        return None, 'unable to resolve host'
    if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_multicast:
        return None, 'url host is not allowed'
    return resolved_ip, None


def sanitize_object_id(value: str) -> str:
    """A Home Assistant-safe object id: ``[a-zA-Z0-9_-]`` only, never empty."""
    cleaned = _OBJECT_ID_SAFE.sub('_', str(value or '')).strip('_')
    return cleaned or 'myastroboard'


def sanitize_topic_level(value: str) -> str:
    """One MQTT topic level: no wildcards, no separators, never empty."""
    cleaned = _TOPIC_LEVEL_UNSAFE.sub('_', str(value or '')).strip()
    return cleaned or 'myastroboard'


class MqttConnector(BaseConnector):
    name = "mqtt"
    label = "MQTT / Home Assistant"
    description = (
        "Publish sky conditions, weather, tonight's targets and your activity to an MQTT broker, "
        "with Home Assistant discovery"
    )
    # Device-based MQTT discovery (one config message per device) needs this HA release.
    min_version = "Home Assistant 2024.11"
    homepage = "https://www.home-assistant.io/integrations/mqtt/"
    # Standalone: the connector feeds no MyAstroBoard tab, it feeds Home Assistant.
    target_modules: list[str] = []

    SECRET_FIELDS = ("password",)

    CONFIG_FIELDS: dict[str, Any] = {
        "username": "",
        "password": "",
        "base_topic": "myastroboard",
        "discovery_enabled": True,
        "discovery_prefix": "homeassistant",
        "publish_interval_seconds": 60,
        # Blank = generated once by the publisher and stored back ("myastroboard-<8 hex>").
        "client_id": "",
        # Accept a self-signed broker certificate (mqtts:// on a LAN broker).
        "tls_insecure": False,
    }

    # Tuning knobs stay on the class (CONNECTORS.md rule), not in utils/constants.py.
    CONNECT_TIMEOUT_SECONDS = 5
    MIN_PUBLISH_INTERVAL_SECONDS = 15
    FULL_REFRESH_MINUTES = 30
    IMAGE_MAX_EDGE_PX = 1280
    IMAGE_MAX_BYTES = 1_000_000
    IMAGE_JPEG_QUALITY = 82

    MODULES = [
        {
            "slug": "sky_conditions",
            "label": "Sky conditions",
            "description": "Sky period, night score, sun and moon times, dark window, best window, top target",
            "default_enabled": True,
        },
        {
            "slug": "weather_now",
            "label": "Weather now",
            "description": "Current weather for astrophotography: clouds, wind, dew risk, seeing, transparency",
            "default_enabled": True,
        },
        {
            "slug": "upcoming_events",
            "label": "Upcoming events",
            "description": "Next event, next ISS / CSS pass, aurora activity, next eclipses",
            "default_enabled": False,
        },
        {
            "slug": "user_activity",
            "label": "User activity",
            "description": "Astrodex counters, tonight's plan and its equipment - per user, each user opts in",
            "default_enabled": False,
        },
        {
            "slug": "astrodex_image",
            "label": "Latest Astrodex picture",
            "description": "The newest Astrodex picture as a Home Assistant image entity - per opted-in user",
            "default_enabled": False,
        },
        {
            "slug": "board_diagnostics",
            "label": "Board diagnostics",
            "description": "Version, update available, cache and SkyTonight scheduler state, last publish",
            "default_enabled": True,
        },
    ]

    # ------------------------------------------------------------------
    # Configuration accessors
    # ------------------------------------------------------------------

    def broker(self) -> tuple[str, int, bool]:
        """``(host, port, tls)`` from the configured URL; raises ValueError when unusable."""
        return parse_broker_url(self.base_url)

    def is_configured(self) -> bool:
        """A parseable mqtt(s):// URL is the only requirement - anonymous brokers exist."""
        try:
            self.broker()
        except ValueError:
            return False
        return True

    def base_topic(self) -> str:
        return sanitize_topic_level(self.config.get("base_topic") or self.CONFIG_FIELDS["base_topic"])

    def discovery_prefix(self) -> str:
        return sanitize_topic_level(self.config.get("discovery_prefix") or self.CONFIG_FIELDS["discovery_prefix"])

    def discovery_enabled(self) -> bool:
        return bool(self.config.get("discovery_enabled", self.CONFIG_FIELDS["discovery_enabled"]))

    def publish_interval_seconds(self) -> int:
        raw = self.config.get("publish_interval_seconds", self.CONFIG_FIELDS["publish_interval_seconds"])
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = int(self.CONFIG_FIELDS["publish_interval_seconds"])
        return max(self.MIN_PUBLISH_INTERVAL_SECONDS, value)

    def client_id(self) -> str:
        return str(self.config.get("client_id") or "").strip()

    def tls_insecure(self) -> bool:
        return bool(self.config.get("tls_insecure", False))

    @staticmethod
    def generate_client_id() -> str:
        return f"myastroboard-{secrets.token_hex(4)}"

    # ------------------------------------------------------------------
    # Topic layout - the single definition shared by the publisher and the tests
    # ------------------------------------------------------------------

    def availability_topic(self) -> str:
        return f"{self.base_topic()}/status"

    def state_topic(self, kind: str, object_id: str = "") -> str:
        """``<base>/board/state``, ``<base>/location/<id>/state``, ``<base>/user/<id>/state``."""
        if kind == "board":
            return f"{self.base_topic()}/board/state"
        return f"{self.base_topic()}/{kind}/{sanitize_topic_level(object_id)}/state"

    def image_topic(self, user_id: str) -> str:
        return f"{self.base_topic()}/user/{sanitize_topic_level(user_id)}/astrodex/latest_image"

    def device_object_id(self, kind: str, object_id: str = "") -> str:
        """The HA device identifier: ``<base>_board``, ``<base>_loc_<id>``, ``<base>_user_<id>``."""
        base = sanitize_object_id(self.base_topic())
        if kind == "board":
            return f"{base}_board"
        prefix = {"location": "loc", "user": "user"}.get(kind, kind)
        return f"{base}_{prefix}_{sanitize_object_id(object_id)}"

    def discovery_topic(self, kind: str, object_id: str = "") -> str:
        return f"{self.discovery_prefix()}/device/{self.device_object_id(kind, object_id)}/config"

    def ha_status_topic(self) -> str:
        """Home Assistant's own birth / will topic, the connector's only subscription."""
        return f"{self.discovery_prefix()}/status"

    # ------------------------------------------------------------------
    # Connection probe
    # ------------------------------------------------------------------

    @staticmethod
    def _default_client_factory(client_id: str):
        # Lazy so the registry import (and every test that never probes) does not pay for paho.
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion

        return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)

    def probe(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls_insecure: Optional[bool] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
    ) -> dict:
        """One MQTT CONNECT / DISCONNECT against *url* (default: the configured broker).

        Returns ``{"reachable": bool, "error": str | None}``. Credentials default to the
        configured ones only when *url* is the configured URL - the caller decides whether a
        stored password may be paired with the host it is probing.
        """
        target = str(url if url is not None else self.base_url or "").strip().rstrip("/")
        try:
            host, port, tls = parse_broker_url(target)
        except ValueError as exc:
            return {"reachable": False, "error": str(exc)}

        resolved_ip, error = resolve_broker_host(host, port)
        if error or resolved_ip is None:
            return {"reachable": False, "error": error or "unable to resolve host"}

        user = username if username is not None else str(self.config.get("username") or "")
        secret = password if password is not None else str(self.config.get("password") or "")
        insecure = self.tls_insecure() if tls_insecure is None else bool(tls_insecure)

        factory = client_factory or self._default_client_factory
        client = factory(f"myastroboard-probe-{secrets.token_hex(3)}")
        outcome: dict[str, Any] = {}

        def _on_connect(_client, _userdata, _flags, reason_code, _properties=None):
            outcome["reason"] = reason_code

        client.on_connect = _on_connect
        try:
            if user:
                client.username_pw_set(user, secret or None)
            if tls:
                client.tls_set()
                if insecure:
                    client.tls_insecure_set(True)
            client.connect_timeout = float(self.CONNECT_TIMEOUT_SECONDS)
            # TLS validates the certificate against the hostname, so it must see the hostname;
            # a plain connection goes to the vetted IP, like the other connectors' probes.
            client.connect(host if tls else resolved_ip, port, keepalive=10)
            deadline = time.monotonic() + self.CONNECT_TIMEOUT_SECONDS
            while "reason" not in outcome and time.monotonic() < deadline:
                client.loop(timeout=0.5)
        except (OSError, ValueError) as exc:
            # ConnectionRefusedError / socket.timeout are OSError; a TLS handshake failure is
            # ssl.SSLError (also OSError); ValueError covers paho argument validation. Only the
            # exception type is logged, never its message: this try block also hands the broker
            # credentials to paho, and some libraries embed a failing argument's value in their
            # exception text - the type name is enough to diagnose a probe failure.
            logger.debug("MQTT probe to %s:%s failed: %s", host, port, type(exc).__name__)
            return {"reachable": False, "error": _describe_probe_error(exc)}
        finally:
            try:
                client.disconnect()
            except Exception:
                pass  # best effort - the probe socket may already be gone

        reason = outcome.get("reason")
        if reason is None:
            return {"reachable": False, "error": "timeout - no answer from the broker"}
        if getattr(reason, "is_failure", False) or (isinstance(reason, int) and reason != 0):
            return {"reachable": False, "error": f"broker refused the connection: {reason}"}
        return {"reachable": True, "error": None}

    def health_check(self) -> dict:
        """Connection probe against the saved broker plus one line per module.

        Module lines only reflect the toggles here; the publisher's own status route says
        what is actually being published.
        """
        if not self.base_url:
            return {"reachable": False, "modules": {}, "error": "url required"}
        result = self.probe()
        modules = {}
        for module in self.MODULES:
            slug = module["slug"]
            enabled = self.is_module_enabled(slug)
            modules[slug] = {
                "ok": bool(result["reachable"]) and enabled,
                "detail": "enabled" if enabled else "disabled",
            }
        payload = {"reachable": bool(result["reachable"]), "modules": modules}
        if result.get("error"):
            payload["error"] = result["error"]
        return payload


def _describe_probe_error(exc: BaseException) -> str:
    """A short, credential-free description of a failed CONNECT.

    Only the exception's type name is ever returned, never ``str(exc)``: this describes the
    outcome of a connection attempt made with the caller's credentials, and some libraries echo
    a failing argument's value back in their exception message.
    """
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout - no answer from the broker"
    name = type(exc).__name__
    if "SSL" in name or "ssl" in name.lower():
        return "TLS handshake failed - check the certificate or enable the insecure option"
    return name
