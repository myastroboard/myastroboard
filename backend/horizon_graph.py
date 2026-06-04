"""
Horizon Graph Service for Current Sun and Moon Positions

Provides altitude and azimuth data for sun and moon throughout the current day
for visualization on a horizon chart (altitude vs time).

Example output:
{
  "horizon_data": {
    "date": "2026-02-14",
    "sun_data": [
      {"hour": 0, "time": "00:00", "altitude_deg": -42.5, "azimuth_deg": 180.2},
      {"hour": 1, "time": "01:00", "altitude_deg": -41.3, "azimuth_deg": 185.5},
      ...
    ],
    "moon_data": [
      {"hour": 0, "time": "00:00", "altitude_deg": 15.2, "azimuth_deg": 120.5},
      ...
    ]
  }
}
"""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import List, Optional

from astropy.time import Time as AstroTime
from astropy.coordinates import EarthLocation, AltAz, get_sun, get_body
import astropy.units as u

# =============================
# Data structures
# =============================


@dataclass
class HorizonPoint:
    """Data point for horizon graph"""

    hour: int
    time: str  # "HH:MM" local time
    altitude_deg: float
    azimuth_deg: float


@dataclass
class HorizonGraphInfo:
    date: str  # "YYYY-MM-DD"
    sun_data: List[HorizonPoint]
    moon_data: List[HorizonPoint]


# =============================
# Service
# =============================


class HorizonGraphService:
    """Calculate sun and moon positions throughout the day for horizon visualization"""

    def __init__(self, latitude: float, longitude: float, timezone: str):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    # =============================
    # Public API
    # =============================

    def get_horizon_data(self) -> Optional[HorizonGraphInfo]:
        """Get sun and moon altitude/azimuth for current day (00:00 to 24:00)"""

        # Get current date in local timezone
        now_local = datetime.datetime.now(self.timezone)
        today = now_local.date()

        # Generate points for entire day: 00:00 to 24:00 (hourly)
        sun_data = self._generate_body_positions(today, "sun")
        moon_data = self._generate_body_positions(today, "moon")

        return HorizonGraphInfo(date=today.isoformat(), sun_data=sun_data, moon_data=moon_data)

    # =============================
    # Core calculations
    # =============================

    def _generate_body_positions(self, date: datetime.date, body: str) -> List[HorizonPoint]:
        """Generate altitude/azimuth positions for sun or moon for each hour of the day"""

        points = []

        # Generate points for each hour: 0, 1, 2, ..., 24 (includes midnight at end of day)
        for hour in range(25):
            # Handle hour 24 as 00:00 of next day
            if hour == 24:
                dt_local = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(0, 0, 0))
            else:
                # Create time at this hour in local timezone
                dt_local = datetime.datetime.combine(date, datetime.time(hour, 0, 0))

            dt_local = dt_local.replace(tzinfo=self.timezone)

            # Convert to UTC
            dt_utc = dt_local.astimezone(datetime.timezone.utc)

            # Create astropy Time object
            t_astropy = AstroTime(dt_utc)
            frame = AltAz(obstime=t_astropy, location=self.location)

            # Get body position
            if body.lower() == "sun":
                coord = get_sun(t_astropy)
            elif body.lower() == "moon":
                coord = get_body("moon", t_astropy, self.location)
            else:
                continue

            # Transform to AltAz frame
            coord_transformed = coord.transform_to(frame)

            # Extract altitude and azimuth
            alt = self._coord_attribute(coord_transformed, "alt")
            az = self._coord_attribute(coord_transformed, "az")

            alt = alt if alt is not None else 0.0
            az = az if az is not None else 0.0

            # Format time as "HH:MM", with hour 24 displayed as "24:00"
            if hour == 24:
                time_str = "24:00"
            else:
                time_str = dt_local.strftime("%H:%M")

            points.append(HorizonPoint(hour=hour, time=time_str, altitude_deg=round(alt, 1), azimuth_deg=round(az, 1)))

        return points

    def _coord_attribute(self, coord, attr_name: str) -> Optional[float]:
        """Safely extract altitude or azimuth from transformed coordinate"""
        attr = getattr(coord, attr_name, None)
        if attr is None:
            return None
        try:
            value = attr.to_value(u.deg) if hasattr(attr, "to_value") else float(attr)
            return float(value)
        except (AttributeError, TypeError):
            return None
