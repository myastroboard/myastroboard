"""
Tests for Equipment Profiles Module
"""
import pytest
import os
import json
import tempfile
import sys
import types

from equipment import equipment_profiles


@pytest.fixture
def temp_data_dir(monkeypatch):
    """Create a temporary data directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        # Recreate the module-level EQUIPMENT_DIR with new temp path
        equipment_profiles.EQUIPMENT_DIR = os.path.join(tmpdir, 'equipments')
        yield tmpdir


@pytest.fixture
def test_user_id():
    """Provide a test user ID"""
    return "test-user-123"


# ============================================================
# Telescope Tests
# ============================================================

def test_create_telescope(temp_data_dir, test_user_id):
    """Test creating a telescope profile"""
    telescope_data = {
        'name': 'Test Refractor',
        'telescope_type': 'Refractor',
        'aperture_mm': 102,
        'focal_length_mm': 714,
        'reducer_barlow_factor': 0.8,
        'notes': 'My first scope'
    }
    
    telescope = equipment_profiles.create_telescope(test_user_id, telescope_data)
    
    assert telescope is not None
    assert telescope['name'] == 'Test Refractor'
    assert telescope['aperture_mm'] == 102
    assert telescope['focal_length_mm'] == 714
    assert telescope['native_focal_ratio'] == 7.0  # 714 / 102
    assert telescope['effective_focal_length'] == 571.2  # 714 * 0.8
    assert telescope['effective_focal_ratio'] == 5.6  # 571.2 / 102
    assert 'id' in telescope
    assert 'created_at' in telescope


def test_create_apo_telescope(temp_data_dir, test_user_id):
    """Test creating an APO refractor telescope profile."""
    telescope_data = {
        "name": "Test APO",
        "telescope_type": "Apochromatic Refractor (APO)",
        "aperture_mm": 102,
        "focal_length_mm": 714,
        "reducer_barlow_factor": 1.0,
    }

    telescope = equipment_profiles.create_telescope(test_user_id, telescope_data)

    assert telescope is not None
    assert telescope["telescope_type"] == equipment_profiles.TelescopeType.APO.value
    expected_ratio = round(telescope_data["focal_length_mm"] / telescope_data["aperture_mm"], 2)
    assert telescope["native_focal_ratio"] == expected_ratio


def test_create_edgehd_telescope(temp_data_dir, test_user_id):
    """Test creating an EdgeHD telescope profile."""
    telescope_data = {
        "name": "Test EdgeHD",
        "telescope_type": "EdgeHD",
        "aperture_mm": 279,
        "focal_length_mm": 2800,
        "reducer_barlow_factor": 1.0,
    }

    telescope = equipment_profiles.create_telescope(test_user_id, telescope_data)

    assert telescope is not None
    assert telescope["telescope_type"] == equipment_profiles.TelescopeType.EDGEHD.value
    expected_ratio = round(telescope_data["focal_length_mm"] / telescope_data["aperture_mm"], 2)
    assert telescope["native_focal_ratio"] == expected_ratio


def test_create_rasa_telescope(temp_data_dir, test_user_id):
    """Test creating a RASA telescope profile."""
    telescope_data = {
        "name": "Test RASA",
        "telescope_type": "Rowe Ackerman Schmidt Astrograph (RASA)",
        "aperture_mm": 279,
        "focal_length_mm": 620,
        "reducer_barlow_factor": 1.0,
    }

    telescope = equipment_profiles.create_telescope(test_user_id, telescope_data)

    assert telescope is not None
    assert telescope["telescope_type"] == equipment_profiles.TelescopeType.RASA.value
    expected_ratio = round(telescope_data["focal_length_mm"] / telescope_data["aperture_mm"], 2)
    assert telescope["native_focal_ratio"] == expected_ratio


def test_update_rasa_telescope(temp_data_dir, test_user_id):
    """Test updating a RASA telescope profile."""
    telescope_data = {
        "name": "Test RASA",
        "telescope_type": "Rowe Ackerman Schmidt Astrograph (RASA)",
        "aperture_mm": 279,
        "focal_length_mm": 620,
        "reducer_barlow_factor": 1.0,
    }

    created = equipment_profiles.create_telescope(test_user_id, telescope_data)

    update_data = {
        "name": "Updated RASA",
        "telescope_type": "Rowe Ackerman Schmidt Astrograph (RASA)",
        "aperture_mm": 279,
        "focal_length_mm": 620,
        "reducer_barlow_factor": 1.0,
        "notes": "Updated notes",
    }

    updated = equipment_profiles.update_telescope(test_user_id, created["id"], update_data)

    assert updated is not None
    assert updated["name"] == update_data["name"]
    assert updated["telescope_type"] == equipment_profiles.TelescopeType.RASA.value
    expected_ratio = round(update_data["focal_length_mm"] / update_data["aperture_mm"], 2)
    assert updated["native_focal_ratio"] == expected_ratio
    assert updated["notes"] == "Updated notes"


def test_get_telescope(temp_data_dir, test_user_id):
    """Test retrieving a telescope profile"""
    telescope_data = {
        'name': 'Test SCT',
        'telescope_type': 'Schmidt-Cassegrain (SCT)',
        'aperture_mm': 203,
        'focal_length_mm': 2032,
        'reducer_barlow_factor': 0.63
    }
    
    created = equipment_profiles.create_telescope(test_user_id, telescope_data)
    retrieved = equipment_profiles.get_telescope(test_user_id, created['id'])
    
    assert retrieved is not None
    assert retrieved['id'] == created['id']
    assert retrieved['name'] == 'Test SCT'


def test_update_telescope(temp_data_dir, test_user_id):
    """Test updating a telescope profile"""
    telescope_data = {
        'name': 'Old Name',
        'telescope_type': 'Refractor',
        'aperture_mm': 80,
        'focal_length_mm': 400,
        'reducer_barlow_factor': 1.0
    }
    
    created = equipment_profiles.create_telescope(test_user_id, telescope_data)
    
    update_data = {
        'name': 'New Name',
        'telescope_type': 'Refractor',
        'aperture_mm': 80,
        'focal_length_mm': 480,  # Changed
        'reducer_barlow_factor': 1.0,
        'notes': 'Updated notes'
    }
    
    updated = equipment_profiles.update_telescope(test_user_id, created['id'], update_data)
    
    assert updated is not None
    assert updated['name'] == 'New Name'
    assert updated['focal_length_mm'] == 480
    assert updated['notes'] == 'Updated notes'


def test_delete_telescope(temp_data_dir, test_user_id):
    """Test deleting a telescope profile"""
    telescope_data = {
        'name': 'To Delete',
        'telescope_type': 'Newtonian',
        'aperture_mm': 200,
        'focal_length_mm': 1000,
        'reducer_barlow_factor': 1.0
    }
    
    created = equipment_profiles.create_telescope(test_user_id, telescope_data)
    success, blocked_by = equipment_profiles.delete_telescope(test_user_id, created['id'])

    assert success is True
    assert blocked_by is None

    # Verify it's gone
    retrieved = equipment_profiles.get_telescope(test_user_id, created['id'])
    assert retrieved is None


# ============================================================
# Camera Tests
# ============================================================

def test_create_camera(temp_data_dir, test_user_id):
    """Test creating a camera profile"""
    camera_data = {
        'name': 'ASI294MC Pro',
        'manufacturer': 'ZWO',
        'sensor_width_mm': 19.1,
        'sensor_height_mm': 13.0,
        'resolution_width_px': 4144,
        'resolution_height_px': 2822,
        'pixel_size_um': 4.63,
        'sensor_type': 'CMOS Color',
        'cooling_supported': True,
        'min_temperature_c': -10,
        'read_noise_e': 3.8,
        'quantum_efficiency': 80
    }
    
    camera = equipment_profiles.create_camera(test_user_id, camera_data)
    
    assert camera is not None
    assert camera['name'] == 'ASI294MC Pro'
    assert camera['sensor_diagonal_mm'] > 0  # Should be calculated
    assert camera['cooling_supported'] is True
    assert camera['min_temperature_c'] == -10


def test_camera_diagonal_calculation(temp_data_dir, test_user_id):
    """Test that camera diagonal is correctly calculated"""
    camera_data = {
        'name': 'Test Camera',
        'manufacturer': 'Test',
        'sensor_width_mm': 3.0,
        'sensor_height_mm': 4.0,  # 3-4-5 triangle
        'resolution_width_px': 1920,
        'resolution_height_px': 1080,
        'pixel_size_um': 5.0,
        'sensor_type': 'CMOS Mono'
    }
    
    camera = equipment_profiles.create_camera(test_user_id, camera_data)
    
    # Diagonal should be 5.0 (3-4-5 triangle)
    assert camera['sensor_diagonal_mm'] == 5.0


# ============================================================
# Mount Tests
# ============================================================

def test_create_mount(temp_data_dir, test_user_id):
    """Test creating a mount profile"""
    mount_data = {
        'name': 'EQ6-R Pro',
        'mount_type': 'Equatorial',
        'payload_capacity_kg': 20,
        'tracking_accuracy_arcsec': 1.5,
        'guiding_supported': True
    }
    
    mount = equipment_profiles.create_mount(test_user_id, mount_data)
    
    assert mount is not None
    assert mount['name'] == 'EQ6-R Pro'
    assert mount['payload_capacity_kg'] == 20
    assert mount['recommended_payload_kg'] == 15.0  # 75% of 20
    assert mount['guiding_supported'] is True


# ============================================================
# Filter Tests
# ============================================================

def test_create_filter(temp_data_dir, test_user_id):
    """Test creating a filter profile"""
    filter_data = {
        'name': 'H-Alpha 7nm',
        'filter_type': 'Narrowband',
        'central_wavelength_nm': 656.3,
        'bandwidth_nm': 7,
        'intended_use': 'Emission nebulae imaging'
    }
    
    filter_obj = equipment_profiles.create_filter(test_user_id, filter_data)
    
    assert filter_obj is not None
    assert filter_obj['name'] == 'H-Alpha 7nm'
    assert filter_obj['central_wavelength_nm'] == 656.3
    assert filter_obj['bandwidth_nm'] == 7


# ============================================================
# FOV Calculator Tests
# ============================================================

def test_fov_calculation():
    """Test Field of View calculation"""
    # Example: 80mm refractor f/6 with ASI294MC Pro
    fov = equipment_profiles.calculate_fov(
        telescope_focal_length_mm=480,
        camera_sensor_width_mm=19.1,
        camera_sensor_height_mm=13.0,
        camera_pixel_size_um=4.63,
        seeing_arcsec=2.0
    )
    
    assert fov.horizontal_fov_deg > 0
    assert fov.vertical_fov_deg > 0
    assert fov.diagonal_fov_deg > 0
    assert fov.image_scale_arcsec_per_px > 0
    assert fov.sampling_classification in ['Undersampled', 'Optimal', 'Oversampled']


def test_fov_sampling_classification():
    """Test FOV sampling classification"""
    # Undersampled case (large image scale - pixels too big for seeing)
    # Need: image_scale > seeing/2 (i.e., > 1.0 for 2" seeing)
    # Formula: image_scale = 206.265 * pixel_um/1000 / focal_mm
    # For undersampling: use very large pixels (webcam) with very short FL
    fov_under = equipment_profiles.calculate_fov(
        telescope_focal_length_mm=1.2,  # Extremely short FL (unrealistic but for testing)
        camera_sensor_width_mm=10,
        camera_sensor_height_mm=10,
        camera_pixel_size_um=6,  # Typical webcam pixel size
        seeing_arcsec=2.0
    )
    # Image scale = 206.265 * 6/1000 / 1.2 = 1.03 arcsec/px
    # Optimal max = 2/2 = 1.0, so 1.03 > 1.0 = Undersampled
    assert fov_under.sampling_classification == 'Undersampled'
    
    # Optimal case (optimal sampling for seeing)
    # Need: seeing/3 < image_scale < seeing/2 (i.e., 0.67 to 1.0 for 2" seeing)
    fov_optimal = equipment_profiles.calculate_fov(
        telescope_focal_length_mm=1000,
        camera_sensor_width_mm=10,
        camera_sensor_height_mm=10,
        camera_pixel_size_um=3.76,
        seeing_arcsec=2.0
    )
    # Image scale = 206.265 * 3.76/1000 / 1000 = 0.78 arcsec/px
    # Optimal range: 0.67 to 1.0, so 0.78 is in range = Optimal
    assert fov_optimal.sampling_classification == 'Optimal'
    
    # Oversampled case (small image scale - pixels too small for seeing)
    # Need: image_scale < seeing/3 (i.e., < 0.67 for 2" seeing)
    fov_over = equipment_profiles.calculate_fov(
        telescope_focal_length_mm=3000,
        camera_sensor_width_mm=10,
        camera_sensor_height_mm=10,
        camera_pixel_size_um=2.4,  # Small pixels
        seeing_arcsec=2.0
    )
    # Image scale = 206.265 * 2.4/1000 / 3000 = 0.165 arcsec/px
    # Optimal min = 2/3 = 0.67, so 0.165 < 0.67 = Oversampled
    assert fov_over.sampling_classification == 'Oversampled'


# ============================================================
# Equipment Combination Tests
# ============================================================

def test_create_combination(temp_data_dir, test_user_id):
    """Test creating an equipment combination"""
    # Create some equipment first
    telescope = equipment_profiles.create_telescope(test_user_id, {
        'name': 'Test Scope',
        'telescope_type': 'Refractor',
        'aperture_mm': 102,
        'focal_length_mm': 714,
        'reducer_barlow_factor': 1.0
    })
    
    camera = equipment_profiles.create_camera(test_user_id, {
        'name': 'Test Camera',
        'manufacturer': 'Test',
        'sensor_width_mm': 13.2,
        'sensor_height_mm': 8.8,
        'resolution_width_px': 3096,
        'resolution_height_px': 2080,
        'pixel_size_um': 4.5,
        'sensor_type': 'CMOS Color'
    })
    
    combination_data = {
        'name': 'My Imaging Setup',
        'telescope_id': telescope['id'],
        'camera_id': camera['id'],
        'notes': 'Primary deep-sky setup'
    }
    
    combination = equipment_profiles.create_combination(test_user_id, combination_data)
    
    assert combination is not None
    assert combination['name'] == 'My Imaging Setup'
    assert combination['telescope_id'] == telescope['id']
    assert combination['camera_id'] == camera['id']


def test_combination_requires_telescope_or_camera(temp_data_dir, test_user_id):
    """Test that combination requires at least telescope or camera"""
    combination_data = {
        'name': 'Invalid Setup',
        # No telescope_id or camera_id
    }
    
    combination = equipment_profiles.create_combination(test_user_id, combination_data)
    
    # Should fail because neither telescope nor camera is specified
    assert combination is None


def test_combination_new_fields_roundtrip(temp_data_dir, test_user_id):
    """guide_camera_id, lens_focal_length_mm, lens_focal_ratio and is_disabled persist on create/update."""
    camera = equipment_profiles.create_camera(test_user_id, {
        'name': 'Main Cam', 'manufacturer': 'ZWO', 'sensor_width_mm': 13.2, 'sensor_height_mm': 8.8,
        'resolution_width_px': 3096, 'resolution_height_px': 2080, 'pixel_size_um': 4.5,
        'sensor_type': 'CMOS Color',
    })
    guide_cam = equipment_profiles.create_camera(test_user_id, {
        'name': 'Guide Cam', 'manufacturer': 'ZWO', 'sensor_width_mm': 6.4, 'sensor_height_mm': 4.8,
        'resolution_width_px': 1280, 'resolution_height_px': 960, 'pixel_size_um': 3.75,
        'sensor_type': 'CMOS Mono',
    })

    combo = equipment_profiles.create_combination(test_user_id, {
        'name': 'Wide-Field Rig',
        'camera_id': camera['id'],
        'guide_camera_id': guide_cam['id'],
        'lens_focal_length_mm': '135',
        'lens_focal_ratio': '2.8',
        'is_disabled': True,
    })

    assert combo is not None
    assert combo['telescope_id'] is None
    assert combo['guide_camera_id'] == guide_cam['id']
    assert combo['lens_focal_length_mm'] == 135.0
    assert combo['lens_focal_ratio'] == 2.8
    assert combo['is_disabled'] is True

    updated = equipment_profiles.update_combination(test_user_id, combo['id'], {
        'name': 'Wide-Field Rig',
        'camera_id': camera['id'],
        'guide_camera_id': '',
        'lens_focal_length_mm': '',
        'lens_focal_ratio': '',
        'is_disabled': False,
    })
    assert updated['guide_camera_id'] is None
    assert updated['lens_focal_length_mm'] is None
    assert updated['lens_focal_ratio'] is None
    assert updated['is_disabled'] is False


def test_is_disabled_create_and_update_roundtrip_all_types(temp_data_dir, test_user_id):
    """is_disabled defaults False, persists True on create, and can be toggled back on update."""
    telescope = equipment_profiles.create_telescope(test_user_id, {
        'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
    })
    assert telescope['is_disabled'] is False

    camera = equipment_profiles.create_camera(test_user_id, {
        'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
        'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
        'sensor_type': 'CMOS Color', 'is_disabled': True,
    })
    assert camera['is_disabled'] is True

    mount = equipment_profiles.create_mount(test_user_id, {
        'name': 'Mount', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10, 'is_disabled': True,
    })
    assert mount['is_disabled'] is True
    mount = equipment_profiles.update_mount(test_user_id, mount['id'], {
        'name': 'Mount', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10, 'is_disabled': False,
    })
    assert mount['is_disabled'] is False

    filt = equipment_profiles.create_filter(test_user_id, {
        'name': 'Filter', 'filter_type': 'LRGB', 'is_disabled': True,
    })
    assert filt['is_disabled'] is True
    filt = equipment_profiles.update_filter(test_user_id, filt['id'], {
        'name': 'Filter', 'filter_type': 'LRGB', 'is_disabled': False,
    })
    assert filt['is_disabled'] is False

    accessory = equipment_profiles.create_accessory(test_user_id, {
        'name': 'Focuser', 'accessory_type': 'Focuser', 'is_disabled': True,
    })
    assert accessory['is_disabled'] is True
    accessory = equipment_profiles.update_accessory(test_user_id, accessory['id'], {
        'name': 'Focuser', 'accessory_type': 'Focuser', 'is_disabled': False,
    })
    assert accessory['is_disabled'] is False

    telescope = equipment_profiles.update_telescope(test_user_id, telescope['id'], {
        'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        'is_disabled': True,
    })
    assert telescope['is_disabled'] is True


class TestEquipmentDeleteGuard:
    """A combination referencing equipment blocks that equipment's deletion (feature.md rule)."""

    def test_delete_telescope_blocked_then_succeeds_after_combo_removed(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'],
        })

        success, blocked_by = equipment_profiles.delete_telescope(test_user_id, telescope['id'])
        assert success is False
        assert blocked_by == ['Combo']
        assert equipment_profiles.get_telescope(test_user_id, telescope['id']) is not None

        assert equipment_profiles.delete_combination(test_user_id, combo['id']) == (True, None)
        success, blocked_by = equipment_profiles.delete_telescope(test_user_id, telescope['id'])
        assert success is True
        assert blocked_by is None

    def test_delete_combination_blocked_by_picture(self, temp_data_dir, test_user_id, monkeypatch):
        """A combination referenced by any Astrodex picture can't be deleted (feature.md rule).

        Patches observation.astrodex.count_pictures_for_combination directly (the module
        delete_combination lazily imports from) rather than creating real Astrodex picture
        data, since this test's temp_data_dir fixture only isolates EQUIPMENT_DIR.
        """
        import observation.astrodex as astrodex_module

        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'],
        })

        monkeypatch.setattr(astrodex_module, 'count_pictures_for_combination', lambda combination_id: 1)
        success, reason = equipment_profiles.delete_combination(test_user_id, combo['id'])
        assert success is False
        assert reason == 'in_use_by_picture'

        monkeypatch.setattr(astrodex_module, 'count_pictures_for_combination', lambda combination_id: 0)
        success, reason = equipment_profiles.delete_combination(test_user_id, combo['id'])
        assert success is True
        assert reason is None

    def test_delete_combination_blocked_by_plan(self, temp_data_dir, test_user_id, monkeypatch):
        """A combination pinned to any Plan My Night plan can't be deleted (M5 rule).

        Patches observation.plan_my_night.count_plans_for_combination directly (the module
        delete_combination lazily imports from) rather than creating real plan files, since
        this test's temp_data_dir fixture only isolates EQUIPMENT_DIR - same approach as
        test_delete_combination_blocked_by_picture above.
        """
        import observation.astrodex as astrodex_module
        import observation.plan_my_night as plan_my_night_module

        monkeypatch.setattr(astrodex_module, 'count_pictures_for_combination', lambda combination_id: 0)

        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'],
        })

        monkeypatch.setattr(plan_my_night_module, 'count_plans_for_combination', lambda combination_id: 1)
        success, reason = equipment_profiles.delete_combination(test_user_id, combo['id'])
        assert success is False
        assert reason == 'in_use_by_plan'

        monkeypatch.setattr(plan_my_night_module, 'count_plans_for_combination', lambda combination_id: 0)
        success, reason = equipment_profiles.delete_combination(test_user_id, combo['id'])
        assert success is True
        assert reason is None

    def test_delete_camera_blocked_as_imaging_camera(self, temp_data_dir, test_user_id):
        camera = equipment_profiles.create_camera(test_user_id, {
            'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS Color',
        })
        equipment_profiles.create_combination(test_user_id, {'name': 'Combo', 'camera_id': camera['id']})

        success, blocked_by = equipment_profiles.delete_camera(test_user_id, camera['id'])
        assert success is False
        assert blocked_by == ['Combo']

    def test_delete_camera_blocked_as_guide_camera(self, temp_data_dir, test_user_id):
        """A camera referenced only as guide_camera_id still blocks deletion."""
        main_camera = equipment_profiles.create_camera(test_user_id, {
            'name': 'Main', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS Color',
        })
        guide_camera = equipment_profiles.create_camera(test_user_id, {
            'name': 'Guide', 'manufacturer': 'M', 'sensor_width_mm': 6, 'sensor_height_mm': 4,
            'resolution_width_px': 1280, 'resolution_height_px': 960, 'pixel_size_um': 3.75,
            'sensor_type': 'CMOS Mono',
        })
        equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'camera_id': main_camera['id'], 'guide_camera_id': guide_camera['id'],
        })

        success, blocked_by = equipment_profiles.delete_camera(test_user_id, guide_camera['id'])
        assert success is False
        assert blocked_by == ['Combo']

    def test_delete_mount_blocked(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        mount = equipment_profiles.create_mount(test_user_id, {
            'name': 'Mount', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10,
        })
        equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'], 'mount_id': mount['id'],
        })

        success, blocked_by = equipment_profiles.delete_mount(test_user_id, mount['id'])
        assert success is False
        assert blocked_by == ['Combo']

    def test_delete_filter_blocked(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        filt = equipment_profiles.create_filter(test_user_id, {'name': 'H-Alpha', 'filter_type': 'Narrowband'})
        equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'], 'filter_ids': [filt['id']],
        })

        success, blocked_by = equipment_profiles.delete_filter(test_user_id, filt['id'])
        assert success is False
        assert blocked_by == ['Combo']

    def test_delete_accessory_blocked(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        accessory = equipment_profiles.create_accessory(test_user_id, {
            'name': 'Focuser', 'accessory_type': 'Focuser',
        })
        equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'], 'accessory_ids': [accessory['id']],
        })

        success, blocked_by = equipment_profiles.delete_accessory(test_user_id, accessory['id'])
        assert success is False
        assert blocked_by == ['Combo']

    def test_delete_unreferenced_equipment_not_blocked(self, temp_data_dir, test_user_id):
        """Equipment not used by any combination deletes normally (no false positives)."""
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'Lonely Scope', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        success, blocked_by = equipment_profiles.delete_telescope(test_user_id, telescope['id'])
        assert success is True
        assert blocked_by is None


class TestFindCombinationsReferencing:
    """Direct coverage of _find_combinations_referencing branches."""

    def test_matches_via_list_field(self, temp_data_dir, test_user_id):
        accessory = equipment_profiles.create_accessory(test_user_id, {
            'name': 'OAG', 'accessory_type': 'Off-Axis Guider',
        })
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'], 'accessory_ids': [accessory['id']],
        })
        matches = equipment_profiles._find_combinations_referencing('accessories', accessory['id'])
        assert len(matches) == 1
        assert matches[0]['name'] == 'Combo'
        assert matches[0]['owner_id'] == test_user_id

    def test_no_matches_returns_empty_list(self, temp_data_dir, test_user_id):
        equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        assert equipment_profiles._find_combinations_referencing('telescopes', 'no-such-id') == []

    def test_inner_exception_on_invalid_combinations_file_blocks_delete(self, temp_data_dir, test_user_id):
        """An unreadable combinations file fails the guard closed (blocks delete) rather than
        being silently skipped - it might still reference the equipment being deleted."""
        equipment_profiles.ensure_equipment_directories()
        bad_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, 'someone_combinations.json')
        with open(bad_file, 'w') as f:
            f.write('{invalid')
        matches = equipment_profiles._find_combinations_referencing('telescopes', 'any-id')
        assert len(matches) == 1
        assert matches[0]['owner_id'] == 'someone'

    def test_outer_exception_returns_empty_list(self, temp_data_dir, monkeypatch):
        def raise_oops(_path):
            raise Exception("oops")

        monkeypatch.setattr(equipment_profiles.os, 'listdir', raise_oops)
        assert equipment_profiles._find_combinations_referencing('telescopes', 'any-id') == []


class TestComputeValidityStatusBranches:
    """Covers compute_combination_validity_status: valid, disabled component, missing component."""

    def test_combination_with_only_enabled_components_is_valid(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'],
        })
        status = equipment_profiles.compute_combination_validity_status(combo, test_user_id)
        assert status == {'is_valid': True, 'invalid_reasons': [], 'disabled_component_ids': []}

    def test_disabled_component_makes_combination_invalid(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': telescope['id'],
        })
        equipment_profiles.update_telescope(test_user_id, telescope['id'], {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
            'is_disabled': True,
        })

        status = equipment_profiles.compute_combination_validity_status(combo, test_user_id)
        assert status['is_valid'] is False
        assert f"disabled:{telescope['id']}" in status['invalid_reasons']
        assert telescope['id'] in status['disabled_component_ids']

    def test_missing_component_makes_combination_invalid(self, temp_data_dir, test_user_id):
        """Defensive fallback for combinations referencing equipment that no longer resolves
        (e.g. data created before delete-guards existed)."""
        combo = {
            'telescope_id': 'ghost-id', 'camera_id': None, 'mount_id': None,
            'guide_camera_id': None, 'filter_ids': [], 'accessory_ids': [],
        }
        status = equipment_profiles.compute_combination_validity_status(combo, test_user_id)
        assert status['is_valid'] is False
        assert 'missing:ghost-id' in status['invalid_reasons']
        assert 'ghost-id' in status['disabled_component_ids']

    def test_combination_with_no_references_is_valid(self, temp_data_dir, test_user_id):
        """A combination with an empty reference list has nothing to invalidate."""
        combo = {
            'telescope_id': None, 'camera_id': None, 'mount_id': None,
            'guide_camera_id': None, 'filter_ids': [], 'accessory_ids': [],
        }
        status = equipment_profiles.compute_combination_validity_status(combo, test_user_id)
        assert status == {'is_valid': True, 'invalid_reasons': [], 'disabled_component_ids': []}


def test_analyze_combination(temp_data_dir, test_user_id):
    """Test analyzing an equipment combination"""
    # Create telescope and camera
    telescope = equipment_profiles.create_telescope(test_user_id, {
        'name': 'Refractor 102/714',
        'telescope_type': 'Refractor',
        'aperture_mm': 102,
        'focal_length_mm': 714,
        'reducer_barlow_factor': 0.8
    })
    
    camera = equipment_profiles.create_camera(test_user_id, {
        'name': 'ASI294MC Pro',
        'manufacturer': 'ZWO',
        'sensor_width_mm': 19.1,
        'sensor_height_mm': 13.0,
        'resolution_width_px': 4144,
        'resolution_height_px': 2822,
        'pixel_size_um': 4.63,
        'sensor_type': 'CMOS Color'
    })
    
    combination = equipment_profiles.create_combination(test_user_id, {
        'name': 'Wide-Field Setup',
        'telescope_id': telescope['id'],
        'camera_id': camera['id']
    })
    
    analysis = equipment_profiles.analyze_combination(test_user_id, combination['id'])
    
    assert analysis is not None
    assert analysis.combination_id == combination['id']
    assert analysis.telescope is not None
    assert analysis.camera is not None
    assert analysis.fov_calculation is not None
    assert len(analysis.suitability) > 0  # Should have at least one suitability
    assert len(analysis.recommendations) > 0  # Should have recommendations


def test_equipment_summary(temp_data_dir, test_user_id):
    """Test getting equipment summary"""
    # Create some equipment
    equipment_profiles.create_telescope(test_user_id, {
        'name': 'Scope 1',
        'telescope_type': 'Refractor',
        'aperture_mm': 80,
        'focal_length_mm': 400,
        'reducer_barlow_factor': 1.0
    })
    
    equipment_profiles.create_camera(test_user_id, {
        'name': 'Camera 1',
        'manufacturer': 'Test',
        'sensor_width_mm': 10,
        'sensor_height_mm': 10,
        'resolution_width_px': 1920,
        'resolution_height_px': 1080,
        'pixel_size_um': 5.0,
        'sensor_type': 'CMOS'
    })
    
    summary = equipment_profiles.get_all_equipment_summary(test_user_id)
    
    assert summary['telescopes_count'] == 1
    assert summary['cameras_count'] == 1
    assert summary['mounts_count'] == 0
    assert summary['filters_count'] == 0
    assert summary['combinations_count'] == 0


# ============================================================
# Safety Tests
# ============================================================

def test_safe_save_creates_backup(temp_data_dir, test_user_id):
    """Test that safe save creates backups"""
    # Create initial data
    telescope_data = {
        'name': 'Original',
        'telescope_type': 'Refractor',
        'aperture_mm': 80,
        'focal_length_mm': 400,
        'reducer_barlow_factor': 1.0
    }
    
    equipment_profiles.create_telescope(test_user_id, telescope_data)
    
    file_path = equipment_profiles.get_user_equipment_file(test_user_id, 'telescopes')
    assert os.path.exists(file_path)
    
    # Update should use safe save
    data = equipment_profiles.load_user_telescopes(test_user_id)
    success = equipment_profiles.save_user_telescopes(test_user_id, data)
    
    assert success is True
    # Backup should be cleaned up after successful save
    backup_path = file_path + '.backup'
    assert not os.path.exists(backup_path)


def test_update_and_delete_camera_mount_filter_accessory_and_combination(temp_data_dir, test_user_id):
    camera = equipment_profiles.create_camera(
        test_user_id,
        {
            'name': 'Cam A',
            'manufacturer': 'Maker',
            'sensor_width_mm': 13.2,
            'sensor_height_mm': 8.8,
            'resolution_width_px': 3000,
            'resolution_height_px': 2000,
            'pixel_size_um': 3.8,
            'sensor_type': 'CMOS Color',
            'min_temperature_c': '',
            'read_noise_e': '',
            'quantum_efficiency': '',
        },
    )
    assert camera is not None

    updated_camera = equipment_profiles.update_camera(
        test_user_id,
        camera['id'],
        {
            'name': 'Cam B',
            'manufacturer': 'Maker',
            'sensor_width_mm': 13.2,
            'sensor_height_mm': 8.8,
            'resolution_width_px': 3100,
            'resolution_height_px': 2100,
            'pixel_size_um': 3.8,
            'sensor_type': 'CMOS Color',
            'cooling_supported': True,
            'is_shared': True,
        },
    )
    assert updated_camera is not None
    assert updated_camera['name'] == 'Cam B'

    mount = equipment_profiles.create_mount(
        test_user_id,
        {
            'name': 'Mount A',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 12,
            'tracking_accuracy_arcsec': '',
            'guiding_supported': True,
        },
    )
    assert mount is not None
    updated_mount = equipment_profiles.update_mount(
        test_user_id,
        mount['id'],
        {
            'name': 'Mount B',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 14,
            'tracking_accuracy_arcsec': 1.2,
            'guiding_supported': True,
            'is_shared': True,
        },
    )
    assert updated_mount is not None
    assert updated_mount['recommended_payload_kg'] == 10.5

    filt = equipment_profiles.create_filter(
        test_user_id,
        {
            'name': 'Filter A',
            'filter_type': 'Narrowband',
            'central_wavelength_nm': 656.3,
            'bandwidth_nm': 7,
            'is_shared': True,
        },
    )
    assert filt is not None
    updated_filter = equipment_profiles.update_filter(
        test_user_id,
        filt['id'],
        {
            'name': 'Filter B',
            'filter_type': 'Narrowband',
            'central_wavelength_nm': '',
            'bandwidth_nm': '',
            'is_shared': False,
        },
    )
    assert updated_filter is not None
    assert updated_filter['name'] == 'Filter B'

    accessory = equipment_profiles.create_accessory(
        test_user_id,
        {
            'name': 'Focuser',
            'manufacturer': 'X',
            'accessory_type': 'Focuser',
            'weight_kg': '',
            'is_shared': True,
        },
    )
    assert accessory is not None
    updated_accessory = equipment_profiles.update_accessory(
        test_user_id,
        accessory['id'],
        {
            'name': 'Focuser Pro',
            'manufacturer': 'X',
            'accessory_type': 'Focuser',
            'weight_kg': 0.3,
            'is_shared': False,
        },
    )
    assert updated_accessory is not None
    assert updated_accessory['name'] == 'Focuser Pro'

    scope = equipment_profiles.create_telescope(
        test_user_id,
        {
            'name': 'Scope',
            'telescope_type': 'Refractor',
            'aperture_mm': 80,
            'focal_length_mm': 480,
            'reducer_barlow_factor': 1.0,
        },
    )
    combo = equipment_profiles.create_combination(
        test_user_id,
        {
            'name': 'Combo A',
            'telescope_id': scope['id'],
            'camera_id': camera['id'],
            'mount_id': mount['id'],
            'filter_ids': [filt['id']],
            'accessory_ids': [accessory['id']],
        },
    )
    assert combo is not None

    updated_combo = equipment_profiles.update_combination(
        test_user_id,
        combo['id'],
        {
            'name': 'Combo B',
            'telescope_id': scope['id'],
            'camera_id': camera['id'],
            'mount_id': mount['id'],
            'filter_ids': [],
            'accessory_ids': [],
        },
    )
    assert updated_combo is not None
    assert updated_combo['name'] == 'Combo B'

    assert equipment_profiles.delete_combination(test_user_id, combo['id']) == (True, None)
    assert equipment_profiles.delete_accessory(test_user_id, accessory['id']) == (True, None)
    assert equipment_profiles.delete_filter(test_user_id, filt['id']) == (True, None)
    assert equipment_profiles.delete_mount(test_user_id, mount['id']) == (True, None)
    assert equipment_profiles.delete_camera(test_user_id, camera['id']) == (True, None)


def test_load_helpers_return_defaults_on_invalid_json(temp_data_dir, test_user_id):
    pairs = [
        ('cameras', equipment_profiles.load_user_cameras),
        ('mounts', equipment_profiles.load_user_mounts),
        ('filters', equipment_profiles.load_user_filters),
        ('accessories', equipment_profiles.load_user_accessories),
        ('combinations', equipment_profiles.load_user_combinations),
    ]
    for eq_type, loader in pairs:
        p = equipment_profiles.get_user_equipment_file(test_user_id, eq_type)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('{invalid json')
        loaded = loader(test_user_id)
        assert isinstance(loaded, dict)
        assert isinstance(loaded.get('items', []), list)


def test_shared_equipment_and_combination_status(temp_data_dir, monkeypatch):
    user_a = 'owner-a'
    user_b = 'viewer-b'

    fake_auth = types.SimpleNamespace(
        user_manager=types.SimpleNamespace(
            list_users=lambda: [
                {'user_id': user_a, 'username': 'alice'},
                {'user_id': user_b, 'username': 'bob'},
            ]
        )
    )
    monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)

    tel_file = equipment_profiles.get_user_equipment_file(user_a, 'telescopes')
    cam_file = equipment_profiles.get_user_equipment_file(user_a, 'cameras')
    combo_file = equipment_profiles.get_user_equipment_file(user_a, 'combinations')

    with open(tel_file, 'w', encoding='utf-8') as f:
        json.dump({'items': [{'id': 't1', 'name': 'Scope', 'is_shared': True}]}, f)
    with open(cam_file, 'w', encoding='utf-8') as f:
        json.dump({'items': [{'id': 'c1', 'name': 'Cam', 'is_shared': True}]}, f)
    with open(combo_file, 'w', encoding='utf-8') as f:
        json.dump(
            {
                'items': [
                    {
                        'id': 'combo1',
                        'name': 'Shared Combo',
                        'telescope_id': 't1',
                        'camera_id': 'c1',
                        'mount_id': None,
                        'filter_ids': [],
                        'accessory_ids': [],
                    }
                ]
            },
            f,
        )

    shared_tel = equipment_profiles.load_all_shared_equipment('telescopes', exclude_user_id=user_b)
    assert len(shared_tel) == 1
    assert shared_tel[0]['owner_username'] == 'alice'

    status_ok = equipment_profiles.compute_combination_share_status(
        {
            'telescope_id': 't1',
            'camera_id': 'c1',
            'mount_id': None,
            'filter_ids': [],
            'accessory_ids': [],
        },
        user_a,
    )
    assert status_ok['is_shared'] is True
    assert status_ok['has_broken_share'] is False

    status_broken = equipment_profiles.compute_combination_share_status(
        {
            'telescope_id': 'missing',
            'camera_id': None,
            'mount_id': None,
            'filter_ids': [],
            'accessory_ids': [],
        },
        user_b,
    )
    assert status_broken['is_shared'] is False
    assert status_broken['has_broken_share'] is True
    assert status_broken['broken_items'] == ['missing']

    shared_combos = equipment_profiles.load_all_shared_combinations(exclude_user_id=user_b)
    assert len(shared_combos) == 1
    assert shared_combos[0]['owner_username'] == 'alice'


def test_safe_save_equipment_returns_false_when_validation_fails(tmp_path):
    target = tmp_path / 'equipment.json'
    target.write_text(json.dumps({'items': []}), encoding='utf-8')

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(equipment_profiles, 'validate_equipment_json', lambda _p: (False, 'bad'))
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})

    assert ok is False


def test_analyze_combination_handles_missing_specs_and_missing_combination(temp_data_dir, test_user_id):
    # Missing combination id path
    assert equipment_profiles.analyze_combination(test_user_id, 'does-not-exist') is None

    telescope = equipment_profiles.create_telescope(
        test_user_id,
        {
            'name': 'Scope Missing Details',
            'telescope_type': 'Refractor',
            'aperture_mm': 80,
            'focal_length_mm': 480,
            'reducer_barlow_factor': 1.0,
        },
    )

    combo = equipment_profiles.create_combination(
        test_user_id,
        {
            'name': 'Partial Combo',
            'telescope_id': telescope['id'],
            'camera_id': None,
        },
    )
    analysis = equipment_profiles.analyze_combination(test_user_id, combo['id'])
    assert analysis is not None
    assert len(analysis.recommendations) > 0


# ============================================================
# Additional branch coverage tests
# ============================================================


class TestDataclassBranchCoverage:
    """Covers __post_init__ FALSE branches."""

    def test_telescope_zero_aperture_skips_calculations(self):
        Telescope = equipment_profiles.Telescope
        t = Telescope(
            id='t1', name='Zero', manufacturer='', telescope_type='Refractor',
            aperture_mm=0, focal_length_mm=500, native_focal_ratio=0.0,
        )
        assert t.native_focal_ratio == 0.0
        assert t.effective_focal_length == 0.0
        assert t.effective_focal_ratio == 0.0

    def test_mount_zero_payload_skips_calculation(self):
        Mount = equipment_profiles.Mount
        m = Mount(id='m1', name='No Payload', payload_capacity_kg=0)
        assert m.recommended_payload_kg == 0.0

    def test_equipment_combination_none_lists_set_to_empty(self):
        EquipmentCombination = equipment_profiles.EquipmentCombination
        combo = EquipmentCombination(id='c1', name='Test')
        assert combo.filter_ids == []
        assert combo.accessory_ids == []

    def test_combination_analysis_none_values_set_to_empty(self):
        CombinationAnalysis = equipment_profiles.CombinationAnalysis
        analysis = CombinationAnalysis(combination_id='c1')
        assert analysis.filters == []
        assert analysis.accessories == []
        assert analysis.suitability == []
        assert analysis.recommendations == []


class TestValidateEquipmentJson:
    """Covers all error paths in validate_equipment_json."""

    def test_non_dict_root_returns_false(self, tmp_path):
        p = tmp_path / 'test.json'
        p.write_text(json.dumps([1, 2, 3]))
        ok, msg = equipment_profiles.validate_equipment_json(str(p))
        assert ok is False
        assert 'object' in msg

    def test_missing_items_key_returns_false(self, tmp_path):
        p = tmp_path / 'test.json'
        p.write_text(json.dumps({'name': 'no items'}))
        ok, msg = equipment_profiles.validate_equipment_json(str(p))
        assert ok is False
        assert 'items' in msg

    def test_invalid_json_decode_error(self, tmp_path):
        p = tmp_path / 'test.json'
        p.write_text('{invalid json', encoding='utf-8')
        ok, msg = equipment_profiles.validate_equipment_json(str(p))
        assert ok is False
        assert 'Invalid JSON' in msg

    def test_file_not_found_general_exception(self):
        ok, msg = equipment_profiles.validate_equipment_json('/nonexistent/path/file.json')
        assert ok is False
        assert 'Validation error' in msg


class TestSafeSaveEquipmentEdgeCases:
    """Covers missing branches in safe_save_equipment."""

    def test_validation_fails_no_backup_to_restore(self, tmp_path, monkeypatch):
        target = tmp_path / 'new_equip.json'
        monkeypatch.setattr(equipment_profiles, 'validate_equipment_json', lambda _p: (False, 'bad'))
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})
        assert ok is False

    def test_shutil_move_exception_triggers_recovery(self, tmp_path, monkeypatch):
        target = tmp_path / 'equipment.json'
        target.write_text(json.dumps({'items': []}), encoding='utf-8')

        def fail_move(*_args):
            raise IOError("disk full")

        monkeypatch.setattr(equipment_profiles.shutil, 'move', fail_move)
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})
        assert ok is False


class TestLoadAllSharedEquipmentExceptions:
    """Covers exception paths in load_all_shared_equipment."""

    def test_inner_exception_on_invalid_file_continues(self, temp_data_dir, monkeypatch):
        import types
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': 'owner1', 'username': 'alice'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        bad_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, 'owner1_telescopes.json')
        with open(bad_file, 'w') as f:
            f.write('{invalid')
        result = equipment_profiles.load_all_shared_equipment('telescopes', exclude_user_id='owner2')
        assert result == []

    def test_outer_exception_returns_empty_list(self, temp_data_dir, monkeypatch):
        import types
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(list_users=lambda: [])
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)

        def raise_oops(_path):
            raise Exception("oops")

        monkeypatch.setattr(equipment_profiles.os, 'listdir', raise_oops)
        result = equipment_profiles.load_all_shared_equipment('telescopes', exclude_user_id='user2')
        assert result == []


class TestComputeShareStatusBranches:
    """Covers branch paths in compute_combination_share_status."""

    def test_own_item_not_shared_sets_is_shared_false(self, temp_data_dir, monkeypatch):
        import types
        user_a = 'share-owner'
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': user_a, 'username': 'alice'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        tel_file = equipment_profiles.get_user_equipment_file(user_a, 'telescopes')
        with open(tel_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 't1', 'name': 'Scope', 'is_shared': False}]}, f)
        status = equipment_profiles.compute_combination_share_status(
            {'telescope_id': 't1', 'camera_id': None, 'mount_id': None,
             'filter_ids': [], 'accessory_ids': []},
            user_a,
        )
        assert status['is_shared'] is False
        assert status['has_broken_share'] is False


class TestCRUDExceptionAndNotFound:
    """Covers exception and not-found paths in CRUD functions."""

    def test_load_user_telescopes_invalid_json(self, temp_data_dir, test_user_id):
        p = equipment_profiles.get_user_equipment_file(test_user_id, 'telescopes')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('{invalid json')
        loaded = equipment_profiles.load_user_telescopes(test_user_id)
        assert isinstance(loaded, dict)
        assert isinstance(loaded.get('items', []), list)

    def test_create_telescope_exception_returns_none(self, temp_data_dir, test_user_id):
        result = equipment_profiles.create_telescope(test_user_id, {
            'name': 'Bad Scope',
            'telescope_type': 'Refractor',
            'aperture_mm': 'not_a_float',
            'focal_length_mm': 500,
        })
        assert result is None

    def test_get_telescope_items_exist_but_id_not_found(self, temp_data_dir, test_user_id):
        equipment_profiles.create_telescope(test_user_id, {
            'name': 'Existing',
            'telescope_type': 'Refractor',
            'aperture_mm': 100,
            'focal_length_mm': 500,
            'reducer_barlow_factor': 1.0,
        })
        result = equipment_profiles.get_telescope(test_user_id, 'nonexistent-id')
        assert result is None

    def test_update_telescope_id_not_found_with_items(self, temp_data_dir, test_user_id):
        equipment_profiles.create_telescope(test_user_id, {
            'name': 'Existing Scope',
            'telescope_type': 'Refractor',
            'aperture_mm': 100,
            'focal_length_mm': 500,
            'reducer_barlow_factor': 1.0,
        })
        result = equipment_profiles.update_telescope(test_user_id, 'nonexistent-id', {
            'name': 'Updated',
            'telescope_type': 'Refractor',
            'aperture_mm': 100,
            'focal_length_mm': 500,
            'reducer_barlow_factor': 1.0,
        })
        assert result is None

    def test_update_telescope_exception_returns_none(self, temp_data_dir, test_user_id):
        telescope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'Test Scope',
            'telescope_type': 'Refractor',
            'aperture_mm': 100,
            'focal_length_mm': 500,
            'reducer_barlow_factor': 1.0,
        })
        result = equipment_profiles.update_telescope(test_user_id, telescope['id'], {
            'name': 'Updated',
            'telescope_type': 'Refractor',
            'aperture_mm': 'not_a_float',
            'focal_length_mm': 500,
        })
        assert result is None

    def test_create_camera_exception_returns_none(self, temp_data_dir, test_user_id):
        result = equipment_profiles.create_camera(test_user_id, {
            'name': 'Bad Cam',
            'manufacturer': 'Test',
            'sensor_width_mm': 'not_a_float',
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        assert result is None

    def test_get_camera_items_exist_but_id_not_found(self, temp_data_dir, test_user_id):
        equipment_profiles.create_camera(test_user_id, {
            'name': 'Cam',
            'manufacturer': 'Test',
            'sensor_width_mm': 10,
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        result = equipment_profiles.get_camera(test_user_id, 'nonexistent-id')
        assert result is None

    def test_update_camera_id_not_found_with_items(self, temp_data_dir, test_user_id):
        equipment_profiles.create_camera(test_user_id, {
            'name': 'Cam',
            'manufacturer': 'Test',
            'sensor_width_mm': 10,
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        result = equipment_profiles.update_camera(test_user_id, 'nonexistent-id', {
            'name': 'Updated',
            'manufacturer': 'Test',
            'sensor_width_mm': 10,
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        assert result is None

    def test_update_camera_exception_returns_none(self, temp_data_dir, test_user_id):
        camera = equipment_profiles.create_camera(test_user_id, {
            'name': 'Cam',
            'manufacturer': 'Test',
            'sensor_width_mm': 10,
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        result = equipment_profiles.update_camera(test_user_id, camera['id'], {
            'name': 'Updated',
            'manufacturer': 'Test',
            'sensor_width_mm': 'not_a_float',
            'sensor_height_mm': 10,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 5.0,
            'sensor_type': 'CMOS',
        })
        assert result is None

    def test_create_mount_exception_returns_none(self, temp_data_dir, test_user_id):
        result = equipment_profiles.create_mount(test_user_id, {
            'name': 'Bad Mount',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 'not_a_float',
        })
        assert result is None

    def test_get_mount_items_exist_but_id_not_found(self, temp_data_dir, test_user_id):
        equipment_profiles.create_mount(test_user_id, {
            'name': 'Mount',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 10,
        })
        result = equipment_profiles.get_mount(test_user_id, 'nonexistent-id')
        assert result is None

    def test_update_mount_id_not_found_with_items(self, temp_data_dir, test_user_id):
        equipment_profiles.create_mount(test_user_id, {
            'name': 'Mount',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 10,
        })
        result = equipment_profiles.update_mount(test_user_id, 'nonexistent-id', {
            'name': 'Updated',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 12,
        })
        assert result is None

    def test_update_mount_exception_returns_none(self, temp_data_dir, test_user_id):
        mount = equipment_profiles.create_mount(test_user_id, {
            'name': 'Mount',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 10,
        })
        result = equipment_profiles.update_mount(test_user_id, mount['id'], {
            'name': 'Updated',
            'mount_type': 'Equatorial',
            'payload_capacity_kg': 'not_a_float',
        })
        assert result is None


# ============================================================
# Additional coverage: save-returns-False paths, get success,
# exception handlers, and combination edge cases
# ============================================================


class TestEquipmentSaveFailurePaths:
    """Cover return-None when save returns False for each CRUD."""

    def test_create_telescope_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_telescopes returns False → create returns None."""
        monkeypatch.setattr(equipment_profiles, 'save_user_telescopes', lambda *_: False)
        result = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        assert result is None

    def test_update_telescope_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_telescope save fails → returns None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_telescopes', lambda *_: False)
        result = equipment_profiles.update_telescope(test_user_id, scope['id'], {
            'name': 'Updated', 'telescope_type': 'Refractor', 'aperture_mm': 102, 'focal_length_mm': 1000
        })
        assert result is None

    def test_create_camera_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_cameras returns False → create returns None."""
        monkeypatch.setattr(equipment_profiles, 'save_user_cameras', lambda *_: False)
        result = equipment_profiles.create_camera(test_user_id, {
            'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS',
        })
        assert result is None

    def test_update_camera_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_camera save fails → returns None."""
        cam = equipment_profiles.create_camera(test_user_id, {
            'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS',
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_cameras', lambda *_: False)
        result = equipment_profiles.update_camera(test_user_id, cam['id'], {
            'name': 'C2', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS',
        })
        assert result is None

    def test_create_mount_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_mounts returns False → create returns None."""
        monkeypatch.setattr(equipment_profiles, 'save_user_mounts', lambda *_: False)
        result = equipment_profiles.create_mount(test_user_id, {
            'name': 'M', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10
        })
        assert result is None

    def test_update_mount_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_mount save fails → returns None."""
        mount = equipment_profiles.create_mount(test_user_id, {
            'name': 'M', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_mounts', lambda *_: False)
        result = equipment_profiles.update_mount(test_user_id, mount['id'], {
            'name': 'M2', 'mount_type': 'Equatorial', 'payload_capacity_kg': 12
        })
        assert result is None

    def test_create_filter_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_filters returns False → create returns None."""
        monkeypatch.setattr(equipment_profiles, 'save_user_filters', lambda *_: False)
        result = equipment_profiles.create_filter(test_user_id, {
            'name': 'H-alpha', 'filter_type': 'Narrowband'
        })
        assert result is None

    def test_update_filter_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_filter save fails → returns None."""
        f = equipment_profiles.create_filter(test_user_id, {'name': 'F', 'filter_type': 'Narrowband'})
        monkeypatch.setattr(equipment_profiles, 'save_user_filters', lambda *_: False)
        result = equipment_profiles.update_filter(test_user_id, f['id'], {
            'name': 'F2', 'filter_type': 'Narrowband'
        })
        assert result is None

    def test_create_accessory_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_accessories returns False → create returns None."""
        monkeypatch.setattr(equipment_profiles, 'save_user_accessories', lambda *_: False)
        result = equipment_profiles.create_accessory(test_user_id, {'name': 'Barlow', 'weight_kg': '1.5'})
        assert result is None

    def test_update_accessory_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_accessory save fails → returns None."""
        a = equipment_profiles.create_accessory(test_user_id, {'name': 'A', 'weight_kg': '0.5'})
        monkeypatch.setattr(equipment_profiles, 'save_user_accessories', lambda *_: False)
        result = equipment_profiles.update_accessory(test_user_id, a['id'], {'name': 'B'})
        assert result is None

    def test_create_combination_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """save_user_combinations returns False → create returns None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_combinations', lambda *_: False)
        result = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': scope['id']
        })
        assert result is None

    def test_update_combination_save_fails_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """update_combination save fails → returns None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Combo', 'telescope_id': scope['id']
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_combinations', lambda *_: False)
        result = equipment_profiles.update_combination(test_user_id, combo['id'], {
            'name': 'Updated', 'telescope_id': scope['id']
        })
        assert result is None


class TestEquipmentDeleteExceptions:
    """Cover exception handlers in delete operations."""

    def test_delete_telescope_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_telescopes → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_telescopes',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_telescope(test_user_id, 'x') == (False, None)

    def test_delete_camera_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_cameras → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_cameras',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_camera(test_user_id, 'x') == (False, None)

    def test_delete_mount_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_mounts → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_mounts',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_mount(test_user_id, 'x') == (False, None)

    def test_delete_filter_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_filters → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_filters',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_filter(test_user_id, 'x') == (False, None)

    def test_delete_accessory_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_accessories → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_accessories',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_accessory(test_user_id, 'x') == (False, None)

    def test_delete_combination_load_exception_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """exception in load_user_combinations → (False, None)."""
        monkeypatch.setattr(equipment_profiles, 'load_user_combinations',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        assert equipment_profiles.delete_combination(test_user_id, 'x') == (False, None)


class TestEquipmentGetSuccessPaths:
    """Cover the success (item found) paths for get_X functions."""

    def test_get_filter_found(self, temp_data_dir, test_user_id):
        """get_filter returns item when found."""
        f = equipment_profiles.create_filter(test_user_id, {'name': 'H-alpha', 'filter_type': 'Narrowband'})
        result = equipment_profiles.get_filter(test_user_id, f['id'])
        assert result is not None and result['id'] == f['id']

    def test_get_accessory_found(self, temp_data_dir, test_user_id):
        """get_accessory returns item when found."""
        a = equipment_profiles.create_accessory(test_user_id, {'name': 'Barlow', 'weight_kg': '0.5'})
        result = equipment_profiles.get_accessory(test_user_id, a['id'])
        assert result is not None and result['id'] == a['id']

    def test_get_combination_found(self, temp_data_dir, test_user_id):
        """->item found: get_combination returns item."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id']
        })
        result = equipment_profiles.get_combination(test_user_id, combo['id'])
        assert result is not None and result['id'] == combo['id']

    def test_update_combination_no_telescope_no_camera_returns_none(self, temp_data_dir, test_user_id):
        """update combination without telescope or camera → None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id']
        })
        # Remove telescope_id and camera_id to trigger validation error
        result = equipment_profiles.update_combination(test_user_id, combo['id'], {
            'name': 'Bad', 'telescope_id': None, 'camera_id': None
        })
        assert result is None

    def test_get_mount_found(self, temp_data_dir, test_user_id):
        """get_mount returns item when found."""
        mount = equipment_profiles.create_mount(test_user_id, {
            'name': 'M', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10
        })
        result = equipment_profiles.get_mount(test_user_id, mount['id'])
        assert result is not None and result['id'] == mount['id']

    def test_get_filter_not_found_returns_none(self, temp_data_dir, test_user_id):
        """get_filter iterates but item not found → None."""
        equipment_profiles.create_filter(test_user_id, {'name': 'F', 'filter_type': 'Narrowband'})
        result = equipment_profiles.get_filter(test_user_id, 'nonexistent-filter-id')
        assert result is None

    def test_get_accessory_not_found_returns_none(self, temp_data_dir, test_user_id):
        """get_accessory iterates but item not found → None."""
        equipment_profiles.create_accessory(test_user_id, {'name': 'A'})
        result = equipment_profiles.get_accessory(test_user_id, 'nonexistent-accessory-id')
        assert result is None

    def test_get_combination_not_found_with_items(self, temp_data_dir, test_user_id):
        """get_combination iterates but item not found → None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        equipment_profiles.create_combination(test_user_id, {'name': 'C', 'telescope_id': scope['id']})
        result = equipment_profiles.get_combination(test_user_id, 'nonexistent-combo-id')
        assert result is None


class TestEquipmentExceptionHandlers:
    """Cover exception handlers triggered by invalid data in create/update."""

    def test_create_filter_exception_returns_none(self, temp_data_dir, test_user_id):
        """missing required filter_type → KeyError → exception handler."""
        result = equipment_profiles.create_filter(test_user_id, {'name': 'F'})  # missing filter_type
        assert result is None

    def test_create_accessory_exception_returns_none(self, temp_data_dir, test_user_id):
        """missing required name → KeyError → exception handler."""
        result = equipment_profiles.create_accessory(test_user_id, {})  # missing name
        assert result is None

    def test_update_filter_exception_returns_none(self, temp_data_dir, test_user_id):
        """missing required name → KeyError in update → exception handler."""
        f = equipment_profiles.create_filter(test_user_id, {'name': 'F', 'filter_type': 'Narrowband'})
        result = equipment_profiles.update_filter(test_user_id, f['id'], {})  # missing name
        assert result is None

    def test_update_accessory_exception_returns_none(self, temp_data_dir, test_user_id):
        """missing required name → KeyError in update → exception handler."""
        a = equipment_profiles.create_accessory(test_user_id, {'name': 'A'})
        result = equipment_profiles.update_accessory(test_user_id, a['id'], {})  # missing name
        assert result is None

    def test_create_combination_exception_returns_none(self, temp_data_dir, test_user_id):
        """telescope_id provided (passes validation) but name missing → KeyError."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        result = equipment_profiles.create_combination(test_user_id, {
            'telescope_id': scope['id'],  # passes validation; no 'name' → KeyError
        })
        assert result is None

    def test_update_combination_exception_returns_none(self, temp_data_dir, test_user_id):
        """telescope_id provided, item found, name missing → KeyError."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id']
        })
        result = equipment_profiles.update_combination(test_user_id, combo['id'], {
            'telescope_id': scope['id'],  # passes validation; no 'name' → KeyError
        })
        assert result is None

    def test_update_filter_not_found_returns_none(self, temp_data_dir, test_user_id):
        """update_filter iterates but ID not found → return None."""
        equipment_profiles.create_filter(test_user_id, {'name': 'F', 'filter_type': 'Narrowband'})
        result = equipment_profiles.update_filter(test_user_id, 'nonexistent-id', {
            'name': 'X', 'filter_type': 'LP'
        })
        assert result is None

    def test_update_accessory_not_found_returns_none(self, temp_data_dir, test_user_id):
        """update_accessory iterates but ID not found → return None."""
        equipment_profiles.create_accessory(test_user_id, {'name': 'A'})
        result = equipment_profiles.update_accessory(test_user_id, 'nonexistent-id', {'name': 'X'})
        assert result is None

    def test_update_combination_not_found_returns_none(self, temp_data_dir, test_user_id):
        """update_combination iterates but ID not found → return None."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        equipment_profiles.create_combination(test_user_id, {'name': 'C', 'telescope_id': scope['id']})
        result = equipment_profiles.update_combination(test_user_id, 'nonexistent-id', {
            'name': 'X', 'telescope_id': scope['id']
        })
        assert result is None

    def test_delete_telescope_save_fails_returns_false(self, temp_data_dir, test_user_id, monkeypatch):
        """save returns False → (False, None)."""
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000
        })
        monkeypatch.setattr(equipment_profiles, 'save_user_telescopes', lambda *_: False)
        result = equipment_profiles.delete_telescope(test_user_id, scope['id'])
        assert result == (False, None)

    def test_update_camera_with_weight_covers_float_return(self, temp_data_dir, test_user_id):
        """get_float_or_none returns float(value) when value is non-empty string."""
        cam = equipment_profiles.create_camera(test_user_id, {
            'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS',
        })
        result = equipment_profiles.update_camera(test_user_id, cam['id'], {
            'name': 'C', 'manufacturer': 'M', 'sensor_width_mm': 10, 'sensor_height_mm': 8,
            'resolution_width_px': 3000, 'resolution_height_px': 2000, 'pixel_size_um': 3.8,
            'sensor_type': 'CMOS', 'weight_kg': '2.5',  # non-empty → covers float(value) path
        })
        assert result is not None and result['weight_kg'] == 2.5


class TestAnalyzeCombination:
    """Cover the analyze_combination function branches."""

    def _make_telescope(self, user_id, focal_length=800, weight_kg=None):
        data = {
            'name': 'Scope', 'telescope_type': 'Refractor',
            'aperture_mm': 100, 'focal_length_mm': focal_length,
        }
        if weight_kg is not None:
            data['weight_kg'] = weight_kg
        return equipment_profiles.create_telescope(user_id, data)

    def _make_camera(self, user_id, pixel_size_um=3.0, sensor_w=10, sensor_h=7,
                     weight_kg=None, include_pixel=True):
        data = {
            'name': 'Cam', 'manufacturer': 'M',
            'sensor_width_mm': sensor_w, 'sensor_height_mm': sensor_h,
            'resolution_width_px': 3000, 'resolution_height_px': 2000,
            'sensor_type': 'CMOS',
        }
        if include_pixel:
            data['pixel_size_um'] = pixel_size_um
        if weight_kg is not None:
            data['weight_kg'] = weight_kg
        return equipment_profiles.create_camera(user_id, data)

    def _make_mount(self, user_id, recommended_payload=20):
        return equipment_profiles.create_mount(user_id, {
            'name': 'Mount', 'mount_type': 'Equatorial',
            'payload_capacity_kg': recommended_payload,
            'recommended_payload_kg': recommended_payload,
        })

    def test_analyze_with_filters_and_accessories(self, temp_data_dir, test_user_id):
        """combination with filter_ids and accessory_ids."""
        scope = self._make_telescope(test_user_id)
        cam = self._make_camera(test_user_id)
        f = equipment_profiles.create_filter(test_user_id, {'name': 'F', 'filter_type': 'LP'})
        a = equipment_profiles.create_accessory(test_user_id, {'name': 'Barlow'})
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Full Setup',
            'telescope_id': scope['id'],
            'camera_id': cam['id'],
            'filter_ids': [f['id']],
            'accessory_ids': [a['id']],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert len(result.filters) == 1
        assert len(result.accessories) == 1

    def test_analyze_optimal_sampling_medium_fov(self, temp_data_dir, test_user_id):
        """OPTIMAL classification + medium FOV → no recommendations."""
        # pixel_scale = 206.265 * 3.0 / 800 = 0.774 arcsec/px → OPTIMAL (0.667–1.0)
        # FOV diagonal = 57.3 * sqrt(10²+7²) / 800 = 0.874° → between 0.5 and 2.0
        scope = self._make_telescope(test_user_id, focal_length=800)
        cam = self._make_camera(test_user_id, pixel_size_um=3.0, sensor_w=10, sensor_h=7)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Optimal Setup', 'telescope_id': scope['id'], 'camera_id': cam['id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert any("Balanced setup" in s for s in result.suitability)
        assert any("No critical issues" in r for r in result.recommendations)

    def test_analyze_oversampled_compact_fov(self, temp_data_dir, test_user_id):
        """OVERSAMPLED + compact FOV ≤ 0.5°."""
        # pixel_scale = 206.265 * 3.0 / 2000 = 0.309 arcsec/px → OVERSAMPLED (<0.667)
        # FOV diagonal = 57.3 * sqrt(3²+2²) / 2000 = 0.103° → ≤ 0.5°
        scope = self._make_telescope(test_user_id, focal_length=2000)
        cam = self._make_camera(test_user_id, pixel_size_um=3.0, sensor_w=3, sensor_h=2)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Oversampled', 'telescope_id': scope['id'], 'camera_id': cam['id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert any("high-resolution" in s for s in result.suitability)
        assert any("compact targets" in s for s in result.suitability)

    def test_analyze_missing_pixel_size_skips_fov(self, temp_data_dir, test_user_id, monkeypatch):
        """telescope + camera but camera has no pixel_size_um → else branch."""
        scope = self._make_telescope(test_user_id, focal_length=800)
        cam = self._make_camera(test_user_id, pixel_size_um=3.0)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'No Pixel', 'telescope_id': scope['id'], 'camera_id': cam['id'],
        })
        # Return camera dict without pixel_size_um to trigger the else branch (1426-1427)
        cam_no_pixel = {k: v for k, v in cam.items() if k != 'pixel_size_um'}
        monkeypatch.setattr(equipment_profiles, 'get_camera', lambda *_: cam_no_pixel)
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert any("Complete telescope" in r for r in result.recommendations)

    def test_analyze_mount_payload_within_limits(self, temp_data_dir, test_user_id):
        """mount + telescope, payload within recommended limits."""
        # telescope weight=3, mount recommended=20 → 3≤20 → "within limits"
        scope = self._make_telescope(test_user_id, focal_length=800, weight_kg=3.0)
        mount = self._make_mount(test_user_id, recommended_payload=20)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Mount Setup', 'telescope_id': scope['id'], 'mount_id': mount['id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert any("within recommended mount limits" in s for s in result.suitability)

    def test_analyze_mount_payload_exceeds_limits(self, temp_data_dir, test_user_id):
        """mount + telescope, payload exceeds recommended limits."""
        # telescope weight=15, mount recommended=5 → 15>5 → "too high"
        scope = self._make_telescope(test_user_id, focal_length=800, weight_kg=15.0)
        mount = self._make_mount(test_user_id, recommended_payload=5)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'Heavy Setup', 'telescope_id': scope['id'], 'mount_id': mount['id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert any("too high" in r for r in result.recommendations)

    def test_analyze_exception_returns_none(self, temp_data_dir, test_user_id, monkeypatch):
        """exception inside try → exception handler → None."""
        scope = self._make_telescope(test_user_id)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id'],
        })
        monkeypatch.setattr(equipment_profiles, 'get_telescope',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk error")))
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is None

    def test_analyze_filter_not_found_skips_append(self, temp_data_dir, test_user_id):
        """filter_id in combination but filter not found → skip append."""
        scope = self._make_telescope(test_user_id)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id'],
            'filter_ids': ['nonexistent-filter-id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert result.filters == []

    def test_analyze_accessory_not_found_skips_append(self, temp_data_dir, test_user_id):
        """accessory_id in combination but accessory not found → skip append."""
        scope = self._make_telescope(test_user_id)
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id'],
            'accessory_ids': ['nonexistent-accessory-id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        assert result.accessories == []

    def test_analyze_mount_zero_payload_skips_comparison(self, temp_data_dir, test_user_id):
        """mount present but both payload values are 0 → skip comparison."""
        # telescope with no weight (defaults to 0), mount with no recommended payload
        scope = equipment_profiles.create_telescope(test_user_id, {
            'name': 'T', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 800,
        })
        mount = equipment_profiles.create_mount(test_user_id, {
            'name': 'M', 'mount_type': 'Equatorial', 'payload_capacity_kg': 10,
            # recommended_payload_kg intentionally omitted → defaults to 0/None
        })
        combo = equipment_profiles.create_combination(test_user_id, {
            'name': 'C', 'telescope_id': scope['id'], 'mount_id': mount['id'],
        })
        result = equipment_profiles.analyze_combination(test_user_id, combo['id'])
        assert result is not None
        # No payload comparison made, so no mount-related suitability message
        assert not any("within recommended" in s for s in result.suitability)


class TestSafeSaveRecoveryBranches:
    """error-recovery paths in safe_save_equipment."""

    def test_no_backup_exists_on_move_failure_skips_restore(self, tmp_path, monkeypatch):
        """new file, no backup, shutil.move fails → if backup: False → skip to 372."""
        new_file = str(tmp_path / 'new_equip.json')
        monkeypatch.setattr(equipment_profiles.shutil, 'move',
                            lambda *a: (_ for _ in ()).throw(IOError("disk full")))
        ok = equipment_profiles.safe_save_equipment(new_file, {'items': []})
        assert ok is False

    def test_restore_copy2_fails_logs_error(self, tmp_path, monkeypatch):
        """existing file, backup created, move fails, restore copy2 also fails."""
        target = tmp_path / 'equip.json'
        target.write_text(json.dumps({'items': []}), encoding='utf-8')
        copy2_calls = [0]
        real_copy2 = equipment_profiles.shutil.copy2
        def _copy2(src, dst):
            copy2_calls[0] += 1
            if copy2_calls[0] >= 2:
                raise IOError("restore failed")
            return real_copy2(src, dst)  # first call (backup) actually copies
        monkeypatch.setattr(equipment_profiles.shutil, 'copy2', _copy2)
        monkeypatch.setattr(equipment_profiles.shutil, 'move',
                            lambda *a: (_ for _ in ()).throw(IOError("disk full")))
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})
        assert ok is False

    def test_no_temp_file_on_open_failure(self, tmp_path, monkeypatch):
        """exception before temp created (step 2 fails) → temp doesn't exist."""
        import builtins
        target = tmp_path / 'equip.json'
        target.write_text(json.dumps({'items': []}), encoding='utf-8')
        real_open = builtins.open
        def _fail_temp(path, *args, **kwargs):
            if str(path).endswith('.tmp'):
                raise IOError("disk full")
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr(builtins, 'open', _fail_temp)
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})
        assert ok is False

    def test_temp_remove_fails_is_swallowed(self, tmp_path, monkeypatch):
        """temp cleanup raises → swallowed → still returns False."""
        target = tmp_path / 'equip.json'
        target.write_text(json.dumps({'items': []}), encoding='utf-8')
        monkeypatch.setattr(equipment_profiles.shutil, 'move',
                            lambda *a: (_ for _ in ()).throw(IOError("disk full")))
        real_remove = equipment_profiles.os.remove
        def _fail_remove(path):
            if str(path).endswith('.tmp'):
                raise OSError("cannot remove")
            return real_remove(path)
        monkeypatch.setattr(equipment_profiles.os, 'remove', _fail_remove)
        ok = equipment_profiles.safe_save_equipment(str(target), {'items': []})
        assert ok is False


class TestSharedEquipmentAdditionalBranches:
    """."""

    def test_load_shared_equipment_item_not_shared_skipped(self, temp_data_dir, monkeypatch):
        """item in file has is_shared=False → not added to result."""
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': 'owner1', 'username': 'alice'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        tel_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, 'owner1_telescopes.json')
        with open(tel_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 't1', 'name': 'Scope', 'is_shared': False}]}, f)
        result = equipment_profiles.load_all_shared_equipment('telescopes', exclude_user_id='other')
        assert result == []

    def test_compute_share_status_item_in_shared_by_id(self, temp_data_dir, monkeypatch):
        """equipment item referenced from shared_by_id (other user's shared pool)."""
        owner_id = 'sharer'
        viewer_id = 'viewer'
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [
                    {'user_id': owner_id, 'username': 'alice'},
                    {'user_id': viewer_id, 'username': 'bob'},
                ]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        tel_file = equipment_profiles.get_user_equipment_file(owner_id, 'telescopes')
        with open(tel_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 't1', 'name': 'SharedScope', 'is_shared': True}]}, f)
        # viewer references owner's shared telescope: t1 is in shared_by_id, not own_by_id
        status = equipment_profiles.compute_combination_share_status(
            {'telescope_id': 't1', 'camera_id': None, 'mount_id': None,
             'filter_ids': [], 'accessory_ids': []},
            viewer_id,  # viewer doesn't own t1
        )
        assert status['is_shared'] is True
        assert 't1' in status['items_share_info']

    def test_load_shared_combinations_excludes_owner(self, temp_data_dir, monkeypatch):
        """combo file belongs to excluded user → skipped."""
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': 'excludeme', 'username': 'excluded'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        combo_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, 'excludeme_combinations.json')
        with open(combo_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 'c1', 'telescope_id': None, 'camera_id': None,
                                   'mount_id': None, 'filter_ids': [], 'accessory_ids': [],
                                   'is_shared': True}]}, f)
        result = equipment_profiles.load_all_shared_combinations(exclude_user_id='excludeme')
        assert result == []

    def test_load_shared_combinations_invalid_json_continues(self, temp_data_dir, monkeypatch):
        """bad JSON in combo file → exception caught → continue."""
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': 'owner1', 'username': 'alice'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        combo_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, 'owner1_combinations.json')
        with open(combo_file, 'w', encoding='utf-8') as f:
            f.write('{invalid json}')
        result = equipment_profiles.load_all_shared_combinations(exclude_user_id='other')
        assert result == []

    def test_load_shared_combinations_not_shared_excluded(self, temp_data_dir, monkeypatch):
        """combination status is_shared=False → not added."""
        owner_id = 'owner1'
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [{'user_id': owner_id, 'username': 'alice'}]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()
        combo_file = os.path.join(equipment_profiles.EQUIPMENT_DIR, f'{owner_id}_combinations.json')
        with open(combo_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 'c1', 'telescope_id': 'missing',
                                   'camera_id': None, 'mount_id': None,
                                   'filter_ids': [], 'accessory_ids': []}]}, f)
        result = equipment_profiles.load_all_shared_combinations(exclude_user_id='other')
        assert result == []

    def test_load_shared_combinations_outer_exception_returns_empty(self, temp_data_dir, monkeypatch):
        """os.listdir raises → outer except → return []."""
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: []
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        monkeypatch.setattr(equipment_profiles.os, 'listdir',
                            lambda _: (_ for _ in ()).throw(Exception("listdir fail")))
        result = equipment_profiles.load_all_shared_combinations(exclude_user_id='other')
        assert result == []


class TestIndexTelescopesAndCameras:
    """index_telescopes_and_cameras merges each user's own + shared telescopes/cameras."""

    def test_merges_own_and_shared_telescopes_and_cameras(self, temp_data_dir, monkeypatch):
        owner_id = 'scope-owner'
        viewer_id = 'viewer'
        fake_auth = types.SimpleNamespace(
            user_manager=types.SimpleNamespace(
                list_users=lambda: [
                    {'user_id': owner_id, 'username': 'alice'},
                    {'user_id': viewer_id, 'username': 'bob'},
                ]
            )
        )
        monkeypatch.setitem(sys.modules, 'utils.auth', fake_auth)
        equipment_profiles.ensure_equipment_directories()

        # Another user's shared telescope and camera
        tel_file = equipment_profiles.get_user_equipment_file(owner_id, 'telescopes')
        with open(tel_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 'shared-scope', 'name': 'Shared Scope', 'is_shared': True}]}, f)
        cam_file = equipment_profiles.get_user_equipment_file(owner_id, 'cameras')
        with open(cam_file, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 'shared-cam', 'name': 'Shared Cam', 'is_shared': True}]}, f)

        # Viewer's own telescope and camera
        own_scope = equipment_profiles.create_telescope(
            viewer_id,
            {'name': 'Own Scope', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 800},
        )
        own_camera = equipment_profiles.create_camera(
            viewer_id,
            {
                'name': 'Own Cam', 'manufacturer': 'ZWO', 'sensor_type': 'CMOS',
                'sensor_width_mm': 19.1, 'sensor_height_mm': 13.0,
                'resolution_width_px': 4144, 'resolution_height_px': 2822, 'pixel_size_um': 4.63,
            },
        )

        telescopes_by_id, cameras_by_id = equipment_profiles.index_telescopes_and_cameras(viewer_id)

        assert own_scope['id'] in telescopes_by_id
        assert 'shared-scope' in telescopes_by_id
        assert own_camera['id'] in cameras_by_id
        assert 'shared-cam' in cameras_by_id
