"""
AllSky connector — integrates with an AllSky all-sky camera instance.
AllSky exposes data purely via file serving (no REST API).
All image resources are returned as URLs for the browser to fetch directly.

Two AllSky layouts are supported side by side:

- up to v2024.12: the web server's ``/current/`` alias points at the AllSky home
  directory, so the live image is ``/current/tmp/image.jpg``; the Export module dumps
  every ``AS_*`` / ``ALLSKY_*`` variable under its full name.
- v2026.10 onwards: ``/current/`` points at ``tmp/current_images``, so the live image is
  ``/current/image.jpg``; the Export module writes only its ``extradata`` list, with the
  ``AS_`` prefix stripped from each key and typed (numeric) values.

Where the live image / Export JSON is served is probed once and remembered (see
``_resolve_image_path``); the JSON is normalised back to the legacy key names.
"""

import socket
import time
from urllib.parse import urlparse, urlunparse

import requests
from datetime import datetime, timezone, timedelta
from typing import Any

from connectors.base_connector import BaseConnector
from utils.logging_config import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT = 5

# Human-readable hints for common 404 causes per module
_MODULE_404_HINTS = {
    "live_image": "Live image not found (checked both the current/ and current/tmp/ AllSky layouts)",
    "sensor_data": (
        "Export module not added to AllSky pipeline, or (AllSky v2026+) its File Location "
        "is not ${ALLSKY_TMP}/current_images/allskydata.json"
    ),
    "daily_timelapse": "Daily timelapse not yet generated (runs at end of night)",
    "keogram": "Keogram not found for last night (generated end-of-night, named after session start date)",
    "startrails": "Startrails not found for last night (generated end-of-night, named after session start date)",
}

# Live-image directories, relative to the base URL, of the AllSky releases we know: the
# current layout first, then the pre-v2026 one. When the configured image_path is one of
# these, the others are tried too, so an AllSky upgrade (either way) needs no reconfiguring.
# A custom image_path is respected as-is.
KNOWN_IMAGE_PATHS = ("current", "current/tmp")

# (base_url, module slug, configured image_path) -> (resolved image_path, resolved at).
# Per process: each worker probes on its own, which only costs a few HEAD requests.
_resolved_image_paths: dict[tuple[str, str, str], tuple[str, float]] = {}


def _normalize_sensor_data(data: Any) -> dict[str, Any]:
    """Return Export-module JSON under the legacy (pre-v2026) key names.

    AllSky v2026 strips the ``AS_`` prefix from every exported key (``AS_TEMPERATURE_C``
    becomes ``TEMPERATURE_C``). Each such key is also exposed under its ``AS_`` name,
    unless that name is already present - a legacy file comes back unchanged. Keys that
    were never prefixed (``ALLSKY_*``) are left alone.
    """
    if not isinstance(data, dict):
        return {}
    normalized = dict(data)
    for key, value in data.items():
        if not isinstance(key, str) or key.startswith(("AS_", "ALLSKY_")):
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

    # Cache TTLs for the two AllSky reads the board makes on the user's behalf. Both are
    # 5 min: sensor values drift slowly, and reachability does not need tighter polling.
    SENSOR_CACHE_TTL = 300
    HEALTH_CACHE_TTL = 300
    # An empty sensor read (Export file missing, AllSky offline) is retried after this long.
    SENSOR_EMPTY_RETRY = 60
    # How long a probed image_path (see KNOWN_IMAGE_PATHS) is trusted before probing again.
    LAYOUT_CACHE_TTL = 300

    CONFIG_FIELDS = {
        "image_path": "current",
        "image_filename": "image.jpg",
        "export_json_path": "allskydata.json",
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
            "description": "Temperature, humidity, gain, exposure, brightness — requires AllSky Export module",
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

    def _sensor_data_url(self, image_path: str | None = None) -> str:
        path = (image_path or self._configured_image_path()).strip("/")
        json_file = self.config.get("export_json_path", "allskydata.json").strip("/")
        return f"{self.base_url}/{path}/{json_file}"

    def _build_layout_url(self, slug: str, image_path: str) -> str:
        return self._image_url(image_path) if slug == "live_image" else self._sensor_data_url(image_path)

    def _probe_layout(self, slug: str) -> tuple[str, bool, int]:
        """HEAD ``slug`` (live_image or sensor_data) under each candidate layout, in order.

        Returns (image_path, ok, status) for the first candidate answering 200 or, when none
        does, for the configured path - and remembers that image_path for LAYOUT_CACHE_TTL,
        so an unreachable camera is not re-probed on every request either.
        """
        candidates = self._image_path_candidates()
        first_code = 0
        for index, path in enumerate(candidates):
            ok, code = self._head(self._build_layout_url(slug, path))
            if index == 0:
                first_code = code
            if ok:
                if index:
                    logger.debug("AllSky %s found under '%s' instead of '%s'", slug, path, candidates[0])
                _resolved_image_paths[(self.base_url, slug, candidates[0])] = (path, time.time())
                return path, True, code
        _resolved_image_paths[(self.base_url, slug, candidates[0])] = (candidates[0], time.time())
        return candidates[0], False, first_code

    def _resolve_image_path(self, slug: str) -> str:
        """Return the image_path serving ``slug`` on this AllSky (probed, then remembered)."""
        candidates = self._image_path_candidates()
        if len(candidates) == 1:
            return candidates[0]
        cached = _resolved_image_paths.get((self.base_url, slug, candidates[0]))
        if cached and time.time() - cached[1] < self.LAYOUT_CACHE_TTL:
            return cached[0]
        return self._probe_layout(slug)[0]

    def _live_image_url(self) -> str:
        return self._image_url(self._resolve_image_path("live_image"))

    def _resolved_sensor_data_url(self) -> str:
        return self._sensor_data_url(self._resolve_image_path("sensor_data"))

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
        last_night = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
        module_results = {}

        url_map = {
            "live_image": None,  # probed across the known layouts below
            "sensor_data": None,
            "keogram": self._keogram_url(last_night),
            "startrails": self._startrails_url(last_night),
            "daily_timelapse": self._daily_timelapse_url(last_night),
        }

        for slug, url in url_map.items():
            if url is None:
                image_path, ok, code = self._probe_layout(slug)
                url = self._build_layout_url(slug, image_path)
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

        return {
            "reachable": base_ok or any(v["ok"] for v in module_results.values()),
            "modules": module_results,
        }

    def get_module_urls(self, date_str: str | None = None) -> dict:
        # End-of-night files are named after the date the night started (previous day).
        last_night = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
        today = date_str or last_night
        urls = {}

        if self.is_module_enabled("live_image"):
            urls["live_image"] = self._live_image_url()

        if self.is_module_enabled("sensor_data"):
            urls["sensor_data"] = self._resolved_sensor_data_url()

        if self.is_module_enabled("keogram"):
            urls["keogram"] = self._keogram_url(today)

        if self.is_module_enabled("startrails"):
            urls["startrails"] = self._startrails_url(today)

        if self.is_module_enabled("daily_timelapse"):
            urls["daily_timelapse"] = self._daily_timelapse_url(today)

        return urls

    def fetch_sensor_data(self) -> dict[str, Any]:
        if not self.is_module_enabled("sensor_data"):
            return {}
        url = self._force_ipv4(self._resolved_sensor_data_url())
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return _normalize_sensor_data(r.json())
        except requests.exceptions.HTTPError as e:
            logger.debug("AllSky sensor data HTTP error: %s", e)
        except requests.exceptions.ConnectionError:
            logger.debug("AllSky sensor data: connection refused at %s", url)
        except requests.exceptions.Timeout:
            logger.debug("AllSky sensor data: timeout at %s", url)
        except Exception as e:
            logger.error("AllSky sensor data unexpected error: %s", e)
        return {}
