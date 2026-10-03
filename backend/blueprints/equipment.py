"""Equipment Profiles Blueprint. Routes: /api/equipment/*"""

from dataclasses import asdict

from flask import Blueprint, jsonify, request

from equipment import equipment_profiles
from observation import astrodex
from utils.auth import get_current_user, user_manager, user_required
from utils.logging_config import get_logger
from utils.repo_config import load_config

logger = get_logger(__name__)

equipment_bp = Blueprint('equipment', __name__)


def _resolve_astrodex_visibility_context():
    """Return (private_mode, usernames_by_id) - shared by every route that needs to resolve
    Astrodex picture visibility/ownership, so a future change to either only needs updating here.
    """
    config = load_config()
    private_mode = bool(config.get('astrodex', {}).get('private', False))
    users = user_manager.list_users()
    usernames_by_id = {
        user_entry.get('user_id', ''): user_entry.get('username', 'unknown')
        for user_entry in users
        if user_entry.get('user_id')
    }
    return private_mode, usernames_by_id


def _build_combination_photo_index_for_current_user(user, user_id):
    """Build the per-combination Astrodex photo index for the requesting user."""
    private_mode, usernames_by_id = _resolve_astrodex_visibility_context()
    return astrodex.build_combination_photo_index(user_id, user.username, private_mode, usernames_by_id)


def _validate_numeric_ranges(data, specs):
    """Shared range-check helper: specs is a list of (field, lo, hi, unit) tuples.
    Returns an error message string for the first out-of-range/non-numeric field found among
    those present in ``data``, else None. Mirrors the min/max attributes on the matching
    frontend number inputs in equipment.js so the API rejects what the UI already disallows.
    """
    for field, lo, hi, unit in specs:
        if field in data and data[field] not in (None, ''):
            try:
                val = float(data[field])
                if not (lo <= val <= hi):
                    return f'{field} must be between {lo} and {hi} {unit}'.strip()
            except TypeError, ValueError:
                return f'{field} must be a number'
    return None


def _validate_telescope_data(data):
    """Return an error message string if telescope numeric fields are out of range, else None."""
    return _validate_numeric_ranges(
        data,
        [
            ('aperture_mm', 10, 5000, 'mm'),
            ('focal_length_mm', 100, 50000, 'mm'),
            ('reducer_barlow_factor', 0.1, 3.0, ''),
            ('weight_kg', 0, 100, 'kg'),
        ],
    )


def _validate_camera_data(data):
    """Return an error message string if camera numeric fields are out of range, else None."""
    return _validate_numeric_ranges(
        data,
        [
            ('sensor_width_mm', 1, 100, 'mm'),
            ('sensor_height_mm', 1, 100, 'mm'),
            ('pixel_size_um', 1, 10, 'um'),
            ('resolution_width_px', 640, 16000, 'px'),
            ('resolution_height_px', 480, 12000, 'px'),
            ('min_temperature_c', -50, 0, 'C'),
            ('weight_kg', 0, 50, 'kg'),
        ],
    )


def _validate_mount_data(data):
    """Return an error message string if mount numeric fields are out of range, else None."""
    return _validate_numeric_ranges(
        data,
        [
            ('payload_capacity_kg', 0.1, 100, 'kg'),
            ('tracking_accuracy_arcsec', 0.1, 10, 'arcsec'),
            ('meridian_flip_delay_min', 0, 120, 'min'),
            ('meridian_flip_duration_min', 0, 60, 'min'),
        ],
    )


def _validate_filter_data(data):
    """Return an error message string if filter numeric fields are out of range, else None."""
    return _validate_numeric_ranges(
        data,
        [
            ('central_wavelength_nm', 300, 2000, 'nm'),
            ('bandwidth_nm', 1, 1000, 'nm'),
        ],
    )


def _validate_accessory_data(data):
    """Return an error message string if accessory numeric fields are out of range, else None."""
    return _validate_numeric_ranges(data, [('weight_kg', 0, 50, 'kg')])


def _validate_combination_data(data):
    """Return an error message string if combination numeric fields are out of range, else None."""
    return _validate_numeric_ranges(
        data,
        [
            ('lens_focal_length_mm', 1, 2000, 'mm'),
            ('lens_focal_ratio', 0.5, 32, ''),
        ],
    )


# Telescopes
@equipment_bp.route('/api/equipment/telescopes', methods=['GET'])
@user_required
def get_telescopes():
    """Get user's telescope profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_telescopes(user_id)
        shared = equipment_profiles.load_all_shared_equipment('telescopes', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting telescopes: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/telescopes', methods=['POST'])
@user_required
def create_telescope():
    """Create a new telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_data = request.json
        err = _validate_telescope_data(telescope_data)
        if err:
            return jsonify({'error': err}), 400
        new_telescope = equipment_profiles.create_telescope(user_id, telescope_data)

        if new_telescope:
            return jsonify({'status': 'success', 'data': new_telescope}), 201
        else:
            return jsonify({'error': 'Failed to create telescope'}), 500
    except Exception as e:
        logger.error(f"Error creating telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/telescopes/<telescope_id>', methods=['GET'])
@user_required
def get_telescope(telescope_id):
    """Get a specific telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope = equipment_profiles.get_telescope(user_id, telescope_id)

        if telescope:
            return jsonify(telescope)
        else:
            return jsonify({'error': 'Telescope not found'}), 404
    except Exception as e:
        logger.error(f"Error getting telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/telescopes/<telescope_id>', methods=['PUT'])
@user_required
def update_telescope(telescope_id):
    """Update a telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_data = request.json
        err = _validate_telescope_data(telescope_data)
        if err:
            return jsonify({'error': err}), 400
        shared = equipment_profiles.load_all_shared_equipment('telescopes', user_id)
        if any(t['id'] == telescope_id for t in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_telescope = equipment_profiles.update_telescope(user_id, telescope_id, telescope_data)

        if updated_telescope:
            return jsonify({'status': 'success', 'data': updated_telescope})
        else:
            return jsonify({'error': 'Telescope not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/telescopes/<telescope_id>', methods=['DELETE'])
@user_required
def delete_telescope(telescope_id):
    """Delete a telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, blocked_by = equipment_profiles.delete_telescope(user_id, telescope_id)

        if success:
            return jsonify({'status': 'success'})
        elif blocked_by:
            return jsonify({'error': 'in_use_by_combination', 'combinations': blocked_by}), 409
        else:
            return jsonify({'error': 'Failed to delete telescope'}), 500
    except Exception as e:
        logger.error(f"Error deleting telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Cameras
@equipment_bp.route('/api/equipment/cameras', methods=['GET'])
@user_required
def get_cameras():
    """Get user's camera profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_cameras(user_id)
        shared = equipment_profiles.load_all_shared_equipment('cameras', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting cameras: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/cameras', methods=['POST'])
@user_required
def create_camera():
    """Create a new camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera_data = request.json
        err = _validate_camera_data(camera_data)
        if err:
            return jsonify({'error': err}), 400
        new_camera = equipment_profiles.create_camera(user_id, camera_data)

        if new_camera:
            return jsonify({'status': 'success', 'data': new_camera}), 201
        else:
            return jsonify({'error': 'Failed to create camera'}), 500
    except Exception as e:
        logger.error(f"Error creating camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/cameras/<camera_id>', methods=['GET'])
@user_required
def get_camera(camera_id):
    """Get a specific camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera = equipment_profiles.get_camera(user_id, camera_id)

        if camera:
            return jsonify(camera)
        else:
            return jsonify({'error': 'Camera not found'}), 404
    except Exception as e:
        logger.error(f"Error getting camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/cameras/<camera_id>', methods=['PUT'])
@user_required
def update_camera(camera_id):
    """Update a camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera_data = request.json
        err = _validate_camera_data(camera_data)
        if err:
            return jsonify({'error': err}), 400
        shared = equipment_profiles.load_all_shared_equipment('cameras', user_id)
        if any(c['id'] == camera_id for c in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_camera = equipment_profiles.update_camera(user_id, camera_id, camera_data)

        if updated_camera:
            return jsonify({'status': 'success', 'data': updated_camera})
        else:
            return jsonify({'error': 'Camera not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/cameras/<camera_id>', methods=['DELETE'])
@user_required
def delete_camera(camera_id):
    """Delete a camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, blocked_by = equipment_profiles.delete_camera(user_id, camera_id)

        if success:
            return jsonify({'status': 'success'})
        elif blocked_by:
            return jsonify({'error': 'in_use_by_combination', 'combinations': blocked_by}), 409
        else:
            return jsonify({'error': 'Failed to delete camera'}), 500
    except Exception as e:
        logger.error(f"Error deleting camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Mounts
@equipment_bp.route('/api/equipment/mounts', methods=['GET'])
@user_required
def get_mounts():
    """Get user's mount profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_mounts(user_id)
        shared = equipment_profiles.load_all_shared_equipment('mounts', user_id)
        # Backfill v1.4 meridian-flip fields so pre-v1.4 mount files render a flip
        # summary in the equipment UI (load_user_mounts returns stored dicts verbatim).
        normalize = equipment_profiles.normalize_mount_flip_fields
        return jsonify(
            {
                'data': [normalize(item) for item in data.get('items', [])],
                'shared_from_others': [normalize(item) for item in shared],
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting mounts: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/mounts', methods=['POST'])
@user_required
def create_mount():
    """Create a new mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount_data = request.json
        err = _validate_mount_data(mount_data)
        if err:
            return jsonify({'error': err}), 400
        new_mount = equipment_profiles.create_mount(user_id, mount_data)

        if new_mount:
            return jsonify({'status': 'success', 'data': new_mount}), 201
        else:
            return jsonify({'error': 'Failed to create mount'}), 500
    except Exception as e:
        logger.error(f"Error creating mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/mounts/<mount_id>', methods=['GET'])
@user_required
def get_mount(mount_id):
    """Get a specific mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount = equipment_profiles.get_mount(user_id, mount_id)

        if mount:
            return jsonify(mount)
        else:
            return jsonify({'error': 'Mount not found'}), 404
    except Exception as e:
        logger.error(f"Error getting mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/mounts/<mount_id>', methods=['PUT'])
@user_required
def update_mount(mount_id):
    """Update a mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount_data = request.json
        err = _validate_mount_data(mount_data)
        if err:
            return jsonify({'error': err}), 400
        shared = equipment_profiles.load_all_shared_equipment('mounts', user_id)
        if any(m['id'] == mount_id for m in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_mount = equipment_profiles.update_mount(user_id, mount_id, mount_data)

        if updated_mount:
            return jsonify({'status': 'success', 'data': updated_mount})
        else:
            return jsonify({'error': 'Mount not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/mounts/<mount_id>', methods=['DELETE'])
@user_required
def delete_mount(mount_id):
    """Delete a mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, blocked_by = equipment_profiles.delete_mount(user_id, mount_id)

        if success:
            return jsonify({'status': 'success'})
        elif blocked_by:
            return jsonify({'error': 'in_use_by_combination', 'combinations': blocked_by}), 409
        else:
            return jsonify({'error': 'Failed to delete mount'}), 500
    except Exception as e:
        logger.error(f"Error deleting mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Filters
@equipment_bp.route('/api/equipment/filters', methods=['GET'])
@user_required
def get_filters():
    """Get user's filter profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_filters(user_id)
        shared = equipment_profiles.load_all_shared_equipment('filters', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting filters: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/filters', methods=['POST'])
@user_required
def create_filter():
    """Create a new filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_data = request.json
        err = _validate_filter_data(filter_data)
        if err:
            return jsonify({'error': err}), 400
        new_filter = equipment_profiles.create_filter(user_id, filter_data)

        if new_filter:
            return jsonify({'status': 'success', 'data': new_filter}), 201
        else:
            return jsonify({'error': 'Failed to create filter'}), 500
    except Exception as e:
        logger.error(f"Error creating filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/filters/<filter_id>', methods=['GET'])
@user_required
def get_filter(filter_id):
    """Get a specific filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_obj = equipment_profiles.get_filter(user_id, filter_id)

        if filter_obj:
            return jsonify(filter_obj)
        else:
            return jsonify({'error': 'Filter not found'}), 404
    except Exception as e:
        logger.error(f"Error getting filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/filters/<filter_id>', methods=['PUT'])
@user_required
def update_filter(filter_id):
    """Update a filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_data = request.json
        err = _validate_filter_data(filter_data)
        if err:
            return jsonify({'error': err}), 400
        shared = equipment_profiles.load_all_shared_equipment('filters', user_id)
        if any(f['id'] == filter_id for f in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_filter = equipment_profiles.update_filter(user_id, filter_id, filter_data)

        if updated_filter:
            return jsonify({'status': 'success', 'data': updated_filter})
        else:
            return jsonify({'error': 'Filter not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/filters/<filter_id>', methods=['DELETE'])
@user_required
def delete_filter(filter_id):
    """Delete a filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, blocked_by = equipment_profiles.delete_filter(user_id, filter_id)

        if success:
            return jsonify({'status': 'success'})
        elif blocked_by:
            return jsonify({'error': 'in_use_by_combination', 'combinations': blocked_by}), 409
        else:
            return jsonify({'error': 'Failed to delete filter'}), 500
    except Exception as e:
        logger.error(f"Error deleting filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Accessories
@equipment_bp.route('/api/equipment/accessories', methods=['GET'])
@user_required
def get_accessories():
    """Get user's accessory profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_accessories(user_id)
        shared = equipment_profiles.load_all_shared_equipment('accessories', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting accessories: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/accessories', methods=['POST'])
@user_required
def create_accessory():
    """Create a new accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory_data = request.json
        err = _validate_accessory_data(accessory_data)
        if err:
            return jsonify({'error': err}), 400
        new_accessory = equipment_profiles.create_accessory(user_id, accessory_data)

        if new_accessory:
            return jsonify({'status': 'success', 'data': new_accessory}), 201
        else:
            return jsonify({'error': 'Failed to create accessory'}), 500
    except Exception as e:
        logger.error(f"Error creating accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/accessories/<accessory_id>', methods=['GET'])
@user_required
def get_accessory(accessory_id):
    """Get a specific accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory = equipment_profiles.get_accessory(user_id, accessory_id)

        if accessory:
            return jsonify(accessory)
        else:
            return jsonify({'error': 'Accessory not found'}), 404
    except Exception as e:
        logger.error(f"Error getting accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/accessories/<accessory_id>', methods=['PUT'])
@user_required
def update_accessory(accessory_id):
    """Update an accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory_data = request.json
        err = _validate_accessory_data(accessory_data)
        if err:
            return jsonify({'error': err}), 400
        shared = equipment_profiles.load_all_shared_equipment('accessories', user_id)
        if any(a['id'] == accessory_id for a in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_accessory = equipment_profiles.update_accessory(user_id, accessory_id, accessory_data)

        if updated_accessory:
            return jsonify({'status': 'success', 'data': updated_accessory})
        else:
            return jsonify({'error': 'Failed to update accessory'}), 500
    except Exception as e:
        logger.error(f"Error updating accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/accessories/<accessory_id>', methods=['DELETE'])
@user_required
def delete_accessory(accessory_id):
    """Delete an accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, blocked_by = equipment_profiles.delete_accessory(user_id, accessory_id)

        if success:
            return jsonify({'status': 'success'})
        elif blocked_by:
            return jsonify({'error': 'in_use_by_combination', 'combinations': blocked_by}), 409
        else:
            return jsonify({'error': 'Failed to delete accessory'}), 500
    except Exception as e:
        logger.error(f"Error deleting accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Equipment Combinations
@equipment_bp.route('/api/equipment/combinations', methods=['GET'])
@user_required
def get_combinations():
    """Get user's equipment combinations"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        photo_index = _build_combination_photo_index_for_current_user(user, user_id)

        data = equipment_profiles.load_user_combinations(user_id)
        # Built once and reused for every combination below instead of each status/validity call
        # re-scanning all 5 equipment types (own + shared) from disk per combination.
        equipment_index = equipment_profiles.index_owned_and_shared_equipment(user_id)
        items_with_status = []
        for combo in data.get('items', []):
            status = equipment_profiles.compute_combination_share_status(combo, user_id, equipment_index)
            validity = equipment_profiles.compute_combination_validity_status(combo, user_id, equipment_index)
            photo_stats = astrodex.summarize_combination_pictures(photo_index.get(combo['id'], []))
            items_with_status.append({**combo, **status, **validity, **photo_stats})
        shared_with_status = equipment_profiles.load_all_shared_combinations(user_id)
        for combo in shared_with_status:
            photo_stats = astrodex.summarize_combination_pictures(photo_index.get(combo['id'], []))
            combo.update(photo_stats)
        return jsonify(
            {
                'data': items_with_status,
                'shared_from_others': shared_with_status,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting combinations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/combinations', methods=['POST'])
@user_required
def create_combination():
    """Create a new equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_data = request.json
        err = _validate_combination_data(combination_data)
        if err:
            return jsonify({'error': err}), 400
        new_combination = equipment_profiles.create_combination(user_id, combination_data)

        if new_combination:
            return jsonify({'status': 'success', 'data': new_combination}), 201
        else:
            return (
                jsonify({'error': 'Failed to create combination. At minimum a telescope or camera must be selected.'}),
                400,
            )
    except Exception as e:
        logger.error(f"Error creating combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/combinations/<combination_id>', methods=['GET'])
@user_required
def get_combination(combination_id):
    """Get a specific equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination = equipment_profiles.get_combination(user_id, combination_id)
        status = {}
        validity = {}
        if combination:
            status = equipment_profiles.compute_combination_share_status(combination, user_id)
            validity = equipment_profiles.compute_combination_validity_status(combination, user_id)
        else:
            # Not owned by this user - fall back to combinations shared with them, same as the
            # list endpoint. load_all_shared_combinations already merges share/validity status
            # and owner info into the combo dict (computed from the owner's perspective), so
            # status/validity stay empty here and {**combination, **status, **validity} below
            # still yields the fully-annotated shape either way.
            combination = next(
                (c for c in equipment_profiles.load_all_shared_combinations(user_id) if c['id'] == combination_id),
                None,
            )

        if combination:
            private_mode, usernames_by_id = _resolve_astrodex_visibility_context()
            pictures = astrodex.get_pictures_for_combination(
                combination_id, user_id, user.username, private_mode, usernames_by_id
            )
            photo_stats = astrodex.summarize_combination_pictures(pictures)
            return jsonify({**combination, **status, **validity, **photo_stats})
        else:
            return jsonify({'error': 'Combination not found'}), 404
    except Exception as e:
        logger.error(f"Error getting combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/combinations/<combination_id>', methods=['PUT'])
@user_required
def update_combination(combination_id):
    """Update an equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_data = request.json
        err = _validate_combination_data(combination_data)
        if err:
            return jsonify({'error': err}), 400
        updated_combination = equipment_profiles.update_combination(user_id, combination_id, combination_data)

        if updated_combination:
            return jsonify({'status': 'success', 'data': updated_combination})
        else:
            return jsonify({'error': 'Combination not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@equipment_bp.route('/api/equipment/combinations/<combination_id>', methods=['DELETE'])
@user_required
def delete_combination(combination_id):
    """Delete an equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success, reason = equipment_profiles.delete_combination(user_id, combination_id)

        if success:
            return jsonify({'status': 'success'})
        elif reason == 'in_use_by_picture':
            return jsonify({'error': 'in_use_by_picture'}), 409
        elif reason == 'in_use_by_plan':
            return jsonify({'error': 'in_use_by_plan'}), 409
        elif reason == 'in_use_by_session':
            return jsonify({'error': 'in_use_by_session'}), 409
        else:
            return jsonify({'error': 'Failed to delete combination'}), 500
    except Exception as e:
        logger.error(f"Error deleting combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# FOV Calculator (standalone endpoint)
@equipment_bp.route('/api/equipment/fov-calculator', methods=['POST'])
@user_required
def calculate_fov():
    """Calculate Field of View for given parameters"""
    try:
        data = request.json

        fov_calculation = equipment_profiles.calculate_fov(
            telescope_focal_length_mm=float(data['telescope_focal_length_mm']),
            camera_sensor_width_mm=float(data['camera_sensor_width_mm']),
            camera_sensor_height_mm=float(data['camera_sensor_height_mm']),
            camera_pixel_size_um=float(data['camera_pixel_size_um']),
            seeing_arcsec=float(data.get('seeing_arcsec', 2.0)),
        )

        return jsonify(asdict(fov_calculation))
    except Exception as e:
        logger.error(f"Error calculating FOV: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Equipment Summary
@equipment_bp.route('/api/equipment/summary', methods=['GET'])
@user_required
def get_equipment_summary():
    """Get summary of all user equipment"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        summary = equipment_profiles.get_all_equipment_summary(user_id)
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error getting equipment summary: {e}")
        return jsonify({'error': 'Internal server error'}), 500
