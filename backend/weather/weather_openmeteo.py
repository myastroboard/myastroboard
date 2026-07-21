"""
Manage weather from Open-Meteo API
https://open-meteo.com/en/docs
"""

import threading
import time
from typing import cast, Optional
import requests
import numpy as np
import pandas as pd
from utils import save_json_file
from utils.repo_config import load_config, get_install_default_location
from utils.constants import URL_OPENMETEO, CONDITIONS_FILE, SKYTONIGHT_LIVE_CONDITIONS_DEBOUNCE_SECONDS
from utils.logging_config import get_logger
from weather.weather_utils import create_weather_client, create_fresh_weather_client

# Create logger with centralized configuration
logger = get_logger(__name__)

# Single-flight protection for hourly forecast: prevent concurrent live API calls
_FORECAST_LOCK = threading.Lock()
_FORECAST_LAST_FAILURE_TS: float = 0.0
_FORECAST_FAILURE_COOLDOWN = 45.0  # seconds to back off after a failed fetch

# Global shared gate: when ANY Open-Meteo call hits the concurrency limit,
# ALL callers (forecast + astro analysis) back off together so they don't
# cycle out-of-phase and keep competing for the single free-tier slot.
_GLOBAL_CONCURRENCY_TS: float = 0.0
_GLOBAL_CONCURRENCY_COOLDOWN = 90.0  # seconds


def _is_openmeteo_concurrency_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "too many concurrent" in msg or "concurrent requests" in msg


def _is_openmeteo_transient_error(exc: Exception) -> bool:
    """Return True for well-known transient server/network errors that need no traceback."""
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "502",
            "503",
            "504",
            "max retries exceeded",
            "too many 502",
            "too many 503",
            "timed out",
            "timeout",
            "connection reset",
            "connection refused",
            "connection error",
            "remote end closed",
        )
    )


def is_openmeteo_rate_limited() -> bool:
    """Return True while the shared Open-Meteo concurrency-limit cooldown is active."""
    return (time.time() - _GLOBAL_CONCURRENCY_TS) < _GLOBAL_CONCURRENCY_COOLDOWN


def record_openmeteo_rate_limit() -> None:
    """Record that the Open-Meteo concurrency limit was just hit (any caller)."""
    global _GLOBAL_CONCURRENCY_TS
    _GLOBAL_CONCURRENCY_TS = time.time()


def clear_openmeteo_rate_limit() -> None:
    """Reset the shared gate after a successful Open-Meteo fetch."""
    global _GLOBAL_CONCURRENCY_TS
    _GLOBAL_CONCURRENCY_TS = 0.0


def fetch_weather(latitude, longitude, timezone, hourly_vars, forecast_hours=12, use_cache=True):
    """
    Call Open-Meteo API and return raw response

    Args:
        latitude: Location latitude
        longitude: Location longitude
        timezone: Timezone string
        hourly_vars: List of variables to fetch
        forecast_hours: Number of hours to forecast (default 12)
        use_cache: If True, use cached client; If False, always fetch fresh data (default True)

    Returns:
        Raw API response
    """
    # Choose client based on caching preference
    if use_cache:
        client = create_weather_client()
    else:
        client = create_fresh_weather_client()

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "hourly": hourly_vars,
        "forecast_hours": forecast_hours,
    }

    response = client.weather_api(URL_OPENMETEO, params=params)[0]
    return response


def parse_hourly(response, hourly_vars, timezone_str: Optional[str] = "UTC"):
    """Transform raw response into pandas DataFrame, apply timezone"""

    hourly = response.Hourly()

    # Dates in UTC
    expected_len = None
    for i, name in enumerate(hourly_vars):
        try:
            first_values = np.asarray(hourly.Variables(i).ValuesAsNumpy()).reshape(-1)
            expected_len = len(first_values)
            break
        except Exception as e:
            logger.warning(f"Hourly field '{name}' failed to decode, will use defaults - {str(e)[:120]}")

    if expected_len is None:
        raise ValueError("Unable to decode any hourly weather variable from Open-Meteo response")

    dates = pd.date_range(
        start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
        periods=expected_len,
        freq=pd.Timedelta(seconds=hourly.Interval()),
    )

    data: dict[str, object] = {"date": dates}

    for i, name in enumerate(hourly_vars):
        try:
            values = np.asarray(hourly.Variables(i).ValuesAsNumpy()).reshape(-1)
        except Exception as e:
            logger.warning(f"Hourly field '{name}' decode failed, substituting defaults - {str(e)[:120]}")
            values = np.full(expected_len, np.nan)
        if len(values) != expected_len:
            logger.warning(
                f"Hourly field '{name}' length mismatch (got {len(values)}, expected {expected_len}); "
                "coercing to aligned series"
            )
            if len(values) < expected_len:
                values = np.pad(values, (0, expected_len - len(values)), mode="constant", constant_values=np.nan)
            else:
                values = values[:expected_len]

        # Coerce to numeric to avoid array/object payloads causing downstream math errors.
        data[name] = pd.to_numeric(values, errors="coerce")

    df = pd.DataFrame(data)
    df = _normalize_hourly_dataframe(df)

    return _enrich_hourly_dataframe(df, timezone_str=timezone_str)


def _normalize_hourly_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required weather columns exist with safe defaults."""
    defaults = {
        "cloud_cover": 100.0,
        "cloud_cover_low": 100.0,
        "cloud_cover_mid": 100.0,
        "cloud_cover_high": 100.0,
        "wind_speed_10m": 0.0,
        "lifted_index": 0.0,
        "relative_humidity_2m": 70.0,
        "visibility": 20000.0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = cast(pd.Series, pd.to_numeric(df[col], errors="coerce")).fillna(default)
    return df


def _enrich_hourly_dataframe(df: pd.DataFrame, timezone_str: Optional[str] = "UTC") -> pd.DataFrame:
    """Apply timezone conversion and derive astronomy-focused weather metrics."""
    # Convert to requested timezone
    try:
        # Ensure the timezone string is valid and convert
        if timezone_str and timezone_str != "UTC":
            # Test if the timezone string is valid first
            import zoneinfo

            try:
                zoneinfo.ZoneInfo(timezone_str)
                df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(timezone_str)
            except zoneinfo.ZoneInfoNotFoundError:
                logger.warning(f"Unknown timezone '{timezone_str}', keeping dates in UTC")
                # Keep dates in UTC if timezone is invalid
        # If timezone_str is None, empty, or UTC, keep as UTC
    except Exception as e:
        logger.warning(f"Failed to convert timezone to {timezone_str}: {e}")
        # Keep dates in UTC if conversion fails

    # -----------------------------
    # Cloudless %
    # -----------------------------
    df["cloudless"] = 100 - df["cloud_cover"]
    df["cloudless_low"] = 100 - df["cloud_cover_low"]
    df["cloudless_mid"] = 100 - df["cloud_cover_mid"]
    df["cloudless_high"] = 100 - df["cloud_cover_high"]

    # -----------------------------
    # Seeing proxy (%)
    # -----------------------------
    wind_factor = cast(pd.Series, 100 - df["wind_speed_10m"] * 3).clip(0, 100)

    stability_factor = (df["lifted_index"] * 5 + 50).clip(0, 100)

    seeing_percent = (wind_factor * 0.7 + stability_factor * 0.3).clip(0, 100)

    # -----------------------------
    # Transparency proxy (%)
    # -----------------------------
    humidity_factor = (100 - df["relative_humidity_2m"]).clip(0, 100)

    visibility_km = df["visibility"] / 1000
    visibility_factor = (visibility_km / 30 * 100).clip(0, 100)

    transparency_percent = (humidity_factor * 0.4 + visibility_factor * 0.6).clip(0, 100)

    # -----------------------------
    # Calm (%)
    # -----------------------------
    calm_percent = cast(pd.Series, 100 - df["wind_speed_10m"] * 5).clip(0, 100)

    # -----------------------------
    # Fog probability (%)
    # -----------------------------
    fog_percent = pd.Series(0, index=df.index)

    mask1 = df["relative_humidity_2m"] > 90
    fog_percent.loc[mask1] = ((df["relative_humidity_2m"] - 90) * 10).clip(0, 100)

    mask2 = (df["relative_humidity_2m"] > 80) & (~mask1)
    fog_percent.loc[mask2] = ((df["relative_humidity_2m"] - 80) * 5).clip(0, 100)

    # -----------------------------
    # Overall astro condition score
    # -----------------------------
    condition_percent = (df["cloudless"] * 0.5 + seeing_percent * 0.25 + transparency_percent * 0.25).clip(0, 100)

    # -----------------------------
    # Store final metrics
    # -----------------------------
    df["condition"] = condition_percent.round(1)
    df["seeing"] = seeing_percent.round(1)
    df["calm"] = calm_percent.round(1)
    df["fog"] = fog_percent.round(1)
    df["transparency"] = transparency_percent.round(1)

    return df


def fetch_weather_json(latitude, longitude, timezone, hourly_vars, forecast_hours=12):
    """Fetch Open-Meteo forecast via plain JSON HTTP as a fallback to SDK decoding."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "hourly": ",".join(hourly_vars),
        "forecast_hours": forecast_hours,
    }
    response = requests.get(URL_OPENMETEO, params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ValueError("Open-Meteo JSON fallback: missing hourly payload")
    return payload


def parse_hourly_json(payload, hourly_vars, timezone_str: Optional[str] = "UTC"):
    """Transform raw JSON fallback response into pandas DataFrame and derived metrics."""
    hourly = payload.get("hourly") or {}
    time_values = hourly.get("time")
    if not isinstance(time_values, list) or not time_values:
        raise ValueError("Open-Meteo JSON fallback: hourly time series is missing")

    dates = pd.to_datetime(time_values, format="mixed", errors="coerce")
    if cast(np.ndarray, dates.isna()).all():
        raise ValueError("Open-Meteo JSON fallback: unable to parse hourly timestamps")

    # Unlike the flatbuffer SDK path (hourly.Time() is always true UTC epoch
    # seconds), Open-Meteo's plain JSON API returns naive LOCAL wall-clock
    # strings whenever a timezone is requested. Localize before treating as
    # UTC, or every non-UTC location gets its forecast window shifted by its
    # own UTC offset - invisible for small offsets, but for e.g. Hawaii
    # (UTC-10) it pushes the whole 12h window into the past, so the frontend's
    # "future only" filter drops every entry and nothing renders.
    tz = timezone_str or "UTC"
    try:
        dates = dates.tz_localize(tz)
    except Exception:
        logger.warning(f"Unknown timezone '{tz}' in JSON fallback, treating hourly times as UTC")
        dates = dates.tz_localize("UTC")

    expected_len = len(dates)
    data: dict[str, object] = {"date": dates}

    for name in hourly_vars:
        raw_values = hourly.get(name, [])
        values = np.asarray(raw_values).reshape(-1)
        if len(values) != expected_len:
            logger.warning(
                f"Hourly JSON field '{name}' length mismatch (got {len(values)}, expected {expected_len}); "
                "coercing to aligned series"
            )
            if len(values) < expected_len:
                values = np.pad(values, (0, expected_len - len(values)), mode="constant", constant_values=np.nan)
            else:
                values = values[:expected_len]
        data[name] = pd.to_numeric(values, errors="coerce")

    df = pd.DataFrame(data)
    df = _normalize_hourly_dataframe(df)
    return _enrich_hourly_dataframe(df, timezone_str=timezone_str)


def get_hourly_forecast(location=None):
    """Return location info + DataFrame of the next 12 hours of weather data.

    ``location`` is a v1.2 location preset dict; falls back to the install
    default preset when omitted. The single-flight lock and failure cooldown
    stay GLOBAL (not per-location) so multi-location installs still respect
    Open-Meteo's concurrency limit as one shared budget.
    """
    global _FORECAST_LAST_FAILURE_TS

    # Failure cooldown: don't retry if we just failed
    if time.time() - _FORECAST_LAST_FAILURE_TS < _FORECAST_FAILURE_COOLDOWN:
        logger.debug("Weather forecast in failure cooldown, skipping live fetch")
        return None

    # Single-flight: if another request is already fetching, skip rather than pile on
    if not _FORECAST_LOCK.acquire(blocking=False):
        logger.debug("Weather forecast fetch already in progress, skipping")
        return None

    try:
        if not isinstance(location, dict) or location.get("latitude") is None:
            location = get_install_default_location(load_config())
        hourly_vars_full = [
            "temperature_2m",
            "relative_humidity_2m",
            "dew_point_2m",
            "precipitation_probability",
            "precipitation",
            "rain",
            "weather_code",
            "visibility",
            "wind_speed_10m",
            "wind_direction_10m",
            "cloud_cover",
            "cloud_cover_low",
            "cloud_cover_mid",
            "cloud_cover_high",
            "lifted_index",
            "sunshine_duration",
            "is_day",
            "uv_index",
            "surface_pressure",
        ]

        hourly_vars_core = [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation_probability",
            "precipitation",
            "rain",
            "weather_code",
            "visibility",
            "wind_speed_10m",
            "wind_direction_10m",
            "cloud_cover",
            "cloud_cover_low",
            "cloud_cover_mid",
            "cloud_cover_high",
            "is_day",
        ]

        def _build_forecast_from_sdk_response(response, used_hourly_vars):
            # Some transient SDK decode issues affect scalar accessors even when hourly
            # data is still readable. Fall back to configured location metadata.
            try:
                latitude = response.Latitude()
            except Exception as e:
                logger.warning(f"Weather forecast: latitude decode failed, using configured location - {str(e)[:120]}")
                latitude = location.get("latitude")

            try:
                longitude = response.Longitude()
            except Exception as e:
                logger.warning(f"Weather forecast: longitude decode failed, using configured location - {str(e)[:120]}")
                longitude = location.get("longitude")

            try:
                elevation = response.Elevation()
            except Exception:
                elevation = None

            try:
                timezone_str = response.Timezone()
            except Exception as e:
                logger.warning(f"Weather forecast: timezone decode failed, using configured timezone - {str(e)[:120]}")
                timezone_str = location.get("timezone")

            if isinstance(timezone_str, bytes):
                timezone_str = timezone_str.decode("utf-8")
            if timezone_str is None:
                timezone_str = location.get("timezone") or "UTC"

            location_info = {
                "name": location["name"],
                "id": location.get("id"),
                "latitude": latitude,
                "longitude": longitude,
                "elevation": elevation,
                "timezone": timezone_str,
            }

            hourly_df = parse_hourly(response, used_hourly_vars, timezone_str=timezone_str)
            return {"location": location_info, "hourly": hourly_df}

        try:
            response = fetch_weather(
                latitude=location["latitude"],
                longitude=location["longitude"],
                timezone=location["timezone"],
                hourly_vars=hourly_vars_full,
            )
            result = _build_forecast_from_sdk_response(response, hourly_vars_full)
            _FORECAST_LAST_FAILURE_TS = 0.0
            clear_openmeteo_rate_limit()
            logger.debug(f"Weather forecast failure timestamp reset to {_FORECAST_LAST_FAILURE_TS}")
            return result
        except Exception as full_error:
            if _is_openmeteo_concurrency_error(full_error):
                raise
            logger.debug(
                f"Weather forecast: full request failed, retrying with core variables - {str(full_error)[:120]}"
            )

        try:
            response = fetch_weather(
                latitude=location["latitude"],
                longitude=location["longitude"],
                timezone=location["timezone"],
                hourly_vars=hourly_vars_core,
                use_cache=False,
            )
            result = _build_forecast_from_sdk_response(response, hourly_vars_core)
            _FORECAST_LAST_FAILURE_TS = 0.0
            clear_openmeteo_rate_limit()
            logger.debug("Weather forecast recovered via core-variable SDK fallback")
            return result
        except Exception as core_error:
            if _is_openmeteo_concurrency_error(core_error):
                raise
            logger.debug(
                f"Weather forecast: core request failed, retrying with JSON fallback - {str(core_error)[:120]}"
            )

        payload = fetch_weather_json(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"],
            hourly_vars=hourly_vars_core,
        )
        timezone_str = payload.get("timezone") or location.get("timezone") or "UTC"
        hourly_df = parse_hourly_json(payload, hourly_vars_core, timezone_str=timezone_str)
        location_info = {
            "name": location["name"],
            "id": location.get("id"),
            "latitude": payload.get("latitude", location.get("latitude")),
            "longitude": payload.get("longitude", location.get("longitude")),
            "elevation": payload.get("elevation"),
            "timezone": timezone_str,
        }
        _FORECAST_LAST_FAILURE_TS = 0.0
        clear_openmeteo_rate_limit()
        logger.debug("Weather forecast recovered via JSON fallback")
        return {"location": location_info, "hourly": hourly_df}

    except Exception as e:
        _FORECAST_LAST_FAILURE_TS = time.time()
        cooldown_until = _FORECAST_LAST_FAILURE_TS + _FORECAST_FAILURE_COOLDOWN
        if _is_openmeteo_concurrency_error(e):
            record_openmeteo_rate_limit()
            logger.warning("Weather forecast: Open-Meteo concurrency limit reached, will retry after cooldown")
        elif _is_openmeteo_transient_error(e):
            logger.warning(f"Weather forecast: transient API error - {str(e)[:120]}")
        else:
            logger.warning(f"Weather forecast: unexpected error - {str(e)[:120]}")
            logger.debug("Weather forecast exception detail:", exc_info=True)
        logger.debug(f"Weather forecast cooldown active until {cooldown_until}")
        return None
    finally:
        _FORECAST_LOCK.release()


# Server-side debounce for the live-conditions fetch: per-location result kept
# for SKYTONIGHT_LIVE_CONDITIONS_DEBOUNCE_SECONDS so a hammered tab cannot
# multiply uncached Open-Meteo calls (see docs/LOCATIONS.md rate-limit analysis).
_SKYTONIGHT_CONDITIONS_DEBOUNCE: dict = {}
_SKYTONIGHT_CONDITIONS_DEBOUNCE_LOCK = threading.Lock()


def get_skytonight_conditions(location=None):
    """
    Return current SkyTonight conditions summary (1h forecast).
    Fetches fresh data (no client cache), debounced server-side per location.
    """
    try:
        if not isinstance(location, dict) or location.get("latitude") is None:
            location = get_install_default_location(load_config())
        debounce_key = location.get("id") or f"{location.get('latitude')}:{location.get('longitude')}"

        with _SKYTONIGHT_CONDITIONS_DEBOUNCE_LOCK:
            cached = _SKYTONIGHT_CONDITIONS_DEBOUNCE.get(debounce_key)
            if cached and (time.time() - cached["ts"]) < SKYTONIGHT_LIVE_CONDITIONS_DEBOUNCE_SECONDS:
                logger.debug("SkyTonight conditions served from per-location debounce window")
                return cached["data"]

        hourly_vars = ["temperature_2m", "relative_humidity_2m", "surface_pressure"]

        # Bypass cache for fresh SkyTonight conditions
        response = fetch_weather(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location["timezone"],
            hourly_vars=hourly_vars,
            forecast_hours=1,
            use_cache=False,  # Always fetch fresh data for SkyTonight
        )

        hourly = response.Hourly()
        if hourly is None:
            raise ValueError("Hourly data missing from weather response")

        # Extract first hour only
        temp_values = hourly.Variables(0)
        humidity_values = hourly.Variables(1)
        pressure_values = hourly.Variables(2)

        if temp_values is None or humidity_values is None or pressure_values is None:
            raise ValueError("Hourly variables missing from weather response")

        temperature = float(temp_values.ValuesAsNumpy()[0])
        humidity = float(humidity_values.ValuesAsNumpy()[0]) / 100
        pressure = float(pressure_values.ValuesAsNumpy()[0]) / 1000

        conditions = {
            "temperature": round(temperature, 1),
            "relative_humidity": round(humidity, 2),
            "pressure": round(pressure, 3),
        }

        # Persist atomically (temp file + os.replace) so a concurrent reader never
        # sees a half-written file.
        save_json_file(CONDITIONS_FILE, conditions)

        with _SKYTONIGHT_CONDITIONS_DEBOUNCE_LOCK:
            _SKYTONIGHT_CONDITIONS_DEBOUNCE[debounce_key] = {"ts": time.time(), "data": conditions}

        return conditions

    except Exception:
        logger.exception("Error while fetching SkyTonight conditions")
        return None
