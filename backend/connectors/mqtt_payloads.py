"""
Payload builders for the MQTT publisher - the one place that knows the wire format.

Turns what MyAstroBoard already computes (per-location caches, SkyTonight results, a user's
Astrodex / plan / log) into Home Assistant devices: one discovery message (device-based
discovery, ``<prefix>/device/<id>/config``) and one JSON state per device. Nothing here talks
to the broker; ``mqtt_publisher.py`` decides what to send and when.

Every feature package is imported lazily inside the functions that need it: this module
lives in ``connectors/``, which ``cache/`` and ``observation/`` already import at module
level, and a module-level import back would close a package cycle (see mqtt_connector.py).

Wire conventions (see docs/HOME_ASSISTANT.md):

- a state key that is unknown is published as JSON ``null``; the entity's template then
  renders ``None``, which Home Assistant maps to *unknown* for every sensor kind;
- every timestamp is ISO 8601 with a UTC offset (the ``timestamp`` device class needs it);
  the naive local strings of the sun / best-window reports are localised with the
  location's timezone;
- string states are capped below Home Assistant's 255-character limit.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from connectors.mqtt_connector import MqttConnector
from utils.logging_config import get_logger

logger = get_logger(__name__)

HOMEPAGE = "https://github.com/myastroboard/myastroboard"
MANUFACTURER = "MyAstroBoard"
MAX_STATE_LEN = 250  # HA refuses sensor states longer than 255 characters
TOP_TARGETS = 5

# Preference key a user sets in Parameters -> Customize to publish their own activity.
USER_OPT_IN_PREFERENCE = "mqtt_publish_enabled"

SKY_PERIOD_OPTIONS = [
    "day",
    "civil_twilight",
    "nautical_twilight",
    "astronomical_twilight",
    "astronomical_night",
    "unknown",
]
PLAN_STATE_OPTIONS = ["none", "current", "previous"]
DEW_RISK_OPTIONS = ["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"]
WIND_IMPACT_OPTIONS = ["NONE", "LOW", "MODERATE", "HIGH", "SEVERE", "UNKNOWN"]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class Device:
    """One Home Assistant device: its discovery message, its state and (optionally) an image."""

    kind: str  # board | location | user
    object_id: str  # '' for the board, the preset id, the user id
    name: str
    device_id: str
    discovery_topic: str
    state_topic: str
    discovery: Dict[str, Any]
    state: Dict[str, Any]
    entity_count: int = 0
    image_topic: Optional[str] = None
    image_id: Optional[str] = None  # the picture id behind image_topic, for change detection
    image_loader: Optional[Callable[[], Optional[bytes]]] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _tz(name: Optional[str]):
    try:
        return ZoneInfo(str(name or "UTC"))
    except Exception:
        return timezone.utc


def to_iso(value: Any, tz=None) -> Optional[str]:
    """Any of the timestamp shapes found in the caches -> ISO 8601 with offset, or None.

    Accepts datetimes, ``YYYY-MM-DD HH:MM[:SS]`` naive local strings (localised with *tz*),
    and ISO strings with or without an offset. ``Not found`` and friends become None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text or text.lower() in ("not found", "none", "null", "n/a", "unknown"):
            return None
        dt = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz or timezone.utc)
    return dt.isoformat(timespec="seconds")


def to_date(value: Any) -> Optional[str]:
    """``YYYY-MM-DD`` or None."""
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else None


def num(value: Any, digits: Optional[int] = None) -> Optional[float]:
    """A float (rounded when *digits* is given) or None for anything non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return round(result, digits) if digits is not None else result


def text(value: Any) -> Optional[str]:
    """A non-empty string capped to the HA state length, or None."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:MAX_STATE_LEN]


def _parse_dt(value: Any, tz=None) -> Optional[datetime]:
    iso = to_iso(value, tz)
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Discovery component specs
# ---------------------------------------------------------------------------


# Long-term statistics: Home Assistant records them for every sensor carrying a ``state_class``
# and keeps them after the entity is gone. Only the user's own cumulative progress (Astrodex
# counters, sessions, integration hours) is worth that - an ephemeris or forecast value is
# recomputable at any time and would only pile up orphaned series on every removal - so
# ``state_class`` is set on those six counters and nowhere else. Short-term history (the
# recorder's default 10 days) still covers every numeric sensor for graphs.
def sensor(
    key: str,
    name: str,
    *,
    device_class: Optional[str] = None,
    unit: Optional[str] = None,
    state_class: Optional[str] = None,
    icon: Optional[str] = None,
    options: Optional[List[str]] = None,
    precision: Optional[int] = None,
    diagnostic: bool = False,
    attributes: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    spec: Dict[str, Any] = {"p": "sensor", "name": name, "val_tpl": "{{ value_json.%s }}" % key}
    if device_class:
        spec["dev_cla"] = device_class
    if unit:
        spec["unit_of_meas"] = unit
    if state_class:
        spec["stat_cla"] = state_class
    if icon:
        spec["ic"] = icon
    if options:
        spec["ops"] = list(options)
    if precision is not None:
        spec["sug_dsp_prc"] = precision
    if diagnostic:
        spec["ent_cat"] = "diagnostic"
    if attributes:
        spec["json_attr_tpl"] = "{{ value_json.%s_attributes | tojson }}" % key
    return key, spec


def binary_sensor(
    key: str, name: str, *, device_class: Optional[str] = None, icon: Optional[str] = None, diagnostic: bool = False
) -> Tuple[str, Dict[str, Any]]:
    spec: Dict[str, Any] = {
        "p": "binary_sensor",
        "name": name,
        "val_tpl": "{{ 'None' if value_json.%s is none else ('ON' if value_json.%s else 'OFF') }}" % (key, key),
    }
    if device_class:
        spec["dev_cla"] = device_class
    if icon:
        spec["ic"] = icon
    if diagnostic:
        spec["ent_cat"] = "diagnostic"
    return key, spec


# Home Assistant's native `update` entity (see update.mqtt in the HA docs): richer than a
# binary_sensor(device_class="update") - it carries the installed and latest version, can link
# to release notes, and lists in HA's own Updates page / sidebar badge instead of sitting as a
# diagnostic sensor. No command_topic: MyAstroBoard has no remote self-update (it is a Docker
# image the user bumps themselves), so the entity is informational only - HA simply omits the
# Install button when none is configured, same as any integration that only reports availability.
def update(
    key: str,
    name: str,
    *,
    installed_version_key: str,
    latest_version_key: str,
    release_url: Optional[str] = None,
    icon: Optional[str] = None,
    diagnostic: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    tpl = "{{ {'installed_version': value_json.%s, 'latest_version': value_json.%s} | tojson }}" % (
        installed_version_key,
        latest_version_key,
    )
    spec: Dict[str, Any] = {"p": "update", "name": name, "val_tpl": tpl}
    if release_url:
        spec["rel_u"] = release_url
    if icon:
        spec["ic"] = icon
    if diagnostic:
        spec["ent_cat"] = "diagnostic"
    return key, spec


def _assemble(
    connector: MqttConnector,
    *,
    kind: str,
    object_id: str,
    name: str,
    model: str,
    version: str,
    components: List[Tuple[str, Dict[str, Any]]],
    state: Dict[str, Any],
    via_board: bool = True,
    image: Optional[Dict[str, Any]] = None,
) -> Device:
    """Fold component specs + state into a Device with a complete discovery payload."""
    device_id = connector.device_object_id(kind, object_id)
    state_topic = connector.state_topic(kind, object_id)
    cmps: Dict[str, Any] = {}
    for key, spec in components:
        comp = dict(spec)
        comp["uniq_id"] = f"{device_id}_{key}"
        comp["stat_t"] = state_topic
        if "json_attr_tpl" in comp:
            comp["json_attr_t"] = state_topic
        cmps[key] = comp
    if image is not None:
        comp = dict(image)
        comp["uniq_id"] = f"{device_id}_{comp.pop('key')}"
        cmps[comp.pop("cmp_key")] = comp

    dev: Dict[str, Any] = {"ids": [device_id], "name": name, "mf": MANUFACTURER, "mdl": model, "sw": version}
    if via_board:
        dev["via_device"] = connector.device_object_id("board")
    discovery = {
        "dev": dev,
        "o": {"name": MANUFACTURER, "sw": version, "url": HOMEPAGE},
        "avty_t": connector.availability_topic(),
        "qos": 0,
        "cmps": cmps,
    }
    return Device(
        kind=kind,
        object_id=object_id,
        name=name,
        device_id=device_id,
        discovery_topic=connector.discovery_topic(kind, object_id),
        state_topic=state_topic,
        discovery=discovery,
        state=state,
        entity_count=len(cmps),
    )


# ---------------------------------------------------------------------------
# Data access (lazy imports - see module docstring)
# ---------------------------------------------------------------------------


def _location_cache(name: str, location_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
    """``(data, timestamp)`` of a per-location cache, ``(None, None)`` when absent or broken."""
    try:
        from cache import cache_store  # lazy: cache/ imports connectors/ at module level

        entry = cache_store.load_location_cache(name, location_id) or {}
        data = entry.get("data")
        return (data if isinstance(data, dict) else None), entry.get("timestamp")
    except Exception as exc:
        logger.debug("MQTT: cache %s for %s unavailable: %s", name, location_id, exc)
        return None, None


def _shared_cache(name: str) -> Optional[Dict[str, Any]]:
    try:
        from cache import cache_store  # lazy: cache/ imports connectors/ at module level

        entry = cache_store.load_shared_cache_entry(name) or {}
        data = entry.get("data")
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("MQTT: shared cache %s unavailable: %s", name, exc)
        return None


def _skytonight_results(location_id: str) -> Dict[str, Any]:
    try:
        from skytonight.skytonight_calculator import load_calculation_results  # lazy: feature package

        return load_calculation_results(location_id) or {}
    except Exception as exc:
        logger.debug("MQTT: SkyTonight results for %s unavailable: %s", location_id, exc)
        return {}


def _app_version() -> str:
    try:
        from utils.txtconf_loader import get_repo_version

        return str(get_repo_version() or "").strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Board device
# ---------------------------------------------------------------------------

BOARD_COMPONENTS = [
    sensor("version", "Version", icon="mdi:tag", diagnostic=True),
    update(
        "update",
        "Update",
        installed_version_key="version",
        latest_version_key="latest_version",
        release_url=f"{HOMEPAGE}/blob/main/CHANGELOG.md",
        icon="mdi:tag-arrow-up",
        diagnostic=True,
    ),
    binary_sensor("caches_ready", "Caches ready", icon="mdi:database-check", diagnostic=True),
    binary_sensor("skytonight_running", "SkyTonight calculating", device_class="running", diagnostic=True),
    sensor("skytonight_last_run", "SkyTonight last run", device_class="timestamp", diagnostic=True),
    sensor("skytonight_next_run", "SkyTonight next run", device_class="timestamp", diagnostic=True),
    sensor("last_publish", "Last publish", device_class="timestamp", diagnostic=True),
    sensor("locations_published", "Locations published", icon="mdi:map-marker-multiple", diagnostic=True),
    sensor("users_published", "Users published", icon="mdi:account-multiple", diagnostic=True),
]


def build_board_device(connector: MqttConnector, publisher_info: Dict[str, Any]) -> Device:
    """The install-level device. *publisher_info* carries what only the publisher knows."""
    version = _app_version()
    state: Dict[str, Any] = {
        "version": version,
        "latest_version": None,
        "caches_ready": None,
        "skytonight_running": None,
        "skytonight_last_run": None,
        "skytonight_next_run": None,
        "last_publish": to_iso(publisher_info.get("last_publish")),
        "locations_published": int(publisher_info.get("locations", 0) or 0),
        "users_published": int(publisher_info.get("users", 0) or 0),
    }
    version_update = _shared_cache("version_update")
    if version_update:
        state["latest_version"] = text(version_update.get("latest_version"))
    try:
        from cache import cache_store  # lazy: cache/ imports connectors/ at module level

        state["caches_ready"] = bool(cache_store.is_astronomical_cache_ready())
    except Exception as exc:
        logger.debug("MQTT: cache readiness unavailable: %s", exc)
    try:
        from skytonight.skytonight_storage import load_scheduler_status  # lazy: feature package

        status = load_scheduler_status() or {}
        state["skytonight_running"] = bool(status.get("is_executing"))
        state["skytonight_last_run"] = to_iso(status.get("last_run"))
        state["skytonight_next_run"] = to_iso(status.get("next_run"))
    except Exception as exc:
        logger.debug("MQTT: SkyTonight scheduler status unavailable: %s", exc)

    return _assemble(
        connector,
        kind="board",
        object_id="",
        name=MANUFACTURER,
        model="Dashboard",
        version=version,
        components=BOARD_COMPONENTS,
        state=state,
        via_board=False,
    )


# ---------------------------------------------------------------------------
# Location device
# ---------------------------------------------------------------------------

SKY_COMPONENTS = [
    sensor("sky_period", "Sky period", device_class="enum", options=SKY_PERIOD_OPTIONS, icon="mdi:weather-night"),
    sensor("next_period", "Next sky period", device_class="enum", options=SKY_PERIOD_OPTIONS, icon="mdi:clock-outline"),
    sensor("next_period_at", "Next sky period at", device_class="timestamp"),
    binary_sensor("is_astronomical_night", "Astronomical night", icon="mdi:weather-night"),
    sensor("observation_score", "Observation score", icon="mdi:telescope", precision=1),
    sensor("sunrise", "Sunrise", device_class="timestamp", icon="mdi:weather-sunset-up"),
    sensor("sunset", "Sunset", device_class="timestamp", icon="mdi:weather-sunset-down"),
    sensor("civil_dusk", "Civil dusk", device_class="timestamp"),
    sensor("civil_dawn", "Civil dawn", device_class="timestamp"),
    sensor("nautical_dusk", "Nautical dusk", device_class="timestamp"),
    sensor("nautical_dawn", "Nautical dawn", device_class="timestamp"),
    sensor("astronomical_dusk", "Astronomical dusk", device_class="timestamp"),
    sensor("astronomical_dawn", "Astronomical dawn", device_class="timestamp"),
    sensor("true_night_hours", "True night duration", device_class="duration", unit="h", precision=2),
    sensor("moon_phase", "Moon phase", icon="mdi:moon-waxing-crescent"),
    sensor(
        "moon_illumination",
        "Moon illumination",
        unit="%",
        icon="mdi:brightness-6",
        precision=0,
    ),
    sensor("moon_altitude", "Moon altitude", unit="°", icon="mdi:angle-acute", precision=1),
    sensor("moon_azimuth", "Moon azimuth", unit="°", icon="mdi:compass", precision=1),
    sensor("moon_distance", "Moon distance", device_class="distance", unit="km", precision=0),
    sensor("next_moonrise", "Next moonrise", device_class="timestamp"),
    sensor("next_moonset", "Next moonset", device_class="timestamp"),
    sensor("next_full_moon", "Next full moon", device_class="timestamp", icon="mdi:moon-full"),
    sensor("next_new_moon", "Next new moon", device_class="timestamp", icon="mdi:moon-new"),
    sensor("dark_window_start", "Dark window start", device_class="timestamp"),
    sensor("dark_window_end", "Dark window end", device_class="timestamp"),
    sensor("best_window_start", "Best window start", device_class="timestamp", icon="mdi:camera-timer"),
    sensor("best_window_end", "Best window end", device_class="timestamp", icon="mdi:camera-timer"),
    sensor("best_window_duration", "Best window duration", device_class="duration", unit="h", precision=1),
    sensor("best_window_score", "Best window score", icon="mdi:star-half-full", precision=0),
    sensor("best_window_moon", "Best window moon condition", icon="mdi:moon-waning-gibbous"),
    sensor("top_target", "Top target tonight", icon="mdi:star-shooting", attributes=True),
    sensor("top_target_score", "Top target AstroScore", icon="mdi:star", precision=2),
    sensor("night_start", "SkyTonight night start", device_class="timestamp"),
    sensor("night_end", "SkyTonight night end", device_class="timestamp"),
    sensor("skytonight_calculated_at", "SkyTonight calculated at", device_class="timestamp", diagnostic=True),
]

WEATHER_COMPONENTS = [
    sensor("temperature", "Temperature", device_class="temperature", unit="°C", precision=1),
    sensor("dew_point", "Dew point", device_class="temperature", unit="°C", precision=1),
    sensor("humidity", "Humidity", device_class="humidity", unit="%", precision=0),
    sensor("cloud_cover", "Cloud cover", unit="%", icon="mdi:weather-cloudy", precision=0),
    sensor("cloud_cover_low", "Low clouds", unit="%", icon="mdi:weather-fog", precision=0),
    sensor("cloud_cover_mid", "Mid clouds", unit="%", icon="mdi:weather-cloudy", precision=0),
    sensor(
        "cloud_cover_high",
        "High clouds",
        unit="%",
        icon="mdi:weather-partly-cloudy",
        precision=0,
    ),
    sensor("wind_speed", "Wind speed", device_class="wind_speed", unit="km/h", precision=1),
    sensor("wind_direction", "Wind direction", unit="°", icon="mdi:compass-outline", precision=0),
    sensor(
        "precipitation_probability",
        "Precipitation probability",
        unit="%",
        icon="mdi:weather-rainy",
        precision=0,
    ),
    sensor(
        "precipitation",
        "Precipitation",
        device_class="precipitation",
        unit="mm",
        precision=1,
    ),
    sensor("pressure", "Pressure", device_class="atmospheric_pressure", unit="hPa", precision=0),
    sensor("visibility", "Visibility", device_class="distance", unit="m", precision=0),
    sensor("weather_code", "Weather code", icon="mdi:weather-partly-cloudy", precision=0),
    sensor("seeing", "Seeing", icon="mdi:blur", precision=1),
    sensor("transparency", "Transparency", icon="mdi:eye-outline", precision=1),
    sensor("limiting_magnitude", "Limiting magnitude", icon="mdi:star-outline", precision=1),
    sensor("dew_risk", "Dew risk", device_class="enum", options=DEW_RISK_OPTIONS, icon="mdi:water-alert"),
    sensor(
        "dew_point_spread",
        "Dew point spread",
        device_class="temperature",
        unit="°C",
        precision=1,
    ),
    sensor(
        "wind_tracking_impact",
        "Wind tracking impact",
        device_class="enum",
        options=WIND_IMPACT_OPTIONS,
        icon="mdi:weather-windy",
    ),
    sensor("tracking_stability", "Tracking stability", icon="mdi:crosshairs-gps", precision=1),
    sensor("weather_alert", "Weather alert", icon="mdi:alert-outline", attributes=True),
    sensor("forecast_updated_at", "Forecast updated at", device_class="timestamp", diagnostic=True),
]

EVENTS_COMPONENTS = [
    sensor("next_event", "Next event", icon="mdi:calendar-star", attributes=True),
    sensor("next_event_at", "Next event at", device_class="timestamp"),
    sensor("next_iss_pass_at", "Next ISS pass", device_class="timestamp", icon="mdi:satellite-variant"),
    sensor("next_iss_pass_peak_altitude", "Next ISS pass peak altitude", unit="°", icon="mdi:angle-acute", precision=0),
    sensor("next_iss_pass_duration", "Next ISS pass duration", device_class="duration", unit="min", precision=1),
    sensor("next_iss_pass_score", "Next ISS pass visibility score", icon="mdi:star-half-full", precision=1),
    sensor("next_css_pass_at", "Next CSS pass", device_class="timestamp", icon="mdi:satellite-variant"),
    sensor("next_css_pass_peak_altitude", "Next CSS pass peak altitude", unit="°", icon="mdi:angle-acute", precision=0),
    sensor("next_css_pass_duration", "Next CSS pass duration", device_class="duration", unit="min", precision=1),
    sensor("next_css_pass_score", "Next CSS pass visibility score", icon="mdi:star-half-full", precision=1),
    sensor("aurora_kp", "Aurora Kp index", icon="mdi:aurora", precision=1),
    sensor("aurora_probability", "Aurora probability", unit="%", icon="mdi:aurora", precision=0),
    sensor("aurora_visibility", "Aurora visibility", icon="mdi:aurora"),
    sensor(
        "next_solar_eclipse_at",
        "Next solar eclipse",
        device_class="timestamp",
        icon="mdi:weather-sunny-off",
        attributes=True,
    ),
    sensor(
        "next_lunar_eclipse_at", "Next lunar eclipse", device_class="timestamp", icon="mdi:moon-new", attributes=True
    ),
]


def _sky_state(location: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    lid = str(location.get("id") or "")
    tz = _tz(location.get("timezone"))
    state: Dict[str, Any] = {key: None for key, _ in SKY_COMPONENTS}
    state["top_target_attributes"] = {}

    sun_data, _ = _location_cache("sun_report", lid)
    sun = (sun_data or {}).get("sun") or {}
    try:
        from astroweather.sun_phases import determine_sky_period  # lazy: feature package

        period, next_period, secs = determine_sky_period(sun_data, str(location.get("timezone") or "UTC"))
    except Exception as exc:
        logger.debug("MQTT: sky period for %s unavailable: %s", lid, exc)
        period, next_period, secs = "unknown", "unknown", None
    state["sky_period"] = period if period in SKY_PERIOD_OPTIONS else "unknown"
    state["next_period"] = next_period if next_period in SKY_PERIOD_OPTIONS else None
    if next_period == "astronomical_dawn":
        state["next_period"] = "astronomical_twilight"
    state["next_period_at"] = to_iso(now + timedelta(seconds=secs)) if secs is not None else None
    state["is_astronomical_night"] = (period == "astronomical_night") if period != "unknown" else None
    for key in (
        "sunrise",
        "sunset",
        "civil_dusk",
        "civil_dawn",
        "nautical_dusk",
        "nautical_dawn",
        "astronomical_dusk",
        "astronomical_dawn",
    ):
        state[key] = to_iso(sun.get(key), tz)
    state["true_night_hours"] = num(sun.get("true_night_hours"), 2)

    astro, _ = _location_cache("astro_weather", lid)
    current = (astro or {}).get("current_conditions") or {}
    state["observation_score"] = num(current.get("observation_score"), 1)

    moon_data, _ = _location_cache("moon_report", lid)
    moon = (moon_data or {}).get("moon") or {}
    state["moon_phase"] = text(moon.get("phase_name"))
    state["moon_illumination"] = num(moon.get("illumination_percent"), 0)
    state["moon_altitude"] = num(moon.get("altitude_deg"), 1)
    state["moon_azimuth"] = num(moon.get("azimuth_deg"), 1)
    state["moon_distance"] = num(moon.get("distance_km"), 0)
    for key in ("next_moonrise", "next_moonset", "next_full_moon", "next_new_moon"):
        state[key] = to_iso(moon.get(key), tz)

    dark_data, _ = _location_cache("dark_window", lid)
    dark = (dark_data or {}).get("next_dark_night") or {}
    state["dark_window_start"] = to_iso(dark.get("start"), tz)
    state["dark_window_end"] = to_iso(dark.get("end"), tz)

    best_data, _ = _location_cache("best_window_practical", lid)
    best = (best_data or {}).get("best_window") or {}
    state["best_window_start"] = to_iso(best.get("start"), tz)
    state["best_window_end"] = to_iso(best.get("end"), tz)
    state["best_window_duration"] = num(best.get("duration_hours"), 1)
    state["best_window_score"] = num(best.get("score"), 0)
    state["best_window_moon"] = text(best.get("moon_condition"))

    results = _skytonight_results(lid)
    meta = results.get("metadata") or {}
    state["night_start"] = to_iso(meta.get("night_start"), tz)
    state["night_end"] = to_iso(meta.get("night_end"), tz)
    state["skytonight_calculated_at"] = to_iso(meta.get("calculated_at"))
    targets = [t for t in (results.get("deep_sky") or []) if isinstance(t, dict)]
    targets.sort(
        key=lambda t: (
            -(num(t.get("astro_score")) or 0.0),
            -(num((t.get("observation") or {}).get("max_altitude")) or 0.0),
        )
    )
    top = targets[:TOP_TARGETS]
    if top:
        first = top[0]
        state["top_target"] = text(first.get("preferred_name"))
        state["top_target_score"] = num(first.get("astro_score"), 3)
        state["top_target_attributes"] = {
            "object_type": first.get("object_type"),
            "constellation": first.get("constellation"),
            "magnitude": num(first.get("magnitude"), 2),
            "max_altitude": num((first.get("observation") or {}).get("max_altitude"), 1),
            "observable_hours": num((first.get("observation") or {}).get("observable_hours"), 2),
            "top_targets": [
                {
                    "name": t.get("preferred_name"),
                    "astro_score": num(t.get("astro_score"), 3),
                    "object_type": t.get("object_type"),
                    "constellation": t.get("constellation"),
                    "max_altitude": num((t.get("observation") or {}).get("max_altitude"), 1),
                }
                for t in top
            ],
        }
    return state


def _nearest_hourly_row(rows: List[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """The forecast row whose timestamp is closest to *now* (rows carry ISO strings)."""
    best_row, best_gap = None, None
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = _parse_dt(row.get("date") or row.get("datetime"))
        if when is None:
            continue
        gap = abs((when - now).total_seconds())
        if best_gap is None or gap < best_gap:
            best_row, best_gap = row, gap
    return best_row


def _weather_state(location: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    lid = str(location.get("id") or "")
    state: Dict[str, Any] = {key: None for key, _ in WEATHER_COMPONENTS}
    state["weather_alert_attributes"] = {}

    forecast, stamp = _location_cache("weather_forecast", lid)
    row = _nearest_hourly_row((forecast or {}).get("hourly") or [], now) or {}
    state["temperature"] = num(row.get("temperature_2m"), 1)
    state["dew_point"] = num(row.get("dew_point_2m"), 1)
    state["humidity"] = num(row.get("relative_humidity_2m"), 0)
    state["cloud_cover"] = num(row.get("cloud_cover"), 0)
    state["cloud_cover_low"] = num(row.get("cloud_cover_low"), 0)
    state["cloud_cover_mid"] = num(row.get("cloud_cover_mid"), 0)
    state["cloud_cover_high"] = num(row.get("cloud_cover_high"), 0)
    state["wind_speed"] = num(row.get("wind_speed_10m"), 1)
    state["wind_direction"] = num(row.get("wind_direction_10m"), 0)
    state["precipitation_probability"] = num(row.get("precipitation_probability"), 0)
    state["precipitation"] = num(row.get("precipitation"), 1)
    state["pressure"] = num(row.get("surface_pressure"), 0)
    state["visibility"] = num(row.get("visibility"), 0)
    state["weather_code"] = num(row.get("weather_code"), 0)
    state["forecast_updated_at"] = to_iso(datetime.fromtimestamp(stamp, tz=timezone.utc)) if stamp else None

    astro, _ = _location_cache("astro_weather", lid)
    current = (astro or {}).get("current_conditions") or {}
    state["seeing"] = num(current.get("seeing_pickering"), 1)
    state["transparency"] = num(current.get("transparency_score"), 1)
    state["limiting_magnitude"] = num(current.get("limiting_magnitude"), 1)
    dew = text(current.get("dew_risk_level"))
    state["dew_risk"] = dew.upper() if dew and dew.upper() in DEW_RISK_OPTIONS else None
    state["dew_point_spread"] = num(current.get("dew_point_spread"), 1)
    wind = text(current.get("wind_tracking_impact"))
    state["wind_tracking_impact"] = wind.upper() if wind and wind.upper() in WIND_IMPACT_OPTIONS else None
    state["tracking_stability"] = num(current.get("tracking_stability_score"), 1)
    alerts = [a for a in ((astro or {}).get("weather_alerts") or []) if a]
    if alerts:
        first = alerts[0]
        state["weather_alert"] = text(first.get("message") if isinstance(first, dict) else first)
        state["weather_alert_attributes"] = {"alerts": alerts[:10], "count": len(alerts)}
    return state


def _next_pass(passes: Any, now: datetime) -> Optional[Dict[str, Any]]:
    upcoming = []
    for item in passes or []:
        if not isinstance(item, dict):
            continue
        end = _parse_dt(item.get("end_time")) or _parse_dt(item.get("peak_time")) or _parse_dt(item.get("start_time"))
        if end is None or end < now:
            continue
        start = _parse_dt(item.get("start_time")) or end
        upcoming.append((start, item))
    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[0][1] if upcoming else None


def _events_state(location: Dict[str, Any], config: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    lid = str(location.get("id") or "")
    tz = _tz(location.get("timezone"))
    state: Dict[str, Any] = {key: None for key, _ in EVENTS_COMPONENTS}
    state["next_event_attributes"] = {}
    state["next_solar_eclipse_at_attributes"] = {}
    state["next_lunar_eclipse_at_attributes"] = {}

    caches = {
        name: _location_cache(name, lid)[0]
        for name in (
            "solar_eclipse",
            "lunar_eclipse",
            "aurora",
            "iss_passes",
            "css_passes",
            "moon_planner",
            "planetary_events",
            "special_phenomena",
            "solar_system_events",
        )
    }

    for station in ("iss", "css"):
        item = _next_pass((caches.get(f"{station}_passes") or {}).get("passes"), now)
        if item:
            state[f"next_{station}_pass_at"] = to_iso(item.get("start_time"), tz)
            state[f"next_{station}_pass_peak_altitude"] = num(item.get("peak_altitude_deg"), 0)
            state[f"next_{station}_pass_duration"] = num(item.get("duration_minutes"), 1)
            state[f"next_{station}_pass_score"] = num(item.get("visibility_score"), 1)

    aurora = (caches.get("aurora") or {}).get("current") or {}
    state["aurora_kp"] = num(aurora.get("kp_index"), 1)
    state["aurora_probability"] = num(aurora.get("probability"), 0)
    state["aurora_visibility"] = text(aurora.get("visibility_level"))

    solar = (caches.get("solar_eclipse") or {}).get("solar_eclipse") or {}
    if solar:
        state["next_solar_eclipse_at"] = to_iso(solar.get("peak_time"), tz)
        state["next_solar_eclipse_at_attributes"] = {
            "type": solar.get("type"),
            "obscuration_percent": num(solar.get("obscuration_percent"), 1),
            "start": to_iso(solar.get("start_time"), tz),
            "end": to_iso(solar.get("end_time"), tz),
            "visible": solar.get("visible"),
        }
    lunar = (caches.get("lunar_eclipse") or {}).get("lunar_eclipse") or {}
    if lunar:
        state["next_lunar_eclipse_at"] = to_iso(lunar.get("peak_time"), tz)
        state["next_lunar_eclipse_at_attributes"] = {
            "type": lunar.get("type"),
            "start": to_iso(lunar.get("partial_begin"), tz),
            "end": to_iso(lunar.get("partial_end"), tz),
            "visible": lunar.get("visible"),
        }

    try:
        from utils.events_aggregator import EventsAggregator

        aggregator = EventsAggregator(
            float(location.get("latitude") or 0.0),
            float(location.get("longitude") or 0.0),
            str(location.get("timezone") or "UTC"),
            language=str(config.get("language") or "en"),
        )
        events = aggregator.aggregate_all_events(
            solar_eclipse_data=caches.get("solar_eclipse"),
            lunar_eclipse_data=caches.get("lunar_eclipse"),
            aurora_data=caches.get("aurora"),
            iss_passes_data=caches.get("iss_passes"),
            css_passes_data=caches.get("css_passes"),
            moon_phases_data=caches.get("moon_planner"),
            planetary_events_data=caches.get("planetary_events"),
            special_phenomena_data=caches.get("special_phenomena"),
            solar_system_events_data=caches.get("solar_system_events"),
        )
        nxt = events.get("next_event") or {}
        if nxt:
            state["next_event"] = text(nxt.get("title"))
            state["next_event_at"] = to_iso(nxt.get("peak_time") or nxt.get("start_time"), tz)
            state["next_event_attributes"] = {
                "event_type": nxt.get("event_type"),
                "description": text(nxt.get("description")),
                "start": to_iso(nxt.get("start_time"), tz),
                "peak": to_iso(nxt.get("peak_time"), tz),
                "end": to_iso(nxt.get("end_time"), tz),
                "days_until": nxt.get("days_until_event"),
                "importance": nxt.get("importance"),
                "visible": nxt.get("visibility"),
                "events_count": events.get("events_count"),
            }
    except Exception as exc:
        logger.debug("MQTT: events aggregation for %s failed: %s", lid, exc)
    return state


def build_location_device(
    connector: MqttConnector, config: Dict[str, Any], location: Dict[str, Any], now: Optional[datetime] = None
) -> Optional[Device]:
    """One device per location preset, holding whichever location modules are enabled."""
    now = now or datetime.now(timezone.utc)
    components: List[Tuple[str, Dict[str, Any]]] = []
    state: Dict[str, Any] = {
        "location_id": location.get("id"),
        "location_name": location.get("name"),
        "timezone": location.get("timezone"),
    }
    if connector.is_module_enabled("sky_conditions"):
        components.extend(SKY_COMPONENTS)
        state.update(_sky_state(location, now))
    if connector.is_module_enabled("weather_now"):
        components.extend(WEATHER_COMPONENTS)
        state.update(_weather_state(location, now))
    if connector.is_module_enabled("upcoming_events"):
        components.extend(EVENTS_COMPONENTS)
        state.update(_events_state(location, config, now))
    if not components:
        return None
    name = f"{MANUFACTURER} - {text(location.get('name')) or 'Location'}"
    return _assemble(
        connector,
        kind="location",
        object_id=str(location.get("id") or ""),
        name=name,
        model="Location",
        version=_app_version(),
        components=components,
        state=state,
    )


# ---------------------------------------------------------------------------
# User device
# ---------------------------------------------------------------------------

USER_COMPONENTS = [
    sensor("astrodex_objects", "Astrodex objects", state_class="total", icon="mdi:star-box-multiple", precision=0),
    sensor(
        "astrodex_objects_with_pictures",
        "Astrodex objects with pictures",
        state_class="total",
        icon="mdi:image-multiple",
        precision=0,
    ),
    sensor("astrodex_pictures", "Astrodex pictures", state_class="total", icon="mdi:image", precision=0),
    sensor("astrodex_constellations", "Astrodex constellations", state_class="total", icon="mdi:creation", precision=0),
    sensor("astrodex_last_picture_at", "Last Astrodex picture", device_class="timestamp", icon="mdi:camera"),
    sensor("astrodex_last_picture_object", "Last Astrodex picture object", icon="mdi:camera", attributes=True),
    sensor("plan_state", "Plan state", device_class="enum", options=PLAN_STATE_OPTIONS, icon="mdi:clipboard-list"),
    binary_sensor("plan_active", "Plan in progress", device_class="running", icon="mdi:clipboard-play"),
    sensor("plan_progress", "Plan progress", unit="%", icon="mdi:progress-clock", precision=0),
    sensor("plan_current_target", "Plan current target", icon="mdi:target", attributes=True),
    sensor("plan_next_target", "Plan next target", icon="mdi:skip-next"),
    sensor("plan_night_start", "Plan night start", device_class="timestamp"),
    sensor("plan_night_end", "Plan night end", device_class="timestamp"),
    sensor("plan_targets_total", "Plan targets", icon="mdi:format-list-numbered", precision=0),
    sensor("plan_targets_done", "Plan targets done", icon="mdi:check-all", precision=0),
    sensor("plan_location", "Plan location", icon="mdi:map-marker"),
    sensor("active_equipment", "Active equipment", icon="mdi:telescope", attributes=True),
    sensor("sessions_total", "Observation sessions", state_class="total", icon="mdi:notebook", precision=0),
    sensor(
        "integration_hours_total",
        "Total integration",
        device_class="duration",
        unit="h",
        state_class="total",
        precision=1,
    ),
    sensor("last_session_date", "Last observation session", device_class="date", icon="mdi:calendar-check"),
]


def user_opted_in(user: Any) -> bool:
    prefs = getattr(user, "preferences", None)
    return bool(isinstance(prefs, dict) and prefs.get(USER_OPT_IN_PREFERENCE))


def _astrodex_state(user_id: str, username: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fill the astrodex_* keys; returns the newest picture record (with its item) or None."""
    try:
        from observation import astrodex  # lazy: observation/ imports connectors/ at module level

        data = astrodex.load_user_astrodex(user_id, username) or {}
    except Exception as exc:
        logger.debug("MQTT: astrodex for %s unavailable: %s", username, exc)
        return None
    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    pictures: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    constellations = set()
    for item in items:
        if text(item.get("constellation")):
            constellations.add(str(item.get("constellation")).strip().lower())
        for pic in item.get("pictures") or []:
            if isinstance(pic, dict):
                pictures.append((str(pic.get("created_at") or pic.get("date") or ""), pic, item))
    state["astrodex_objects"] = len(items)
    state["astrodex_objects_with_pictures"] = sum(1 for i in items if i.get("pictures"))
    state["astrodex_pictures"] = len(pictures)
    state["astrodex_constellations"] = len(constellations)
    if not pictures:
        return None
    pictures.sort(key=lambda entry: entry[0], reverse=True)
    _, pic, item = pictures[0]
    state["astrodex_last_picture_at"] = to_iso(pic.get("created_at") or pic.get("date"))
    state["astrodex_last_picture_object"] = text(item.get("name"))
    state["astrodex_last_picture_object_attributes"] = {
        "catalogue": item.get("catalogue"),
        "object_type": item.get("type"),
        "constellation": item.get("constellation"),
        "date": to_date(pic.get("date")),
        "equipment": text(pic.get("device")),
        "rating": num(pic.get("rating"), 1),
        "integration_minutes": num(pic.get("integration_minutes"), 1),
    }
    return {"picture": pic, "item": item}


def _plan_state(user_id: str, username: str, config: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    """Fill the plan_* keys; returns the active plan's combination id (for the equipment)."""
    try:
        from observation.plan_my_night import pick_active_plan  # lazy: observation/ imports connectors/

        payload = pick_active_plan(user_id, username)
    except Exception as exc:
        logger.debug("MQTT: plan for %s unavailable: %s", username, exc)
        payload = None
    if not payload:
        state["plan_state"] = "none"
        state["plan_active"] = False
        state["plan_progress"] = 0
        state["plan_targets_total"] = 0
        state["plan_targets_done"] = 0
        return None
    plan = payload.get("plan") or {}
    timeline = payload.get("timeline") or {}
    entries = [e for e in (plan.get("entries") or []) if isinstance(e, dict)]
    plan_state = payload.get("state") if payload.get("state") in PLAN_STATE_OPTIONS else "none"
    state["plan_state"] = plan_state
    state["plan_active"] = bool(timeline.get("is_inside_night"))
    state["plan_progress"] = num(timeline.get("progress_percent"), 0)
    state["plan_night_start"] = to_iso(plan.get("night_start"))
    state["plan_night_end"] = to_iso(plan.get("night_end"))
    state["plan_targets_total"] = len(entries)
    state["plan_targets_done"] = sum(1 for e in entries if e.get("done"))

    current = payload.get("current_banner") or {}
    if current:
        state["plan_current_target"] = text(current.get("name"))
        state["plan_current_target_attributes"] = {
            "catalogue": current.get("catalogue"),
            "object_type": current.get("type") or current.get("object_type"),
            "planned_minutes": num(current.get("planned_minutes"), 0),
            "slot_start": to_iso(current.get("timeline_start")),
            "slot_end": to_iso(current.get("timeline_end")),
            "visibility": current.get("visibility"),
            "meridian_flip": (
                (current.get("meridian_flip") or {}).get("state")
                if isinstance(current.get("meridian_flip"), dict)
                else None
            ),
        }
    current_id = timeline.get("current_target_id")
    remaining = [e for e in entries if not e.get("done") and e.get("id") != current_id]
    if current_id:
        after = [e for e in entries if e.get("id") == current_id]
        if after:
            idx = entries.index(after[0])
            remaining = [e for e in entries[idx + 1 :] if not e.get("done")]
    if remaining:
        state["plan_next_target"] = text(remaining[0].get("name"))

    location_id = plan.get("location_id")
    if location_id:
        try:
            from utils.repo_config import get_location_by_id

            loc = get_location_by_id(config, location_id)
            state["plan_location"] = text((loc or {}).get("name"))
        except Exception:
            state["plan_location"] = None
    return plan.get("combination_id") or None


def _equipment_state(user_id: str, combination_id: Optional[str], state: Dict[str, Any]) -> None:
    if not combination_id:
        return
    try:
        from equipment import equipment_profiles  # lazy: feature package

        combo = equipment_profiles.get_combination(user_id, combination_id)
        if combo is None:
            for shared in equipment_profiles.load_all_shared_combinations(user_id):
                if shared.get("id") == combination_id:
                    combo = shared
                    break
        if combo is None:
            return
        own, shared_items = equipment_profiles.index_owned_and_shared_equipment(user_id)
        by_id = {**shared_items, **own}

        def _name(item_id):
            item = by_id.get(item_id) if item_id else None
            return text(item.get("name")) if item else None

        telescope_id = combo.get("telescope_id")
        telescope = by_id.get(str(telescope_id)) if telescope_id else None
        state["active_equipment"] = text(combo.get("name"))
        state["active_equipment_attributes"] = {
            "telescope": _name(combo.get("telescope_id")),
            "camera": _name(combo.get("camera_id")),
            "guide_camera": _name(combo.get("guide_camera_id")),
            "mount": _name(combo.get("mount_id")),
            "filters": [n for n in (_name(f) for f in (combo.get("filter_ids") or [])) if n],
            "accessories": [n for n in (_name(a) for a in (combo.get("accessory_ids") or [])) if n],
            "focal_length_mm": num((telescope or {}).get("focal_length_mm") or combo.get("lens_focal_length_mm"), 0),
            "aperture_mm": num((telescope or {}).get("aperture_mm"), 0),
            "disabled": bool(combo.get("is_disabled")),
        }
    except Exception as exc:
        logger.debug("MQTT: equipment for %s unavailable: %s", user_id, exc)


def _sessions_state(user_id: str, state: Dict[str, Any]) -> None:
    try:
        from observation import observation_sessions, session_analytics  # lazy: feature package

        sessions = observation_sessions.get_user_sessions(user_id)
    except Exception as exc:
        logger.debug("MQTT: observation log for %s unavailable: %s", user_id, exc)
        return
    state["sessions_total"] = len(sessions)
    minutes = 0.0
    last_date: Optional[str] = None
    try:
        for session, night, entry in session_analytics.iter_entries(sessions):
            minutes += float(session_analytics.entry_integration_minutes(entry) or 0.0)
            day = session_analytics.entry_date(night)
            if day and (last_date is None or day > last_date):
                last_date = day
        if last_date is None:
            for session in sessions:
                _, end = observation_sessions.session_date_range(session)
                if end and (last_date is None or end > last_date):
                    last_date = end
    except Exception as exc:
        logger.debug("MQTT: session totals for %s unavailable: %s", user_id, exc)
    state["integration_hours_total"] = round(minutes / 60.0, 1)
    state["last_session_date"] = to_date(last_date)


def _image_loader(connector: MqttConnector, picture: Dict[str, Any]) -> Callable[[], Optional[bytes]]:
    """Encode the picture as a bounded JPEG when (and only when) the publisher asks for it."""

    def _load() -> Optional[bytes]:
        try:
            from observation import astrodex  # lazy: observation/ imports connectors/ at module level

            path = astrodex._resolve_image_file_path(picture.get("filename"))
        except Exception as exc:
            logger.debug("MQTT: picture path unavailable: %s", exc)
            return None
        if not path:
            return None
        return encode_thumbnail(
            path, connector.IMAGE_MAX_EDGE_PX, connector.IMAGE_MAX_BYTES, connector.IMAGE_JPEG_QUALITY
        )

    return _load


def encode_thumbnail(path: str, max_edge: int, max_bytes: int, quality: int) -> Optional[bytes]:
    """A JPEG of *path* no larger than *max_edge* px and *max_bytes*, or None when impossible."""
    try:
        import io

        from PIL import Image, ImageOps  # lazy, like the Observation Log PDF export

        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
            for edge in (max_edge, 1024, 800, 640):
                if edge > max_edge:
                    continue
                work = img.copy()
                work.thumbnail((edge, edge))
                buffer = io.BytesIO()
                work.save(buffer, format="JPEG", quality=quality, optimize=True)
                data = buffer.getvalue()
                if len(data) <= max_bytes:
                    return data
        logger.warning("MQTT: picture %s exceeds %d bytes even at 640 px, not published", path, max_bytes)
    except Exception as exc:
        logger.warning("MQTT: could not encode picture %s: %s", path, exc)
    return None


def build_user_device(
    connector: MqttConnector, config: Dict[str, Any], user: Any, now: Optional[datetime] = None
) -> Optional[Device]:
    """One device per opted-in user. None when nothing is enabled for them."""
    user_id = str(getattr(user, "user_id", "") or "")
    username = str(getattr(user, "username", "") or "")
    if not user_id or not user_opted_in(user):
        return None
    activity = connector.is_module_enabled("user_activity")
    image_wanted = connector.is_module_enabled("astrodex_image")
    if not activity and not image_wanted:
        return None

    state: Dict[str, Any] = {"user_id": user_id, "username": username}
    components: List[Tuple[str, Dict[str, Any]]] = []
    image_spec: Optional[Dict[str, Any]] = None
    image_topic: Optional[str] = None
    image_id: Optional[str] = None
    loader: Optional[Callable[[], Optional[bytes]]] = None

    if activity:
        components.extend(USER_COMPONENTS)
        state.update({key: None for key, _ in USER_COMPONENTS})
        state["astrodex_last_picture_object_attributes"] = {}
        state["plan_current_target_attributes"] = {}
        state["active_equipment_attributes"] = {}
        latest = _astrodex_state(user_id, username, state)
        combination_id = _plan_state(user_id, username, config, state)
        _equipment_state(user_id, combination_id, state)
        _sessions_state(user_id, state)
    else:
        scratch: Dict[str, Any] = {}
        latest = _astrodex_state(user_id, username, scratch)

    if image_wanted:
        image_topic = connector.image_topic(user_id)
        state["latest_picture_attributes"] = {}
        if latest:
            pic = latest["picture"]
            image_id = str(pic.get("id") or pic.get("filename") or "")
            loader = _image_loader(connector, pic)
            state["latest_picture_attributes"] = {
                "object": text(latest["item"].get("name")),
                "catalogue": latest["item"].get("catalogue"),
                "date": to_date(pic.get("date")),
                "equipment": text(pic.get("device")),
                "rating": num(pic.get("rating"), 1),
                "picture_id": image_id,
            }
        image_spec = {
            "key": "latest_picture",
            "cmp_key": "latest_picture",
            "p": "image",
            "name": "Latest Astrodex picture",
            "img_t": image_topic,
            "content_type": "image/jpeg",
            "ic": "mdi:image-filter-hdr",
            "json_attr_t": connector.state_topic("user", user_id),
            "json_attr_tpl": "{{ value_json.latest_picture_attributes | tojson }}",
        }

    device = _assemble(
        connector,
        kind="user",
        object_id=user_id,
        name=f"{MANUFACTURER} - {username or user_id}",
        model="User",
        version=_app_version(),
        components=components,
        state=state,
        image=image_spec,
    )
    if image_wanted:
        device.image_topic = image_topic
        device.image_id = image_id or None
        device.image_loader = loader
    return device


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect(
    connector: MqttConnector, config: Dict[str, Any], publisher_info: Dict[str, Any], now: Optional[datetime] = None
) -> List[Device]:
    """Every device to publish this cycle: locations, opted-in users, then the board.

    The board goes last so its counters reflect what this cycle produced. A builder that
    fails logs and is skipped - one broken cache never blocks the others.
    """
    now = now or datetime.now(timezone.utc)
    devices: List[Device] = []

    if any(connector.is_module_enabled(slug) for slug in ("sky_conditions", "weather_now", "upcoming_events")):
        try:
            from utils.repo_config import get_scheduler_locations

            locations = get_scheduler_locations(config)
        except Exception as exc:
            logger.warning("MQTT: could not list locations: %s", exc)
            locations = []
        for location in locations:
            if not isinstance(location, dict) or not location.get("id"):
                continue
            try:
                device = build_location_device(connector, config, location, now)
            except Exception as exc:
                logger.error("MQTT: location device %s failed: %s", location.get("id"), exc)
                continue
            if device:
                devices.append(device)
    locations_count = len(devices)

    users_count = 0
    if connector.is_module_enabled("user_activity") or connector.is_module_enabled("astrodex_image"):
        try:
            from utils.auth import user_manager  # lazy: avoid an import cycle at module load

            user_manager._reload_users_if_changed()
            users = list(user_manager.users.values())
        except Exception as exc:
            logger.warning("MQTT: could not list users: %s", exc)
            users = []
        for user in users:
            try:
                device = build_user_device(connector, config, user, now)
            except Exception as exc:
                logger.error("MQTT: user device %s failed: %s", getattr(user, "username", "?"), exc)
                continue
            if device:
                devices.append(device)
                users_count += 1

    if connector.is_module_enabled("board_diagnostics"):
        info = dict(publisher_info)
        info["locations"] = locations_count
        info["users"] = users_count
        try:
            devices.append(build_board_device(connector, info))
        except Exception as exc:
            logger.error("MQTT: board device failed: %s", exc)
    return devices
