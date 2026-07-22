"""
Tests for Shared Equipment feature
"""
import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock

from equipment import equipment_profiles


USER_A = "user-a-uuid"
USER_B = "user-b-uuid"

USER_LIST = [
    {'user_id': USER_A, 'username': 'alice'},
    {'user_id': USER_B, 'username': 'bob'},
]


@pytest.fixture
def temp_data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        equipment_profiles.EQUIPMENT_DIR = os.path.join(tmpdir, 'equipments')
        yield tmpdir


def _mock_user_manager():
    mgr = MagicMock()
    mgr.list_users.return_value = USER_LIST
    return mgr


def _create_telescope(user_id, name, is_shared=False):
    data = {
        'name': name,
        'manufacturer': 'TestCo',
        'telescope_type': 'Refractor',
        'aperture_mm': 100,
        'focal_length_mm': 500,
        'is_shared': is_shared,
    }
    return equipment_profiles.create_telescope(user_id, data)


# ============================================================
# is_shared defaults and persistence
# ============================================================

def test_is_shared_defaults_false(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope A')
    assert scope is not None
    assert scope.get('is_shared') is False


def test_set_shared_true(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope A')
    updated = equipment_profiles.update_telescope(USER_A, scope['id'], {
        **scope,
        'is_shared': True,
    })
    assert updated is not None
    assert updated['is_shared'] is True


def test_shared_flag_persisted(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope A', is_shared=True)
    loaded = equipment_profiles.get_telescope(USER_A, scope['id'])
    assert loaded['is_shared'] is True


# ============================================================
# load_all_shared_equipment
# ============================================================

def test_load_shared_from_other_users(temp_data_dir):
    _create_telescope(USER_A, 'Scope A', is_shared=True)
    _create_telescope(USER_B, 'Scope B not shared', is_shared=False)
    _create_telescope(USER_B, 'Scope B shared', is_shared=True)

    with patch('utils.auth.user_manager', _mock_user_manager()):
        shared = equipment_profiles.load_all_shared_equipment('telescopes', USER_A)

    names = [s['name'] for s in shared]
    assert 'Scope B shared' in names
    assert 'Scope B not shared' not in names
    assert 'Scope A' not in names  # own user excluded


def test_non_shared_item_not_visible_to_others(temp_data_dir):
    _create_telescope(USER_B, 'Private Scope', is_shared=False)

    with patch('utils.auth.user_manager', _mock_user_manager()):
        shared = equipment_profiles.load_all_shared_equipment('telescopes', USER_A)

    assert shared == []


def test_shared_item_annotated_with_owner(temp_data_dir):
    _create_telescope(USER_B, 'Bob Scope', is_shared=True)

    with patch('utils.auth.user_manager', _mock_user_manager()):
        shared = equipment_profiles.load_all_shared_equipment('telescopes', USER_A)

    assert len(shared) == 1
    item = shared[0]
    assert item['owner_id'] == USER_B
    assert item['owner_username'] == 'bob'


# ============================================================
# compute_combination_share_status
# ============================================================

def _create_filter(user_id, name, is_shared=False):
    data = {
        'name': name,
        'filter_type': 'LRGB',
        'is_shared': is_shared,
    }
    return equipment_profiles.create_filter(user_id, data)


def test_combination_is_shared_all_own_true(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope', is_shared=True)
    filt = _create_filter(USER_A, 'H-Alpha', is_shared=True)

    combo = {
        'telescope_id': scope['id'],
        'camera_id': None,
        'mount_id': None,
        'filter_ids': [filt['id']],
        'accessory_ids': [],
    }

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_share_status(combo, USER_A)

    assert status['is_shared'] is True
    assert status['has_broken_share'] is False
    assert status['broken_items'] == []


def test_combination_not_shared_when_one_not_shared(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope', is_shared=True)
    filt = _create_filter(USER_A, 'H-Alpha', is_shared=False)

    combo = {
        'telescope_id': scope['id'],
        'camera_id': None,
        'mount_id': None,
        'filter_ids': [filt['id']],
        'accessory_ids': [],
    }

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_share_status(combo, USER_A)

    assert status['is_shared'] is False
    assert status['has_broken_share'] is False


def test_combination_broken_share_when_item_gone(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope', is_shared=True)
    ghost_id = 'nonexistent-filter-id'

    combo = {
        'telescope_id': scope['id'],
        'camera_id': None,
        'mount_id': None,
        'filter_ids': [ghost_id],
        'accessory_ids': [],
    }

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_share_status(combo, USER_A)

    assert status['is_shared'] is False
    assert status['has_broken_share'] is True
    assert ghost_id in status['broken_items']


def test_combination_using_shared_equipment_from_other_user(temp_data_dir):
    scope_b = _create_telescope(USER_B, 'Bob Scope', is_shared=True)

    combo = {
        'telescope_id': scope_b['id'],
        'camera_id': None,
        'mount_id': None,
        'filter_ids': [],
        'accessory_ids': [],
    }

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_share_status(combo, USER_A)

    assert status['is_shared'] is True
    assert status['has_broken_share'] is False


# ============================================================
# Cross-user scenario
# ============================================================

def test_shared_is_shared_field_for_filters(temp_data_dir):
    filt = _create_filter(USER_A, 'OIII', is_shared=True)
    assert filt is not None
    assert filt['is_shared'] is True


def test_update_shared_to_false(temp_data_dir):
    scope = _create_telescope(USER_A, 'Scope', is_shared=True)
    updated = equipment_profiles.update_telescope(USER_A, scope['id'], {**scope, 'is_shared': False})
    assert updated['is_shared'] is False


# ============================================================
# Cross-user delete-guard and validity status (feature.md rules)
# ============================================================

def test_shared_telescope_delete_blocked_by_other_users_combination(temp_data_dir):
    """USER_B's shared telescope, referenced by USER_A's own combination, can't be deleted by USER_B."""
    scope_b = _create_telescope(USER_B, 'Bob Scope', is_shared=True)
    equipment_profiles.create_combination(USER_A, {
        'name': "Alice's Combo", 'telescope_id': scope_b['id'],
    })

    success, blocked_by = equipment_profiles.delete_telescope(USER_B, scope_b['id'])
    assert success is False
    assert blocked_by == ["Alice's Combo"]


def test_validity_status_from_owner_perspective_when_shared_item_disabled(temp_data_dir):
    """USER_A's combination references USER_B's shared telescope; disabling it (by USER_B) makes
    USER_A's combination invalid when computed from USER_A's perspective."""
    scope_b = _create_telescope(USER_B, 'Bob Scope', is_shared=True)
    combo = equipment_profiles.create_combination(USER_A, {
        'name': "Alice's Combo", 'telescope_id': scope_b['id'],
    })

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_validity_status(combo, USER_A)
    assert status['is_valid'] is True

    equipment_profiles.update_telescope(USER_B, scope_b['id'], {**scope_b, 'is_disabled': True})

    with patch('utils.auth.user_manager', _mock_user_manager()):
        status = equipment_profiles.compute_combination_validity_status(combo, USER_A)
    assert status['is_valid'] is False
    assert scope_b['id'] in status['disabled_component_ids']


def test_load_all_shared_combinations_attaches_validity_status(temp_data_dir):
    """load_all_shared_combinations includes is_valid alongside is_shared for each entry."""
    scope_b = _create_telescope(USER_B, 'Bob Scope', is_shared=True)
    equipment_profiles.create_combination(USER_B, {
        'name': 'Shared Combo', 'telescope_id': scope_b['id'],
    })

    with patch('utils.auth.user_manager', _mock_user_manager()):
        shared = equipment_profiles.load_all_shared_combinations(exclude_user_id=USER_A)

    assert len(shared) == 1
    assert shared[0]['name'] == 'Shared Combo'
    assert shared[0]['is_valid'] is True
    assert shared[0]['owner_username'] == 'bob'
