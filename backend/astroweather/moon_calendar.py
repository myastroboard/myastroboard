"""Monthly Moon-phase calendar.

Pure ephemeris: for a given calendar month it returns, per day, the Moon's
illumination and waxing/waning state derived from the phase angle (same engine
and formula as the live Moon report), plus the exact local timestamps of that
month's principal phases (new / first quarter / full / last quarter).

Each day is sampled at a fixed night hour (23:00 local) - a calendar of Moon
phases is a night-observation planning aid, so every cell shows the Moon as it
is when you would actually be out under it, and every cell is sampled the same
way (no "now" special-casing). The 7-night dark-time forecast and the target
visibility calendar sample the same 23:00 instant (see
``astroweather.moon_planner._ILLUMINATION_SAMPLE_HOUR``), so those agree with
this calendar for a given date. This still differs slightly from the
#moon-display widget, which is a live "right now" readout; during the day the
two naturally disagree by a few percent and converge at night.

No location coordinates are needed, only the timezone, which is used to place
each phase instant on the correct local calendar day.

Example output (Europe/Paris, September 2026):
{
  "days": [
    {"date": "2026-09-01", "day": 1, "illumination_percent": 72.3,
     "waxing": false, "moonless": false, "phase_event": null},
    ...
    {"date": "2026-09-11", "day": 11, "illumination_percent": 0.3,
     "waxing": true, "moonless": true,
     "phase_event": {"type": "new", "time": "2026-09-11T05:27+02:00"}}
  ],
  "principal_phases": [
    {"type": "last_quarter", "date": "2026-09-04", "time": "2026-09-04T09:51+02:00"},
    {"type": "new", "date": "2026-09-11", "time": "2026-09-11T05:27+02:00"},
    ...
  ]
}
"""

import calendar
import datetime
import math
from zoneinfo import ZoneInfo

from astronomy import MoonPhase, NextMoonQuarter, SearchMoonQuarter, Time

# Astronomy Engine MoonQuarter.quarter -> phase name used by this module and i18n.
_QUARTER_TYPES = {0: "new", 1: "first_quarter", 2: "full", 3: "last_quarter"}

# Moon illumination below this percentage is treated as a "dark sky" night, matching
# the 'illumination' dark-window mode used elsewhere in the app (moon_planner).
MOONLESS_ILLUMINATION_THRESHOLD = 15.0

# Local hour each day is sampled at: solidly night-time, matching how this
# calendar is used (planning an observing session), and the same for every cell.
_SAMPLE_HOUR = 23


def _astro_time(dt_utc: datetime.datetime) -> Time:
    """Build an Astronomy Engine Time from a timezone-aware UTC datetime."""
    return Time.Make(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        dt_utc.hour,
        dt_utc.minute,
        dt_utc.second + dt_utc.microsecond / 1_000_000,
    )


def _illumination_percent(phase_angle_deg: float) -> float:
    """Illuminated fraction (%) from the Moon phase angle in degrees.

    Identical to MoonService.get_report(): 0 deg -> new (0%), 180 deg -> full (100%).
    """
    return (1 - math.cos(math.radians(phase_angle_deg))) / 2 * 100


def phase_at(instant: datetime.datetime) -> dict:
    """Moon phase state at a single instant.

    Uses the same engine and formula as MoonService.get_report() (Astronomy
    Engine ``MoonPhase`` -> ``(1 - cos(angle)) / 2``).

    Args:
        instant: A timezone-aware datetime.

    Returns:
        ``{"illumination_percent": <float, 1 dp>, "waxing": <bool>, "moonless": <bool>}``.
    """
    utc = instant.astimezone(datetime.UTC)
    angle = float(MoonPhase(_astro_time(utc)))
    illumination = round(_illumination_percent(angle), 1)
    return {
        "illumination_percent": illumination,
        "waxing": angle < 180,
        "moonless": illumination < MOONLESS_ILLUMINATION_THRESHOLD,
    }


def build_phase_calendar(year: int, month: int, timezone: str) -> dict:
    """Per-day Moon phase data for one calendar month.

    Args:
        year: Calendar year.
        month: Calendar month, 1-12.
        timezone: IANA timezone name, used to bucket phase instants into local days.

    Returns:
        A dict ``{"days": [...], "principal_phases": [...]}``. Each day is
        ``{date, day, illumination_percent, waxing, moonless, phase_event}`` where
        ``phase_event`` is ``None`` or ``{"type": <phase name>, "time": <local ISO>}``.
    """
    tz = ZoneInfo(timezone)
    days_in_month = calendar.monthrange(year, month)[1]

    # --- principal phases whose local date falls within the target month ---
    month_start_local = datetime.datetime(year, month, 1, tzinfo=tz)
    search_from_utc = (month_start_local - datetime.timedelta(days=2)).astimezone(datetime.UTC)

    principal_phases: list[dict] = []
    events_by_day: dict[int, dict] = {}
    quarter = SearchMoonQuarter(_astro_time(search_from_utc))
    while True:
        instant_local = quarter.time.Utc().replace(tzinfo=datetime.UTC).astimezone(tz)
        if (instant_local.year, instant_local.month) > (year, month):
            break
        if (instant_local.year, instant_local.month) == (year, month):
            phase_type = _QUARTER_TYPES[quarter.quarter]
            local_iso = instant_local.isoformat(timespec="minutes")
            events_by_day[instant_local.day] = {"type": phase_type, "time": local_iso}
            principal_phases.append({"type": phase_type, "date": instant_local.date().isoformat(), "time": local_iso})
        quarter = NextMoonQuarter(quarter)

    # --- per-day phase state, sampled at the same night hour for every day ---
    days: list[dict] = []
    for day in range(1, days_in_month + 1):
        night_local = datetime.datetime(year, month, day, _SAMPLE_HOUR, tzinfo=tz)
        event: dict | None = events_by_day.get(day)
        days.append(
            {
                "date": datetime.date(year, month, day).isoformat(),
                "day": day,
                **phase_at(night_local),
                "phase_event": event,
            }
        )

    return {"days": days, "principal_phases": principal_phases}
