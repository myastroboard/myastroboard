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

import astropy.units as u
import numpy as np
from astroplan.moon import moon_illumination
from astropy.coordinates import AltAz, EarthLocation, get_body, get_sun
from astropy.time import Time

# Local hour at which a night's Moon illumination is reported. Solidly night-time
# and deliberately identical to the monthly phase calendar's sample hour
# (``astroweather.moon_calendar._SAMPLE_HOUR``) so the 7-night forecast, the target
# visibility calendar and the phase calendar never disagree for the same date. The
# altitude grid still spans 18:00 -> 06:00; only this illumination readout is pinned.
_ILLUMINATION_SAMPLE_HOUR = 23


def moon_illumination_percent(dt_local: datetime.datetime) -> float:
    """Moon illumination (%) at a given moment - a pure ephemeris computation, so
    unlike a weather forecast it works for any date, including ones in the past.

    Reused by Observation Log to record a night's moon condition (see
    observation/observation_sessions.py) - the same engine already powering this
    module's own 7-night dark-time forecast, so numbers stay consistent app-wide.
    """
    utc_dt = dt_local.astimezone(datetime.UTC)
    return float(moon_illumination(Time(utc_dt)) * 100)


def night_body_altitude_grid(
    latitude: float,
    longitude: float,
    timezone_name: str,
    night_date: datetime.date,
    step_minutes: int = 10,
) -> dict:
    """Vectorized Sun and Moon altitude over one night (18:00 local -> 06:00 next day).

    One Astropy ``AltAz`` transform per body over the whole time grid, matching the
    optimisation used by :meth:`MoonPlanner._night_data`. Shared with the target
    visibility calendar (``observation/visibility_calendar.py``) so all three consumers
    compute the night grid the same way instead of keeping separate copies.

    Args:
        latitude: Observer latitude in degrees.
        longitude: Observer longitude in degrees.
        timezone_name: IANA timezone name (e.g. ``"Europe/Paris"``).
        night_date: The calendar date the night starts on (evening).
        step_minutes: Sampling resolution in minutes.

    Returns:
        Dict with:
          - ``time``: Astropy ``Time`` array over the grid.
          - ``sun_alt_deg`` / ``moon_alt_deg``: numpy arrays of altitudes in degrees.
          - ``moon_illumination_pct``: Moon illumination (%) at ``_ILLUMINATION_SAMPLE_HOUR``
            (23:00) local on ``night_date`` - the same instant the monthly phase calendar
            samples, so the two never disagree for a given date.
    """
    tz = ZoneInfo(timezone_name)
    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    start = datetime.datetime.combine(night_date, datetime.time(18, 0), tzinfo=tz)
    end = datetime.datetime.combine(night_date + datetime.timedelta(days=1), datetime.time(6, 0), tzinfo=tz)
    illumination_instant = datetime.datetime.combine(night_date, datetime.time(_ILLUMINATION_SAMPLE_HOUR, 0), tzinfo=tz)
    step = datetime.timedelta(minutes=step_minutes)

    utc_times = []
    dt = start
    while dt <= end:
        utc_times.append(dt.astimezone(datetime.UTC))
        dt += step

    t_arr = Time(utc_times)
    frame = AltAz(obstime=t_arr, location=location)
    sun_alts = np.asarray(get_sun(t_arr).transform_to(frame).alt.deg)  # type: ignore[union-attr]
    moon_alts = np.asarray(get_body("moon", t_arr).transform_to(frame).alt.deg)  # type: ignore[union-attr]

    return {
        "time": t_arr,
        "sun_alt_deg": sun_alts,
        "moon_alt_deg": moon_alts,
        "moon_illumination_pct": moon_illumination_percent(illumination_instant),
    }


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
        step_minutes = 10
        grid = night_body_altitude_grid(
            self.latitude, self.longitude, str(self.timezone.key), date, step_minutes=step_minutes
        )
        sun_alts = grid["sun_alt_deg"]
        moon_alts = grid["moon_alt_deg"]

        # One representative illumination for the night, sampled at 23:00 local (it drifts
        # only ~0.5%/h, and this matches the monthly phase calendar's sample instant).
        illum_percent = grid["moon_illumination_pct"]
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
        return moon_illumination_percent(dt_local)

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
