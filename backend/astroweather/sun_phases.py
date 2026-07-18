"""
Sun Service for Astrophotography

Provides:
- Sunrise / Sunset
- Civil / Nautical / Astronomical twilight times
- Duration of true astronomical night


Example output (on API call):
{
  "sun": {
    "sunrise": "2026-01-29 08:12",
    "sunset": "2026-01-29 17:45",

    "civil_dusk": "2026-01-29 18:20",
    "civil_dawn": "2026-01-29 07:37",

    "nautical_dusk": "2026-01-29 18:55",
    "nautical_dawn": "2026-01-29 07:02",

    "astronomical_dusk": "2026-01-29 19:35",
    "astronomical_dawn": "2026-01-29 06:22",

    "true_night_hours": 10.78
  }
}

"""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
from astropy.time import Time as AstroTime
from astropy.coordinates import EarthLocation, AltAz, get_sun
import astropy.units as u

# -----------------------------
# Data structure
# -----------------------------


@dataclass
class SunAstroInfo:
    sunrise: str
    sunset: str

    civil_dusk: str
    civil_dawn: str

    nautical_dusk: str
    nautical_dawn: str

    astronomical_dusk: str
    astronomical_dawn: str

    true_night_hours: float


# -----------------------------
# Service
# -----------------------------


class SunService:

    def __init__(self, latitude, longitude, timezone):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    # -----------------------------
    # Public API
    # -----------------------------

    def get_today_report(self):

        today = datetime.date.today()
        return self._compute_day(today)

    def get_tomorrow_report(self):
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        return self._compute_day(tomorrow)

    # -----------------------------
    # Core calculation
    # -----------------------------

    def _compute_day(self, date):

        # Build a single array covering noon → next noon (5-min steps)
        # and run one vectorized Astropy call instead of 2304 individual ones.
        step_minutes = 5
        start = datetime.datetime.combine(date, datetime.time(12, 0), self.timezone)
        n_steps = int(24 * 60 / step_minutes) + 1  # inclusive of both endpoints

        utc_times = [
            (start + datetime.timedelta(minutes=i * step_minutes)).astimezone(datetime.timezone.utc)
            for i in range(n_steps)
        ]
        t_arr = AstroTime(utc_times)
        frame = AltAz(obstime=t_arr, location=self.location)
        sun_alts = np.asarray(get_sun(t_arr).transform_to(frame).alt.deg)  # type: ignore[union-attr]

        def find_crossing(target_alt, direction):
            if direction == "down":
                mask = (sun_alts[:-1] > target_alt) & (sun_alts[1:] <= target_alt)
            else:
                mask = (sun_alts[:-1] < target_alt) & (sun_alts[1:] >= target_alt)
            indices = np.nonzero(mask)[0]
            if len(indices) == 0:
                return None
            return start + datetime.timedelta(minutes=(int(indices[0]) + 1) * step_minutes)

        sunset = find_crossing(0, "down")
        sunrise = find_crossing(0, "up")
        civil_dusk = find_crossing(-6, "down")
        civil_dawn = find_crossing(-6, "up")
        nautical_dusk = find_crossing(-12, "down")
        nautical_dawn = find_crossing(-12, "up")
        astro_dusk = find_crossing(-18, "down")
        astro_dawn = find_crossing(-18, "up")

        night_hours = 0
        if astro_dusk and astro_dawn:
            night_hours = (astro_dawn - astro_dusk).total_seconds() / 3600

        return SunAstroInfo(
            sunrise=self._fmt(sunrise),
            sunset=self._fmt(sunset),
            civil_dusk=self._fmt(civil_dusk),
            civil_dawn=self._fmt(civil_dawn),
            nautical_dusk=self._fmt(nautical_dusk),
            nautical_dawn=self._fmt(nautical_dawn),
            astronomical_dusk=self._fmt(astro_dusk),
            astronomical_dawn=self._fmt(astro_dawn),
            true_night_hours=round(night_hours, 2),
        )

    def _sun_altitude(self, dt_local):
        """Return sun altitude in degrees at a single local datetime (used by tests)."""
        utc = dt_local.astimezone(datetime.timezone.utc)
        t = AstroTime(utc)
        frame = AltAz(obstime=t, location=self.location)
        return float(get_sun(t).transform_to(frame).alt.deg)  # type: ignore[union-attr, arg-type]

    # -----------------------------
    # Formatting
    # -----------------------------

    def _fmt(self, dt):

        if dt is None:
            return "Not found"

        return dt.strftime("%Y-%m-%d %H:%M")
