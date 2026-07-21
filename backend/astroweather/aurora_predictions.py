"""
Aurora Borealis Prediction System
Predicts aurora visibility based on geomagnetic activity (Kp index) and observer latitude.
Uses NOAA Space Weather Prediction Center data.
"""

import threading
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from utils.constants import CACHE_TTL, CACHE_TTL_AURORA
from utils.logging_config import get_logger

logger = get_logger(__name__)

# NOAA Space Weather API endpoints
NOAA_KP_API = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
NOAA_3DAY_FORECAST = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"

# Timeout for API requests
REQUEST_TIMEOUT = 10

# Kp index / forecast are global geomagnetic values with no location
# dimension, but the scheduler calls this module once per configured
# location. Cache the raw NOAA responses at module level (shared across every
# AuroraService instance) so N locations share one NOAA fetch per TTL window
# instead of each making their own live call - mirrors the shared-TLE /
# per-location-math split already used for ISS/CSS passes.
_kp_index_cache: Dict[str, Any] = {'value': None, 'timestamp': 0.0}
_kp_forecast_cache: Dict[str, Any] = {'value': None, 'timestamp': 0.0}

# Serialises the NOAA fetches so several locations refreshing in parallel share a
# single upstream call per TTL window instead of each issuing its own.
_KP_FETCH_LOCK = threading.Lock()

# Aurora best window hours (local time)
AURORA_BEST_WINDOW_START = 22
AURORA_BEST_WINDOW_END = 2


class AuroraService:
    """Service for aurora predictions and analysis"""

    def __init__(self, latitude: float, longitude: float, timezone_str: str):
        """
        Initialize aurora service with observer location

        Args:
            latitude: Observer latitude (-90 to 90)
            longitude: Observer longitude (-180 to 180)
            timezone_str: IANA timezone string (e.g., 'Europe/Paris')
        """
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_str = timezone_str

    def fetch_current_kp_index(self) -> Optional[float]:
        """
        Fetch current Kp index from NOAA API (shared across locations - see
        _kp_index_cache above)

        Returns:
            Latest Kp index value or None if fetch fails
        """
        now = time.monotonic()
        if _kp_index_cache['value'] is not None and (now - _kp_index_cache['timestamp']) < CACHE_TTL_AURORA:
            return _kp_index_cache['value']
        with _KP_FETCH_LOCK:
            # Re-check inside the lock: another location's parallel job may have just
            # populated the shared cache while we waited, avoiding a duplicate fetch.
            now = time.monotonic()
            if _kp_index_cache['value'] is not None and (now - _kp_index_cache['timestamp']) < CACHE_TTL_AURORA:
                return _kp_index_cache['value']
            try:
                response = requests.get(NOAA_KP_API, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list) and len(data) > 0:
                    latest = data[-1]
                    # New format: list of dicts with key 'Kp'
                    if isinstance(latest, dict):
                        raw = latest.get('Kp')
                    # Legacy format: list of lists, Kp at index 1
                    elif isinstance(latest, list) and len(latest) > 1:
                        raw = latest[1]
                    else:
                        raw = None

                    if raw is not None:
                        try:
                            kp_value = float(raw)
                            logger.debug(f"Fetched current Kp index: {kp_value}")
                            _kp_index_cache['value'] = kp_value
                            _kp_index_cache['timestamp'] = now
                            return kp_value
                        except (ValueError, TypeError):
                            logger.warning(f"Could not parse Kp value from {latest}")
                return None
            except requests.RequestException as e:
                logger.debug(f"Failed to fetch current Kp index from NOAA: {e}")
                return None
            except Exception as e:
                logger.error(f"Error fetching Kp index: {e}")
                return None

    def fetch_kp_forecast(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch 3-day Kp index forecast from NOAA

        Returns:
            List of forecast entries with timestamp and Kp value or None if fetch fails
        """
        now = time.monotonic()
        if _kp_forecast_cache['value'] is not None and (now - _kp_forecast_cache['timestamp']) < CACHE_TTL_AURORA:
            return _kp_forecast_cache['value']
        with _KP_FETCH_LOCK:
            # Re-check inside the lock: another location's parallel job may have just
            # populated the shared cache while we waited, avoiding a duplicate fetch.
            now = time.monotonic()
            if _kp_forecast_cache['value'] is not None and (now - _kp_forecast_cache['timestamp']) < CACHE_TTL_AURORA:
                return _kp_forecast_cache['value']
            try:
                response = requests.get(NOAA_3DAY_FORECAST, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                forecast_data = []

                # New format: list of dicts (key 'kp' lowercase)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    for row in data:
                        raw_kp = row.get('kp')
                        if raw_kp is None:
                            continue
                        try:
                            forecast_data.append({'timestamp': row.get('time_tag', ''), 'kp': float(raw_kp)})
                        except (TypeError, ValueError):
                            continue
                # Legacy format: list of lists with header row
                elif isinstance(data, list) and len(data) > 1 and isinstance(data[0], list):
                    header = data[0]
                    time_idx = header.index('time_tag') if 'time_tag' in header else None
                    kp_idx = next((i for i, h in enumerate(header) if str(h).lower() == 'kp'), None)

                    if kp_idx is not None:
                        for row in data[1:]:
                            if not isinstance(row, list) or len(row) <= kp_idx:
                                continue
                            try:
                                kp_value = float(row[kp_idx])
                            except (TypeError, ValueError):
                                continue
                            timestamp = ''
                            if time_idx is not None and len(row) > time_idx:
                                timestamp = row[time_idx]
                            forecast_data.append({'timestamp': timestamp, 'kp': kp_value})

                logger.debug(f"Fetched Kp forecast: {len(forecast_data)} entries")
                if forecast_data:
                    _kp_forecast_cache['value'] = forecast_data
                    _kp_forecast_cache['timestamp'] = now
                    return forecast_data
                return None
            except requests.RequestException as e:
                logger.debug(f"Failed to fetch Kp forecast from NOAA: {e}")
                return None
            except Exception as e:
                logger.error(f"Error fetching Kp forecast: {e}")
                return None

    def calculate_aurora_probability(self, kp_index: float) -> float:
        """
        Calculate aurora visibility probability based on Kp index and observer latitude

        Args:
            kp_index: Current geomagnetic Kp index (0-9)

        Returns:
            Aurora probability 0-100%
        """
        # Absolute latitude is used (aurora visible at both poles)
        abs_latitude = abs(self.latitude)

        # Base aurora oval extends from approximately 65-72 degrees magnetic latitude
        # Magnetic latitude differs from geographic, simplified here
        base_aurora_latitude = 67

        # Rule of thumb: Aurora oval expands equatorward when Kp is high
        # Each Kp increase lowers the aurora latitude by ~3-4 degrees
        aurora_edge_latitude = base_aurora_latitude - (kp_index * 3.5)

        # Positive distance means observer is poleward (inside) of the oval edge
        distance_from_edge = abs_latitude - aurora_edge_latitude

        if distance_from_edge >= 10:
            # Deep inside aurora oval
            probability = 25 + (kp_index * 7)
        elif distance_from_edge >= 0:
            # Inside near the edge
            probability = 15 + (kp_index * 6)
        elif distance_from_edge >= -5:
            # Just outside the oval edge
            probability = 5 + (kp_index * 4)
        else:
            # Far equatorward from the oval
            probability = max(0, (kp_index - 3) * 6)

        return max(0, min(100, probability))

    def get_probability_level(self, probability: float) -> str:
        """Translate probability into a user-friendly label."""
        if probability < 10:
            return "Very Low"
        if probability < 25:
            return "Low"
        if probability < 50:
            return "Moderate"
        if probability < 75:
            return "High"
        return "Very High"

    def get_aurora_score(self, kp_index: float, forecast_timestamp: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate comprehensive aurora visibility score

        Args:
            kp_index: Current geomagnetic Kp index (0-9)
            forecast_timestamp: ISO timestamp string from forecast (optional)

        Returns:
            Dictionary with aurora score and details
        """
        probability = self.calculate_aurora_probability(kp_index)
        probability_level = self.get_probability_level(probability)

        # Determine visibility level
        if kp_index < 3:
            visibility = "None"
            visibility_description = "No aurora activity expected"
        elif kp_index < 4:
            visibility = "Very Low"
            visibility_description = "Aurora possible only at very high latitudes"
        elif kp_index < 5:
            visibility = "Low"
            visibility_description = "Aurora possible at high latitudes"
        elif kp_index < 6:
            visibility = "Moderate"
            visibility_description = "Aurora likely at high latitudes"
        elif kp_index < 7:
            visibility = "Good"
            visibility_description = "Aurora likely visible across northern regions"
        elif kp_index < 8:
            visibility = "Excellent"
            visibility_description = "Aurora very likely, possibly at lower latitudes"
        else:
            visibility = "Severe Storm"
            visibility_description = "Intense aurora activity, visible at lower latitudes"

        # Get local timestamp for the report
        try:
            from zoneinfo import ZoneInfo

            tzinfo = ZoneInfo(self.timezone_str)
        except Exception:
            tzinfo = timezone.utc
        if forecast_timestamp:
            try:
                # NOAA timestamp is usually in ISO format and UTC
                dt_utc = datetime.fromisoformat(forecast_timestamp)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                local_timestamp = dt_utc.astimezone(tzinfo).isoformat()
            except Exception:
                local_timestamp = datetime.now(tzinfo).isoformat()
        else:
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(tzinfo)
            local_timestamp = now_local.isoformat()
        return {
            "kp_index": kp_index,
            "kp_index_max": 9,
            "probability": round(probability, 1),
            "probability_level": probability_level,
            "visibility_level": visibility,
            "visibility_description": visibility_description,
            "observer_latitude": self.latitude,
            "timestamp": local_timestamp,
            "best_viewing_window": {
                "start_hour": AURORA_BEST_WINDOW_START,
                "end_hour": AURORA_BEST_WINDOW_END,
                "description": (
                    f"{AURORA_BEST_WINDOW_START:02d}:00 - {AURORA_BEST_WINDOW_END:02d}:00"
                    " local time (best aurora activity period)"
                ),
            },
            "color_description": self._get_aurora_color_description(kp_index),
        }

    def _get_aurora_color_description(self, kp_index: float) -> Dict[str, str]:
        """
        Describe expected aurora colors based on Kp index and altitude

        Args:
            kp_index: Current geomagnetic Kp index

        Returns:
            Dictionary with color information
        """
        colors = {}

        # Green aurora (oxygen, 100-300 km) - most common
        colors["green"] = "Green (most common, 100-300 km altitude)"

        # Red aurora (high altitude oxygen, >300 km)
        if kp_index >= 4:
            colors["red"] = "Red (high altitude, >300 km, with strong activity)"

        # Blue/Purple aurora (nitrogen) - rare, only during severe storms
        if kp_index >= 8:
            colors["blue_purple"] = "Blue/Purple (nitrogen, rare, during severe storms)"

        # Pink/Magenta (high altitude mix)
        if kp_index >= 6:
            colors["pink"] = "Pink/Magenta (high altitude, during strong activity)"

        return colors

    def get_detailed_report(self) -> Optional[Dict[str, Any]]:
        """
        Generate comprehensive aurora report for observer location

        Returns:
            Detailed aurora report with current and forecast data
        """
        try:
            # Fetch current Kp index
            current_kp = self.fetch_current_kp_index()
            kp_forecast = None
            if current_kp is None:
                # Try forecast as a soft fallback before using a static default.
                kp_forecast = self.fetch_kp_forecast()
                if kp_forecast:
                    latest_kp = None
                    for entry in reversed(kp_forecast):
                        kp_value = entry.get('kp') if isinstance(entry, dict) else None
                        if kp_value is None:
                            continue
                        try:
                            latest_kp = float(kp_value)
                            break
                        except (TypeError, ValueError):
                            continue

                    if latest_kp is not None:
                        current_kp = latest_kp
                        logger.info(f"Current Kp unavailable; using forecast fallback Kp={current_kp}")

                if current_kp is None:
                    # Final fallback for NOAA outages.
                    current_kp = 3.0
                    logger.info("Current Kp unavailable; using default Kp index 3.0")

            # Calculate aurora score
            aurora_score = self.get_aurora_score(current_kp)

            # Convert timestamp to observer's local timezone
            try:
                from zoneinfo import ZoneInfo

                tzinfo = ZoneInfo(self.timezone_str)
            except Exception:
                tzinfo = timezone.utc
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(tzinfo)
            local_timestamp = now_local.isoformat()

            # Build report
            aurora_score["best_viewing_window"]["description"] = (
                f"{AURORA_BEST_WINDOW_START:02d}:00 - {AURORA_BEST_WINDOW_END:02d}:00"
                " local time (best aurora activity period)"
            )
            report = {
                "timestamp": local_timestamp,
                "location": {"latitude": self.latitude, "longitude": self.longitude, "timezone": self.timezone_str},
                "current": aurora_score,
                "forecast": [],
                "cache_ttl": CACHE_TTL,
            }

            # Try to fetch forecast
            if kp_forecast is None:
                kp_forecast = self.fetch_kp_forecast()
            if kp_forecast:
                try:
                    from zoneinfo import ZoneInfo

                    tzinfo = ZoneInfo(self.timezone_str)
                except Exception:
                    tzinfo = timezone.utc
                now_local = datetime.now(tzinfo)
                # Filter forecast entries to those after now
                filtered = []
                for entry in kp_forecast:
                    ts = entry.get('timestamp')
                    if isinstance(ts, str) and ts:
                        try:
                            dt_utc = datetime.fromisoformat(ts)
                            if dt_utc.tzinfo is None:
                                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                            dt_local = dt_utc.astimezone(tzinfo)
                            if dt_local > now_local:
                                filtered.append((dt_local, entry))
                        except Exception:
                            continue
                # Sort by local time and take next 8
                filtered = sorted(filtered, key=lambda x: x[0])[:8]
                for dt_local, entry in filtered:
                    kp_val = entry.get('kp', 0)
                    report["forecast"].append(self.get_aurora_score(kp_val, entry.get('timestamp')))

            logger.info(f"Generated aurora report for lat={int(self.latitude)}, lon={int(self.longitude)}, tz=***")
            return report

        except Exception as e:
            logger.error(f"Error generating aurora report: {e}")
            return None


def get_aurora_report(latitude: float, longitude: float, timezone_str: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get aurora report for a location

    Args:
        latitude: Observer latitude
        longitude: Observer longitude
        timezone_str: IANA timezone string

    Returns:
        Aurora report or None if failed
    """
    service = AuroraService(latitude, longitude, timezone_str)
    return service.get_detailed_report()
