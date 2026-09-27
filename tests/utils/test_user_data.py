"""Tests for utils.user_data - per-user files: purge (erasure) and export (portability)."""

import json
import types
import uuid
import zipfile

import pytest

from utils import user_data

_DIR_TARGETS = {
    'observation.astrodex.ASTRODEX_DIR': 'astrodex',
    'observation.astrodex.ASTRODEX_IMAGES_DIR': 'astrodex_images',
    'equipment.equipment_profiles.EQUIPMENT_DIR': 'equipments',
    'observation.observation_sessions.OBSERVATION_SESSIONS_DIR': 'observation_sessions',
    'observation.plan_my_night.PLAN_DIR': 'projects',
    'observation.wishlist.WISHLIST_DIR': 'wishlist',
}


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    for target, name in _DIR_TARGETS.items():
        (tmp_path / name).mkdir()
        monkeypatch.setattr(target, str(tmp_path / name))
    (tmp_path / 'observation_sessions' / 'attachments').mkdir()
    return tmp_path


def _user(user_id=None, username='alice'):
    return types.SimpleNamespace(
        user_id=user_id or str(uuid.uuid4()),
        username=username,
        role='user',
        account_scope='global',
        created_at='2026-01-01T00:00:00+00:00',
        last_login=None,
        totp_enabled=True,
        push_subscriptions=[{'endpoint': 'https://push.example/secret', 'keys': {'auth': 'x'}}],
        preferences={'language': 'fr'},
        password_hash='scrypt:hash',
        totp_secret='BASE32SECRET',
    )


def _populate(root, user_id):
    (root / 'astrodex' / f'{user_id}_astrodex.json').write_text(
        json.dumps({'items': [{'pictures': [{'filename': 'legacy_m42.jpg'}]}]}), encoding='utf-8'
    )
    (root / 'astrodex_images' / f'{user_id}_photo.jpg').write_bytes(b'\xff\xd8jpeg')
    (root / 'astrodex_images' / 'legacy_m42.jpg').write_bytes(b'\xff\xd8legacy')
    (root / 'equipments' / f'{user_id}_telescopes.json').write_text('[]', encoding='utf-8')
    (root / 'observation_sessions' / f'{user_id}_sessions.json').write_text('[]', encoding='utf-8')
    (root / 'observation_sessions' / f'{user_id}_sessions.json.lock').write_text('', encoding='utf-8')
    (root / 'observation_sessions' / 'attachments' / f'{user_id}_notes.txt').write_text('n', encoding='utf-8')
    (root / 'projects' / f'{user_id}_plan_my_night.json').write_text('{}', encoding='utf-8')
    (root / 'wishlist' / f'{user_id}_wishlist.json').write_text('[]', encoding='utf-8')


class TestPurge:
    def test_rejects_malformed_user_id(self, data_dirs):
        assert user_data.purge_user_files('../etc') == 0

    def test_removes_only_that_users_files_including_lock_files(self, data_dirs):
        alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
        _populate(data_dirs, alice)
        _populate(data_dirs, bob)

        assert user_data.purge_user_files(alice) == 8

        assert not list(data_dirs.rglob(f'{alice}_*'))
        assert len(list(data_dirs.rglob(f'{bob}_*'))) == 8


class TestExport:
    def test_archive_contains_every_folder_and_nothing_from_others(self, data_dirs, monkeypatch):
        monkeypatch.setattr('utils.repo_config.get_locations_for_user', lambda config, user: [{'name': 'Home'}])
        alice, bob = _user(), _user(username='bob')
        _populate(data_dirs, alice.user_id)
        _populate(data_dirs, bob.user_id)

        archive_file, download_name = user_data.build_user_export(alice)
        try:
            with zipfile.ZipFile(archive_file) as archive:
                names = set(archive.namelist())
                account = json.loads(archive.read('account.json'))
                locations = json.loads(archive.read('locations.json'))
        finally:
            archive_file.close()

        uid = alice.user_id
        assert names == {
            'README.txt',
            'account.json',
            'locations.json',
            f'astrodex/{uid}_astrodex.json',
            f'astrodex/images/{uid}_photo.jpg',
            'astrodex/images/legacy_m42.jpg',
            f'equipment/{uid}_telescopes.json',
            f'observation_sessions/{uid}_sessions.json',
            f'observation_sessions/attachments/{uid}_notes.txt',
            f'plans/{uid}_plan_my_night.json',
            f'wishlist/{uid}_wishlist.json',
        }
        assert download_name.startswith('myastroboard_alice_data_') and download_name.endswith('.zip')
        assert account['username'] == 'alice' and account['two_factor_enabled'] is True
        assert account['push_subscriptions'] == 1
        serialized = json.dumps(account)
        assert 'scrypt:hash' not in serialized and 'BASE32SECRET' not in serialized
        assert 'push.example' not in serialized
        assert locations == [{'name': 'Home'}]

    def test_rejects_malformed_user_id(self, data_dirs):
        with pytest.raises(ValueError):
            user_data.build_user_export(_user(user_id='../etc'))

    def test_download_name_is_sanitized(self, data_dirs, monkeypatch):
        monkeypatch.setattr('utils.repo_config.get_locations_for_user', lambda config, user: [])
        archive_file, download_name = user_data.build_user_export(_user(username='a/b c'))
        archive_file.close()
        assert '/' not in download_name and ' ' not in download_name
