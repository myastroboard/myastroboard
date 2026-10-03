"""Weather, Moon, Aurora and Seeing forecast Blueprint.

Routes: /api/weather/*, /api/moon/*, /api/aurora/predictions, /api/seeing-forecast
"""

import datetime
import json
import math
import time as _time
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from astroweather import moon_calendar
from cache import cache_store
from utils.auth import login_required
from utils.constants import CACHE_TTL, CACHE_TTL_ASTRO_WEATHER, WEATHER_CACHE_TTL
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger
from utils.repo_config import load_config
from utils.route_helpers import _active_location_cache, _resolve_active_location
from weather.weather_openmeteo import get_hourly_forecast

logger = get_logger(__name__)

weather_bp = Blueprint('weather', __name__)


def _local_condition_score(record):
    """Self-contained 0-100 fallback score from a weather record's own component series
    (``cloudless`` / ``seeing`` / ``transparency``), for hours the jet-stream-aware
    ``astro_weather`` score cannot cover.

    A cold or partial astro cache would otherwise leave every hour with no ``condition``,
    blanking the Weather tab's quality column. This mirrors the component weighting
    ``weather_openmeteo`` applied before the app-wide observation score was unified.
    Returns ``None`` when a component is missing or not a finite number.
    """
    try:
        cloudless = float(record["cloudless"])
        seeing = float(record["seeing"])
        transparency = float(record["transparency"])
    except KeyError, TypeError, ValueError:
        return None
    if not all(math.isfinite(v) for v in (cloudless, seeing, transparency)):
        return None
    blended = cloudless * 0.5 + seeing * 0.25 + transparency * 0.25
    return round(min(100.0, max(0.0, blended)), 1)


def _forecast_with_observation_score(payload, location_id):
    """Return a copy of a weather-forecast payload with each hourly record's ``condition``
    set to the app-wide observation score for that hour (weather_astro's
    ``observation_score`` x10, 0-100), read from the warm astro_weather cache.

    There is a single observation score in the app; ``weather_openmeteo`` no longer derives
    one. Hours the astro cache cannot answer (cold/partial cache, or no matching hour) fall
    back to ``_local_condition_score`` so the quality column degrades gracefully instead of
    going blank. A record with neither an astro score nor usable components gets no
    ``condition`` key - the Weather tab renders that as "unknown".
    """
    hourly = [dict(record) for record in ((payload or {}).get("hourly") or [])]
    score_by_hour = {}
    try:
        astro_entry = cache_store.load_location_cache("astro_weather", location_id)
        astro_hourly = (astro_entry.get("data") or {}).get("hourly_data") or []
        score_by_hour = {
            str(row.get("datetime"))[:13]: row.get("observation_score")
            for row in astro_hourly
            if row.get("datetime") is not None and row.get("observation_score") is not None
        }
    except Exception:
        logger.exception("Failed to read observation score cache for weather forecast")

    for record in hourly:
        record.pop("condition", None)
        raw = score_by_hour.get(str(record.get("date"))[:13])
        merged = None
        if raw is not None:
            try:
                merged = round(float(raw) * 10, 1)
            except TypeError, ValueError:
                merged = None
        if merged is None:
            merged = _local_condition_score(record)
        if merged is not None:
            record["condition"] = merged

    return {**(payload or {}), "hourly": hourly}


def _cached_astro_analysis_if_default(hours, language, location_id):
    """Return the warm ``astro_weather`` cache payload when it can answer this request
    verbatim - the 24h analysis in the install's configured language, which is what the
    Astrophotography tab always asks for. Returns ``None`` for any other hours/language so
    the caller falls back to the live analysis path unchanged. Stale is accepted (the
    scheduler refreshes it); an empty slot returns ``None``.
    """
    if hours != 24 or language != load_config().get("language", "en"):
        return None
    entry = cache_store.load_location_cache("astro_weather", location_id)
    if not cache_store.is_cache_valid(entry, CACHE_TTL_ASTRO_WEATHER):
        return None  # scheduler slot missing or stale - let the live path recompute/degrade
    return entry.get("data") or None


@weather_bp.route('/api/weather/forecast', methods=['GET'])
@login_required
def get_hourly_forecast_api():
    """Get hourly weather forecast for the caller's active location"""
    try:
        active_location, weather_entry = _active_location_cache("weather_forecast")
        location_id = active_location.get("id")

        # Serve from app cache if valid - avoids a live API call on every page load
        if cache_store.is_cache_valid(weather_entry, WEATHER_CACHE_TTL):
            return jsonify(_forecast_with_observation_score(weather_entry["data"], location_id))

        # Cache miss or stale: fetch live (requests_cache SQLite deduplicates across workers)
        forecast = get_hourly_forecast(location=active_location)
        if forecast is None:
            # Serve stale cache rather than returning an error
            if weather_entry.get("data"):
                logger.warning("[WARNING] Weather API unavailable, serving stale cache")
                return jsonify(_forecast_with_observation_score(weather_entry["data"], location_id))
            return (
                jsonify(
                    {"status": "pending", "message": "Weather data is temporarily unavailable. Please retry shortly."}
                ),
                202,
            )

        df = forecast["hourly"].copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: x.decode() if isinstance(x, bytes) else x)
        hourly_json = json.loads(df.to_json(orient="records"))
        location = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in forecast["location"].items()}
        response_payload = {"location": location, "hourly": hourly_json}

        # Keep cache status/metrics consistent even when this endpoint performs
        # an on-demand refresh outside the scheduler cycle.
        cache_store.update_location_cache("weather_forecast", location_id, response_payload)

        return jsonify(_forecast_with_observation_score(response_payload, location_id))

    except Exception as e:
        logger.error(f"Error getting hourly forecast: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route('/api/weather/astro-analysis', methods=['GET'])
@login_required
def get_astro_weather_analysis_api():
    """Get comprehensive astrophotography weather analysis"""
    try:
        from weather.weather_astro import get_astro_weather_analysis

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        # Get optional hours parameter (default 24)
        hours = request.args.get('hours', 24, type=int)
        hours = min(max(hours, 1), 72)  # Limit between 1-72 hours

        location = _resolve_active_location()

        # The Astrophotography tab always asks for the 24h analysis in the configured
        # language - serve that from the warm scheduler cache so the "Score de la Nuit"
        # cards match the sky-widget pill and the location switcher exactly.
        cached = _cached_astro_analysis_if_default(hours, language, location.get("id"))
        if cached is not None:
            return jsonify(cached)

        analysis = get_astro_weather_analysis(hours, language=language, location=location)
        if analysis is None:
            return (
                jsonify(
                    {
                        "status": "pending",
                        "message": (
                            "Astrophotography weather analysis is temporarily unavailable. Please retry shortly."
                        ),
                    }
                ),
                202,
            )

        return jsonify(analysis)

    except Exception as e:
        logger.error(f"Error getting astro weather analysis: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route('/api/weather/astro-current', methods=['GET'])
@login_required
def get_current_astro_conditions_api():
    """Get current astrophotography conditions summary"""
    try:
        from weather.weather_astro import get_current_astro_conditions

        location = _resolve_active_location()

        # current_conditions is language-independent (pure numbers) - serve it from the
        # warm astro_weather cache whenever present so it matches the sky-widget pill.
        entry = cache_store.load_location_cache("astro_weather", location.get("id"))
        cached_current = (entry.get("data") or {}).get("current_conditions")
        if cached_current:
            return jsonify(cached_current)

        conditions = get_current_astro_conditions(location=location)
        if conditions is None:
            return jsonify({"error": "Failed to fetch current astrophotography conditions"}), 500

        return jsonify(conditions)

    except Exception as e:
        logger.error(f"Error getting current astro conditions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route('/api/weather/alerts', methods=['GET'])
@login_required
def get_weather_alerts_api():
    """Get weather alerts for astrophotography"""
    try:
        from weather.weather_astro import get_astro_weather_analysis

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        analysis = get_astro_weather_analysis(
            6, language=language, location=_resolve_active_location()
        )  # Next 6 hours for alerts
        if analysis is None:
            return jsonify({"alerts": [], "status": "pending"}), 200

        return jsonify(
            {
                "alerts": analysis.get("weather_alerts", []),
                "generated_at": analysis.get("generated_at"),
                "location": analysis.get("location"),
            }
        )

    except Exception as e:
        logger.error(f"Error getting weather alerts: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route("/api/moon/report", methods=["GET"])
@login_required
def get_moon_report_api():
    """Return astrophotography-grade Moon report from scheduler-managed cache."""
    try:
        _, entry = _active_location_cache("moon_report")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        # Avoid synchronous recomputation in request path: moon calculations can
        # exceed gunicorn timeout on small hosts and cause worker restart loops.
        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not ready yet (scheduler will refresh in background).
        return (
            jsonify({"status": "pending", "message": "Moon report cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Moon report cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route("/api/moon/dark-window", methods=["GET"])
@login_required
def get_next_dark_window_api():
    """Return next astronomical moonless dark window from scheduler-managed cache."""
    try:
        _, entry = _active_location_cache("dark_window")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        # Avoid synchronous recomputation in request path: moon calculations can
        # exceed gunicorn timeout on small hosts and cause worker restart loops.
        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not ready yet (scheduler will refresh in background).
        return (
            jsonify({"status": "pending", "message": "Dark window cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Dark Window cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route("/api/moon/next-7-nights", methods=["GET"])
@login_required
def get_next_7_nights_api():
    """Return Moon Planner next 7 nights report, from cache only"""
    try:
        _, entry = _active_location_cache("moon_planner")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify({"status": "pending", "message": "Moon Planner cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Moon Planner cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


_moon_phase_calendar_cache: dict = {}  # "<tz>:<yyyy-mm>" -> {"timestamp", "data"}
_MOON_PHASE_CALENDAR_TTL = 21600  # 6 hours - the per-day phase data is deterministic
_MOON_PHASE_CALENDAR_CACHE_MAX = 32  # ~2 reachable months x a handful of timezones; evict the oldest beyond this


def _clamp_calendar_month(req_year, req_month, cur_year: int, cur_month: int) -> tuple[int, int]:
    """Clamp a requested (year, month) to the allowed window [current month, current month + 1].

    Missing or malformed values fall back to the current month.
    """
    cur_index = cur_year * 12 + (cur_month - 1)
    try:
        req_index = int(req_year) * 12 + (int(req_month) - 1)
    except TypeError, ValueError:
        req_index = cur_index
    req_index = max(cur_index, min(req_index, cur_index + 1))
    clamped_year, month_zero_based = divmod(req_index, 12)
    return clamped_year, month_zero_based + 1


@weather_bp.route("/api/moon/phase-calendar", methods=["GET"])
@login_required
def get_moon_phase_calendar_api():
    """Return a full calendar month of Moon phases for the active location.

    Query params ``year`` and ``month`` are clamped to the allowed 2-month window
    (current month and the next one); anything outside or malformed falls back to
    the current month. Pure ephemeris - always available, never 'pending'.
    """
    try:
        location = _resolve_active_location()
        tz_name = location.get("timezone", "UTC")
        now_local = datetime.datetime.now(ZoneInfo(tz_name))

        year, month = _clamp_calendar_month(
            request.args.get("year"), request.args.get("month"), now_local.year, now_local.month
        )

        cache_key = f"{tz_name}:{year:04d}-{month:02d}"
        slot = _moon_phase_calendar_cache.setdefault(cache_key, {"timestamp": 0.0, "data": None})
        clock = _time.time()
        if not slot["data"] or (clock - slot["timestamp"]) >= _MOON_PHASE_CALENDAR_TTL:
            slot["data"] = moon_calendar.build_phase_calendar(year, month, tz_name)
            slot["timestamp"] = clock
            # Only current/next month are ever reachable, so stale (old-month or
            # other-timezone) entries just accumulate - drop the oldest past the cap.
            while len(_moon_phase_calendar_cache) > _MOON_PHASE_CALENDAR_CACHE_MAX:
                oldest = min(_moon_phase_calendar_cache, key=lambda k: _moon_phase_calendar_cache[k]["timestamp"])
                _moon_phase_calendar_cache.pop(oldest, None)

        calendar_data = slot["data"]
        current_index = now_local.year * 12 + (now_local.month - 1)
        viewed_index = year * 12 + (month - 1)
        is_current_month = viewed_index == current_index

        return jsonify(
            {
                "year": year,
                "month": month,
                "timezone": tz_name,
                "location": {"id": location.get("id"), "name": location.get("name")},
                "today": now_local.date().isoformat(),
                "is_current_month": is_current_month,
                "can_go_prev": viewed_index == current_index + 1,
                "can_go_next": is_current_month,
                "days": calendar_data["days"],
                "principal_phases": calendar_data["principal_phases"],
            }
        )

    except Exception as e:
        logger.error(f"Error computing moon phase calendar: {e}")
        return jsonify({"error": "Internal server error"}), 500


@weather_bp.route("/api/aurora/predictions", methods=["GET"])
@login_required
def get_aurora_predictions_api():
    """Return Aurora Borealis predictions report, from cache only"""
    try:
        _, entry = _active_location_cache("aurora")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Aurora predictions cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Aurora predictions cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@weather_bp.route("/api/seeing-forecast", methods=["GET"])
@login_required
def get_seeing_forecast_api():
    """Return atmospheric seeing forecast for planetary imaging, from cache only"""
    try:
        _, entry = _active_location_cache("seeing_forecast")
        if cache_store.is_cache_valid(entry, CACHE_TTL):
            return jsonify(entry["data"])

        stale_data = entry.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Seeing forecast cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Seeing forecast cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500
