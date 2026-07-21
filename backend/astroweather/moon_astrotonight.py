"""
AstroTonightService

Computes the best astrophotography imaging window tonight.

Conditions:
- Sun altitude < -18° (astronomical night)
- Moon constraint depending on mode

Modes:
- strict      : Moon below horizon
- practical   : Moon altitude < 5°
- illumination: Moon illumination < 15%

Example output (on API call):
{
  "best_window": {
    "start": "2026-01-30 22:15",
    "end": "2026-01-31 04:40",
    "duration_hours": 6.42,
    "moon_condition": "strict",
    "score": 100
  }
}

"""

import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import Any, cast

import astropy.units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz, get_sun, get_body

from astroplan.moon import moon_illumination

# ============================================================
# Data structure
# ============================================================


@dataclass
class BestWindow:
    start: str
    end: str
    duration_hours: float
    moon_condition: str
    score: int


# ============================================================
# Main service
# ============================================================


class AstroTonightService:

    def __init__(self, latitude: float, longitude: float, timezone: str):

        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)

        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)

    # ============================================================
    # Public API
    # ============================================================

    def best_window_tonight(self, mode="strict") -> BestWindow:
        """
        Returns the best continuous imaging window tonight.
        """
        windows = self.best_windows_all_modes()
        return windows[mode]

    def best_windows_all_modes(self) -> dict:
        """
        Compute best windows for all three modes in a single vectorized Astropy pass.
        All altitudes for the full night grid are computed in one batch call instead
        of one AltAz frame per time-step, reducing frame constructions from O(N) to 1.
        Returns a dict keyed by mode: {'strict': BestWindow, 'practical': BestWindow, 'illumination': BestWindow}
        """
        now = datetime.datetime.now(self.timezone)
        # Before dawn we are still inside the night that began the previous evening,
        # so anchor the window there (otherwise a pre-dawn call would skip the
        # in-progress night and jump to the next evening); after 06:00 local, use
        # tonight's upcoming night.
        base_date = now.date() - datetime.timedelta(days=1) if now.hour < 6 else now.date()

        step_minutes = 5
        step = datetime.timedelta(minutes=step_minutes)

        # Night interval: 18:00 → 06:00 local
        start = datetime.datetime.combine(base_date, datetime.time(18, 0), tzinfo=self.timezone)
        end = datetime.datetime.combine(
            base_date + datetime.timedelta(days=1), datetime.time(6, 0), tzinfo=self.timezone
        )

        # Illumination computed once per night (used by 'illumination' mode)
        illumination = self._moon_illumination(start)

        # Build full time grid upfront
        times_local = []
        dt = start
        while dt <= end:
            times_local.append(dt)
            dt += step

        # Single vectorized Astropy pass: one AltAz frame for all N time steps
        times_utc = [t.astimezone(datetime.timezone.utc) for t in times_local]
        t_array = Time(times_utc)
        frame = AltAz(obstime=t_array, location=self.location)
        sun_alts = cast(Any, get_sun(t_array).transform_to(frame).alt).to_value(u.deg)
        moon_alts = cast(Any, get_body("moon", t_array).transform_to(frame).alt).to_value(u.deg)

        modes = ["strict", "practical", "illumination"]

        best_start = {m: None for m in modes}
        best_duration = {m: datetime.timedelta(0) for m in modes}
        current_start = {m: None for m in modes}

        def is_ok(mode, sun_alt, moon_alt):
            if sun_alt >= -18:
                return False
            if mode == "strict":
                return moon_alt < 0
            if mode == "practical":
                return moon_alt < 5
            return illumination < 15

        for i, dt in enumerate(times_local):
            sun_alt = float(sun_alts[i])
            moon_alt = float(moon_alts[i])

            for m in modes:
                ok = is_ok(m, sun_alt, moon_alt)
                if ok:
                    if current_start[m] is None:
                        current_start[m] = dt
                else:
                    cs = current_start[m]
                    if cs is not None:
                        duration = dt - cs
                        if duration > best_duration[m]:
                            best_duration[m] = duration
                            best_start[m] = cs
                        current_start[m] = None

        # Close any still-open windows at end of scan
        for m in modes:
            cs = current_start[m]
            if cs is not None:
                duration = end - cs
                if duration > best_duration[m]:
                    best_duration[m] = duration
                    best_start[m] = cs

        # Build result dict
        result = {}
        for m in modes:
            if best_start[m] is None:
                result[m] = BestWindow(
                    start="Not found",
                    end="Not found",
                    duration_hours=0,
                    moon_condition="unfavorable",
                    score=0,
                )
            else:
                bs = best_start[m]
                if bs is None:  # pragma: no cover
                    continue
                b_end = bs + best_duration[m]
                hours = best_duration[m].total_seconds() / 3600
                result[m] = BestWindow(
                    start=bs.strftime("%Y-%m-%d %H:%M"),
                    end=b_end.strftime("%Y-%m-%d %H:%M"),
                    duration_hours=round(hours, 2),
                    moon_condition=m,
                    score=self._score(hours),
                )

        return result

    # ============================================================
    # Moon illumination %
    # ============================================================

    def _moon_illumination(self, dt_local):

        utc_dt = dt_local.astimezone(datetime.timezone.utc)
        t = Time(utc_dt)

        illum = moon_illumination(t) * 100
        return float(illum)

    # ============================================================
    # Score function
    # ============================================================

    def _score(self, hours):

        if hours >= 6:
            return 100
        elif hours >= 4:
            return 85
        elif hours >= 2:
            return 65
        elif hours > 0:
            return 40
        return 10
