"""Full Moon details: supermoon, micromoon, Blue Moon and traditional name.

Pure ephemeris (Astronomy Engine, the engine already behind the Moon report and
the phase calendar). For each Full Moon instant it returns:

- the geocentric Earth-Moon distance and the apparent diameter it gives;
- ``supermoon`` / ``micromoon``, using Richard Nolle's definition: a Full Moon
  within 10% of the perigee (or apogee) distance of its own orbit. The orbit is
  bounded by the perigee and the apogee nearest to the Full Moon, both computed
  with ``SearchLunarApsis`` - so the thresholds follow the real orbit instead of a
  fixed number;
- ``blue_moon``: the second Full Moon of the same local calendar month;
- ``folk_name``: the North American traditional name (Farmer's Almanac): one per
  month, except the Harvest Moon (the Full Moon nearest the September equinox)
  and the Hunter's Moon (the one after it). These names are folklore, not a
  computation; only the Harvest / Hunter's placement is computed.

Example (Europe/Paris, 2026-11-24):
{
  "time": "2026-11-24T15:54+01:00", "date": "2026-11-24",
  "distance_km": 360754, "angular_diameter_arcmin": 33.1,
  "size_vs_mean_percent": 6.6, "supermoon": true, "micromoon": false,
  "blue_moon": false, "folk_name": "beaver"
}
"""

import datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

from astronomy import KM_PER_AU, ApsisKind, GeoMoon, NextLunarApsis, SearchLunarApsis, SearchMoonPhase, Seasons, Time

# Mean Earth-Moon distance (semi-major axis of the lunar orbit), NASA Moon fact sheet.
MEAN_DISTANCE_KM = 384_400.0
# Mean lunar radius, NASA Moon fact sheet.
MOON_RADIUS_KM = 1_737.4
# Nolle's definition: within 10% of the perigee-apogee range from the perigee (supermoon)
# or from the apogee (micromoon).
APSIS_FRACTION = 0.10

# Traditional name per local calendar month (Farmer's Almanac). September and October
# are overridden by the computed Harvest / Hunter's placement.
_FOLK_NAMES_BY_MONTH = {
    1: "wolf",
    2: "snow",
    3: "worm",
    4: "pink",
    5: "flower",
    6: "strawberry",
    7: "buck",
    8: "sturgeon",
    9: "corn",
    10: "hunters",
    11: "beaver",
    12: "cold",
}

# A synodic month is 29.3-29.8 days: searching 35 days back always lands on the previous one.
_PREVIOUS_FULL_MOON_LOOKBACK_DAYS = 35
# Half a synodic month plus a margin: the apsides bracketing a Full Moon lie inside it.
_APSIS_SEARCH_HALF_WINDOW_DAYS = 16


def _to_local(t: Time, tz: ZoneInfo) -> datetime.datetime:
    """Astronomy Engine Time (UTC, naive) -> aware local datetime."""
    return t.Utc().replace(tzinfo=datetime.UTC).astimezone(tz)


def _astro_time(dt: datetime.datetime) -> Time:
    """Aware datetime -> Astronomy Engine Time."""
    utc = dt.astimezone(datetime.UTC)
    return Time.Make(utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second + utc.microsecond / 1_000_000)


def _distance_km(t: Time) -> float:
    """Geocentric Earth-Moon centre distance (km) at ``t``."""
    return GeoMoon(t).Length() * KM_PER_AU


def _nearest_apsides(t: Time) -> tuple[float, float]:
    """Distances (km) of the perigee and the apogee nearest to ``t``."""
    perigee: tuple[float, float] | None = None  # (|dt| days, distance km)
    apogee: tuple[float, float] | None = None
    apsis = SearchLunarApsis(t.AddDays(-_APSIS_SEARCH_HALF_WINDOW_DAYS))
    while apsis.time.ut <= t.ut + _APSIS_SEARCH_HALF_WINDOW_DAYS:
        gap = abs(apsis.time.ut - t.ut)
        if apsis.kind == ApsisKind.Pericenter:
            if perigee is None or gap < perigee[0]:
                perigee = (gap, apsis.dist_km)
        elif apogee is None or gap < apogee[0]:
            apogee = (gap, apsis.dist_km)
        apsis = NextLunarApsis(apsis)
    # A 32-day window always holds at least one perigee and one apogee (anomalistic month ~27.6 d).
    assert perigee is not None and apogee is not None
    return perigee[1], apogee[1]


def _harvest_moon(year: int) -> Time:
    """The Full Moon nearest the September equinox of ``year``."""
    equinox = Seasons(year).sep_equinox
    first = SearchMoonPhase(180, equinox.AddDays(-16), 32)
    assert first is not None
    second = SearchMoonPhase(180, first.AddDays(1), 32)
    assert second is not None
    return first if abs(first.ut - equinox.ut) <= abs(second.ut - equinox.ut) else second


def _folk_name(t: Time, local: datetime.datetime) -> str:
    """Traditional name of the Full Moon at ``t`` (local datetime ``local``)."""
    harvest = _harvest_moon(local.year)
    if abs(t.ut - harvest.ut) < 1:
        return "harvest"
    hunters = SearchMoonPhase(180, harvest.AddDays(1), 32)
    if hunters is not None and abs(t.ut - hunters.ut) < 1:
        return "hunters"
    return _FOLK_NAMES_BY_MONTH[local.month]


def describe_full_moon(t: Time, timezone: str) -> dict[str, Any]:
    """All the details of the Full Moon at instant ``t``.

    Args:
        t: The Full Moon instant (from ``SearchMoonPhase(180, ...)``).
        timezone: IANA timezone, used for the local date, the Blue Moon month and the name.

    Returns:
        ``{time, date, distance_km, angular_diameter_arcmin, size_vs_mean_percent,
        supermoon, micromoon, blue_moon, folk_name}`` (see the module docstring).
    """
    tz = ZoneInfo(timezone)
    local = _to_local(t, tz)
    distance = _distance_km(t)
    perigee_km, apogee_km = _nearest_apsides(t)
    margin = APSIS_FRACTION * (apogee_km - perigee_km)

    previous = SearchMoonPhase(180, t.AddDays(-_PREVIOUS_FULL_MOON_LOOKBACK_DAYS), 30)
    blue_moon = False
    if previous is not None:
        previous_local = _to_local(previous, tz)
        blue_moon = (previous_local.year, previous_local.month) == (local.year, local.month)

    diameter_arcmin = math.degrees(2 * math.asin(MOON_RADIUS_KM / distance)) * 60
    return {
        "time": local.isoformat(timespec="minutes"),
        "date": local.date().isoformat(),
        "distance_km": round(distance),
        "angular_diameter_arcmin": round(diameter_arcmin, 1),
        "size_vs_mean_percent": round((MEAN_DISTANCE_KM / distance - 1) * 100, 1),
        "supermoon": distance <= perigee_km + margin,
        "micromoon": distance >= apogee_km - margin,
        "blue_moon": blue_moon,
        "folk_name": _folk_name(t, local),
    }


def upcoming_full_moons(start: datetime.datetime, count: int, timezone: str) -> list[dict[str, Any]]:
    """The next ``count`` Full Moons from ``start`` (aware datetime), with their details."""
    results: list[dict[str, Any]] = []
    search_from = _astro_time(start)
    for _ in range(count):
        t = SearchMoonPhase(180, search_from, 32)
        if t is None:
            break
        results.append(describe_full_moon(t, timezone))
        search_from = t.AddDays(1)
    return results
