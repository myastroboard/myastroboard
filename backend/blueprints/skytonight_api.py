"""
SkyTonight API Blueprint
All /api/skytonight/* and /api/catalogues routes, plus the payload-builder helpers.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from observation import astrodex
from observation import beginner_catalog
from equipment import equipment_profiles
from observation import object_info
from observation import plan_my_night
from skytonight import skytonight_targets
from utils.auth import admin_required, get_current_user, login_required, user_manager
from utils.constants import (
    OUTPUT_DIR,
    SKYTONIGHT_CALCULATION_LOG_FILE,
)
from constellation import Constellation as _Constellation
from utils.logging_config import get_logger
from utils.repo_config import load_config, get_active_location, get_locations_for_user
from skytonight.skytonight_scheduler_manager import (
    get_remote_skytonight_scheduler_status,
    get_skytonight_scheduler_for_api,
    _run_skytonight_refresh,
)
from skytonight.skytonight_storage import (
    ensure_skytonight_directories,
    get_alttime_dir,
    get_bodies_results_file,
    get_comets_results_file,
    get_dso_results_file,
    get_scheduler_trigger_file as get_skytonight_scheduler_trigger_file,
    get_skymap_file,
    has_bodies_results,
    has_calculation_results,
    has_comets_results,
    has_dso_results,
)
from skytonight.skytonight_calculator import compute_target_debug, load_calculation_results
from utils import load_json_file, normalize_catalogue_key as _normalize_catalogue_key

logger = get_logger(__name__)

skytonight_bp = Blueprint('skytonight', __name__)

# ---------------------------------------------------------------------------
# Constellation abbreviation → full name map
# ---------------------------------------------------------------------------


def _humanize_const_name(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', name)


_CONSTELLATION_ABBR_MAP: Dict[str, str] = {
    str(c.abbr): _humanize_const_name(c.name) for c in _Constellation if c.abbr is not None
}
# PyOngc uses Se1/Se2 for the two halves of Serpens (not in the IAU enum).
_CONSTELLATION_ABBR_MAP['Se1'] = 'Serpens Caput'
_CONSTELLATION_ABBR_MAP['Se2'] = 'Serpens Cauda'


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _skytonight_request_location() -> Dict[str, Any]:
    """The location preset SkyTonight endpoints serve for this request.

    v1.2: the nightly calculation runs once per scheduler location, so every
    endpoint resolves the requesting user's *active* preset and reads that
    location's result files. Overlays (horizon lines, timezone) come from the
    same preset, keeping them consistent with the served data.
    """
    config = load_config()
    try:
        user = get_current_user()
    except RuntimeError:
        user = None  # outside a request context (direct calls in tests/tools)
    return get_active_location(config, user)


def _skytonight_request_location_override(location_id: Optional[str]) -> Dict[str, Any]:
    """Resolve the location preset for this request, optionally pinned to *location_id*.

    Used by endpoints that need to read a specific location's result files regardless
    of the viewer's currently active preset (e.g. Plan My Night reading altitude-time
    data for the location a plan was pinned to at creation - see plan_my_night.py's
    'Pinned at creation' comment). Falls back to the requester's active preset when
    *location_id* is empty or the user has no access to it, so a stale/foreign id
    can't be used to probe another location's data.
    """
    config = load_config()
    try:
        user = get_current_user()
    except RuntimeError:
        user = None  # outside a request context (direct calls in tests/tools)

    if location_id:
        accessible = {loc['id']: loc for loc in get_locations_for_user(config, user)}
        if location_id in accessible:
            return accessible[location_id]

    return get_active_location(config, user)


def _target_attr(target: object, key: str, default=None):
    if isinstance(target, dict):
        return target.get(key, default)
    return getattr(target, key, default)


def _target_catalogue_names(target: object) -> Dict[str, str]:
    value = _target_attr(target, 'catalogue_names', {})
    return value if isinstance(value, dict) else {}


def _get_catalogue_alias_payload(catalogue: str, item_name: str) -> tuple:
    """Return alias group metadata for a catalogue item."""
    if not catalogue or not item_name:
        return '', {}

    entry = skytonight_targets.get_lookup_entry(catalogue, item_name)
    if not isinstance(entry, dict):
        return '', {}

    group_id = str(entry.get('group_id', '') or '')
    aliases = entry.get('aliases', {})
    if not isinstance(aliases, dict):
        aliases = {}

    return group_id, aliases


def _preload_all_current_plan_entries(user_id: str, username: str) -> list:
    """Aggregate entries from all current (non-previous) plans for a user across all combinations."""
    all_entries: list = []
    seen_ids: set = set()
    for file_path in plan_my_night.get_all_plan_files(user_id):
        fname = os.path.basename(file_path)
        cid: Optional[str] = None
        if fname != f'{user_id}_plan_my_night.json':
            cid = fname.replace(f'{user_id}_plan_', '').replace('.json', '')
        try:
            payload = plan_my_night.load_user_plan(user_id, username, combination_id=cid)
            plan_obj = payload.get('plan')
            if not isinstance(plan_obj, dict):
                continue
            if plan_my_night.get_plan_state(plan_obj) != 'current':
                continue
            for entry in plan_obj.get('entries', []):
                eid = entry.get('id')
                if eid and eid not in seen_ids:
                    all_entries.append(entry)
                    seen_ids.add(eid)
        except Exception:
            pass  # malformed plan file for this user/combination — skip it
    return all_entries


def _resolve_source_catalogue(catalogue_names: Dict[str, str], display_name: str) -> str:
    """Pick the catalogue label that matches the chosen display name."""
    if not isinstance(catalogue_names, dict) or not catalogue_names:
        return 'SkyTonight'

    normalized_display = skytonight_targets.normalize_object_name(display_name)
    if normalized_display:
        for catalogue_label, catalogue_value in catalogue_names.items():
            if skytonight_targets.normalize_object_name(catalogue_value) == normalized_display:
                return str(catalogue_label)

    return str(next(iter(catalogue_names.keys()), 'SkyTonight'))


def _annotate_skytonight_item(
    item: Dict[str, Any],
    user_id: str,
    username: str,
    source_catalogue: str,
    plan_state: str,
    _preloaded_astrodex: Optional[Dict[str, Any]] = None,
    _preloaded_plan_entries: Optional[list] = None,
) -> None:
    """Annotate a single item with astrodex / plan-my-night presence flags.

    When *_preloaded_astrodex* and *_preloaded_plan_entries* are supplied the
    function uses those already-loaded structures instead of reading the user
    files from disk again, which is critical for batch annotation (e.g. 1 000
    DSO rows in one API call).
    """
    item_name = str(item.get('target name') or item.get('name') or item.get('id') or '').strip()
    if item_name:
        if _preloaded_astrodex is not None:
            item['in_astrodex'] = astrodex.is_item_in_preloaded_astrodex(
                _preloaded_astrodex, item_name, source_catalogue
            )
        else:
            item['in_astrodex'] = astrodex.is_item_in_astrodex(user_id, item_name, source_catalogue)

        if _preloaded_plan_entries is not None:
            item['in_plan_my_night'] = plan_my_night.is_target_in_entries(
                _preloaded_plan_entries, source_catalogue, item_name
            )
        else:
            item['in_plan_my_night'] = plan_my_night.is_target_in_current_plan(
                user_id, username, source_catalogue, item_name
            )

        group_id, aliases = _get_catalogue_alias_payload(source_catalogue, item_name)
        item['catalogue_group_id'] = group_id
        item['catalogue_aliases'] = aliases
    else:
        item['in_astrodex'] = False
        item['in_plan_my_night'] = False
        item['catalogue_group_id'] = ''
        item['catalogue_aliases'] = {}
    item['plan_state'] = plan_state


_ALTTIME_ID_SAFE = re.compile(r'[^a-z0-9_-]')


def _alttime_json_path(target_id: str, location_id: Optional[str] = None, alttime_dir: Optional[str] = None) -> str:
    """Return absolute path for a target's altitude-time JSON file (per location).

    Pass a pre-resolved *alttime_dir* (from :func:`get_alttime_dir`, called once)
    when checking many rows in a loop - it avoids re-resolving/creating the
    directory (a filesystem call) on every single row.
    """
    safe_id = _ALTTIME_ID_SAFE.sub('_', target_id.lower())
    resolved_dir = alttime_dir if alttime_dir is not None else get_alttime_dir(location_id)
    return os.path.normpath(os.path.join(resolved_dir, f'{safe_id}_alttime.json'))


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _build_skytonight_reports_payload(catalogue: Optional[str], user_id: str, username: str) -> Dict[str, Any]:
    """Build the SkyTonight reports payload served to the frontend.

    When the scheduler has already computed a calculation results cache (i.e.
    :func:`~skytonight_storage.has_calculation_results` returns True) the data
    is served from that pre-computed file.  This contains per-target
    visibility metrics and AstroScore computed for tonight.

    When no cache exists yet (first startup before the scheduler ran) the
    function falls back to the static targets dataset so the frontend always
    gets something useful.
    """
    plan_payload = plan_my_night.get_plan_with_timeline(user_id, username)
    plan_state = plan_payload.get('state', 'none')
    location_id = _skytonight_request_location().get('id')

    base_result: Dict[str, Any] = {
        'report': [],
        'bodies': [],
        'comets': [],
    }

    # --- Prefer calculation results cache (scheduler-computed) ---
    if has_calculation_results(location_id):
        calc = load_calculation_results(location_id)
        night_meta = calc.get('metadata', {})
        alttime_dir = get_alttime_dir(location_id)

        base_result['night_metadata'] = night_meta

        max_deep_sky_rows = 1000 if not catalogue else 4000
        deep_sky_rows = 0

        for calc_item in calc.get('deep_sky', []):
            if deep_sky_rows >= max_deep_sky_rows:  # pragma: no cover
                break

            # Catalogue filter
            calc_catalogue_names: Dict[str, str] = calc_item.get('catalogue_names', {})
            if catalogue:
                display_name = str(calc_catalogue_names.get(catalogue, '') or '').strip()
                if not display_name:
                    continue
                source_catalogue = catalogue
            else:
                display_name = str(calc_item.get('preferred_name', '') or '').strip()
                source_catalogue = _resolve_source_catalogue(calc_catalogue_names, display_name)

            preferred_display_name = str(calc_item.get('preferred_name', '') or '').strip() or display_name
            canonical_id = (
                str(calc_catalogue_names.get('OpenNGC') or calc_catalogue_names.get('OpenIC') or '').strip()
                or preferred_display_name
            )

            observation = calc_item.get('observation', {})
            const_abbr = calc_item.get('constellation', '')
            const_full = _CONSTELLATION_ABBR_MAP.get(const_abbr, const_abbr)
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            row: Dict[str, Any] = {
                'id': canonical_id,
                'target name': preferred_display_name,
                'type': calc_item.get('object_type', ''),
                'constellation': const_full,
                'mag': calc_item.get('magnitude'),
                'size': calc_item.get('size_arcmin'),
                'foto': calc_item.get('astro_score'),
                'difficulty': calc_item.get('difficulty'),
                'difficulty_score': calc_item.get('difficulty_score'),
                'fraction of time observable': observation.get('observable_fraction'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'observable_hours': observation.get('observable_hours'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'meridian transit': observation.get('meridian_transit'),
                'antimeridian transit': observation.get('antimeridian_transit'),
                'catalogue_names': calc_catalogue_names,
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(row, user_id, username, source_catalogue, plan_state)
            base_result['report'].append(row)
            deep_sky_rows += 1

        for calc_item in calc.get('bodies', []):
            observation = calc_item.get('observation', {})
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            meridian_transit = observation.get('meridian_transit')
            row = {
                'target name': calc_item.get('preferred_name', ''),
                'type': calc_item.get('object_type', ''),
                'visual magnitude': calc_item.get('magnitude'),
                'foto': calc_item.get('astro_score'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'max altitude time': observation.get('max_altitude_time'),
                'meridian transit': meridian_transit,
                'antimeridian transit': observation.get('antimeridian_transit'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'observable_hours': observation.get('observable_hours'),
                'solar elongation': calc_item.get('solar_elongation_deg'),
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(row, user_id, username, 'Bodies', plan_state)
            base_result['bodies'].append(row)

        for calc_item in calc.get('comets', []):
            observation = calc_item.get('observation', {})
            metadata = calc_item.get('metadata', {})
            if not isinstance(metadata, dict):
                metadata = {}
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            row = {
                'target name': calc_item.get('preferred_name', ''),
                'type': calc_item.get('object_type', ''),
                'visual magnitude': calc_item.get('magnitude'),
                'absolute magnitude': metadata.get('absolute_magnitude'),
                'q': metadata.get('perihelion_date', ''),
                'foto': calc_item.get('astro_score'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'distance earth au': metadata.get('distance_earth_au'),
                'distance sun au': metadata.get('distance_sun_au'),
                'rise time': observation.get('rise_time'),
                'set time': observation.get('set_time'),
                'meridian transit': observation.get('meridian_transit'),
                'antimeridian transit': observation.get('antimeridian_transit'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'observable_hours': observation.get('observable_hours'),
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(row, user_id, username, 'Comets', plan_state)
            base_result['comets'].append(row)

        base_result['report_truncated'] = len(base_result['report']) >= max_deep_sky_rows
        base_result['report_limit'] = max_deep_sky_rows
        return base_result

    # --- Fallback: static targets dataset (no calculations yet) ---
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []
    if not targets:
        logger.info('SkyTonight dataset is empty; returning empty payload and relying on scheduler refresh')

    max_deep_sky_rows = 1000 if not catalogue else 4000
    skip_deep_sky_annotations = catalogue is None
    deep_sky_rows = 0

    for target in targets:
        category = str(_target_attr(target, 'category', '') or '').strip()
        preferred_name = str(_target_attr(target, 'preferred_name', '') or '').strip()
        object_type = str(_target_attr(target, 'object_type', '') or '').strip()
        constellation = str(_target_attr(target, 'constellation', '') or '').strip()
        magnitude = _target_attr(target, 'magnitude', None)
        catalogue_names = _target_catalogue_names(target)
        metadata = _target_attr(target, 'metadata', {})
        if not isinstance(metadata, dict):
            metadata = {}

        if category == 'deep_sky':
            if deep_sky_rows >= max_deep_sky_rows:  # pragma: no cover
                continue

            if catalogue:
                display_name = str(catalogue_names.get(catalogue, '') or '').strip()
                if not display_name:
                    continue
                source_catalogue = catalogue
            else:
                display_name = preferred_name
                source_catalogue = _resolve_source_catalogue(catalogue_names, display_name)

            const_full = _CONSTELLATION_ABBR_MAP.get(constellation, constellation)
            row = {
                'id': display_name,
                'target name': display_name,
                'type': object_type,
                'constellation': const_full,
                'mag': magnitude,
                'size': _target_attr(target, 'size_arcmin', None),
                'foto': None,
                'alttime_file': '',
                'source_type': 'dataset',
            }
            if skip_deep_sky_annotations:
                row['in_astrodex'] = False
                row['in_plan_my_night'] = False
                row['catalogue_group_id'] = ''
                row['catalogue_aliases'] = {}
                row['plan_state'] = plan_state
            else:
                _annotate_skytonight_item(row, user_id, username, source_catalogue, plan_state)
            base_result['report'].append(row)
            deep_sky_rows += 1
            continue

        if category == 'bodies':
            row = {
                'target name': preferred_name,
                'type': object_type,
                'visual magnitude': magnitude,
                'foto': None,
                'alttime_file': '',
                'source_type': 'dataset',
            }
            _annotate_skytonight_item(row, user_id, username, 'Bodies', plan_state)
            base_result['bodies'].append(row)
            continue

        if category == 'comets':
            row = {
                'target name': preferred_name,
                'type': object_type,
                'visual magnitude': magnitude,
                'q': metadata.get('perihelion_date', ''),
                'alttime_file': '',
                'source_type': 'dataset',
            }
            _annotate_skytonight_item(row, user_id, username, 'Comets', plan_state)
            base_result['comets'].append(row)

    base_result['report_truncated'] = len(base_result['report']) >= max_deep_sky_rows
    base_result['report_limit'] = max_deep_sky_rows
    return base_result


def _build_bodies_section_payload(user_id: str, username: str) -> Dict[str, Any]:
    """Build the Solar system bodies payload for the reactive UI section."""
    plan_payload = plan_my_night.get_plan_with_timeline(user_id, username)
    plan_state = plan_payload.get('state', 'none')
    location_id = _skytonight_request_location().get('id')

    # Pre-load user data once to avoid N×file-reads inside the per-item annotation loop.
    _preloaded_astrodex = astrodex.load_user_astrodex(user_id)
    _preloaded_plan_entries: list = _preload_all_current_plan_entries(user_id, username)

    if has_bodies_results(location_id):
        data = load_json_file(get_bodies_results_file(location_id), default={})
        alttime_dir = get_alttime_dir(location_id)
        rows = []
        for calc_item in data.get('bodies', []):
            observation = calc_item.get('observation', {})
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            row: Dict[str, Any] = {
                'target name': calc_item.get('preferred_name', ''),
                'type': calc_item.get('object_type', ''),
                'visual magnitude': calc_item.get('magnitude'),
                'foto': calc_item.get('astro_score'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'max altitude time': observation.get('max_altitude_time'),
                'meridian transit': observation.get('meridian_transit'),
                'antimeridian transit': observation.get('antimeridian_transit'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'solar elongation': calc_item.get('solar_elongation_deg'),
                'observable_hours': observation.get('observable_hours'),
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(
                row,
                user_id,
                username,
                'Bodies',
                plan_state,
                _preloaded_astrodex=_preloaded_astrodex,
                _preloaded_plan_entries=_preloaded_plan_entries,
            )
            rows.append(row)
        return {
            'bodies': rows,
            'night_metadata': data.get('metadata', {}),
            'available': True,
            'in_progress': bool(data.get('metadata', {}).get('in_progress', False)),
            'source_type': 'calculated',
        }

    # Fallback: static dataset
    dataset = skytonight_targets.load_targets_dataset()
    rows = []
    for target in dataset.get('targets', []) if isinstance(dataset, dict) else []:
        if str(_target_attr(target, 'category', '') or '') != 'bodies':
            continue
        preferred_name = str(_target_attr(target, 'preferred_name', '') or '')
        row = {
            'target name': preferred_name,
            'type': str(_target_attr(target, 'object_type', '') or ''),
            'visual magnitude': _target_attr(target, 'magnitude', None),
            'foto': None,
            'alttime_file': '',
            'source_type': 'dataset',
        }
        _annotate_skytonight_item(
            row,
            user_id,
            username,
            'Bodies',
            plan_state,
            _preloaded_astrodex=_preloaded_astrodex,
            _preloaded_plan_entries=_preloaded_plan_entries,
        )
        rows.append(row)
    return {
        'bodies': rows,
        'night_metadata': {},
        'available': bool(rows),
        'in_progress': False,
        'source_type': 'dataset',
    }


def _build_comets_section_payload(user_id: str, username: str) -> Dict[str, Any]:
    """Build the comets payload for the reactive UI section."""
    plan_payload = plan_my_night.get_plan_with_timeline(user_id, username)
    plan_state = plan_payload.get('state', 'none')
    location_id = _skytonight_request_location().get('id')

    # Pre-load user data once to avoid N×file-reads inside the per-item annotation loop.
    _preloaded_astrodex = astrodex.load_user_astrodex(user_id)
    _preloaded_plan_entries: list = _preload_all_current_plan_entries(user_id, username)

    if has_comets_results(location_id):
        data = load_json_file(get_comets_results_file(location_id), default={})
        alttime_dir = get_alttime_dir(location_id)
        rows = []
        for calc_item in data.get('comets', []):
            observation = calc_item.get('observation', {})
            metadata = calc_item.get('metadata', {})
            if not isinstance(metadata, dict):
                metadata = {}
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            row: Dict[str, Any] = {
                'target name': calc_item.get('preferred_name', ''),
                'type': calc_item.get('object_type', ''),
                'visual magnitude': calc_item.get('magnitude'),
                'absolute magnitude': metadata.get('absolute_magnitude'),
                'q': metadata.get('perihelion_date', ''),
                'foto': calc_item.get('astro_score'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'distance earth au': metadata.get('distance_earth_au'),
                'distance sun au': metadata.get('distance_sun_au'),
                'rise time': observation.get('rise_time'),
                'set time': observation.get('set_time'),
                'meridian transit': observation.get('meridian_transit'),
                'antimeridian transit': observation.get('antimeridian_transit'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'observable_hours': observation.get('observable_hours'),
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(
                row,
                user_id,
                username,
                'Comets',
                plan_state,
                _preloaded_astrodex=_preloaded_astrodex,
                _preloaded_plan_entries=_preloaded_plan_entries,
            )
            rows.append(row)
        return {
            'comets': rows,
            'night_metadata': data.get('metadata', {}),
            'available': True,
            'in_progress': bool(data.get('metadata', {}).get('in_progress', False)),
            'source_type': 'calculated',
        }

    # Fallback: static dataset
    dataset = skytonight_targets.load_targets_dataset()
    rows = []
    for target in dataset.get('targets', []) if isinstance(dataset, dict) else []:
        if str(_target_attr(target, 'category', '') or '') != 'comets':
            continue
        preferred_name = str(_target_attr(target, 'preferred_name', '') or '')
        meta_t = _target_attr(target, 'metadata', {})
        if not isinstance(meta_t, dict):
            meta_t = {}
        row = {
            'target name': preferred_name,
            'type': str(_target_attr(target, 'object_type', '') or ''),
            'visual magnitude': _target_attr(target, 'magnitude', None),
            'q': meta_t.get('perihelion_date', ''),
            'foto': None,
            'alttime_file': '',
            'source_type': 'dataset',
        }
        _annotate_skytonight_item(
            row,
            user_id,
            username,
            'Comets',
            plan_state,
            _preloaded_astrodex=_preloaded_astrodex,
            _preloaded_plan_entries=_preloaded_plan_entries,
        )
        rows.append(row)
    return {
        'comets': rows,
        'night_metadata': {},
        'available': bool(rows),
        'in_progress': False,
        'source_type': 'dataset',
    }


def _build_dso_section_payload(catalogue: Optional[str], user_id: str, username: str) -> Dict[str, Any]:
    """Build the deep-sky objects payload for the reactive UI section."""
    plan_payload = plan_my_night.get_plan_with_timeline(user_id, username)
    plan_state = plan_payload.get('state', 'none')
    max_rows = 1000 if not catalogue else 4000
    location_id = _skytonight_request_location().get('id')

    # Pre-load user data once to avoid N×file-reads inside the per-item annotation loop.
    _preloaded_astrodex = astrodex.load_user_astrodex(user_id)
    _preloaded_plan_entries: list = _preload_all_current_plan_entries(user_id, username)

    if has_dso_results(location_id):
        data = load_json_file(get_dso_results_file(location_id), default={})
        alttime_dir = get_alttime_dir(location_id)
        rows = []
        rows_added = 0
        for calc_item in data.get('deep_sky', []):
            if rows_added >= max_rows:  # pragma: no cover
                break
            calc_catalogue_names: Dict[str, str] = calc_item.get('catalogue_names', {})
            if catalogue:
                display_name = str(calc_catalogue_names.get(catalogue, '') or '').strip()
                if not display_name:
                    continue
                source_catalogue = catalogue
            else:
                display_name = str(calc_item.get('preferred_name', '') or '').strip()
                source_catalogue = _resolve_source_catalogue(calc_catalogue_names, display_name)

            preferred_display_name = str(calc_item.get('preferred_name', '') or '').strip() or display_name
            canonical_id = (
                str(calc_catalogue_names.get('OpenNGC') or calc_catalogue_names.get('OpenIC') or '').strip()
                or preferred_display_name
            )
            observation = calc_item.get('observation', {})
            const_abbr = calc_item.get('constellation', '')
            const_full = _CONSTELLATION_ABBR_MAP.get(const_abbr, const_abbr)
            ra_hms = observation.get('ra_hms', '')
            dec_dms = observation.get('dec_dms', '')
            row: Dict[str, Any] = {
                'id': canonical_id,
                'target name': preferred_display_name,
                'type': calc_item.get('object_type', ''),
                'constellation': const_full,
                'mag': calc_item.get('magnitude'),
                'size': calc_item.get('size_arcmin'),
                'foto': calc_item.get('astro_score'),
                'difficulty': calc_item.get('difficulty'),
                'difficulty_score': calc_item.get('difficulty_score'),
                'fraction of time observable': observation.get('observable_fraction'),
                'altitude': observation.get('max_altitude'),
                'azimuth': observation.get('azimuth'),
                'observable_hours': observation.get('observable_hours'),
                'right ascension': ra_hms,
                'declination': dec_dms,
                'hmsdms': f"{ra_hms} / {dec_dms}" if ra_hms and dec_dms else None,
                'meridian transit': observation.get('meridian_transit'),
                'antimeridian transit': observation.get('antimeridian_transit'),
                'catalogue_names': calc_catalogue_names,
                'alttime_file': (
                    calc_item.get('target_id', '')
                    if os.path.isfile(_alttime_json_path(calc_item.get('target_id', ''), alttime_dir=alttime_dir))
                    else ''
                ),
                'source_type': 'calculated',
                'plan_state': plan_state,
            }
            _annotate_skytonight_item(
                row,
                user_id,
                username,
                source_catalogue,
                plan_state,
                _preloaded_astrodex=_preloaded_astrodex,
                _preloaded_plan_entries=_preloaded_plan_entries,
            )
            rows.append(row)
            rows_added += 1
        return {
            'report': rows,
            'night_metadata': data.get('metadata', {}),
            'available': True,
            'in_progress': bool(data.get('metadata', {}).get('in_progress', False)),
            'source_type': 'calculated',
            'report_truncated': rows_added >= max_rows,
            'report_limit': max_rows,
        }

    # Fallback: static dataset
    dataset = skytonight_targets.load_targets_dataset()
    rows = []
    rows_added = 0
    for target in dataset.get('targets', []) if isinstance(dataset, dict) else []:
        if str(_target_attr(target, 'category', '') or '') != 'deep_sky':
            continue
        if rows_added >= max_rows:  # pragma: no cover
            break
        catalogue_names = _target_catalogue_names(target)
        preferred_name = str(_target_attr(target, 'preferred_name', '') or '').strip()
        source_catalogue = catalogue or ''
        if catalogue:
            display_name = str(catalogue_names.get(catalogue, '') or '').strip()
            if not display_name:
                continue
        else:
            display_name = preferred_name
        const = str(_target_attr(target, 'constellation', '') or '')
        const_full = _CONSTELLATION_ABBR_MAP.get(const, const)
        row = {
            'id': display_name,
            'target name': display_name,
            'type': str(_target_attr(target, 'object_type', '') or ''),
            'constellation': const_full,
            'mag': _target_attr(target, 'magnitude', None),
            'size': _target_attr(target, 'size_arcmin', None),
            'foto': None,
            'alttime_file': '',
            'source_type': 'dataset',
            'in_astrodex': False,
            'in_plan_my_night': False,
            'catalogue_group_id': '',
            'catalogue_aliases': {},
            'plan_state': plan_state,
        }
        if catalogue:
            _annotate_skytonight_item(
                row,
                user_id,
                username,
                source_catalogue,
                plan_state,
                _preloaded_astrodex=_preloaded_astrodex,
                _preloaded_plan_entries=_preloaded_plan_entries,
            )
        rows.append(row)
        rows_added += 1
    return {
        'report': rows,
        'night_metadata': {},
        'available': bool(rows),
        'in_progress': False,
        'source_type': 'dataset',
        'report_truncated': rows_added >= max_rows,
        'report_limit': max_rows,
    }


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_in_range(value: float, min_value: float, max_value: float) -> float:
    """Return a soft score in [1, 5] where [min_value, max_value] is ideal."""
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    if min_value <= value <= max_value:
        return 5.0

    span = max(max_value - min_value, 1.0)
    tolerance = span * 1.5
    distance = (min_value - value) if value < min_value else (value - max_value)
    penalty = min(distance / max(tolerance, 1.0), 1.0)
    return max(1.0, 5.0 - 4.0 * penalty)


def _ideal_focal_range(size_arcmin: Optional[float], object_type: str) -> tuple[float, float]:
    """Estimate a practical focal-length band from target apparent size/type."""
    if size_arcmin is not None and size_arcmin > 0:
        if size_arcmin >= 120:
            return (100.0, 350.0)
        if size_arcmin >= 60:
            return (200.0, 550.0)
        if size_arcmin >= 30:
            return (350.0, 850.0)
        if size_arcmin >= 15:
            return (600.0, 1300.0)
        if size_arcmin >= 8:
            return (900.0, 1800.0)
        return (1200.0, 3000.0)

    normalized_type = str(object_type or '').lower()
    if any(token in normalized_type for token in ['galaxy', 'planetary', 'globular']):
        return (900.0, 2200.0)
    if any(token in normalized_type for token in ['open cluster', 'asterism', 'nebula', 'cloud']):
        return (250.0, 900.0)
    return (450.0, 1400.0)


def _aperture_score(aperture_mm: float, magnitude: Optional[float]) -> float:
    """Estimate how suitable aperture is for target brightness."""
    if magnitude is None:
        return _score_in_range(aperture_mm, 70.0, 180.0)

    faintness = max(0.0, min((magnitude - 6.0) / 6.0, 1.0))
    min_ap = 50.0 + 120.0 * faintness
    ideal_ap = 100.0 + 220.0 * faintness
    return _score_in_range(aperture_mm, min_ap, ideal_ap)


def _speed_score(f_ratio: float, object_type: str) -> float:
    normalized_type = str(object_type or '').lower()
    if any(token in normalized_type for token in ['nebula', 'open cluster', 'asterism', 'cloud']):
        if f_ratio <= 5.0:
            return 5.0
        if f_ratio <= 6.5:
            return 4.0
        if f_ratio <= 8.0:
            return 3.0
        if f_ratio <= 10.0:
            return 2.0
        return 1.0
    return 3.5


def _fov_match_score(fov_diagonal_deg: float, size_arcmin: Optional[float]) -> Optional[float]:
    """Score how well a combination's diagonal FOV frames the target (None if size unknown).

    A target filling roughly 10-60% of the frame's diagonal is considered a good framing;
    much smaller and the target is lost in empty sky, much larger and it gets cropped.
    """
    if size_arcmin is None or size_arcmin <= 0 or fov_diagonal_deg <= 0:
        return None
    fill_ratio = size_arcmin / (fov_diagonal_deg * 60.0)
    return _score_in_range(fill_ratio, 0.10, 0.60)


def _recommend_combinations_for_target(
    target_payload: Dict[str, Any],
    combinations: list[Dict[str, Any]],
    telescopes_by_id: Dict[str, Dict[str, Any]],
    cameras_by_id: Dict[str, Dict[str, Any]],
) -> list[Dict[str, Any]]:
    size_arcmin = _to_float(target_payload.get('size'))
    magnitude = _to_float(target_payload.get('mag'))
    object_type = str(target_payload.get('type') or target_payload.get('object_type') or '')

    ideal_f_min, ideal_f_max = _ideal_focal_range(size_arcmin, object_type)
    recommendations: list[Dict[str, Any]] = []

    for combo in combinations:
        telescope = telescopes_by_id.get(combo.get('telescope_id') or '')
        camera = cameras_by_id.get(combo.get('camera_id') or '')

        if telescope:
            aperture_mm = _to_float(telescope.get('aperture_mm'))
            focal_length = _to_float(telescope.get('effective_focal_length')) or _to_float(
                telescope.get('focal_length_mm')
            )
            f_ratio = _to_float(telescope.get('effective_focal_ratio')) or _to_float(
                telescope.get('native_focal_ratio')
            )
        else:
            # Camera-only combination (e.g. DSLR + lens on a tracker): fall back to the
            # combination's own lens fields, deriving an effective aperture so the same
            # aperture/speed scoring can still run.
            focal_length = _to_float(combo.get('lens_focal_length_mm'))
            f_ratio = _to_float(combo.get('lens_focal_ratio'))
            aperture_mm = (focal_length / f_ratio) if focal_length and f_ratio else None

        if not aperture_mm or not focal_length or not f_ratio:
            continue

        focal_score = _score_in_range(focal_length, ideal_f_min, ideal_f_max)
        aperture_sc = _aperture_score(aperture_mm, magnitude)
        speed_sc = _speed_score(f_ratio, object_type)

        fov_calculation = None
        fov_score = None
        if camera:
            try:
                sensor_width = float(camera.get('sensor_width_mm') or 0)
                sensor_height = float(camera.get('sensor_height_mm') or 0)
                pixel_size = float(camera.get('pixel_size_um') or 0)
                if sensor_width > 0 and sensor_height > 0 and pixel_size > 0:
                    fov_calculation = equipment_profiles.calculate_fov(
                        focal_length, sensor_width, sensor_height, pixel_size
                    )
                    fov_score = _fov_match_score(fov_calculation.diagonal_fov_deg, size_arcmin)
            except (TypeError, ValueError, ZeroDivisionError):
                fov_calculation = None
                fov_score = None

        if fov_score is not None:
            final_raw = (0.30 * focal_score) + (0.30 * fov_score) + (0.25 * aperture_sc) + (0.15 * speed_sc)
        else:
            final_raw = (0.50 * focal_score) + (0.35 * aperture_sc) + (0.15 * speed_sc)
        final_score = int(round(max(1.0, min(5.0, final_raw))))

        recommendations.append(
            {
                'combination_id': str(combo.get('id') or ''),
                'combination_name': str(combo.get('name') or ''),
                'telescope_id': combo.get('telescope_id'),
                'telescope_name': str(telescope.get('name')) if telescope else None,
                'camera_id': combo.get('camera_id'),
                'camera_name': str(camera.get('name')) if camera else None,
                'is_camera_only': telescope is None,
                'aperture_mm': round(aperture_mm, 1),
                'effective_focal_length': round(focal_length, 1),
                'effective_focal_ratio': round(f_ratio, 2),
                'ideal_focal_min': int(ideal_f_min),
                'ideal_focal_max': int(ideal_f_max),
                'fov_diagonal_deg': round(fov_calculation.diagonal_fov_deg, 3) if fov_calculation else None,
                'image_scale_arcsec_per_px': (
                    round(fov_calculation.image_scale_arcsec_per_px, 3) if fov_calculation else None
                ),
                'sampling_classification': fov_calculation.sampling_classification if fov_calculation else None,
                'target_magnitude': round(magnitude, 2) if magnitude is not None else None,
                'target_size_arcmin': round(size_arcmin, 1) if size_arcmin is not None else None,
                'rating_1_to_5': final_score,
                'is_shared': bool(combo.get('is_shared', False)),
                'owner_username': combo.get('owner_username'),
            }
        )

    recommendations.sort(
        key=lambda row: (
            row.get('rating_1_to_5', 0),
            row.get('aperture_mm', 0),
            -abs((row.get('effective_focal_length', 0) or 0) - ((ideal_f_min + ideal_f_max) / 2.0)),
        ),
        reverse=True,
    )
    return recommendations


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@skytonight_bp.route('/api/catalogues', methods=['GET'])
@login_required
def get_catalogues_api():
    """Get available deep-sky catalogues from SkyTonight dataset."""
    try:
        dataset = skytonight_targets.load_targets_dataset()
        targets = dataset.get('targets', []) if isinstance(dataset, dict) else []
        catalogues = set()
        for target in targets:
            category = _target_attr(target, 'category', '')
            if str(category or '').strip() != 'deep_sky':
                continue
            for catalogue_name in _target_catalogue_names(target).keys():
                cleaned = str(catalogue_name or '').strip()
                if cleaned:
                    catalogues.add(cleaned)
        return jsonify(sorted(catalogues))
    except Exception as e:
        logger.error(f"Error getting catalogues: {e}")
        return jsonify([])


@skytonight_bp.route('/api/scheduler/status', methods=['GET'])
@login_required
def scheduler_status_api():
    """Legacy scheduler endpoint mapped to SkyTonight scheduler status."""
    return skytonight_scheduler_status_api()


@skytonight_bp.route('/api/scheduler/trigger', methods=['POST'])
@admin_required
def trigger_scheduler_api():
    """Legacy scheduler endpoint mapped to SkyTonight manual trigger."""
    return trigger_skytonight_scheduler_api()


@skytonight_bp.route('/api/skytonight/scheduler/status', methods=['GET'])
@login_required
def skytonight_scheduler_status_api():
    """Get SkyTonight scheduler status."""
    sched = get_skytonight_scheduler_for_api()
    if sched == 'remote_scheduler':
        return jsonify(get_remote_skytonight_scheduler_status())
    if sched:
        return jsonify(sched.get_status())
    return jsonify(
        {
            'running': False,
            'enabled': bool(load_config().get('skytonight', {}).get('enabled', False)),
            'last_run': None,
            'next_run': None,
            'is_executing': False,
            'mode': 'idle',
            'reason': 'SkyTonight scheduler not running',
            'server_time_valid': False,
            'server_time': None,
            'timezone': str(_skytonight_request_location().get('timezone') or 'UTC'),
            'last_error': None,
            'last_result': {},
            'progress': {
                'execution_duration_seconds': None,
            },
        }
    )


@skytonight_bp.route('/api/skytonight/scheduler/trigger', methods=['POST'])
@admin_required
def trigger_skytonight_scheduler_api():
    """Manually trigger SkyTonight execution."""
    sched = get_skytonight_scheduler_for_api()
    if sched == 'remote_scheduler':
        trigger_file = get_skytonight_scheduler_trigger_file()
        try:
            with open(trigger_file, 'w', encoding='utf-8') as file_obj:
                file_obj.write('trigger_now')
            return jsonify({'status': 'triggered', 'message': 'Trigger signal sent to SkyTonight scheduler worker'})
        except Exception as e:
            logger.error(f'Failed to create SkyTonight trigger file: {e}')
            return jsonify({'error': 'Failed to trigger SkyTonight scheduler'}), 500
    if sched:
        return jsonify(sched.trigger_now())
    return jsonify({'error': 'SkyTonight scheduler not running'}), 500


@skytonight_bp.route('/api/skytonight/dataset/status', methods=['GET'])
@login_required
def skytonight_dataset_status_api():
    """Return current SkyTonight dataset metadata and counts."""
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []
    metadata = dataset.get('metadata', {}) if isinstance(dataset, dict) else {}
    scheduler = get_skytonight_scheduler_for_api()
    if scheduler == 'remote_scheduler':
        scheduler_status = get_remote_skytonight_scheduler_status()
    elif scheduler:
        scheduler_status = scheduler.get_status()
    else:
        scheduler_status = {'running': False, 'is_executing': False}

    deep_sky_count = 0
    for target in targets:
        category = getattr(target, 'category', None)
        if category is None and isinstance(target, dict):
            category = target.get('category')
        if str(category or '').strip() == 'deep_sky':
            deep_sky_count += 1

    return jsonify(
        {
            'enabled': bool(load_config().get('skytonight', {}).get('enabled', False)),
            'loaded': bool(dataset.get('loaded', False)),
            'dataset_file': str(dataset.get('dataset_file', '')),
            'metadata': metadata if isinstance(metadata, dict) else {},
            'computed_counts': {
                'targets_total': len(targets),
                'deep_sky': deep_sky_count,
            },
            'calculations_cached': has_calculation_results(_skytonight_request_location().get('id')),
            'scheduler': {
                'running': scheduler_status.get('running', False),
                'is_executing': scheduler_status.get('is_executing', False),
                'last_run': scheduler_status.get('last_run'),
                'next_run': scheduler_status.get('next_run'),
                'mode': scheduler_status.get('mode'),
                'reason': scheduler_status.get('reason'),
            },
        }
    )


@skytonight_bp.route('/api/skytonight/dataset/rebuild', methods=['POST'])
@admin_required
def skytonight_dataset_rebuild_api():
    """Force a SkyTonight dataset rebuild immediately."""
    try:
        result = _run_skytonight_refresh()
        return jsonify({'status': 'rebuilt', **result})
    except Exception as e:
        logger.error(f'Failed to rebuild SkyTonight dataset: {e}')
        return jsonify({'error': 'Failed to rebuild SkyTonight dataset'}), 500


@skytonight_bp.route('/api/skytonight/log', methods=['GET'])
@login_required
def skytonight_log_api():
    """Return the latest SkyTonight calculation log content."""
    try:
        ensure_skytonight_directories()
        if not os.path.isfile(SKYTONIGHT_CALCULATION_LOG_FILE):
            return jsonify({'log_content': ''})

        with open(SKYTONIGHT_CALCULATION_LOG_FILE, 'r', encoding='utf-8') as file_obj:
            return jsonify({'log_content': file_obj.read()})
    except Exception as e:
        logger.error(f'Error getting SkyTonight log content: {e}')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/reports', methods=['GET'])
@login_required
def get_skytonight_reports_api():
    """Return SkyTonight report payload."""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        return jsonify(_build_skytonight_reports_payload(None, user_id, user.username))
    except Exception as e:
        logger.error(f'Error getting SkyTonight reports: {e}')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/reports/<catalogue>', methods=['GET'])
@login_required
def get_skytonight_catalogue_reports_api(catalogue):
    """Return SkyTonight report payload filtered by a deep-sky catalogue alias."""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if not re.match(r'^[a-zA-Z0-9_-]+$', catalogue):
            logger.warning(f'Invalid catalogue name: {catalogue}')
            return jsonify({'error': 'Invalid catalogue name'}), 400

        return jsonify(_build_skytonight_reports_payload(catalogue, user_id, user.username))
    except Exception as e:
        logger.error(f'Error getting SkyTonight catalogue reports: {e}')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/alttime/<target_id>', methods=['GET'])
@login_required
def get_skytonight_alttime_api(target_id):
    """Return altitude-time JSON data for a single target's graph popup.

    Accepts an optional ``?location_id=`` query param so a caller can pin the lookup
    to a specific accessible location (e.g. Plan My Night reading a plan's pinned
    location) instead of the viewer's currently active one.
    """
    if not re.match(r'^[a-zA-Z0-9_-]+$', target_id):
        return jsonify({'error': 'Invalid target identifier'}), 400

    request_location = _skytonight_request_location_override(request.args.get('location_id'))
    file_path = os.path.realpath(_alttime_json_path(target_id, request_location.get('id')))
    output_dir_abs = os.path.realpath(OUTPUT_DIR)
    # Path traversal guard. realpath + startswith (rather than
    # os.path.commonpath) is the pattern CodeQL's py/path-injection query
    # recognises as a sanitizer barrier.
    if not file_path.startswith(output_dir_abs + os.sep):
        return jsonify({'error': 'Invalid target identifier'}), 400

    if not os.path.isfile(file_path):
        return jsonify({'error': 'Altitude-time data not available for this target'}), 404

    try:
        with open(file_path, 'r', encoding='utf-8') as fobj:
            data = json.load(fobj)
        # Always inject the current horizon profile so the chart reflects the
        # live profile even for alttime files pre-dating it. Since v1.2 the
        # horizon lives on the location preset the calculation ran for (the
        # requester's active preset) - keeps the overlay consistent with the data.
        current_horizon = request_location.get('horizon_profile') or []
        if current_horizon:
            data['horizon_profile'] = current_horizon
        elif 'horizon_profile' not in data:
            data['horizon_profile'] = []
        return jsonify(data)
    except Exception:
        logger.exception(f'Error reading alttime JSON for target {target_id}')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/combination-recommendations', methods=['POST'])
@login_required
def get_skytonight_combination_recommendations_api():
    """Return per-user equipment-combination recommendations (1-5 rating) for one target.

    This endpoint is user-specific and on-demand, independent from the
    scheduler-based SkyTonight calculations. Only enabled and valid combinations
    (own or shared) are considered - see equipment_profiles.compute_combination_validity_status.
    """
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        target_payload = request.get_json(silent=True) or {}
        if not isinstance(target_payload, dict):
            return jsonify({'error': 'Invalid payload'}), 400

        combos_blob = equipment_profiles.load_user_combinations(user_id)
        own_combinations = list(combos_blob.get('items', []) if isinstance(combos_blob, dict) else [])

        active_combinations: list[Dict[str, Any]] = []
        for combo in own_combinations:
            if combo.get('is_disabled'):
                continue
            validity = equipment_profiles.compute_combination_validity_status(combo, user_id)
            if validity['is_valid']:
                active_combinations.append(combo)
        for combo in equipment_profiles.load_all_shared_combinations(user_id):
            if combo.get('is_disabled') or not combo.get('is_valid', True):
                continue
            active_combinations.append(combo)

        if not active_combinations:
            return jsonify(
                {
                    'has_combinations': False,
                    'target': target_payload,
                    'recommendations': [],
                }
            )

        mag_value = target_payload.get('mag')
        if mag_value is None:
            mag_value = target_payload.get('visual magnitude')

        normalized_target = {
            'id': target_payload.get('id', ''),
            'target_name': target_payload.get('target_name') or target_payload.get('target name') or '',
            'type': target_payload.get('type') or target_payload.get('object_type') or '',
            'size': target_payload.get('size'),
            'mag': mag_value,
        }
        telescopes_by_id, cameras_by_id = equipment_profiles.index_telescopes_and_cameras(user_id)
        recommendations = _recommend_combinations_for_target(
            normalized_target, active_combinations, telescopes_by_id, cameras_by_id
        )

        return jsonify(
            {
                'has_combinations': bool(active_combinations),
                'target': normalized_target,
                'recommendations': recommendations,
            }
        )
    except Exception:
        logger.exception('Error computing combination recommendations')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/skymap', methods=['GET'])
@login_required
def get_skytonight_skymap_api():
    """Return sky map trajectory data (az/alt arrays per visible target)."""
    request_location = _skytonight_request_location()
    skymap_file = get_skymap_file(request_location.get('id'))
    if not os.path.isfile(skymap_file):
        return jsonify({'targets': []}), 200
    try:
        with open(skymap_file, 'r', encoding='utf-8') as fobj:
            data = json.load(fobj)
        targets = data.get('targets', [])

        # Translate 3-letter constellation abbreviations to full names
        for tgt in targets:
            abbr = tgt.get('constellation', '')
            if abbr:
                tgt['constellation'] = _CONSTELLATION_ABBR_MAP.get(abbr, abbr)

        # Backfill the messier flag for skymap files written before this field was added.
        # Cross-reference against dso_results.json (already loaded; O(n) pass).
        needs_enrichment = any(tgt.get('category') == 'deep_sky' and 'messier' not in tgt for tgt in targets)
        dso_results_file = get_dso_results_file(request_location.get('id'))
        if needs_enrichment and os.path.isfile(dso_results_file):
            dso_data = load_json_file(dso_results_file, default={})
            messier_ids = {
                item.get('target_id', ''): bool('Messier' in (item.get('catalogue_names') or {}))
                for item in dso_data.get('deep_sky', [])
            }
            for tgt in targets:
                if tgt.get('category') == 'deep_sky' and 'messier' not in tgt:
                    tgt['messier'] = messier_ids.get(tgt.get('id', ''), False)

        # Include constraints so the frontend can draw horizon lines on the map.
        # horizon_profile comes from the active location's preset (v1.2).
        cfg = load_config()
        constraints = cfg.get('skytonight', {}).get('constraints', {})
        return jsonify(
            {
                'targets': targets,
                'constraints': {
                    'altitude_constraint_min': float(constraints.get('altitude_constraint_min', 30)),
                    'horizon_profile': request_location.get('horizon_profile') or [],
                },
            }
        )
    except Exception:
        logger.exception('Error reading skymap data file')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/data/bodies', methods=['GET'])
@login_required
def get_skytonight_data_bodies_api():
    """Return only Solar system body results (reactive per-section endpoint)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        return jsonify(_build_bodies_section_payload(user.user_id, user.username))
    except Exception:
        logger.exception('Error building bodies section payload')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/data/comets', methods=['GET'])
@login_required
def get_skytonight_data_comets_api():
    """Return only comet results (reactive per-section endpoint)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        return jsonify(_build_comets_section_payload(user.user_id, user.username))
    except Exception:
        logger.exception('Error building comets section payload')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/data/dso', methods=['GET'])
@login_required
def get_skytonight_data_dso_api():
    """Return only deep-sky object results (reactive per-section endpoint).

    Optional query param ``catalogue`` filters to a single catalogue.
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        catalogue = request.args.get('catalogue', '').strip() or None
        if catalogue and not re.match(r'^[a-zA-Z0-9_-]+$', catalogue):
            return jsonify({'error': 'Invalid catalogue name'}), 400
        return jsonify(_build_dso_section_payload(catalogue, user.user_id, user.username))
    except Exception:
        logger.exception('Error building DSO section payload')
        return jsonify({'error': 'Internal server error'}), 500


# Difficulty tiers a given experience_level preference is allowed to see.
_EXPERIENCE_LEVEL_ALLOWED_DIFFICULTIES: Dict[str, set] = {
    'beginner': {'beginner'},
    'intermediate': {'beginner', 'intermediate'},
    'advanced': {'beginner', 'intermediate', 'advanced'},
}


def _experience_level_allowed_difficulties(experience_level: str) -> set:
    """Return the difficulty tiers a given experience_level preference is allowed to see."""
    return _EXPERIENCE_LEVEL_ALLOWED_DIFFICULTIES.get(
        experience_level, _EXPERIENCE_LEVEL_ALLOWED_DIFFICULTIES['advanced']
    )


def _filter_targets_by_experience_level(targets: List[Dict[str, Any]], experience_level: str) -> List[Dict[str, Any]]:
    """Return only the targets whose `difficulty` tier is allowed for experience_level."""
    allowed = _experience_level_allowed_difficulties(experience_level)
    return [item for item in targets if item.get('difficulty', 'intermediate') in allowed]


# Fallback estimated integration time (hours) by difficulty tier, used when a
# recommended target has no matching entry in the curated beginner catalog.
_DIFFICULTY_ESTIMATED_HOURS: Dict[str, float] = {
    'beginner': 2.0,
    'intermediate': 4.0,
    'advanced': 8.0,
}

_RECOMMENDATIONS_DEFAULT_LIMIT = 5
_RECOMMENDATIONS_MAX_LIMIT = 10


def _build_beginner_catalog_hours_lookup() -> Dict[str, float]:
    """Return a normalized-catalogue-id -> typical_integration_hours lookup from the beginner catalog."""
    lookup: Dict[str, float] = {}
    for entry in beginner_catalog.load_beginner_catalog():
        key = _normalize_catalogue_key(entry.get('catalogue_id'))
        hours = entry.get('typical_integration_hours')
        if key and hours is not None:
            lookup[key] = hours
    return lookup


@skytonight_bp.route('/api/skytonight/recommendations', methods=['GET'])
@login_required
def get_skytonight_recommendations_api():
    """Return a small, difficulty-filtered set of "what to shoot tonight" target recommendations.

    Filters ``dso_results.json`` by the user's ``experience_level`` preference, sorts the
    remaining targets by AstroScore descending, and returns the top N (default 5, max 10).
    """
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            limit = int(request.args.get('limit', _RECOMMENDATIONS_DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = _RECOMMENDATIONS_DEFAULT_LIMIT
        limit = max(1, min(limit, _RECOMMENDATIONS_MAX_LIMIT))

        preferences = user_manager.get_user_preferences(user.user_id)
        experience_level = preferences.get('experience_level', 'advanced')

        dso_data = load_json_file(get_dso_results_file(_skytonight_request_location().get('id')), default={})
        deep_sky = dso_data.get('deep_sky', []) if isinstance(dso_data, dict) else []

        candidates = _filter_targets_by_experience_level(deep_sky, experience_level)
        candidates.sort(key=lambda item: item.get('astro_score') or 0.0, reverse=True)
        candidates = candidates[:limit]

        hours_lookup = _build_beginner_catalog_hours_lookup()
        preloaded_plan_entries = _preload_all_current_plan_entries(user.user_id, user.username)
        preloaded_astrodex = astrodex.load_user_astrodex(user.user_id, user.username)

        targets = []
        for item in candidates:
            catalogue_names: Dict[str, str] = item.get('catalogue_names', {}) or {}
            preferred_name = str(item.get('preferred_name', '') or '').strip()
            difficulty = item.get('difficulty', 'intermediate')
            source_catalogue = _resolve_source_catalogue(catalogue_names, preferred_name)
            canonical_id = (
                str(catalogue_names.get('OpenNGC') or catalogue_names.get('OpenIC') or '').strip() or preferred_name
            )
            messier = str(catalogue_names.get('Messier') or '').strip() or None

            matched_hours = None
            for name in catalogue_names.values():
                matched_hours = hours_lookup.get(_normalize_catalogue_key(name))
                if matched_hours is not None:
                    break
            if matched_hours is not None:
                estimated_hours = matched_hours
                is_estimate = False
            else:
                estimated_hours = _DIFFICULTY_ESTIMATED_HOURS.get(difficulty, 4.0)
                is_estimate = True

            in_astrodex = (
                astrodex.is_item_in_preloaded_astrodex(preloaded_astrodex, preferred_name, source_catalogue)
                if preferred_name
                else False
            )
            in_plan = (
                plan_my_night.is_target_in_entries(preloaded_plan_entries, source_catalogue, preferred_name)
                if preferred_name
                else False
            )

            coordinates = item.get('coordinates') or {}
            thumbnail_url = None
            ra_hours = coordinates.get('ra_hours')
            dec_degrees = coordinates.get('dec_degrees')
            if ra_hours is not None and dec_degrees is not None:
                thumbnail_url = object_info.get_object_image_proxy_url(ra_hours * 15.0, dec_degrees)

            targets.append(
                {
                    'target_id': item.get('target_id', ''),
                    'id': canonical_id,
                    'messier': messier,
                    'preferred_name': preferred_name,
                    'catalogue': source_catalogue,
                    'object_type': item.get('object_type', ''),
                    'constellation': item.get('constellation', ''),
                    'coordinates': item.get('coordinates'),
                    'difficulty': difficulty,
                    'difficulty_score': item.get('difficulty_score', 0),
                    'astro_score': item.get('astro_score'),
                    'magnitude': item.get('magnitude'),
                    'size_arcmin': item.get('size_arcmin'),
                    'estimated_integration_hours': estimated_hours,
                    'estimated_integration_hours_is_estimate': is_estimate,
                    'thumbnail_url': thumbnail_url,
                    'in_astrodex': in_astrodex,
                    'in_plan': in_plan,
                }
            )

        return jsonify(
            {
                'targets': targets,
                'experience_level': experience_level,
                'count': len(targets),
            }
        )
    except Exception:
        logger.exception('Error building SkyTonight recommendations payload')
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/logs/<catalogue>', methods=['GET'])
@login_required
def get_catalogue_log(catalogue):
    """Legacy-compatible log endpoint returning SkyTonight calculation log."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', catalogue):
        logger.warning(f"Invalid catalogue name: {catalogue}")
        return jsonify({"error": "Invalid catalogue name"}), 400

    try:
        ensure_skytonight_directories()
        log_file = SKYTONIGHT_CALCULATION_LOG_FILE

        if not os.path.exists(log_file):
            return jsonify({"error": "Log file not found"}), 404

        if os.path.getsize(log_file) == 0:
            return jsonify({"error": "Log file is empty"}), 404

        with open(log_file, 'r', encoding='utf-8') as f:
            log_content = f.read()

        return jsonify(
            {
                "catalogue": "skytonight",
                "log_content": log_content,
                "file_size": os.path.getsize(log_file),
            }
        )

    except Exception as e:
        logger.error(f"Error getting catalogue log: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/logs/<catalogue>/exists', methods=['GET'])
@login_required
def check_catalogue_log_exists(catalogue):
    """Legacy-compatible log existence endpoint for SkyTonight log."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', catalogue):
        logger.warning(f"Invalid catalogue name: {catalogue}")
        return jsonify({"error": "Invalid catalogue name"}), 400

    try:
        ensure_skytonight_directories()
        log_file = SKYTONIGHT_CALCULATION_LOG_FILE
        log_exists = os.path.exists(log_file) and os.path.getsize(log_file) > 0
        return jsonify(
            {
                "catalogue": "skytonight",
                "log_exists": log_exists,
            }
        )

    except Exception:
        logger.exception("Error checking if catalogue log exists")
        return jsonify({'error': 'Internal server error'}), 500


@skytonight_bp.route('/api/skytonight/target-debug', methods=['GET'])
@login_required
def skytonight_target_debug():
    """Return per-constraint diagnostic data for a target searched by name.

    Computes the same observability checks as the nightly scheduler and
    explains why the target would or would not appear in SkyTonight results.

    Query parameters
    ----------------
    name : str
        Target name (e.g. 'M 31', 'NGC 224', 'Jupiter').
    """
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Missing name parameter'}), 400

    try:
        config = load_config()
        result = compute_target_debug(name, config=config, location=_skytonight_request_location())
        return jsonify(result)
    except Exception as e:
        logger.error(f'Error in skytonight_target_debug for name={name!r}: {e}')
        return jsonify({'error': 'Internal server error'}), 500
