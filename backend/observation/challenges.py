"""Challenges (v1.9) - short target lists generated from real visibility at the user's site.

Never a dated list written by hand: every challenge is recomputed from the SkyTonight
dataset and the ephemeris of the active location, so it is right for the observer's
latitude and horizon and never goes stale.

* **Seasonal challenges** - "the galaxies / nebulae / clusters of this season": the
  brightest Messier and Caldwell objects of that class that clear the SkyTonight altitude
  constraints during astronomical darkness on the season's sampled nights.
* **Messier marathon** - the night closest to the March new moon, the order in which the
  Messier objects can be caught that night from this site, and how many of them are
  reachable at all. Not every latitude can see all of them; the count says so.
* **Missing tonight** - the objects of a catalogue the user has not captured yet that are
  observable tonight, for the "next within reach" links.

The ephemeris work reuses the visibility calendar's night grid (one Sun/Moon grid per night,
every target folded through it analytically), and results are kept in small bounded
in-process caches keyed on the location's geometry: they change once a season at most.
"""

from __future__ import annotations

import datetime
from collections import OrderedDict
from collections.abc import Collection, Sequence
from typing import Any
from zoneinfo import ZoneInfo

import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time

from astroweather.moon_calendar import phase_at
from observation import achievements, visibility_calendar
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Catalogues a seasonal challenge draws from: the well-known, completable sets.
CHALLENGE_CATALOGUES: tuple[str, ...] = ('Messier', 'Caldwell')
CHALLENGE_CLASSES: tuple[str, ...] = (achievements.CLASS_GALAXY, achievements.CLASS_NEBULA, achievements.CLASS_CLUSTER)
CHALLENGE_SIZE = 8
# Fewer targets than this and the class is not offered as a challenge this season.
CHALLENGE_MIN_TARGETS = 3
# A target must be observable at least this long on one sampled night to be proposed.
CHALLENGE_MIN_HOURS = 1.5

# Seasons by meteorological index (see achievements.season_index), per hemisphere.
_SEASON_MONTHS: tuple[tuple[int, int, int], ...] = ((12, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11))
_SEASON_NAMES_NORTH = ('winter', 'spring', 'summer', 'autumn')
_SEASON_NAMES_SOUTH = ('summer', 'autumn', 'winter', 'spring')

# Messier marathon: the search window for its night, the lowest altitude a marathoner
# works down to (well under the imaging constraint - a marathon is visual and goes low),
# and the Sun altitude that ends twilight enough to start (nautical).
MARATHON_SEARCH_START = (3, 1)
MARATHON_SEARCH_END = (4, 15)
MARATHON_SHOWN_UNTIL = (4, 15)
MARATHON_HIGHLIGHT_FROM = (2, 1)
MARATHON_MIN_ALTITUDE = 10.0
MARATHON_SUN_ALTITUDE = -12.0
_MARATHON_STEP_MINUTES = 10
_MARATHON_GRID_START_HOUR = 16
_MARATHON_GRID_END_HOUR = 10
# A lunation's darkest night is only a marathon candidate below this illumination.
_MARATHON_MAX_ILLUMINATION = 15.0

_MAX_CACHE_ENTRIES = 16
_season_cache: OrderedDict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = OrderedDict()
_marathon_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()


def clear_caches() -> None:
    """Drop the challenge caches (used by tests)."""
    _season_cache.clear()
    _marathon_cache.clear()


def _remember(cache: OrderedDict, key: Any, value: Any) -> Any:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _MAX_CACHE_ENTRIES:
        cache.popitem(last=False)
    return value


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------


def current_season(today: datetime.date, latitude: float | None) -> dict[str, Any]:
    """The season *today* falls in at *latitude*, with the three nights it is sampled on.

    The sampled nights are the 15th of each of the season's months, so a season's list is
    the same on every day of that season.
    """
    index = achievements.season_index(today.isoformat())
    index = 0 if index is None else index
    southern = latitude is not None and latitude < 0
    months = _SEASON_MONTHS[index]
    # A winter (Dec-Feb) season started in the previous calendar year when we are in Jan/Feb.
    start_year = today.year - 1 if index == 0 and today.month in (1, 2) else today.year
    nights = []
    for month in months:
        year = start_year if month >= months[0] else start_year + 1
        nights.append(datetime.date(year, month, 15))
    return {
        'index': index,
        'name': (_SEASON_NAMES_SOUTH if southern else _SEASON_NAMES_NORTH)[index],
        'hemisphere': 'south' if southern else 'north',
        'start_year': start_year,
        'nights': nights,
    }


def _season_candidates() -> list[dict[str, Any]]:
    """Messier and Caldwell objects with coordinates, once each."""
    seen: set[str] = set()
    candidates = []
    for catalogue in CHALLENGE_CATALOGUES:
        for member in achievements.catalogue_members(catalogue):
            if member['target_id'] in seen or member['ra_deg'] is None or member['dec_deg'] is None:
                continue
            if member['object_class'] not in CHALLENGE_CLASSES:
                continue
            seen.add(member['target_id'])
            candidates.append({**member, 'catalogue': catalogue})
    return candidates


def _season_lists(location: dict[str, Any], season: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Per class, the season's best targets at *location* (cached per season and site)."""
    cache_key = (visibility_calendar.location_cache_signature(location), season['index'], season['start_year'])
    cached = _season_cache.get(cache_key)
    if cached is not None:
        _season_cache.move_to_end(cache_key)
        return cached

    alt_min, alt_max = visibility_calendar.observing_constraints()
    _lat, _lon, _tz, horizon_profile = visibility_calendar.location_geometry(location)
    contexts = []
    for night in season['nights']:
        try:
            contexts.append(visibility_calendar.night_context_for(location, night))
        except Exception as error:
            logger.warning(f'Seasonal challenge sample failed for {night}: {error}')
    if not contexts:
        return {}

    by_class: dict[str, list[dict[str, Any]]] = {name: [] for name in CHALLENGE_CLASSES}
    for candidate in _season_candidates():
        best_hours = 0.0
        best_night = None
        for context in contexts:
            sample = visibility_calendar.sample_target_in_context(
                context, candidate['ra_deg'], candidate['dec_deg'], alt_min, alt_max, horizon_profile
            )
            if sample['observable_hours'] > best_hours:
                best_hours = sample['observable_hours']
                best_night = sample['date']
        if best_hours < CHALLENGE_MIN_HOURS:
            continue
        by_class[candidate['object_class']].append(
            {
                'target_id': candidate['target_id'],
                'name': candidate['identifier'],
                'preferred_name': candidate['preferred_name'],
                'object_type': candidate['object_type'],
                'constellation': candidate['constellation'],
                'magnitude': candidate['magnitude'],
                'catalogue': candidate['catalogue'],
                'observable_hours': round(best_hours, 1),
                'best_sampled_night': best_night,
            }
        )

    for rows in by_class.values():
        # Brightest first: the most accessible targets make the best checklist.
        rows.sort(key=lambda row: (row['magnitude'] is None, row['magnitude'] or 0.0, -row['observable_hours']))
        del rows[CHALLENGE_SIZE:]
    return _remember(_season_cache, cache_key, by_class)


def seasonal_challenges(
    location: dict[str, Any],
    today: datetime.date,
    captured_keys: Collection[str],
) -> dict[str, Any]:
    """The season's challenges at *location*, each target marked captured or not."""
    season = current_season(today, _latitude(location))
    lists = _season_lists(location, season)
    challenges = []
    for object_class in CHALLENGE_CLASSES:
        rows = lists.get(object_class) or []
        if len(rows) < CHALLENGE_MIN_TARGETS:
            continue
        targets = [{**row, 'captured': row['target_id'] in captured_keys} for row in rows]
        challenges.append(
            {
                'id': f'season_{object_class}',
                'object_class': object_class,
                'targets': targets,
                'captured': sum(1 for target in targets if target['captured']),
                'total': len(targets),
            }
        )
    return {
        'season': season['name'],
        'hemisphere': season['hemisphere'],
        'sampled_nights': [night.isoformat() for night in season['nights']],
        'challenges': challenges,
    }


def _latitude(location: dict[str, Any]) -> float | None:
    try:
        return float(location.get('latitude'))  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None


# ---------------------------------------------------------------------------
# Messier marathon
# ---------------------------------------------------------------------------


def marathon_year(today: datetime.date) -> int:
    """The year of the next (or current) marathon season."""
    return today.year if (today.month, today.day) <= MARATHON_SHOWN_UNTIL else today.year + 1


def marathon_nights(year: int, timezone_name: str) -> list[tuple[datetime.date, float]]:
    """The new-moon nights of the March-April marathon window, with their illumination.

    One night per lunation: the day the Moon is least illuminated at 23:00 local. The
    window holds one or two of them; the planner then keeps whichever lets the most
    objects be caught, since a new moon early in March and one in early April lose
    different objects to the twilight.
    """
    tz = ZoneInfo(timezone_name)
    day = datetime.date(year, *MARATHON_SEARCH_START)
    end = datetime.date(year, *MARATHON_SEARCH_END)
    samples: list[tuple[datetime.date, float]] = []
    while day <= end:
        instant = datetime.datetime.combine(day, datetime.time(23, 0), tzinfo=tz)
        samples.append((day, float(phase_at(instant)['illumination_percent'])))
        day += datetime.timedelta(days=1)

    nights = []
    for index, (night, illumination) in enumerate(samples):
        previous = samples[index - 1][1] if index > 0 else float('inf')
        following = samples[index + 1][1] if index + 1 < len(samples) else float('inf')
        if illumination <= previous and illumination < following and illumination < _MARATHON_MAX_ILLUMINATION:
            nights.append((night, illumination))
    if not nights:
        nights.append(min(samples, key=lambda sample: sample[1]))
    return nights


def _sun_grid(lat_deg: float, lon_deg: float, timezone_name: str, night: datetime.date):
    """Sun altitude, LST and local time over a whole marathon night.

    Wider than the shared 18:00-06:00 night grid: a marathon starts in the evening
    twilight and ends in the morning one, which runs past 06:00 local under summer time.
    """
    tz = ZoneInfo(timezone_name)
    start = datetime.datetime.combine(night, datetime.time(_MARATHON_GRID_START_HOUR, 0), tzinfo=tz)
    end = datetime.datetime.combine(
        night + datetime.timedelta(days=1), datetime.time(_MARATHON_GRID_END_HOUR, 0), tzinfo=tz
    )
    moments = []
    moment = start
    while moment <= end:
        moments.append(moment.astimezone(datetime.UTC))
        moment += datetime.timedelta(minutes=_MARATHON_STEP_MINUTES)
    times = Time(moments)
    frame = AltAz(obstime=times, location=EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg))
    sun_alt = np.asarray(get_sun(times).transform_to(frame).alt.deg)  # type: ignore[union-attr]
    lst_hours = np.asarray(times.sidereal_time('apparent', longitude=lon_deg * u.deg).hour)
    local = [instant.astimezone(tz) for instant in moments]
    return sun_alt, lst_hours, local


def _plan_marathon_night(
    location: dict[str, Any],
    members: Sequence[dict[str, Any]],
    night: datetime.date,
    illumination: float,
) -> dict[str, Any]:
    """The marathon order and reachable count from *location* on one night."""
    lat_deg, lon_deg, timezone_name, horizon_profile = visibility_calendar.location_geometry(location)
    sun_alt, lst_hours, local = _sun_grid(lat_deg, lon_deg, timezone_name, night)
    dark = sun_alt < MARATHON_SUN_ALTITUDE
    dark_indices = np.where(dark)[0]

    sequence = []
    unreachable = []
    for member in members:
        alt, az = visibility_calendar.fixed_target_altaz(member['ra_deg'], member['dec_deg'], lat_deg, lst_hours)
        floor = np.maximum(MARATHON_MIN_ALTITUDE, visibility_calendar.horizon_floor(az, horizon_profile))
        usable = np.where(dark & (alt >= floor))[0]
        row = {
            'target_id': member['target_id'],
            'name': member['identifier'],
            'preferred_name': member['preferred_name'],
            'object_type': member['object_type'],
            'constellation': member['constellation'],
        }
        if usable.size == 0:
            unreachable.append(row)
            continue
        # The best moment is the highest point inside the usable window: the window's
        # start for an object setting at dusk, its end for one rising at dawn, the
        # meridian for the rest - which yields the classic west-to-east marathon order.
        best = int(usable[int(np.argmax(alt[usable]))])
        row.update(
            {
                'best_time': local[best].strftime('%H:%M'),
                'window_start': local[int(usable[0])].strftime('%H:%M'),
                'window_end': local[int(usable[-1])].strftime('%H:%M'),
                'altitude': round(float(alt[best]), 1),
                '_order': (best, int(usable[-1])),
            }
        )
        sequence.append(row)

    sequence.sort(key=lambda row: row['_order'])
    for row in sequence:
        del row['_order']
    unreachable.sort(key=lambda row: _natural_key(row['name']))
    return {
        'night': night,
        'illumination': illumination,
        'dark_start': local[int(dark_indices[0])].strftime('%H:%M') if dark_indices.size else None,
        'dark_end': local[int(dark_indices[-1])].strftime('%H:%M') if dark_indices.size else None,
        'sequence': sequence,
        'unreachable': unreachable,
    }


def _compute_marathon(location: dict[str, Any], year: int) -> dict[str, Any]:
    _lat, _lon, timezone_name, _horizon = visibility_calendar.location_geometry(location)
    members = [
        member
        for member in achievements.catalogue_members('Messier')
        if member['ra_deg'] is not None and member['dec_deg'] is not None
    ]
    plans = [
        _plan_marathon_night(location, members, night, illumination)
        for night, illumination in marathon_nights(year, timezone_name)
    ]
    plan = max(plans, key=lambda candidate: (len(candidate['sequence']), -candidate['illumination']))
    night = plan['night']
    illumination = plan['illumination']
    sequence = plan['sequence']
    unreachable = plan['unreachable']

    return {
        'year': year,
        'date': night.isoformat(),
        'moon_illumination_percent': round(float(illumination), 1),
        'dark_start': plan['dark_start'],
        'dark_end': plan['dark_end'],
        'minimum_altitude': MARATHON_MIN_ALTITUDE,
        'sequence': sequence,
        'unreachable': unreachable,
        'reachable': len(sequence),
        'total': len(members),
    }


def _natural_key(name: str) -> tuple:
    """Order "M 9" before "M 10"."""
    digits = ''.join(character for character in name if character.isdigit())
    return (int(digits) if digits else 0, name)


def messier_marathon(
    location: dict[str, Any],
    today: datetime.date,
    captured_keys: Collection[str],
) -> dict[str, Any]:
    """The next Messier marathon from *location*, with the reachable count and the order."""
    year = marathon_year(today)
    cache_key = (visibility_calendar.location_cache_signature(location), year)
    plan = _marathon_cache.get(cache_key)
    if plan is None:
        plan = _remember(_marathon_cache, cache_key, _compute_marathon(location, year))
    else:
        _marathon_cache.move_to_end(cache_key)

    night = datetime.date.fromisoformat(plan['date'])
    highlight_from = datetime.date(year, *MARATHON_HIGHLIGHT_FROM)
    sequence = [{**row, 'captured': row['target_id'] in captured_keys} for row in plan['sequence']]
    return {
        **plan,
        'sequence': sequence,
        'captured': sum(1 for row in sequence if row['captured']),
        'days_until': (night - today).days,
        'in_season': highlight_from <= today <= datetime.date(year, *MARATHON_SHOWN_UNTIL),
    }


# ---------------------------------------------------------------------------
# Missing tonight
# ---------------------------------------------------------------------------


def missing_tonight(
    catalogue: str,
    location: dict[str, Any],
    today: datetime.date,
    captured_keys: Collection[str],
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Objects of *catalogue* not captured yet that are observable tonight, longest first."""
    members: Sequence[dict[str, Any]] = [
        member
        for member in achievements.catalogue_members(catalogue)
        if member['target_id'] not in captured_keys and member['ra_deg'] is not None and member['dec_deg'] is not None
    ]
    if not members:
        return []
    rows = visibility_calendar.next_visibility_batch(list(members), location, reference_date=today, months_ahead=1)
    visible = []
    for member, row in zip(members, rows, strict=False):
        hours = row.get('observable_hours_next')
        if not hours or hours <= 0:
            continue
        visible.append(
            {
                'target_id': member['target_id'],
                'name': member['identifier'],
                'preferred_name': member['preferred_name'],
                'object_type': member['object_type'],
                'constellation': member['constellation'],
                'magnitude': member['magnitude'],
                'observable_hours': hours,
                'transit_local_time': row.get('transit_local_time_next'),
                'max_altitude': row.get('max_altitude_next'),
            }
        )
    visible.sort(key=lambda row: (-row['observable_hours'], row['magnitude'] is None, row['magnitude'] or 0.0))
    return visible[: max(1, int(limit))]
