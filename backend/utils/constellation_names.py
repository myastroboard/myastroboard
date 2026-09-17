"""Canonical IAU constellation abbreviation -> full display name expansion.

The SkyTonight dataset stores IAU abbreviations (``"Cyg"``), the frontend's
``constellations`` i18n namespace is keyed on full names (``"Cygnus"``), and records
frozen from a user action (Plan My Night targets, Observation Log entries, Astrodex
items) carry whichever of the two their source happened to hand over.

This module is the single place that bridges the two. It lives in ``utils/`` rather than
in any feature package because three feature/route modules need it and a shared helper
must not create a feature-to-feature import (see ``docs/EXTENDING.md``) - which is
exactly why the table used to exist as separate copies in ``observation/beginner_catalog.py``
and ``blueprints/skytonight_api.py``, each with a comment about dodging a circular import.
"""

from typing import Any, Dict
import re

from constellation import Constellation as _Constellation

# "CanesVenatici" -> "Canes Venatici": the enum member names are concatenated words.
_CAMEL_BOUNDARY = re.compile(r'(?<!^)(?=[A-Z])')


def _humanize(name: str) -> str:
    return _CAMEL_BOUNDARY.sub(' ', name)


def _build_abbreviation_map() -> Dict[str, str]:
    mapping = {str(item.abbr): _humanize(item.name) for item in _Constellation if item.abbr is not None}
    # Serpens is the one constellation split into two disjoint areas; the dataset
    # distinguishes them, the enum does not.
    mapping['Se1'] = 'Serpens Caput'
    mapping['Se2'] = 'Serpens Cauda'
    return mapping


ABBREVIATION_TO_NAME: Dict[str, str] = _build_abbreviation_map()

# Lowercased full name -> canonical full name, so an already-expanded value in any casing
# ("cygnus", "CYGNUS") normalizes to the exact spelling the i18n keys use.
_NAME_BY_LOWERCASE: Dict[str, str] = {value.lower(): value for value in ABBREVIATION_TO_NAME.values()}


def full_constellation_name(value: Any) -> str:
    """Expand *value* to its full IAU constellation name.

    Accepts an abbreviation (``"And"``), an already-expanded name in any casing
    (``"andromeda"``), or an empty/unknown value. Unknown non-empty values are returned
    stripped but otherwise unchanged, so a name this table does not know about still
    displays rather than disappearing.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    expanded = ABBREVIATION_TO_NAME.get(text)
    if expanded:
        return expanded
    return _NAME_BY_LOWERCASE.get(text.lower(), text)
