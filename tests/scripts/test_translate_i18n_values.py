"""Tests for scripts/translate_i18n_values.py: machine translation that keeps placeholders and terms."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Import the script with a stand-in 'translators' package: the real one may go online on import."""
    fake = types.ModuleType('translators')
    fake.translate_text = lambda *args, **kwargs: pytest.fail('translate_text must be patched in tests')
    saved = sys.modules.get('translators')
    sys.modules['translators'] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            'translate_i18n_values', ROOT / 'scripts' / 'translate_i18n_values.py'
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            del sys.modules['translators']
        else:
            sys.modules['translators'] = saved
    return module


translate_i18n_values = _load()


@pytest.fixture
def translator(monkeypatch):
    """A fake translator that wraps the text it receives, and records each call; no throttle delay."""
    calls = []

    def fake_translate_text(text, translator, from_language, to_language):
        calls.append({'text': text, 'translator': translator, 'from': from_language, 'to': to_language})
        return f'[{to_language}] {text} !'

    monkeypatch.setattr(translate_i18n_values.ts, 'translate_text', fake_translate_text)
    monkeypatch.setattr(translate_i18n_values.time, 'sleep', lambda _seconds: None)
    return calls


@pytest.mark.unit
def test_protect_and_restore_round_trip():
    """Placeholders and protected terms become tokens, and restoring gives the original text back."""
    text = 'Open {count} DSO in SkyTonight for {name}'
    protected, mapping = translate_i18n_values.protect_segments(text)
    assert '{count}' not in protected and 'SkyTonight' not in protected and 'DSO' not in protected
    assert mapping['__PH_0__'] == '{count}'
    assert mapping['__PH_1__'] == '{name}'
    assert translate_i18n_values.restore_segments(protected, mapping) == text


@pytest.mark.unit
def test_longer_terms_are_protected_before_their_parts():
    """'HMS/DMS' is kept whole rather than having its 'DMS' part tokenized on its own."""
    protected, mapping = translate_i18n_values.protect_segments('Use HMS/DMS')
    assert list(mapping.values()) == ['HMS/DMS']
    assert protected == 'Use __TM_0__'


@pytest.mark.unit
@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('', False),
        ('   ', False),
        ('NNE', False),
        ('N/A', False),
        ('km', False),
        ('arcsec/pixel', False),
        ('Orion', False),
        ('Ursa Major', False),
        ('Jupiter', False),
        ('Clear sky tonight', True),
        ('Moon', True),
        ('inches', True),
    ],
)
def test_needs_translation_skips_neutral_values(value, expected):
    """Blank values, short codes, units, planets and constellations stay as written."""
    assert translate_i18n_values.needs_translation(value, 'de') is expected


@pytest.mark.unit
def test_translate_value_restores_placeholders_and_tidies_spacing(translator):
    """The translator sees tokens, never placeholders or terms; spaces before punctuation are removed."""
    result = translate_i18n_values.translate_value('Sync {count} targets to Astrodex', 'es')
    assert result == '[es] Sync {count} targets to Astrodex!'
    assert '{count}' not in translator[0]['text']
    assert 'Astrodex' not in translator[0]['text']
    assert translator[0]['translator'] == 'google'
    assert (translator[0]['from'], translator[0]['to']) == ('en', 'es')


@pytest.mark.unit
def test_translate_value_does_not_call_the_service_for_neutral_values(translator):
    """A value that needs no translation is returned without a request."""
    assert translate_i18n_values.translate_value('Cassiopeia', 'it') == 'Cassiopeia'
    assert translator == []


@pytest.mark.unit
def test_translate_node_walks_structures_and_counts(translator):
    """Dicts and lists are walked, non-strings kept, and each string counted as translated or kept."""
    stats = {'translated': 0, 'kept': 0, 'failed': 0}
    node = {'title': 'Weather', 'list': ['Cloud cover', 'Mars'], 'count': 3, 'flag': None}
    result = translate_i18n_values.translate_node(node, 'pt', stats)
    assert result == {'title': '[pt] Weather!', 'list': ['[pt] Cloud cover!', 'Mars'], 'count': 3, 'flag': None}
    assert stats == {'translated': 2, 'kept': 1, 'failed': 0}


@pytest.mark.unit
def test_translate_node_keeps_the_english_text_when_the_service_fails(monkeypatch):
    """A failed request keeps the source value and is counted as failed."""

    def broken(*_args, **_kwargs):
        raise RuntimeError('quota exceeded')

    monkeypatch.setattr(translate_i18n_values.ts, 'translate_text', broken)
    stats = {'translated': 0, 'kept': 0, 'failed': 0}
    assert translate_i18n_values.translate_node('Good seeing', 'de', stats) == 'Good seeing'
    assert stats == {'translated': 0, 'kept': 0, 'failed': 1}


@pytest.mark.unit
def test_main_writes_the_target_language_file(tmp_path, monkeypatch, translator, capsys):
    """main() translates en.json into <lang>.json next to it, as indented UTF-8 JSON."""
    source = tmp_path / 'en.json'
    source.write_text(json.dumps({'a': {'b': 'Night sky', 'c': 'NE'}}), encoding='utf-8')
    monkeypatch.setattr(translate_i18n_values, 'I18N_DIR', tmp_path)
    monkeypatch.setattr(translate_i18n_values, 'SOURCE_FILE', source)
    monkeypatch.setattr('sys.argv', ['translate_i18n_values.py', '--lang', 'de'])
    translate_i18n_values.main()
    written = (tmp_path / 'de.json').read_text(encoding='utf-8')
    assert json.loads(written) == {'a': {'b': '[de] Night sky!', 'c': 'NE'}}
    assert written.startswith('{\n  "a"') and written.endswith('}\n')
    assert 'stats: translated=1 kept=1 failed=0' in capsys.readouterr().out


@pytest.mark.unit
def test_main_rejects_an_unknown_language(monkeypatch):
    """Only the languages the script knows are accepted."""
    monkeypatch.setattr('sys.argv', ['translate_i18n_values.py', '--lang', 'xx'])
    with pytest.raises(SystemExit):
        translate_i18n_values.main()
