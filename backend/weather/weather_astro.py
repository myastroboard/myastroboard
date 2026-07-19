"""
Advanced Weather Metrics for Astrophotography
Provides specialized weather analysis for astronomical observation and imaging

Features:
- Cloud altitude layer discrimination (high/mid/low)
- Seeing forecast (Pickering scale 1-10)
- Transparency forecast (magnitude limit prediction)
- Jet stream impact on seeing
- Dew point and humidity alerts
- Wind speed impact on tracking
"""

import copy
import time
import threading
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple, cast
from datetime import datetime, timedelta

from utils.repo_config import load_config
from utils.constants import (
    URL_OPENMETEO,
    ASTRO_BEST_PERIOD_MIN_DURATION_HOURS,
)
from utils.logging_config import get_logger
from weather.weather_utils import create_weather_client
from weather.weather_openmeteo import (
    is_openmeteo_rate_limited,
    record_openmeteo_rate_limit,
    _is_openmeteo_transient_error,
)
from utils.i18n_utils import create_translated_alert

# Create logger with centralized configuration
logger = get_logger(__name__)

# Astrophotography-specific constants
PICKERING_SCALE_MAX = 10
MAGNITUDE_LIMIT_ZENITH_MIN = 4.0  # Urban limit
MAGNITUDE_LIMIT_ZENITH_MAX = 8.0  # Perfect dark sky
DEW_POINT_WARNING_THRESHOLD = 2.0  # °C difference from ambient
JET_STREAM_ALTITUDE = 9000  # meters (typical jet stream altitude)
PRECIPITATION_VETO_MM = 2.0  # mm/h of forecast precipitation that fully zeroes the observation score

_ASTRO_ANALYSIS_LOCK = threading.Lock()
_ASTRO_ANALYSIS_LAST_SUCCESS: Dict[Tuple[int, str, str], Dict[str, Any]] = {}
_ASTRO_ANALYSIS_LAST_SUCCESS_TS: Dict[Tuple[int, str, str], float] = {}
_ASTRO_ANALYSIS_LAST_FAILURE_TS: Dict[Tuple[int, str, str], float] = {}
_ASTRO_ANALYSIS_FAILURE_COOLDOWN = 90.0  # seconds to wait before retrying after a failed fetch
_ASTRO_ANALYSIS_CACHE_TTL = 1800.0  # 30 minutes - Open-Meteo data doesn't change faster than hourly


def _analysis_cache_key(hours: int, language: str, location_id: str = "") -> Tuple[int, str, str]:
    # location_id is part of the key (v1.2): without it, one location's analysis
    # would silently be served for a different location's tab in multi-location
    # installs (the pre-v1.2 key was only (hours, language)).
    return (int(hours), language or "en", location_id or "")


def _get_last_successful_analysis(hours: int, language: str, location_id: str = "") -> Optional[Dict[str, Any]]:
    key = _analysis_cache_key(hours, language, location_id)
    cached = _ASTRO_ANALYSIS_LAST_SUCCESS.get(key)
    if cached is None:
        return None
    return copy.deepcopy(cached)


def _store_last_successful_analysis(hours: int, language: str, data: Dict[str, Any], location_id: str = "") -> None:
    key = _analysis_cache_key(hours, language, location_id)
    _ASTRO_ANALYSIS_LAST_SUCCESS[key] = copy.deepcopy(data)
    _ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = time.time()


def _is_openmeteo_concurrency_error(exc: Exception) -> bool:
    return "Too many concurrent requests" in str(exc)


class AstroWeatherAnalyzer:
    """Advanced weather analysis for astrophotography"""

    def __init__(self, language: str = "en", location: Optional[Dict[str, Any]] = None):
        self.config = load_config()
        if isinstance(location, dict) and location.get("latitude") is not None:
            self.location = location
        else:
            from utils.repo_config import get_install_default_location

            self.location = get_install_default_location(self.config)
        self.language = language

    def fetch_extended_weather_data(self, forecast_hours: int = 24) -> Optional[Dict]:
        """
        Fetch extended weather data with additional atmospheric variables
        for astrophotography analysis
        """
        try:
            client = create_weather_client()
            location_str = f"lat={int(self.location.get('latitude', 0))}, lon={int(self.location.get('longitude', 0))}"

            # Full extended hourly variables for astrophotography (including jet stream data)
            hourly_vars_full = [
                # Basic weather
                "temperature_2m",
                "relative_humidity_2m",
                "dew_point_2m",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_speed_80m",
                "wind_speed_120m",
                "surface_pressure",
                "visibility",
                # Cloud layers
                "cloud_cover",
                "cloud_cover_low",
                "cloud_cover_mid",
                "cloud_cover_high",
                # Atmospheric stability
                "lifted_index",
                "convective_inhibition",
                # Precipitation
                "precipitation",
                "precipitation_probability",
                # Solar/UV
                "is_day",
                "uv_index",
                # Jet stream data (critical for astro analysis)
                "geopotential_height_500hPa",
                "geopotential_height_850hPa",
                "temperature_500hPa",
                "temperature_850hPa",
                "wind_speed_500hPa",
                "wind_direction_500hPa",
            ]

            # Fallback: core variables only (if full request fails)
            hourly_vars_core = [
                "temperature_2m",
                "relative_humidity_2m",
                "dew_point_2m",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_speed_80m",
                "wind_speed_120m",
                "surface_pressure",
                "visibility",
                "cloud_cover",
                "cloud_cover_low",
                "cloud_cover_mid",
                "cloud_cover_high",
                "lifted_index",
                "convective_inhibition",
                "precipitation",
                "precipitation_probability",
                "is_day",
                "uv_index",
            ]

            logger.debug(
                f"Fetching astro weather: {location_str}, {forecast_hours}h,"
                f" {len(hourly_vars_full)} variables (full with jet stream)"
            )

            params = {
                "latitude": self.location.get("latitude"),
                "longitude": self.location.get("longitude"),
                "timezone": self.location.get("timezone", "UTC"),
                "hourly": hourly_vars_full,
                "forecast_hours": forecast_hours,
            }

            try:
                response = client.weather_api(URL_OPENMETEO, params=params)[0]
                result = self._parse_extended_data(response, hourly_vars_full)
                logger.debug(
                    f"Open-Meteo API: Successfully fetched {forecast_hours}h astro weather data"
                    f" {location_str} (with jet stream)"
                )
                return result
            except Exception as full_error:
                # If full request fails (likely due to server load), retry with core variables
                if _is_openmeteo_concurrency_error(full_error):
                    raise  # Don't retry on concurrency errors, let main handler deal with it

                logger.warning("Full astro weather request failed, retrying with core variables only")
                params["hourly"] = hourly_vars_core

                try:
                    response = client.weather_api(URL_OPENMETEO, params=params)[0]
                    result = self._parse_extended_data(response, hourly_vars_core)
                    logger.debug(
                        f"Open-Meteo API: Successfully fetched {forecast_hours}h astro weather data"
                        f" {location_str} (core variables, jet stream uses estimations)"
                    )
                    return result
                except Exception:
                    # If both full and core requests fail, return None and let cache fallback handle it
                    logger.warning("Core astro weather request also failed - will use stale cache if available")
                    return None

        except Exception as e:
            if _is_openmeteo_concurrency_error(e):
                record_openmeteo_rate_limit()
                logger.warning("Open-Meteo API: CONCURRENCY LIMIT REACHED - Too many concurrent requests")
            elif _is_openmeteo_transient_error(e):
                logger.warning(f"Open-Meteo API: transient error fetching astro weather - {str(e)[:120]}")
            else:
                logger.warning(f"Open-Meteo API: unexpected error fetching astro weather - {str(e)[:120]}")
                logger.debug("Full traceback:", exc_info=True)
            return None

    def _parse_extended_data(self, response, hourly_vars: List[str]) -> Dict:
        """Parse the extended weather response into organized data structure"""
        hourly = response.Hourly()

        # Create time series
        dates = pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            periods=len(hourly.Variables(0).ValuesAsNumpy()),
            freq=pd.Timedelta(seconds=hourly.Interval()),
        )

        # Parse timezone
        timezone_str = response.Timezone()
        if isinstance(timezone_str, bytes):
            timezone_str = timezone_str.decode("utf-8")

        # Build data dictionary
        data = {"datetime": dates.tz_convert(timezone_str)}
        for i, var_name in enumerate(hourly_vars):
            data[var_name] = hourly.Variables(i).ValuesAsNumpy()

        df = pd.DataFrame(data)

        return {
            "location": {
                "name": self.location.get("name", "Unknown"),
                "latitude": response.Latitude(),
                "longitude": response.Longitude(),
                "elevation": response.Elevation(),
                "timezone": timezone_str,
            },
            "data": df,
        }

    def analyze_cloud_layers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze cloud altitude layers for astrophotography impact

        Returns:
        - cloud_discrimination: Quality score based on cloud layer analysis
        - high_cloud_impact: Impact of high clouds on imaging
        - mid_cloud_impact: Impact of mid clouds on imaging
        - low_cloud_impact: Impact of low clouds on imaging
        """
        result = df.copy()

        # Cloud layer analysis
        high_clouds = cast(pd.Series, result["cloud_cover_high"])
        mid_clouds = cast(pd.Series, result["cloud_cover_mid"])
        low_clouds = cast(pd.Series, result["cloud_cover_low"])

        # Cloud discrimination score (0-100%)
        # High clouds have least impact, low clouds have most impact.
        # Weighted average: result = sum(w_i * x_i) / sum(w_i), so each weight
        # is divided by 1.3 (= 0.3 + 0.4 + 0.6) to normalize to sum to 1.0.
        cloud_discrimination = (
            (100 - high_clouds) * (0.3 / 1.3)  # High clouds less problematic
            + (100 - mid_clouds) * (0.4 / 1.3)  # Mid clouds moderate impact
            + (100 - low_clouds) * (0.6 / 1.3)  # Low clouds worst for astronomy
        ).clip(0, 100)

        # Individual cloud layer impacts
        high_cloud_impact = self._calculate_cloud_impact(high_clouds, "high")
        mid_cloud_impact = self._calculate_cloud_impact(mid_clouds, "mid")
        low_cloud_impact = self._calculate_cloud_impact(low_clouds, "low")

        result["cloud_discrimination"] = cloud_discrimination.round(1)
        result["high_cloud_impact"] = high_cloud_impact
        result["mid_cloud_impact"] = mid_cloud_impact
        result["low_cloud_impact"] = low_cloud_impact

        return result

    def _calculate_cloud_impact(self, cloud_cover: pd.Series, layer_type: str) -> pd.Series:
        """Calculate specific impact of cloud layer on astrophotography"""
        impact_factors = {
            "high": 0.3,  # High clouds - cirrus, less impact
            "mid": 0.6,  # Mid clouds - altostratus, moderate impact
            "low": 1.0,  # Low clouds - cumulus/stratus, major impact
        }

        factor = impact_factors.get(layer_type, 1.0)

        # Convert cloud cover percentage to impact score
        impact = (cloud_cover * factor).clip(0, 100)

        return impact.round(1)

    def calculate_seeing_forecast(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate seeing forecast using Pickering scale (1-10)
        Based on wind speed, atmospheric stability, and jet stream effects
        """
        result = df.copy()

        # Wind factor (surface and upper level)
        surface_wind = cast(pd.Series, result["wind_speed_10m"])
        if "wind_speed_80m" in result:
            upper_wind_80m = cast(pd.Series, result["wind_speed_80m"]).fillna(surface_wind * 1.2)
        else:
            upper_wind_80m = surface_wind * 1.2

        # Wind seeing impact (lower is better for seeing)
        wind_seeing_score = self._wind_to_seeing_score(surface_wind, upper_wind_80m)

        # Atmospheric stability from lifted index
        stability_score = self._stability_to_seeing_score(cast(pd.Series, result["lifted_index"]))

        # Jet stream impact
        jet_stream_score = self._jet_stream_impact(
            cast(pd.Series, result.get("wind_speed_500hPa", surface_wind * 2)),
        )

        # Combined seeing score (Pickering scale 1-10)
        seeing_pickering = (wind_seeing_score * 0.4 + stability_score * 0.3 + jet_stream_score * 0.3).clip(1, 10)

        result["seeing_pickering"] = seeing_pickering.round(1)
        result["wind_seeing_component"] = wind_seeing_score.round(1)
        result["stability_seeing_component"] = stability_score.round(1)
        result["jetstream_seeing_component"] = jet_stream_score.round(1)

        return result

    def _wind_to_seeing_score(self, surface_wind: pd.Series, upper_wind: pd.Series) -> pd.Series:
        """Convert wind speeds to seeing score component"""
        # Average wind effect
        avg_wind = (surface_wind + upper_wind) / 2

        # Convert to Pickering scale component (1-10, higher = better seeing)
        # Calm conditions (0-5 km/h) = excellent seeing (8-10)
        # Light winds (5-15 km/h) = good seeing (6-8)
        # Moderate winds (15-25 km/h) = fair seeing (4-6)
        # Strong winds (25+ km/h) = poor seeing (1-4)

        seeing_score = np.where(
            avg_wind <= 5, 9, np.where(avg_wind <= 15, 7, np.where(avg_wind <= 25, 5, np.where(avg_wind <= 35, 3, 1)))
        )

        return pd.Series(seeing_score, index=surface_wind.index)

    def _stability_to_seeing_score(self, lifted_index: pd.Series) -> pd.Series:
        """Convert atmospheric stability (lifted index) to seeing score"""
        # Lifted Index interpretation:
        # > 2: Very stable (excellent seeing)
        # 0 to 2: Stable (good seeing)
        # -2 to 0: Slightly unstable (fair seeing)
        # < -2: Unstable (poor seeing)

        seeing_score = np.where(
            lifted_index > 2,
            9,
            np.where(lifted_index > 0, 7, np.where(lifted_index > -2, 5, np.where(lifted_index > -4, 3, 1))),
        )

        return pd.Series(seeing_score, index=lifted_index.index)

    def _jet_stream_impact(self, wind_500hpa: pd.Series) -> pd.Series:
        """Calculate jet stream impact on seeing conditions from 500 hPa wind speed."""
        # Strong jet stream winds indicate turbulence

        # Jet stream strength indicator
        jet_strength = wind_500hpa

        # Convert to seeing impact (1-10 scale)
        seeing_score = np.where(
            jet_strength <= 30,
            9,  # Weak jet stream = good seeing
            np.where(
                jet_strength <= 50,
                7,  # Moderate jet stream
                np.where(
                    jet_strength <= 80,
                    5,  # Strong jet stream
                    np.where(jet_strength <= 100, 3, 1),  # Very strong jet stream
                ),
            ),
        )

        return pd.Series(seeing_score, index=wind_500hpa.index)

    def calculate_transparency_forecast(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate transparency forecast with magnitude limit prediction
        Based on humidity, visibility, aerosols, and atmospheric conditions
        """
        result = df.copy()

        # Base factors for transparency
        humidity = cast(pd.Series, result["relative_humidity_2m"])
        visibility_m = cast(pd.Series, result["visibility"])

        # Humidity impact on transparency
        humidity_factor = self._humidity_to_transparency(humidity)

        # Visibility impact
        visibility_factor = self._visibility_to_transparency(visibility_m)

        # Atmospheric clarity (inverse of cloud cover)
        cloud_total = (
            result["cloud_cover_high"] * 0.3 + result["cloud_cover_mid"] * 0.6 + result["cloud_cover_low"] * 1.0
        ) / 1.9  # Normalize

        clarity_factor = (100 - cloud_total) / 100

        # Combined transparency score (0-100%)
        transparency_score = (humidity_factor * 0.4 + visibility_factor * 0.4 + clarity_factor * 0.2).clip(0, 100)

        # Convert to limiting magnitude
        magnitude_limit = self._transparency_to_magnitude_limit(transparency_score)

        result["transparency_score"] = transparency_score.round(1)
        result["limiting_magnitude"] = magnitude_limit.round(2)
        result["humidity_transparency"] = (humidity_factor * 100).round(1)
        result["visibility_transparency"] = (visibility_factor * 100).round(1)

        return result

    def _humidity_to_transparency(self, humidity: pd.Series) -> pd.Series:
        """Convert humidity percentage to transparency factor (0-1)"""
        # Lower humidity = better transparency
        # 30% humidity = excellent (1.0)
        # 50% humidity = good (0.8)
        # 70% humidity = fair (0.6)
        # 90% humidity = poor (0.2)

        transparency = np.where(
            humidity <= 30,
            1.0,
            np.where(humidity <= 50, 0.8, np.where(humidity <= 70, 0.6, np.where(humidity <= 85, 0.4, 0.2))),
        )

        return pd.Series(transparency, index=humidity.index)

    def _visibility_to_transparency(self, visibility_m: pd.Series) -> pd.Series:
        """Convert visibility distance to transparency factor (0-1)"""
        # Convert meters to km
        visibility_km = visibility_m / 1000

        # Visibility impact on transparency
        # 50+ km = excellent (1.0)
        # 30+ km = good (0.8)
        # 20+ km = fair (0.6)
        # 10+ km = poor (0.4)
        # <10 km = very poor (0.2)

        transparency = np.where(
            visibility_km >= 50,
            1.0,
            np.where(
                visibility_km >= 30, 0.8, np.where(visibility_km >= 20, 0.6, np.where(visibility_km >= 10, 0.4, 0.2))
            ),
        )

        return pd.Series(transparency, index=visibility_m.index)

    def _transparency_to_magnitude_limit(self, transparency_score: pd.Series) -> pd.Series:
        """Convert transparency score to limiting magnitude"""
        # Scale transparency score (0-100) to magnitude limit
        magnitude_range = MAGNITUDE_LIMIT_ZENITH_MAX - MAGNITUDE_LIMIT_ZENITH_MIN

        magnitude_limit = MAGNITUDE_LIMIT_ZENITH_MIN + (transparency_score / 100) * magnitude_range

        return magnitude_limit

    def analyze_dew_point_alerts(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze dew point conditions and generate alerts for astrophotography
        """
        result = df.copy()

        temperature = result["temperature_2m"]
        dew_point = result["dew_point_2m"]

        # Calculate temperature-dew point spread
        dew_point_spread = temperature - dew_point

        # Dew risk levels
        dew_risk = np.where(
            dew_point_spread <= 1,
            "CRITICAL",  # Dew formation imminent
            np.where(
                dew_point_spread <= 2,
                "HIGH",  # High risk of dew
                np.where(
                    dew_point_spread <= 4,
                    "MODERATE",  # Moderate risk
                    np.where(dew_point_spread <= 8, "LOW", "MINIMAL"),  # Low/minimal risk
                ),
            ),
        )

        # Dew risk score (0-100, higher = less risk)
        dew_risk_score = np.where(
            dew_point_spread <= 1,
            10,
            np.where(
                dew_point_spread <= 2, 30, np.where(dew_point_spread <= 4, 50, np.where(dew_point_spread <= 8, 70, 90))
            ),
        )

        result["dew_point_spread"] = dew_point_spread.round(1)
        result["dew_risk_level"] = dew_risk
        result["dew_risk_score"] = dew_risk_score

        return result

    def analyze_wind_tracking_impact(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze wind impact on telescope tracking and mount stability
        """
        result = df.copy()

        wind_speed = result["wind_speed_10m"]

        # Wind impact on tracking
        tracking_impact = np.where(
            wind_speed <= 5,
            "EXCELLENT",  # No impact
            np.where(
                wind_speed <= 10,
                "GOOD",  # Minimal impact
                np.where(
                    wind_speed <= 15,
                    "FAIR",  # Some impact
                    np.where(wind_speed <= 25, "POOR", "CRITICAL"),  # Significant impact  # Severe impact
                ),
            ),
        )

        # Tracking stability score (0-100)
        tracking_score = np.where(
            wind_speed <= 5,
            95,
            np.where(wind_speed <= 10, 80, np.where(wind_speed <= 15, 60, np.where(wind_speed <= 25, 30, 10))),
        )

        # Wind gusts estimation (simple model)
        estimated_gusts = wind_speed * 1.3

        result["wind_tracking_impact"] = tracking_impact
        result["tracking_stability_score"] = tracking_score
        result["estimated_wind_gusts"] = estimated_gusts.round(1)

        return result

    def analyze_precipitation_impact(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze precipitation impact on observation viability.

        Unlike the other components (seeing, transparency, cloud, tracking),
        rain isn't just "one factor among several" - it's a hard go/no-go
        signal, so it's applied as a multiplicative penalty on the composite
        score rather than averaged in like the rest.
        """
        result = df.copy()

        precipitation_mm = cast(pd.Series, result["precipitation"]).fillna(0)

        # 0 mm -> no penalty (factor 1.0); PRECIPITATION_VETO_MM+ -> fully vetoed (factor 0.0)
        precipitation_factor = (1.0 - (precipitation_mm / PRECIPITATION_VETO_MM).clip(0, 1)).round(2)

        result["precipitation_factor"] = precipitation_factor

        return result

    def generate_comprehensive_analysis(self, forecast_hours: int = 24) -> Optional[Dict]:
        """
        Generate comprehensive astrophotography weather analysis
        combining all advanced metrics
        """
        try:
            # Fetch extended weather data
            weather_data = self.fetch_extended_weather_data(forecast_hours)
            if not weather_data:
                # No weather data available - will trigger 202 pending response
                logger.warning("Could not fetch weather data")
                return None

            df = weather_data["data"]

            # Apply all analysis methods
            df = self.analyze_cloud_layers(df)
            df = self.calculate_seeing_forecast(df)
            df = self.calculate_transparency_forecast(df)
            df = self.analyze_dew_point_alerts(df)
            df = self.analyze_wind_tracking_impact(df)
            df = self.analyze_precipitation_impact(df)

            # Convert datetime for JSON serialization
            df_json = df.copy()
            dt_series = cast(pd.Series, pd.to_datetime(df_json["datetime"], errors="coerce"))
            df_json["datetime"] = dt_series.map(lambda x: x.strftime("%Y-%m-%dT%H:%M:%S%z") if pd.notna(x) else None)
            df_json["observation_score"] = (
                (
                    (
                        df_json["seeing_pickering"].fillna(0) * 10
                        + df_json["transparency_score"].fillna(0)
                        + df_json["cloud_discrimination"].fillna(0)
                        + df_json["tracking_stability_score"].fillna(0)
                    )
                    / 4
                    / 10
                )
                * df_json["precipitation_factor"].fillna(1.0)
            ).round(1)

            # Create summary statistics
            current_conditions = self._generate_current_summary(df.iloc[0] if len(df) > 0 else None)
            best_periods = self._find_best_observation_periods(df)
            alerts = self._generate_weather_alerts(df)

            return {
                "location": weather_data["location"],
                "generated_at": datetime.now().isoformat(),
                "forecast_hours": forecast_hours,
                "current_conditions": current_conditions,
                "best_observation_periods": best_periods,
                "weather_alerts": alerts,
                "hourly_data": df_json.to_dict(orient="records"),
            }

        except Exception:
            logger.exception("Failed to generate comprehensive analysis")
            return None

    @staticmethod
    def _observation_score(
        seeing: float, transparency: float, cloud: float, tracking: float, precipitation_factor: float = 1.0
    ) -> float:
        """0–10 composite observation quality score (canonical definition of the formula).

        ``precipitation_factor`` (0-1) multiplies the whole score - rain is a hard
        go/no-go signal, not just another averaged component. See
        ``analyze_precipitation_impact``.
        """
        return (((seeing * 10 + transparency + cloud + tracking) / 4) / 10) * precipitation_factor

    def _generate_current_summary(self, current_row: Optional[pd.Series]) -> Dict:
        """Generate summary of current conditions"""
        if current_row is None:
            return {"status": "No current data available"}

        seeing = float(cast(Any, current_row.get("seeing_pickering", 0)))
        transparency = float(cast(Any, current_row.get("transparency_score", 0)))
        cloud = float(cast(Any, current_row.get("cloud_discrimination", 0)))
        tracking = float(cast(Any, current_row.get("tracking_stability_score", 0)))
        precipitation_factor = float(cast(Any, current_row.get("precipitation_factor", 1.0)))

        return {
            "seeing_pickering": seeing,
            "transparency_score": transparency,
            "limiting_magnitude": float(cast(Any, current_row.get("limiting_magnitude", 0))),
            "cloud_discrimination": cloud,
            "dew_risk_level": current_row.get("dew_risk_level", "UNKNOWN"),
            "dew_point_spread": float(cast(Any, current_row.get("dew_point_spread", 0))),
            "wind_tracking_impact": current_row.get("wind_tracking_impact", "UNKNOWN"),
            "tracking_stability_score": tracking,
            "precipitation_factor": precipitation_factor,
            "observation_score": round(
                self._observation_score(seeing, transparency, cloud, tracking, precipitation_factor), 1
            ),
        }

    def _resolve_astronomical_night_window(self) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Resolve astronomical night bounds from this location's SkyTonight metadata."""
        try:
            from skytonight.skytonight_calculator import load_calculation_results

            analyzer_location = getattr(self, "location", None)
            calc = load_calculation_results(
                analyzer_location.get("id") if isinstance(analyzer_location, dict) else None
            )
            metadata = calc.get("metadata") or {}
            night_start = metadata.get("night_start")
            night_end = metadata.get("night_end")
            if not night_start or not night_end:
                return None

            start_ts = pd.to_datetime(night_start, errors="coerce")
            end_ts = pd.to_datetime(night_end, errors="coerce")
            if pd.isna(start_ts) or pd.isna(end_ts) or end_ts <= start_ts:
                return None

            return cast(pd.Timestamp, start_ts), cast(pd.Timestamp, end_ts)
        except Exception as error:
            logger.debug(f"Astronomical night window unavailable for astro weather filtering: {error}")
            return None

    def _infer_forecast_slot_hours(self, datetimes: pd.Series) -> float:
        """Infer sampling interval from forecast points (typically 1h)."""
        dt_series = cast(pd.Series, pd.to_datetime(datetimes, errors="coerce")).dropna().sort_values()
        if len(dt_series) < 2:
            return 1.0

        diffs = dt_series.diff().dropna().dt.total_seconds() / 3600.0
        positive_diffs = diffs[diffs > 0]
        if len(positive_diffs) == 0:
            return 1.0

        slot_hours = float(positive_diffs.median())
        if slot_hours <= 0:  # pragma: no cover
            return 1.0  # pragma: no cover

        # Clamp to a sane range to avoid outliers creating unrealistic durations.
        return max(0.25, min(slot_hours, 3.0))

    def _find_best_observation_periods(self, df: pd.DataFrame) -> List[Dict]:
        """Find the best periods for astrophotography within the forecast"""
        if len(df) == 0:
            return []

        working_df = df.copy()
        working_df["datetime"] = pd.to_datetime(working_df["datetime"], format="mixed", errors="coerce")
        working_df = working_df[working_df["datetime"].notna()].copy()
        if len(working_df) == 0:
            return []

        # Calculate overall quality score. Precipitation is a multiplicative veto (see
        # analyze_precipitation_impact) rather than a fifth averaged component - active
        # rain shouldn't be masked by otherwise-clear metrics when picking "best" periods.
        precipitation_factor = (
            working_df["precipitation_factor"] if "precipitation_factor" in working_df.columns else 1.0
        )
        working_df["overall_quality"] = (
            (
                working_df["seeing_pickering"] * 10  # Convert to percentage scale
                + working_df["transparency_score"]
                + working_df["cloud_discrimination"]
                + working_df["tracking_stability_score"]
            )
            / 4
        ) * precipitation_factor

        # Filter to only nighttime hours (is_day == 0)
        # This ensures we only consider periods when astronomical observation is possible
        nighttime_df = (
            working_df[working_df["is_day"] == 0].copy() if "is_day" in working_df.columns else working_df.copy()
        )

        # If SkyTonight provides astronomical night bounds, prefer them to reject twilight/daylight edge cases.
        night_window = self._resolve_astronomical_night_window()
        if night_window is not None:
            night_start, night_end = night_window
            nighttime_df = nighttime_df[
                (nighttime_df["datetime"] >= night_start) & (nighttime_df["datetime"] < night_end)
            ].copy()

        # Find periods with quality > 70%
        good_periods = cast(pd.DataFrame, nighttime_df[nighttime_df["overall_quality"] >= 70].copy())

        if len(good_periods) == 0:
            return []

        good_periods = good_periods.sort_values("datetime")
        slot_hours = self._infer_forecast_slot_hours(cast(pd.Series, good_periods["datetime"]))
        slot_delta = timedelta(hours=slot_hours)

        # Group consecutive good periods
        periods = []
        current_period_start = None
        current_period_last_slot = None
        current_period_qualities: List[float] = []

        def _finalize_current_period() -> None:
            if (
                current_period_start is None or current_period_last_slot is None or len(current_period_qualities) == 0
            ):  # pragma: no cover
                return  # pragma: no cover

            period_end = current_period_last_slot + slot_delta
            duration_hours = (period_end - current_period_start).total_seconds() / 3600.0
            periods.append(
                {
                    "start": current_period_start.isoformat(),
                    "end": period_end.isoformat(),
                    "duration_hours": round(duration_hours, 2),
                    "average_quality": round(float(np.mean(current_period_qualities)), 3),
                }
            )

        for _, row in good_periods.iterrows():
            row_dt = cast(pd.Timestamp, row["datetime"])
            row_quality = float(cast(Any, row["overall_quality"]))

            if current_period_start is None:
                current_period_start = row_dt
                current_period_last_slot = row_dt
                current_period_qualities = [row_quality]
            else:
                # Check if this row is consecutive to the previous
                time_diff = (row_dt - cast(pd.Timestamp, current_period_last_slot)).total_seconds() / 3600
                if time_diff <= (slot_hours * 1.5):
                    current_period_last_slot = row_dt
                    current_period_qualities.append(row_quality)
                else:
                    _finalize_current_period()
                    current_period_start = row_dt
                    current_period_last_slot = row_dt
                    current_period_qualities = [row_quality]

        # Don't forget the last period
        _finalize_current_period()

        # Hide periods that are too short to be practically useful for observation/imaging.
        periods = [
            period
            for period in periods
            if float(period.get("duration_hours", 0.0)) >= ASTRO_BEST_PERIOD_MIN_DURATION_HOURS
        ]

        # Sort by quality then by duration and return top 5
        periods.sort(key=lambda x: (x["average_quality"], x["duration_hours"]), reverse=True)
        return periods[:5]

    def _generate_weather_alerts(self, df: pd.DataFrame) -> List[Dict]:
        """Generate weather alerts for astrophotography conditions"""
        alerts = []

        if len(df) == 0:
            return alerts

        # Check next 6 hours for critical conditions
        next_6h = df.head(6)

        # Dew alerts
        critical_dew = next_6h[next_6h["dew_risk_level"] == "CRITICAL"]
        if len(critical_dew) > 0:
            alerts.append(
                create_translated_alert(
                    alert_type="DEW_WARNING",
                    severity="HIGH",
                    time=critical_dew.iloc[0]["datetime"].isoformat(),
                    language=self.language,
                )
            )

        # High wind alerts
        critical_wind = next_6h[next_6h["wind_tracking_impact"] == "CRITICAL"]
        if len(critical_wind) > 0:
            alerts.append(
                create_translated_alert(
                    alert_type="WIND_WARNING",
                    severity="HIGH",
                    time=critical_wind.iloc[0]["datetime"].isoformat(),
                    language=self.language,
                )
            )

        # Poor seeing alerts
        poor_seeing = next_6h[next_6h["seeing_pickering"] <= 3]
        if len(poor_seeing) > 0:
            alerts.append(
                create_translated_alert(
                    alert_type="SEEING_WARNING",
                    severity="MEDIUM",
                    time=poor_seeing.iloc[0]["datetime"].isoformat(),
                    language=self.language,
                )
            )

        # Low transparency alerts
        poor_transparency = next_6h[next_6h["transparency_score"] <= 30]
        if len(poor_transparency) > 0:
            alerts.append(
                create_translated_alert(
                    alert_type="TRANSPARENCY_WARNING",
                    severity="MEDIUM",
                    time=poor_transparency.iloc[0]["datetime"].isoformat(),
                    language=self.language,
                )
            )

        return alerts


def get_astro_weather_analysis(
    hours: int = 24, language: str = "en", location: Optional[Dict[str, Any]] = None
) -> Optional[Dict]:
    """
    Main function to get comprehensive astrophotography weather analysis.
    ``location`` is a v1.2 location preset; falls back to the install default.
    """
    location_id = (location or {}).get("id") or ""
    cache_key = _analysis_cache_key(hours, language, location_id)

    # Serve in-memory cache when data is still fresh - avoids hitting Open-Meteo on
    # every browser poll (e.g. weather-alerts polls every 5 minutes).
    last_success_ts = _ASTRO_ANALYSIS_LAST_SUCCESS_TS.get(cache_key, 0.0)
    if time.time() - last_success_ts < _ASTRO_ANALYSIS_CACHE_TTL:
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.debug(f"Serving cached astro weather analysis (TTL not expired) {cache_key}")
            return cached

    # Check shared Open-Meteo gate first: if ANY module recently hit the concurrency
    # limit, all callers back off together so they don't cycle out-of-phase.
    if is_openmeteo_rate_limited():
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.debug(f"Serving stale analysis (shared Open-Meteo rate limit active) {cache_key}")
            return cached
        logger.debug(f"Shared Open-Meteo rate limit active, no cache available {cache_key}")
        return None

    # If we failed recently, serve stale cache instead of hammering the API again
    last_failure = _ASTRO_ANALYSIS_LAST_FAILURE_TS.get(cache_key, 0.0)
    if time.time() - last_failure < _ASTRO_ANALYSIS_FAILURE_COOLDOWN:
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.debug(f"Serving stale analysis during failure cooldown {cache_key}")
            return cached
        logger.debug(f"In failure cooldown, no cache available {cache_key}")
        return None

    lock_acquired = _ASTRO_ANALYSIS_LOCK.acquire(blocking=False)
    if not lock_acquired:
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.debug(f"Using cached astro weather analysis (another request in progress): {cache_key}")
            return cached
        return None

    try:
        analyzer = AstroWeatherAnalyzer(language=language, location=location)
        analysis = analyzer.generate_comprehensive_analysis(hours)
        if analysis is not None:
            _store_last_successful_analysis(hours, language, analysis, location_id)
            # Clear any failure timestamp on success
            _ASTRO_ANALYSIS_LAST_FAILURE_TS.pop(cache_key, None)
            logger.debug(f"Fresh astro weather analysis retrieved successfully {cache_key}")
            return analysis

        # Fetch failed - record failure timestamp to trigger cooldown
        _ASTRO_ANALYSIS_LAST_FAILURE_TS[cache_key] = time.time()
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.warning(f"DEGRADED: Serving STALE astro weather analysis (fresh fetch failed) {cache_key}")
            return cached
        logger.error(f"CRITICAL: No astro weather analysis available (no cache, fetch failed) {cache_key}")
        return None
    except Exception as e:
        _ASTRO_ANALYSIS_LAST_FAILURE_TS[cache_key] = time.time()
        cached = _get_last_successful_analysis(hours, language, location_id)
        if cached is not None:
            logger.warning(
                f"DEGRADED: Serving STALE astro weather analysis (exception occurred) {cache_key}: {str(e)[:80]}"
            )
            logger.debug("Exception traceback:", exc_info=True)
            return cached
        logger.error(f"CRITICAL: No astro weather analysis available (exception, no cache) {cache_key}")
        logger.debug("Exception traceback:", exc_info=True)
        return None
    finally:
        _ASTRO_ANALYSIS_LOCK.release()


def get_current_astro_conditions(location: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    """
    Get current astrophotography conditions summary for a location preset
    """
    try:
        analyzer = AstroWeatherAnalyzer(location=location)
        analysis = analyzer.generate_comprehensive_analysis(1)
        if analysis:
            return analysis["current_conditions"]
        return None
    except Exception:
        logger.exception("Failed to get current astro conditions")
        return None
