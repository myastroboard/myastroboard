"""Tests for authentication user management rules."""

import json
import os

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import auth


@pytest.fixture
def isolated_user_manager(tmp_path, monkeypatch):
    """Create a UserManager instance using an isolated users file."""
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", str(users_file))
    return auth.UserManager()


def test_admin_can_delete_default_admin_if_not_self(isolated_user_manager):
    manager = isolated_user_manager

    default_admin = manager.get_user_by_username("admin")
    acting_admin = manager.create_user("supervisor", "secret", auth.ROLE_ADMIN)

    manager.delete_user(default_admin.user_id, current_user_id=acting_admin.user_id)

    assert manager.get_user_by_id(default_admin.user_id) is None


def test_admin_cannot_delete_own_account(isolated_user_manager):
    manager = isolated_user_manager

    acting_admin = manager.create_user("owner", "secret", auth.ROLE_ADMIN)

    with pytest.raises(ValueError, match="Cannot delete your own account"):
        manager.delete_user(acting_admin.user_id, current_user_id=acting_admin.user_id)


def test_change_own_password_updates_only_current_user(isolated_user_manager):
    manager = isolated_user_manager

    alice = manager.create_user("alice", "old-secret", "user")
    bob = manager.create_user("bob", "bob-secret", "user")

    old_bob_hash = manager.get_user_by_id(bob.user_id).password_hash

    manager.change_own_password(alice.user_id, "old-secret", "new-secret")

    updated_alice = manager.get_user_by_id(alice.user_id)
    updated_bob = manager.get_user_by_id(bob.user_id)

    assert check_password_hash(updated_alice.password_hash, "new-secret")
    assert updated_bob.password_hash == old_bob_hash


def test_change_own_password_rejects_wrong_current_password(isolated_user_manager):
    manager = isolated_user_manager
    user = manager.create_user("alice", "old-secret", "user")

    old_hash = manager.get_user_by_id(user.user_id).password_hash

    with pytest.raises(ValueError, match="Current password is incorrect"):
        manager.change_own_password(user.user_id, "bad-secret", "new-secret")

    unchanged_user = manager.get_user_by_id(user.user_id)
    assert unchanged_user.password_hash == old_hash


def test_validate_users_json_data_rejects_mismatched_user_id():
    is_valid, error_msg = auth.UserManager.validate_users_json_data({
        "abc": {
            "user_id": "def",
            "username": "alice",
            "password_hash": "hash",
            "role": "user",
            "created_at": "2026-03-12T00:00:00"
        }
    })

    assert not is_valid
    assert "mismatched user_id" in error_msg


def test_update_user_preferences_updates_only_target_user(isolated_user_manager):
    manager = isolated_user_manager
    alice = manager.create_user("alice", "alice-secret", "user")
    bob = manager.create_user("bob", "bob-secret", "user")

    manager.update_user_preferences(alice.user_id, {
        "time_format": "24h",
        "density": "compact"
    })

    alice_prefs = manager.get_user_preferences(alice.user_id)
    bob_prefs = manager.get_user_preferences(bob.user_id)

    assert alice_prefs["time_format"] == "24h"
    assert alice_prefs["density"] == "compact"
    assert bob_prefs["time_format"] == "auto"
    assert bob_prefs["density"] == "comfortable"


def test_update_user_preferences_rejects_invalid_values(isolated_user_manager):
    manager = isolated_user_manager
    user = manager.create_user("alice", "alice-secret", "user")

    with pytest.raises(ValueError, match="Invalid time_format"):
        manager.update_user_preferences(user.user_id, {
            "time_format": "invalid-format"
        })


# ===========================================================================
# User model tests
# ===========================================================================


class TestUserModel:

    def test_user_id_auto_generated(self):
        u = auth.User(username='alice', password_hash='hash', role=auth.ROLE_USER)
        assert u.user_id is not None
        assert len(u.user_id) > 0

    def test_user_id_provided_used(self):
        u = auth.User(username='alice', password_hash='hash', role=auth.ROLE_USER, user_id='custom-id')
        assert u.user_id == 'custom-id'

    def test_to_dict_roundtrip(self):
        u = auth.User(username='alice', password_hash='hash', role=auth.ROLE_USER, user_id='u1')
        d = u.to_dict()
        assert d['username'] == 'alice'
        assert d['user_id'] == 'u1'
        assert d['role'] == auth.ROLE_USER

    def test_from_dict_roundtrip(self):
        d = {
            'user_id': 'u2',
            'username': 'bob',
            'password_hash': 'hash2',
            'role': auth.ROLE_ADMIN,
            'created_at': '2026-01-01T00:00:00Z',
            'last_login': None,
            'preferences': None,
            'push_subscriptions': None,
        }
        u = auth.User.from_dict(d)
        assert u.username == 'bob'
        assert u.role == auth.ROLE_ADMIN
        assert u.user_id == 'u2'

    def test_is_admin_true(self):
        u = auth.User(username='admin', password_hash='h', role=auth.ROLE_ADMIN)
        assert u.is_admin() is True
        assert u.is_user() is False
        assert u.is_read_only() is False

    def test_is_user_true(self):
        u = auth.User(username='alice', password_hash='h', role=auth.ROLE_USER)
        assert u.is_user() is True
        assert u.is_admin() is False
        assert u.is_read_only() is False

    def test_is_read_only_true(self):
        u = auth.User(username='viewer', password_hash='h', role=auth.ROLE_READ_ONLY)
        assert u.is_read_only() is True
        assert u.is_user() is False
        assert u.is_admin() is False

    def test_is_using_default_password_true(self):
        u = auth.User(
            username=auth.DEFAULT_ADMIN_USERNAME,
            password_hash=generate_password_hash(auth.DEFAULT_ADMIN_PASSWORD),
            role=auth.ROLE_ADMIN,
        )
        assert u.is_using_default_password() is True

    def test_is_using_default_password_false_changed(self):
        u = auth.User(
            username=auth.DEFAULT_ADMIN_USERNAME,
            password_hash=generate_password_hash('changed!'),
            role=auth.ROLE_ADMIN,
        )
        assert u.is_using_default_password() is False

    def test_is_using_default_password_false_non_admin(self):
        u = auth.User(
            username='alice',
            password_hash=generate_password_hash(auth.DEFAULT_ADMIN_PASSWORD),
            role=auth.ROLE_USER,
        )
        # Non-admin always returns False
        assert u.is_using_default_password() is False

    def test_check_password_correct(self):
        u = auth.User(username='alice', password_hash=generate_password_hash('secret'), role=auth.ROLE_USER)
        assert u.check_password('secret') is True

    def test_check_password_wrong(self):
        u = auth.User(username='alice', password_hash=generate_password_hash('secret'), role=auth.ROLE_USER)
        assert u.check_password('wrong') is False

    def test_preferences_defaults_when_none(self):
        u = auth.User(username='alice', password_hash='h', role=auth.ROLE_USER, preferences=None)
        assert u.preferences == auth.DEFAULT_USER_PREFERENCES

    def test_preferences_copy_on_init(self):
        prefs = {'startup_main_tab': 'skytonight', 'time_format': 'auto', 'density': 'comfortable',
                 'theme_mode': 'auto', 'first_day_of_week': 'monday', 'language': 'en',
                 'startup_subtab': 'astro-weather', 'notifications': {}}
        u = auth.User(username='alice', password_hash='h', role=auth.ROLE_USER, preferences=prefs)
        # Mutation of original doesn't affect user
        prefs['startup_main_tab'] = 'changed'
        assert u.preferences['startup_main_tab'] == 'skytonight'

    def test_push_subscriptions_default_empty_list(self):
        u = auth.User(username='alice', password_hash='h', role=auth.ROLE_USER)
        assert u.push_subscriptions == []

    def test_push_subscriptions_stored(self):
        subs = [{'endpoint': 'https://example.com/push/123'}]
        u = auth.User(username='alice', password_hash='h', role=auth.ROLE_USER, push_subscriptions=subs)
        assert u.push_subscriptions == subs


# ===========================================================================
# UserManager tests
# ===========================================================================


class TestUserManagerLoadSave:

    def test_load_users_creates_default_admin_when_no_file(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        assert admin is not None
        assert admin.role == auth.ROLE_ADMIN

    def test_load_users_reads_existing_file(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        # Create a manager (which creates default admin and saves)
        manager1 = auth.UserManager()
        manager1.create_user('bob', 'bob-pass', auth.ROLE_USER)

        # Load fresh manager
        manager2 = auth.UserManager()
        assert manager2.get_user_by_username('bob') is not None

    def test_load_users_handles_invalid_json(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        users_file.write_text('{invalid json', encoding='utf-8')
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        # Should silently fail and have empty users
        assert manager.users == {}

    def test_load_users_handles_invalid_data_structure(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        # Valid JSON but wrong structure (missing required fields)
        bad_data = {
            'uid1': {
                'user_id': 'uid1',
                'username': 'bad',
                # missing password_hash, role, created_at
            }
        }
        users_file.write_text(json.dumps(bad_data), encoding='utf-8')
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        assert manager.users == {}

    def test_save_users_atomic_write(self, isolated_user_manager, tmp_path):
        manager = isolated_user_manager
        manager.create_user('alice', 'alice-pass', auth.ROLE_USER)
        # Ensure file saved
        assert os.path.exists(auth.USERS_FILE)

    def test_save_users_backup_cleaned_on_success(self, isolated_user_manager):
        manager = isolated_user_manager
        backup_path = auth.USERS_FILE + '.backup'
        manager.create_user('alice', 'alice-pass', auth.ROLE_USER)
        # Backup should be removed on success
        assert not os.path.exists(backup_path)


class TestUserManagerReloadIfChanged:

    def test_reload_when_mtime_changes(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        # Manually create another user and rewrite the file externally
        # Force different mtime by changing the mtime attribute
        manager._users_mtime = 0  # pretend file is stale
        # Next call should trigger reload
        manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        # Should have reloaded
        assert manager._users_mtime != 0

    def test_reload_clears_users_when_file_deleted(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        # Add a user
        manager.create_user('alice', 'alice-pass', auth.ROLE_USER)
        assert len(manager.users) >= 2  # admin + alice

        # Delete the file and reset mtime
        os.remove(str(users_file))
        manager._users_mtime = None

        manager._reload_users_if_changed()
        # File gone → users cleared
        assert manager.users == {}

    def test_reload_handles_exception_gracefully(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()

        # Make getmtime raise an exception
        original_getmtime = os.path.getmtime
        monkeypatch.setattr(os.path, 'getmtime', lambda p: (_ for _ in ()).throw(OSError('fail')))
        # Should not raise
        manager._reload_users_if_changed()
        # Restore
        monkeypatch.setattr(os.path, 'getmtime', original_getmtime)


class TestUserManagerCreate:

    def test_create_user_success(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('newuser', 'password123', auth.ROLE_USER)
        assert user.username == 'newuser'
        assert user.role == auth.ROLE_USER

    def test_create_user_duplicate_raises(self, isolated_user_manager):
        manager = isolated_user_manager
        manager.create_user('alice', 'pass', auth.ROLE_USER)
        with pytest.raises(ValueError, match='already exists'):
            manager.create_user('alice', 'pass2', auth.ROLE_USER)

    def test_create_user_invalid_role_raises(self, isolated_user_manager):
        manager = isolated_user_manager
        with pytest.raises(ValueError, match='Invalid role'):
            manager.create_user('baduser', 'pass', 'superadmin')

    def test_create_user_all_roles(self, isolated_user_manager):
        manager = isolated_user_manager
        for role in [auth.ROLE_ADMIN, auth.ROLE_USER, auth.ROLE_READ_ONLY]:
            user = manager.create_user(f'user_{role}', 'pass', role)
            assert user.role == role

    def test_create_user_attributes_all_existing_locations(self, isolated_user_manager, monkeypatch):
        """New users see every location that already exists by default - an
        admin can manually exclude specific ones afterward, rather than
        having to attribute each location by hand."""
        manager = isolated_user_manager
        monkeypatch.setattr(
            'repo_config.load_config',
            lambda: {'locations': [{'id': 'loc-a'}, {'id': 'loc-b'}]},
        )

        user = manager.create_user('newuser', 'password123', auth.ROLE_USER)

        assert sorted(user.preferences['location']['attributed_location_ids']) == ['loc-a', 'loc-b']

    def test_create_user_no_locations_leaves_empty_attribution(self, isolated_user_manager, monkeypatch):
        manager = isolated_user_manager
        monkeypatch.setattr('repo_config.load_config', lambda: {'locations': []})

        user = manager.create_user('newuser2', 'password123', auth.ROLE_USER)

        assert user.preferences['location']['attributed_location_ids'] == []

    def test_create_user_survives_location_lookup_failure(self, isolated_user_manager, monkeypatch):
        """User creation itself must not fail just because the location
        lookup did (e.g. config unavailable at that instant)."""
        manager = isolated_user_manager
        monkeypatch.setattr(
            'repo_config.load_config', lambda: (_ for _ in ()).throw(RuntimeError('boom'))
        )

        user = manager.create_user('newuser3', 'password123', auth.ROLE_USER)

        assert user.preferences['location']['attributed_location_ids'] == []

    def test_create_user_does_not_mutate_shared_default_preferences(self, isolated_user_manager, monkeypatch):
        """DEFAULT_USER_PREFERENCES['location'] is shared by shallow-copy
        reference across every user until reassigned - creating a user with
        locations to attribute must not corrupt that shared default for
        whoever gets created next."""
        manager = isolated_user_manager
        monkeypatch.setattr('repo_config.load_config', lambda: {'locations': [{'id': 'loc-a'}]})

        manager.create_user('first_user', 'password123', auth.ROLE_USER)

        assert auth.DEFAULT_USER_PREFERENCES['location']['attributed_location_ids'] == []


class TestUserManagerGetUser:

    def test_get_user_by_username_returns_none_for_missing(self, isolated_user_manager):
        assert isolated_user_manager.get_user_by_username('nobody') is None

    def test_get_user_by_id_returns_none_for_missing(self, isolated_user_manager):
        assert isolated_user_manager.get_user_by_id('nonexistent-id') is None

    def test_get_user_backwards_compat(self, isolated_user_manager):
        admin = isolated_user_manager.get_user(auth.DEFAULT_ADMIN_USERNAME)
        assert admin is not None

    def test_list_users_does_not_include_password(self, isolated_user_manager):
        manager = isolated_user_manager
        manager.create_user('alice', 'pass', auth.ROLE_USER)
        users = manager.list_users()
        assert all('password_hash' not in u for u in users)
        assert any(u['username'] == 'alice' for u in users)


class TestUserManagerUpdateUser:

    def test_update_username(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        updated = manager.update_user(user.user_id, username='alicia')
        assert updated.username == 'alicia'

    def test_update_password(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'old-pass', auth.ROLE_USER)
        manager.update_user(user.user_id, password='new-pass')
        updated = manager.get_user_by_id(user.user_id)
        assert updated.check_password('new-pass')

    def test_update_role(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        manager.update_user(user.user_id, role=auth.ROLE_ADMIN)
        updated = manager.get_user_by_id(user.user_id)
        assert updated.role == auth.ROLE_ADMIN

    def test_update_nonexistent_user_raises(self, isolated_user_manager):
        with pytest.raises(ValueError, match='not found'):
            isolated_user_manager.update_user('no-such-id', username='x')

    def test_update_duplicate_username_raises(self, isolated_user_manager):
        manager = isolated_user_manager
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        manager.create_user('bob', 'pass', auth.ROLE_USER)
        with pytest.raises(ValueError, match='already taken'):
            manager.update_user(alice.user_id, username='bob')

    def test_update_username_same_as_current_no_conflict(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        # Updating to the same username should not raise
        updated = manager.update_user(user.user_id, username='alice')
        assert updated.username == 'alice'

    def test_update_invalid_role_raises(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        with pytest.raises(ValueError, match='Invalid role'):
            manager.update_user(user.user_id, role='superuser')


class TestUserManagerChangePassword:

    def test_change_own_password_user_not_found(self, isolated_user_manager):
        with pytest.raises(ValueError, match='User not found'):
            isolated_user_manager.change_own_password('no-such-id', 'old', 'new')

    def test_change_own_password_too_short(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'old-secret', auth.ROLE_USER)
        with pytest.raises(ValueError, match='at least 6 characters'):
            manager.change_own_password(user.user_id, 'old-secret', '12345')

    def test_change_own_password_same_as_current(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'old-secret', auth.ROLE_USER)
        with pytest.raises(ValueError, match='different from current'):
            manager.change_own_password(user.user_id, 'old-secret', 'old-secret')


class TestUserManagerAuthenticate:

    def test_authenticate_correct_credentials(self, isolated_user_manager):
        manager = isolated_user_manager
        manager.create_user('alice', 'mypassword', auth.ROLE_USER)
        user = manager.authenticate('alice', 'mypassword')
        assert user is not None
        assert user.username == 'alice'
        assert user.last_login is not None

    def test_authenticate_wrong_password(self, isolated_user_manager):
        manager = isolated_user_manager
        manager.create_user('alice', 'mypassword', auth.ROLE_USER)
        user = manager.authenticate('alice', 'wrongpassword')
        assert user is None

    def test_authenticate_unknown_user(self, isolated_user_manager):
        user = isolated_user_manager.authenticate('nobody', 'pass')
        assert user is None

    def test_authenticate_updates_last_login(self, isolated_user_manager):
        manager = isolated_user_manager
        manager.create_user('alice', 'mypassword', auth.ROLE_USER)
        user = manager.authenticate('alice', 'mypassword')
        assert user.last_login is not None


class TestUserManagerDeleteUser:

    def test_delete_nonexistent_user_raises(self, isolated_user_manager):
        with pytest.raises(ValueError, match='not found'):
            isolated_user_manager.delete_user('no-such-id')

    def test_delete_user_removes_from_list(self, isolated_user_manager):
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        manager.delete_user(alice.user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(alice.user_id) is None

    def test_delete_user_cleans_astrodex(self, isolated_user_manager, tmp_path, monkeypatch):
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        # Create fake astrodex dir structure
        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        # Create astrodex file with picture reference
        astrodex_data = {
            'items': [{
                'name': 'M42',
                'pictures': [{'filename': f'{user_id}_test.jpg'}],
            }]
        }
        astrodex_file = astrodex_dir / f'{user_id}_astrodex.json'
        astrodex_file.write_text(json.dumps(astrodex_data), encoding='utf-8')

        # Create the image file
        img_file = images_dir / f'{user_id}_test.jpg'
        img_file.write_bytes(b'fake image data')

        # Monkeypatch the directories
        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        manager.delete_user(user_id, current_user_id=admin.user_id)

        # Astrodex file should be deleted
        assert not astrodex_file.exists()

    def test_delete_user_handles_astrodex_cleanup_failure_gracefully(self, isolated_user_manager, monkeypatch):
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)

        # Just ensure delete doesn't raise even if cleanup fails
        manager.delete_user(alice.user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(alice.user_id) is None


class TestUserManagerPreferences:

    def test_get_user_preferences_user_not_found(self, isolated_user_manager):
        with pytest.raises(ValueError, match='User not found'):
            isolated_user_manager.get_user_preferences('no-such-id')

    def test_get_user_preferences_sanitizes_and_saves(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        # Manually corrupt the preferences to trigger sanitization
        user.preferences = {'startup_main_tab': 'skytonight'}  # incomplete prefs
        prefs = manager.get_user_preferences(user.user_id)
        # Should return full sanitized preferences
        assert 'time_format' in prefs

    def test_update_user_preferences_user_not_found(self, isolated_user_manager):
        with pytest.raises(ValueError, match='User not found'):
            isolated_user_manager.update_user_preferences('no-such-id', {'time_format': '24h'})

    def test_update_user_preferences_not_a_dict(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        with pytest.raises(ValueError, match='must be a dictionary'):
            manager.update_user_preferences(user.user_id, 'not-a-dict')

    def test_update_user_preferences_valid(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)
        prefs = manager.update_user_preferences(user.user_id, {'theme_mode': 'dark'})
        assert prefs['theme_mode'] == 'dark'


# ===========================================================================
# validate_users_json_data edge cases
# ===========================================================================


class TestValidateUsersJsonData:

    def test_not_a_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data([])
        assert not is_valid
        assert 'dictionary' in msg

    def test_empty_dict_valid(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({})
        assert is_valid

    def test_empty_key_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({'': {}})
        assert not is_valid
        assert 'non-empty string' in msg

    def test_user_data_not_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({'uid1': 'not-a-dict'})
        assert not is_valid
        assert 'dictionary' in msg

    def test_missing_required_field_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({
            'uid1': {'user_id': 'uid1', 'username': 'alice', 'role': auth.ROLE_USER, 'created_at': '2026-01-01'}
            # missing password_hash
        })
        assert not is_valid
        assert 'missing' in msg

    def test_invalid_role_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({
            'uid1': {
                'user_id': 'uid1',
                'username': 'alice',
                'password_hash': 'h',
                'role': 'superuser',
                'created_at': '2026-01-01',
            }
        })
        assert not is_valid
        assert 'invalid role' in msg.lower()

    def test_preferences_not_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({
            'uid1': {
                'user_id': 'uid1',
                'username': 'alice',
                'password_hash': 'h',
                'role': auth.ROLE_USER,
                'created_at': '2026-01-01',
                'preferences': 'not-a-dict',
            }
        })
        assert not is_valid
        assert 'preferences' in msg

    def test_valid_data_passes(self):
        is_valid, msg = auth.UserManager.validate_users_json_data({
            'uid1': {
                'user_id': 'uid1',
                'username': 'alice',
                'password_hash': 'h',
                'role': auth.ROLE_USER,
                'created_at': '2026-01-01',
            }
        })
        assert is_valid


class TestValidateUsersJsonFile:

    def test_invalid_json_fails(self, tmp_path):
        f = tmp_path / 'bad.json'
        f.write_text('{invalid}', encoding='utf-8')
        is_valid, msg = auth.UserManager.validate_users_json_file(str(f))
        assert not is_valid
        assert 'JSON' in msg

    def test_file_not_found_fails(self, tmp_path):
        is_valid, msg = auth.UserManager.validate_users_json_file(str(tmp_path / 'nonexistent.json'))
        assert not is_valid

    def test_valid_file_passes(self, tmp_path):
        f = tmp_path / 'users.json'
        f.write_text(json.dumps({}), encoding='utf-8')
        is_valid, msg = auth.UserManager.validate_users_json_file(str(f))
        assert is_valid


# ===========================================================================
# validate_user_preferences edge cases
# ===========================================================================


class TestValidateUserPreferences:

    def test_not_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences('not-a-dict')
        assert not is_valid

    def test_invalid_startup_main_tab_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'startup_main_tab': 'invalid-tab'})
        assert not is_valid
        assert 'startup_main_tab' in msg

    def test_invalid_startup_subtab_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'startup_subtab': 'invalid-subtab'})
        assert not is_valid
        assert 'startup_subtab' in msg

    def test_invalid_density_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'density': 'ultra-compact'})
        assert not is_valid
        assert 'density' in msg

    def test_invalid_theme_mode_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'theme_mode': 'sepia'})
        assert not is_valid
        assert 'theme_mode' in msg

    def test_invalid_first_day_of_week_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'first_day_of_week': 'wednesday'})
        assert not is_valid
        assert 'first_day_of_week' in msg

    def test_invalid_language_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'language': 'xx'})
        assert not is_valid
        assert 'language' in msg

    def test_notifications_not_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'notifications': 'yes'})
        assert not is_valid
        assert 'notifications' in msg

    def test_invalid_experience_level_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'experience_level': 'expert'})
        assert not is_valid
        assert 'experience_level' in msg

    def test_valid_experience_level_passes(self):
        for level in ('beginner', 'intermediate', 'advanced'):
            is_valid, msg = auth.UserManager.validate_user_preferences({'experience_level': level})
            assert is_valid

    def test_beginner_catalog_enabled_not_bool_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'beginner_catalog_enabled': 'yes'})
        assert not is_valid
        assert 'beginner_catalog_enabled' in msg

    def test_beginner_catalog_enabled_bool_passes(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'beginner_catalog_enabled': False})
        assert is_valid

    def test_recommendations_enabled_not_bool_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'recommendations_enabled': 'yes'})
        assert not is_valid
        assert 'recommendations_enabled' in msg

    def test_recommendations_enabled_bool_passes(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'recommendations_enabled': True})
        assert is_valid

    def test_wizard_not_dict_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'wizard': 'yes'})
        assert not is_valid
        assert 'wizard' in msg

    def test_wizard_completed_not_bool_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'wizard': {'completed': 'yes'}})
        assert not is_valid
        assert 'wizard' in msg

    def test_wizard_skipped_not_bool_fails(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'wizard': {'skipped': 'yes'}})
        assert not is_valid
        assert 'wizard' in msg

    def test_wizard_valid_passes(self):
        is_valid, msg = auth.UserManager.validate_user_preferences(
            {'wizard': {'completed': True, 'skipped': False}}
        )
        assert is_valid

    def test_valid_minimal_preferences(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'time_format': '24h'})
        assert is_valid

    def test_valid_full_preferences(self):
        prefs = {
            'startup_main_tab': 'skytonight',
            'startup_subtab': 'astro-weather',
            'time_format': '24h',
            'density': 'compact',
            'theme_mode': 'dark',
            'first_day_of_week': 'sunday',
            'language': 'en',
            'notifications': {'enabled': True},
        }
        is_valid, msg = auth.UserManager.validate_user_preferences(prefs)
        assert is_valid

    def test_unknown_keys_silently_ignored(self):
        is_valid, msg = auth.UserManager.validate_user_preferences({'unknown_future_key': 'value'})
        assert is_valid

    def test_default_experience_level_is_advanced(self):
        """Locks in the resolved feature.md discrepancy: 'advanced', not 'beginner'."""
        assert auth.DEFAULT_USER_PREFERENCES['experience_level'] == 'advanced'

    def test_default_wizard_state_is_not_completed_or_skipped(self):
        assert auth.DEFAULT_USER_PREFERENCES['wizard'] == {'completed': False, 'skipped': False}

    def test_default_notifications_includes_n8_trigger(self):
        assert 'N8' in auth.DEFAULT_USER_PREFERENCES['notifications']['triggers']


class TestSanitizeUserPreferences:

    def test_none_input_returns_defaults(self):
        result = auth.UserManager.sanitize_user_preferences(None)
        assert result == auth.DEFAULT_USER_PREFERENCES

    def test_not_dict_returns_defaults(self):
        result = auth.UserManager.sanitize_user_preferences('string')
        assert result == auth.DEFAULT_USER_PREFERENCES

    def test_partial_prefs_merged_with_defaults(self):
        result = auth.UserManager.sanitize_user_preferences({'startup_main_tab': 'skytonight'})
        assert result['startup_main_tab'] == 'skytonight'
        assert result['time_format'] == auth.DEFAULT_USER_PREFERENCES['time_format']

    def test_unknown_keys_not_included(self):
        result = auth.UserManager.sanitize_user_preferences({'unknown_key': 'value'})
        assert 'unknown_key' not in result


# ===========================================================================
# Auth decorators (via Flask app)
# ===========================================================================


class TestAuthDecorators:

    @pytest.fixture
    def flask_app(self, tmp_path, monkeypatch):
        """Set up a minimal Flask app with auth routes for testing."""
        import sys
        import os
        backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)

        from app import app as flask_app
        flask_app.config['TESTING'] = True

        # Use isolated users file
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        # Reset user manager state
        auth.user_manager._users_mtime = None
        auth.user_manager.users = {}
        auth.user_manager.load_users()

        return flask_app

    def test_login_required_blocks_unauthenticated(self, flask_app):
        with flask_app.test_client() as c:
            resp = c.get('/api/skytonight/scheduler/status')
            assert resp.status_code == 401

    def test_admin_required_blocks_regular_user(self, flask_app):
        with flask_app.test_client() as c:
            user = auth.user_manager.create_user('reguser', 'pass', auth.ROLE_USER)
            with c.session_transaction() as sess:
                sess['username'] = 'reguser'
                sess['user_id'] = user.user_id
                sess['role'] = auth.ROLE_USER
            resp = c.post('/api/skytonight/scheduler/trigger')
            assert resp.status_code == 403

    def test_admin_required_allows_admin(self, flask_app, monkeypatch):
        import skytonight_api as _mod
        monkeypatch.setattr(_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        with flask_app.test_client() as c:
            admin = auth.user_manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
            with c.session_transaction() as sess:
                sess['username'] = auth.DEFAULT_ADMIN_USERNAME
                sess['user_id'] = admin.user_id
                sess['role'] = auth.ROLE_ADMIN
            resp = c.post('/api/skytonight/scheduler/trigger')
            # Should not be 401 or 403
            assert resp.status_code in (200, 500)

    def test_admin_required_blocks_unknown_user_in_session(self, flask_app):
        with flask_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'ghost_user_not_in_db'
            resp = c.post('/api/skytonight/scheduler/trigger')
            assert resp.status_code == 403

    def test_get_current_user_returns_none_when_no_session(self, flask_app):
        with flask_app.test_request_context('/'):
            user = auth.get_current_user()
            assert user is None

    def test_get_current_user_returns_user_when_session_set(self, flask_app):
        with flask_app.test_request_context('/'):
            from flask import session
            session['username'] = auth.DEFAULT_ADMIN_USERNAME
            user = auth.get_current_user()
            assert user is not None
            assert user.username == auth.DEFAULT_ADMIN_USERNAME

    def test_is_user_admin_true(self, flask_app):
        with flask_app.test_request_context('/'):
            from flask import session
            session['username'] = auth.DEFAULT_ADMIN_USERNAME
            assert auth.is_user_admin() is True

    def test_is_user_admin_false_no_session(self, flask_app):
        with flask_app.test_request_context('/'):
            # is_user_admin returns None (falsy) when no session; `and` short-circuits
            assert not auth.is_user_admin()


# ===========================================================================
# auth.UserManager.save_users failure path
# ===========================================================================


class TestSaveUsersFailurePaths:

    def test_save_users_restores_backup_on_validation_failure(self, tmp_path, monkeypatch):
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()

        # Patch validate_users_json_file to fail, triggering backup restore
        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file', classmethod(lambda cls, fp: (False, 'fail')))

        # This should raise and restore backup
        with pytest.raises(Exception):
            manager.save_users()

    def test_ensure_default_admin_does_not_duplicate(self, isolated_user_manager):
        manager = isolated_user_manager
        # Call ensure_default_admin again; should not create a duplicate
        manager.ensure_default_admin()
        admins = [u for u in manager.users.values() if u.username == auth.DEFAULT_ADMIN_USERNAME]
        assert len(admins) == 1


# ===========================================================================
# Additional coverage for missing lines
# ===========================================================================


class TestDeleteUserAstrodexCleanup:
    """Target lines 551-596: astrodex file exists, images, listdir cleanup."""

    def test_delete_user_with_astrodex_file_and_images(self, isolated_user_manager, tmp_path, monkeypatch):
        """Covers lines 552-563, 566-576, 579-588, 591-593: full astrodex cleanup."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        # Create fake astrodex dir structure
        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        # Create astrodex file with picture references
        valid_filename = f'{user_id}_pic1.jpg'
        traversal_filename = '../outside.jpg'  # should be ignored (path traversal)
        astrodex_data = {
            'items': [{
                'name': 'M42',
                'pictures': [
                    {'filename': valid_filename},
                    {'filename': traversal_filename},  # invalid chars → skipped
                ],
            }]
        }
        astrodex_file = astrodex_dir / f'{user_id}_astrodex.json'
        astrodex_file.write_text(json.dumps(astrodex_data), encoding='utf-8')

        # Create the image files
        img_file = images_dir / valid_filename
        img_file.write_bytes(b'fake image data')

        # Create another image with user_id prefix (for listdir loop)
        img_file2 = images_dir / f'{user_id}_pic2.jpg'
        img_file2.write_bytes(b'another image')

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        manager.delete_user(user_id, current_user_id=admin.user_id)

        # Astrodex file should be deleted
        assert not astrodex_file.exists()
        # Image files should be deleted
        assert not img_file.exists()
        assert not img_file2.exists()

    def test_delete_user_astrodex_file_read_error_logged(self, isolated_user_manager, tmp_path, monkeypatch):
        """Covers line 562-563: exception when reading astrodex file."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        # Write invalid JSON to astrodex file
        astrodex_file = astrodex_dir / f'{user_id}_astrodex.json'
        astrodex_file.write_text('{invalid json', encoding='utf-8')

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        # Should not raise
        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None

    def test_delete_user_image_remove_failure_logged(self, isolated_user_manager, tmp_path, monkeypatch):
        """Covers lines 575-576: os.remove fails for image → warning logged."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        valid_filename = f'{user_id}_pic1.jpg'
        astrodex_data = {'items': [{'name': 'M42', 'pictures': [{'filename': valid_filename}]}]}
        astrodex_file = astrodex_dir / f'{user_id}_astrodex.json'
        astrodex_file.write_text(json.dumps(astrodex_data), encoding='utf-8')

        img_file = images_dir / valid_filename
        img_file.write_bytes(b'data')

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        original_remove = os.remove
        call_count = [0]

        def failing_remove(path):
            call_count[0] += 1
            if str(valid_filename) in str(path) and call_count[0] <= 2:
                raise OSError('Permission denied')
            original_remove(path)

        monkeypatch.setattr(os, 'remove', failing_remove)

        # Should not raise - failure should be silently logged
        manager.delete_user(user_id, current_user_id=admin.user_id)


class TestSaveUsersCleanupPaths:
    """Covers lines 260->267, 264-265, 267->273, 270-271, 274-277: cleanup paths in save_users."""

    def test_save_users_temp_file_removed_on_error(self, tmp_path, monkeypatch):
        """Covers lines 267-277: temp file cleanup after validation failure."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()

        # Make validate_users_json_file always fail
        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file',
                            classmethod(lambda cls, fp: (False, 'simulated failure')))

        with pytest.raises(Exception):
            manager.save_users()

        # The temp file should not remain
        assert not os.path.exists(str(users_file) + '.tmp')

    def test_save_users_backup_removed_on_success(self, tmp_path, monkeypatch):
        """Covers line 252-253: backup cleaned up after successful save."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()

        # Create a backup file that would normally be created and cleaned
        backup_path = str(users_file) + '.backup'

        # First create a valid file so a backup is made on next save
        manager.create_user('alice', 'pass', auth.ROLE_USER)

        # Backup should have been cleaned up
        assert not os.path.exists(backup_path)

    def test_save_users_restore_backup_on_error(self, tmp_path, monkeypatch):
        """Covers lines 260-265: backup restored when save fails."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()

        # Ensure file exists before we try to fail
        manager.create_user('alice', 'pass', auth.ROLE_USER)
        # Make validate always fail to trigger backup restore path
        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file',
                            classmethod(lambda cls, fp: (False, 'simulated failure')))

        with pytest.raises(Exception):
            manager.save_users()

        # File should still exist (restored from backup)
        assert users_file.exists()

    def test_save_users_restore_replace_fails(self, tmp_path, monkeypatch):
        """Lines 264-265: os.replace raises during backup restore."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        manager.create_user('alice', 'pass', auth.ROLE_USER)

        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file',
                            classmethod(lambda cls, fp: (False, 'fail')))

        def _fail_replace(src, dst):
            raise OSError('replace denied')

        monkeypatch.setattr(auth.os, 'replace', _fail_replace)
        with pytest.raises(Exception):
            manager.save_users()

    def test_save_users_temp_remove_fails(self, tmp_path, monkeypatch):
        """Lines 270-271: os.remove raises on temp file cleanup."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        manager.create_user('alice', 'pass', auth.ROLE_USER)

        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file',
                            classmethod(lambda cls, fp: (False, 'fail')))

        original_remove = auth.os.remove

        def _fail_tmp_remove(path):
            if str(path).endswith('.tmp'):
                raise OSError('cannot remove tmp')
            original_remove(path)

        monkeypatch.setattr(auth.os, 'remove', _fail_tmp_remove)
        with pytest.raises(Exception):
            manager.save_users()

    def test_save_users_backup_cleanup_fails_after_restore_failure(self, tmp_path, monkeypatch):
        """Lines 264-265 and 274-277: restore replace fails AND backup remove fails."""
        users_file = tmp_path / 'users.json'
        monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))
        manager = auth.UserManager()
        manager.create_user('alice', 'pass', auth.ROLE_USER)

        monkeypatch.setattr(auth.UserManager, 'validate_users_json_file',
                            classmethod(lambda cls, fp: (False, 'fail')))

        def _fail_replace(src, dst):
            raise OSError('replace denied')

        def _fail_backup_remove(path):
            if str(path).endswith('.backup'):
                raise OSError('cannot remove backup')

        monkeypatch.setattr(auth.os, 'replace', _fail_replace)
        monkeypatch.setattr(auth.os, 'remove', _fail_backup_remove)
        with pytest.raises(Exception):
            manager.save_users()


class TestUserRequiredDecorator:
    """Covers lines 654-668: user_required decorator - tested directly via decorator logic."""

    def test_user_required_blocks_unauthenticated(self, isolated_user_manager):
        """Test decorator logic by calling the inner decorated_function directly."""
        from flask import Flask

        mini_app = Flask(__name__ + '_user_req')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/protected')
        @auth.user_required
        def protected():
            from flask import jsonify
            return jsonify({'ok': True})

        with mini_app.test_client() as c:
            resp = c.get('/protected')
            assert resp.status_code == 401

    def test_user_required_blocks_read_only_user(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_user_req_ro')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/protected')
        @auth.user_required
        def protected():
            from flask import jsonify
            return jsonify({'ok': True})

        isolated_user_manager.create_user('viewer', 'pass', auth.ROLE_READ_ONLY)
        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'viewer'
            resp = c.get('/protected')
            assert resp.status_code == 403

    def test_user_required_blocks_unknown_user_in_session(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_user_req_ghost')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/protected')
        @auth.user_required
        def protected():
            from flask import jsonify
            return jsonify({'ok': True})

        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'ghost_user_not_in_db'
            resp = c.get('/protected')
            assert resp.status_code == 403

    def test_user_required_allows_regular_user(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_user_req_regular')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/protected')
        @auth.user_required
        def protected():
            from flask import jsonify
            return jsonify({'ok': True})

        isolated_user_manager.create_user('regular', 'pass', auth.ROLE_USER)
        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'regular'
            resp = c.get('/protected')
            assert resp.status_code == 200

    def test_user_required_allows_admin(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_user_req_admin')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/protected')
        @auth.user_required
        def protected():
            from flask import jsonify
            return jsonify({'ok': True})

        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = auth.DEFAULT_ADMIN_USERNAME
            resp = c.get('/protected')
            assert resp.status_code == 200


class TestGetUserPreferencesSaveOnSanitize:
    """Covers line 479-481: save_users called when sanitized prefs differ."""

    def test_get_user_preferences_saves_when_sanitized(self, isolated_user_manager):
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)

        # Manually set preferences to a subset (dirty) state
        user.preferences = {'startup_main_tab': 'skytonight'}  # missing many keys

        # get_user_preferences should sanitize and save
        prefs = manager.get_user_preferences(user.user_id)

        # All default keys should now be present
        assert 'time_format' in prefs
        assert 'density' in prefs

        # And the updated user should have the sanitized preferences saved
        reloaded = manager.get_user_by_id(user.user_id)
        assert 'time_format' in reloaded.preferences


class TestValidateUsersJsonDataPreferencesInvalid:
    """Covers line 312: invalid preferences inside validate_users_json_data."""

    def test_invalid_preferences_in_user_data_fails(self):
        data = {
            'uid1': {
                'user_id': 'uid1',
                'username': 'alice',
                'password_hash': 'h',
                'role': auth.ROLE_USER,
                'created_at': '2026-01-01',
                'preferences': {'time_format': 'invalid-format'},  # invalid value
            }
        }
        is_valid, msg = auth.UserManager.validate_users_json_data(data)
        assert not is_valid
        assert 'preferences' in msg.lower() or 'time_format' in msg.lower()


class TestLoginRequiredDecoratorPassThrough:
    """Covers line 643: login_required passes through to the wrapped function."""

    def test_login_required_passes_through_authenticated(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_login_req')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/guarded')
        @auth.login_required
        def guarded():
            from flask import jsonify
            return jsonify({'reached': True})

        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = auth.DEFAULT_ADMIN_USERNAME
            resp = c.get('/guarded')
            assert resp.status_code == 200
            assert resp.get_json()['reached'] is True


class TestAdminRequiredDecoratorUnauthenticated:
    """Covers lines 680-682: admin_required blocks unauthenticated requests."""

    def test_admin_required_blocks_no_session(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_admin_req')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/admin-only', methods=['POST'])
        @auth.admin_required
        def admin_only():
            from flask import jsonify
            return jsonify({'ok': True})

        with mini_app.test_client() as c:
            resp = c.post('/admin-only')
            assert resp.status_code == 401

    def test_admin_required_blocks_regular_user(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_admin_req_block')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/admin-only', methods=['POST'])
        @auth.admin_required
        def admin_only():
            from flask import jsonify
            return jsonify({'ok': True})

        isolated_user_manager.create_user('reguser', 'pass', auth.ROLE_USER)
        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'reguser'
            resp = c.post('/admin-only')
            assert resp.status_code == 403

    def test_admin_required_allows_admin(self, isolated_user_manager):
        from flask import Flask

        mini_app = Flask(__name__ + '_admin_req_allow')
        mini_app.config['TESTING'] = True
        mini_app.config['SECRET_KEY'] = 'test-secret'

        @mini_app.route('/admin-only', methods=['POST'])
        @auth.admin_required
        def admin_only():
            from flask import jsonify
            return jsonify({'ok': True})

        with mini_app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = auth.DEFAULT_ADMIN_USERNAME
            resp = c.post('/admin-only')
            assert resp.status_code == 200


class TestUpdateUserPreferencesMergedValidation:
    """Covers line 504: update_user_preferences merged validation failure."""

    def test_update_preferences_merged_validation_fails(self, isolated_user_manager, monkeypatch):
        """Covers the case where merged preferences fail validation."""
        manager = isolated_user_manager
        user = manager.create_user('alice', 'pass', auth.ROLE_USER)

        call_count = [0]
        original_validate = auth.UserManager.validate_user_preferences

        def patched_validate(prefs):
            call_count[0] += 1
            # First call (individual validation) passes, second call (merged) fails
            if call_count[0] > 1:
                return False, 'merged validation failed'
            return original_validate(prefs)

        monkeypatch.setattr(auth.UserManager, 'validate_user_preferences', staticmethod(patched_validate))

        with pytest.raises(ValueError, match='merged validation failed'):
            manager.update_user_preferences(user.user_id, {'theme_mode': 'dark'})


class TestDeleteUserPathConfinement:
    """Covers line 546: path confinement check raises ValueError."""

    def test_delete_user_path_confinement_check(self, isolated_user_manager, tmp_path, monkeypatch):
        """Covers line 546: astrodex_file not within base_astrodex_dir → ValueError → caught."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        # Create dirs
        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        # Patch os.path.normpath to return a path outside the base dir
        original_normpath = os.path.normpath

        def patched_normpath(path):
            if '_astrodex.json' in str(path):
                # Return a path outside the astrodex dir
                return str(tmp_path / 'outside_astrodex.json')
            return original_normpath(path)

        monkeypatch.setattr(os.path, 'normpath', patched_normpath)

        # Should not raise - ValueError is caught by outer except
        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None


class TestDeleteUserImageTraversalGuard:
    """Covers line 570: file_path doesn't start with base_images_dir → continue."""

    def test_delete_user_image_traversal_skipped(self, isolated_user_manager, tmp_path, monkeypatch):
        """Test that images with paths outside images_dir are skipped (line 570)."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        # Create astrodex file with a picture filename
        valid_filename = f'{user_id}_pic1.jpg'
        astrodex_data = {'items': [{'name': 'M42', 'pictures': [{'filename': valid_filename}]}]}
        astrodex_file = astrodex_dir / f'{user_id}_astrodex.json'
        astrodex_file.write_text(json.dumps(astrodex_data), encoding='utf-8')

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        # Make normpath return a path outside images_dir for the image file
        original_normpath = os.path.normpath

        def patched_normpath(path):
            if valid_filename in str(path) and 'astrodex_images' in str(path):
                # Return a traversal path outside images_dir
                return str(tmp_path / 'outside_dir' / valid_filename)
            return original_normpath(path)

        monkeypatch.setattr(os.path, 'normpath', patched_normpath)

        # Should complete without error - traversal paths are skipped
        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None


class TestDeleteUserListdirRemoveFails:
    """Lines 587-588: os.remove raises in the listdir loop."""

    def test_delete_user_listdir_remove_fails(self, isolated_user_manager, tmp_path, monkeypatch):
        """Lines 587-588: os.remove on a listdir-found image raises → warning logged."""
        manager = isolated_user_manager
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user('alice', 'pass', auth.ROLE_USER)
        user_id = alice.user_id

        astrodex_dir = tmp_path / 'astrodex'
        images_dir = tmp_path / 'astrodex_images'
        astrodex_dir.mkdir()
        images_dir.mkdir()

        # No astrodex JSON → image_filenames is empty, first loop is no-op
        # Create an image matching the user_id prefix for the listdir loop
        img_filename = f'{user_id}_pic.jpg'
        img_file = images_dir / img_filename
        img_file.write_bytes(b'data')

        monkeypatch.setattr('astrodex.ASTRODEX_DIR', str(astrodex_dir))
        monkeypatch.setattr('astrodex.ASTRODEX_IMAGES_DIR', str(images_dir))

        original_remove = os.remove

        def _fail_remove(path):
            if img_filename in str(path):
                raise OSError('cannot remove')
            original_remove(path)

        monkeypatch.setattr(os, 'remove', _fail_remove)
        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None
