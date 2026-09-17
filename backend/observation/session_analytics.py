"""Session Analytics (v1.5) - read-only aggregation over the Observation Log.

Answers "how am I progressing?" and "how am I optimizing?" from data the app already
stores. This module owns no state: it adds no file, no config key and no cache job, and
every function here is pure - callers hand it already-loaded sessions (and, where
relevant, Astrodex items) and get a payload back. That keeps it trivially testable and
keeps the I/O in the blueprint layer, the same split
``catalogue_collection.get_collection_page(catalogue, astrodex_items)`` already uses.

Why the Observation Log and not Astrodex
----------------------------------------
``docs/OBSERVATION_LOG.md`` settled this when v1.3 shipped: attaching a photo to an entry
is a manual, optional step, so Astrodex picture metadata covers an unknown subset of what
was actually captured, while every logged entry carries its own
``frame_count`` / ``sub_exposure_seconds`` / ``integration_minutes``. Astrodex is
therefore used only for the separately-labelled "collection size" figure and for the sky
coverage map's objects that were never logged as a session entry.

Scale directions (they disagree, on purpose - both mirror 7Timer's ASTRO scales, as
``observation_sessions`` documents)
----------------------------------------------------------------------------------
* ``seeing``: 1 = best .. 8 = worst
* ``transparency``: 1 = worst .. 8 = best
* ``sqm``: higher is darker, therefore better
* ``moon_illumination_percent``: lower is better
* ``rating``: 0-5 in 0.5 steps, higher is better

Every bucket this module emits is ordered best-first and carries its own numeric bounds,
so a consumer never has to re-derive which way a scale runs.
"""

import math
from collections import OrderedDict
from datetime import date
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from observation import target_coordinates
from utils import normalize_catalogue_key as _normalize_key
from utils.constellation_names import full_constellation_name
from utils.logging_config import get_logger

logger = get_logger(__name__)

# A bucket with fewer samples than this is reported but not plotted: with a handful of
# nights, an average is noise dressed as insight (see feature.md, decision D8).
MINIMUM_BUCKET_SAMPLES = 5

# How many rows the "top targets" / constellation breakdowns return before collapsing the
# tail into an "others" row on the frontend.
TOP_TARGETS_LIMIT = 15
TOP_CONSTELLATIONS_LIMIT = 15

_QUALITY_BEST = 'best'
_QUALITY_MID = 'mid'
_QUALITY_WORST = 'worst'

# (quality, minimum, maximum) ordered best-first; bounds are inclusive.
_SEEING_BANDS = ((_QUALITY_BEST, 1.0, 3.0), (_QUALITY_MID, 4.0, 5.0), (_QUALITY_WORST, 6.0, 8.0))
_TRANSPARENCY_BANDS = ((_QUALITY_BEST, 6.0, 8.0), (_QUALITY_MID, 4.0, 5.0), (_QUALITY_WORST, 1.0, 3.0))
_SQM_BANDS = ((_QUALITY_BEST, 20.5, 30.0), (_QUALITY_MID, 19.0, 20.5), (_QUALITY_WORST, 0.0, 19.0))
_MOON_BANDS = ((_QUALITY_BEST, 0.0, 33.0), (_QUALITY_MID, 33.0, 66.0), (_QUALITY_WORST, 66.0, 100.0))

_CONDITION_METRICS: Tuple[Tuple[str, str, Tuple[Tuple[str, float, float], ...]], ...] = (
    ('seeing', 'lower_is_better', _SEEING_BANDS),
    ('transparency', 'higher_is_better', _TRANSPARENCY_BANDS),
    ('sqm', 'higher_is_better', _SQM_BANDS),
    ('moon_illumination_percent', 'lower_is_better', _MOON_BANDS),
)

# Label shown for entries whose effective equipment combination is unknown - kept as an
# explicit bucket rather than dropped, so the hours always add up to the headline total.
NO_COMBINATION_KEY = ''


# ---------------------------------------------------------------------------
# Small coercions - every field here comes off disk and may be absent or junk
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> Optional[float]:
    """Coerce a stored numeric field, returning None for absent/unparseable values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_text(value: Any) -> str:
    return str(value or '').strip()


def _dicts(values: Any) -> List[Dict[str, Any]]:
    """Return only the dict members of a stored list field."""
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _round(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def _mean(values: Sequence[float], digits: int = 2) -> Optional[float]:
    return _round(sum(values) / len(values), digits) if values else None


# ---------------------------------------------------------------------------
# Walking sessions -> nights -> entries
# ---------------------------------------------------------------------------


def _sorted_nights(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A session's nights in chronological order (storage order is not guaranteed)."""
    return sorted(_dicts(session.get('nights')), key=lambda night: _as_text(night.get('date')))


def _entry_night(session: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the night an entry belongs to.

    Falls back to the session's earliest night when ``night_id`` is null or dangling -
    the same rule ``observation_sessions._primary_night()`` uses wherever exactly one
    night's conditions are needed.
    """
    nights = _sorted_nights(session)
    night_id = _as_text(entry.get('night_id'))
    if night_id:
        for night in nights:
            if _as_text(night.get('id')) == night_id:
                return night
    return nights[0] if nights else {}


def iter_entries(sessions: Iterable[Dict[str, Any]]) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    """Yield ``(session, night, entry)`` for every entry of every session."""
    for session in sessions:
        if not isinstance(session, dict):
            continue
        for entry in _dicts(session.get('entries')):
            yield session, _entry_night(session, entry), entry


def entry_date(night: Dict[str, Any]) -> str:
    """The ``YYYY-MM-DD`` an entry is attributed to - the night it happened, never
    ``created_at``: a session logged three weeks late must land in the month it happened."""
    return _as_text(night.get('date'))


def entry_integration_minutes(entry: Dict[str, Any]) -> float:
    """Integration time for one entry.

    ``integration_minutes`` is the one guaranteed-summable field (see
    ``docs/OBSERVATION_LOG.md``); ``frame_count`` x ``sub_exposure_seconds`` is used only
    when it is absent but both of those were recorded.
    """
    minutes = _as_float(entry.get('integration_minutes'))
    if minutes is not None and minutes > 0:
        return minutes
    frames = _as_float(entry.get('frame_count'))
    sub_exposure = _as_float(entry.get('sub_exposure_seconds'))
    if frames and sub_exposure and frames > 0 and sub_exposure > 0:
        return frames * sub_exposure / 60.0
    return 0.0


def entry_is_captured(entry: Dict[str, Any]) -> bool:
    """Whether an entry records real capture evidence rather than an empty placeholder.

    Same threshold the Observation Log itself uses to auto-register a target in Astrodex:
    frames were taken, or integration time was recorded.
    """
    frames = _as_float(entry.get('frame_count')) or 0.0
    return frames > 0 or entry_integration_minutes(entry) > 0


def entry_rating(entry: Dict[str, Any]) -> Optional[float]:
    """The entry's 0-5 rating, or None when it was never rated."""
    rating = _as_float(entry.get('rating'))
    if rating is None or rating < 0 or rating > 5:
        return None
    return rating


def object_key(entry: Dict[str, Any]) -> str:
    """Stable cross-catalogue identity for an entry's target.

    ``catalogue_group_id`` is the dataset's own identity when the target came from
    SkyTonight, so "M 31" and "NGC 224" count as one object; the normalized name is the
    fallback for a manually-added target that never resolved.
    """
    return _as_text(entry.get('catalogue_group_id')) or _normalize_key(entry.get('name'))


def effective_combination(session: Dict[str, Any], entry: Dict[str, Any]) -> Tuple[str, str]:
    """``(combination_id, combination_name)`` actually used for one entry.

    An entry's own combination is an optional override of the session's (someone switched
    telescopes mid-session); null means "same as the session". Both are frozen snapshots
    stored on the records themselves, so this never needs the ``equipment`` package and
    never blanks when a combination is later renamed or deleted.
    """
    combination_id = _as_text(entry.get('combination_id'))
    if combination_id:
        return combination_id, _as_text(entry.get('combination_name'))
    return _as_text(session.get('combination_id')), _as_text(session.get('combination_name'))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _month_key(day: str) -> str:
    return day[:7] if len(day) >= 7 else ''


def _dense_month_range(first: str, last: str) -> List[str]:
    """Every ``YYYY-MM`` from *first* to *last* inclusive, so the chart has no holes."""
    if not first or not last:
        return []
    try:
        year, month = int(first[:4]), int(first[5:7])
        end_year, end_month = int(last[:4]), int(last[5:7])
    except ValueError:
        return []
    months: List[str] = []
    # A wide log is still only a few hundred months; the guard is against a corrupt date
    # producing an unbounded loop, not against a legitimately long history.
    while (year, month) <= (end_year, end_month) and len(months) < 2400:
        months.append(f'{year:04d}-{month:02d}')
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def _accumulate(bucket: Dict[str, Any], integration: float, rating: Optional[float]) -> None:
    bucket['integration_minutes'] += integration
    bucket['entries'] += 1
    if rating is not None:
        bucket['_ratings'].append(rating)


def _new_bucket(**fields: Any) -> Dict[str, Any]:
    bucket: Dict[str, Any] = {'integration_minutes': 0.0, 'entries': 0, '_ratings': []}
    bucket.update(fields)
    return bucket


def _finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
    ratings = bucket.pop('_ratings')
    bucket['integration_minutes'] = _round(bucket['integration_minutes'])
    bucket['average_rating'] = _mean(ratings, 1)
    bucket['rated_entries'] = len(ratings)
    return bucket


def _sorted_buckets(buckets: Dict[Any, Dict[str, Any]], limit: Optional[int] = None) -> List[Dict[str, Any]]:
    rows = [_finalize(bucket) for bucket in buckets.values()]
    rows.sort(key=lambda row: (-row['integration_minutes'], -row['entries']))
    return rows[:limit] if limit else rows


def build_summary(
    sessions: Sequence[Dict[str, Any]],
    today: date,
    astrodex_item_count: int = 0,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate a user's whole Observation Log into the stats dashboard payload.

    Args:
        sessions: The user's own sessions, as loaded from their sessions file.
        today: The observer's current local date - the caller resolves it from the active
            location's timezone so "this month" means the user's month, not the server's.
        astrodex_item_count: Size of the user's Astrodex collection, reported as its own
            separately-labelled figure rather than mixed into the logged totals.
        year: The year the "this year" bucket covers; defaults to *today*'s year.
    """
    target_year = int(year) if year is not None else today.year
    year_prefix = f'{target_year:04d}'
    month_prefix = f'{today.year:04d}-{today.month:02d}'

    lifetime_minutes = 0.0
    year_minutes = 0.0
    month_minutes = 0.0
    total_entries = 0
    captured_entries = 0
    ratings: List[float] = []
    object_keys = set()
    constellation_keys = set()
    dated_nights = set()
    first_day = ''
    last_day = ''

    monthly: Dict[str, Dict[str, Any]] = {}
    types: Dict[str, Dict[str, Any]] = {}
    constellations: Dict[str, Dict[str, Any]] = {}
    equipment: Dict[str, Dict[str, Any]] = {}
    equipment_sessions: Dict[str, set] = {}
    targets: Dict[str, Dict[str, Any]] = {}

    for session, night, entry in iter_entries(sessions):
        total_entries += 1
        day = entry_date(night)
        integration = entry_integration_minutes(entry)
        rating = entry_rating(entry)
        if rating is not None:
            ratings.append(rating)

        lifetime_minutes += integration
        if day.startswith(year_prefix):
            year_minutes += integration
        if day.startswith(month_prefix):
            month_minutes += integration

        if day:
            dated_nights.add((_as_text(session.get('id')), _as_text(night.get('id')) or day))
            first_day = day if not first_day or day < first_day else first_day
            last_day = day if not last_day or day > last_day else last_day

            month = _month_key(day)
            bucket = monthly.setdefault(month, _new_bucket(month=month, nights=set()))
            _accumulate(bucket, integration, rating)
            bucket['nights'].add(day)

        if entry_is_captured(entry):
            captured_entries += 1
            key = object_key(entry)
            if key:
                object_keys.add(key)

        object_type = _as_text(entry.get('type')) or 'Unknown'
        _accumulate(types.setdefault(object_type, _new_bucket(type=object_type)), integration, rating)

        constellation = full_constellation_name(entry.get('constellation'))
        if constellation:
            constellation_keys.add(constellation)
            _accumulate(
                constellations.setdefault(constellation, _new_bucket(constellation=constellation)),
                integration,
                rating,
            )

        combination_id, combination_name = effective_combination(session, entry)
        combo_key = combination_id or NO_COMBINATION_KEY
        combo_bucket = equipment.setdefault(
            combo_key,
            _new_bucket(combination_id=combination_id or None, combination_name=combination_name),
        )
        # A later entry may carry the name a bare id did not.
        if combination_name and not combo_bucket['combination_name']:
            combo_bucket['combination_name'] = combination_name
        _accumulate(combo_bucket, integration, rating)
        equipment_sessions.setdefault(combo_key, set()).add(_as_text(session.get('id')))

        target_key = object_key(entry) or _normalize_key(entry.get('name'))
        if target_key:
            target_bucket = targets.setdefault(
                target_key,
                _new_bucket(
                    name=_as_text(entry.get('name')),
                    catalogue=_as_text(entry.get('catalogue')),
                    type=object_type,
                    constellation=constellation,
                    last_date='',
                ),
            )
            _accumulate(target_bucket, integration, rating)
            if day > target_bucket['last_date']:
                target_bucket['last_date'] = day

    month_rows = []
    for month in _dense_month_range(_month_key(first_day), _month_key(last_day)):
        bucket = monthly.get(month)
        if bucket is None:
            month_rows.append(
                {
                    'month': month,
                    'integration_minutes': 0.0,
                    'entries': 0,
                    'nights': 0,
                    'average_rating': None,
                    'rated_entries': 0,
                }
            )
            continue
        nights = len(bucket.pop('nights'))
        row = _finalize(bucket)
        row['nights'] = nights
        month_rows.append(row)

    equipment_rows = _sorted_buckets(equipment)
    for row in equipment_rows:
        key = row['combination_id'] or NO_COMBINATION_KEY
        row['sessions'] = len(equipment_sessions.get(key, set()))

    session_count = len([session for session in sessions if isinstance(session, dict)])
    night_count = sum(len(_sorted_nights(session)) for session in sessions if isinstance(session, dict))

    return {
        'year': target_year,
        'totals': {
            'integration_minutes_lifetime': _round(lifetime_minutes),
            'integration_minutes_year': _round(year_minutes),
            'integration_minutes_month': _round(month_minutes),
            'sessions': session_count,
            'nights': night_count,
            'nights_with_entries': len(dated_nights),
            'entries': total_entries,
            'captured_entries': captured_entries,
            'objects_captured': len(object_keys),
            'constellations': len(constellation_keys),
            'average_rating': _mean(ratings, 1),
            'rated_entries': len(ratings),
            'astrodex_items': max(0, int(astrodex_item_count or 0)),
            'first_night': first_day,
            'last_night': last_day,
        },
        'monthly': month_rows,
        'object_types': _sorted_buckets(types),
        'constellations': _sorted_buckets(constellations, TOP_CONSTELLATIONS_LIMIT),
        'constellations_total': len(constellations),
        'equipment': equipment_rows,
        'top_targets': _sorted_buckets(targets, TOP_TARGETS_LIMIT),
        'targets_total': len(targets),
    }


# ---------------------------------------------------------------------------
# Sky coverage map
# ---------------------------------------------------------------------------

# Sources a coverage point can come from, in increasing order of evidence.
SOURCE_ASTRODEX = 'astrodex'
SOURCE_LOG = 'log'
SOURCE_BOTH = 'both'


def never_visible_declination(latitude: Optional[float]) -> Optional[float]:
    """The declination below/above which nothing ever rises at *latitude*.

    Returns a signed bound: from the northern hemisphere nothing below
    ``-(90 - lat)`` ever clears the horizon, and from the southern hemisphere nothing
    above ``+(90 + lat)``. None when the latitude is unknown, so the frontend simply
    draws no band rather than guessing one.
    """
    value = _as_float(latitude)
    if value is None or not -90.0 <= value <= 90.0:
        return None
    if value >= 0:
        return -(90.0 - value)
    return 90.0 + value


def _astrodex_dates(item: Dict[str, Any]) -> Tuple[str, str]:
    """(earliest, latest) capture date across an Astrodex item's pictures.

    Falls back to the item's own ``created_at`` day: an item with no dated picture is
    still an object the user has, it just has no capture date of its own.
    """
    days = sorted(
        day for day in (_as_text(picture.get('date'))[:10] for picture in _dicts(item.get('pictures'))) if day
    )
    if days:
        return days[0], days[-1]
    created = _as_text(item.get('created_at'))[:10]
    return created, created


def build_sky_coverage(
    sessions: Sequence[Dict[str, Any]],
    astrodex_items: Sequence[Dict[str, Any]] = (),
    latitude: Optional[float] = None,
) -> Dict[str, Any]:
    """Place every object the user has captured on an RA/Dec grid.

    Folds two sources into one set of points: Observation Log entries with real capture
    evidence, and Astrodex items (which cover objects added straight to the gallery, never
    logged as a session entry). Both are keyed on the SkyTonight dataset's cross-catalogue
    ``group_id`` when it resolves, so the same object recorded as "M 31" in one place and
    "M31 - Andromeda Galaxy" in the other is one dot, not two.

    Objects whose coordinates cannot be resolved at all are counted in ``unplaced`` rather
    than silently dropped - the same honest accounting ``astrodex.get_astrodex_map_points``
    does with its ungeotagged pictures.
    """
    points: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    unplaced: Dict[str, str] = {}

    def record(key: str, name: str, identity: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
        """Get or create the point for *key*, or register it as unplaceable."""
        existing = points.get(key)
        if existing is not None:
            if existing['source'] != source:
                existing['source'] = SOURCE_BOTH
            return existing
        if not identity['placed']:
            unplaced.setdefault(key, name)
            return None
        point = {
            'key': key,
            'name': name,
            'preferred_name': identity['preferred_name'] or name,
            'type': '',
            'constellation': '',
            'ra_deg': _round(identity['ra_deg'], 4),
            'dec_deg': _round(identity['dec_deg'], 4),
            'ra_hours': _round(identity['ra_deg'] / 15.0, 4),
            'integration_minutes': 0.0,
            'entries': 0,
            'first_date': '',
            'last_date': '',
            'astrodex_item_id': None,
            'source': source,
            'resolved': identity['resolved'],
        }
        points[key] = point
        return point

    def stamp_dates(point: Dict[str, Any], first: str, last: str) -> None:
        if first and (not point['first_date'] or first < point['first_date']):
            point['first_date'] = first
        if last and last > point['last_date']:
            point['last_date'] = last

    for _session, night, entry in iter_entries(sessions):
        if not entry_is_captured(entry):
            continue
        name = _as_text(entry.get('name'))
        if not name:
            continue
        identity = target_coordinates.resolve_target(name, entry.get('catalogue'), entry.get('ra'), entry.get('dec'))
        key = identity['group_id'] or object_key(entry)
        if not key:
            continue
        point = record(key, name, identity, SOURCE_LOG)
        if point is None:
            continue
        point['integration_minutes'] += entry_integration_minutes(entry)
        point['entries'] += 1
        point['type'] = point['type'] or _as_text(entry.get('type'))
        point['constellation'] = point['constellation'] or full_constellation_name(entry.get('constellation'))
        if not point['astrodex_item_id']:
            point['astrodex_item_id'] = _as_text(entry.get('astrodex_item_id')) or None
        day = entry_date(night)
        stamp_dates(point, day, day)

    for item in _dicts(astrodex_items):
        name = _as_text(item.get('name'))
        if not name:
            continue
        identity = target_coordinates.resolve_target(name, item.get('catalogue'))
        key = identity['group_id'] or _normalize_key(name)
        if not key:
            continue
        point = record(key, name, identity, SOURCE_ASTRODEX)
        if point is None:
            continue
        point['type'] = point['type'] or _as_text(item.get('type'))
        point['constellation'] = point['constellation'] or full_constellation_name(item.get('constellation'))
        point['astrodex_item_id'] = point['astrodex_item_id'] or _as_text(item.get('id')) or None
        stamp_dates(point, *_astrodex_dates(item))

    rows = list(points.values())
    for row in rows:
        row['integration_minutes'] = _round(row['integration_minutes'])
        row['type'] = row['type'] or 'Unknown'

    return {
        'points': rows,
        'total_objects': len(rows) + len(unplaced),
        'unplaced_count': len(unplaced),
        'unplaced_names': sorted(unplaced.values())[:TOP_TARGETS_LIMIT],
        'never_visible_dec_below': never_visible_declination(latitude),
        'latitude': _as_float(latitude),
    }


# ---------------------------------------------------------------------------
# Conditions correlation
# ---------------------------------------------------------------------------


def _band_for(value: float, bands: Tuple[Tuple[str, float, float], ...]) -> Optional[str]:
    """The quality band *value* falls into, or None when it is outside every band."""
    for quality, minimum, maximum in bands:
        if minimum <= value <= maximum:
            return quality
    return None


def build_conditions(sessions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Join every rated entry to its night's conditions and bucket the results.

    Strictly descriptive: each bucket reports its own sample count alongside its average,
    and a bucket under :data:`MINIMUM_BUCKET_SAMPLES` is flagged rather than plotted. No
    trend line and no correlation coefficient - see feature.md decision D8.
    """
    samples: List[Dict[str, Any]] = []

    for session, night, entry in iter_entries(sessions):
        rating = entry_rating(entry)
        if rating is None:
            continue
        sample = {
            'date': entry_date(night),
            'name': _as_text(entry.get('name')),
            'rating': rating,
            'integration_minutes': _round(entry_integration_minutes(entry)),
            'seeing': _as_float(night.get('seeing')),
            'transparency': _as_float(night.get('transparency')),
            'sqm': _as_float(night.get('sqm')),
            'moon_illumination_percent': _as_float(night.get('moon_illumination_percent')),
        }
        if any(sample[metric] is not None for metric, _, _ in _CONDITION_METRICS):
            samples.append(sample)

    metrics: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for metric, direction, bands in _CONDITION_METRICS:
        grouped: Dict[str, List[float]] = {quality: [] for quality, _, _ in bands}
        measured = 0
        for sample in samples:
            value = sample[metric]
            if value is None:
                continue
            measured += 1
            quality = _band_for(value, bands)
            if quality is not None:
                grouped[quality].append(sample['rating'])

        metrics[metric] = {
            'direction': direction,
            'measured_samples': measured,
            'buckets': [
                {
                    'quality': quality,
                    'min': minimum,
                    'max': maximum,
                    'samples': len(grouped[quality]),
                    'average_rating': _mean(grouped[quality], 1),
                    'insufficient_data': len(grouped[quality]) < MINIMUM_BUCKET_SAMPLES,
                }
                for quality, minimum, maximum in bands
            ],
        }

    return {
        'samples': samples,
        'metrics': metrics,
        'total_rated_entries': len(samples),
        'minimum_samples': MINIMUM_BUCKET_SAMPLES,
    }


# ---------------------------------------------------------------------------
# Best months - the personal half (the astronomical half is location ephemeris)
# ---------------------------------------------------------------------------


def build_logged_months(sessions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per calendar month (1-12), what the user actually logged across all years.

    Pairs with the location's astronomical dark-hours figures to answer "when is it worth
    planning to be out here, and when have I actually been out". Deliberately *not* a
    weather statistic - MyAstroBoard keeps no historical weather (see feature.md 2.6).
    """
    buckets: Dict[int, Dict[str, Any]] = {
        month: {'month': month, 'integration_minutes': 0.0, 'entries': 0, '_ratings': [], '_nights': set()}
        for month in range(1, 13)
    }

    for _session, night, entry in iter_entries(sessions):
        day = entry_date(night)
        if len(day) < 7:
            continue
        try:
            month = int(day[5:7])
        except ValueError:
            continue
        bucket = buckets.get(month)
        if bucket is None:
            continue
        bucket['integration_minutes'] += entry_integration_minutes(entry)
        bucket['entries'] += 1
        bucket['_nights'].add(day)
        rating = entry_rating(entry)
        if rating is not None:
            bucket['_ratings'].append(rating)

    rows: List[Dict[str, Any]] = []
    for month in range(1, 13):
        bucket = buckets[month]
        nights = bucket.pop('_nights')
        ratings = bucket.pop('_ratings')
        rows.append(
            {
                'month': month,
                'integration_hours': _round(bucket['integration_minutes'] / 60.0),
                'entries': bucket['entries'],
                'nights_logged': len(nights),
                'average_rating': _mean(ratings, 1),
            }
        )
    return rows
