"""Resolve a frozen target record to numeric equatorial coordinates.

Plan My Night entries, Observation Log entries and wishlist candidates all carry a
*frozen snapshot* of their target's identity, including ``ra`` / ``dec``. Those two
fields are **not** a reliable numeric source: ``plan_my_night._build_target_payload()``
stores ``item_data.get('ra') or item_data.get('right ascension')``, and the two frontend
paths that feed it disagree -

* the SkyTonight target cards send ``target.coordinates.ra_hours`` - a decimal-hours float;
* the SkyTonight result tables send the ``'right ascension'`` column, which
  ``blueprints/skytonight_api.py`` fills with the formatted ``ra_hms`` string
  (``"21h 31m 48.32s"``).

Astrodex items are worse: ``astrodex.UNUSED_ITEM_FIELDS`` strips ``ra``/``dec`` on every
write, so they carry no coordinates at all.

Resolution order (first hit wins), used by every consumer so the behaviour is identical
everywhere:

1. the SkyTonight dataset lookup, which carries canonical numeric ``ra_deg``/``dec_deg``;
2. parsing whatever the record itself stored, in either observed shape;
3. give up - the caller counts the miss and reports it rather than dropping it silently.

The sexagesimal parsing here deliberately does not reuse ``utils.dms_to_decimal``: that
helper accepts neither the ``h m s`` nor the colon-separated form, and it mis-signs a
value whose degrees field is a negative zero (``"-00d30m00s"`` returns ``+0.5``, because
``float("-00") < 0`` is False). It currently has no production callers, so it is left
alone rather than changed from an unrelated branch.
"""

import math
import re
from typing import Any, Dict, Optional, Tuple

from observation.astrodex import _extract_name_candidates
from skytonight import skytonight_targets
from utils.logging_config import get_logger

logger = get_logger(__name__)

# "21h 31m 48.32s", "21:31:48.32", "48d 26m 17.4s", "48 26 17.4", "-00 30 00".
# The sign is captured separately from the leading field so a "-0" degrees value keeps
# its sign (see the module docstring).
_SEXAGESIMAL = re.compile(
    r"""^\s*
    (?P<sign>[+-])?\s*
    (?P<first>\d+(?:\.\d+)?)\s*[hd°:\s]\s*
    (?P<second>\d+(?:\.\d+)?)\s*[m'′:\s]?\s*
    (?:(?P<third>\d+(?:\.\d+)?)\s*["s″]?)?
    \s*$""",
    re.VERBOSE,
)

# A numeric right ascension coming from the frontend is in decimal *hours*
# (``coordinates.ra_hours``). A value above this can only be degrees, so it is read as
# such rather than silently wrapping past the end of the sky.
_MAX_RA_HOURS = 24.0


def _sexagesimal_to_float(value: str) -> Optional[float]:
    """Parse a sexagesimal string into a signed decimal value in its leading unit."""
    match = _SEXAGESIMAL.match(value)
    if not match:
        return None
    try:
        first = float(match.group('first'))
        second = float(match.group('second'))
        third = float(match.group('third') or 0.0)
    except (TypeError, ValueError):
        return None
    if second >= 60.0 or third >= 60.0:
        return None
    magnitude = first + second / 60.0 + third / 3600.0
    return -magnitude if match.group('sign') == '-' else magnitude


def _as_finite_float(value: Any) -> Optional[float]:
    """Return *value* as a float when it already is a real number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def parse_ra_to_degrees(value: Any) -> Optional[float]:
    """Parse a stored right ascension into degrees in ``[0, 360)``.

    Accepts a decimal-hours number, an ``"21h 31m 48.32s"`` / ``"21:31:48.32"`` string, or
    a bare decimal string. Returns None when the value is absent or unparseable.
    """
    number = _as_finite_float(value)
    if number is None:
        text = str(value or '').strip()
        if not text:
            return None
        hours = _sexagesimal_to_float(text)
        if hours is None:
            try:
                hours = float(text)
            except ValueError:
                return None
    else:
        hours = number

    if hours < 0.0:
        return None
    degrees = hours if hours > _MAX_RA_HOURS else hours * 15.0
    if degrees > 360.0:
        return None
    # 24h and 360 deg are both the 0 point, not one past the end of the sky.
    return degrees % 360.0


def parse_dec_to_degrees(value: Any) -> Optional[float]:
    """Parse a stored declination into degrees in ``[-90, 90]``.

    Accepts a decimal-degrees number, a ``"48° 26' 17.40\\""`` / ``"-05:12:33"``
    string, or a bare decimal string. Returns None when absent or unparseable.
    """
    degrees = _as_finite_float(value)
    if degrees is None:
        text = str(value or '').strip()
        if not text:
            return None
        degrees = _sexagesimal_to_float(text)
        if degrees is None:
            try:
                degrees = float(text)
            except ValueError:
                return None

    if degrees < -90.0 or degrees > 90.0:
        return None
    return degrees


def _coordinates_from_lookup_entry(entry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Read ``ra_deg``/``dec_deg`` off a SkyTonight lookup entry, if both are usable."""
    if not isinstance(entry, dict):
        return None
    ra_deg = _as_finite_float(entry.get('ra_deg'))
    dec_deg = _as_finite_float(entry.get('dec_deg'))
    if ra_deg is None or dec_deg is None:
        return None
    if not 0.0 <= ra_deg < 360.0 or not -90.0 <= dec_deg <= 90.0:
        return None
    return ra_deg, dec_deg


def lookup_dataset_entry(name: Any, catalogue: Any = '') -> Dict[str, Any]:
    """Return the SkyTonight lookup entry for *name*, or ``{}`` when it is not in the dataset.

    Tries the record's own catalogue first, then every identifier that can be pulled out
    of a display label - Astrodex stores items as ``"M31 - Andromeda Galaxy"``, so the
    bare identifier has to be extracted before the lookup can match. ``get_lookup_entry``
    falls back to alias and preferred-name keys internally, so a wrong-but-non-empty
    catalogue still resolves; ``'preferred'`` is passed when the record has none.
    """
    label = str(name or '').strip()
    if not label:
        return {}

    catalogue_key = str(catalogue or '').strip() or 'preferred'
    candidates = [label] + [candidate for candidate in _extract_name_candidates(label) if candidate != label]
    for candidate in candidates:
        entry = skytonight_targets.get_lookup_entry(catalogue_key, candidate)
        if isinstance(entry, dict) and entry:
            return entry
    return {}


def resolve_from_dataset(name: Any, catalogue: Any = '') -> Optional[Tuple[float, float]]:
    """Look *name* up in the SkyTonight dataset and return its ``(ra_deg, dec_deg)``."""
    label = str(name or '').strip()
    if not label:
        return None

    catalogue_key = str(catalogue or '').strip() or 'preferred'
    candidates = [label] + [candidate for candidate in _extract_name_candidates(label) if candidate != label]
    for candidate in candidates:
        coordinates = _coordinates_from_lookup_entry(skytonight_targets.get_lookup_entry(catalogue_key, candidate))
        if coordinates is not None:
            return coordinates
    return None


def resolve_coordinates(
    name: Any,
    catalogue: Any = '',
    ra: Any = None,
    dec: Any = None,
) -> Optional[Tuple[float, float]]:
    """Resolve a frozen target record to ``(ra_deg, dec_deg)``, or None if it cannot be.

    Applies the module's documented resolution order: dataset lookup first (canonical),
    then the record's own stored ``ra``/``dec`` in whichever shape it happens to be in.
    """
    from_dataset = resolve_from_dataset(name, catalogue)
    if from_dataset is not None:
        return from_dataset

    ra_deg = parse_ra_to_degrees(ra)
    dec_deg = parse_dec_to_degrees(dec)
    if ra_deg is None or dec_deg is None:
        return None
    return ra_deg, dec_deg


def resolve_target(
    name: Any,
    catalogue: Any = '',
    ra: Any = None,
    dec: Any = None,
) -> Dict[str, Any]:
    """Resolve a frozen target record to the identity + coordinates its consumers need.

    Used by the sky coverage map (which has to fold Observation Log entries and Astrodex
    items into one set of points) and by wishlist creation (which stamps the resolved
    values onto the stored item so the visibility pass is a pure numeric loop).

    ``group_id`` is the dataset's cross-catalogue identity when the object is known, so
    "M 31" logged as an entry and "M31 - Andromeda Galaxy" sitting in Astrodex collapse to
    one object. It is empty for an object the dataset does not carry; callers fall back to
    the normalized name in that case.

    Returns a dict that is always complete: ``resolved`` says whether the dataset knew the
    object, ``placed`` whether usable coordinates were found at all.
    """
    entry = lookup_dataset_entry(name, catalogue)
    coordinates = _coordinates_from_lookup_entry(entry)
    if coordinates is None:
        ra_deg = parse_ra_to_degrees(ra)
        dec_deg = parse_dec_to_degrees(dec)
        coordinates = (ra_deg, dec_deg) if ra_deg is not None and dec_deg is not None else None

    return {
        'group_id': str(entry.get('group_id') or '') if entry else '',
        'target_id': str(entry.get('target_id') or '') if entry else '',
        'preferred_name': str(entry.get('preferred_name') or '') if entry else '',
        'object_type': str(entry.get('object_type') or '') if entry else '',
        'constellation': str(entry.get('constellation') or '') if entry else '',
        'category': str(entry.get('category') or '') if entry else '',
        'ra_deg': coordinates[0] if coordinates else None,
        'dec_deg': coordinates[1] if coordinates else None,
        'resolved': bool(entry),
        'placed': coordinates is not None,
    }
