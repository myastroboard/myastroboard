"""Beginner Catalog module - curated starter DSO list for astrophotography beginners.

Loads the static, bundled ``backend/catalogues/beginner_catalog.json`` dataset,
resolves its per-object descriptive text via i18n keys, and enriches each entry
with the current user's SkyTonight/Astrodex/Plan My Night state.
"""

import json
import os
import re
from typing import Any, Dict, List

from observation import object_info
from constellation import Constellation as _Constellation
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger
from skytonight.skytonight_storage import get_alttime_dir
from utils import normalize_catalogue_key as _normalize_key

logger = get_logger(__name__)

_CATALOGUES_DIR = os.path.join(os.path.dirname(__file__), '..', 'catalogues')
_BEGINNER_CATALOG_FILE = os.path.join(_CATALOGUES_DIR, 'beginner_catalog.json')

# Same "safe id" sanitization used to name *_alttime.json files, duplicated here rather
# than imported to avoid a circular import (skytonight_api/skytonight_calculator don't
# import this module, but keeping the convention local avoids adding a new cross-module
# dependency just for one regex).
_ALTTIME_ID_SAFE = re.compile(r'[^a-z0-9_-]')


def _alttime_file_for_target(target_id: str, location_id: Any) -> str:
    """Return ``target_id`` if its per-location altitude-time JSON file exists on disk, else ''."""
    if not target_id:
        return ''
    safe_id = _ALTTIME_ID_SAFE.sub('_', target_id.lower())
    path = os.path.join(get_alttime_dir(location_id), f'{safe_id}_alttime.json')
    return target_id if os.path.isfile(path) else ''


def _humanize_const_name(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', name)


# Same abbreviation -> full name conversion used by the DSO endpoints (skytonight_api.py),
# duplicated here rather than imported to avoid a circular import (skytonight_api imports
# this module already).
_CONSTELLATION_ABBR_MAP: Dict[str, str] = {
    str(c.abbr): _humanize_const_name(c.name) for c in _Constellation if c.abbr is not None
}
_CONSTELLATION_ABBR_MAP['Se1'] = 'Serpens Caput'
_CONSTELLATION_ABBR_MAP['Se2'] = 'Serpens Cauda'


_catalog_cache: Dict[str, Any] = {'data': None, 'key': None}


def load_beginner_catalog() -> List[Dict[str, Any]]:
    """Load and return the static beginner catalog dataset.

    Returns an empty list (and logs a warning) if the bundled file is missing
    or malformed, rather than raising - this dataset is not user-critical.

    The parsed result is cached in memory keyed by (path, mtime) - this file is
    bundled/static in production, so this avoids re-reading and re-parsing it
    on every request while still picking up an on-disk change (or a test
    monkeypatching the file path) automatically.
    """
    if not os.path.exists(_BEGINNER_CATALOG_FILE):
        logger.warning(f'Beginner catalog file not found: {_BEGINNER_CATALOG_FILE}')
        return []

    cache_key = (_BEGINNER_CATALOG_FILE, os.path.getmtime(_BEGINNER_CATALOG_FILE))
    if _catalog_cache['data'] is not None and _catalog_cache['key'] == cache_key:
        return _catalog_cache['data']

    try:
        with open(_BEGINNER_CATALOG_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f'Failed to load beginner catalog file: {e}')
        return []

    if not isinstance(data, list):
        logger.error('Beginner catalog file does not contain a JSON list')
        return []

    _catalog_cache['data'], _catalog_cache['key'] = data, cache_key
    return data


def translate_catalog_entries(catalog: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    """Return a new list of catalog entries with ``why_beginner``/``suggested_framing`` resolved via i18n.

    Args:
        catalog: Raw catalog entries as returned by :func:`load_beginner_catalog`.
        lang: Language code to resolve text in (falls back to English per ``I18nManager``).
    """
    manager = I18nManager(lang)
    translated = []
    for entry in catalog:
        i18n_key = entry.get('i18n_key', '')
        new_entry = dict(entry)
        new_entry['why_beginner'] = manager.t(f'beginner_catalog.objects.{i18n_key}.why')
        new_entry['suggested_framing'] = manager.t(f'beginner_catalog.objects.{i18n_key}.framing')
        const_abbr = entry.get('constellation')
        new_entry['constellation'] = (
            _CONSTELLATION_ABBR_MAP.get(const_abbr, const_abbr) if isinstance(const_abbr, str) else const_abbr
        )
        translated.append(new_entry)
    return translated


def _build_dso_lookup(dso_results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build a normalized-name -> DSO result entry lookup from ``dso_results.json`` content."""
    lookup: Dict[str, Dict[str, Any]] = {}
    for item in dso_results.get('deep_sky', []) if isinstance(dso_results, dict) else []:
        catalogue_names = item.get('catalogue_names', {})
        if not isinstance(catalogue_names, dict):
            continue
        for name in catalogue_names.values():
            key = _normalize_key(name)
            if key:
                lookup[key] = item
    return lookup


def _build_name_key_set(items: List[Dict[str, Any]], name_fields: List[str]) -> set:
    """Build a set of normalized keys from a list of item dicts, over multiple possible field names."""
    keys = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for field_name in name_fields:
            key = _normalize_key(item.get(field_name))
            if key:
                keys.add(key)
    return keys


def enrich_with_skytonight(
    catalog: List[Dict[str, Any]],
    dso_results: Dict[str, Any],
    user_astrodex_items: List[Dict[str, Any]],
    user_plan_entries: List[Dict[str, Any]],
    location_id: Any = None,
) -> List[Dict[str, Any]]:
    """Add ``visible_tonight``, ``astro_score``, ``in_astrodex`` and ``in_plan`` to each catalog entry.

    Args:
        catalog: Translated catalog entries (output of :func:`translate_catalog_entries`).
        dso_results: Parsed content of ``dso_results.json`` (may be empty/missing).
        user_astrodex_items: The current user's Astrodex items (``astrodex.load_user_astrodex()['items']``).
        user_plan_entries: The current user's Plan My Night entries.
        location_id: Active location id, used to resolve the per-location altitude-time
            JSON directory for the ``alttime_file`` field.
    """
    dso_lookup = _build_dso_lookup(dso_results)
    astrodex_keys = _build_name_key_set(user_astrodex_items, ['name', 'catalogue'])
    plan_keys = _build_name_key_set(user_plan_entries, ['name', 'catalogue', 'target_name'])

    enriched = []
    for entry in catalog:
        new_entry = dict(entry)
        catalogue_key = _normalize_key(entry.get('catalogue_id'))
        name_key = _normalize_key(entry.get('preferred_name'))

        dso_match = dso_lookup.get(catalogue_key)
        new_entry['visible_tonight'] = dso_match is not None
        new_entry['astro_score'] = dso_match.get('astro_score') if dso_match else None
        new_entry['alttime_file'] = (
            _alttime_file_for_target(dso_match.get('target_id', ''), location_id) if dso_match else ''
        )

        # Every catalog entry has its own fixed coordinates, so the thumbnail can be
        # resolved directly rather than making the client re-resolve the object via a
        # full SIMBAD/Wikipedia lookup just to recover an image URL.
        ra_hours = entry.get('ra_hours')
        dec_degrees = entry.get('dec_degrees')
        new_entry['thumbnail_url'] = (
            object_info.get_object_image_proxy_url(ra_hours * 15.0, dec_degrees)
            if ra_hours is not None and dec_degrees is not None
            else None
        )

        # Match against every known alias for this object (not just its own
        # catalogue_id/preferred_name), so an astrodex/plan entry saved under a
        # different alias of the same object (e.g. "NGC1976" for "M42") is still
        # recognized as captured/planned.
        match_keys = {catalogue_key, name_key}
        if dso_match:
            match_keys.update(_normalize_key(alias) for alias in dso_match.get('catalogue_names', {}).values())
        match_keys.discard('')

        new_entry['in_astrodex'] = bool(match_keys & astrodex_keys)
        new_entry['in_plan'] = bool(match_keys & plan_keys)

        enriched.append(new_entry)

    return enriched
