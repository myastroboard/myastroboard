"""
AllSky connector — integrates with an AllSky all-sky camera instance.

Two channels:

- **images** (live image, keogram, startrails, timelapse) are files served by AllSky's web
  server, fetched over HTTP through the board's proxy;
- **sensor data** arrives over MQTT: AllSky's *Publish Data to Redis/MQTT/REST/influxDB* module
  (``allsky_publishdata``, *AllSKY Redis/MQTT/REST Data Publish* in v2024.12), run in the Day and
  Night pipelines, publishes one flat JSON object of the variables the admin listed on a topic at
  every image.
  ``connectors/mqtt_subscriber.py`` keeps the last message; ``fetch_sensor_data`` reads it back.
  (Earlier releases downloaded the Export module's ``allskydata.json`` instead.)

Two AllSky layouts are supported side by side for the live image:

- up to v2024.12: the web server's ``/current/`` alias points at the AllSky home
  directory, so the live image is ``/current/tmp/image.jpg``;
- v2026.10 onwards: ``/current/`` points at ``tmp/current_images``, so the live image is
  ``/current/image.jpg``.

Which one serves it is probed once and remembered (see ``_resolve_image_path``). The MQTT
payload carries the variables under their ``AS_`` names in both versions; it is still normalised
(``_normalize_sensor_data``) so ``DAY_OR_NIGHT`` and a prefix-less key read the same.
"""

import re
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from connectors import mqtt_subscriber
from connectors.base_connector import BaseConnector
from utils.logging_config import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT = 5

# Human-readable hints for common 404 causes per module
_MODULE_404_HINTS = {
    "live_image": "Live image not found (checked both the current/ and current/tmp/ AllSky layouts)",
    "daily_timelapse": "Daily timelapse not yet generated (runs at end of night)",
    "keogram": "Keogram not found for last night (generated end-of-night, named after session start date)",
    "startrails": "Startrails not found for last night (generated end-of-night, named after session start date)",
}

# Live-image directories, relative to the base URL, of the AllSky releases we know: the
# current layout first, then the pre-v2026 one. When the configured image_path is one of
# these, the others are tried too, so an AllSky upgrade (either way) needs no reconfiguring.
# A custom image_path is respected as-is.
KNOWN_IMAGE_PATHS = ("current", "current/tmp")

# An MQTT topic to listen to: exact (no + or # wildcard), no NUL, at most 256 characters.
_TOPIC_INVALID = re.compile(r"[+#\x00]")
MAX_TOPIC_LENGTH = 256

# (base_url, configured image_path) -> (resolved live image path, resolved at).
# Per process: each worker probes on its own, which only costs a few HEAD requests.
_resolved_image_paths: dict[tuple[str, str], tuple[str, float]] = {}


def _normalize_sensor_data(data: Any) -> dict[str, Any]:
    """Return AllSky variables under their ``AS_`` names, plus ``DAY_OR_NIGHT``.

    Publish Data sends the variables under the names the admin listed - ``AS_TEMPERATURE_C``
    in both AllSky versions - but a prefix-less name (``TEMPERATURE_C``, what the v2026 Export
    module used to write) is also exposed under its ``AS_`` name, unless that name is already
    present. Keys that were never prefixed (``ALLSKY_*``, ``utc``) are left alone. The card reads
    ``DAY_OR_NIGHT``, which v2026 lists as ``AS_DAY_OR_NIGHT``.
    """
    if not isinstance(data, dict):
        return {}
    normalized = dict(data)
    for key, value in data.items():
        # utc is Publish Data's own timestamp, not an AllSky variable
        if not isinstance(key, str) or key.startswith(("AS_", "ALLSKY_")) or key == "utc":
            continue
        normalized.setdefault(f"AS_{key}", value)
    if "DAY_OR_NIGHT" not in normalized and "AS_DAY_OR_NIGHT" in normalized:
        normalized["DAY_OR_NIGHT"] = normalized["AS_DAY_OR_NIGHT"]
    return normalized


class AllSkyConnector(BaseConnector):
    name = "allsky"
    label = "AllSky"
    description = "All-sky camera — live image, keogram, startrails, sensor data, timelapse"
    min_version = "v2024.12"
    homepage = "https://github.com/AllskyTeam/allsky"
    target_modules = ["observatory"]

    # Cache TTL of the reachability check (5 min: it does not need tighter polling).
    HEALTH_CACHE_TTL = 300
    # How long a probed image_path (see KNOWN_IMAGE_PATHS) is trusted before probing again.
    LAYOUT_CACHE_TTL = 300
    # A sensor message older than this is no longer shown. Publish Data runs at every image (Day
    # and Night pipelines) or every Periodic jobs run, both about a minute apart, so this leaves
    # room for missed runs or an AllSky restart without showing readings that stopped updating.
    MQTT_STALE_AFTER_SECONDS = 900

    # Sensor data comes from the shared MQTT connection this field picks; the connector's own
    # `url` stays its web interface (images).
    CONNECTION_FIELD = "mqtt_connection_id"

    CONFIG_FIELDS = {
        "image_path": "current",
        "image_filename": "image.jpg",
        "mqtt_connection_id": "",
        # = "MQTT Topic" of AllSky's Publish Data module (whose own default is "allsky" too)
        "mqtt_topic": "allsky",
        # Blank = generated (myastroboard-allsky-<hex>); must differ from the other connectors
        # on the same connection.
        "client_id": "",
    }

    MODULES = [
        {
            "slug": "live_image",
            "label": "Live image",
            "description": "Auto-refreshing live sky image",
            "default_enabled": True,
        },
        {
            "slug": "sensor_data",
            "label": "Sensor data",
            "description": "Temperature, humidity, gain, exposure, brightness - received over MQTT from "
            "AllSky's Publish Data module",
            "default_enabled": False,
        },
        {
            "slug": "keogram",
            "label": "Keogram",
            "description": "Daily keogram timeline strip (generated end-of-night)",
            "default_enabled": True,
        },
        {
            "slug": "startrails",
            "label": "Startrails",
            "description": "Stacked startrails image (generated end-of-night)",
            "default_enabled": False,
        },
        {
            "slug": "daily_timelapse",
            "label": "Daily timelapse",
            "description": "Full-night timelapse video (generated end-of-night)",
            "default_enabled": False,
        },
    ]

    def _configured_image_path(self) -> str:
        return (self.config.get("image_path") or KNOWN_IMAGE_PATHS[0]).strip("/")

    def _image_path_candidates(self) -> list[str]:
        """Configured image_path first, then the other known layouts when it is one of them."""
        configured = self._configured_image_path()
        if configured not in KNOWN_IMAGE_PATHS:
            return [configured]
        return [configured] + [path for path in KNOWN_IMAGE_PATHS if path != configured]

    def _image_url(self, image_path: str | None = None) -> str:
        path = (image_path or self._configured_image_path()).strip("/")
        filename = self.config.get("image_filename", "image.jpg")
        return f"{self.base_url}/{path}/{filename}"

    def _probe_layout(self) -> tuple[str, bool, int]:
        """HEAD the live image under each candidate layout, in order.

        Returns (image_path, ok, status) for the first candidate answering 200 or, when none
        does, for the configured path - and remembers that image_path for LAYOUT_CACHE_TTL,
        so an unreachable camera is not re-probed on every request either.
        """
        candidates = self._image_path_candidates()
        first_code = 0
        for index, path in enumerate(candidates):
            ok, code = self._head(self._image_url(path))
            if index == 0:
                first_code = code
            if ok:
                if index:
                    logger.debug("AllSky live image found under '%s' instead of '%s'", path, candidates[0])
                _resolved_image_paths[(self.base_url, candidates[0])] = (path, time.time())
                return path, True, code
        _resolved_image_paths[(self.base_url, candidates[0])] = (candidates[0], time.time())
        return candidates[0], False, first_code

    def _resolve_image_path(self) -> str:
        """Return the image_path serving the live image on this AllSky (probed, then remembered)."""
        candidates = self._image_path_candidates()
        if len(candidates) == 1:
            return candidates[0]
        cached = _resolved_image_paths.get((self.base_url, candidates[0]))
        if cached and time.time() - cached[1] < self.LAYOUT_CACHE_TTL:
            return cached[0]
        return self._probe_layout()[0]

    def _live_image_url(self) -> str:
        return self._image_url(self._resolve_image_path())

    # ------------------------------------------------------------------
    # Sensor data over MQTT
    # ------------------------------------------------------------------

    def mqtt_topic(self) -> str:
        return str(self.config.get("mqtt_topic") or "").strip() or self.CONFIG_FIELDS["mqtt_topic"]

    @staticmethod
    def topic_error(topic: str) -> str | None:
        """Why *topic* cannot be listened to, or None."""
        if not topic:
            return "topic required"
        if len(topic) > MAX_TOPIC_LENGTH:
            return f"topic must be at most {MAX_TOPIC_LENGTH} characters"
        if _TOPIC_INVALID.search(topic):
            return "topic must not contain + or # (an exact topic, no wildcard)"
        return None

    @classmethod
    def validate_config(cls, block: dict) -> str | None:
        return cls.topic_error(str(block.get("mqtt_topic") or "").strip() or cls.CONFIG_FIELDS["mqtt_topic"])

    def mqtt_subscriptions(self) -> list[str]:
        """The Publish Data topic, while the connector and its sensor_data module are on."""
        if not (self.is_enabled() and self.is_module_enabled("sensor_data") and self.connection):
            return []
        topic = self.mqtt_topic()
        return [] if self.topic_error(topic) else [topic]

    def _last_sensor_message(self) -> tuple[dict[str, Any] | None, float | None]:
        """The last message received on the configured topic and its age in seconds."""
        message = mqtt_subscriber.read_last_message(self.name)
        if not message or message.get("topic") != self.mqtt_topic():
            return None, None
        try:
            received = datetime.fromisoformat(str(message.get("received_at")))
        except TypeError, ValueError:
            return None, None
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        return message, max(0.0, (datetime.now(UTC) - received).total_seconds())

    def _sensor_health(self) -> dict[str, Any]:
        """The sensor_data line of the health check: is a recent message there?"""
        topic = self.mqtt_topic()
        if not self.connection:
            return {"ok": False, "detail": "No MQTT connection chosen"}
        message, age = self._last_sensor_message()
        if message is not None and age is not None and age <= self.MQTT_STALE_AFTER_SECONDS:
            return {"ok": True, "detail": f"Last message {int(age)} s ago on {topic}"}
        state = mqtt_subscriber.read_status()["connectors"].get(self.name) or {}
        if message is not None and age is not None:
            detail = f"Last message {int(age // 60)} min ago on {topic} - is AllSky still capturing images?"
        else:
            detail = f"No message received on {topic} yet - check AllSky's Publish Data module"
        if state.get("last_error"):
            detail = f"{detail} ({state['last_error']})"
        elif state and not state.get("connected"):
            detail = f"{detail} (not connected to the broker)"
        return {"ok": False, "detail": detail}

    def _keogram_url(self, date_str: str) -> str:
        return f"{self.base_url}/images/{date_str}/keogram/keogram-{date_str}.jpg"

    def _startrails_url(self, date_str: str) -> str:
        return f"{self.base_url}/images/{date_str}/startrails/startrails-{date_str}.jpg"

    def _daily_timelapse_url(self, date_str: str) -> str:
        return f"{self.base_url}/images/{date_str}/allsky-{date_str}.mp4"

    @staticmethod
    def _force_ipv4(url: str) -> str:
        """Replace hostname with its IPv4 address to avoid IPv6 ENETUNREACH in Docker."""
        try:
            parsed = urlparse(url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            infos = socket.getaddrinfo(parsed.hostname, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                ipv4 = infos[0][4][0]
                netloc = f"{ipv4}:{parsed.port}" if parsed.port else ipv4
                return urlunparse(parsed._replace(netloc=netloc))
        except OSError as exc:
            logger.debug("IPv4 resolution failed for %s: %s", url, exc)
        return url

    def _head(self, url: str) -> tuple[bool, int]:
        """Returns (success, status_code). Falls back to GET if HEAD not allowed."""
        url = self._force_ipv4(url)
        try:
            r = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if r.status_code == 405:
                r = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            return r.status_code == 200, r.status_code
        except requests.exceptions.ConnectionError:
            return False, 0
        except requests.exceptions.Timeout:
            return False, -1
        except Exception:
            return False, -2

    def health_check(self) -> dict:
        if not self.base_url:
            return {"reachable": False, "modules": {}}

        # Check base URL reachability first
        base_ok, base_code = self._head(self.base_url)

        # End-of-night files are named after the date the night started (previous day).
        last_night = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
        module_results = {}

        url_map = {
            "live_image": None,  # probed across the known layouts below
            "keogram": self._keogram_url(last_night),
            "startrails": self._startrails_url(last_night),
            "daily_timelapse": self._daily_timelapse_url(last_night),
        }

        for slug, url in url_map.items():
            if url is None:
                image_path, ok, code = self._probe_layout()
                url = self._image_url(image_path)
            else:
                ok, code = self._head(url)
            if ok:
                detail = "200 OK"
            elif code == 404:
                hint = _MODULE_404_HINTS.get(slug, "File not found on AllSky server")
                detail = f"404 — {hint}"
            elif code == 0:
                detail = "Connection refused"
            elif code == -1:
                detail = "Timeout"
            else:
                detail = f"HTTP {code}"
            module_results[slug] = {"ok": ok, "detail": detail, "url": url}

        reachable = base_ok or any(v["ok"] for v in module_results.values())
        module_results["sensor_data"] = self._sensor_health()
        return {"reachable": reachable, "modules": module_results}

    def get_module_urls(self, date_str: str | None = None) -> dict:
        # End-of-night files are named after the date the night started (previous day).
        last_night = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
        today = date_str or last_night
        urls = {}

        if self.is_module_enabled("live_image"):
            urls["live_image"] = self._live_image_url()

        if self.is_module_enabled("keogram"):
            urls["keogram"] = self._keogram_url(today)

        if self.is_module_enabled("startrails"):
            urls["startrails"] = self._startrails_url(today)

        if self.is_module_enabled("daily_timelapse"):
            urls["daily_timelapse"] = self._daily_timelapse_url(today)

        return urls

    def fetch_sensor_data(self) -> dict[str, Any]:
        """The variables of the last MQTT message, normalised, plus ``_received_at`` (ISO).

        Empty when the module is off, no message arrived yet on the configured topic, or the
        last one is older than ``MQTT_STALE_AFTER_SECONDS``. ``_received_at`` is the board's
        receive time (AllSky's own ``utc`` comes from the camera's clock, which can be off).
        """
        if not self.is_module_enabled("sensor_data"):
            return {}
        message, age = self._last_sensor_message()
        if message is None or age is None or age > self.MQTT_STALE_AFTER_SECONDS:
            return {}
        data = _normalize_sensor_data(message["payload"])
        data["_received_at"] = message.get("received_at")
        return data
