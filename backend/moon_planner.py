"""
Moon Planner for Astrophotography

Provides next 7 nights dark-time forecast with 3 darkness modes:
- strict (Sun altitude < -18° AND Moon altitude < 0°) -> No moon on sky
- practical (Sun < -18° AND Moon altitude < 5°) -> Moon, but negligible
- illumination (Sun < -18° AND Moon illumination < 15%) -> Visible moon, but faint


Example output for a night (on API call):
{
  "date": "2026-01-30",
  "dark_hours": { # Total duration in hours during which the night is considered usable according to the mode.
    "strict": 5.3,
    "practical": 6.1,
    "illumination": 7.8
  },
  "moon": {
    "max_altitude": 12.4, # Maximum altitude of the Moon during the night (degrees)
    "illumination_percent": 6.2 # Maximum illumination percentage of the Moon during the night (%)
  },
  "astrophoto_score": 100,
  "units": {
    "dark_hours": "hours",
    "altitude": "degrees",
    "illumination": "percent"
  }
}

"""

import datetime
from zoneinfo import ZoneInfo

import numpy as np
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz, get_sun, get_body

from astroplan.moon import moon_illumination


class MoonPlanner:

    def __init__(self, latitude: float, longitude: float, timezone: str):

        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    # ============================================================
    # Public API
    # ============================================================

    def next_7_nights(self):
        return self.next_n_nights(7)

    def next_n_nights(self, n: int):

        today = datetime.datetime.now(self.timezone).date()
        results = []

        for i in range(n):
            date = today + datetime.timedelta(days=i)
            night = self._night_data(date)

            results.append(
                {
                    "date": str(date),
                    "dark_hours": {
                        "strict": round(night["hours_strict"], 2),
                        "practical": round(night["hours_practical"], 2),
                        "illumination": round(night["hours_illumination"], 2),
                    },
                    "moon": {
                        "max_altitude": round(night["moon_max_alt"], 1),
                        "illumination_percent": round(night["illumination"], 1),
                    },
                    "astrophoto_score": self._score(night["hours_strict"]),
                }
            )

        return results

    # ============================================================
    # Core computation
    # ============================================================

    def _night_data(self, date):
        """Compute all 3 darkness modes for one night in a single vectorized pass.

        Instead of calling _dark_hours 3 times (3 × 73 individual Astropy calls),
        we build an array of all time points and let Astropy transform the whole
        array at once.  That yields 2 vectorized calls (sun + moon) per night
        instead of 146 individual ones - ~50× fewer coordinate transforms.
        """
        start = datetime.datetime.combine(date, datetime.time(18, 0), tzinfo=self.timezone)
        end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(6, 0), tzinfo=self.timezone)

        step_minutes = 10
        step = datetime.timedelta(minutes=step_minutes)

        # Build array of UTC time points
        utc_times = []
        dt = start
        while dt <= end:
            utc_times.append(dt.astimezone(datetime.timezone.utc))
            dt += step

        # Single vectorized Astropy call per celestial body
        t_arr = Time(utc_times)
        frame = AltAz(obstime=t_arr, location=self.location)
        sun_alts = np.asarray(get_sun(t_arr).transform_to(frame).alt.deg)
        moon_alts = np.asarray(get_body("moon", t_arr).transform_to(frame).alt.deg)

        # Illumination is constant across the night (computed once)
        illum_percent = self._moon_illumination(start)
        moon_max_alt = float(np.max(moon_alts))

        astro_night = sun_alts < -18
        hours_strict = float(np.sum(astro_night & (moon_alts < 0)) * step_minutes / 60)
        hours_practical = float(np.sum(astro_night & (moon_alts < 5)) * step_minutes / 60)
        hours_illumination = float(np.sum(astro_night) * step_minutes / 60) if illum_percent < 15 else 0.0

        return {
            "hours_strict": hours_strict,
            "hours_practical": hours_practical,
            "hours_illumination": hours_illumination,
            "moon_max_alt": moon_max_alt,
            "illumination": illum_percent,
        }

    # ============================================================
    # Moon illumination (official astroplan)
    # ============================================================

    def _moon_illumination(self, dt_local):

        utc_dt = dt_local.astimezone(datetime.timezone.utc)
        t = Time(utc_dt)

        illum = moon_illumination(t) * 100
        return float(illum)

    # ============================================================
    # Simple astrophotography score
    # ============================================================

    def _score(self, strict_hours):

        if strict_hours >= 6:
            return 100
        elif strict_hours >= 4:
            return 80
        elif strict_hours >= 2:
            return 60
        elif strict_hours > 0:
            return 40
        return 10
