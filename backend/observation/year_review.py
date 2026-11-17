"""Year in review (v1.9) - one year of the user's own record, told as a short story.

Every figure comes from the same facts the badges use (``achievements.collect_progress``)
and from the Observation Log itself; nothing is stored and nothing is estimated. A screen
the year has no data for comes back as ``None`` and the frontend hides it, so a user with
two sessions sees two honest screens rather than five empty ones.

"The year" is the calendar year of the observing nights: a night is attributed to its
own ``date``, which the Observation Log records in the observer's local calendar, so a
session at 01:30 on the 1st of January belongs to the night of the 31st of December when
the user logged it that way, in either hemisphere.

There is no comparison with other users - no such base exists, and the review never
invents one. The only comparison is with the user's own previous year, when it exists.
"""

import math
from collections.abc import Sequence
from typing import Any

from observation import session_analytics
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Catalogues the progress screen always reports when the user has captured any of them;
# other catalogues appear only in a year the user added objects to them.
REVIEW_CATALOGUES: tuple[str, ...] = ('Messier', 'Caldwell', 'Herschel400', 'Sharpless', 'Arp', 'Barnard')

# How many pictures the closing mosaic holds (a 3 x 3 grid at most).
MOSAIC_LIMIT = 9


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


def _round(value: float, digits: int = 1) -> float:
    return round(value + 0.0, digits)


def _in_year(day: str, year: int) -> bool:
    return day[:4] == f'{year:04d}'


def available_years(facts: dict[str, Any]) -> list[int]:
    """Every year with at least one dated capture or integration, most recent first."""
    years: set[int] = set()
    days = list(facts.get('activity_dates', [])) + [day for day, _minutes, _key in facts.get('integration', [])]
    for day in days:
        if len(day) >= 4 and day[:4].isdigit():
            years.add(int(day[:4]))
    return sorted(years, reverse=True)


def _year_figures(facts: dict[str, Any], year: int) -> dict[str, Any]:
    """Integration, capture days and objects of one year, from the shared facts."""
    minutes_by_key: dict[str, float] = {}
    total_minutes = 0.0
    for day, minutes, key in facts.get('integration', []):
        if _in_year(day, year):
            total_minutes += minutes
            minutes_by_key[key] = minutes_by_key.get(key, 0.0) + minutes

    days_by_key: dict[str, set[str]] = {}
    for day, key in facts.get('capture_days', []):
        if _in_year(day, year):
            days_by_key.setdefault(key, set()).add(day)

    return {
        'integration_minutes': total_minutes,
        'minutes_by_key': minutes_by_key,
        'days_by_key': days_by_key,
        'keys': set(days_by_key) | set(minutes_by_key),
    }


def _log_nights(sessions: Sequence[dict[str, Any]], year: int) -> dict[tuple[str, str], dict[str, Any]]:
    """Every logged night of *year* that has at least one entry, with its entries."""
    nights: dict[tuple[str, str], dict[str, Any]] = {}
    for session, night, entry in session_analytics.iter_entries(sessions):
        day = session_analytics.entry_date(night)
        if not _in_year(day, year):
            continue
        key = (_as_text(session.get('id')), _as_text(night.get('id')) or day)
        bucket = nights.setdefault(
            key,
            {
                'date': day,
                'session': session,
                'night': night,
                'entries': [],
            },
        )
        bucket['entries'].append(entry)
    return nights


def _best_picture(item: dict[str, Any], year: int | None) -> dict[str, Any] | None:
    """The item's picture to show: one taken in *year* if any, best rated first, else its cover."""
    pictures = [picture for picture in item.get('pictures') or [] if isinstance(picture, dict)]
    pictures = [picture for picture in pictures if _as_text(picture.get('filename'))]
    if not pictures:
        return None
    if year is not None:
        dated = [picture for picture in pictures if _in_year(_as_text(picture.get('date'))[:10], year)]
        if dated:
            return max(dated, key=_picture_rank)
    main = next((picture for picture in pictures if picture.get('is_main')), None)
    return main or pictures[0]


def _picture_rank(picture: dict[str, Any]) -> tuple[float, float, str]:
    rating = _as_float(picture.get('rating'))
    minutes = _as_float(picture.get('integration_minutes'))
    return (rating if rating is not None else -1.0, minutes or 0.0, _as_text(picture.get('date')))


def _picture_ref(item: dict[str, Any], picture: dict[str, Any]) -> dict[str, Any]:
    return {
        'filename': _as_text(picture.get('filename')),
        'name': _as_text(item.get('name')),
        'date': _as_text(picture.get('date'))[:10],
        'rating': _as_float(picture.get('rating')),
    }


def _favourite_class(facts: dict[str, Any], figures: dict[str, Any]) -> dict[str, Any] | None:
    captures = facts.get('captures', {})
    classes: dict[str, dict[str, float]] = {}
    for key in figures['keys']:
        capture = captures.get(key)
        if capture is None:
            continue
        bucket = classes.setdefault(capture['object_class'], {'objects': 0, 'minutes': 0.0})
        bucket['objects'] += 1
        bucket['minutes'] += figures['minutes_by_key'].get(key, 0.0)
    if not classes:
        return None
    name, bucket = max(classes.items(), key=lambda pair: (pair[1]['minutes'], pair[1]['objects'], pair[0]))
    return {
        'object_class': name,
        'objects': int(bucket['objects']),
        'integration_minutes': _round(bucket['minutes']),
        'classes': len(classes),
    }


def _target_of_year(
    facts: dict[str, Any],
    figures: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    year: int,
) -> dict[str, Any] | None:
    minutes_by_key = figures['minutes_by_key']
    if not minutes_by_key:
        return None
    key, minutes = max(minutes_by_key.items(), key=lambda pair: (pair[1], pair[0]))
    if minutes <= 0:
        return None
    capture = facts.get('captures', {}).get(key, {})
    picture = None
    item = items_by_id.get(_as_text(capture.get('astrodex_item_id')))
    if item is not None:
        chosen = _best_picture(item, year)
        picture = _picture_ref(item, chosen) if chosen else None
    return {
        'key': key,
        'name': capture.get('name') or key,
        'preferred_name': capture.get('preferred_name') or capture.get('name') or key,
        'object_type': capture.get('object_type', ''),
        'object_class': capture.get('object_class', ''),
        'constellation': capture.get('constellation', ''),
        'integration_minutes': _round(minutes),
        'nights': len(figures['days_by_key'].get(key, set())),
        'picture': picture,
    }


def _best_night(nights: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    """The longest logged night of the year; the best rated breaks a tie."""
    best: tuple[tuple[float, float], dict[str, Any]] | None = None
    for bucket in nights.values():
        minutes = sum(session_analytics.entry_integration_minutes(entry) for entry in bucket['entries'])
        ratings = [rating for rating in map(session_analytics.entry_rating, bucket['entries']) if rating is not None]
        average = sum(ratings) / len(ratings) if ratings else None
        rank = (minutes, average if average is not None else -1.0)
        if minutes <= 0 and average is None:
            continue
        if best is None or rank > best[0]:
            best = (rank, {**bucket, 'minutes': minutes, 'average_rating': average})
    if best is None:
        return None

    bucket = best[1]
    night = bucket['night']
    session = bucket['session']
    names = []
    for entry in bucket['entries']:
        name = _as_text(entry.get('name'))
        if name and name not in names:
            names.append(name)
    combination_names = {session_analytics.effective_combination(session, entry)[1] for entry in bucket['entries']} - {
        ''
    }
    return {
        'date': bucket['date'],
        'integration_minutes': _round(bucket['minutes']),
        'average_rating': _round(bucket['average_rating']) if bucket['average_rating'] is not None else None,
        'targets': names,
        'target_count': len(names),
        'sqm': _as_float(night.get('sqm')),
        'seeing': _as_float(night.get('seeing')),
        'transparency': _as_float(night.get('transparency')),
        'moon_illumination_percent': _as_float(night.get('moon_illumination_percent')),
        'combination_name': sorted(combination_names)[0] if len(combination_names) == 1 else None,
    }


def _equipment(nights: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    """The equipment combination that collected the most light this year (named ones only)."""
    minutes_by_name: dict[str, float] = {}
    nights_by_name: dict[str, set[tuple[str, str]]] = {}
    total = 0.0
    for night_key, bucket in nights.items():
        for entry in bucket['entries']:
            minutes = session_analytics.entry_integration_minutes(entry)
            total += minutes
            _combination_id, name = session_analytics.effective_combination(bucket['session'], entry)
            if not name or minutes <= 0:
                continue
            minutes_by_name[name] = minutes_by_name.get(name, 0.0) + minutes
            nights_by_name.setdefault(name, set()).add(night_key)
    if not minutes_by_name or total <= 0:
        return None
    name, minutes = max(minutes_by_name.items(), key=lambda pair: (pair[1], pair[0]))
    return {
        'combination_name': name,
        'integration_minutes': _round(minutes),
        'nights': len(nights_by_name[name]),
        'share_percent': int(round(100.0 * minutes / total)),
        'combinations_used': len(minutes_by_name),
    }


def _catalogue_progress(facts: dict[str, Any], totals: dict[str, int], year: int) -> list[dict[str, Any]]:
    """Per catalogue: objects captured by the end of *year*, and how many of them were new.

    An undated capture counts as captured before the year: it cannot be claimed as this
    year's progress.
    """
    year_end = f'{year:04d}-12-31'
    year_start = f'{year:04d}-01-01'
    captures = list(facts.get('captures', {}).values())
    rows = []
    for catalogue in REVIEW_CATALOGUES:
        size = int(totals.get(catalogue, 0) or 0)
        if size <= 0:
            continue
        members = [capture for capture in captures if catalogue in capture['catalogues']]
        by_end = [capture for capture in members if not capture['first_date'] or capture['first_date'] <= year_end]
        before = [capture for capture in by_end if not capture['first_date'] or capture['first_date'] < year_start]
        gained = len(by_end) - len(before)
        if not by_end:
            continue
        if gained <= 0 and catalogue != 'Messier':
            continue
        rows.append({'catalogue': catalogue, 'captured': len(by_end), 'gained': gained, 'total': size})
    return rows


def _mosaic(astrodex_items: Sequence[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    """The year's pictures, one per object, best rated first."""
    picks = []
    for item in astrodex_items:
        if not isinstance(item, dict):
            continue
        pictures = [
            picture
            for picture in item.get('pictures') or []
            if isinstance(picture, dict)
            and _as_text(picture.get('filename'))
            and _in_year(_as_text(picture.get('date'))[:10], year)
        ]
        if pictures:
            picture = max(pictures, key=_picture_rank)
            picks.append((_picture_rank(picture), _picture_ref(item, picture)))
    picks.sort(key=lambda pair: pair[0], reverse=True)
    return [ref for _rank, ref in picks[:MOSAIC_LIMIT]]


def build_year_review(
    sessions: Sequence[dict[str, Any]],
    astrodex_items: Sequence[dict[str, Any]],
    year: int,
    facts: dict[str, Any],
    totals: dict[str, int],
) -> dict[str, Any]:
    """Every screen of one year's review. A screen without data is ``None`` (or empty)."""
    figures = _year_figures(facts, year)
    log_nights = _log_nights(sessions, year)
    captured_log_nights = {
        key: bucket
        for key, bucket in log_nights.items()
        if any(session_analytics.entry_is_captured(entry) for entry in bucket['entries'])
    }
    capture_days = {day for day, _key in facts.get('capture_days', []) if _in_year(day, year)}
    night_count = len(captured_log_nights) or len(capture_days)
    source = 'log' if captured_log_nights else ('astrodex' if figures['keys'] else None)

    captures = facts.get('captures', {})
    new_keys = [key for key, capture in captures.items() if _in_year(capture.get('first_date', ''), year)]
    items_by_id = {
        _as_text(item.get('id')): item for item in astrodex_items if isinstance(item, dict) and item.get('id')
    }

    previous_figures = _year_figures(facts, year - 1)
    previous = None
    if previous_figures['keys']:
        previous = {
            'year': year - 1,
            'integration_minutes': _round(previous_figures['integration_minutes']),
            'targets': len(previous_figures['keys']),
        }

    has_data = bool(figures['keys'])
    return {
        'year': year,
        'available_years': available_years(facts),
        'has_data': has_data,
        'source': source,
        'totals': {
            'integration_minutes': _round(figures['integration_minutes']),
            'nights': night_count,
            'sessions': len({key[0] for key in captured_log_nights}),
            'targets': len(figures['keys']),
            'new_targets': len(new_keys),
        }
        if has_data
        else None,
        'favourite_class': _favourite_class(facts, figures) if has_data else None,
        'target_of_year': _target_of_year(facts, figures, items_by_id, year) if has_data else None,
        'best_night': _best_night(captured_log_nights),
        'equipment': _equipment(log_nights),
        'catalogues': _catalogue_progress(facts, totals, year) if has_data else [],
        'previous_year': previous if has_data else None,
        'mosaic': _mosaic(astrodex_items, year),
    }
