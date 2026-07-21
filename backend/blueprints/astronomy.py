"""Sky widget, sun, astronomical events, sidereal/horizon and best-window Blueprint.

Routes: /api/sky-widget, /api/sun/*, /api/moon/next-eclipse, /api/events/*,
/api/astro/*, /api/tonight/best-window
"""

from typing import Any, Dict

from flask import Blueprint, request, jsonify

from cache import cache_store
from utils.auth import login_required
from utils.constants import (
    CACHE_TTL,
    CACHE_TTL_AURORA,
    CACHE_TTL_CSS_PASSES,
    CACHE_TTL_ISS_PASSES,
    CACHE_TTL_LUNAR_ECLIPSE,
    CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_PLANETARY_EVENTS,
    CACHE_TTL_SIDEREAL_TIME,
    CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS,
    CACHE_TTL_SPECIAL_PHENOMENA,
)
from utils.events_aggregator import EventsAggregator
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger
from utils.route_helpers import _active_location_cache, _resolve_active_location

logger = get_logger(__name__)

astronomy_bp = Blueprint('astronomy', __name__)


def _determine_sky_period(sun_data: "dict | None", timezone_str: str) -> tuple:
    """
    Determine current sky period from sun report cache data.
    Returns (period, next_period, seconds_until_next).
    period values: 'day', 'civil_twilight', 'nautical_twilight',
                   'astronomical_twilight', 'astronomical_night'
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo

    if not sun_data or "sun" not in sun_data:
        return "unknown", "unknown", None

    sun = sun_data["sun"]
    try:
        tz = ZoneInfo(timezone_str)
    except Exception:
        tz = _dt.timezone.utc
    now = _dt.datetime.now(tz=tz)

    def parse_dt(s):
        if not s or s == "Not found":
            return None
        try:
            return _dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            return None

    def secs(dt_end):
        return max(0, int((dt_end - now).total_seconds()))

    sunset = parse_dt(sun.get("sunset"))
    sunrise = parse_dt(sun.get("sunrise"))
    civil_dusk = parse_dt(sun.get("civil_dusk"))
    civil_dawn = parse_dt(sun.get("civil_dawn"))
    nautical_dusk = parse_dt(sun.get("nautical_dusk"))
    nautical_dawn = parse_dt(sun.get("nautical_dawn"))
    astro_dusk = parse_dt(sun.get("astronomical_dusk"))
    astro_dawn = parse_dt(sun.get("astronomical_dawn"))

    # Check from darkest to lightest
    if astro_dusk and astro_dawn and astro_dusk <= now <= astro_dawn:
        return "astronomical_night", "astronomical_dawn", secs(astro_dawn)
    if nautical_dusk and astro_dusk and nautical_dusk <= now < astro_dusk:
        return "astronomical_twilight", "astronomical_night", secs(astro_dusk)
    if astro_dawn and nautical_dawn and astro_dawn < now <= nautical_dawn:
        return "astronomical_twilight", "nautical_twilight", secs(nautical_dawn)
    if civil_dusk and nautical_dusk and civil_dusk <= now < nautical_dusk:
        return "nautical_twilight", "astronomical_twilight", secs(nautical_dusk)
    if nautical_dawn and civil_dawn and nautical_dawn < now <= civil_dawn:
        return "nautical_twilight", "civil_twilight", secs(civil_dawn)
    if sunset and civil_dusk and sunset <= now < civil_dusk:
        return "civil_twilight", "nautical_twilight", secs(civil_dusk)
    if civil_dawn and sunrise and civil_dawn < now <= sunrise:
        return "civil_twilight", "day", secs(sunrise)
    # Day: next is civil_dusk (via sunset)
    if sunset and now < sunset:
        return "day", "civil_twilight", secs(sunset)
    if civil_dusk and now < civil_dusk:
        return "day", "civil_twilight", secs(civil_dusk)
    return "day", "civil_twilight", None


@astronomy_bp.route("/api/sky-widget", methods=["GET"])
@login_required
def get_sky_widget_api():
    """Return current sky status for the persistent sky widget (period, score, location)"""
    try:
        location, sun_entry = _active_location_cache("sun_report")
        location_name = location.get("name", "")
        timezone_str = location.get("timezone", "UTC")

        # Get sun report from cache (accept stale)
        sun_data = sun_entry.get("data")

        observation_score = None
        try:
            from weather.weather_astro import get_current_astro_conditions

            conditions = get_current_astro_conditions(location=location)
            if conditions:
                observation_score = conditions.get("observation_score")
        except Exception:
            pass  # score stays None if weather data unavailable

        period, next_period, seconds_until_next = _determine_sky_period(sun_data, timezone_str)

        return jsonify(
            {
                "location": location_name,
                "location_id": location.get("id"),
                "period": period,
                "next_period": next_period,
                "time_until_next_seconds": seconds_until_next,
                "observation_score": observation_score,
                "timezone": timezone_str,
            }
        )

    except Exception as e:
        logger.error(f"Error getting sky widget data: {e}")
        return jsonify({"error": "Internal server error"}), 500


@astronomy_bp.route("/api/sun/today", methods=["GET"])
@login_required
def get_sun_today_api():
    """Return Sun today report, from cache only"""
    try:
        _, entry = _active_location_cache("sun_report")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify({"status": "pending", "message": "Sun report cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Sun report cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/sun/next-eclipse", methods=["GET"])
@login_required
def get_solar_eclipse_api():
    """Return next solar eclipse, from cache only"""
    try:
        _, entry = _active_location_cache("solar_eclipse")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify(
                {"status": "pending", "message": "Solar eclipse cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Solar Eclipse cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/moon/next-eclipse", methods=["GET"])
@login_required
def get_lunar_eclipse_api():
    """Return next lunar eclipse, from cache only"""
    try:
        _, entry = _active_location_cache("lunar_eclipse")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify(
                {"status": "pending", "message": "Lunar eclipse cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Lunar Eclipse cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/events/upcoming", methods=["GET"])
@login_required
def get_upcoming_events_api():
    """Return aggregated upcoming astronomical events (eclipses, auroras, planetary, phenomena, solar system events)"""
    try:
        location = _resolve_active_location()
        location_id = location.get("id")
        latitude = location.get("latitude", 0)
        longitude = location.get("longitude", 0)
        user_timezone = location.get("timezone", "UTC")

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        def _valid_location_data(name, ttl):
            entry = cache_store.load_location_cache(name, location_id)
            return entry.get("data") if cache_store.is_cache_valid(entry, ttl) else None

        # Get cached event data (per active location)
        solar_eclipse_data = _valid_location_data("solar_eclipse", CACHE_TTL_SOLAR_ECLIPSE)
        lunar_eclipse_data = _valid_location_data("lunar_eclipse", CACHE_TTL_LUNAR_ECLIPSE)
        aurora_data = _valid_location_data("aurora", CACHE_TTL_AURORA)
        iss_passes_data = _valid_location_data("iss_passes", CACHE_TTL_ISS_PASSES)
        css_passes_data = _valid_location_data("css_passes", CACHE_TTL_CSS_PASSES)
        moon_phases_data = _valid_location_data("moon_planner", CACHE_TTL_MOON_PLANNER)
        planetary_events_data = _valid_location_data("planetary_events", CACHE_TTL_PLANETARY_EVENTS)
        special_phenomena_data = _valid_location_data("special_phenomena", CACHE_TTL_SPECIAL_PHENOMENA)
        solar_system_events_data = _valid_location_data("solar_system_events", CACHE_TTL_SOLAR_SYSTEM_EVENTS)

        if special_phenomena_data:
            special_phenomena_data = _translate_special_phenomena_events(special_phenomena_data, language)

        # Translate solar system events if needed
        if solar_system_events_data and language != "en":
            solar_system_events_data = _translate_solar_system_events(solar_system_events_data, language)

        # Aggregate events
        aggregator = EventsAggregator(latitude, longitude, user_timezone, language=language)
        events = aggregator.aggregate_all_events(
            solar_eclipse_data=solar_eclipse_data,
            lunar_eclipse_data=lunar_eclipse_data,
            aurora_data=aurora_data,
            iss_passes_data=iss_passes_data,
            css_passes_data=css_passes_data,
            moon_phases_data=moon_phases_data,
            planetary_events_data=planetary_events_data,
            special_phenomena_data=special_phenomena_data,
            solar_system_events_data=solar_system_events_data,
        )

        return jsonify(events)

    except Exception as e:
        logger.error(f"Error aggregating upcoming events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/events/planetary", methods=["GET"])
@login_required
def get_planetary_events_api():
    """Return planetary events (conjunctions, oppositions, elongations, retrograde motion)"""
    try:
        _, entry = _active_location_cache("planetary_events")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Planetary events cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving planetary events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/events/phenomena", methods=["GET"])
@login_required
def get_special_phenomena_api():
    """Return special phenomena (equinoxes, solstices, zodiacal light, Milky Way visibility)"""
    try:
        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        _, entry = _active_location_cache("special_phenomena")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(_translate_special_phenomena_events(entry["data"], language))

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(_translate_special_phenomena_events(stale_data, language))

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Special phenomena cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving special phenomena: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/events/solarsystem", methods=["GET"])
@login_required
def get_solar_system_events_api():
    """Return solar system events (meteor showers, comets, asteroid occultations) with language support"""
    try:
        # Get language parameter from request
        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        _, entry = _active_location_cache("solar_system_events")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(_translate_solar_system_events(entry["data"], language))

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(_translate_solar_system_events(stale_data, language))

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Solar system events cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving solar system events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _translate_solar_system_events(data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """
    Translate solar system event descriptions based on language

    Args:
        data: Solar system events cache data
        language: Target language code

    Returns:
        Data with translated event descriptions
    """
    if language == "en":
        # English is default, no translation needed
        return data

    # Create a copy to avoid modifying cache
    translated_data = data.copy() if isinstance(data, dict) else {"events": []}
    events = translated_data.get("events", [])

    if not isinstance(events, list):
        return translated_data

    # Translate each event's title and description
    i18n = I18nManager(language)
    translated_events = []

    for event in events:
        if not isinstance(event, dict):
            translated_events.append(event)
            continue

        translated_event = event.copy()
        event_type = event.get("event_type", "")

        try:
            # Translate based on event type
            if event_type == "Meteor Shower":
                raw_data = event.get("raw_data", {})
                shower_name = raw_data.get("shower", "")
                zenith_hourly_rate = event.get("zenith_hourly_rate", "")
                parent_body = event.get("parent_body", "")

                if shower_name and zenith_hourly_rate and parent_body:
                    title = i18n.t('events_api.solar_system.meteor_shower_title', shower_name=shower_name)
                    description = i18n.t(
                        'events_api.solar_system.meteor_shower_description',
                        zenith_hourly_rate=zenith_hourly_rate,
                        parent_body=parent_body,
                    )
                    translated_event["title"] = title
                    translated_event["description"] = description

            elif event_type == "Comet Appearance":
                magnitude = event.get("magnitude", "")
                visibility = event.get("equipment_needed", "")
                raw_data = event.get("raw_data", {})
                comet_name = raw_data.get("comet", "")

                if comet_name and magnitude and visibility:
                    title = i18n.t('events_api.solar_system.comet_title', comet_name=comet_name)
                    description = i18n.t(
                        'events_api.solar_system.comet_description', magnitude=magnitude, visibility=visibility
                    )
                    translated_event["title"] = title
                    translated_event["description"] = description

            elif event_type == "Asteroid Occultation":
                title = i18n.t('events_api.solar_system.asteroid_occultation_title')
                description = i18n.t('events_api.solar_system.asteroid_occultation_description')
                translated_event["title"] = title
                translated_event["description"] = description

        except Exception as e:
            logger.debug(f"Error translating solar system event: {e}")

        translated_events.append(translated_event)

    translated_data["events"] = translated_events
    return translated_data


def _translate_special_phenomena_events(data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Translate special phenomena events that are cached with localized strings."""
    translated_data = data.copy() if isinstance(data, dict) else {"events": []}
    events = translated_data.get("events", [])

    if not isinstance(events, list):
        return translated_data

    i18n = I18nManager(language)
    translated_events = []

    def _t(key: str, fallback: str, **kwargs: Any) -> str:
        translated = i18n.t(key, **kwargs)
        if translated and translated != key:
            return translated
        if kwargs:
            try:
                return fallback.format(**kwargs)
            except Exception:
                return fallback
        return fallback

    for event in events:
        if not isinstance(event, dict):
            translated_events.append(event)
            continue

        translated_event = event.copy()

        try:
            event_type = str(event.get("event_type", ""))
            raw_data = event.get("raw_data", {}) if isinstance(event.get("raw_data"), dict) else {}
            event_key = str(raw_data.get("event", "")).strip().lower()

            if event_key == "spring_equinox":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.spring_equinox_title',
                    str(event.get("title", "Vernal Equinox (Spring)")),
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.spring_equinox_description',
                    str(
                        event.get(
                            "description",
                            "First day of spring. Equal day and night length. Sun directly above equator.",
                        )
                    ),
                )
            elif event_key == "summer_solstice":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.summer_solstice_title', str(event.get("title", "Summer Solstice"))
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.summer_solstice_description',
                    str(
                        event.get("description", "First day of summer. Longest day of the year in Northern Hemisphere.")
                    ),
                )
            elif event_key == "autumn_equinox":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.autumn_equinox_title',
                    str(event.get("title", "Autumnal Equinox (Fall)")),
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.autumn_equinox_description',
                    str(
                        event.get(
                            "description",
                            "First day of autumn. Equal day and night length. Sun directly above equator.",
                        )
                    ),
                )
            elif event_key == "winter_solstice":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.winter_solstice_title', str(event.get("title", "Winter Solstice"))
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.winter_solstice_description',
                    str(
                        event.get(
                            "description", "First day of winter. Shortest day of the year in Northern Hemisphere."
                        )
                    ),
                )
            elif event_key == "zodiacal_light":
                viewing_raw = str(event.get("viewing_type", "")).strip().lower()
                if viewing_raw == "morning":
                    viewing_label = _t('events_api.special_phenomena.zodiacal_viewing_morning', 'Morning')
                else:
                    viewing_label = _t('events_api.special_phenomena.zodiacal_viewing_evening', 'Evening')

                translated_event["title"] = _t(
                    'events_api.special_phenomena.zodiacal_light_title',
                    str(event.get("title", "Zodiacal Light Visible ({viewing_type})")),
                    viewing_type=viewing_label,
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.zodiacal_light_description',
                    str(
                        event.get(
                            "description",
                            "Faint cone of light from interplanetary dust visible during twilight."
                            " Best viewed in dark skies.",
                        )
                    ),
                )
                translated_event["viewing_type"] = viewing_label
            elif event_type == "Milky Way Core Visibility":
                gc_altitude = event.get("galactic_center_altitude")

                if gc_altitude is None:
                    gc_altitude = raw_data.get("galactic_center_altitude")
                if gc_altitude is None:
                    gc_altitude = raw_data.get("gc_altitude")

                if gc_altitude is not None:
                    altitude_text = f"{float(gc_altitude):.0f}"
                    translated_event["title"] = _t(
                        'events_api.special_phenomena.milky_way_title',
                        str(event.get("title", "Milky Way Core Visible")),
                    )
                    translated_event["description"] = _t(
                        'events_api.special_phenomena.milky_way_description',
                        str(
                            event.get(
                                "description",
                                "Galactic center visible at {gc_altitude}° altitude."
                                " Excellent night for wide-field astrophotography.",
                            )
                        ),
                        gc_altitude=altitude_text,
                    )
        except Exception as e:  # pragma: no cover
            logger.debug(f"Error translating special phenomenon event: {e}")

        translated_events.append(translated_event)

    translated_data["events"] = translated_events
    return translated_data


@astronomy_bp.route("/api/astro/sidereal-time", methods=["GET"])
@login_required
def get_sidereal_time_api():
    """Return sidereal time information for observation planning.

    `current` is always computed live (a few ms) so it is never stale.
    `hourly_forecast` is served from the scheduler cache (day-sensitive TTL).
    """
    try:
        location, cached = _active_location_cache("sidereal_time")
        if not location or location.get("latitude") is None:
            return jsonify({'error': 'Location not configured'}), 400

        from observation.sidereal_time import SiderealTimeService

        svc = SiderealTimeService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
        )

        # current - always fresh, no cache needed
        current_info = svc.get_current_sidereal_info()

        # hourly_forecast - from scheduler cache (day-sensitive, refreshed at day change
        # evaluated in the observer's timezone, not the server's)
        hourly_forecast = None
        if cache_store.is_cache_valid_for_today(
            cached, CACHE_TTL_SIDEREAL_TIME, tz_name=location.get("timezone")
        ) and cached.get("data"):
            hourly_forecast = cached["data"].get("hourly_forecast")

        return jsonify(
            {
                "location": location,
                "current": current_info,
                "hourly_forecast": hourly_forecast,
                "units": {
                    "sidereal_time": "hours (0-24, where 24h = 1 sidereal day = 23h56m4s solar time)",
                    "coordinates": "degrees",
                    "elevation": "meters",
                },
            }
        )

    except Exception as e:
        logger.error(f"Error retrieving sidereal time: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/astro/horizon-graph", methods=["GET"])
@login_required
def get_horizon_graph_api():
    """Return sun and moon horizon positions for current day"""
    try:
        _, entry = _active_location_cache("horizon_graph")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Horizon graph cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Horizon Graph cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astronomy_bp.route("/api/tonight/best-window", methods=["GET"])
@login_required
def best_window_api():
    """
    Return best observation window for tonight, from cache only
    Modes: strict, practical, illumination
    """
    try:
        mode = request.args.get("mode", "strict")
        modes = ["strict", "practical", "illumination"]
        active_location = _resolve_active_location()

        if mode == "all":
            results = {}
            missing_modes = []

            for current_mode in modes:
                cache_entry = cache_store.load_location_cache(f"best_window_{current_mode}", active_location.get("id"))
                if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
                    results[current_mode] = cache_entry["data"]
                    continue

                # Serve stale data when available instead of recomputing inline.
                if cache_entry.get("data") is not None:
                    results[current_mode] = cache_entry["data"]
                    continue

                missing_modes.append(current_mode)

            for current_mode in missing_modes:
                results[current_mode] = {
                    "status": "pending",
                    "message": (
                        f"Best window cache for mode '{current_mode}' is not ready yet. " "Please try again shortly."
                    ),
                }

            return jsonify({"modes": results})

        if mode not in modes:
            return jsonify({"error": "Invalid mode"}), 400

        cache_entry = cache_store.load_location_cache(f"best_window_{mode}", active_location.get("id"))

        if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
            return jsonify(cache_entry["data"])

        # Serve stale cache when available instead of triggering a heavy inline
        # recomputation that can exceed gunicorn timeout on small hosts.
        if cache_entry.get("data") is not None:
            return jsonify(cache_entry["data"])

        # Cache non disponible
        return (
            jsonify(
                {
                    "status": "pending",
                    "message": f"Best window cache for mode '{mode}' is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Best Window cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500
