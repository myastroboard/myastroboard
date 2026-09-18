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

# Standard sunrise/sunset altitude of the Sun's centre: the upper limb sits on the
# horizon when the centre is 0.833° below it (34' mean refraction + 16' semidiameter).
# Twilight thresholds (-6/-12/-18°) are, by convention, geometric centre depressions
# and are intentionally NOT offset by this value.
SUN_STANDARD_ALTITUDE = -0.833

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
        start_local = datetime.datetime.combine(date, datetime.time(12, 0), self.timezone)
        # Anchor the sampling grid in UTC so a daylight-saving transition inside the
        # window cannot open a 1-hour gap in the wall-clock arithmetic.
        start_utc = start_local.astimezone(datetime.timezone.utc)
        n_steps = int(24 * 60 / step_minutes) + 1  # inclusive of both endpoints

        utc_times = [start_utc + datetime.timedelta(minutes=i * step_minutes) for i in range(n_steps)]
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
            i = int(indices[0])
            # Linearly interpolate between the two bracketing samples for the exact
            # crossing instant instead of snapping to the next sample (which biased
            # every result up to one step late).
            alt_before = float(sun_alts[i])
            alt_after = float(sun_alts[i + 1])
            span = alt_after - alt_before
            frac = 0.0 if span == 0 else (target_alt - alt_before) / span
            frac = min(1.0, max(0.0, frac))
            crossing_utc = start_utc + datetime.timedelta(minutes=(i + frac) * step_minutes)
            return crossing_utc.astimezone(self.timezone)

        # Sunrise/sunset use the standard -0.833° centre altitude (upper limb on the
        # horizon with mean refraction); twilights keep their -6/-12/-18° centre
        # depressions by convention.
        sunset = find_crossing(SUN_STANDARD_ALTITUDE, "down")
        sunrise = find_crossing(SUN_STANDARD_ALTITUDE, "up")
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


# -----------------------------
# Sky period from a cached report
# -----------------------------

SKY_PERIODS = (
    "day",
    "civil_twilight",
    "nautical_twilight",
    "astronomical_twilight",
    "astronomical_night",
    "unknown",
)


def determine_sky_period(sun_data, timezone_str: str) -> tuple:
    """
    Determine the current sky period from a ``sun_report`` cache payload.

    Returns ``(period, next_period, seconds_until_next)``. *period* is one of SKY_PERIODS;
    the report's naive local time strings ("YYYY-MM-DD HH:MM", or "Not found") are read in
    *timezone_str*. Shared by the sky widget route and the MQTT publisher.
    """
    if not sun_data or "sun" not in sun_data:
        return "unknown", "unknown", None

    sun = sun_data["sun"]
    try:
        tz = ZoneInfo(timezone_str)
    except Exception:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz=tz)

    def parse_dt(s):
        if not s or s == "Not found":
            return None
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            return None

    def secs(dt_end):
        return max(0, int((dt_end - now).total_seconds()))

    sunset = parse_dt(sun.get("sunset"))
    sunrise = parse_dt(sun.get("sunrise"))
    civil_dusk = parse_dt(sun.get("civil_dusk"))
    civil_dawn = parse_dt(sun.get("civil_dawn"))
    nautical_dusk = parse_dt(sun.get("nautical_dusk"))
    nautical_dawn = parse_dt(sun.get("nautical_dawn"))
    astro_dusk = parse_dt(sun.get("astronomical_dusk"))
    astro_dawn = parse_dt(sun.get("astronomical_dawn"))

    # Check from darkest to lightest
    if astro_dusk and astro_dawn and astro_dusk <= now <= astro_dawn:
        return "astronomical_night", "astronomical_dawn", secs(astro_dawn)
    if nautical_dusk and astro_dusk and nautical_dusk <= now < astro_dusk:
        return "astronomical_twilight", "astronomical_night", secs(astro_dusk)
    if astro_dawn and nautical_dawn and astro_dawn < now <= nautical_dawn:
        return "astronomical_twilight", "nautical_twilight", secs(nautical_dawn)
    if civil_dusk and nautical_dusk and civil_dusk <= now < nautical_dusk:
        return "nautical_twilight", "astronomical_twilight", secs(nautical_dusk)
    if nautical_dawn and civil_dawn and nautical_dawn < now <= civil_dawn:
        return "nautical_twilight", "civil_twilight", secs(civil_dawn)
    if sunset and civil_dusk and sunset <= now < civil_dusk:
        return "civil_twilight", "nautical_twilight", secs(civil_dusk)
    if civil_dawn and sunrise and civil_dawn < now <= sunrise:
        return "civil_twilight", "day", secs(sunrise)
    # Day: next is civil_dusk (via sunset)
    if sunset and now < sunset:
        return "day", "civil_twilight", secs(sunset)
    if civil_dusk and now < civil_dusk:
        return "day", "civil_twilight", secs(civil_dusk)
    return "day", "civil_twilight", None
