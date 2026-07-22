"""
Atmospheric Seeing Forecast from 7Timer
Provides seeing conditions for planetary imaging
https://www.7timer.info/
"""

import requests
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from utils.logging_config import get_logger

logger = get_logger(__name__)

# 7Timer API endpoint (machine-readable)
SEEING_API_ENDPOINT = "https://www.7timer.info/bin/api.pl"

# Timeout for API requests
REQUEST_TIMEOUT = 10

# Seeing scale mapping (ASTRO product) - 1=best, 8=worst
SEEING_SCALE = {
    1: {"label": "Excellent", "description": "< 0.5 arcsec", "conditions": "Perfect for planetary imaging"},
    2: {"label": "Very Good", "description": "0.5 - 0.75 arcsec", "conditions": "Excellent planetary detail"},
    3: {"label": "Good", "description": "0.75 - 1 arcsec", "conditions": "Very good for planetary imaging"},
    4: {"label": "Moderate", "description": "1 - 1.25 arcsec", "conditions": "Fair for planetary imaging"},
    5: {"label": "Fair", "description": "1.25 - 1.5 arcsec", "conditions": "Usable with reduced fine detail"},
    6: {"label": "Poor", "description": "1.5 - 2 arcsec", "conditions": "Poor conditions"},
    7: {
        "label": "Very Poor",
        "description": "2 - 2.5 arcsec",
        "conditions": "Unsuitable for high-resolution planetary imaging",
    },
    8: {"label": "Bad", "description": "> 2.5 arcsec", "conditions": "Unsuitable for planetary imaging"},
}

# Transparency scale mapping (ASTRO product) - 1=worst, 8=best (mag per air mass)
TRANSPARENCY_SCALE = {
    1: {"label": "Very Poor", "description": "< 0.3 mag/airmass"},
    2: {"label": "Poor", "description": "0.3 - 0.4 mag/airmass"},
    3: {"label": "Below Average", "description": "0.4 - 0.5 mag/airmass"},
    4: {"label": "Average", "description": "0.5 - 0.6 mag/airmass"},
    5: {"label": "Above Average", "description": "0.6 - 0.7 mag/airmass"},
    6: {"label": "Good", "description": "0.7 - 0.85 mag/airmass"},
    7: {"label": "Very Good", "description": "0.85 - 1 mag/airmass"},
    8: {"label": "Excellent", "description": "> 1 mag/airmass"},
}

# Cloud cover scale mapping (ASTRO product) - 1=clearest, 9=fully overcast
CLOUDCOVER_SCALE = {
    1: {"label": "Clear", "description": "0 - 6%"},
    2: {"label": "Mostly Clear", "description": "6 - 19%"},
    3: {"label": "Mostly Clear", "description": "19 - 31%"},
    4: {"label": "Partly Cloudy", "description": "31 - 44%"},
    5: {"label": "Partly Cloudy", "description": "44 - 56%"},
    6: {"label": "Mostly Cloudy", "description": "56 - 69%"},
    7: {"label": "Mostly Cloudy", "description": "69 - 81%"},
    8: {"label": "Cloudy", "description": "81 - 94%"},
    9: {"label": "Overcast", "description": "94 - 100%"},
}

# Wind speed (10m) scale mapping (ASTRO product) - 1=calm, 8=hurricane
WIND_SPEED_SCALE = {
    1: {"label": "Calm", "description": "< 0.3 m/s"},
    2: {"label": "Light", "description": "0.3 - 3.4 m/s"},
    3: {"label": "Moderate", "description": "3.4 - 8.0 m/s"},
    4: {"label": "Fresh", "description": "8.0 - 10.8 m/s"},
    5: {"label": "Strong", "description": "10.8 - 17.2 m/s"},
    6: {"label": "Gale", "description": "17.2 - 24.5 m/s"},
    7: {"label": "Storm", "description": "24.5 - 32.6 m/s"},
    8: {"label": "Hurricane", "description": "> 32.6 m/s"},
}

# Composite quality score weights (must sum to 1.0). Seeing and transparency are
# 7Timer's own astronomy-specific model outputs (not proxies), so they carry the
# most weight; cloud cover is the next-strongest go/no-go signal; wind is a minor
# tracking-stability proxy.
QUALITY_WEIGHT_SEEING = 0.35
QUALITY_WEIGHT_TRANSPARENCY = 0.30
QUALITY_WEIGHT_CLOUD = 0.25
QUALITY_WEIGHT_WIND = 0.10

# Precipitation is a hard veto (not an averaged component), same convention as
# weather_astro.py's precipitation_factor: active rain/snow shouldn't be masked
# by otherwise-clear metrics.
PRECIPITATION_VETO_FACTOR = 0.1

# Quality label thresholds, shared with the Trend sub-tab's night-score-timeline
# (see static/js/weather_astro.js renderNightTimeline) so both tabs read consistently.
QUALITY_LABEL_THRESHOLDS = (
    (8, "Excellent"),
    (6, "Good"),
    (4, "Fair"),
    (2, "Poor"),
)
QUALITY_LABEL_DEFAULT = "Bad"


def _quality_label(score: float) -> str:
    """Map a 0-10 composite quality score to a label, matching night-score-timeline bins."""
    for threshold, label in QUALITY_LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return QUALITY_LABEL_DEFAULT


def _decode_rh2m_percent(rh2m: int) -> Optional[float]:
    """Convert 7Timer's coded relative humidity value (-4..16) to a midpoint percentage."""
    try:
        code = int(rh2m)
    except (TypeError, ValueError):
        return None
    # Each code step is a 5-point-wide band starting at -4 => 0-5%, midpoint 2.5%
    return round(max(0.0, min(100.0, (code + 4) * 5 + 2.5)), 1)


def _quality_component(value: Optional[int], scale_size: int, higher_raw_is_better: bool = False) -> float:
    """Convert a 1..N 7Timer scale value to a 0-10 quality component (10=best).

    Most 7Timer scales are 1=best (seeing, cloudcover, wind speed class), but
    ``transparency`` is the opposite (1=worst, N=best per 7Timer's own docs) - pass
    ``higher_raw_is_better=True`` for those.
    """
    if value is None:
        return 0.0
    if higher_raw_is_better:
        quality = (value - 1) / (scale_size - 1) * 10
    else:
        quality = (scale_size - value) / (scale_size - 1) * 10
    return max(0.0, min(10.0, quality))


class SeeingForecastService:
    """Service for atmospheric seeing forecast from 7Timer"""

    def __init__(self, latitude: float, longitude: float, timezone_str: str):
        """
        Initialize seeing forecast service with observer location

        Args:
            latitude: Observer latitude (-90 to 90)
            longitude: Observer longitude (-180 to 180)
            timezone_str: IANA timezone string (e.g., 'Europe/Paris')
        """
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_str = timezone_str

    def fetch_tonight_seeing(self) -> Optional[Dict[str, Any]]:
        """
        Fetch atmospheric forecast for tonight from 7Timer's ASTRO product.

        Parses every field 7Timer's ASTRO dataseries provides (seeing, transparency,
        cloud cover, wind, humidity, precipitation type) - not just seeing - and
        combines them into a single composite quality_score per timeslot.

        Returns:
            Dictionary with the forecast data or None if fetch fails
            Structure:
            {
                "now": current_seeing_value,
                "now_description": "Moderate",
                "now_quality_score": 7.2,
                "now_quality_label": "Good",
                "forecast": [
                    {
                        "time": "2024-01-15T20:00Z",
                        "seeing": 2,
                        "description": "Good",
                        "conditions": "...",
                        "transparency": 5,
                        "transparency_label": "Above Average",
                        "cloudcover": 2,
                        "cloudcover_label": "Mostly Clear",
                        "wind_speed_class": 3,
                        "wind_label": "Moderate",
                        "wind_direction": "NW",
                        "humidity_percent": 42.5,
                        "lifted_index": 2,
                        "prec_type": "none",
                        "quality_score": 7.2,
                        "quality_label": "Good",
                    },
                    ...
                ],
                "best_window": {...},          # composite quality_score-based window
                "best_seeing_window": {...},   # seeing-only window (unchanged meaning)
            }
        """
        try:
            # Get current UTC time
            now_utc = datetime.now(timezone.utc)

            # 7Timer API init timestamp format (YYYYMMDDHH)
            requested_init = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            init_str = requested_init.strftime("%Y%m%d%H")

            logger.debug(f"Fetching 7Timer seeing data (location redacted, init={init_str})")

            # Fetch from 7Timer API
            params = {
                "lon": self.longitude,
                "lat": self.latitude,
                "product": "astro",
                "output": "json",
                "init": init_str,
            }

            response = requests.get(SEEING_API_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if not data or "init" not in data or "dataseries" not in data:
                logger.warning("7Timer API returned unexpected format")
                return None

            # Extract forecast data
            dataseries = data["dataseries"]

            # Use API init if present to compute timepoint offsets accurately
            try:
                api_init = datetime.strptime(str(data.get("init", init_str)), "%Y%m%d%H").replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                api_init = requested_init

            if not dataseries:
                logger.debug("No seeing data available from 7Timer")
                return None

            # Build forecast list with local times
            forecast_list = []
            for point in dataseries:
                timepoint = point.get("timepoint")
                seeing = point.get("seeing")

                if timepoint is not None and seeing is not None:
                    # 7Timer astro timepoint is in hours since init
                    try:
                        forecast_time = api_init + timedelta(hours=float(timepoint))
                        seeing_value = int(seeing)
                    except (TypeError, ValueError):
                        continue

                    # Skip undefined entries from 7Timer (-9999)
                    if seeing_value < 1 or seeing_value > 8:
                        continue

                    entry = self._build_forecast_entry(forecast_time, seeing_value, point)
                    forecast_list.append(entry)

            if not forecast_list:
                logger.info("7Timer returned no usable seeing values for this location/time window")
                return {
                    "location": {"latitude": self.latitude, "longitude": self.longitude, "timezone": self.timezone_str},
                    "now": None,
                    "now_description": "Unavailable",
                    "now_quality_score": None,
                    "now_quality_label": "Unavailable",
                    "forecast": [],
                    "best_window": None,
                    "best_seeing_window": None,
                    "message_key": "seeing_forecast.unavailable_no_usable_values",
                    "updated_at": now_utc.isoformat(),
                }

            # Find current point: closest timepoint to now (not necessarily the first)
            current_point = min(
                forecast_list, key=lambda p: abs((datetime.fromisoformat(p["time"]) - now_utc).total_seconds())
            )
            current_seeing = current_point["seeing"]
            current_description = current_point["description"]
            current_quality_score = current_point["quality_score"]
            current_quality_label = current_point["quality_label"]

            # Best seeing-only window (unchanged meaning: seeing <= 3, i.e. Good or better)
            best_seeing_window = self._find_best_window(
                forecast_list, metric_key="seeing", threshold=3, higher_is_better=False
            )
            # Best overall window based on the composite quality score (>= 6, i.e. Good or better)
            best_window = self._find_best_window(
                forecast_list, metric_key="quality_score", threshold=6, higher_is_better=True
            )

            result = {
                "location": {"latitude": self.latitude, "longitude": self.longitude, "timezone": self.timezone_str},
                "now": current_seeing,
                "now_description": current_description,
                "now_quality_score": current_quality_score,
                "now_quality_label": current_quality_label,
                "forecast": forecast_list,
                "best_window": best_window,
                "best_seeing_window": best_seeing_window,
                "updated_at": now_utc.isoformat(),
            }

            logger.info(f"Successfully fetched seeing forecast from 7Timer (current: {current_description})")
            return result

        except requests.RequestException as e:
            logger.error(f"Failed to fetch seeing forecast from 7Timer: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing 7Timer seeing forecast: {e}")
            return None

    def _build_forecast_entry(
        self, forecast_time: datetime, seeing_value: int, point: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Decode every ASTRO field for one timepoint and compute its composite quality_score."""
        seeing_info = SEEING_SCALE.get(seeing_value, {})

        transparency_value = self._safe_int(point.get("transparency"))
        transparency_info = TRANSPARENCY_SCALE.get(transparency_value, {}) if transparency_value else {}

        cloudcover_value = self._safe_int(point.get("cloudcover"))
        cloudcover_info = CLOUDCOVER_SCALE.get(cloudcover_value, {}) if cloudcover_value else {}

        wind10m = point.get("wind10m") or {}
        wind_speed_value = self._safe_int(wind10m.get("speed")) if isinstance(wind10m, dict) else None
        wind_info = WIND_SPEED_SCALE.get(wind_speed_value, {}) if wind_speed_value else {}
        wind_direction = wind10m.get("direction") if isinstance(wind10m, dict) else None

        rh2m_value = self._safe_int(point.get("rh2m"))
        humidity_percent = _decode_rh2m_percent(rh2m_value) if rh2m_value is not None else None

        lifted_index = self._safe_int(point.get("lifted_index"))
        prec_type = point.get("prec_type") or "none"

        quality_score = self._compute_quality_score(
            seeing_value, transparency_value, cloudcover_value, wind_speed_value, prec_type
        )

        return {
            "time": forecast_time.isoformat(),
            "seeing": seeing_value,
            "description": seeing_info.get("label", "Unknown"),
            "conditions": seeing_info.get("conditions", ""),
            "transparency": transparency_value,
            "transparency_label": transparency_info.get("label", "Unknown"),
            "cloudcover": cloudcover_value,
            "cloudcover_label": cloudcover_info.get("label", "Unknown"),
            "wind_speed_class": wind_speed_value,
            "wind_label": wind_info.get("label", "Unknown"),
            "wind_direction": wind_direction,
            "humidity_percent": humidity_percent,
            "lifted_index": lifted_index,
            "prec_type": prec_type,
            "quality_score": quality_score,
            "quality_label": _quality_label(quality_score),
        }

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _compute_quality_score(
        seeing: int,
        transparency: Optional[int],
        cloudcover: Optional[int],
        wind_speed_class: Optional[int],
        prec_type: str,
    ) -> float:
        """0-10 composite quality score combining seeing, transparency, cloud cover and wind.

        Precipitation is a hard multiplicative veto rather than an averaged component
        (mirrors weather_astro.py's precipitation_factor convention): active rain/snow
        shouldn't be masked by otherwise-clear metrics.
        """
        seeing_quality = _quality_component(seeing, 8)
        # 7Timer's transparency scale is inverted relative to its other scales: 1=worst, 8=best.
        transparency_quality = _quality_component(transparency, 8, higher_raw_is_better=True)
        cloud_quality = _quality_component(cloudcover, 9)
        wind_quality = _quality_component(wind_speed_class, 8)

        score = (
            seeing_quality * QUALITY_WEIGHT_SEEING
            + transparency_quality * QUALITY_WEIGHT_TRANSPARENCY
            + cloud_quality * QUALITY_WEIGHT_CLOUD
            + wind_quality * QUALITY_WEIGHT_WIND
        )

        if prec_type and prec_type != "none":
            score *= PRECIPITATION_VETO_FACTOR

        return round(max(0.0, min(10.0, score)), 1)

    def _find_best_window(
        self, forecast_list: List[Dict], metric_key: str, threshold: float, higher_is_better: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Find the longest consecutive period where ``metric_key`` meets ``threshold``.

        Args:
            forecast_list: List of forecast points (each must contain ``metric_key``)
            metric_key: Which field to evaluate ("seeing" or "quality_score")
            threshold: Cutoff value a point must meet to count as part of a "good" window
            higher_is_better: True if values >= threshold are good (e.g. quality_score),
                False if values <= threshold are good (e.g. seeing, where 1 is best)
        Returns:
            Dictionary with best window info or None if no good window found
        """
        if not forecast_list:
            return None

        def is_good(value: float) -> bool:
            return value >= threshold if higher_is_better else value <= threshold

        def is_better(candidate: float, current_best: float) -> bool:
            return candidate > current_best if higher_is_better else candidate < current_best

        best_duration = 0
        best_start = None
        best_metric = None
        current_start = None
        current_metric = None

        for i, point in enumerate(forecast_list):
            value = point[metric_key]
            time_str = point["time"]

            if is_good(value):
                if current_metric is None:
                    current_start = time_str
                    current_metric = value
                else:
                    # Track the best value seen so far in this window
                    if is_better(value, current_metric):
                        current_metric = value
            else:
                # End of good window
                if current_start is not None:
                    start_idx = forecast_list.index(next(p for p in forecast_list if p["time"] == current_start))
                    end_idx = i - 1
                    duration_hours = (end_idx - start_idx + 1) * 3  # 7Timer ASTRO uses 3-hour steps

                    if duration_hours > best_duration:
                        best_duration = duration_hours
                        best_start = current_start
                        best_metric = current_metric

                    current_start = None
                    current_metric = None

        # Check if last window extends to end
        if current_start is not None:
            start_idx = forecast_list.index(next(p for p in forecast_list if p["time"] == current_start))
            end_idx = len(forecast_list) - 1
            duration_hours = (end_idx - start_idx + 1) * 3

            if duration_hours > best_duration:
                best_duration = duration_hours
                best_start = current_start
                best_metric = current_metric

        if best_start and best_metric is not None and best_duration >= 3:  # Only report windows of 3+ hours
            if metric_key == "seeing":
                scale_info = SEEING_SCALE.get(int(best_metric), {})
                return {
                    "start": best_start,
                    "seeing": best_metric,
                    "description": scale_info.get("label", "Unknown"),
                    "conditions": scale_info.get("conditions", ""),
                    "duration_hours": best_duration,
                }
            return {
                "start": best_start,
                "quality_score": best_metric,
                "quality_label": _quality_label(best_metric),
                "duration_hours": best_duration,
            }

        return None


def get_seeing_forecast(latitude: float, longitude: float, timezone_str: str) -> Optional[Dict[str, Any]]:
    """
    Get seeing forecast for the specified location

    Args:
        latitude: Observer latitude
        longitude: Observer longitude
        timezone_str: Timezone string

    Returns:
        Seeing forecast data or None if fetch fails
    """
    service = SeeingForecastService(latitude, longitude, timezone_str)
    return service.fetch_tonight_seeing()
