"""Tests for utils.user_data - per-user data: purge (erasure) and export (portability)."""

import ast
import importlib
import json
import os
import types
import uuid
import zipfile
from pathlib import Path

import pytest

from db import documents
from utils import user_data

_DIR_TARGETS = {
    'observation.astrodex.ASTRODEX_DIR': 'astrodex',
    'observation.astrodex.ASTRODEX_IMAGES_DIR': 'astrodex_images',
    'observation.observation_sessions.OBSERVATION_SESSIONS_DIR': 'observation_sessions',
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
    """Documents in the database, pictures and attachments on disk."""
    documents.put_document(
        user_id, 'astrodex', {'items': [{'id': 'i', 'name': 'M 42', 'pictures': [{'filename': 'legacy_m42.jpg'}]}]}
    )
    documents.put_document(user_id, 'equipment.telescopes', {'items': []})
    documents.put_document(user_id, 'observation_sessions', {'sessions': []})
    documents.put_document(user_id, 'plan', {'plan': None}, doc_key='default')
    documents.put_document(user_id, 'wishlist', {'items': []})
    (root / 'astrodex_images' / f'{user_id}_photo.jpg').write_bytes(b'\xff\xd8jpeg')
    (root / 'astrodex_images' / 'legacy_m42.jpg').write_bytes(b'\xff\xd8legacy')
    (root / 'observation_sessions' / 'attachments' / f'{user_id}_notes.txt').write_text('n', encoding='utf-8')
    (root / 'observation_sessions' / 'attachments' / f'{user_id}_draft.tmp').write_text('', encoding='utf-8')


class TestPurge:
    def test_rejects_malformed_user_id(self, data_dirs):
        assert user_data.purge_user_files('../etc') == 0

    def test_removes_only_that_users_files_including_working_files(self, data_dirs):
        alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
        _populate(data_dirs, alice)
        _populate(data_dirs, bob)

        assert user_data.purge_user_files(alice) == 3

        assert not list(data_dirs.rglob(f'{alice}_*'))
        assert len(list(data_dirs.rglob(f'{bob}_*'))) == 3


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
                plan = json.loads(archive.read(f'plans/{alice.user_id}_plan_my_night.json'))
        finally:
            archive_file.close()

        uid = alice.user_id
        assert plan == {'plan': None}
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

    def test_skips_what_cannot_be_exported(self, data_dirs, monkeypatch):
        """Unknown document kinds, unsafe or missing pictures and a failing location lookup are left out."""

        def failing_locations(config, user):
            raise RuntimeError('config unreadable')

        monkeypatch.setattr('utils.repo_config.get_locations_for_user', failing_locations)
        alice = _user()
        uid = alice.user_id
        pictures = [{'filename': f'{uid}_photo.jpg'}, {'filename': '../secret.jpg'}, {'filename': 'missing.jpg'}]
        documents.put_document(uid, 'astrodex', {'items': [{'id': 'i', 'name': 'M 42', 'pictures': pictures}]})
        documents.put_document(uid, 'notes', {'text': 'not a known kind'})

        archive_file, _name = user_data.build_user_export(alice)
        try:
            with zipfile.ZipFile(archive_file) as archive:
                names = set(archive.namelist())
                locations = json.loads(archive.read('locations.json'))
        finally:
            archive_file.close()

        assert names == {'README.txt', 'account.json', 'locations.json', f'astrodex/{uid}_astrodex.json'}
        assert locations == []

    def test_unreadable_astrodex_exports_no_legacy_picture(self, data_dirs, monkeypatch):
        def failing_load(user_id):
            raise OSError('database locked')

        monkeypatch.setattr('observation.astrodex.load_user_astrodex', failing_load)
        assert user_data._legacy_astrodex_pictures(str(uuid.uuid4())) == []


# ---------------------------------------------------------------------------
# Guard: every per-user store must be covered by user_data_dirs()
#
# A feature that keeps user files in a directory user_data_dirs() does not list
# leaves them behind on account deletion and out of the personal data export,
# silently. These tests scan backend/ so a new store has to be classified here.
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).resolve().parents[2] / 'backend'

# Directories holding ``<user_id>_...`` files: must all be in user_data_dirs()
_PER_USER_DIRS = {
    ('observation/astrodex.py', 'ASTRODEX_IMAGES_DIR'),
}

# Data directories that hold no per-user files, with the reason
_SHARED_DIRS = {
    ('utils/constants.py', 'DATA_DIR'): 'data root',
    ('observation/astrodex.py', 'ASTRODEX_DIR'): 'holds images/ (ASTRODEX_IMAGES_DIR, covered)',
    ('observation/observation_sessions.py', 'OBSERVATION_SESSIONS_DIR'): 'holds attachments/ (covered)',
    ('utils/constants.py', 'DATA_DIR_CACHE'): 'shared computed caches',
    ('utils/constants.py', 'SKYTONIGHT_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'SKYTONIGHT_CATALOGUES_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'SKYTONIGHT_CALCULATIONS_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'CONFIG_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'OUTPUT_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'SKYTONIGHT_OUTPUT_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'SKYTONIGHT_LOGS_DIR'): 'shared SkyTonight engine data',
    ('utils/constants.py', 'SKYTONIGHT_RUNTIME_DIR'): 'shared SkyTonight engine data',
    ('observation/object_info.py', 'OBJECT_IMAGE_CACHE_DIR'): 'catalogue object images',
    ('utils/map_tiles.py', 'MAP_TILES_CACHE_DIR'): 'OpenStreetMap tile cache',
    ('space/css_passes.py', 'SKYFIELD_CACHE_DIR'): 'ephemeris cache',
    ('space/iss_passes.py', 'SKYFIELD_CACHE_DIR'): 'ephemeris cache',
    ('space/spaceflight_tracker.py', '_SPACEFLIGHT_IMAGES_DIR'): 'launch images cache',
}

# Modules allowed to build ``<user_id>_...`` file names (all write into _PER_USER_DIRS)
_USER_FILE_MODULES = {
    'blueprints/astrodex.py',
    'blueprints/observation_sessions.py',
    'observation/myastroshine_integration.py',
    'utils/user_data.py',
}

_HOW_TO_FIX = (
    "If it stores per-user files, add it to user_data_dirs() in backend/utils/user_data.py "
    "(so account deletion and the personal data export cover it) and to the lists in this test - "
    "per-user JSON data belongs in the database (db/documents.py), not in files; "
    "otherwise classify it as shared here. See the 'Personal Data (GDPR)' section of "
    ".github/instructions/copilot.instructions.md."
)


def _backend_modules():
    for path in sorted(_BACKEND.rglob('*.py')):
        if '__pycache__' not in path.parts:
            yield path.relative_to(_BACKEND).as_posix(), ast.parse(path.read_text(encoding='utf-8'))


def _data_dir_constants():
    """Module-level ``*_DIR`` constants that point into the data directory (not the source tree)."""
    found = set()
    for module, tree in _backend_modules():
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = getattr(target, 'id', '')
                if (name.endswith('_DIR') or name.endswith('_DIR_CACHE')) and '__file__' not in ast.unparse(node.value):
                    found.add((module, name))
    return found


def _is_user_id(node):
    return isinstance(node, ast.FormattedValue) and ast.unparse(node.value).endswith(('user_id', 'uid'))


def _builds_user_file_name(node):
    """f'{user_id}_...' or f'{user_id}{SOMETHING_SUFFIX}'."""
    if not isinstance(node, ast.JoinedStr) or len(node.values) < 2 or not _is_user_id(node.values[0]):
        return False
    following = node.values[1]
    if isinstance(following, ast.Constant):
        return str(following.value).startswith('_')
    return isinstance(following, ast.FormattedValue) and ast.unparse(following.value).endswith('SUFFIX')


class TestEveryPerUserStoreIsCovered:
    def test_every_data_directory_is_classified(self):
        unclassified = _data_dir_constants() - _PER_USER_DIRS - set(_SHARED_DIRS)
        assert not unclassified, f"Unclassified data directories {sorted(unclassified)}. {_HOW_TO_FIX}"

    def test_classification_lists_have_no_stale_entries(self):
        stale = (_PER_USER_DIRS | set(_SHARED_DIRS)) - _data_dir_constants()
        assert not stale, f"These directory constants no longer exist, drop them from the lists: {sorted(stale)}"

    def test_per_user_directories_are_in_user_data_dirs(self):
        covered = {os.path.realpath(directory) for _folder, directory in user_data.user_data_dirs()}
        for module, name in sorted(_PER_USER_DIRS):
            value = getattr(importlib.import_module(module[: -len('.py')].replace('/', '.')), name)
            assert os.path.realpath(value) in covered, f"{module}:{name} is missing from user_data_dirs()"

    def test_only_known_modules_build_per_user_file_names(self):
        builders = {module for module, tree in _backend_modules() if any(map(_builds_user_file_name, ast.walk(tree)))}
        unknown = builders - _USER_FILE_MODULES
        assert not unknown, f"{sorted(unknown)} build <user_id>_ file names. {_HOW_TO_FIX}"
        assert _USER_FILE_MODULES - builders == set(), "Drop modules that no longer build such names"
