"""
Atmospheric Seeing Forecast from 7Timer
Provides seeing conditions for planetary imaging
https://www.7timer.info/
"""

import requests
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from logging_config import get_logger

logger = get_logger(__name__)

# 7Timer API endpoint (machine-readable)
SEEING_API_ENDPOINT = "https://www.7timer.info/bin/api.pl"

# Timeout for API requests
REQUEST_TIMEOUT = 10

# Seeing scale mapping (ASTRO product)
SEEING_SCALE = {
    1: {"label": "Excellent", "description": "< 0.5 arcsec", "conditions": "Perfect for planetary imaging"},
    2: {"label": "Very Good", "description": "0.5 - 0.75 arcsec", "conditions": "Excellent planetary detail"},
    3: {"label": "Good", "description": "0.75 - 1 arcsec", "conditions": "Very good for planetary imaging"},
    4: {"label": "Moderate", "description": "1 - 1.25 arcsec", "conditions": "Fair for planetary imaging"},
    5: {"label": "Fair", "description": "1.25 - 1.5 arcsec", "conditions": "Usable with reduced fine detail"},
    6: {"label": "Poor", "description": "1.5 - 2 arcsec", "conditions": "Poor conditions"},
    7: {"label": "Very Poor", "description": "2 - 2.5 arcsec", "conditions": "Unsuitable for high-resolution planetary imaging"},
    8: {"label": "Bad", "description": "> 2.5 arcsec", "conditions": "Unsuitable for planetary imaging"},
}


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
        Fetch seeing forecast for tonight from 7Timer
        
        Returns:
            Dictionary with seeing forecast data or None if fetch fails
            Structure:
            {
                "now": current_seeing_value,
                "now_description": "Moderate",
                "forecast": [
                    {
                        "time": "2024-01-15T20:00Z",
                        "seeing": 2,
                        "description": "Good",
                        "local_time": "21:00"
                    },
                    ...
                ],
                "best_window": {
                    "start": "2024-01-15T22:00Z",
                    "end": "2024-01-16T02:00Z",
                    "seeing": 1,
                    "duration_hours": 4
                }
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
                "init": init_str
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

                    # Keep all valid timepoints from the init, including past ones.
                    # Cutting at now_utc at cache time would discard the leading hours of
                    # today's forecast on every cache refresh, reducing day coverage.
                    # The frontend filters past points for display when needed.
                    iso_time = forecast_time.isoformat()
                    seeing_info = SEEING_SCALE.get(seeing_value, {})
                    forecast_list.append({
                        "time": iso_time,
                        "seeing": seeing_value,
                        "description": seeing_info.get("label", "Unknown"),
                        "conditions": seeing_info.get("conditions", "")
                    })
            
            if not forecast_list:
                logger.info("7Timer returned no usable seeing values for this location/time window")
                return {
                    "location": {
                        "latitude": self.latitude,
                        "longitude": self.longitude,
                        "timezone": self.timezone_str
                    },
                    "now": None,
                    "now_description": "Unavailable",
                    "forecast": [],
                    "best_window": None,
                    "message_key": "seeing_forecast.unavailable_no_usable_values",
                    "updated_at": now_utc.isoformat()
                }
            
            # Find current seeing: closest timepoint to now (not necessarily the first)
            current_point = min(
                forecast_list,
                key=lambda p: abs((datetime.fromisoformat(p["time"]) - now_utc).total_seconds())
            ) if forecast_list else None
            current_seeing = current_point["seeing"] if current_point else None
            current_description = current_point["description"] if current_point else "Unknown"
            
            # Find best window (longest consecutive period with seeing <= 3, i.e., Good or better)
            best_window = self._find_best_window(forecast_list)
            
            result = {
                "location": {
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "timezone": self.timezone_str
                },
                "now": current_seeing,
                "now_description": current_description,
                "forecast": forecast_list,
                "best_window": best_window,
                "updated_at": now_utc.isoformat()
            }
            
            logger.info(f"Successfully fetched seeing forecast from 7Timer (current: {current_description})")
            return result
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch seeing forecast from 7Timer: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing 7Timer seeing forecast: {e}")
            return None

    def _find_best_window(self, forecast_list: List[Dict]) -> Optional[Dict[str, Any]]:
        """
        Find the longest consecutive period with good seeing (<=2: Excellent or Good)
        
        Args:
            forecast_list: List of forecast points
        Returns:
            Dictionary with best window info or None if no good window found
        """
        if not forecast_list:
            return None
        
        best_duration = 0
        best_start = None
        best_seeing = None
        current_start = None
        current_seeing = None
        
        for i, point in enumerate(forecast_list):
            seeing = point["seeing"]
            time_str = point["time"]
            
            if seeing <= 3:  # Good or better
                if current_start is None:
                    current_start = time_str
                    current_seeing = seeing
                else:
                    # Track minimum seeing in this window
                    if seeing < current_seeing:
                        current_seeing = seeing
            else:
                # End of good window
                if current_start is not None:
                    # Calculate duration
                    start_idx = forecast_list.index(next(p for p in forecast_list if p["time"] == current_start))
                    end_idx = i - 1
                    duration_hours = (end_idx - start_idx + 1) * 3  # 7Timer ASTRO uses 3-hour steps
                    
                    if duration_hours > best_duration:
                        best_duration = duration_hours
                        best_start = current_start
                        best_seeing = current_seeing
                    
                    current_start = None
                    current_seeing = None
        
        # Check if last window extends to end
        if current_start is not None:
            start_idx = forecast_list.index(next(p for p in forecast_list if p["time"] == current_start))
            end_idx = len(forecast_list) - 1
            duration_hours = (end_idx - start_idx + 1) * 3
            
            if duration_hours > best_duration:
                best_duration = duration_hours
                best_start = current_start
                best_seeing = current_seeing
        
        if best_start and best_seeing is not None and best_duration >= 3:  # Only report windows of 3+ hours
            seeing_info = SEEING_SCALE.get(int(best_seeing), {})
            return {
                "start": best_start,
                "seeing": best_seeing,
                "description": seeing_info.get("label", "Unknown"),
                "conditions": seeing_info.get("conditions", ""),
                "duration_hours": best_duration
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
