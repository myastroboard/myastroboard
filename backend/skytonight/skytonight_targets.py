"""SkyTonight target dataset access and compatibility helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from utils.constants import SKYTONIGHT_DATASET_FILE, SKYTONIGHT_PREFERRED_NAME_ORDER
from utils.logging_config import get_logger
from skytonight.skytonight_models import SkyTonightTarget
from utils import load_json_file, save_json_file

logger = get_logger(__name__)

_dataset_cache: Dict[str, Any] = {}


def invalidate_targets_dataset_cache() -> None:
    """Clear the in-memory targets dataset cache.

    Use this after rebuilding dataset files so the next read reloads fresh
    objects from disk and old large lists can be reclaimed by GC.
    """
    global _dataset_cache
    _dataset_cache = {}


def normalize_catalogue_name(value: str) -> str:
    """Normalize catalogue labels for stable comparisons."""
    return ' '.join(str(value or '').strip().split())


def normalize_object_name(value: str) -> str:
    """Normalize object names for stable comparisons and duplicate checks."""
    filtered = ''.join(character for character in str(value or '').strip().lower() if character.isalnum())
    return filtered


def _catalogue_priority(catalogue: str, order: Optional[List[str]] = None) -> Tuple[int, str]:
    normalized = normalize_catalogue_name(catalogue)
    effective_order = order if order is not None else SKYTONIGHT_PREFERRED_NAME_ORDER
    try:
        return (effective_order.index(normalized), normalized.lower())
    except ValueError:
        return (len(effective_order), normalized.lower())


def choose_preferred_catalogue_name(catalogue_names: Dict[str, str], order: Optional[List[str]] = None) -> str:
    """Choose the display name using the SkyTonight catalogue priority.

    Parameters
    ----------
    catalogue_names:
        Dict of catalogue label → name string (e.g. ``{'Messier': 'M 31', 'OpenNGC': 'NGC 224'}``).
    order:
        Optional list of catalogue labels defining the preference order.
        When *None* the module-level :data:`SKYTONIGHT_PREFERRED_NAME_ORDER` constant is used.
    """
    if not isinstance(catalogue_names, dict) or not catalogue_names:
        return ''

    best_catalogue = sorted(catalogue_names.keys(), key=lambda c: _catalogue_priority(c, order))[0]
    return str(catalogue_names.get(best_catalogue, '') or '').strip()


def _build_lookup_entry(target: SkyTonightTarget) -> Dict[str, Any]:
    aliases = {
        normalize_catalogue_name(key): str(value) for key, value in target.catalogue_names.items() if str(value).strip()
    }
    group_id = target.target_id
    coords = target.coordinates
    return {
        'group_id': group_id,
        'aliases': aliases,
        'target_id': group_id,
        'preferred_name': target.preferred_name or choose_preferred_catalogue_name(target.catalogue_names),
        'category': target.category,
        'object_type': target.object_type,
        'constellation': target.constellation,
        'ra_deg': coords.ra_hours * 15.0 if coords else None,
        'dec_deg': coords.dec_degrees if coords else None,
    }


def _append_lookup_name(
    lookup: Dict[str, Dict[str, Any]], catalogue: str, object_name: str, entry: Dict[str, Any]
) -> None:
    normalized_catalogue = normalize_catalogue_name(catalogue)
    normalized_name = normalize_object_name(object_name)
    if not normalized_catalogue or not normalized_name:
        return
    lookup[f'{normalized_catalogue.lower()}::{normalized_name}'] = entry


def build_lookup_from_targets(targets: List[SkyTonightTarget]) -> Dict[str, Dict[str, Any]]:
    """Build a lookup table compatible with legacy alias consumers."""
    lookup: Dict[str, Dict[str, Any]] = {}

    for target in targets:
        entry = _build_lookup_entry(target)

        for catalogue, object_name in target.catalogue_names.items():
            _append_lookup_name(lookup, catalogue, object_name, entry)

        for alias in target.aliases:
            _append_lookup_name(lookup, 'alias', alias, entry)

        preferred_name = target.preferred_name or choose_preferred_catalogue_name(target.catalogue_names)
        if preferred_name:
            _append_lookup_name(lookup, 'preferred', preferred_name, entry)

    return lookup


def _coerce_targets(raw_targets: Any) -> List[SkyTonightTarget]:
    if not isinstance(raw_targets, list):
        return []
    targets: List[SkyTonightTarget] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        try:
            target = SkyTonightTarget.from_dict(item)
        except (TypeError, ValueError) as error:
            logger.warning(f'Invalid SkyTonight target skipped: {error}')
            continue
        if target.target_id:
            targets.append(target)
    return targets


def load_targets_dataset(force_reload: bool = False, dataset_file: Optional[str] = None) -> Dict[str, Any]:
    """Load the persisted SkyTonight dataset and derive compatibility lookup tables."""
    global _dataset_cache

    target_dataset_file = dataset_file or SKYTONIGHT_DATASET_FILE

    if not force_reload and _dataset_cache.get('dataset_file') == target_dataset_file and _dataset_cache.get('loaded'):
        return _dataset_cache

    payload = load_json_file(target_dataset_file, default={})
    targets = _coerce_targets(payload.get('targets', []))
    lookup = build_lookup_from_targets(targets)

    _dataset_cache = {
        'loaded': True,
        'dataset_file': target_dataset_file,
        'metadata': payload.get('metadata', {}) if isinstance(payload.get('metadata', {}), dict) else {},
        'targets': targets,
        'lookup': lookup,
    }
    return _dataset_cache


def save_targets_dataset(
    targets: List[SkyTonightTarget], metadata: Optional[Dict[str, Any]] = None, dataset_file: Optional[str] = None
) -> bool:
    """Persist a normalized SkyTonight dataset to disk."""
    target_dataset_file = dataset_file or SKYTONIGHT_DATASET_FILE
    payload = {
        'metadata': metadata or {},
        'targets': [target.to_dict() for target in targets],
    }
    saved = save_json_file(target_dataset_file, payload)
    if saved:
        load_targets_dataset(force_reload=True, dataset_file=target_dataset_file)
    return saved


def get_lookup_entry(
    catalogue: str,
    object_name: str,
    force_reload: bool = False,
    dataset_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a legacy-compatible lookup entry from the SkyTonight dataset."""
    if not catalogue or not object_name:
        return {}

    dataset = load_targets_dataset(force_reload=force_reload, dataset_file=dataset_file)
    lookup = dataset.get('lookup', {})
    key = f'{normalize_catalogue_name(catalogue).lower()}::{normalize_object_name(object_name)}'
    entry = lookup.get(key, {}) if isinstance(lookup, dict) else {}

    if entry:
        return entry

    alias_key = f'alias::{normalize_object_name(object_name)}'
    preferred_key = f'preferred::{normalize_object_name(object_name)}'
    return lookup.get(alias_key, {}) or lookup.get(preferred_key, {}) or {}


def get_aliases_map(catalogue: str, object_name: str, dataset_file: Optional[str] = None) -> Dict[str, str]:
    entry = get_lookup_entry(catalogue, object_name, dataset_file=dataset_file)
    aliases = entry.get('aliases', {}) if isinstance(entry, dict) else {}
    return aliases if isinstance(aliases, dict) else {}


def get_group_id(catalogue: str, object_name: str, dataset_file: Optional[str] = None) -> str:
    entry = get_lookup_entry(catalogue, object_name, dataset_file=dataset_file)
    return str(entry.get('group_id', '') or '') if isinstance(entry, dict) else ''


def merge_item_with_target_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    """Attach SkyTonight alias metadata to an item in-place for compatibility."""
    if not isinstance(item, dict):
        return item

    catalogue = str(item.get('catalogue', '') or '').strip()
    name = str(item.get('name', '') or '').strip()
    if not catalogue or not name:
        item.pop('catalogue_aliases', None)
        item.pop('catalogue_group_id', None)
        return item

    entry = get_lookup_entry(catalogue, name)
    if not entry:
        item.pop('catalogue_aliases', None)
        item.pop('catalogue_group_id', None)
        return item

    aliases = entry.get('aliases', {})
    if isinstance(aliases, dict) and aliases:
        item['catalogue_aliases'] = aliases
    else:
        item.pop('catalogue_aliases', None)

    group_id = str(entry.get('group_id', '') or '')
    if group_id:
        item['catalogue_group_id'] = group_id
    else:
        item.pop('catalogue_group_id', None)

    return item
