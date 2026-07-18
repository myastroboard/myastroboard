"""
Solar Eclipse Service for Astrophotography

Provides:
- Next solar eclipse
- Astrophotography score classification based on:
  - Type (Total, Annular, Partial)
  - Visibility from observer location
  - Magnitude/Obscuration
  - Altitude at peak
- Eclipse timing in local time
- Altitude vs time graphic data
- Useful astrophotography information:
  - Visibility from lat/lon
  - Type → visual impact and rarity
  - Altitude → height above horizon at peak
  - Azimuth → direction for setting up
  - Obscuration → percentage of sun obscured
  - Duration → shooting window
  - Start, Peak, End times (local time)

Example output:
{
  "solar_eclipse": {
    "visible": true,
    "type": "Partial",
    "magnitude": 0.45,
    "obscuration_percent": 45.0,
    "peak_time": "2026-08-12 14:32:15",
    "start_time": "2026-08-12 13:05:00",
    "end_time": "2026-08-12 15:59:00",
    "peak_altitude_deg": 52.3,
    "peak_azimuth_deg": 180.2,
    "duration_minutes": 174,
    "astrophotography_score": 6.5,
    "score_classification": "Moderate interest",
    "altitude_vs_time": [
      {"time": "13:05", "altitude": 0.0, "azimuth": 90.0},
      ...
    ]
  }
}
"""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Any, Optional, List

from astronomy import SearchLocalSolarEclipse, Time as AstronTime, Observer
from astropy.time import Time as AstroTime
from astropy.coordinates import EarthLocation, AltAz, get_sun
import astropy.units as u

# =============================
# Data structures
# =============================


@dataclass
class EclipsePoint:
    """Data point for altitude vs time"""

    time: str  # "HH:MM" local time
    altitude_deg: float
    azimuth_deg: float


@dataclass
class SolarEclipseInfo:
    visible: bool
    type: str
    magnitude: float
    obscuration_percent: float
    peak_time: str
    start_time: str
    end_time: str
    peak_altitude_deg: float
    peak_azimuth_deg: float
    duration_minutes: int
    astrophotography_score: float
    score_classification: str
    altitude_vs_time: List[EclipsePoint]


# =============================
# Service
# =============================


class SolarEclipseService:
    """Calculate solar eclipse information for astrophotography"""

    def __init__(self, latitude: float, longitude: float, timezone: str):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.observer = Observer(latitude, longitude, 0)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    # =============================
    # Public API
    # =============================

    def get_next_eclipse(self) -> Optional[SolarEclipseInfo]:
        """Get next solar eclipse from now"""

        # astronomy.Time expects UTC time
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        t_start_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        t_start = AstronTime(t_start_str)

        # Search for next eclipse (astronomy-engine returns None if no eclipse in next ~18 months)
        eclipse = SearchLocalSolarEclipse(t_start, self.observer)
        if eclipse is None:
            return None

        # Convert peak time to local.
        # Time.Utc() returns a NAIVE datetime — attach UTC tzinfo before converting.
        peak_utc = eclipse.peak.time.Utc().replace(tzinfo=datetime.timezone.utc)
        peak_local = peak_utc.astimezone(self.timezone)

        # Convert eclipse times to local
        partial_begin_utc = eclipse.partial_begin.time.Utc().replace(tzinfo=datetime.timezone.utc)
        partial_begin_local = partial_begin_utc.astimezone(self.timezone)

        partial_end_utc = eclipse.partial_end.time.Utc().replace(tzinfo=datetime.timezone.utc)
        partial_end_local = partial_end_utc.astimezone(self.timezone)

        # Calculate altitude/azimuth at peak
        peak_alt_deg = eclipse.peak.altitude
        peak_alt_deg = max(peak_alt_deg, 0.0)  # Ensure non-negative for visible eclipses
        peak_az_deg = self._get_sun_azimuth(peak_utc)

        # Determine eclipse type
        eclipse_type = self._get_eclipse_type(eclipse)

        # Calculate magnitude and obscuration
        magnitude = eclipse.obscuration
        obscuration = magnitude * 100  # Convert to percentage

        # Check visibility
        visible = peak_alt_deg > 0

        # Calculate duration
        duration_seconds = (partial_end_local - partial_begin_local).total_seconds()
        duration_minutes = int(duration_seconds / 60)

        # Generate altitude vs time points
        altitude_vs_time = self._generate_altitude_vs_time(partial_begin_local, partial_end_local)

        # Calculate astrophotography score
        score, classification = self._calculate_astrophotography_score(
            eclipse_type, visible, obscuration, peak_alt_deg, duration_minutes
        )

        return SolarEclipseInfo(
            visible=visible,
            type=eclipse_type,
            magnitude=round(magnitude, 4),
            obscuration_percent=round(obscuration, 1),
            peak_time=self._fmt(peak_local),
            start_time=self._fmt(partial_begin_local),
            end_time=self._fmt(partial_end_local),
            peak_altitude_deg=round(peak_alt_deg, 2),
            peak_azimuth_deg=round(peak_az_deg, 2),
            duration_minutes=duration_minutes,
            astrophotography_score=round(score, 1),
            score_classification=classification,
            altitude_vs_time=altitude_vs_time,
        )

    # =============================
    # Core calculations
    # =============================

    def _get_eclipse_type(self, eclipse: Any) -> str:
        """Determine eclipse type from eclipse object"""
        # Check the eclipse kind
        kind_name = str(eclipse.kind).lower()

        if 'total' in kind_name:
            return "Total"
        elif 'annular' in kind_name:
            return "Annular"
        else:
            return "Partial"

    def _get_sun_azimuth(self, dt_utc: datetime.datetime) -> float:
        """Get sun's azimuth at given UTC time"""
        t_astropy = AstroTime(dt_utc)
        frame = AltAz(obstime=t_astropy, location=self.location)

        sun = get_sun(t_astropy)
        sun_transformed = sun.transform_to(frame)

        az = self._coord_attribute(sun_transformed, "az")
        return az if az is not None else 0.0

    def _coord_attribute(self, coord: Any, attr_name: str) -> Optional[float]:
        """Safely extract altitude or azimuth from transformed coordinate"""
        attr = getattr(coord, attr_name, None)
        if attr is None:
            return None
        try:
            value = attr.to_value(u.deg) if hasattr(attr, "to_value") else float(attr)
            return float(value)
        except (AttributeError, TypeError):
            return None

    def _generate_altitude_vs_time(
        self, start_local: datetime.datetime, end_local: datetime.datetime
    ) -> List[EclipsePoint]:
        """Generate altitude vs time points for the eclipse"""

        points = []

        # Generate points every 5 minutes
        current = start_local
        step = datetime.timedelta(minutes=5)

        while current <= end_local:
            current_utc = current.astimezone(datetime.timezone.utc)
            t_astropy = AstroTime(current_utc)
            frame = AltAz(obstime=t_astropy, location=self.location)

            sun = get_sun(t_astropy)
            sun_transformed = sun.transform_to(frame)

            alt = self._coord_attribute(sun_transformed, "alt")
            az = self._coord_attribute(sun_transformed, "az")

            alt = alt if alt is not None else 0.0
            az = az if az is not None else 0.0

            time_str = current.strftime("%H:%M")
            points.append(EclipsePoint(time=time_str, altitude_deg=round(alt, 1), azimuth_deg=round(az, 1)))

            current += step

        return points

    def _calculate_astrophotography_score(
        self, eclipse_type: str, visible: bool, obscuration: float, peak_altitude: float, duration_minutes: int
    ) -> tuple[float, str]:
        """
        Calculate astrophotography score (0-10) based on various factors.

        Scoring factors:
        - Type: Total (10) > Annular (8) > Partial (5)
        - Visibility: -5 if below horizon
        - Altitude at peak: Higher is better (0° = 0, 90° = full points)
        - Duration: Longer shooting window is better
        - Magnitude: Higher obscuration is better for partial/annular
        """

        if not visible:
            return 0.0, "not_visible"

        # Base score from type
        if eclipse_type == "Total":
            base_score = 10.0
        elif eclipse_type == "Annular":
            base_score = 8.0
        else:  # Partial
            base_score = 5.0

        # Altitude bonus/penalty (0° to 90°)
        altitude_factor = peak_altitude / 90.0
        altitude_bonus = altitude_factor * 2.0  # Max +2 points

        # Duration factor (min 0, max +1.5 for >150 minutes)
        duration_factor = min(duration_minutes / 150.0, 1.0)
        duration_bonus = duration_factor * 1.5

        # Magnitude factor for partial/annular
        if eclipse_type == "Partial":
            magnitude_bonus = (obscuration / 100.0) * 1.0  # Max +1
        elif eclipse_type == "Annular":
            magnitude_bonus = (obscuration / 100.0) * 1.0
        else:
            magnitude_bonus = 0.0

        # Penalize if sun is very low
        if peak_altitude < 10:
            altitude_penalty = (10.0 - peak_altitude) * 0.1
        else:
            altitude_penalty = 0.0

        final_score = base_score + altitude_bonus + duration_bonus + magnitude_bonus - altitude_penalty
        final_score = max(0.0, min(10.0, final_score))  # Clamp to 0-10

        # Classification
        if final_score >= 8.5:
            classification = "excellent"
        elif final_score >= 7.0:
            classification = "very_good"
        elif final_score >= 5.0:
            classification = "good"
        elif final_score >= 3.0:
            classification = "moderate"
        else:
            classification = "low"

        return final_score, classification

    # =============================
    # Formatting
    # =============================

    def _fmt(self, dt: datetime.datetime) -> str:
        """Format datetime to ISO format with local timezone"""
        return dt.isoformat(timespec='seconds')
