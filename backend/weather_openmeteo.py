"""
Manage weather from Open-Meteo API
https://open-meteo.com/en/docs
"""

import json
import os
import threading
import time
from typing import Optional
import pandas as pd
from repo_config import load_config
from constants import URL_OPENMETEO, CONDITIONS_FILE
from logging_config import get_logger
from weather_utils import create_weather_client, create_fresh_weather_client

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
    dates = pd.date_range(
        start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
        periods=len(hourly.Variables(0).ValuesAsNumpy()),
        freq=pd.Timedelta(seconds=hourly.Interval()),
    )

    data = {"date": dates}

    for i, name in enumerate(hourly_vars):
        data[name] = hourly.Variables(i).ValuesAsNumpy()

    df = pd.DataFrame(data)

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
    wind_factor = (100 - df["wind_speed_10m"] * 3).clip(0, 100)

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
    calm_percent = (100 - df["wind_speed_10m"] * 5).clip(0, 100)

    # -----------------------------
    # Fog probability (%)
    # -----------------------------
    fog_percent = pd.Series(0, index=df.index)

    mask1 = df["relative_humidity_2m"] > 90
    fog_percent[mask1] = ((df["relative_humidity_2m"] - 90) * 10).clip(0, 100)

    mask2 = (df["relative_humidity_2m"] > 80) & (~mask1)
    fog_percent[mask2] = ((df["relative_humidity_2m"] - 80) * 5).clip(0, 100)

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


def get_hourly_forecast():
    """Return location info + DataFrame of the next 12 hours of weather data"""
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
        config = load_config()
        hourly_vars = [
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

        response = fetch_weather(
            latitude=config["location"]["latitude"],
            longitude=config["location"]["longitude"],
            timezone=config["location"]["timezone"],
            hourly_vars=hourly_vars,
        )

        location_info = {
            "name": config["location"]["name"],
            "latitude": response.Latitude(),
            "longitude": response.Longitude(),
            "elevation": response.Elevation(),
            "timezone": response.Timezone(),
        }

        # Because the timezone is returned as bytes
        timezone_str = response.Timezone()
        if isinstance(timezone_str, bytes):
            timezone_str = timezone_str.decode("utf-8")
        if timezone_str is None:
            timezone_str = "UTC"

        hourly_df = parse_hourly(response, hourly_vars, timezone_str=timezone_str)
        # Clear failure timestamps on success
        _FORECAST_LAST_FAILURE_TS = 0.0
        clear_openmeteo_rate_limit()
        return {"location": location_info, "hourly": hourly_df}

    except Exception as e:
        _FORECAST_LAST_FAILURE_TS = time.time()
        if _is_openmeteo_concurrency_error(e):
            record_openmeteo_rate_limit()
            logger.warning("Weather forecast: Open-Meteo concurrency limit reached, will retry after cooldown")
        elif _is_openmeteo_transient_error(e):
            logger.warning(f"Weather forecast: transient API error - {str(e)[:120]}")
        else:
            logger.warning(f"Weather forecast: unexpected error - {str(e)[:120]}")
            logger.debug("Weather forecast exception detail:", exc_info=True)
        return None
    finally:
        _FORECAST_LOCK.release()


def get_skytonight_conditions():
    """
    Return current SkyTonight conditions summary (1h forecast).
    ALWAYS fetches fresh data (no caching) for accurate real-time conditions.
    """
    try:
        config = load_config()

        hourly_vars = ["temperature_2m", "relative_humidity_2m", "surface_pressure"]

        # Bypass cache for fresh SkyTonight conditions
        response = fetch_weather(
            latitude=config["location"]["latitude"],
            longitude=config["location"]["longitude"],
            timezone=config["location"]["timezone"],
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

        # Save JSON
        os.makedirs(os.path.dirname(CONDITIONS_FILE), exist_ok=True)
        with open(CONDITIONS_FILE, "w") as f:
            json.dump(conditions, f, indent=2)

        return conditions

    except Exception:
        logger.exception("Error while fetching SkyTonight conditions")
        return None
