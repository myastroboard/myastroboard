"""Achievements (v1.9) - badges computed on read from what was actually logged.

Nothing here is stored. A badge is a pure function of the user's Observation Log and
Astrodex as they are now, so there is no new table, nothing to add to account erasure or
to the personal data export, and nothing that can go stale behind an edit. The flip side
is stated in the documentation: deleting the entries a badge rests on takes the badge
back. The only thing kept is the list of badges the user has already seen (a preference),
so a new badge is pointed out once.

The date a badge was earned is not stored either: it is read off the history itself (the
night the tenth Messier object was first captured, the night the running total crossed
ten hours), so it survives without a write and stays true when an old session is
back-filled.

Two layers, the same split as ``session_analytics``:

* :func:`collect_progress` walks the already-loaded sessions and Astrodex items once and
  returns plain facts - captured objects with their first date and catalogues,
  integration events, observed nights, activity dates;
* :func:`evaluate_badges` turns those facts and the catalogue sizes into badges. It is
  pure and takes no dataset, so tests feed it facts directly.

Resolving an object against the SkyTonight dataset is injected (``resolve``), defaulting
to :func:`observation.target_coordinates.lookup_dataset_entry`.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from observation import achievement_definitions as definitions
from observation import session_analytics, target_coordinates
from skytonight import skytonight_targets
from utils import normalize_catalogue_key as _normalize_key
from utils.constellation_names import full_constellation_name
from utils.logging_config import get_logger

logger = get_logger(__name__)

# How many "next within reach" milestones the Progress page shows.
NEXT_WITHIN_REACH_LIMIT = 4

# Object classes a badge or a review screen can name.
CLASS_GALAXY = 'galaxy'
CLASS_NEBULA = 'nebula'
CLASS_CLUSTER = 'cluster'
CLASS_COMET = 'comet'
CLASS_PLANET = 'planet'
CLASS_MOON = 'moon'
CLASS_SUN = 'sun'
CLASS_STAR = 'star'
CLASS_OTHER = 'other'

Resolver = Callable[[Any, Any], dict[str, Any]]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _as_text(value: Any) -> str:
    return str(value or '').strip()


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def _day(value: Any) -> str:
    """The ``YYYY-MM-DD`` part of a stored date or timestamp, or '' when it has none."""
    text = _as_text(value)[:10]
    return text if len(text) == 10 and text[4] == '-' and text[7] == '-' else ''


def _earlier(current: str, candidate: str) -> str:
    """The earlier of two ``YYYY-MM-DD`` days, an empty day counting as unknown."""
    if not candidate:
        return current
    if not current:
        return candidate
    return min(current, candidate)


def _dicts(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def classify_object(object_type: Any, category: Any = '', name: Any = '') -> str:
    """Fold a free-form object type into the handful of classes a badge can name.

    Order matters: "Planetary Nebula" is a nebula, not a planet, and "Galaxy Cluster" is a
    galaxy, not a star cluster.
    """
    kind = _as_text(object_type).casefold()
    group = _as_text(category).casefold()
    label = _as_text(name).casefold()

    if group == 'comets' or 'comet' in kind:
        return CLASS_COMET
    if kind == 'sun' or label in ('sun', 'soleil', 'sol'):
        return CLASS_SUN
    if kind == 'moon' or label in ('moon', 'lune', 'luna', 'mond', 'lua'):
        return CLASS_MOON
    if 'nebula' in kind or 'hii' in kind or 'supernova' in kind or 'molecular cloud' in kind:
        return CLASS_NEBULA
    if 'planet' in kind or group == 'bodies':
        return CLASS_PLANET
    if 'galax' in kind:
        return CLASS_GALAXY
    if 'cluster' in kind or 'association' in kind:
        return CLASS_CLUSTER
    if 'star' in kind:
        return CLASS_STAR
    return CLASS_OTHER


def season_index(day: str) -> int | None:
    """Meteorological season of a date: 0 = Dec-Feb, 1 = Mar-May, 2 = Jun-Aug, 3 = Sep-Nov.

    Hemisphere-neutral on purpose: which name a season carries depends on the hemisphere,
    whether four different ones were covered does not.
    """
    if len(day) < 7:
        return None
    try:
        month = int(day[5:7])
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return (month % 12) // 3


# ---------------------------------------------------------------------------
# Collecting facts
# ---------------------------------------------------------------------------


class _CachedResolver:
    """Memoize dataset lookups within one request: the same object recurs a lot."""

    def __init__(self, resolve: Resolver):
        self._resolve = resolve
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def __call__(self, name: Any, catalogue: Any) -> dict[str, Any]:
        key = (_as_text(name), _as_text(catalogue))
        if key not in self._cache:
            try:
                entry = self._resolve(key[0], key[1])
            except Exception as error:
                logger.debug(f'Dataset lookup failed for {key[0]!r}: {error}')
                entry = {}
            self._cache[key] = entry if isinstance(entry, dict) else {}
        return self._cache[key]


def _new_capture(key: str, name: str, entry: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """The capture fact for one object, from its dataset entry when known, else its record."""
    raw_aliases = entry.get('aliases')
    aliases = raw_aliases if isinstance(raw_aliases, dict) else {}
    catalogues = {str(catalogue): str(value) for catalogue, value in aliases.items() if str(value).strip()}
    own_catalogue = _as_text(record.get('catalogue'))
    if own_catalogue and own_catalogue not in catalogues and not entry:
        catalogues[own_catalogue] = name

    object_type = _as_text(entry.get('object_type')) or _as_text(record.get('type'))
    constellation = full_constellation_name(entry.get('constellation') or record.get('constellation'))
    dec_deg = _as_float(entry.get('dec_deg'))
    if dec_deg is None:
        dec_deg = target_coordinates.parse_dec_to_degrees(record.get('dec'))

    return {
        'key': key,
        'name': name,
        'preferred_name': _as_text(entry.get('preferred_name')) or name,
        'object_type': object_type,
        'object_class': classify_object(object_type, entry.get('category'), name),
        'constellation': constellation,
        'catalogues': catalogues,
        'dec_deg': dec_deg,
        'first_date': '',
        'astrodex_item_id': None,
    }


def collect_progress(
    sessions: Sequence[dict[str, Any]],
    astrodex_items: Sequence[dict[str, Any]] = (),
    location_bortle: dict[str, Any] | None = None,
    resolve: Resolver | None = None,
) -> dict[str, Any]:
    """Walk the user's log and Astrodex once and return the facts badges are built from.

    Returns a dict with:

    * ``captures`` - ``{key: capture}``, one per distinct object, with its first capture
      date, class, constellation, declination and catalogue identifiers. An object is
      captured when a log entry records frames or integration time (the threshold the
      Observation Log uses to register it in Astrodex), or when it sits in Astrodex;
    * ``integration`` - ``[(day, minutes, key)]``: every logged entry's integration time,
      plus the integration recorded on Astrodex pictures that no log entry points to, so a
      gallery-only user still has hours and a logged picture is never counted twice;
    * ``nights`` - one fact per night with at least one capture: its date, SQM, Moon
      illumination and the Bortle class of its location preset when known;
    * ``sessions`` - per session, the sorted dates of its nights;
    * ``activity_dates`` - every day something was captured;
    * ``capture_days`` - ``[(day, key)]``, one per dated capture event (a logged entry,
      an Astrodex picture), so a year can be cut out of the history;
    * ``astrodex_item_keys`` - ``{astrodex item id: capture key}``.

    *location_bortle* maps a location preset id to its Bortle class, resolved by the
    caller from the configuration (sessions only store the preset id).
    """
    lookup = _CachedResolver(resolve or target_coordinates.lookup_dataset_entry)
    bortle_by_location = location_bortle or {}

    captures: dict[str, dict[str, Any]] = {}
    integration: list[tuple[str, float, str]] = []
    nights: dict[tuple[str, str], dict[str, Any]] = {}
    session_nights: list[list[str]] = []
    activity_dates: set[str] = set()
    capture_days: list[tuple[str, str]] = []
    linked_pictures: set[str] = set()
    item_keys: dict[str, str] = {}

    def capture_for(name: str, catalogue: Any, record: dict[str, Any], fallback_key: str) -> dict[str, Any] | None:
        entry = lookup(name, catalogue)
        key = _as_text(entry.get('group_id')) or fallback_key
        if not key:
            return None
        capture = captures.get(key)
        if capture is None:
            capture = _new_capture(key, name, entry, record)
            captures[key] = capture
        return capture

    for session in sessions:
        if not isinstance(session, dict):
            continue
        dates = sorted({_day(night.get('date')) for night in _dicts(session.get('nights'))} - {''})
        if dates:
            session_nights.append(dates)

    for session, night, entry in session_analytics.iter_entries(sessions):
        picture_id = _as_text(entry.get('astrodex_picture_id'))
        if picture_id:
            linked_pictures.add(picture_id)
        if not session_analytics.entry_is_captured(entry):
            continue
        name = _as_text(entry.get('name'))
        if not name:
            continue
        capture = capture_for(name, entry.get('catalogue'), entry, session_analytics.object_key(entry))
        if capture is None:
            continue
        day = _day(session_analytics.entry_date(night))
        capture['first_date'] = _earlier(capture['first_date'], day)
        if not capture['astrodex_item_id']:
            capture['astrodex_item_id'] = _as_text(entry.get('astrodex_item_id')) or None

        minutes = session_analytics.entry_integration_minutes(entry)
        if minutes > 0:
            integration.append((day, minutes, capture['key']))
        if day:
            activity_dates.add(day)
            capture_days.append((day, capture['key']))
            night_key = (_as_text(session.get('id')), _as_text(night.get('id')) or day)
            if night_key not in nights:
                location_id = _as_text(session.get('location_id'))
                nights[night_key] = {
                    'date': day,
                    'sqm': _as_float(night.get('sqm')),
                    'moon_illumination_percent': _as_float(night.get('moon_illumination_percent')),
                    'bortle': _as_float(bortle_by_location.get(location_id)) if location_id else None,
                }

    for item in _dicts(list(astrodex_items)):
        name = _as_text(item.get('name'))
        if not name:
            continue
        capture = capture_for(name, item.get('catalogue'), item, _normalize_key(name))
        if capture is None:
            continue
        item_id = _as_text(item.get('id'))
        if item_id:
            item_keys[item_id] = capture['key']
            capture['astrodex_item_id'] = capture['astrodex_item_id'] or item_id

        picture_days = []
        for picture in _dicts(item.get('pictures')):
            day = _day(picture.get('date'))
            if day:
                picture_days.append(day)
                activity_dates.add(day)
                capture_days.append((day, capture['key']))
            minutes = _as_float(picture.get('integration_minutes'))
            if minutes and minutes > 0 and _as_text(picture.get('id')) not in linked_pictures:
                integration.append((day, minutes, capture['key']))
        first_day = min(picture_days) if picture_days else _day(item.get('created_at'))
        capture['first_date'] = _earlier(capture['first_date'], first_day)
        if not picture_days and first_day:
            activity_dates.add(first_day)
            capture_days.append((first_day, capture['key']))

    return {
        'captures': captures,
        'integration': integration,
        'nights': list(nights.values()),
        'sessions': session_nights,
        'activity_dates': sorted(activity_dates),
        'capture_days': capture_days,
        'astrodex_item_keys': item_keys,
    }


# ---------------------------------------------------------------------------
# Catalogue sizes (read off the SkyTonight dataset, memoized on its identity)
# ---------------------------------------------------------------------------

_catalogue_totals_cache: dict[str, Any] = {'marker': None, 'totals': {}}


def catalogue_totals() -> dict[str, int]:
    """Number of deep-sky objects each catalogue holds in the built SkyTonight dataset.

    Read from the dataset rather than written down, so "the whole Messier catalogue" is
    whatever the dataset carries (the merged M 40 / M 102 cases included) and a rebuilt
    dataset is picked up without a code change.
    """
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []
    marker = id(targets)
    if _catalogue_totals_cache['marker'] == marker:
        return _catalogue_totals_cache['totals']

    totals: dict[str, int] = {}
    for target in targets:
        category = target.get('category') if isinstance(target, dict) else getattr(target, 'category', '')
        if str(category or '') != 'deep_sky':
            continue
        names = target.get('catalogue_names') if isinstance(target, dict) else getattr(target, 'catalogue_names', {})
        for catalogue, value in (names or {}).items():
            if str(value or '').strip():
                totals[str(catalogue)] = totals.get(str(catalogue), 0) + 1

    _catalogue_totals_cache['marker'] = marker
    _catalogue_totals_cache['totals'] = totals
    return totals


def catalogue_members(catalogue: str) -> list[dict[str, Any]]:
    """Every deep-sky object of *catalogue* in the dataset, with coordinates when known."""
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []
    members: list[dict[str, Any]] = []
    for target in targets:
        is_dict = isinstance(target, dict)

        def field(name: str, default: Any = None, source: Any = target, as_dict: bool = is_dict) -> Any:
            return source.get(name, default) if as_dict else getattr(source, name, default)

        if field('category') != 'deep_sky':
            continue
        identifier = str((field('catalogue_names') or {}).get(catalogue) or '').strip()
        if not identifier:
            continue
        coordinates = field('coordinates')
        if isinstance(coordinates, dict):
            ra_hours, dec_degrees = coordinates.get('ra_hours'), coordinates.get('dec_degrees')
        else:
            ra_hours = getattr(coordinates, 'ra_hours', None)
            dec_degrees = getattr(coordinates, 'dec_degrees', None)
        object_type = str(field('object_type') or '')
        members.append(
            {
                'target_id': str(field('target_id') or ''),
                'identifier': identifier,
                'preferred_name': str(field('preferred_name') or '') or identifier,
                'object_type': object_type,
                'object_class': classify_object(object_type, 'deep_sky'),
                'constellation': full_constellation_name(field('constellation')),
                'magnitude': _as_float(field('magnitude')),
                'ra_deg': float(ra_hours) * 15.0 if ra_hours is not None else None,
                'dec_deg': float(dec_degrees) if dec_degrees is not None else None,
            }
        )
    return members


# ---------------------------------------------------------------------------
# Evaluating badges
# ---------------------------------------------------------------------------


def _nth_date(days: Iterable[str], count: int) -> str | None:
    """The day the *count*-th item was reached, in chronological order.

    Undated items sort last: a badge earned only thanks to an undated record is earned,
    but has no date to show.
    """
    ordered = sorted(days, key=lambda day: (day == '', day))
    if count <= 0 or len(ordered) < count:
        return None
    return ordered[count - 1] or None


def _crossing_date(events: Iterable[tuple[str, float]], threshold: float) -> str | None:
    """The day a running total of ``(day, amount)`` events first reaches *threshold*."""
    total = 0.0
    for day, amount in sorted(events, key=lambda event: (event[0] == '', event[0])):
        total += amount
        if total >= threshold - 1e-9:
            return day or None
    return None


def _distinct_progress(dated_values: Iterable[tuple[str, Any]], threshold: int) -> tuple[int, str | None]:
    """How many distinct values were reached, and the day the *threshold*-th one was."""
    seen: set[Any] = set()
    reached_on: str | None = None
    for day, value in sorted(dated_values, key=lambda pair: (pair[0] == '', pair[0])):
        if value is None or value in seen:
            continue
        seen.add(value)
        if len(seen) == threshold and reached_on is None:
            reached_on = day or None
    return len(seen), reached_on


def _evaluate(definition: dict[str, Any], facts: dict[str, Any], totals: dict[str, int]) -> dict[str, Any] | None:
    """``(current, target, earned_on)`` for one badge, or None when it cannot be evaluated."""
    rule = definition['rule']
    threshold = definition.get('threshold')
    captures = list(facts.get('captures', {}).values())
    earned_on: str | None = None

    if rule == 'first_class':
        days = [capture['first_date'] for capture in captures if capture['object_class'] == definition['object_class']]
        current, target = min(len(days), 1), 1
        earned_on = _nth_date(days, 1)
    elif rule == 'catalogue_count':
        catalogue = definition['catalogue']
        size = int(totals.get(catalogue, 0) or 0)
        if size <= 0:
            return None
        target = size if threshold is None else int(threshold)
        if target > size:
            return None
        days = [capture['first_date'] for capture in captures if catalogue in capture['catalogues']]
        current = len(days)
        earned_on = _nth_date(days, target)
    elif rule == 'integration_hours':
        target = int(threshold or 0)
        events = [(day, minutes) for day, minutes, _key in facts.get('integration', [])]
        current = round(sum(minutes for _day_, minutes in events) / 60.0, 1)
        earned_on = _crossing_date(events, target * 60.0)
    elif rule == 'single_target_hours':
        target = int(threshold or 0)
        per_target: dict[str, list[tuple[str, float]]] = {}
        for day, minutes, key in facts.get('integration', []):
            per_target.setdefault(key, []).append((day, minutes))
        current = round(max((sum(m for _d, m in rows) for rows in per_target.values()), default=0.0) / 60.0, 1)
        crossings = [_crossing_date(rows, target * 60.0) for rows in per_target.values()]
        reached = sorted(day for day in crossings if day)
        earned_on = reached[0] if reached else None
    elif rule == 'multi_night_session':
        target = int(threshold or 0)
        lengths = [dates for dates in facts.get('sessions', []) if dates]
        current = min(max((len(dates) for dates in lengths), default=0), target)
        reached = sorted(dates[target - 1] for dates in lengths if len(dates) >= target)
        earned_on = reached[0] if reached else None
    elif rule == 'seasons':
        target = int(threshold or 0)
        current, earned_on = _distinct_progress(
            ((day, season_index(day)) for day in facts.get('activity_dates', [])), target
        )
    elif rule == 'constellations':
        target = int(threshold or 0)
        current, earned_on = _distinct_progress(
            ((capture['first_date'], capture['constellation'] or None) for capture in captures), target
        )
    elif rule == 'hemispheres':
        target = 2
        sides = []
        for capture in captures:
            dec = capture.get('dec_deg')
            if dec is not None and dec != 0:
                sides.append((capture['first_date'], 'north' if dec > 0 else 'south'))
        current, earned_on = _distinct_progress(sides, target)
    elif rule in ('dark_site', 'new_moon_night'):
        target = 1
        days = [night['date'] for night in facts.get('nights', []) if _night_qualifies(rule, night)]
        current = min(len(days), 1)
        earned_on = _nth_date(days, 1)
    else:
        logger.warning(f'Unknown badge rule {rule!r} for badge {definition.get("id")!r}')
        return None

    earned = current >= target
    return {
        'current': current,
        'target': target,
        'earned': earned,
        'earned_on': earned_on if earned else None,
    }


def _night_qualifies(rule: str, night: dict[str, Any]) -> bool:
    if rule == 'dark_site':
        bortle = night.get('bortle')
        sqm = night.get('sqm')
        return (bortle is not None and bortle <= definitions.DARK_SITE_MAX_BORTLE) or (
            sqm is not None and sqm >= definitions.DARK_SITE_MIN_SQM
        )
    moon = night.get('moon_illumination_percent')
    return moon is not None and moon <= definitions.NEW_MOON_MAX_ILLUMINATION


def evaluate_badges(
    facts: dict[str, Any],
    totals: dict[str, int],
    badge_definitions: Sequence[dict[str, Any]] = definitions.BADGE_DEFINITIONS,
) -> list[dict[str, Any]]:
    """Every badge that can be evaluated, earned or not, in definition order.

    A catalogue badge whose catalogue the dataset does not carry (or carries with fewer
    objects than the tier asks) is left out rather than shown unreachable.
    """
    badges: list[dict[str, Any]] = []
    tiers: dict[str, int] = {}
    for definition in badge_definitions:
        result = _evaluate(definition, facts, totals)
        if result is None:
            continue
        family = definition['family']
        tiers[family] = tiers.get(family, 0) + 1
        badge = {
            'id': definition['id'],
            'family': family,
            'group': definition['group'],
            'rule': definition['rule'],
            'icon': definition['icon'],
            'tier': tiers[family],
            'catalogue': definition.get('catalogue'),
            'object_class': definition.get('object_class'),
            'complete_catalogue': definition['rule'] == 'catalogue_count' and definition.get('threshold') is None,
        }
        badge.update(result)
        badges.append(badge)
    return badges


def next_within_reach(badges: Sequence[dict[str, Any]], limit: int = NEXT_WITHIN_REACH_LIMIT) -> list[dict[str, Any]]:
    """The closest unearned milestones: the lowest open tier of each family, nearest first.

    Families with no progress at all are skipped (a stranger's "0 of 50 Sharpless" is not
    within reach of anything), and so are the one-off condition badges, which depend on the
    sky rather than on effort.
    """
    candidates: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for badge in badges:
        if badge['earned'] or badge['family'] in seen_families:
            continue
        seen_families.add(badge['family'])
        if badge['group'] == definitions.GROUP_CONDITIONS or not badge['current']:
            continue
        candidates.append(badge)
    candidates.sort(key=lambda badge: (-(float(badge['current']) / float(badge['target'])), badge['target']))
    return candidates[: max(0, int(limit))]


def summarize(badges: Sequence[dict[str, Any]], seen_ids: Iterable[str] = ()) -> dict[str, Any]:
    """Counters for the page header, plus which earned badges the user has not seen yet."""
    seen = set(seen_ids or ())
    earned = [badge for badge in badges if badge['earned']]
    return {
        'earned': len(earned),
        'total': len(badges),
        'new_ids': [badge['id'] for badge in earned if badge['id'] not in seen],
    }


def catalogue_progress(
    facts: dict[str, Any], totals: dict[str, int], catalogues: Sequence[str]
) -> list[dict[str, Any]]:
    """Captured count per catalogue, for the catalogues that exist in the dataset."""
    captures = list(facts.get('captures', {}).values())
    rows = []
    for catalogue in catalogues:
        size = int(totals.get(catalogue, 0) or 0)
        if size <= 0:
            continue
        captured = sum(1 for capture in captures if catalogue in capture['catalogues'])
        rows.append({'catalogue': catalogue, 'captured': captured, 'total': size})
    return rows


def catalogue_pictures(
    facts: dict[str, Any],
    astrodex_items: Sequence[dict[str, Any]],
    catalogue: str,
    limit: int = 9,
) -> list[str]:
    """Cover picture filenames of the user's captured objects of *catalogue*, oldest capture first.

    Used for the montage of a catalogue badge's share card; objects without an Astrodex
    picture are simply not in it.
    """
    items_by_id = {_as_text(item.get('id')): item for item in astrodex_items if isinstance(item, dict)}
    members = sorted(
        (capture for capture in facts.get('captures', {}).values() if catalogue in capture['catalogues']),
        key=lambda capture: (capture['first_date'] == '', capture['first_date']),
    )
    filenames: list[str] = []
    for capture in members:
        item = items_by_id.get(_as_text(capture.get('astrodex_item_id')))
        pictures = [picture for picture in _dicts((item or {}).get('pictures')) if _as_text(picture.get('filename'))]
        if not pictures:
            continue
        cover = next((picture for picture in pictures if picture.get('is_main')), pictures[0])
        filenames.append(_as_text(cover.get('filename')))
        if len(filenames) >= limit:
            break
    return filenames
