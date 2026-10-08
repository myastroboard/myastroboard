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
    homepage: str = ""

    # Ordered list of module definitions: {slug, label, description, default_enabled}
    MODULES: list[dict] = []

    # App areas (navbar tabs) where this connector's data surfaces, e.g. ["observatory"].
    # Purely declarative — it drives the badges on the connector card so users know where to
    # look once the connector is enabled. An empty list means the connector is self-contained
    # and adds nothing to an existing tab.
    target_modules: list[str] = []

    # Config keys holding credentials. GET /api/connectors masks these before the config
    # block leaves the server, so a connector that authenticates can be listed like any
    # other without its secrets reaching the browser. On save, a blank or still-masked
    # submission for one of these means "keep the stored value".
    SECRET_FIELDS: tuple[str, ...] = ()

    # Settable config keys beyond the common label / url / enabled / modules, as
    # {key: default}. POST /api/connectors/<name>/config accepts these and nothing else,
    # coercing each submitted value to the type of its default and falling back to that
    # default when the submission is blank.
    CONFIG_FIELDS: dict[str, Any] = {}

    # Keys among CONFIG_FIELDS holding a URL. The shared save strips their trailing
    # slash, as it does for the main `url`, so callers can concatenate paths onto them.
    URL_FIELDS: tuple[str, ...] = ()

    # Keys among CONFIG_FIELDS restricted to a closed set of string values, as
    # {key: (allowed, ...)}. The shared save keeps a submission only when it is one of
    # these; anything else (including a blank/missing value) falls back to the field's
    # CONFIG_FIELDS default. GET /api/connectors exposes this so the frontend can build a
    # <select> from it instead of hardcoding the choices a second time.
    ENUM_FIELDS: dict[str, tuple[str, ...]] = {}

    # Config key holding the id of the shared MQTT connection this connector talks through
    # (utils/mqtt_connections.py), or "" for a connector that does not use one. The connection
    # (broker URL, username, TLS switch - never the password, see connection_password()) is
    # handed to the constructor apart from the block, so a connector keeps its own `url` (AllSky:
    # its web interface) next to the broker. The card shows a connection picker, and the
    # connection cannot be deleted while this connector points at it.
    CONNECTION_FIELD: str = ""

    def __init__(self, config: dict, connection: dict | None = None):
        """
        Args:
            config: The connector's config dict from config["connectors"][name]
            connection: The shared MQTT connection its CONNECTION_FIELD picks
                (utils.mqtt_connections.connection_for), or None
        """
        self.config = config
        self.connection = connection
        self.base_url = config.get("url", "").rstrip("/")

    @classmethod
    def validate_config(cls, block: dict) -> str | None:
        """Why a config block about to be saved is refused, or None.

        Called by the shared save after the typed coercion of CONFIG_FIELDS, for checks the
        types alone cannot express (AllSky: an MQTT topic without wildcard).
        """
        return None

    def is_configured(self) -> bool:
        """Whether the connector has everything it needs to be usable.

        A base URL is the only universal requirement; a connector that also needs
        credentials overrides this to say so, which is what the card's
        Installed / Not installed badge reflects.
        """
        return bool(self.base_url)

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False)) and self.is_configured()

    def is_module_enabled(self, module_slug: str) -> bool:
        modules = self.config.get("modules", {})
        return bool(modules.get(module_slug, {}).get("enabled", False))

    @abstractmethod
    def health_check(self) -> dict:
        """
        Returns per-module health status.
        Shape: {"reachable": bool, "modules": {"slug": {"ok": bool, "detail": str}}}
        """

    def get_module_urls(self, date_str: str | None = None) -> dict:
        """
        Returns resolved URLs for all enabled modules.
        Shape: {"module_slug": "http://..."}

        Defaults to none: only a connector whose modules are browser-fetched resources
        (images, video) has URLs to resolve.
        """
        return {}

    def mqtt_subscriptions(self) -> list[str]:
        """MQTT topics this connector reads through its connection (connectors/mqtt_subscriber.py).

        Defaults to none: only a connector that consumes data published on a broker lists any.
        The subscriber keeps the last message of each and the connector reads it back with
        ``mqtt_subscriber.read_last_message(name)``.
        """
        return []

    def mqtt_client_id(self) -> str:
        """The MQTT client id configured for this connector, or "" to have one generated.

        A broker keeps one session per client id, so connectors sharing a connection must not
        share it (the shared save refuses a duplicate - utils.mqtt_connections.client_id_conflict).
        """
        return str(self.config.get("client_id") or "").strip()

    def fetch_sensor_data(self) -> dict[str, Any]:
        """
        Fetches live structured data (sensor readings, status variables, etc.).

        Defaults to none: only a connector that exposes live readings implements this.
        """
        return {}
