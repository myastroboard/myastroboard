"""
Abstract base class for all external tool connectors.
Each connector exposes modules (discrete features) that can be independently enabled.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    # Subclasses must define these class attributes
    name: str = ""
    label: str = ""
    description: str = ""
    min_version: str = ""

    # Ordered list of module definitions: {slug, label, description, default_enabled}
    MODULES: list[dict] = []

    def __init__(self, config: dict):
        """
        Args:
            config: The connector's config dict from config["connectors"][name]
        """
        self.config = config
        self.base_url = config.get("url", "").rstrip("/")

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False)) and bool(self.base_url)

    def is_module_enabled(self, module_slug: str) -> bool:
        modules = self.config.get("modules", {})
        return bool(modules.get(module_slug, {}).get("enabled", False))

    @abstractmethod
    def health_check(self) -> dict:
        """
        Returns per-module health status.
        Shape: {"reachable": bool, "modules": {"slug": {"ok": bool, "detail": str}}}
        """

    @abstractmethod
    def get_module_urls(self, date_str: str | None = None) -> dict:
        """
        Returns resolved URLs for all enabled modules.
        Shape: {"module_slug": "http://..."}
        """

    @abstractmethod
    def fetch_sensor_data(self) -> dict[str, Any]:
        """
        Fetches live structured data (sensor readings, status variables, etc.).
        Returns empty dict if sensor_data module is not enabled or request fails.
        """
