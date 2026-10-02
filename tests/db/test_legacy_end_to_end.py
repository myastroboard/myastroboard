"""A complete pre-1.7 data directory imported, then read back through the application modules."""

import json
import os

import pytest
from sqlalchemy import delete

from db import engine, legacy_import, schema

ALICE = '11111111-1111-4111-8111-111111111111'
BOB = '22222222-2222-4222-8222-222222222222'
GHOST = '99999999-9999-4999-8999-999999999999'
COMBO = '33333333-3333-4333-8333-333333333333'


def _user(user_id, username, role):
    return {
        'user_id': user_id,
        'username': username,
        'password_hash': 'pbkdf2:sha256:600000$salt$hash',
        'role': role,
        'created_at': '2026-01-01T00:00:00+00:00',
        'last_login': None,
        'preferences': {'language': 'fr', 'theme_mode': 'dark'},
        'push_subscriptions': [],
        'account_scope': 'global',
        'totp_secret': None,
        'totp_enabled': False,
        'totp_confirmed_at': None,
    }


ASTRODEX = {
    'user_id': ALICE,
    'username': 'alice',
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-03-01T00:00:00+00:00',
    'items': [
        {
            'id': 'item-1',
            'name': 'M 31',
            'type': 'Galaxy',
            'catalogue': 'Messier',
            'constellation': 'Andromeda',
            'notes': 'Première lumière ✨',
            'pictures': [{'id': 'pic-1', 'filename': f'{ALICE}_m31.jpg', 'latitude': 45.1, 'longitude': 5.7}],
            'mag': 3.4,
            'created_at': '2026-02-01T00:00:00+00:00',
            'updated_at': '2026-02-01T00:00:00+00:00',
        }
    ],
}
SESSIONS = {
    'user_id': ALICE,
    'username': 'alice',
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-02-01T00:00:00+00:00',
    'sessions': [
        {
            'id': 'session-1',
            'nights': [{'id': 'night-1', 'date': '2026-02-10', 'notes': ''}],
            'entries': [{'id': 'entry-1', 'night_id': 'night-1', 'name': 'M 31'}],
            'attachments': [],
            'created_at': '2026-02-10T20:00:00+00:00',
            'updated_at': '2026-02-10T20:00:00+00:00',
        }
    ],
}
WISHLIST = {
    'user_id': BOB,
    'username': 'bob',
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-02-01T00:00:00+00:00',
    'items': [{'id': 'wish-1', 'name': 'M 42', 'priority': 'high'}],
}
TELESCOPES = {
    'user_id': ALICE,
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-02-01T00:00:00+00:00',
    'items': [{'id': 'scope-1', 'name': 'Newton 200/1000', 'aperture_mm': 200.0, 'focal_length_mm': 1000.0}],
}
COMBINATIONS = {
    'user_id': ALICE,
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-02-01T00:00:00+00:00',
    'items': [{'id': COMBO, 'name': 'Newton + 533', 'telescope_id': 'scope-1', 'filter_ids': []}],
}
PLAN = {
    'user_id': ALICE,
    'username': 'alice',
    'created_at': '2026-02-01T00:00:00+00:00',
    'updated_at': '2026-02-01T00:00:00+00:00',
    'plan': {'plan_date': '2026-02-10', 'combination_id': COMBO, 'entries': [{'id': 'p-1', 'name': 'M 31'}]},
}
CONFIG = {
    'locations': [
        {
            'id': 'loc-1',
            'name': 'Jardin',
            'latitude': 45.1,
            'longitude': 5.7,
            'elevation': 220,
            'timezone': 'Europe/Paris',
            'is_install_default': True,
        }
    ],
    'location_configured': True,
    'astrodex': {'private': False, 'map_private': True},
}


def _write(root, relative, payload):
    path = os.path.join(root, *relative.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(payload, bytes) else 'w'
    with open(path, mode, **({} if mode == 'wb' else {'encoding': 'utf-8'})) as handle:
        if isinstance(payload, (bytes, str)):
            handle.write(payload)
        else:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


@pytest.fixture
def legacy_data_dir(tmp_path):
    """A 1.6 data directory with one file of every kind (and a picture that must stay put)."""
    root = str(tmp_path / 'data')
    _write(root, 'users.json', {ALICE: _user(ALICE, 'alice', 'admin'), BOB: _user(BOB, 'bob', 'user')})
    _write(root, 'config.json', CONFIG)
    _write(root, 'app_settings.json', {'vapid_contact_email': 'admin@example.org', 'log_retention_days': 30})
    _write(root, 'security_settings.json', {'trusted_networks': ['192.168.1.0/24'], 'two_factor_enabled': True})
    _write(root, 'connectors_secrets.json', {'mqtt': {'password': 'broker-pw'}})
    _write(root, 'vapid.json', {'private_key': 'PRIV', 'public_key': 'PUB'})
    _write(root, 'secret_key.txt', 'a' * 64 + '\n')
    _write(root, 'astrodex/myastroshine_consumed_handoffs.json', {'jti-1': 4102444800.0})
    _write(root, f'astrodex/{ALICE}_astrodex.json', ASTRODEX)
    _write(root, f'observation_sessions/{ALICE}_sessions.json', SESSIONS)
    _write(root, f'observation_sessions/{GHOST}_sessions.json', dict(SESSIONS, user_id=GHOST))
    _write(root, f'wishlist/{BOB}_wishlist.json', WISHLIST)
    _write(root, f'equipments/{ALICE}_telescopes.json', TELESCOPES)
    _write(root, f'equipments/{ALICE}_combinations.json', COMBINATIONS)
    _write(root, f'projects/{ALICE}_plan_{COMBO}.json', PLAN)
    _write(root, f'astrodex/images/{ALICE}_m31.jpg', b'\xff\xd8 not really a jpeg')
    _write(root, 'cache/astro_cache.json', {'kept': True})
    with engine.transaction() as conn:
        conn.execute(delete(schema.users))
    return root


def test_full_import_then_read_back_through_the_application(legacy_data_dir, monkeypatch):
    from db import settings_store
    from equipment import equipment_profiles
    from observation import astrodex, myastroshine_integration, observation_sessions, plan_my_night, wishlist
    from utils import app_settings, connector_secrets, push_manager, repo_config, security_settings
    from utils.auth import UserManager

    root = legacy_data_dir
    report = legacy_import.run_if_needed(root)

    assert report is not None and report.succeeded, report and report.failure
    assert report.orphaned == [f'observation_sessions/{GHOST}_sessions.json']
    assert report.unreadable == []
    assert len(report.deleted) == 14

    # Every legacy file is gone; pictures and caches are untouched; the orphan is kept aside
    for relative in report.deleted:
        assert not os.path.exists(os.path.join(root, relative)), relative
    assert os.path.exists(os.path.join(root, 'astrodex', 'images', f'{ALICE}_m31.jpg'))
    assert os.path.exists(os.path.join(root, 'cache', 'astro_cache.json'))
    assert os.path.exists(os.path.join(root, 'backups', 'orphans', 'observation_sessions', f'{GHOST}_sessions.json'))

    # Accounts
    manager = UserManager()
    assert {user['username'] for user in manager.list_users()} == {'alice', 'bob'}
    assert manager.get_user_by_username('alice').preferences['theme_mode'] == 'dark'

    # Per-user documents, read through the feature modules
    assert astrodex.load_user_astrodex(ALICE)['items'] == ASTRODEX['items']
    assert observation_sessions.load_user_sessions(ALICE)['sessions'] == SESSIONS['sessions']
    assert wishlist.load_user_wishlist(BOB)['items'] == WISHLIST['items']
    assert equipment_profiles.load_user_telescopes(ALICE) == TELESCOPES
    assert equipment_profiles.load_user_combinations(ALICE) == COMBINATIONS
    assert plan_my_night.load_user_plan(ALICE, combination_id=COMBO)['plan'] == PLAN['plan']
    assert plan_my_night.list_user_plan_combination_ids(ALICE) == [COMBO]

    # Install-wide settings
    assert repo_config.load_config()['locations'][0]['name'] == 'Jardin'
    app_settings._cache = None
    assert app_settings.get_app_settings()['log_retention_days'] == 30
    security_settings._cache = None
    assert security_settings.get_security_settings()['trusted_networks'] == ['192.168.1.0/24']
    assert connector_secrets.load_secrets('mqtt') == {'password': 'broker-pw'}
    monkeypatch.setattr(push_manager, '_vapid_keys', {})
    assert push_manager.load_or_generate_vapid_keys() == {'private_key': 'PRIV', 'public_key': 'PUB'}
    assert app_settings.load_or_generate_secret_key() == 'a' * 64
    assert myastroshine_integration.is_handoff_consumed('jti-1') is True
    assert settings_store.get_setting('myastroshine_consumed_handoffs') == {'jti-1': 4102444800.0}

    # Nothing left to do on the next start
    assert legacy_import.run_if_needed(root) is None


def test_corrupt_per_user_document_is_quarantined_not_fatal(legacy_data_dir):
    root = legacy_data_dir
    _write(root, f'wishlist/{BOB}_wishlist.json', '{"items": [')

    report = legacy_import.run_if_needed(root)

    assert report is not None and report.succeeded
    assert report.unreadable == [f'wishlist/{BOB}_wishlist.json']
    assert os.path.exists(os.path.join(root, 'backups', 'unreadable', 'wishlist', f'{BOB}_wishlist.json'))


def test_corrupt_config_fails_the_whole_import(legacy_data_dir):
    root = legacy_data_dir
    _write(root, 'config.json', '{broken')

    report = legacy_import.run_if_needed(root)

    assert report is not None and not report.succeeded
    assert 'config.json' in (report.failure or '')
    assert os.path.exists(os.path.join(root, 'users.json'))
    assert os.path.exists(os.path.join(root, f'astrodex/{ALICE}_astrodex.json'))
