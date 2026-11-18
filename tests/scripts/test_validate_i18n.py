"""Tests for scripts/validate_i18n.py: the i18n consistency gate run in CI."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location('validate_i18n', ROOT / 'scripts' / 'validate_i18n.py')
validate_i18n = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validate_i18n)

REFERENCE = {'common': {'hello': 'Hello', 'count': 3, 'items': ['one', {'deep': True}]}}
FRENCH = {'common': {'hello': 'Bonjour', 'count': 3, 'items': ['un', {'deep': False}]}}
BACKEND_SOURCE = "_TRANSLATION_FILENAMES = {\n    'en': 'en.json',\n    'fr': 'fr.json',\n}\n"
INDEX_SOURCE = (
    '<script>var supported = ["fr"];</script>\n'
    '<select><option value="en">English</option><option value="fr">Francais</option></select>\n'
)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A minimal valid project layout (en + fr), with the script's paths pointed at it."""
    i18n = tmp_path / 'static' / 'i18n'
    i18n.mkdir(parents=True)
    (i18n / 'en.json').write_text(json.dumps(REFERENCE, indent=2), encoding='utf-8')
    (i18n / 'fr.json').write_text(json.dumps(FRENCH, indent=2), encoding='utf-8')
    (tmp_path / 'static' / 'manifest.fr.webmanifest').write_text('{}', encoding='utf-8')
    backend = tmp_path / 'i18n_utils.py'
    backend.write_text(BACKEND_SOURCE, encoding='utf-8')
    index = tmp_path / 'index.html'
    index.write_text(INDEX_SOURCE, encoding='utf-8')
    monkeypatch.setattr(validate_i18n, 'I18N_DIR', i18n)
    monkeypatch.setattr(validate_i18n, 'BACKEND_FILE', backend)
    monkeypatch.setattr(validate_i18n, 'INDEX_HTML', index)
    monkeypatch.setattr(validate_i18n, 'STATIC_DIR', tmp_path / 'static')
    return tmp_path


def _write_fr(tree, text):
    (tree / 'static' / 'i18n' / 'fr.json').write_text(text, encoding='utf-8')


@pytest.mark.unit
def test_repository_translations_are_consistent(capsys):
    """The real static/i18n files, backend declaration and index.html pass every check."""
    assert validate_i18n.main() == 0
    assert 'i18n validation OK' in capsys.readouterr().out


@pytest.mark.unit
def test_valid_tree_passes(tree, capsys):
    """A consistent layout reports OK with its language list."""
    assert validate_i18n.main() == 0
    assert "2 language(s): ['en', 'fr']" in capsys.readouterr().out


@pytest.mark.unit
def test_no_translation_files_is_an_error(tree, capsys):
    """An empty i18n folder fails straight away."""
    for path in (tree / 'static' / 'i18n').glob('*.json'):
        path.unlink()
    assert validate_i18n.main() == 1
    assert 'No i18n JSON files' in capsys.readouterr().out


@pytest.mark.unit
def test_language_missing_from_every_declaration_is_reported(tree, capsys):
    """A new language file without backend, selector, supported-array and manifest entries fails four times."""
    (tree / 'static' / 'i18n' / 'de.json').write_text(json.dumps(FRENCH, indent=2), encoding='utf-8')
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert '[de] Not declared in _TRANSLATION_FILENAMES' in out
    assert '[de] Missing <option value="de">' in out
    assert '[de] Webmanifest file not found: static/manifest.de.webmanifest' in out
    assert "[de] Not listed in 'var supported = [...]'" in out
    assert '4 error(s) found' in out


@pytest.mark.unit
def test_missing_backend_and_template_files_are_reported(tree, capsys):
    """Without the backend module and index.html, both are reported and their checks are skipped."""
    validate_i18n.BACKEND_FILE.unlink()
    validate_i18n.INDEX_HTML.unlink()
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert 'Backend file not found' in out
    assert 'Template not found' in out
    assert '2 error(s) found' in out


@pytest.mark.unit
def test_unparsable_backend_and_template_are_reported(tree, capsys):
    """A backend without _TRANSLATION_FILENAMES and a template without the supported array both fail."""
    validate_i18n.BACKEND_FILE.write_text('LANGS = []\n', encoding='utf-8')
    validate_i18n.INDEX_HTML.write_text('<option value="en"></option><option value="fr"></option>', encoding='utf-8')
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert 'Could not parse _TRANSLATION_FILENAMES' in out
    assert "Could not find 'var supported = [...]'" in out


@pytest.mark.unit
def test_missing_reference_file_is_reported(tree, capsys):
    """Without en.json there is no reference, so the key checks cannot run."""
    (tree / 'static' / 'i18n' / 'en.json').unlink()
    assert validate_i18n.main() == 1
    assert 'Reference translation file not found' in capsys.readouterr().out


@pytest.mark.unit
def test_unparsable_reference_file_is_reported(tree, capsys):
    """A broken en.json is reported, and the per-language key checks are skipped."""
    (tree / 'static' / 'i18n' / 'en.json').write_text('{"common": ', encoding='utf-8')
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert '[en] Could not load reference file' in out
    assert 'Missing translation key' not in out


@pytest.mark.unit
def test_unparsable_translation_file_is_reported(tree, capsys):
    """A broken translated file is reported once, as a parse error."""
    _write_fr(tree, '{"common": {"hello": ')
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert '[fr] Could not parse translation file' in out
    assert '1 error(s) found' in out


@pytest.mark.unit
def test_unreadable_translation_file_is_reported(tree, capsys):
    """A language entry that cannot be read is reported and its content checks are skipped."""
    (tree / 'static' / 'i18n' / 'fr.json').unlink()
    (tree / 'static' / 'i18n' / 'fr.json').mkdir()
    assert validate_i18n.main() == 1
    assert '[fr] Could not read file' in capsys.readouterr().out


@pytest.mark.unit
def test_key_mismatches_are_reported(tree, capsys):
    """Missing keys, extra keys and leaf type changes against en.json are each reported."""
    broken = {'common': {'count': '3', 'items': ['un', {'deep': False}], 'orphan': 'x'}}
    _write_fr(tree, json.dumps(broken, indent=2))
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    assert "[fr] Missing translation key: 'common.hello'" in out
    assert "[fr] Extra key not in reference: 'common.orphan'" in out
    assert "[fr] Type mismatch at 'common.count': expected int, got str" in out


@pytest.mark.unit
def test_duplicate_keys_are_reported(tree, capsys):
    """A key repeated inside one object is reported even though JSON parsing keeps the last one."""
    _write_fr(tree, json.dumps(FRENCH, indent=2).replace('"hello": "Bonjour",', '"hello": "A",\n"hello": "B",'))
    assert validate_i18n.main() == 1
    assert "[fr] Duplicate key: 'hello'" in capsys.readouterr().out


@pytest.mark.unit
def test_inline_objects_are_reported_and_long_lines_truncated(tree, capsys):
    """An object opened and closed on one line is reported, its snippet cut to the maximum length."""
    long_value = 'x' * 150
    text = '{\n  "common": {"hello": "' + long_value + '", "count": 3, "items": ["un", {"deep": false}]}\n}'
    _write_fr(tree, text)
    assert validate_i18n.main() == 1
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if 'Inline object on line 2' in line)
    snippet = line.split('Inline object on line 2: ', 1)[1]
    assert len(snippet) == validate_i18n.MAX_SNIPPET_LENGTH
    assert snippet.endswith('...')


@pytest.mark.unit
def test_html_entities_are_reported(tree, capsys):
    """An HTML entity in a value is reported with its key path, in any language."""
    _write_fr(tree, json.dumps({**FRENCH, 'common': {**FRENCH['common'], 'hello': 'Tom &amp; Jerry'}}, indent=2))
    assert validate_i18n.main() == 1
    assert "[fr] HTML entity in value at 'common.hello'" in capsys.readouterr().out


@pytest.mark.unit
def test_flatten_keys_and_leaf_types_walk_lists():
    """Nested lists produce indexed paths, also for a top-level list."""
    data = {'a': [1, {'b': 'x'}, [True]]}
    assert validate_i18n.flatten_keys(data) == {'a[0]', 'a[1].b', 'a[2][0]'}
    assert validate_i18n.get_leaf_types(data) == {'a[0]': 'int', 'a[1].b': 'str', 'a[2][0]': 'bool'}
    assert validate_i18n.flatten_keys(['x', ['y']]) == {'[0]', '[1][0]'}
    assert validate_i18n.get_leaf_types(['x', {'k': None}]) == {'[0]': 'str', '[1].k': 'NoneType'}


@pytest.mark.unit
def test_find_html_entities_covers_named_numeric_and_hex_forms():
    """Named, decimal and hex entities are found, inside lists too; a bare ampersand is fine."""
    data = {'a': 'R&D', 'b': ['&lt;', 'ok'], 'c': {'d': '&#169;', 'e': '&#x27;'}}
    assert sorted(validate_i18n.find_html_entities(data)) == ['b[0]', 'c.d', 'c.e']


@pytest.mark.unit
def test_find_duplicate_keys_ignores_invalid_json():
    """Unparsable text yields no duplicates; parse errors are reported elsewhere."""
    assert validate_i18n.find_duplicate_keys('{"a": ') == []
    assert validate_i18n.find_duplicate_keys('{"a": {"b": 1, "b": 2}, "a": 3}') == ['b', 'a']


@pytest.mark.unit
def test_find_inline_objects_ignores_colons_and_braces_inside_strings():
    """Only a real one-line object value counts, not punctuation inside strings or a multi-line object."""
    text = '\n'.join(
        [
            '{',
            '  "time": "at 10:30 {x}",',
            '  "escaped": "say \\"a: {b}\\"",',
            '  "open": {',
            '    "k": "v"',
            '  },',
            '  "inline": {"k": "}{ \\" x"}',
            '}',
        ]
    )
    assert validate_i18n.find_inline_objects(text) == [(7, '"inline": {"k": "}{ \\" x"}')]


@pytest.mark.unit
def test_html_parsers_extract_language_codes():
    """Language codes with region subtags are read from the backend dict, supported array and options."""
    assert validate_i18n.parse_backend_languages('_TRANSLATION_FILENAMES = {"en": "a", "pt-BR": "b"}') == {
        'en',
        'pt-BR',
    }
    assert validate_i18n.parse_html_supported_langs("var supported = ['fr', \"de\"];") == {'fr', 'de'}
    assert validate_i18n.parse_html_selector_langs('<option selected value="it">') == {'it'}


@pytest.mark.unit
def test_a_bare_value_has_no_keys_or_leaves():
    """A value that is neither an object nor a list holds no translation key."""
    assert validate_i18n.flatten_keys('text') == set()
    assert validate_i18n.get_leaf_types(3) == {}


@pytest.mark.unit
def test_empty_reference_and_translation_pass(tree, capsys):
    """An empty reference has no leaf types to compare, and an empty translation matches it."""
    (tree / 'static' / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    _write_fr(tree, '{}')
    assert validate_i18n.main() == 0
    assert 'i18n validation OK' in capsys.readouterr().out
