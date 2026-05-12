"""
Cache functions for heavy computations.
All cache management is server-side with TTL-based expiration.
Automatically resets astronomical caches when location parameters change.
"""

from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging_config import get_logger

from repo_config import load_config
from moon_astrotonight import AstroTonightService
from moon_phases import MoonService
from moon_planner import MoonPlanner
from sun_phases import SunService
from sun_eclipse import SolarEclipseService
from moon_eclipse import LunarEclipseService
from horizon_graph import HorizonGraphService
from aurora_predictions import get_aurora_report
from iss_passes import get_iss_passes_report
from weather_openmeteo import get_hourly_forecast
import cache_store
from constants import (
    WEATHER_CACHE_TTL,
    CACHE_TTL_MOON_REPORT, CACHE_TTL_DARK_WINDOW, CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_SUN_REPORT, CACHE_TTL_BEST_WINDOW, CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_LUNAR_ECLIPSE, CACHE_TTL_HORIZON_GRAPH, CACHE_TTL_AURORA,
    CACHE_TTL_ISS_PASSES, CACHE_TTL_PLANETARY_EVENTS, CACHE_TTL_SPECIAL_PHENOMENA,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS, CACHE_TTL_SIDEREAL_TIME, CACHE_TTL_SEEING_FORECAST,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS, CACHE_TTL_SPACEFLIGHT_EVENTS,
)

# Initialize logger for this module
logger = get_logger(__name__)


def check_and_handle_config_changes():
    """
    Check if location configuration has changed.
    If it has, reset all astronomical caches.
    This ensures cache is invalidated when the observer location changes.
    """
    config = load_config()
    location_config = config.get("location")
    
    if not location_config:
        return False
    
    # Check if this is the first time (no persisted location)
    is_first_time = cache_store._last_known_location_config["latitude"] is None
    
    if is_first_time:
        # First initialization - just store the config without warning
        logger.info("Initializing location config tracking")
        cache_store.update_location_config(location_config)
        return False
    
    # Check if location actually changed
    if cache_store.has_location_changed(location_config):
        logger.warning(f"Location configuration changed! Resetting all astronomical caches.")
        cache_store.reset_all_caches()
        cache_store.update_location_config(location_config)
        return True
    
    return False

def update_moon_report_cache():
    """
    Updates the Moon report cache.
    Delegates to update_moon_caches() so the MoonService report is computed once.
    """
    update_moon_caches()


def update_dark_window_cache():
    """
    Updates the dark window cache.
    Delegates to update_moon_caches() so the MoonService report is computed once.
    """
    update_moon_caches()


def update_moon_caches(config=None):
    """
    Computes MoonService.get_report() ONCE and writes both the moon_report and
    dark_window caches. Calling the two caches separately would instantiate
    MoonService and run all Astropy calculations twice with identical inputs.
    """
    try:
        logger.info("Updating Moon report + Dark window caches (single pass)...")
        if config is None:
            config = load_config()

        if not config.get("location"):
            raise ValueError("Location configuration is missing")

        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        moon = MoonService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
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

        moon_response = {
            "location": config["location"],
            "moon": report_json
        }
        cache_store._moon_report_cache["data"] = moon_response
        cache_store._moon_report_cache["timestamp"] = now_ts
        cache_store.update_shared_cache_entry(
            "moon_report",
            cache_store._moon_report_cache["data"],
            cache_store._moon_report_cache["timestamp"]
        )

        # --- dark_window (derived from the same report) ---
        dark_response = {
            "next_dark_night": {
                "start": report.next_dark_night_start,
                "end": report.next_dark_night_end
            }
        }
        cache_store._dark_window_report_cache["data"] = dark_response
        cache_store._dark_window_report_cache["timestamp"] = now_ts
        cache_store.update_shared_cache_entry(
            "dark_window",
            cache_store._dark_window_report_cache["data"],
            cache_store._dark_window_report_cache["timestamp"]
        )

        logger.info(f"Moon report + Dark window caches updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Moon/Dark window caches: {e}")


def update_moon_planner_cache(config=None):
    """
    Updates the Moon Planner cache (next 7 nights report)
    """
    try:
        logger.debug("Updating Moon Planner cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        planner = MoonPlanner(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        nights = planner.next_7_nights()

        response = {
            "location": config["location"],
            "next_7_nights": nights,
            "units": {
                "dark_hours": "hours",
                "altitude": "degrees",
                "illumination": "percent"
            }
        }

        # Update global cache
        cache_store._moon_planner_report_cache["data"] = response
        cache_store._moon_planner_report_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "moon_planner",
            cache_store._moon_planner_report_cache["data"],
            cache_store._moon_planner_report_cache["timestamp"]
        )

        logger.info(f"Moon Planner cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Moon Planner cache: {e}")


def update_sun_report_cache(config=None):
    """
    Updates the Sun report cache (today report)
    """
    try:
        logger.debug("Updating Sun report cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        sun = SunService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        report = sun.get_today_report()

        response = {
            "location": config["location"],
            "sun": report.__dict__,
            "units": {
                "times": "local timezone",
                "true_night_hours": "hours"
            }
        }

        # Update global cache
        cache_store._sun_report_cache["data"] = response
        cache_store._sun_report_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "sun_report",
            cache_store._sun_report_cache["data"],
            cache_store._sun_report_cache["timestamp"]
        )

        logger.info(f"Sun report cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Sun report cache: {e}")


def update_best_window_cache(config=None):
    """
    Updates all three best-window caches (strict, practical, illumination) in a single
    night scan — altitudes are computed once per time-step instead of once per mode.
    """
    try:
        logger.debug("Updating Best window cache...")
        if config is None:
            config = load_config()

        if not config.get("location"):
            raise ValueError("Location configuration is missing")

        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        service = AstroTonightService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        # Single-pass: all 3 modes computed with one time-step loop
        windows = service.best_windows_all_modes()

        for mode, window in windows.items():
            cache_store._best_window_cache[mode]["data"] = {
                "location": config["location"],
                "mode": mode,
                "best_window": window.__dict__,
                "units": {
                    "times": "local timezone",
                    "duration": "hours",
                    "score": "0-100"
                }
            }
            cache_store._best_window_cache[mode]["timestamp"] = time.time()
            cache_store.update_shared_cache_entry(
                f"best_window_{mode}",
                cache_store._best_window_cache[mode]["data"],
                cache_store._best_window_cache[mode]["timestamp"]
            )

        logger.info(f"Best window cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update best window cache: {e}")


def update_weather_cache():
    """
    Updates the weather forecast cache
    Pre-fetches weather data from Open-Meteo API and caches it
    """
    try:
        logger.debug("Updating Weather forecast cache...")
        
        forecast = get_hourly_forecast()
        
        if forecast is None:
            logger.error("Failed to fetch weather forecast - API returned None")
            return
        
        # Serialize to JSON-compatible format so the endpoint can serve directly from cache
        df = forecast["hourly"].copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: x.decode() if isinstance(x, bytes) else x)
        location = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in forecast["location"].items()}
        
        cache_store._weather_cache["data"] = {"location": location, "hourly": df.to_dict(orient="records")}
        cache_store._weather_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "weather_forecast",
            cache_store._weather_cache["data"],
            cache_store._weather_cache["timestamp"],
        )
        
        logger.info(f"Weather forecast cache updated at {datetime.now().isoformat()}")
        
    except Exception as e:
        logger.error(f"Failed to update Weather forecast cache: {e}")


def update_solar_eclipse_cache(config=None):
    """
    Updates the Solar Eclipse cache
    """
    try:
        logger.debug("Updating Solar Eclipse cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        eclipse_service = SolarEclipseService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        eclipse = eclipse_service.get_next_eclipse()

        if eclipse is None:
            response = {
                "location": config["location"],
                "solar_eclipse": None,
                "message": "No solar eclipse found in the next 18 months"
            }
        else:
            # Convert dataclass to dict
            eclipse_dict = eclipse.__dict__.copy()
            # Convert altitude_vs_time EclipsePoint objects to dicts
            if "altitude_vs_time" in eclipse_dict:
                eclipse_dict["altitude_vs_time"] = [
                    point.__dict__ for point in eclipse_dict["altitude_vs_time"]
                ]
            
            response = {
                "location": config["location"],
                "solar_eclipse": eclipse_dict,
                "units": {
                    "times": "ISO format local timezone",
                    "altitude": "degrees",
                    "azimuth": "degrees",
                    "duration": "minutes",
                    "astrophotography_score": "0-10"
                }
            }

        # Update global cache
        cache_store._solar_eclipse_cache["data"] = response
        cache_store._solar_eclipse_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "solar_eclipse",
            cache_store._solar_eclipse_cache["data"],
            cache_store._solar_eclipse_cache["timestamp"]
        )

        logger.info(f"Solar eclipse cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Solar Eclipse cache: {e}", exc_info=True)


def update_lunar_eclipse_cache(config=None):
    """
    Updates the Lunar Eclipse cache
    """
    try:
        logger.debug("Updating Lunar Eclipse cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        eclipse_service = LunarEclipseService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        eclipse = eclipse_service.get_next_eclipse()

        if eclipse is None:
            response = {
                "location": config["location"],
                "lunar_eclipse": None,
                "message": "No lunar eclipse found in the next 18 months"
            }
        else:
            # Convert dataclass to dict
            eclipse_dict = eclipse.__dict__.copy()
            # Convert altitude_vs_time EclipsePoint objects to dicts
            if "altitude_vs_time" in eclipse_dict:
                eclipse_dict["altitude_vs_time"] = [
                    point.__dict__ for point in eclipse_dict["altitude_vs_time"]
                ]
            
            response = {
                "location": config["location"],
                "lunar_eclipse": eclipse_dict,
                "units": {
                    "times": "ISO format local timezone",
                    "altitude": "degrees",
                    "azimuth": "degrees",
                    "duration": "minutes",
                    "astrophotography_score": "0-10"
                }
            }

        # Update global cache
        cache_store._lunar_eclipse_cache["data"] = response
        cache_store._lunar_eclipse_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "lunar_eclipse",
            cache_store._lunar_eclipse_cache["data"],
            cache_store._lunar_eclipse_cache["timestamp"]
        )

        logger.info(f"Lunar eclipse cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Lunar Eclipse cache: {e}", exc_info=True)

def update_horizon_graph_cache(config=None):
    """
    Updates the Horizon Graph cache (sun and moon positions throughout the day)
    """
    try:
        logger.info("Updating Horizon Graph cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        horizon_service = HorizonGraphService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"]
        )

        horizon_data = horizon_service.get_horizon_data()

        if horizon_data is None:
            response = {
                "location": config["location"],
                "horizon_data": None,
                "message": "Failed to calculate horizon data"
            }
        else:
            # Convert dataclass to dict
            horizon_dict = horizon_data.__dict__.copy()
            # Convert HorizonPoint objects to dicts
            if "sun_data" in horizon_dict:
                horizon_dict["sun_data"] = [
                    point.__dict__ for point in horizon_dict["sun_data"]
                ]
            if "moon_data" in horizon_dict:
                horizon_dict["moon_data"] = [
                    point.__dict__ for point in horizon_dict["moon_data"]
                ]
            
            response = {
                "location": config["location"],
                "horizon_data": horizon_dict,
                "units": {
                    "altitude": "degrees",
                    "azimuth": "degrees",
                    "time": "HH:MM local timezone"
                }
            }

        # Update global cache
        cache_store._horizon_graph_cache["data"] = response
        cache_store._horizon_graph_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "horizon_graph",
            cache_store._horizon_graph_cache["data"],
            cache_store._horizon_graph_cache["timestamp"]
        )

        logger.info(f"Horizon Graph cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Horizon Graph cache: {e}", exc_info=True)


def update_aurora_cache(config=None):
    """
    Updates the Aurora Borealis predictions cache
    """
    try:
        logger.info("Updating Aurora Borealis predictions cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        # Get aurora report
        report = get_aurora_report(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone_str=location["timezone"]
        )

        if report is None:
            raise ValueError("Failed to generate aurora report")

        # Update global cache
        cache_store._aurora_cache["data"] = report
        cache_store._aurora_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "aurora",
            cache_store._aurora_cache["data"],
            cache_store._aurora_cache["timestamp"]
        )

        logger.info(f"Aurora cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Aurora cache: {e}", exc_info=True)


def update_iss_passes_cache(days: int = 20, config=None):
    """
    Updates the ISS passes cache.
    """
    try:
        logger.info("Updating ISS passes cache...")
        if config is None:
            config = load_config()

        if not config.get("location"):
            raise ValueError("Location configuration is missing")

        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

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

        cache_store._iss_passes_cache["data"] = report
        cache_store._iss_passes_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "iss_passes",
            cache_store._iss_passes_cache["data"],
            cache_store._iss_passes_cache["timestamp"],
        )

        logger.info(f"ISS passes cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.warning(f"Failed to update ISS passes cache: {e}")


def update_planetary_events_cache(config=None):
    """
    Updates the Planetary Events cache
    Calculates planetary conjunctions, oppositions, elongations, and retrograde motion
    """
    try:
        logger.debug("Updating Planetary Events cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        from planetary_events import PlanetaryEventsService
        
        events_service = PlanetaryEventsService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC")
        )

        events = events_service.get_planetary_events(days_ahead=365)

        response = {
            "location": config["location"],
            "events": events,
            "count": len(events),
            "units": {
                "times": "ISO 8601 with user timezone offset",
                "angles": "degrees",
                "elevation": "meters"
            }
        }

        # Update global cache
        cache_store._planetary_events_cache["data"] = response
        cache_store._planetary_events_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "planetary_events",
            cache_store._planetary_events_cache["data"],
            cache_store._planetary_events_cache["timestamp"]
        )

        logger.info(f"Planetary events cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Planetary events cache: {e}", exc_info=True)


def update_special_phenomena_cache(config=None):
    """
    Updates the Special Phenomena cache
    Calculates equinoxes, solstices, zodiacal light windows, and Milky Way visibility
    """
    try:
        logger.debug("Updating Special Phenomena cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        from special_phenomena import SpecialPhenomenaService
        
        phenomena_service = SpecialPhenomenaService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
            language=config.get("language", "en")
        )

        events = phenomena_service.get_special_phenomena(days_ahead=365)

        response = {
            "location": config["location"],
            "events": events,
            "count": len(events),
            "units": {
                "times": "ISO 8601 with user timezone offset",
                "angles": "degrees",
                "elevation": "meters"
            }
        }

        # Update global cache
        cache_store._special_phenomena_cache["data"] = response
        cache_store._special_phenomena_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "special_phenomena",
            cache_store._special_phenomena_cache["data"],
            cache_store._special_phenomena_cache["timestamp"]
        )

        logger.info(f"Special phenomena cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Special phenomena cache: {e}", exc_info=True)


def update_solar_system_events_cache(config=None):
    """
    Updates the Solar System Events cache
    Calculates meteor shower peaks, comet appearances, and asteroid occultations
    """
    try:
        logger.debug("Updating Solar System Events cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        from solar_system_events import SolarSystemEventsService
        
        solsys_service = SolarSystemEventsService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC")
        )

        events = solsys_service.get_solar_system_events(days_ahead=365)

        response = {
            "location": config["location"],
            "events": events,
            "count": len(events),
            "units": {
                "times": "ISO 8601 with user timezone offset",
                "angles": "degrees",
                "elevation": "meters"
            }
        }

        # Update global cache
        cache_store._solar_system_events_cache["data"] = response
        cache_store._solar_system_events_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "solar_system_events",
            cache_store._solar_system_events_cache["data"],
            cache_store._solar_system_events_cache["timestamp"]
        )

        logger.info(f"Solar system events cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Solar system events cache: {e}", exc_info=True)


def update_sidereal_time_cache(config=None):
    """
    Updates the Sidereal Time cache
    Provides sidereal time information for current observation planning
    """
    try:
        logger.debug("Updating Sidereal Time cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        from sidereal_time import SiderealTimeService
        
        sidereal_service = SiderealTimeService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC")
        )

        # Get current sidereal time
        current_info = sidereal_service.get_current_sidereal_info()

        # Get hourly sidereal times for current day
        today = datetime.today().date()
        hourly_info = sidereal_service.get_hourly_sidereal_times(today)

        response = {
            "location": config["location"],
            "current": current_info,
            "hourly_forecast": hourly_info,
            "units": {
                "sidereal_time": "hours (0-24, where 24h = 1 sidereal day = 23h56m4s solar time)",
                "coordinates": "degrees",
                "elevation": "meters"
            }
        }

        # Update global cache
        cache_store._sidereal_time_cache["data"] = response
        cache_store._sidereal_time_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "sidereal_time",
            cache_store._sidereal_time_cache["data"],
            cache_store._sidereal_time_cache["timestamp"]
        )

        logger.info(f"Sidereal time cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Sidereal time cache: {e}", exc_info=True)


def update_seeing_forecast_cache(config=None):
    """
    Updates the Seeing Forecast cache
    Provides atmospheric seeing conditions for planetary imaging
    Fetches data from 7Timer API
    """
    try:
        logger.debug("Updating Seeing Forecast cache...")
        if config is None:
            config = load_config()
        
        if not config.get("location"):
            raise ValueError("Location configuration is missing")
        
        location = config["location"]
        logger.debug(f"Using location: lat={int(location.get('latitude'))}, lon={int(location.get('longitude'))}, tz=***")

        from seeing_forecast_7timer import get_seeing_forecast
        
        seeing_data = get_seeing_forecast(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone_str=location.get("timezone", "UTC")
        )

        if seeing_data is None:
            response = {
                "location": config["location"],
                "seeing_forecast": None,
                "message": "Failed to fetch seeing forecast from 7Timer",
                "message_key": "seeing_forecast.unavailable_fetch_failed"
            }
        else:
            response = {
                "location": config["location"],
                "seeing_forecast": seeing_data,
                "units": {
                    "seeing": "scale 1-5 (1=Excellent, 2=Good, 3=Moderate, 4=Poor, 5=Very Poor)",
                    "times": "ISO 8601 UTC",
                    "duration": "hours"
                }
            }

        # Update global cache
        cache_store._seeing_forecast_cache["data"] = response
        cache_store._seeing_forecast_cache["timestamp"] = time.time()
        cache_store.update_shared_cache_entry(
            "seeing_forecast",
            cache_store._seeing_forecast_cache["data"],
            cache_store._seeing_forecast_cache["timestamp"]
        )

        logger.info(f"Seeing forecast cache updated at {datetime.now().isoformat()}")

    except Exception as e:
        logger.error(f"Failed to update Seeing forecast cache: {e}", exc_info=True)


def update_spaceflight_launches_cache():
    """Fetch upcoming and recent launches from Launch Library 2 and cache results."""
    try:
        logger.debug("Updating Spaceflight launches cache...")
        from spaceflight_tracker import get_upcoming_launches, get_past_launches

        upcoming = get_upcoming_launches(limit=12)
        past = get_past_launches(limit=10)

        if upcoming is None and past is None:
            # API unavailable (rate-limited or down) — keep existing data but
            # refresh the timestamp so the scheduler won't retry every cycle.
            # The backoff in spaceflight_tracker._get() already prevents real
            # HTTP calls until the backoff window expires.
            if cache_store._spaceflight_launches_cache.get("data"):
                cache_store._spaceflight_launches_cache["timestamp"] = time.time()
                cache_store.update_shared_cache_entry(
                    "spaceflight_launches",
                    cache_store._spaceflight_launches_cache["data"],
                    cache_store._spaceflight_launches_cache["timestamp"],
                )
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
        from spaceflight_tracker import get_iss_crew, get_astronauts_in_space

        iss_crew = get_iss_crew()
        astronauts = get_astronauts_in_space()

        if iss_crew is None and astronauts is None:
            if cache_store._spaceflight_astronauts_cache.get("data"):
                cache_store._spaceflight_astronauts_cache["timestamp"] = time.time()
                cache_store.update_shared_cache_entry(
                    "spaceflight_astronauts",
                    cache_store._spaceflight_astronauts_cache["data"],
                    cache_store._spaceflight_astronauts_cache["timestamp"],
                )
            logger.warning("Spaceflight astronauts fetch returned no data (kept existing cache)")
            return

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
        from spaceflight_tracker import get_upcoming_space_events

        events = get_upcoming_space_events(limit=15)

        if events is None:
            if cache_store._spaceflight_events_cache.get("data"):
                cache_store._spaceflight_events_cache["timestamp"] = time.time()
                cache_store.update_shared_cache_entry(
                    "spaceflight_events",
                    cache_store._spaceflight_events_cache["data"],
                    cache_store._spaceflight_events_cache["timestamp"],
                )
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
            from spaceflight_tracker import prune_image_cache
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

            active = list(itertools.chain(
                _collect_images(shared_launches.get("data") or {}),
                _collect_images(shared_astronauts.get("data") or {}),
                _collect_images(shared_events.get("data") or {}),
            ))
            prune_image_cache(active)
        except Exception as _prune_exc:
            logger.warning("Spaceflight image prune failed: %s", _prune_exc)
    except Exception as e:
        logger.error(f"Failed to update Spaceflight events cache: {e}", exc_info=True)


def fully_initialize_caches():
    """
    Selectively refreshes cache entries whose individual TTL has expired.
    Each job has its own TTL (see constants.py) — heavy/slow jobs run far less
    frequently than time-sensitive ones, reducing CPU/memory pressure on startup
    and during periodic scheduler cycles.

    Optimisations applied per refresh cycle:
    - Config file is read ONCE and forwarded to every update function.
    - moon_report + dark_window share a single MoonService.get_report() call
      (update_moon_caches) and are therefore a single job entry here.
    - best_window runs all 3 modes in one Astropy night-scan pass.

    Automatically resets all caches if location configuration has changed.
    Called on startup and by the cache scheduler every ~5 minutes.
    """
    from functools import partial
    logger.debug("Starting cache refresh cycle...")
    start_time = datetime.now()

    try:
        # Reset all caches when location changes; skip-logic below still applies
        # because reset_all_caches() zeros all timestamps so every job will be stale
        check_and_handle_config_changes()

        # Load config ONCE per refresh cycle — shared across all update functions
        config = load_config()

        # (name, shared_sync_key, update_fn, ttl_seconds, cache_entry_ref, day_sensitive)
        # day_sensitive=True: cache is invalidated when the local calendar day changes,
        # regardless of TTL. This prevents serving stale "today's data" after midnight
        # when a long TTL (≥2h) would otherwise keep the cache alive into the next day.
        cache_jobs = [
            ("moon_report",        "moon_report",         partial(update_moon_caches,             config=config), CACHE_TTL_MOON_REPORT,         cache_store._moon_report_cache,             True),
            ("moon_planner",        "moon_planner",        partial(update_moon_planner_cache,       config=config), CACHE_TTL_MOON_PLANNER,        cache_store._moon_planner_report_cache,     True),
            ("sun_report",          "sun_report",          partial(update_sun_report_cache,         config=config), CACHE_TTL_SUN_REPORT,          cache_store._sun_report_cache,              True),
            ("solar_eclipse",       "solar_eclipse",       partial(update_solar_eclipse_cache,      config=config), CACHE_TTL_SOLAR_ECLIPSE,       cache_store._solar_eclipse_cache,           False),
            ("lunar_eclipse",       "lunar_eclipse",       partial(update_lunar_eclipse_cache,      config=config), CACHE_TTL_LUNAR_ECLIPSE,       cache_store._lunar_eclipse_cache,           False),
            ("horizon_graph",       "horizon_graph",       partial(update_horizon_graph_cache,      config=config), CACHE_TTL_HORIZON_GRAPH,       cache_store._horizon_graph_cache,           True),
            ("aurora",              "aurora",              partial(update_aurora_cache,             config=config), CACHE_TTL_AURORA,              cache_store._aurora_cache,                  False),
            ("iss_passes",          "iss_passes",          partial(update_iss_passes_cache,         config=config), CACHE_TTL_ISS_PASSES,          cache_store._iss_passes_cache,              False),
            ("planetary_events",    "planetary_events",    partial(update_planetary_events_cache,   config=config), CACHE_TTL_PLANETARY_EVENTS,    cache_store._planetary_events_cache,        False),
            ("special_phenomena",   "special_phenomena",   partial(update_special_phenomena_cache,  config=config), CACHE_TTL_SPECIAL_PHENOMENA,   cache_store._special_phenomena_cache,       False),
            ("solar_system_events", "solar_system_events", partial(update_solar_system_events_cache,config=config), CACHE_TTL_SOLAR_SYSTEM_EVENTS, cache_store._solar_system_events_cache,     False),
            ("sidereal_time",       "sidereal_time",       partial(update_sidereal_time_cache,      config=config), CACHE_TTL_SIDEREAL_TIME,       cache_store._sidereal_time_cache,           True),
            ("seeing_forecast",       "seeing_forecast",       partial(update_seeing_forecast_cache,     config=config), CACHE_TTL_SEEING_FORECAST,         cache_store._seeing_forecast_cache,        False),
            ("spaceflight_launches",  "spaceflight_launches",  update_spaceflight_launches_cache,                        CACHE_TTL_SPACEFLIGHT_LAUNCHES,    cache_store._spaceflight_launches_cache,   False),
            ("spaceflight_astronauts","spaceflight_astronauts",update_spaceflight_astronauts_cache,                      CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,  cache_store._spaceflight_astronauts_cache, False),
            ("spaceflight_events",    "spaceflight_events",    update_spaceflight_events_cache,                          CACHE_TTL_SPACEFLIGHT_EVENTS,      cache_store._spaceflight_events_cache,     False),
            ("best_window",           "best_window_strict",    partial(update_best_window_cache,         config=config), CACHE_TTL_BEST_WINDOW,             cache_store._best_window_cache["strict"],  True),
            ("weather_forecast",      None,                    update_weather_cache,                                     WEATHER_CACHE_TTL,                 cache_store._weather_cache,                False),
        ]

        # Spaceflight image-integrity check jobs (cache_entry key -> name for logging)
        _SPACEFLIGHT_IMAGE_JOBS = {
            "spaceflight_launches", "spaceflight_astronauts",
        }

        # Determine which jobs actually need to run
        jobs_to_run = []
        for job_name, shared_key, update_fn, ttl, cache_entry, day_sensitive in cache_jobs:
            # Sync in-memory entry from shared file to get the persisted timestamp
            if shared_key is not None:
                cache_store.sync_cache_from_shared(shared_key, cache_entry)

            # For spaceflight jobs: invalidate if any referenced image is gone from disk
            if job_name in _SPACEFLIGHT_IMAGE_JOBS and cache_entry.get("data"):
                from spaceflight_tracker import spaceflight_cache_images_intact
                if not spaceflight_cache_images_intact(cache_entry["data"]):
                    logger.info(
                        "Spaceflight cache '%s' has missing image files — forcing re-fetch",
                        job_name,
                    )
                    cache_entry["timestamp"] = 0

            valid = (
                cache_store.is_cache_valid_for_today(cache_entry, ttl)
                if day_sensitive
                else cache_store.is_cache_valid(cache_entry, ttl)
            )
            if valid:
                logger.debug("Cache '%s' still valid (TTL=%ds), skipping", job_name, ttl)
            else:
                jobs_to_run.append((job_name, update_fn, ttl))

        if not jobs_to_run:
            logger.debug("All caches are still valid — no refresh needed this cycle")
            return

        # Network-bound jobs that can run concurrently (pure API calls, no shared state).
        # The clients (requests lib) are thread-safe; no Astropy state is mutated here.
        PARALLELIZABLE_JOBS = {
            "aurora",
            "iss_passes",
            "seeing_forecast",
            "spaceflight_launches",
            "spaceflight_astronauts",
            "spaceflight_events",
        }

        sequential = [(n, fn, ttl) for n, fn, ttl in jobs_to_run if n not in PARALLELIZABLE_JOBS]
        parallel   = [(n, fn, ttl) for n, fn, ttl in jobs_to_run if n in PARALLELIZABLE_JOBS]

        total_steps = len(jobs_to_run)
        success_count = 0

        # --- Parallel network jobs ---
        if parallel:
            parallel_names = ", ".join(n for n, _, _ in parallel)
            logger.debug("Launching %d network jobs in parallel: %s", len(parallel), parallel_names)
            cache_store.set_cache_initialization_in_progress(
                True,
                current_step=0,
                total_steps=len(parallel),
                step_name="parallel_network",
            )
            with ThreadPoolExecutor(max_workers=min(len(parallel), 6)) as executor:
                futures = {executor.submit(fn): (name, ttl) for name, fn, ttl in parallel}
                completed_parallel = 0
                for future in as_completed(futures):
                    job_name, ttl = futures[future]
                    job_start = time.time()
                    try:
                        future.result()
                        duration = time.time() - job_start
                        cache_store.record_cache_execution(job_name, duration, True)
                        success_count += 1
                        logger.debug("Parallel cache '%s' refreshed in %.2fs", job_name, duration)
                    except Exception as e:
                        duration = time.time() - job_start
                        cache_store.record_cache_execution(job_name, duration, False)
                        logger.error("Parallel cache '%s' failed after %.2fs: %s", job_name, duration, e, exc_info=True)
                    finally:
                        completed_parallel += 1
                        cache_store.set_cache_initialization_in_progress(
                            True,
                            current_step=completed_parallel,
                            total_steps=len(parallel),
                            step_name="parallel_network",
                        )

        # --- Sequential compute jobs (Astropy — kept single-threaded for safety) ---
        for index, (job_name, update_fn, ttl) in enumerate(sequential, start=len(parallel) + 1):
            cache_store.set_cache_initialization_in_progress(
                True,
                current_step=index,
                total_steps=total_steps,
                step_name=job_name,
            )
            job_start = time.time()
            try:
                update_fn()
                duration = time.time() - job_start
                cache_store.record_cache_execution(job_name, duration, True)
                # moon_report and dark_window are computed together — mirror metrics
                if job_name == "moon_report":
                    cache_store.record_cache_execution("dark_window", duration, True)
                success_count += 1
                logger.debug("Cache '%s' refreshed in %.2fs", job_name, duration)
            except Exception as e:
                duration = time.time() - job_start
                cache_store.record_cache_execution(job_name, duration, False)
                if job_name == "moon_report":
                    cache_store.record_cache_execution("dark_window", duration, False)
                logger.error("Failed to update '%s' cache after %.2fs: %s", job_name, duration, e, exc_info=True)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Cache refresh cycle: %d/%d jobs ran (%d parallel, %d sequential), %d/%d succeeded in %.2fs",
            total_steps, len(cache_jobs), len(parallel), len(sequential), success_count, total_steps, duration,
        )

    finally:
        cache_store.set_cache_initialization_in_progress(False)
