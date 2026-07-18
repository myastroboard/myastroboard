"""
Cache functions for heavy computations.
All cache management is server-side with TTL-based expiration.

Multi-location model (v1.2): every location-dependent job runs once per
"active" location (install default + presets attributed to at least one user,
see repo_config.get_scheduler_locations). Editing one preset's coordinates
resets only that preset's caches. Location-independent jobs (spaceflight,
IERS, AllSky) keep running exactly once per cycle.
"""

from datetime import datetime
import time
from typing import Callable, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.logging_config import get_logger

from utils.repo_config import load_config, get_all_locations, get_install_default_location, get_scheduler_locations
from astroweather.moon_astrotonight import AstroTonightService
from astroweather.moon_phases import MoonService
from astroweather.moon_planner import MoonPlanner
from astroweather.sun_phases import SunService
from astroweather.sun_eclipse import SolarEclipseService
from astroweather.moon_eclipse import LunarEclipseService
from astroweather.horizon_graph import HorizonGraphService
from astroweather.aurora_predictions import get_aurora_report
from space.iss_passes import get_iss_passes_report
from space.css_passes import get_css_passes_report
from weather.weather_openmeteo import get_hourly_forecast
from utils import slugify_location_name
from cache import cache_store
from utils.constants import (
    WEATHER_CACHE_TTL,
    CACHE_TTL_MOON_REPORT,
    CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_SUN_REPORT,
    CACHE_TTL_BEST_WINDOW,
    CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_LUNAR_ECLIPSE,
    CACHE_TTL_HORIZON_GRAPH,
    CACHE_TTL_AURORA,
    CACHE_TTL_ISS_PASSES,
    CACHE_TTL_CSS_PASSES,
    CACHE_TTL_PLANETARY_EVENTS,
    CACHE_TTL_SPECIAL_PHENOMENA,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS,
    CACHE_TTL_SIDEREAL_TIME,
    CACHE_TTL_SEEING_FORECAST,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES,
    CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
    CACHE_TTL_SPACEFLIGHT_EVENTS,
    CACHE_TTL_IERS,
    CACHE_TTL_ALLSKY_SENSOR,
    CACHE_TTL_ALLSKY_HEALTH,
)

# Initialize logger for this module
logger = get_logger(__name__)

# One-time-per-process guard for the pre-v1.2 cache key migration
_legacy_cache_migration_done = False


def _resolve_job_location(config, location):
    """Return the location preset a cache job should compute for.

    Jobs called directly (tests, manual refresh) without a location fall back
    to the install default preset. A config with no usable preset raises so
    each job's try/except logs the error instead of computing (or fetching)
    for a location nobody configured.
    """
    if isinstance(location, dict) and location.get("id"):
        return location
    default = get_install_default_location(config)
    if not default.get("id"):
        raise ValueError("Location configuration is missing")
    return default


def _masked_location_log(location):
    """Return a safe, masked location string for logs without leaking timezone details."""

    def _safe_coord(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return "?"

    return (
        f"Using location: lat={_safe_coord(location.get('latitude'))}, "
        f"lon={_safe_coord(location.get('longitude'))}, tz=***"
    )


def check_and_handle_config_changes():
    """
    Check if any location preset's parameters have changed.
    Resets the caches of each changed preset only (not the whole install).
    Also performs the one-time pre-v1.2 -> v1.2 cache key migration.
    """
    global _legacy_cache_migration_done

    config = load_config()
    locations = get_all_locations(config)
    if not locations:
        return False

    # --- One-time upgrade path -------------------------------------------
    # Transfer the pre-v1.2 flat signature + plain cache keys onto the
    # migrated install-default preset so the warm cache survives the upgrade.
    if not _legacy_cache_migration_done:
        install_default = get_install_default_location(config)
        legacy_signature = cache_store.pop_legacy_location_signature()
        if legacy_signature is not None:
            migrated = cache_store.migrate_legacy_cache_keys(install_default["id"])
            current_signature = cache_store.get_current_location_signature(install_default)
            if legacy_signature == current_signature:
                cache_store.update_location_config(install_default)
                logger.info(
                    "Migrated %d legacy cache entries onto location preset '%s'",
                    migrated,
                    install_default.get("name"),
                )
            else:
                # Config was edited between upgrade steps - migrated data is stale
                cache_store.reset_caches_for_location(install_default["id"])
                cache_store.update_location_config(install_default)
                logger.warning("Legacy location signature mismatch - reset migrated caches")
        else:
            # No legacy signature but plain keys may still exist (idempotent no-op otherwise)
            cache_store.migrate_legacy_cache_keys(install_default["id"])
        _legacy_cache_migration_done = True

    # --- Per-preset change detection --------------------------------------
    any_changed = False
    for location in locations:
        if not cache_store.is_location_tracked(location):
            # First time seeing this preset - just start tracking it
            logger.info(f"Tracking new location preset: {location.get('name')}")
            cache_store.update_location_config(location)
            continue
        if cache_store.has_location_changed(location):
            logger.warning("Location preset '%s' changed! Resetting its astronomical caches.", location.get("name"))
            cache_store.reset_caches_for_location(location["id"])
            cache_store.update_location_config(location)
            any_changed = True

    return any_changed


def update_moon_report_cache(config=None, location=None):
    """
    Updates the Moon report cache.
    Delegates to update_moon_caches() so the MoonService report is computed once.
    """
    update_moon_caches(config=config, location=location)


def update_dark_window_cache(config=None, location=None):
    """
    Updates the dark window cache.
    Delegates to update_moon_caches() so the MoonService report is computed once.
    """
    update_moon_caches(config=config, location=location)


def update_moon_caches(config=None, location=None):
    """
    Computes MoonService.get_report() ONCE and writes both the moon_report and
    dark_window caches. Calling the two caches separately would instantiate
    MoonService and run all Astropy calculations twice with identical inputs.
    """
    try:
        logger.info("Updating Moon report + Dark window caches (single pass)...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        moon = MoonService(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        report = moon.get_report()
        now_ts = time.time()

        # --- moon_report ---
        report_json = {}
        for k, v in report.__dict__.items():
            if isinstance(v, bytes):
                report_json[k] = v.decode("utf-8")
            else:
                report_json[k] = v

        moon_response = {"location": location, "moon": report_json}
        cache_store.update_location_cache("moon_report", location["id"], moon_response, now_ts)

        # --- dark_window (derived from the same report) ---
        dark_response = {"next_dark_night": {"start": report.next_dark_night_start, "end": report.next_dark_night_end}}
        cache_store.update_location_cache("dark_window", location["id"], dark_response, now_ts)

        logger.info(f"Moon report + Dark window caches updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Moon/Dark window caches: {e}")


def update_moon_planner_cache(config=None, location=None):
    """
    Updates the Moon Planner cache (next 7 nights report)
    """
    try:
        logger.debug("Updating Moon Planner cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        planner = MoonPlanner(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        nights = planner.next_7_nights()

        response = {
            "location": location,
            "next_7_nights": nights,
            "units": {"dark_hours": "hours", "altitude": "degrees", "illumination": "percent"},
        }

        cache_store.update_location_cache("moon_planner", location["id"], response)

        logger.info(f"Moon Planner cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Moon Planner cache: {e}")


def _next_astronomical_dusk_utc(sun_service, tz_name: str) -> str | None:
    """Return the next upcoming astronomical dusk as a UTC ISO string.

    Looks at today's and tomorrow's reports so the value stays valid even
    when the cache refreshes after midnight UTC (before local dusk has passed).
    """
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt, timezone as _tz

    tz = ZoneInfo(tz_name)
    now_utc = _dt.now(_tz.utc)

    for report in (sun_service.get_today_report(), sun_service.get_tomorrow_report()):
        dusk_str = report.astronomical_dusk
        if not dusk_str or dusk_str == 'Not found':
            continue
        try:
            dusk_local = _dt.fromisoformat(dusk_str).replace(tzinfo=tz)
            dusk_utc = dusk_local.astimezone(_tz.utc)
            if dusk_utc > now_utc:
                return dusk_utc.isoformat()
        except Exception:
            continue
    return None


def update_sun_report_cache(config=None, location=None):
    """
    Updates the Sun report cache (today report)
    """
    try:
        logger.debug("Updating Sun report cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        sun = SunService(latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"])

        report = sun.get_today_report()

        # Compute next upcoming astronomical dusk as a UTC ISO string.
        # The report stores times as naive local strings, which would be misinterpreted
        # as UTC by consumers. We resolve this once here and store an unambiguous value.
        next_dusk_utc = _next_astronomical_dusk_utc(sun, location["timezone"])

        response = {
            "location": location,
            "sun": report.__dict__,
            "next_astronomical_dusk_utc": next_dusk_utc,
            "units": {"times": "local timezone", "true_night_hours": "hours"},
        }

        cache_store.update_location_cache("sun_report", location["id"], response)

        logger.info(f"Sun report cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Sun report cache: {e}")


def update_best_window_cache(config=None, location=None):
    """
    Updates all three best-window caches (strict, practical, illumination) in a single
    night scan - altitudes are computed once per time-step instead of once per mode.
    """
    try:
        logger.debug("Updating Best window cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        service = AstroTonightService(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        # Single-pass: all 3 modes computed with one time-step loop
        windows = service.best_windows_all_modes()

        for mode, window in windows.items():
            payload = {
                "location": location,
                "mode": mode,
                "best_window": window.__dict__,
                "units": {"times": "local timezone", "duration": "hours", "score": "0-100"},
            }
            cache_store.update_location_cache(f"best_window_{mode}", location["id"], payload)

        logger.info(f"Best window cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update best window cache: {e}")


def update_weather_cache(config=None, location=None):
    """
    Updates the weather forecast cache for one location.
    Pre-fetches weather data from Open-Meteo API and caches it.
    """
    try:
        logger.debug("Updating Weather forecast cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        forecast = get_hourly_forecast(location=location)

        if forecast is None:
            stale_entry = cache_store.load_location_cache("weather_forecast", location["id"])
            if stale_entry.get("data"):
                logger.warning(
                    "Live weather fetch failed for location %s; keeping existing cached weather payload",
                    location.get("id"),
                )
            else:
                logger.warning("Failed to fetch weather forecast - API returned None (no stale cache available)")
            return

        # Serialize to JSON-compatible format so the endpoint can serve directly from cache
        df = forecast["hourly"].copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: x.decode() if isinstance(x, bytes) else x)
        location_info = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in forecast["location"].items()}

        payload = {"location": location_info, "hourly": df.to_dict(orient="records")}
        cache_store.update_location_cache("weather_forecast", location["id"], payload)

        logger.info(f"Weather forecast cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Weather forecast cache: {e}")


def update_solar_eclipse_cache(config=None, location=None):
    """
    Updates the Solar Eclipse cache
    """
    try:
        logger.debug("Updating Solar Eclipse cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        eclipse_service = SolarEclipseService(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        eclipse = eclipse_service.get_next_eclipse()

        if eclipse is None:
            response = {
                "location": location,
                "solar_eclipse": None,
                "message": "No solar eclipse found in the next 18 months",
            }
        else:
            # Convert dataclass to dict
            eclipse_dict = eclipse.__dict__.copy()
            # Convert altitude_vs_time EclipsePoint objects to dicts
            if "altitude_vs_time" in eclipse_dict:  # pragma: no branch
                eclipse_dict["altitude_vs_time"] = [point.__dict__ for point in eclipse_dict["altitude_vs_time"]]

            response = {
                "location": location,
                "solar_eclipse": eclipse_dict,
                "units": {
                    "times": "ISO format local timezone",
                    "altitude": "degrees",
                    "azimuth": "degrees",
                    "duration": "minutes",
                    "astrophotography_score": "0-10",
                },
            }

        cache_store.update_location_cache("solar_eclipse", location["id"], response)

        logger.info(f"Solar eclipse cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Solar Eclipse cache: {e}", exc_info=True)


def update_lunar_eclipse_cache(config=None, location=None):
    """
    Updates the Lunar Eclipse cache
    """
    try:
        logger.debug("Updating Lunar Eclipse cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        eclipse_service = LunarEclipseService(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        eclipse = eclipse_service.get_next_eclipse()

        if eclipse is None:
            response = {
                "location": location,
                "lunar_eclipse": None,
                "message": "No lunar eclipse found in the next 18 months",
            }
        else:
            # Convert dataclass to dict
            eclipse_dict = eclipse.__dict__.copy()
            # Convert altitude_vs_time EclipsePoint objects to dicts
            if "altitude_vs_time" in eclipse_dict:  # pragma: no branch
                eclipse_dict["altitude_vs_time"] = [point.__dict__ for point in eclipse_dict["altitude_vs_time"]]

            response = {
                "location": location,
                "lunar_eclipse": eclipse_dict,
                "units": {
                    "times": "ISO format local timezone",
                    "altitude": "degrees",
                    "azimuth": "degrees",
                    "duration": "minutes",
                    "astrophotography_score": "0-10",
                },
            }

        cache_store.update_location_cache("lunar_eclipse", location["id"], response)

        logger.info(f"Lunar eclipse cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Lunar Eclipse cache: {e}", exc_info=True)


def update_horizon_graph_cache(config=None, location=None):
    """
    Updates the Horizon Graph cache (sun and moon positions throughout the day)
    """
    try:
        logger.info("Updating Horizon Graph cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        horizon_service = HorizonGraphService(
            latitude=location["latitude"], longitude=location["longitude"], timezone=location["timezone"]
        )

        horizon_data = horizon_service.get_horizon_data()

        if horizon_data is None:
            response = {
                "location": location,
                "horizon_data": None,
                "message": "Failed to calculate horizon data",
            }
        else:
            # Convert dataclass to dict
            horizon_dict = horizon_data.__dict__.copy()
            # Convert HorizonPoint objects to dicts
            if "sun_data" in horizon_dict:  # pragma: no branch
                horizon_dict["sun_data"] = [point.__dict__ for point in horizon_dict["sun_data"]]
            if "moon_data" in horizon_dict:  # pragma: no branch
                horizon_dict["moon_data"] = [point.__dict__ for point in horizon_dict["moon_data"]]

            response = {
                "location": location,
                "horizon_data": horizon_dict,
                "units": {"altitude": "degrees", "azimuth": "degrees", "time": "HH:MM local timezone"},
            }

        cache_store.update_location_cache("horizon_graph", location["id"], response)

        logger.info(f"Horizon Graph cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Horizon Graph cache: {e}", exc_info=True)


def update_aurora_cache(config=None, location=None):
    """
    Updates the Aurora Borealis predictions cache.
    The NOAA Kp fetch is location-independent (and internally cached by the
    aurora service); only the local visibility math varies per location.
    """
    try:
        logger.info("Updating Aurora Borealis predictions cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        # Get aurora report
        report = get_aurora_report(
            latitude=location["latitude"], longitude=location["longitude"], timezone_str=location["timezone"]
        )

        if report is None:
            raise ValueError("Failed to generate aurora report")

        cache_store.update_location_cache("aurora", location["id"], report)

        logger.info(f"Aurora cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Aurora cache: {e}", exc_info=True)


def update_iss_passes_cache(days: int = 20, config=None, location=None):
    """
    Updates the ISS passes cache for one location.
    The TLE fetch inside the pass service is satellite-specific (not observer-
    specific) and has its own on-disk cache shared by all locations; only the
    local Skyfield pass-visibility computation runs per location.
    """
    try:
        logger.info("Updating ISS passes cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        report = get_iss_passes_report(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation_m=location.get("elevation", 0),
            timezone_str=location["timezone"],
            days=days,
        )

        if report is None:
            logger.warning("ISS passes report unavailable (provider/network/cache miss); keeping previous cache state")
            return

        cache_store.update_location_cache("iss_passes", location["id"], report)

        logger.info(f"ISS passes cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.warning(f"Failed to update ISS passes cache: {e}")


def update_css_passes_cache(days: int = 20, config=None, location=None):
    """Updates the CSS (Tiangong) passes cache for one location."""
    try:
        logger.info("Updating CSS passes cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        report = get_css_passes_report(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation_m=location.get("elevation", 0),
            timezone_str=location["timezone"],
            days=days,
        )

        if report is None:
            logger.warning("CSS passes report unavailable (provider/network/cache miss); keeping previous cache state")
            return

        cache_store.update_location_cache("css_passes", location["id"], report)

        logger.info(f"CSS passes cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.warning(f"Failed to update CSS passes cache: {e}")


def update_planetary_events_cache(config=None, location=None):
    """
    Updates the Planetary Events cache
    Calculates planetary conjunctions, oppositions, elongations, and retrograde motion
    """
    try:
        logger.debug("Updating Planetary Events cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        from observation.planetary_events import PlanetaryEventsService

        events_service = PlanetaryEventsService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
        )

        events = events_service.get_planetary_events(days_ahead=365)

        response = {
            "location": location,
            "events": events,
            "count": len(events),
            "units": {"times": "ISO 8601 with user timezone offset", "angles": "degrees", "elevation": "meters"},
        }

        cache_store.update_location_cache("planetary_events", location["id"], response)

        logger.info(f"Planetary events cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Planetary events cache: {e}", exc_info=True)


def update_special_phenomena_cache(config=None, location=None):
    """
    Updates the Special Phenomena cache
    Calculates equinoxes, solstices, zodiacal light windows, and Milky Way visibility
    """
    try:
        logger.debug("Updating Special Phenomena cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        from observation.special_phenomena import SpecialPhenomenaService

        phenomena_service = SpecialPhenomenaService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
            language=config.get("language", "en"),
        )

        events = phenomena_service.get_special_phenomena(days_ahead=365)

        response = {
            "location": location,
            "events": events,
            "count": len(events),
            "units": {"times": "ISO 8601 with user timezone offset", "angles": "degrees", "elevation": "meters"},
        }

        cache_store.update_location_cache("special_phenomena", location["id"], response)

        logger.info(f"Special phenomena cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Special phenomena cache: {e}", exc_info=True)


def update_solar_system_events_cache(config=None, location=None):
    """
    Updates the Solar System Events cache
    Calculates meteor shower peaks, comet appearances, and asteroid occultations
    """
    try:
        logger.debug("Updating Solar System Events cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        from observation.solar_system_events import SolarSystemEventsService

        solsys_service = SolarSystemEventsService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
        )

        events = solsys_service.get_solar_system_events(days_ahead=365)

        response = {
            "location": location,
            "events": events,
            "count": len(events),
            "units": {"times": "ISO 8601 with user timezone offset", "angles": "degrees", "elevation": "meters"},
        }

        cache_store.update_location_cache("solar_system_events", location["id"], response)

        logger.info(f"Solar system events cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Solar system events cache: {e}", exc_info=True)


def update_sidereal_time_cache(config=None, location=None):
    """
    Updates the Sidereal Time cache
    Provides sidereal time information for current observation planning
    """
    try:
        logger.debug("Updating Sidereal Time cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        from observation.sidereal_time import SiderealTimeService

        sidereal_service = SiderealTimeService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
        )

        # Get current sidereal time
        current_info = sidereal_service.get_current_sidereal_info()

        # Get hourly sidereal times for current day
        today = datetime.today().date()
        hourly_info = sidereal_service.get_hourly_sidereal_times(today)

        response = {
            "location": location,
            "current": current_info,
            "hourly_forecast": hourly_info,
            "units": {
                "sidereal_time": "hours (0-24, where 24h = 1 sidereal day = 23h56m4s solar time)",
                "coordinates": "degrees",
                "elevation": "meters",
            },
        }

        cache_store.update_location_cache("sidereal_time", location["id"], response)

        logger.info(f"Sidereal time cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Sidereal time cache: {e}", exc_info=True)


def update_seeing_forecast_cache(config=None, location=None):
    """
    Updates the Seeing Forecast cache
    Provides atmospheric seeing conditions for planetary imaging
    Fetches data from 7Timer API
    """
    try:
        logger.debug("Updating Seeing Forecast cache...")
        if config is None:
            config = load_config()
        location = _resolve_job_location(config, location)

        logger.debug(_masked_location_log(location))

        from astroweather.seeing_forecast_7timer import get_seeing_forecast

        seeing_data = get_seeing_forecast(
            latitude=location["latitude"], longitude=location["longitude"], timezone_str=location.get("timezone", "UTC")
        )

        if seeing_data is None:
            response = {
                "location": location,
                "seeing_forecast": None,
                "message": "Failed to fetch seeing forecast from 7Timer",
                "message_key": "seeing_forecast.unavailable_fetch_failed",
            }
        else:
            response = {
                "location": location,
                "seeing_forecast": seeing_data,
                "units": {
                    "seeing": "scale 1-5 (1=Excellent, 2=Good, 3=Moderate, 4=Poor, 5=Very Poor)",
                    "times": "ISO 8601 UTC",
                    "duration": "hours",
                },
            }

        cache_store.update_location_cache("seeing_forecast", location["id"], response)

        logger.info(f"Seeing forecast cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Seeing forecast cache: {e}", exc_info=True)


def update_spaceflight_launches_cache():
    """Fetch upcoming and recent launches from Launch Library 2 and cache results."""
    try:
        logger.debug("Updating Spaceflight launches cache...")
        from space.spaceflight_tracker import get_upcoming_launches, get_past_launches

        upcoming = get_upcoming_launches(limit=12)
        past = get_past_launches(limit=10)

        if upcoming is None and past is None:
            logger.warning("Spaceflight launches fetch returned no data (kept existing cache)")
            return

        response = {
            "upcoming": upcoming or {"count": 0, "results": []},
            "past": past or {"count": 0, "results": []},
        }

        cache_store._spaceflight_launches_cache["data"] = response
        cache_store._spaceflight_launches_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "spaceflight_launches",
            cache_store._spaceflight_launches_cache["data"],
            cache_store._spaceflight_launches_cache["timestamp"],
        )
        logger.info(f"Spaceflight launches cache updated at {datetime.now().isoformat()}")
    except Exception as e:
        logger.error(f"Failed to update Spaceflight launches cache: {e}", exc_info=True)


def update_spaceflight_astronauts_cache():
    """Fetch current ISS crew and all astronauts in space from Launch Library 2."""
    try:
        logger.debug("Updating Spaceflight astronauts cache...")
        from space.spaceflight_tracker import get_iss_crew, get_astronauts_in_space

        iss_crew = get_iss_crew()
        astronauts = get_astronauts_in_space()

        if iss_crew is None and astronauts is None:
            logger.warning("Spaceflight astronauts fetch returned no data (kept existing cache)")
            return

        # Build name → station map from active expeditions and annotate each astronaut
        station_by_name = {}
        for exp in (iss_crew or {}).get("expeditions", []):
            for member in exp.get("crew", []):
                if member.get("name"):
                    station_by_name[member["name"]] = {
                        "station_name": exp.get("station_name"),
                        "station_abbrev": exp.get("station_abbrev"),
                    }
        if astronauts:
            for ast in astronauts.get("results", []):
                station = station_by_name.get(ast.get("name") or "")
                ast["station_name"] = station["station_name"] if station else None
                ast["station_abbrev"] = station["station_abbrev"] if station else None

        response = {
            "iss_crew": iss_crew or {},
            "astronauts_in_space": astronauts or {"count": 0, "results": []},
        }

        cache_store._spaceflight_astronauts_cache["data"] = response
        cache_store._spaceflight_astronauts_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "spaceflight_astronauts",
            cache_store._spaceflight_astronauts_cache["data"],
            cache_store._spaceflight_astronauts_cache["timestamp"],
        )
        logger.info(f"Spaceflight astronauts cache updated at {datetime.now().isoformat()}")
    except Exception as e:
        logger.error(f"Failed to update Spaceflight astronauts cache: {e}", exc_info=True)


def update_spaceflight_events_cache():
    """Fetch upcoming space events (dockings, EVAs, milestones) from Launch Library 2."""
    try:
        logger.debug("Updating Spaceflight events cache...")
        from space.spaceflight_tracker import get_upcoming_space_events

        events = get_upcoming_space_events(limit=15)

        if events is None:
            logger.warning("Spaceflight events fetch returned no data (kept existing cache)")
            return

        response = events

        cache_store._spaceflight_events_cache["data"] = response
        cache_store._spaceflight_events_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "spaceflight_events",
            cache_store._spaceflight_events_cache["data"],
            cache_store._spaceflight_events_cache["timestamp"],
        )
        logger.info(f"Spaceflight events cache updated at {datetime.now().isoformat()}")

        # Prune stale images from the three spaceflight caches
        try:
            from space.spaceflight_tracker import prune_image_cache
            import itertools

            def _collect_images(obj):
                """Recursively yield all string values that look like cached image paths."""
                if isinstance(obj, dict):
                    for v in obj.values():
                        yield from _collect_images(v)
                elif isinstance(obj, list):
                    for v in obj:
                        yield from _collect_images(v)
                elif isinstance(obj, str) and obj.startswith("/api/spaceflight/img/"):
                    yield obj

            shared_launches = cache_store.load_shared_cache_entry("spaceflight_launches") or {}
            shared_astronauts = cache_store.load_shared_cache_entry("spaceflight_astronauts") or {}
            shared_events = cache_store.load_shared_cache_entry("spaceflight_events") or {}

            active = list(
                itertools.chain(
                    _collect_images(shared_launches.get("data") or {}),
                    _collect_images(shared_astronauts.get("data") or {}),
                    _collect_images(shared_events.get("data") or {}),
                )
            )
            prune_image_cache(active)
        except Exception as _prune_exc:
            logger.warning("Spaceflight image prune failed: %s", _prune_exc)
    except Exception as e:
        logger.error(f"Failed to update Spaceflight events cache: {e}", exc_info=True)


def update_iers_cache():
    """Download fresh IERS-A Earth-orientation data to data/cache/iers/finals2000A.all.

    Downloads directly to a visible path (consistent with other app caches like skyfield)
    rather than astropy's internal hash-addressed download cache.
    Called by the scheduler every CACHE_TTL_IERS seconds (21 days).
    """
    import os
    import requests
    from astropy.utils import iers as _iers
    from astropy.utils.iers import IERS_Auto
    from astropy.time import Time
    from utils.constants import IERS_CACHE_FILE

    try:
        urls = [str(_iers.conf.iers_auto_url)]
        mirror_url = getattr(_iers.conf, 'iers_auto_url_mirror', None)
        if mirror_url:
            urls.append(str(mirror_url))

        os.makedirs(os.path.dirname(IERS_CACHE_FILE), exist_ok=True)

        last_error = None
        for url in urls:
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                with open(IERS_CACHE_FILE, 'wb') as f:
                    f.write(response.content)
                break
            except Exception as dl_err:
                last_error = dl_err
                logger.warning("IERS download failed from %s: %s", url, dl_err)
        else:
            raise RuntimeError(f"All IERS download URLs failed: {last_error}")

        from astropy.utils.iers import IERS_A, earth_orientation_table

        table = IERS_A.open(IERS_CACHE_FILE)
        IERS_Auto.iers_table = table  # type: ignore[assignment]  # atomic swap — never passes through None
        # IERS_Auto.open() with auto_download=False always overwrites iers_table with the
        # bundled (old) table, bypassing our downloaded one. Setting earth_orientation_table
        # directly ensures coordinate transforms (get_polar_motion) use the fresh data.
        earth_orientation_table.set(table)

        mjd_max = table['MJD'].max()  # type: ignore[union-attr]
        if hasattr(mjd_max, 'value'):  # pragma: no branch
            mjd_max = float(mjd_max.value)
        valid_until = Time(float(mjd_max), format='mjd').iso[:10]

        cache_store._iers_cache["data"] = {"valid_until": valid_until}
        cache_store._iers_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "iers", cache_store._iers_cache["data"], cache_store._iers_cache["timestamp"]
        )
        logger.info("IERS-A data downloaded to %s. Valid until %s.", IERS_CACHE_FILE, valid_until)
    except Exception as e:
        logger.error("Failed to refresh IERS-A data: %s. Will retry next scheduler cycle.", e)


def update_allsky_sensor_cache(config=None):
    """Fetches live sensor data from the AllSky Export JSON and stores it in cache."""
    if config is None:
        config = load_config()

    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return
    if not allsky_cfg.get("modules", {}).get("sensor_data", {}).get("enabled"):
        return

    from connectors.allsky_connector import AllSkyConnector

    connector = AllSkyConnector(allsky_cfg)
    data = connector.fetch_sensor_data()
    now_ts = time.time()
    cache_store._allsky_sensor_cache["data"] = data
    cache_store._allsky_sensor_cache["timestamp"] = now_ts
    logger.debug("AllSky sensor cache updated")


def update_allsky_health_cache(config=None):
    """Runs per-module reachability checks against the AllSky instance and stores results in cache."""
    if config is None:
        config = load_config()

    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return

    from connectors.allsky_connector import AllSkyConnector

    result = AllSkyConnector(allsky_cfg).health_check()
    cache_store._allsky_health_cache["data"] = result
    cache_store._allsky_health_cache["timestamp"] = time.time()
    logger.debug("AllSky health cache updated")


# (job_name, shared_cache_name, update_fn_name, ttl_seconds, day_sensitive)
# Location-scoped jobs: run once per scheduler location; the shared_cache_name is
# combined with the location id for TTL checks (cache_store.location_cache_key).
# Function NAMES (resolved via globals() at run time) keep the jobs patchable in tests.
_LOCATION_JOBS = (
    ("moon_report", "moon_report", "update_moon_caches", CACHE_TTL_MOON_REPORT, True),
    ("moon_planner", "moon_planner", "update_moon_planner_cache", CACHE_TTL_MOON_PLANNER, True),
    ("sun_report", "sun_report", "update_sun_report_cache", CACHE_TTL_SUN_REPORT, True),
    ("solar_eclipse", "solar_eclipse", "update_solar_eclipse_cache", CACHE_TTL_SOLAR_ECLIPSE, False),
    ("lunar_eclipse", "lunar_eclipse", "update_lunar_eclipse_cache", CACHE_TTL_LUNAR_ECLIPSE, False),
    ("horizon_graph", "horizon_graph", "update_horizon_graph_cache", CACHE_TTL_HORIZON_GRAPH, True),
    ("aurora", "aurora", "update_aurora_cache", CACHE_TTL_AURORA, False),
    ("iss_passes", "iss_passes", "update_iss_passes_cache", CACHE_TTL_ISS_PASSES, False),
    ("css_passes", "css_passes", "update_css_passes_cache", CACHE_TTL_CSS_PASSES, False),
    ("planetary_events", "planetary_events", "update_planetary_events_cache", CACHE_TTL_PLANETARY_EVENTS, False),
    ("special_phenomena", "special_phenomena", "update_special_phenomena_cache", CACHE_TTL_SPECIAL_PHENOMENA, False),
    (
        "solar_system_events",
        "solar_system_events",
        "update_solar_system_events_cache",
        CACHE_TTL_SOLAR_SYSTEM_EVENTS,
        False,
    ),
    ("sidereal_time", "sidereal_time", "update_sidereal_time_cache", CACHE_TTL_SIDEREAL_TIME, True),
    ("seeing_forecast", "seeing_forecast", "update_seeing_forecast_cache", CACHE_TTL_SEEING_FORECAST, False),
    ("best_window", "best_window_strict", "update_best_window_cache", CACHE_TTL_BEST_WINDOW, True),
    ("weather_forecast", "weather_forecast", "update_weather_cache", WEATHER_CACHE_TTL, False),
)

# Network-bound jobs that can run concurrently (pure API calls, no shared state).
# The clients (requests lib) are thread-safe; no Astropy state is mutated here.
# Job×location pairs all feed the same fixed-size pool so total in-flight
# requests never exceed the pre-v1.2 ceiling regardless of location count.
_PARALLELIZABLE_JOBS = {
    "aurora",
    "iss_passes",
    "css_passes",
    "seeing_forecast",
    "spaceflight_launches",
    "spaceflight_astronauts",
    "spaceflight_events",
    "iers",
}


def fully_initialize_caches():
    """
    Selectively refreshes cache entries whose individual TTL has expired.
    Each job has its own TTL (see constants.py) - heavy/slow jobs run far less
    frequently than time-sensitive ones, reducing CPU/memory pressure on startup
    and during periodic scheduler cycles.

    Multi-location (v1.2): every location-scoped job is expanded into one work
    unit per scheduler location (install default + presets attributed to at
    least one user), each gated by its own (job, location) TTL. Global jobs
    (spaceflight, IERS, AllSky) run exactly once, unchanged.

    Optimisations applied per refresh cycle:
    - Config file is read ONCE and forwarded to every update function.
    - moon_report + dark_window share a single MoonService.get_report() call
      (update_moon_caches) and are therefore a single job entry here.
    - best_window runs all 3 modes in one Astropy night-scan pass.

    Automatically resets a location's caches when its parameters change.
    Called on startup and by the cache scheduler every ~5 minutes.
    """
    from functools import partial

    logger.debug("Starting cache refresh cycle...")
    start_time = datetime.now()

    try:
        # Reset changed locations' caches; skip-logic below still applies
        # because reset zeroes those slots' timestamps so their jobs go stale
        check_and_handle_config_changes()

        # Load config ONCE per refresh cycle - shared across all update functions
        config = load_config()

        scheduler_locations = get_scheduler_locations(config)
        install_default_id = get_install_default_location(config).get("id")
        multi_location = len(scheduler_locations) > 1

        def _job_label(job_name, location):
            """Metrics/progress key: plain name for the install default, suffixed otherwise."""
            if not multi_location or location.get("id") == install_default_id:
                return job_name
            return f"{job_name}@{slugify_location_name(str(location.get('name') or location.get('id')))}"

        # --- Build the work list: (label, base_job_name, update_fn, ttl) ---
        jobs_to_run = []

        for job_name, shared_name, update_fn_name, ttl, day_sensitive in _LOCATION_JOBS:
            update_fn = globals()[update_fn_name]  # late-bound: patchable in tests
            for location in scheduler_locations:
                location_id = location.get("id")
                if not location_id:
                    continue
                entry = cache_store.load_location_cache(shared_name, location_id)
                valid = (
                    cache_store.is_cache_valid_for_today(entry, ttl)
                    if day_sensitive
                    else cache_store.is_cache_valid(entry, ttl)
                )
                if valid:
                    logger.debug(
                        "Cache '%s' still valid for location %s (TTL=%ds), skipping", job_name, location_id, ttl
                    )
                else:
                    jobs_to_run.append(
                        (
                            _job_label(job_name, location),
                            job_name,
                            partial(update_fn, config=config, location=location),
                            ttl,
                            location_id,
                        )
                    )

        # --- Global jobs (spaceflight, IERS, AllSky) ---
        global_jobs: List[Tuple[str, Optional[str], Callable[..., None], int, dict]] = [
            (
                "spaceflight_launches",
                "spaceflight_launches",
                update_spaceflight_launches_cache,
                CACHE_TTL_SPACEFLIGHT_LAUNCHES,
                cache_store._spaceflight_launches_cache,
            ),
            (
                "spaceflight_astronauts",
                "spaceflight_astronauts",
                update_spaceflight_astronauts_cache,
                CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
                cache_store._spaceflight_astronauts_cache,
            ),
            (
                "spaceflight_events",
                "spaceflight_events",
                update_spaceflight_events_cache,
                CACHE_TTL_SPACEFLIGHT_EVENTS,
                cache_store._spaceflight_events_cache,
            ),
            ("iers", "iers", update_iers_cache, CACHE_TTL_IERS, cache_store._iers_cache),
        ]

        # Add AllSky jobs only when the connector is enabled
        allsky_cfg = config.get("connectors", {}).get("allsky", {})
        if allsky_cfg.get("enabled") and allsky_cfg.get("url"):
            if allsky_cfg.get("modules", {}).get("sensor_data", {}).get("enabled"):
                global_jobs.append(
                    (
                        "allsky_sensor",
                        None,
                        partial(update_allsky_sensor_cache, config=config),
                        CACHE_TTL_ALLSKY_SENSOR,
                        cache_store._allsky_sensor_cache,
                    )
                )
            global_jobs.append(
                (
                    "allsky_health",
                    None,
                    partial(update_allsky_health_cache, config=config),
                    CACHE_TTL_ALLSKY_HEALTH,
                    cache_store._allsky_health_cache,
                )
            )

        # Spaceflight image-integrity check jobs (cache_entry key -> name for logging)
        _SPACEFLIGHT_IMAGE_JOBS = {
            "spaceflight_launches",
            "spaceflight_astronauts",
        }

        for job_name, shared_key, update_fn, ttl, cache_entry in global_jobs:
            # Sync in-memory entry from shared file to get the persisted timestamp
            if shared_key is not None:
                cache_store.sync_cache_from_shared(shared_key, cache_entry)

            # For spaceflight jobs: invalidate if any referenced image is gone from disk
            if job_name in _SPACEFLIGHT_IMAGE_JOBS and cache_entry.get("data"):
                from space.spaceflight_tracker import spaceflight_cache_images_intact

                if not spaceflight_cache_images_intact(cache_entry["data"]):
                    logger.info(
                        "Spaceflight cache '%s' has missing image files - forcing re-fetch",
                        job_name,
                    )
                    cache_entry["timestamp"] = 0

            if cache_store.is_cache_valid(cache_entry, ttl):
                logger.debug("Cache '%s' still valid (TTL=%ds), skipping", job_name, ttl)
            else:
                jobs_to_run.append((job_name, job_name, update_fn, ttl, None))

        # If a table is already loaded in memory but is beyond (or very close to)
        # its validity horizon, force an immediate IERS refresh before any other
        # astropy jobs run to avoid degraded-accuracy startup warnings.
        iers_stale_or_near_expiry = False
        try:
            from astropy.time import Time as _Time
            from astropy.utils.iers import IERS_Auto as _IERS_Auto

            iers_table = _IERS_Auto.iers_table
            if iers_table is not None:
                mjd_max = iers_table['MJD'].max()  # type: ignore[index, union-attr]
                if hasattr(mjd_max, 'value'):
                    mjd_max = float(mjd_max.value)
                else:
                    mjd_max = float(mjd_max)

                # Keep a small forward cushion so startup does not run right at the
                # edge of table validity and emit warnings under normal workload.
                iers_stale_or_near_expiry = mjd_max <= (float(_Time.now().mjd) + 2.0)  # type: ignore[arg-type]
        except Exception as _iers_state_err:
            logger.warning("Unable to evaluate loaded IERS table validity: %s", _iers_state_err)

        if iers_stale_or_near_expiry and not any(base == 'iers' for _, base, _, _, _ in jobs_to_run):
            logger.info("Loaded IERS table is stale/near expiry; forcing immediate refresh")
            jobs_to_run.append(('iers', 'iers', update_iers_cache, CACHE_TTL_IERS, None))

        if not jobs_to_run:
            logger.debug("All caches are still valid - no refresh needed this cycle")
            return

        sequential = [
            (label, base, fn, ttl, location_id)
            for label, base, fn, ttl, location_id in jobs_to_run
            if base not in _PARALLELIZABLE_JOBS
        ]
        parallel = [
            (label, base, fn, ttl, location_id)
            for label, base, fn, ttl, location_id in jobs_to_run
            if base in _PARALLELIZABLE_JOBS
        ]

        total_steps = len(jobs_to_run)
        n_parallel = len(parallel)  # saved before any pre-phase removal
        success_count = 0

        # If the IERS table is not yet loaded in this process, run the IERS download
        # synchronously *before* launching parallel jobs.  Parallel jobs like ISS passes
        # use astropy AltAz; without a current IERS table they would trigger the
        # "polar motions after IERS data is valid" warning on every first-boot cycle.
        from astropy.utils.iers import IERS_Auto as _iers_auto_check

        if _iers_auto_check.iers_table is None or iers_stale_or_near_expiry:
            iers_parallel = next(
                ((label, base, fn, ttl, loc_id) for label, base, fn, ttl, loc_id in parallel if base == 'iers'), None
            )
            if iers_parallel is not None:
                logger.info(
                    "IERS table absent/stale; downloading synchronously before parallel phase"
                    " to avoid stale-data warnings"
                )
                _iers_start = time.time()
                try:
                    iers_parallel[2]()
                    cache_store.record_cache_execution('iers', time.time() - _iers_start, True)
                    success_count += 1
                except Exception as _iers_pre_err:
                    cache_store.record_cache_execution('iers', time.time() - _iers_start, False)
                    logger.error("Pre-parallel IERS download failed: %s", _iers_pre_err)
                parallel = [
                    (label, base, fn, ttl, loc_id) for label, base, fn, ttl, loc_id in parallel if base != 'iers'
                ]

        # --- Parallel network jobs (job × location units share one fixed-size pool) ---
        if parallel:
            parallel_names = ", ".join(label for label, _, _, _, _ in parallel)
            logger.debug("Launching %d network jobs in parallel: %s", len(parallel), parallel_names)
            cache_store.set_cache_initialization_in_progress(
                True,
                current_step=0,
                total_steps=len(parallel),
                step_name="parallel_network",
            )
            with ThreadPoolExecutor(max_workers=min(len(parallel), 6)) as executor:
                futures = {executor.submit(fn): (label, ttl, loc_id) for label, _base, fn, ttl, loc_id in parallel}
                completed_parallel = 0
                for future in as_completed(futures):
                    job_label, ttl, location_id = futures[future]
                    job_start = time.time()
                    try:
                        future.result()
                        duration = time.time() - job_start
                        cache_store.record_cache_execution(job_label, duration, True, location_id=location_id)
                        success_count += 1
                        logger.debug("Parallel cache '%s' refreshed in %.2fs", job_label, duration)
                    except Exception as e:
                        duration = time.time() - job_start
                        cache_store.record_cache_execution(job_label, duration, False, location_id=location_id)
                        logger.error(
                            "Parallel cache '%s' failed after %.2fs: %s", job_label, duration, e, exc_info=True
                        )
                    finally:
                        completed_parallel += 1
                        cache_store.set_cache_initialization_in_progress(
                            True,
                            current_step=completed_parallel,
                            total_steps=len(parallel),
                            step_name="parallel_network",
                        )

        # --- Sequential compute jobs (Astropy - kept single-threaded for safety) ---
        for index, (job_label, base_name, update_fn, ttl, location_id) in enumerate(
            sequential, start=len(parallel) + 1
        ):
            cache_store.set_cache_initialization_in_progress(
                True,
                current_step=index,
                total_steps=total_steps,
                step_name=job_label,
            )
            job_start = time.time()
            try:
                update_fn()
                duration = time.time() - job_start
                cache_store.record_cache_execution(job_label, duration, True, location_id=location_id)
                # moon_report and dark_window are computed together - mirror metrics
                if base_name == "moon_report":
                    cache_store.record_cache_execution(
                        job_label.replace("moon_report", "dark_window"), duration, True, location_id=location_id
                    )
                success_count += 1
                logger.debug("Cache '%s' refreshed in %.2fs", job_label, duration)
            except Exception as e:
                duration = time.time() - job_start
                cache_store.record_cache_execution(job_label, duration, False, location_id=location_id)
                if base_name == "moon_report":
                    cache_store.record_cache_execution(
                        job_label.replace("moon_report", "dark_window"), duration, False, location_id=location_id
                    )
                logger.error("Failed to update '%s' cache after %.2fs: %s", job_label, duration, e, exc_info=True)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Cache refresh cycle: %d jobs ran (%d parallel, %d sequential) across %d location(s),"
            " %d/%d succeeded in %.2fs",
            total_steps,
            n_parallel,
            len(sequential),
            len(scheduler_locations),
            success_count,
            total_steps,
            duration,
        )

    finally:
        cache_store.set_cache_initialization_in_progress(False)
