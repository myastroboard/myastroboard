"""Tests for json_settings_store.py: the shared load/save/mtime helpers behind
utils/app_settings.py and utils/security_settings.py.
"""

import json

from utils.json_settings_store import get_file_mtime, load_json_settings, save_json_settings


def test_load_returns_defaults_when_file_missing(tmp_path):
    settings = load_json_settings(str(tmp_path / 'missing.json'), {'a': 1, 'b': False}, 'Test')

    assert settings == {'a': 1, 'b': False}


def test_load_merges_known_keys_over_defaults(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'a': 2}))

    settings = load_json_settings(str(path), {'a': 1, 'b': False}, 'Test')

    assert settings == {'a': 2, 'b': False}


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'a': 2, 'unexpected': 'value'}))

    settings = load_json_settings(str(path), {'a': 1}, 'Test')

    assert settings == {'a': 2}


def test_load_falls_back_to_defaults_on_corrupt_json(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{not json')

    settings = load_json_settings(str(path), {'a': 1}, 'Test')

    assert settings == {'a': 1}


def test_load_falls_back_to_defaults_when_unreadable(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'a': 2}))
    monkeypatch.setattr('builtins.open', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))

    settings = load_json_settings(str(path), {'a': 1}, 'Test')

    assert settings == {'a': 1}


def test_save_merges_over_defaults_and_writes_file(tmp_path):
    path = tmp_path / 'nested' / 'settings.json'

    merged = save_json_settings(str(path), {'a': 1, 'b': False}, {'a': 2}, 'Test')

    assert merged == {'a': 2, 'b': False}
    on_disk = json.loads(path.read_text())
    assert on_disk == {'a': 2, 'b': False}


def test_save_creates_missing_parent_directory(tmp_path):
    path = tmp_path / 'a' / 'b' / 'c' / 'settings.json'

    save_json_settings(str(path), {'a': 1}, {'a': 1}, 'Test')

    assert path.exists()


def test_save_ignores_unknown_keys_in_the_input(tmp_path):
    path = tmp_path / 'settings.json'

    merged = save_json_settings(str(path), {'a': 1}, {'a': 2, 'unexpected': 'value'}, 'Test')

    assert merged == {'a': 2}
    assert 'unexpected' not in json.loads(path.read_text())


def test_get_file_mtime_none_when_missing(tmp_path):
    assert get_file_mtime(str(tmp_path / 'missing.json')) is None


def test_get_file_mtime_matches_os_path_getmtime(tmp_path):
    import os

    path = tmp_path / 'settings.json'
    path.write_text('{}')

    assert get_file_mtime(str(path)) == os.path.getmtime(str(path))


def test_get_file_mtime_changes_after_a_rewrite(tmp_path, monkeypatch):
    import os

    path = tmp_path / 'settings.json'
    path.write_text('{}')
    first = get_file_mtime(str(path))

    # Force a different mtime deterministically rather than relying on a real
    # wall-clock gap, which can be flaky on filesystems with coarse resolution.
    os.utime(str(path), (first + 5, first + 5))

    assert get_file_mtime(str(path)) == first + 5


def test_get_file_mtime_none_on_os_error(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    path.write_text('{}')
    monkeypatch.setattr('os.path.getmtime', lambda _p: (_ for _ in ()).throw(OSError('fail')))

    assert get_file_mtime(str(path)) is None
