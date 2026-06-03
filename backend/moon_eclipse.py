"""
Lunar Eclipse Service for Astrophotography

Provides:
- Next lunar eclipse
- Astrophotography score classification based on:
  - Type (Total, Partial, Penumbral)
  - Visibility from observer location
  - Duration of eclipse
  - Altitude at peak
- Eclipse timing in local time
- Altitude vs time graphic data
- Useful astrophotography information:
  - Visible from lat/lon
  - Peak local time
  - Type (penumbral / partial / total)
  - Time of maximum
  - Overall visibility
  - Altitude → height above horizon at peak
  - Duration → observation window

Example output:
{
  "lunar_eclipse": {
    "visible": true,
    "type": "Total",
    "peak_time": "2026-09-18 22:45:30",
    "partial_begin": "2026-09-18 20:15:00",
    "total_begin": "2026-09-18 21:30:00",
    "total_end": "2026-09-19 00:00:00",
    "partial_end": "2026-09-19 01:15:00",
    "peak_altitude_deg": 65.5,
    "peak_azimuth_deg": 180.2,
    "total_duration_minutes": 285,
    "partial_duration_minutes": 120,
    "astrophotography_score": 8.5,
    "score_classification": "Very good - Highly recommended",
    "altitude_vs_time": [
      {"time": "20:15", "altitude": 10.0, "azimuth": 120.0},
      ...
    ]
  }
}
"""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Any, Optional, List

from astronomy import SearchLunarEclipse, Time as AstronTime, Observer
from astropy.time import Time as AstroTime
from astropy.coordinates import EarthLocation, AltAz, get_body
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
class LunarEclipseInfo:
    visible: bool
    type: str
    peak_time: str
    partial_begin: str
    total_begin: Optional[str]
    total_end: Optional[str]
    partial_end: str
    peak_altitude_deg: float
    peak_azimuth_deg: float
    total_duration_minutes: int
    partial_duration_minutes: int
    astrophotography_score: float
    score_classification: str
    altitude_vs_time: List[EclipsePoint]


# =============================
# Service
# =============================

class LunarEclipseService:
    """Calculate lunar eclipse information for astrophotography"""

    def __init__(self, latitude: float, longitude: float, timezone: str):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.observer = Observer(latitude, longitude, 0)
        self.location = EarthLocation(
            lat=latitude * u.deg,
            lon=longitude * u.deg
        )

    # =============================
    # Public API
    # =============================

    def get_next_eclipse(self) -> Optional[LunarEclipseInfo]:
        """Get next lunar eclipse from now"""
        
        # astronomy.Time expects UTC time
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        t_start_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        t_start = AstronTime(t_start_str)

        # Search for next lunar eclipse
        eclipse = SearchLunarEclipse(t_start)
        if eclipse is None:
            return None

        # Convert peak time to local.
        # Time.Utc() returns a NAIVE datetime — attach UTC tzinfo before converting.
        peak_utc = eclipse.peak.Utc().replace(tzinfo=datetime.timezone.utc)
        peak_local = peak_utc.astimezone(self.timezone)

        # Convert eclipse times to local using semi-duration to calculate begin/end times
        # sd_penum, sd_partial, sd_total are in minutes
        peak_time_utc = eclipse.peak.Utc().replace(tzinfo=datetime.timezone.utc)
        
        # Calculate partial begin/end from sd_partial
        if eclipse.sd_partial > 0:
            delta_minutes = datetime.timedelta(minutes=eclipse.sd_partial)
            partial_begin_utc = peak_time_utc - delta_minutes
            partial_end_utc = peak_time_utc + delta_minutes
            partial_begin_local = partial_begin_utc.astimezone(self.timezone)
            partial_end_local = partial_end_utc.astimezone(self.timezone)
        else:
            # No partial phase, use penumbral instead
            delta_minutes = datetime.timedelta(minutes=eclipse.sd_penum)
            partial_begin_utc = peak_time_utc - delta_minutes
            partial_end_utc = peak_time_utc + delta_minutes
            partial_begin_local = partial_begin_utc.astimezone(self.timezone)
            partial_end_local = partial_end_utc.astimezone(self.timezone)

        # Total eclipse times (may be zero for partial/penumbral)
        if eclipse.sd_total > 0:
            delta_minutes = datetime.timedelta(minutes=eclipse.sd_total)
            total_begin_utc = peak_time_utc - delta_minutes
            total_end_utc = peak_time_utc + delta_minutes
            total_begin_local = total_begin_utc.astimezone(self.timezone)
            total_end_local = total_end_utc.astimezone(self.timezone)
            total_begin_str = self._fmt(total_begin_local)
            total_end_str = self._fmt(total_end_local)
        else:
            total_begin_str = None
            total_end_str = None
            total_begin_local = None
            total_end_local = None

        # Calculate altitude/azimuth at peak
        peak_alt_deg, peak_az_deg = self._get_moon_altitude_azimuth(peak_utc)

        # Determine eclipse type
        eclipse_type = self._get_eclipse_type(eclipse)

        # Check visibility
        visible = peak_alt_deg > 0

        # Calculate durations
        partial_duration = (partial_end_local - partial_begin_local).total_seconds() / 60
        partial_duration_minutes = int(partial_duration)

        if total_begin_local and total_end_local:
            total_duration = (total_end_local - total_begin_local).total_seconds() / 60
            total_duration_minutes = int(total_duration)
        else:
            total_duration_minutes = 0

        # Generate altitude vs time points
        altitude_vs_time = self._generate_altitude_vs_time(partial_begin_local, partial_end_local)

        # Calculate astrophotography score
        score, classification = self._calculate_astrophotography_score(
            eclipse_type, visible, peak_alt_deg, partial_duration_minutes, total_duration_minutes
        )

        return LunarEclipseInfo(
            visible=visible,
            type=eclipse_type,
            peak_time=self._fmt(peak_local),
            partial_begin=self._fmt(partial_begin_local),
            total_begin=total_begin_str,
            total_end=total_end_str,
            partial_end=self._fmt(partial_end_local),
            peak_altitude_deg=round(peak_alt_deg, 2),
            peak_azimuth_deg=round(peak_az_deg, 2),
            total_duration_minutes=total_duration_minutes,
            partial_duration_minutes=partial_duration_minutes,
            astrophotography_score=round(score, 1),
            score_classification=classification,
            altitude_vs_time=altitude_vs_time
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
        elif 'partial' in kind_name:
            return "Partial"
        else:
            return "Penumbral"

    def _get_moon_altitude_azimuth(self, dt_utc: datetime.datetime) -> tuple[float, float]:
        """Get moon's altitude and azimuth at given UTC time"""
        t_astropy = AstroTime(dt_utc)
        frame = AltAz(obstime=t_astropy, location=self.location)

        moon = get_body("moon", t_astropy)
        moon_transformed = moon.transform_to(frame)

        alt = self._coord_attribute(moon_transformed, "alt")
        az = self._coord_attribute(moon_transformed, "az")
        
        alt = alt if alt is not None else 0.0
        az = az if az is not None else 0.0
        return alt, az

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
        self,
        start_local: datetime.datetime,
        end_local: datetime.datetime
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

            moon = get_body("moon", t_astropy)
            moon_transformed = moon.transform_to(frame)

            alt = self._coord_attribute(moon_transformed, "alt")
            az = self._coord_attribute(moon_transformed, "az")
            
            alt = alt if alt is not None else 0.0
            az = az if az is not None else 0.0

            time_str = current.strftime("%H:%M")
            points.append(EclipsePoint(
                time=time_str,
                altitude_deg=round(alt, 1),
                azimuth_deg=round(az, 1)
            ))

            current += step

        return points

    def _calculate_astrophotography_score(
        self,
        eclipse_type: str,
        visible: bool,
        peak_altitude: float,
        partial_duration_minutes: int,
        total_duration_minutes: int
    ) -> tuple[float, str]:
        """
        Calculate astrophotography score (0-10) based on various factors.
        
        Scoring factors:
        - Type: Total (10) > Partial (7) > Penumbral (3)
        - Visibility: -5 if below horizon
        - Altitude at peak: Higher is better
        - Duration: Longer observation window is better
        - Total eclipse duration: If present, adds significant value
        """
        
        if not visible:
            return 0.0, "not_visible"

        eclipse_type_normalized = eclipse_type.strip().lower()

        # Base score from type
        if eclipse_type_normalized == "total":
            base_score = 10.0
        elif eclipse_type_normalized == "partial":
            base_score = 7.0
        else:  # Penumbral
            base_score = 3.0

        # Altitude bonus (0° to 90°)
        altitude_factor = peak_altitude / 90.0
        altitude_bonus = altitude_factor * 2.0  # Max +2 points

        # Duration factor for partial eclipse (min 0, max +1.5 for >180 minutes)
        duration_factor = min(partial_duration_minutes / 180.0, 1.0)
        duration_bonus = duration_factor * 1.5

        # Total duration bonus (if applicable)
        if total_duration_minutes > 0:
            total_duration_factor = min(total_duration_minutes / 100.0, 1.0)
            total_bonus = total_duration_factor * 1.0  # Max +1 for long total phase
        else:
            total_bonus = 0.0

        # Penalize if moon is very low
        if peak_altitude < 10:
            altitude_penalty = (10.0 - peak_altitude) * 0.15
        else:
            altitude_penalty = 0.0

        final_score = base_score + altitude_bonus + duration_bonus + total_bonus - altitude_penalty
        final_score = max(0.0, min(10.0, final_score))  # Clamp to 0-10

        # Classification
        if final_score >= 9.0:
            classification = "excellent"
        elif final_score >= 7.5:
            classification = "very_good"
        elif final_score >= 6.0:
            classification = "good"
        elif final_score >= 4.0:
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
