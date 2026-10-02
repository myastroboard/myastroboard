"""Admin backup ZIP: built from the database, restored into it, compatible with 1.6 archives."""

import io
import json
import os
import zipfile

import pytest
from sqlalchemy import delete

from db import documents, engine, schema, settings_store, users_store
from utils import backup_archive

ALICE = '11111111-1111-4111-8111-111111111111'
BOB = '22222222-2222-4222-8222-222222222222'


def _user(user_id, username, role='user'):
    return {
        'user_id': user_id,
        'username': username,
        'password_hash': 'pbkdf2:sha256:x',
        'role': role,
        'created_at': '2026-01-01T00:00:00+00:00',
    }


@pytest.fixture
def media_dirs(tmp_path, monkeypatch):
    """Picture and attachment directories of this test."""
    from observation import astrodex, observation_sessions

    images = tmp_path / 'astrodex' / 'images'
    monkeypatch.setattr(astrodex, 'ASTRODEX_DIR', str(tmp_path / 'astrodex'))
    monkeypatch.setattr(astrodex, 'ASTRODEX_IMAGES_DIR', str(images))
    monkeypatch.setattr(observation_sessions, 'OBSERVATION_SESSIONS_DIR', str(tmp_path / 'observation_sessions'))
    images.mkdir(parents=True)
    return {'images': images, 'attachments': tmp_path / 'observation_sessions' / 'attachments'}


@pytest.fixture
def populated(media_dirs):
    with engine.transaction() as conn:
        conn.execute(delete(schema.users))
    users_store.upsert_users([_user(ALICE, 'alice', 'admin'), _user(BOB, 'bob')])
    settings_store.put_setting('config', {'locations': [{'id': 'loc-1', 'name': 'Jardin'}]})
    settings_store.put_setting('app_settings', {'log_retention_days': 30})
    settings_store.put_setting('security_settings', {'trusted_networks': ['10.0.0.0/8']})
    settings_store.put_setting('connectors_secrets', {'mqtt': {'password': 'secret'}})
    documents.put_document(ALICE, 'astrodex', {'username': 'alice', 'items': [{'id': 'i', 'name': 'M 31'}]})
    documents.put_document(ALICE, 'equipment.cameras', {'items': [{'id': 'cam', 'name': 'ASI533'}]})
    documents.put_document(BOB, 'wishlist', {'username': 'bob', 'items': []})
    documents.put_document(ALICE, 'plan', {'user_id': ALICE, 'plan': None}, doc_key='default')
    (media_dirs['images'] / f'{ALICE}_m31.jpg').write_bytes(b'jpeg')
    return media_dirs


def _backup_bytes():
    buf = io.BytesIO()
    backup_archive.write_backup(buf)
    return buf.getvalue()


def _restore(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        plan = backup_archive.plan_restore(archive)
        return backup_archive.apply_restore(archive, plan)


def test_backup_uses_the_pre_1_7_layout_and_leaves_secrets_out(populated):
    with zipfile.ZipFile(io.BytesIO(_backup_bytes())) as archive:
        names = set(archive.namelist())
        users = json.loads(archive.read('users.json'))

    assert {
        'config.json',
        'app_settings.json',
        'users.json',
        f'astrodex/{ALICE}_astrodex.json',
        f'equipments/{ALICE}_cameras.json',
        f'wishlist/{BOB}_wishlist.json',
        f'astrodex/images/{ALICE}_m31.jpg',
    } == names
    assert set(users) == {ALICE, BOB}
    # Plans, security settings and secrets are never part of a backup
    assert not any(name.startswith('projects/') for name in names)


def test_round_trip_restores_everything_and_drops_newer_data(populated):
    blob = _backup_bytes()
    # Changes made after the backup
    documents.put_document(ALICE, 'astrodex', {'username': 'alice', 'items': []})
    documents.put_document(BOB, 'astrodex', {'username': 'bob', 'items': [{'id': 'x', 'name': 'NGC 7000'}]})
    users_store.upsert_users([_user('33333333-3333-4333-8333-333333333333', 'carol')])
    (populated['images'] / 'stray.jpg').write_bytes(b'new')
    settings_store.put_setting('config', {'locations': []})

    report = _restore(blob)

    assert report.skipped == []
    assert set(users_store.get_all_users()) == {ALICE, BOB}
    assert documents.get_document(ALICE, 'astrodex')['items'] == [{'id': 'i', 'name': 'M 31'}]
    assert documents.get_document(BOB, 'astrodex') is None
    assert settings_store.get_setting('config') == {'locations': [{'id': 'loc-1', 'name': 'Jardin'}]}
    assert sorted(os.listdir(populated['images'])) == [f'{ALICE}_m31.jpg']
    # Not in the archive, so untouched by the restore
    assert settings_store.get_setting('connectors_secrets') == {'mqtt': {'password': 'secret'}}
    assert documents.get_document(ALICE, 'plan', 'default') == {'user_id': ALICE, 'plan': None}


def test_restores_a_1_6_archive(populated):
    """A ZIP written by 1.6 (files straight from the data directory) restores as is."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('users.json', json.dumps({ALICE: _user(ALICE, 'alice', 'admin')}))
        archive.writestr(f'astrodex/{ALICE}_astrodex.json', json.dumps({'username': 'alice', 'items': []}))
        archive.writestr('astrodex/myastroshine_consumed_handoffs.json', '{}')  # ignored
        archive.writestr(f'astrodex/images/{ALICE}_new.jpg', b'jpeg')
        archive.writestr('equipments/', b'')  # directory entry

    report = _restore(buf.getvalue())

    assert set(users_store.get_all_users()) == {ALICE}
    assert documents.get_document(ALICE, 'astrodex') == {'username': 'alice', 'items': []}
    assert documents.get_document(BOB, 'wishlist') is None  # bob is gone, with his data
    assert sorted(os.listdir(populated['images'])) == [f'{ALICE}_new.jpg']
    assert report.restored == 3


def test_documents_of_unknown_users_are_skipped(populated):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr(f'wishlist/{BOB}_wishlist.json', json.dumps({'username': 'bob', 'items': []}))
        archive.writestr('wishlist/44444444-4444-4444-8444-444444444444_wishlist.json', '{"items": []}')

    report = _restore(buf.getvalue())

    assert report.skipped == ['wishlist/44444444-4444-4444-8444-444444444444_wishlist.json']


@pytest.mark.parametrize(
    'name, payload, message',
    [
        ('config.json', '{nope', 'config.json is not valid JSON'),
        ('config.json', '[1, 2]', 'config.json is not a JSON object'),
        ('users.json', '{"x": {"user_id": "y"}}', 'users.json is invalid'),
        (f'astrodex/{ALICE}_astrodex.json', '"text"', 'is not a JSON object'),
    ],
)
def test_invalid_members_reject_the_whole_archive(populated, name, payload, message):
    before = users_store.get_all_users()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr(name, payload)

    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as archive:
        with pytest.raises(backup_archive.BackupArchiveError, match=message):
            backup_archive.plan_restore(archive)
    assert users_store.get_all_users() == before


def test_unsafe_binary_paths_are_sanitized(populated):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('astrodex/images/../../escape.jpg', b'x')

    _restore(buf.getvalue())

    root = populated['images'].parent.parent
    assert not (root / 'escape.jpg').exists()
    assert os.listdir(populated['images']) == [f'{ALICE}_m31.jpg']  # the traversal member is dropped


def test_empty_archive_plan(populated):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('readme.txt', 'hello')
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as archive:
        assert backup_archive.plan_restore(archive).empty
