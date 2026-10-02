"""Tests for json_settings_store.py: the shared load/save/revision helpers behind
utils/app_settings.py and utils/security_settings.py.
"""

from db import settings_store
from utils.json_settings_store import get_settings_revision, load_json_settings, save_json_settings


def test_load_returns_defaults_when_never_saved():
    settings = load_json_settings('test_settings', {'a': 1, 'b': False}, 'Test')

    assert settings == {'a': 1, 'b': False}


def test_load_merges_known_keys_over_defaults():
    settings_store.put_setting('test_settings', {'a': 2})

    settings = load_json_settings('test_settings', {'a': 1, 'b': False}, 'Test')

    assert settings == {'a': 2, 'b': False}


def test_load_ignores_unknown_keys():
    settings_store.put_setting('test_settings', {'a': 2, 'unexpected': 'value'})

    settings = load_json_settings('test_settings', {'a': 1}, 'Test')

    assert settings == {'a': 2}


def test_load_falls_back_to_defaults_on_wrong_shape():
    settings_store.put_setting('test_settings', 'not an object')

    settings = load_json_settings('test_settings', {'a': 1}, 'Test')

    assert settings == {'a': 1}


def test_load_falls_back_to_defaults_when_unreadable(monkeypatch):
    def _boom(_key):
        raise OSError('denied')

    monkeypatch.setattr(settings_store, 'get_setting', _boom)

    settings = load_json_settings('test_settings', {'a': 1}, 'Test')

    assert settings == {'a': 1}


def test_save_merges_over_defaults_and_stores():
    merged = save_json_settings('test_settings', {'a': 1, 'b': False}, {'a': 2}, 'Test')

    assert merged == {'a': 2, 'b': False}
    assert settings_store.get_setting('test_settings') == {'a': 2, 'b': False}


def test_save_ignores_unknown_keys_in_the_input():
    merged = save_json_settings('test_settings', {'a': 1}, {'a': 2, 'unexpected': 'value'}, 'Test')

    assert merged == {'a': 2}
    assert 'unexpected' not in settings_store.get_setting('test_settings')


def test_revision_moves_on_each_save():
    before = get_settings_revision('test_settings')
    save_json_settings('test_settings', {'a': 1}, {'a': 1}, 'Test')

    assert get_settings_revision('test_settings') == before + 1


def test_revision_none_when_unreadable(monkeypatch):
    def _boom(_key):
        raise OSError('denied')

    monkeypatch.setattr(settings_store, 'setting_revision', _boom)

    assert get_settings_revision('test_settings') is None
