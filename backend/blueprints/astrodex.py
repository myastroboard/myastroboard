"""Astrodex + beginner catalog Blueprint. Routes: /api/astrodex/*, /api/beginner-catalog"""

import os
import uuid
from typing import Any, Dict

from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from observation import astrodex
from observation import beginner_catalog
from utils.auth import login_required, user_required, get_current_user, user_manager
from blueprints.plan_my_night import _resolve_requested_language
from utils.logging_config import get_logger
from utils.repo_config import load_config, get_locations_for_user, get_location_by_id
from utils.route_helpers import _resolve_active_location
from blueprints.skytonight_api import _preload_all_current_plan_entries
from skytonight import skytonight_targets
from skytonight.skytonight_storage import get_dso_results_file, has_dso_results
from utils import load_json_file, normalize_catalogue_key as _normalize_catalogue_key_for_difficulty

logger = get_logger(__name__)

astrodex_bp = Blueprint('astrodex', __name__)

_EMPTY_PICTURE_LOCATION = {
    'location_id': None,
    'location_name': None,
    'latitude': None,
    'longitude': None,
    'elevation': None,
}


def _safe_picture_coordinate(value, min_value, max_value):
    """Best-effort float parse for a manually-typed coordinate. Returns None
    for anything empty, unparseable, or out of range - a bad value is simply
    dropped (same low-stakes trust level as notes/exposition_time), not a 400."""
    if value is None or value == '':
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not (min_value <= parsed <= max_value):
        return None
    return parsed


def _resolve_picture_location_snapshot(
    location_id, user, custom_name=None, custom_latitude=None, custom_longitude=None
):
    """Resolve a picture's location into a frozen Astrodex snapshot (v1.2):
    either a preset (looked up + access-checked server-side) or a free-text
    "somewhere else" label the uploader typed themselves - a one-off trip
    isn't worth turning into an admin-managed preset.

    Preset coordinates are looked up server-side - never trusted from the
    client - and restricted to locations the user can actually access, so a
    picture can't be tagged with coordinates the uploader has no attribution
    to. A custom label's coordinates are optional and exactly what the
    uploader typed (same trust level as notes/exposition_time - it's a label
    on their own picture, not an access-control boundary). Everything empty
    resolves to "no location" rather than an error, since clearing a
    picture's location is a valid choice.
    """
    if location_id:
        config = load_config()
        accessible_ids = {loc['id'] for loc in get_locations_for_user(config, user)}
        if location_id in accessible_ids:
            location = get_location_by_id(config, location_id)
            if location:
                return {
                    'location_id': location['id'],
                    'location_name': location.get('name'),
                    'latitude': location.get('latitude'),
                    'longitude': location.get('longitude'),
                    'elevation': location.get('elevation'),
                }
        # location_id supplied but doesn't resolve to a real/accessible preset -
        # fall through; a custom label (if any) can still stand on its own.

    custom_name = (custom_name or '').strip()
    if custom_name:
        return {
            'location_id': None,
            'location_name': custom_name,
            'latitude': _safe_picture_coordinate(custom_latitude, -90, 90),
            'longitude': _safe_picture_coordinate(custom_longitude, -180, 180),
            'elevation': None,
        }

    return dict(_EMPTY_PICTURE_LOCATION)


_difficulty_lookup_cache: Dict[str, Dict[str, Any]] = {}


def _build_difficulty_lookup(location_id=None) -> Dict[str, str]:
    """Build a normalized-catalogue-name -> difficulty lookup from a location's dso_results.json.

    Cached in memory per location, keyed by the file's mtime - dso_results.json is only
    rewritten by the twice-daily SkyTonight calculation job, so rebuilding this on every
    /api/astrodex request is wasted work.
    """
    dso_results_file = get_dso_results_file(location_id)
    try:
        cache_key = os.path.getmtime(dso_results_file)
    except OSError:
        cache_key = None

    slot = _difficulty_lookup_cache.get(location_id or '')
    if slot is not None and slot['data'] is not None and slot['key'] == cache_key:
        return slot['data']

    dso_data = load_json_file(dso_results_file, default={})
    lookup: Dict[str, str] = {}
    for entry in dso_data.get('deep_sky', []) if isinstance(dso_data, dict) else []:
        difficulty = entry.get('difficulty')
        catalogue_names = entry.get('catalogue_names', {})
        if not difficulty or not isinstance(catalogue_names, dict):
            continue
        for name in catalogue_names.values():
            key = _normalize_catalogue_key_for_difficulty(name)
            if key:
                lookup[key] = difficulty

    _difficulty_lookup_cache[location_id or ''] = {'data': lookup, 'key': cache_key}
    return lookup


def _enrich_astrodex_items_with_difficulty(items, location_id=None):
    """Attach a `difficulty` field to each Astrodex item by cross-referencing SkyTonight's dso_results.json.

    Items with no catalogue/name match (e.g. manual entries not present in SkyTonight's
    catalogue) get `difficulty: None` rather than a guessed value.
    """
    lookup = _build_difficulty_lookup(location_id)
    for item in items:
        if not isinstance(item, dict):
            continue
        catalogue_key = _normalize_catalogue_key_for_difficulty(item.get('catalogue'))
        name_key = _normalize_catalogue_key_for_difficulty(item.get('name'))
        item['difficulty'] = lookup.get(catalogue_key) or lookup.get(name_key)
    return items


@astrodex_bp.route('/api/astrodex', methods=['GET'])
@login_required
def get_astrodex():
    """Get user's astrodex collection"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        config = load_config()
        private_mode = bool(config.get('astrodex', {}).get('private', False))
        users = user_manager.list_users()
        usernames_by_id = {
            user_entry.get('user_id', ''): user_entry.get('username', 'unknown')
            for user_entry in users
            if user_entry.get('user_id')
        }

        astrodex_data = astrodex.get_visible_astrodex(
            current_user_id=user_id,
            current_username=user.username,
            private_mode=private_mode,
            usernames_by_id=usernames_by_id,
        )
        _enrich_astrodex_items_with_difficulty(astrodex_data.get('items', []), _resolve_active_location().get('id'))

        return jsonify(
            {
                'items': astrodex_data.get('items', []),
                'stats': astrodex_data.get('stats', {}),
                'created_at': astrodex_data.get('created_at'),
                'updated_at': astrodex_data.get('updated_at'),
                'private_mode': astrodex_data.get('private_mode', private_mode),
                'current_user_id': user_id,
            }
        )
    except Exception as e:
        logger.error(f"Error getting astrodex: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/beginner-catalog', methods=['GET'])
@login_required
def get_beginner_catalog():
    """Return the curated beginner-friendly DSO catalog, enriched with the user's SkyTonight/Astrodex/Plan state."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        lang = _resolve_requested_language()
        visible_only_param = request.args.get('visible_only', 'true')
        visible_only = str(visible_only_param).strip().lower() != 'false'

        catalog = beginner_catalog.load_beginner_catalog()
        catalog = beginner_catalog.translate_catalog_entries(catalog, lang)

        active_location_id = _resolve_active_location().get('id')
        dso_results = load_json_file(get_dso_results_file(active_location_id), default={})
        astrodex_payload = astrodex.load_user_astrodex(user.user_id, user.username)
        user_astrodex_items = astrodex_payload.get('items', []) if isinstance(astrodex_payload, dict) else []
        # Aggregate across all telescope-scoped plans and only count "current" (non-archived)
        # ones, matching /api/skytonight/recommendations so "already planned" status agrees
        # between the two panels instead of only reflecting the default no-telescope plan.
        user_plan_entries = _preload_all_current_plan_entries(user.user_id, user.username)

        catalog = beginner_catalog.enrich_with_skytonight(
            catalog, dso_results, user_astrodex_items, user_plan_entries, location_id=active_location_id
        )

        # Only apply the visible_only filter when results actually exist - per spec, an
        # empty/missing dso_results.json (no calculation run yet) returns everything.
        if visible_only and has_dso_results(active_location_id):
            objects = [entry for entry in catalog if entry.get('visible_tonight')]
        else:
            objects = catalog

        visible_tonight_count = sum(1 for entry in catalog if entry.get('visible_tonight'))

        return jsonify(
            {
                'objects': objects,
                'total': len(catalog),
                'visible_tonight': visible_tonight_count,
            }
        )
    except Exception as e:
        logger.error(f"Error getting beginner catalog: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items', methods=['POST'])
@user_required
def add_astrodex_item():
    """Add item to user's astrodex"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        item_data = request.json

        if not item_data.get('name'):
            return jsonify({'error': 'Item name is required'}), 400

        # Check if item already exists (exact name or catalogue aliases)
        existing = astrodex.find_item_in_astrodex(user_id, item_data['name'], item_data.get('catalogue', ''))
        if existing:
            return (
                jsonify(
                    {
                        'error': 'duplicate',
                        'existing_item': {'id': existing['id'], 'name': existing.get('name', '')},
                    }
                ),
                409,
            )

        new_item = astrodex.create_astrodex_item(user_id, item_data, user.username)

        if new_item:
            return jsonify({'status': 'success', 'item': new_item})
        else:
            return jsonify({'error': 'Failed to create item'}), 500
    except Exception as e:
        logger.error(f"Error adding astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>/catalogue-name', methods=['POST'])
@user_required
def switch_astrodex_item_catalogue_name(item_id):
    """Switch Astrodex item displayed name to a catalogue-specific alias."""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        target_catalogue = data.get('catalogue', '')

        if not target_catalogue:
            return jsonify({'error': 'Target catalogue is required'}), 400

        updated_item = astrodex.switch_item_catalogue_name(user_id, item_id, target_catalogue)
        if updated_item:
            return jsonify({'status': 'success', 'item': updated_item})

        return jsonify({'error': 'Item not found'}), 404
    except ValueError as e:
        logger.warning(f"Value error switching astrodex item catalogue name: {e}")
        return jsonify({'error': 'Invalid input'}), 400
    except Exception as e:
        logger.error(f"Error switching astrodex item catalogue name: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>', methods=['GET'])
@login_required
def get_astrodex_item_api(item_id):
    """Get a specific astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        item = astrodex.get_astrodex_item(user_id, item_id)

        if item:
            return jsonify(item)
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error getting astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>', methods=['PUT'])
@user_required
def update_astrodex_item_api(item_id):
    """Update an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json

        updated_item = astrodex.update_astrodex_item(user_id, item_id, updates)

        if updated_item:
            return jsonify({'status': 'success', 'item': updated_item})
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error updating astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>', methods=['DELETE'])
@user_required
def delete_astrodex_item_api(item_id):
    """Delete an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.delete_astrodex_item(user_id, item_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>/pictures', methods=['POST'])
@user_required
def add_picture_to_astrodex_item(item_id):
    """Add a picture to an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        picture_data = request.json

        # Location is resolved server-side (v1.2) - never trust client-supplied
        # preset coordinates. Uses the uploader's explicit choice (a preset id
        # or a free-text "somewhere else" label) if they picked one, else
        # falls back to their current active location. Independent of the
        # item's own location, since a single item can be re-imaged from
        # different sites across multiple sessions.
        requested_location_id = picture_data.get('location_id')
        custom_name = picture_data.get('location_name')
        if not requested_location_id and not (custom_name or '').strip():
            requested_location_id = _resolve_active_location().get('id')
        picture_data.update(
            _resolve_picture_location_snapshot(
                requested_location_id,
                user,
                custom_name=custom_name,
                custom_latitude=picture_data.get('latitude'),
                custom_longitude=picture_data.get('longitude'),
            )
        )

        new_picture = astrodex.add_picture_to_item(user_id, item_id, picture_data)

        if new_picture:
            return jsonify({'status': 'success', 'picture': new_picture})
        else:
            return jsonify({'error': 'Item not found or failed to add picture'}), 404
    except Exception as e:
        logger.error(f"Error adding picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>/pictures/<picture_id>', methods=['PUT'])
@user_required
def update_picture_api(item_id, picture_id):
    """Update a picture in an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json

        # Location is resolved server-side (v1.2) and only touched if this
        # edit explicitly included location_id and/or location_name - editing
        # unrelated fields (notes, filters, ...) must never disturb an
        # existing location. Both empty/absent means "clear the location",
        # which _resolve_picture_location_snapshot turns into the all-None
        # snapshot.
        if 'location_id' in updates or 'location_name' in updates:
            updates.update(
                _resolve_picture_location_snapshot(
                    updates.get('location_id'),
                    user,
                    custom_name=updates.get('location_name'),
                    custom_latitude=updates.get('latitude'),
                    custom_longitude=updates.get('longitude'),
                )
            )

        updated_picture = astrodex.update_picture(user_id, item_id, picture_id, updates)

        if updated_picture:
            return jsonify({'status': 'success', 'picture': updated_picture})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error updating picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>/pictures/<picture_id>', methods=['DELETE'])
@user_required
def delete_picture_api(item_id, picture_id):
    """Delete a picture from an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.delete_picture(user_id, item_id, picture_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/items/<item_id>/pictures/<picture_id>/main', methods=['POST'])
@user_required
def set_main_picture_api(item_id, picture_id):
    """Set a picture as the main picture for an item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.set_main_picture(user_id, item_id, picture_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error setting main picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/upload', methods=['POST'])
@user_required
def upload_astrodex_image():
    """Upload an image for astrodex safely"""
    try:
        if 'file' not in request.files:
            logger.warning("No file part in the request")
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file or not file.filename:
            logger.warning("No file selected for upload")
            return jsonify({'error': 'No file selected'}), 400

        # Strict extension validation
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

        original_filename = secure_filename(file.filename)
        if '.' not in original_filename:
            logger.warning(f"File name does not have an extension: {original_filename}")
            return jsonify({'error': 'Invalid file name'}), 400

        file_ext = original_filename.rsplit('.', 1)[1].lower()
        if file_ext not in allowed_extensions:
            logger.warning(f"Invalid file type: {file_ext}")
            return jsonify({'error': 'Invalid file type'}), 400

        # Validate user
        try:
            user = get_current_user()
            user_id = user.user_id if user else None
            if not user_id:  # pragma: no cover
                logger.warning("User not authenticated for file upload")
                return jsonify({'error': 'User not authenticated'}), 401

        except (TypeError, ValueError):  # pragma: no cover
            logger.warning("Invalid user ID")
            return jsonify({'error': 'Invalid user ID'}), 400

        # Generate safe unique filename
        unique_filename = f"{user_id}_{uuid.uuid4()}.{file_ext}"

        # Ensure directory exists
        astrodex.ensure_astrodex_directories()

        base_dir = os.path.realpath(astrodex.ASTRODEX_IMAGES_DIR)
        file_path = os.path.realpath(os.path.join(base_dir, unique_filename))

        # Confinement check (anti path traversal). realpath + startswith
        # (rather than os.path.commonpath) is the pattern CodeQL's
        # py/path-injection query recognises as a sanitizer barrier.
        if not file_path.startswith(base_dir + os.sep):  # pragma: no cover
            logger.warning(f"Attempted path traversal attack: {file_path}")
            return jsonify({'error': 'Invalid file path'}), 400

        # Save file
        file.save(file_path)

        return jsonify({'status': 'success', 'filename': unique_filename})

    except Exception:
        logger.exception("Error uploading astrodex image")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/images/<filename>', methods=['GET'])
@login_required
def get_astrodex_image(filename):
    """Serve an astrodex image"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        config = load_config()
        private_mode = bool(config.get('astrodex', {}).get('private', False))
        users = user_manager.list_users()
        usernames_by_id = {
            user_entry.get('user_id', ''): user_entry.get('username', 'unknown')
            for user_entry in users
            if user_entry.get('user_id')
        }

        if not astrodex.can_user_view_image(user_id, filename, private_mode, usernames_by_id):
            return jsonify({'error': 'Image not accessible'}), 403

        return send_from_directory(astrodex.ASTRODEX_IMAGES_DIR, filename)
    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return jsonify({'error': 'Image not found'}), 404


@astrodex_bp.route('/api/astrodex/check/<item_name>', methods=['GET'])
@login_required
def check_item_in_astrodex(item_name):
    """Check if an item is in user's astrodex"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        is_in_astrodex = astrodex.is_item_in_astrodex(user_id, item_name)

        return jsonify({'in_astrodex': is_in_astrodex})
    except Exception as e:
        logger.error(f"Error checking astrodex: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/constellations', methods=['GET'])
@login_required
def get_constellations():
    """Get list of constellation names"""
    try:
        constellations = astrodex.get_constellations_list()
        return jsonify({'constellations': constellations})
    except Exception as e:
        logger.error(f"Error getting constellations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@astrodex_bp.route('/api/astrodex/catalogue-lookup', methods=['GET'])
@login_required
def astrodex_catalogue_lookup():
    """Look up a celestial object by name in the SkyTonight catalogue dataset.

    Returns basic object metadata (type, constellation, catalogue names) so the
    Astrodex manual-add form can be pre-filled when the entered name is known.
    """
    try:
        from constellation import Constellation
        import re as _re

        # Build a one-time abbr→full-name mapping (e.g. 'Cnc' -> 'Cancer',
        # 'UMa' -> 'Ursa Major').  c.name is the Python enum member name
        # (e.g. 'UrsaMajor') so we apply the same humanize() logic used in
        # astrodex.get_constellations_list() to insert spaces before capitals.
        def _humanize(name: str) -> str:
            return _re.sub(r'(?<!^)(?=[A-Z])', ' ', name)

        _abbr_to_name = {c.abbr: _humanize(c.name) for c in Constellation}

        name = request.args.get('name', '').strip()
        if not name:
            return jsonify({'found': False})

        # get_lookup_entry requires a non-empty catalogue; searching via the
        # 'alias' key covers all catalogue names and common aliases since the
        # lookup table registers every target under alias::<normalised_name>.
        entry = skytonight_targets.get_lookup_entry('alias', name)
        if entry:
            raw_constellation = entry.get('constellation') or ''
            full_constellation = (_abbr_to_name.get(raw_constellation, raw_constellation) or '').lower()
            return jsonify(
                {
                    'found': True,
                    'preferred_name': entry.get('preferred_name', ''),
                    'object_type': entry.get('object_type', ''),
                    'constellation': full_constellation,
                    'catalogue_names': entry.get('aliases', {}),
                }
            )

        # Fallback: query SIMBAD TAP to support extended catalogs (HIP, HD, SAO, TYC…)
        from observation.object_info import (
            resolve_identifier_for_catalogue_lookup,
            build_catalogue_names_from_aliases,
            is_safe_identifier,
        )

        if is_safe_identifier(name):
            simbad = resolve_identifier_for_catalogue_lookup(name)
            if simbad:
                catalogue_names = build_catalogue_names_from_aliases(name, simbad['aliases'])
                # preferred_name: the typed identifier if it maps to a known catalog,
                # otherwise the best sorted alias, otherwise the typed identifier as-is.
                if any(v == name for v in catalogue_names.values()):
                    preferred_name = name
                else:
                    preferred_name = simbad['aliases'][0] if simbad['aliases'] else name
                return jsonify(
                    {
                        'found': True,
                        'preferred_name': preferred_name,
                        'object_type': simbad['object_type'],
                        'constellation': simbad['constellation'],
                        'catalogue_names': catalogue_names,
                    }
                )

        return jsonify({'found': False})
    except Exception as e:
        logger.error(f"Error in catalogue lookup: {e}")
        return jsonify({'error': 'Internal server error'}), 500
