"""Tests for scripts/translate_checker.py: the translation completeness report."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location('translate_checker', ROOT / 'scripts' / 'translate_checker.py')
translate_checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(translate_checker)


@pytest.fixture
def i18n_dir(tmp_path, monkeypatch):
    """An empty i18n folder the script reads instead of static/i18n."""
    folder = tmp_path / 'i18n'
    folder.mkdir()
    monkeypatch.setattr(translate_checker, 'I18N_DIR', folder)
    return folder


def _write(folder, name, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (folder / name).write_text(text, encoding='utf-8')


@pytest.mark.unit
def test_report_lists_completion_and_missing_keys(i18n_dir, capsys):
    """Each language gets its completion percentage and the list of reference keys it lacks."""
    _write(i18n_dir, 'en.json', {'a': 'A', 'b': {'c': 'C', 'd': ['x', 'y']}})
    _write(i18n_dir, 'fr.json', {'a': 'A', 'b': {'d': ['x']}})
    translate_checker.main()
    out = capsys.readouterr().out
    assert 'Reference keys: 4' in out
    assert '- en.json      : 100.00% (4/4)' in out
    assert '- fr.json      :  50.00% (2/4)' in out
    assert '[en.json] Missing keys: 0\n  - None' in out
    assert '[fr.json] Missing keys: 2\n  - b.c\n  - b.d[1]' in out


@pytest.mark.unit
def test_invalid_language_file_is_skipped_with_a_warning(i18n_dir, capsys):
    """A broken or non-object language file is skipped; the others are still reported."""
    _write(i18n_dir, 'en.json', {'a': 'A'})
    _write(i18n_dir, 'de.json', '{"a": ')
    _write(i18n_dir, 'it.json', ['A'])
    translate_checker.main()
    out = capsys.readouterr().out
    assert 'Warning: skip de.json' in out
    assert 'Warning: skip it.json (Top-level JSON object must be a dictionary in it.json)' in out
    assert '- en.json      : 100.00% (1/1)' in out


@pytest.mark.unit
def test_missing_folder_is_reported(tmp_path, monkeypatch, capsys):
    """A missing i18n folder stops the report with an error line."""
    monkeypatch.setattr(translate_checker, 'I18N_DIR', tmp_path / 'nope')
    translate_checker.main()
    assert 'Error: i18n folder not found' in capsys.readouterr().out


@pytest.mark.unit
def test_missing_reference_is_reported(i18n_dir, capsys):
    """Without en.json there is nothing to compare against."""
    _write(i18n_dir, 'fr.json', {'a': 'A'})
    translate_checker.main()
    assert 'Error: reference file not found' in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize('payload', ['{"a": ', '["a"]'])
def test_unloadable_reference_is_reported(i18n_dir, capsys, payload):
    """A reference that is not valid JSON, or not an object, stops the report."""
    _write(i18n_dir, 'en.json', payload)
    translate_checker.main()
    assert 'Error while loading reference file en.json' in capsys.readouterr().out


@pytest.mark.unit
def test_empty_reference_is_reported(i18n_dir, capsys):
    """A reference without keys cannot give a percentage."""
    _write(i18n_dir, 'en.json', {})
    translate_checker.main()
    assert 'has no keys to compare' in capsys.readouterr().out


@pytest.mark.unit
def test_no_valid_language_file_is_reported(i18n_dir, monkeypatch, capsys):
    """When every language file fails to load after the reference did, the report says so."""
    _write(i18n_dir, 'en.json', {'a': 'A'})
    monkeypatch.setattr(translate_checker, 'iter_language_files', lambda _folder: [i18n_dir / 'gone.json'])
    translate_checker.main()
    out = capsys.readouterr().out
    assert 'Warning: skip gone.json' in out
    assert 'No valid translation files found.' in out


@pytest.mark.unit
def test_flatten_keys_handles_top_level_list():
    """A top-level list yields bracketed paths, nested containers included."""
    assert translate_checker.flatten_keys(['a', ['b'], {'c': 1}]) == {'[0]', '[1][0]', '[2].c'}
    assert translate_checker.flatten_keys('scalar') == set()
