"""
AllSky connector — integrates with an AllSky all-sky camera instance.
AllSky exposes data purely via file serving (no REST API).
All image resources are returned as URLs for the browser to fetch directly.
"""

import requests
from datetime import datetime, timezone
from typing import Any

from connectors.base_connector import BaseConnector
from logging_config import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT = 5

# Human-readable hints for common 404 causes per module
_MODULE_404_HINTS = {
    "sensor_data":     "Export module not added to AllSky pipeline",
    "mini_timelapse":  "Mini-timelapse disabled in AllSky settings (Number Of Images = 0)",
    "daily_timelapse": "Daily timelapse not yet generated (runs at end of night)",
    "keogram":         "Keogram not yet generated for today (runs at end of night)",
    "startrails":      "Startrails not yet generated for today (runs at end of night)",
}


class AllSkyConnector(BaseConnector):
    name = "allsky"
    label = "AllSky"
    description = "All-sky camera — live image, keogram, startrails, sensor data, timelapse"
    min_version = "v2024.12"
    homepage = "https://github.com/AllskyTeam/allsky"

    MODULES = [
        {"slug": "live_image",       "label": "Live image",        "description": "Auto-refreshing live sky image", "default_enabled": True},
        {"slug": "sensor_data",      "label": "Sensor data",       "description": "Temperature, humidity, gain, exposure, brightness — requires AllSky Export module", "default_enabled": False},
        {"slug": "keogram",          "label": "Keogram",           "description": "Daily keogram timeline strip (generated end-of-night)", "default_enabled": True},
        {"slug": "startrails",       "label": "Startrails",        "description": "Stacked startrails image (generated end-of-night)", "default_enabled": False},
        {"slug": "daily_timelapse",  "label": "Daily timelapse",   "description": "Full-night timelapse video (generated end-of-night)", "default_enabled": False},
        {"slug": "mini_timelapse",   "label": "Mini-timelapse",    "description": "Frequent mini-timelapse clip — requires AllSky mini-timelapse enabled", "default_enabled": False},
    ]

    def _image_url(self) -> str:
        path = self.config.get("image_path", "current/tmp").strip("/")
        filename = self.config.get("image_filename", "image.jpg")
        return f"{self.base_url}/{path}/{filename}"

    def _sensor_data_url(self) -> str:
        image_path = self.config.get("image_path", "current/tmp").strip("/")
        json_file  = self.config.get("export_json_path", "allskydata.json").strip("/")
        return f"{self.base_url}/{image_path}/{json_file}"

    def _keogram_url(self, date_str: str) -> str:
        return f"{self.base_url}/keograms/keogram-{date_str}.jpg"

    def _startrails_url(self, date_str: str) -> str:
        return f"{self.base_url}/startrails/startrails-{date_str}.jpg"

    def _daily_timelapse_url(self, date_str: str) -> str:
        return f"{self.base_url}/videos/allsky-{date_str}.mp4"

    def _mini_timelapse_thumb_url(self) -> str:
        return f"{self.base_url}/allsky-tmp/mini-timelapse.jpg"

    def _mini_timelapse_video_url(self) -> str:
        return f"{self.base_url}/allsky-tmp/mini-timelapse.mp4"

    def _head(self, url: str) -> tuple[bool, int]:
        """Returns (success, status_code). Falls back to GET if HEAD not allowed."""
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

        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        module_results = {}

        url_map = {
            "live_image":       self._image_url(),
            "sensor_data":      self._sensor_data_url(),
            "keogram":          self._keogram_url(today),
            "startrails":       self._startrails_url(today),
            "daily_timelapse":  self._daily_timelapse_url(today),
            "mini_timelapse":   self._mini_timelapse_thumb_url(),
        }

        for slug, url in url_map.items():
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
            module_results[slug] = {"ok": ok, "detail": detail}

        return {
            "reachable": base_ok or any(v["ok"] for v in module_results.values()),
            "modules": module_results,
        }

    def get_module_urls(self, date_str: str | None = None) -> dict:
        today = date_str or datetime.now(timezone.utc).strftime("%Y%m%d")
        urls = {}

        if self.is_module_enabled("live_image"):
            urls["live_image"] = self._image_url()

        if self.is_module_enabled("sensor_data"):
            urls["sensor_data"] = self._sensor_data_url()

        if self.is_module_enabled("keogram"):
            urls["keogram"] = self._keogram_url(today)

        if self.is_module_enabled("startrails"):
            urls["startrails"] = self._startrails_url(today)

        if self.is_module_enabled("daily_timelapse"):
            urls["daily_timelapse"] = self._daily_timelapse_url(today)

        if self.is_module_enabled("mini_timelapse"):
            urls["mini_timelapse_thumb"] = self._mini_timelapse_thumb_url()
            urls["mini_timelapse_video"] = self._mini_timelapse_video_url()

        return urls

    def fetch_sensor_data(self) -> dict[str, Any]:
        if not self.is_module_enabled("sensor_data"):
            return {}
        url = self._sensor_data_url()
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning("AllSky sensor data HTTP error: %s", e)
        except requests.exceptions.ConnectionError:
            logger.warning("AllSky sensor data: connection refused at %s", url)
        except requests.exceptions.Timeout:
            logger.warning("AllSky sensor data: timeout at %s", url)
        except Exception as e:
            logger.error("AllSky sensor data unexpected error: %s", e)
        return {}
