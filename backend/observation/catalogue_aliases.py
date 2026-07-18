"""Catalogue aliases resolver for cross-catalogue object matching."""

import json
import os
import re
from typing import Dict, Optional

from utils.logging_config import get_logger

from skytonight import skytonight_targets

logger = get_logger(__name__)

ALIASES_FILE = os.path.join(os.path.dirname(__file__), '..', 'catalogue_aliases.json')

_aliases_cache: Dict = {}
_aliases_mtime: Optional[float] = None


def normalize_object_name(name: str) -> str:
    """Normalize object name for stable matching."""
    if not name:
        return ''
    normalized = re.sub(r'[^a-z0-9]+', '', str(name).strip().lower())
    return normalized


def make_lookup_key(catalogue: str, object_name: str) -> str:
    """Build lookup key used in generated aliases table."""
    return f"{str(catalogue or '').strip().lower()}::{normalize_object_name(object_name)}"


def load_aliases_table(force_reload: bool = False) -> Dict:
    """Load aliases table from backend/catalogue_aliases.json with cache."""
    global _aliases_cache, _aliases_mtime

    if not os.path.exists(ALIASES_FILE):
        return {}

    try:
        current_mtime = os.path.getmtime(ALIASES_FILE)
        if not force_reload and _aliases_cache and _aliases_mtime == current_mtime:
            return _aliases_cache

        with open(ALIASES_FILE, 'r', encoding='utf-8') as file:
            data = json.load(file)

        _aliases_cache = data if isinstance(data, dict) else {}
        _aliases_mtime = current_mtime
        logger.debug(f"Catalogue aliases cache refreshed at mtime={_aliases_mtime}")
        return _aliases_cache
    except Exception as error:
        logger.error(f"Error loading catalogue aliases table: {error}")
        return {}


def get_alias_entry(catalogue: str, object_name: str) -> Dict:
    """Get aliases entry for a given catalogue/object pair."""
    if not catalogue or not object_name:
        return {}

    skytonight_entry = skytonight_targets.get_lookup_entry(catalogue, object_name)
    if skytonight_entry:
        return skytonight_entry

    aliases_table = load_aliases_table()
    lookup = aliases_table.get('lookup', {})
    key = make_lookup_key(catalogue, object_name)
    return lookup.get(key, {}) if isinstance(lookup, dict) else {}


def get_aliases_map(catalogue: str, object_name: str) -> Dict[str, str]:
    """Get aliases map for a catalogue/object pair."""
    entry = get_alias_entry(catalogue, object_name)
    aliases = entry.get('aliases', {}) if isinstance(entry, dict) else {}
    return aliases if isinstance(aliases, dict) else {}


def get_group_id(catalogue: str, object_name: str) -> str:
    """Get stable aliases group id for a catalogue/object pair."""
    entry = get_alias_entry(catalogue, object_name)
    group_id = entry.get('group_id', '') if isinstance(entry, dict) else ''
    return str(group_id or '')


def merge_item_with_alias_entry(item: Dict) -> Dict:
    """Attach runtime aliases metadata from current aliases table."""
    if not isinstance(item, dict):
        return item

    item.pop('catalogue_group_id', None)

    catalogue = item.get('catalogue', '')
    name = item.get('name', '')
    if not catalogue or not name:
        item.pop('catalogue_aliases', None)
        return item

    entry = get_alias_entry(catalogue, name)
    if not entry:
        item.pop('catalogue_aliases', None)
        return item

    aliases = entry.get('aliases', {})

    if isinstance(aliases, dict) and aliases:
        item['catalogue_aliases'] = aliases
    else:
        item.pop('catalogue_aliases', None)

    return item
