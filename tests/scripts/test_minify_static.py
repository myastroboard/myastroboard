"""Tests for scripts/minify_static.py: the build-time CSS/JS minification of the Docker image."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location('minify_static', ROOT / 'scripts' / 'minify_static.py')
minify_static = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(minify_static)

JS_SOURCE = '// comment\nfunction add(a, b) {\n    return a + b;\n}\n'
CSS_SOURCE = '/* comment */\n.card {\n    color: red;\n    margin: 0px;\n}\n'


@pytest.fixture
def static_tree(tmp_path):
    """A static folder with a script, a stylesheet, an already minified vendor file and an image."""
    root = tmp_path / 'static'
    (root / 'js').mkdir(parents=True)
    (root / 'css').mkdir()
    (root / 'js' / 'app.js').write_text(JS_SOURCE, encoding='utf-8')
    (root / 'css' / 'main.css').write_text(CSS_SOURCE, encoding='utf-8')
    (root / 'js' / 'vendor.min.js').write_text(JS_SOURCE, encoding='utf-8')
    (root / 'logo.svg').write_text('<svg/>', encoding='utf-8')
    return root


@pytest.mark.unit
@pytest.mark.parametrize(
    ('name', 'skipped'),
    [('lib.min.js', True), ('LIB.MIN.CSS', True), ('app.js', False), ('admin.css', False)],
)
def test_should_skip_only_minified_files(name, skipped):
    """Files already named .min.js / .min.css are left alone, whatever their case."""
    assert minify_static.should_skip(Path(name)) is skipped


@pytest.mark.unit
def test_minify_file_rewrites_js_and_css(tmp_path):
    """Comments and whitespace go away, and the file ends with a single newline."""
    js = tmp_path / 'a.js'
    css = tmp_path / 'a.css'
    js.write_text(JS_SOURCE, encoding='utf-8')
    css.write_text(CSS_SOURCE, encoding='utf-8')
    assert minify_static.minify_file(js) is True
    assert minify_static.minify_file(css) is True
    assert js.read_text(encoding='utf-8') == 'function add(a,b){return a+b;}\n'
    assert css.read_text(encoding='utf-8') == '.card{color:red;margin:0}\n'


@pytest.mark.unit
def test_minify_file_leaves_unchanged_empty_and_other_files(tmp_path):
    """Already minimal content, empty files and other extensions are not rewritten."""
    minimal = tmp_path / 'm.css'
    minimal.write_text('.a{color:red}\n', encoding='utf-8')
    empty = tmp_path / 'e.js'
    empty.write_text('// only a comment\n', encoding='utf-8')
    other = tmp_path / 'notes.txt'
    other.write_text('keep   me', encoding='utf-8')
    assert minify_static.minify_file(minimal) is False
    assert minify_static.minify_file(empty) is False
    assert minify_static.minify_file(other) is False
    assert empty.read_text(encoding='utf-8') == '// only a comment\n'
    assert other.read_text(encoding='utf-8') == 'keep   me'


@pytest.mark.unit
def test_minify_tree_counts_processed_and_changed(static_tree):
    """Only non-minified JS and CSS files are processed, recursively."""
    assert minify_static.minify_tree(static_tree) == (2, 2)
    assert minify_static.minify_tree(static_tree) == (2, 0)
    assert (static_tree / 'js' / 'vendor.min.js').read_text(encoding='utf-8') == JS_SOURCE


@pytest.mark.unit
def test_main_copies_to_a_fresh_target(static_tree, tmp_path, monkeypatch, capsys):
    """With a target folder, the source is copied there (replacing any old target) and only the copy shrinks."""
    target = tmp_path / 'build'
    target.mkdir()
    (target / 'stale.js').write_text('old', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['minify_static.py', str(static_tree), str(target)])
    assert minify_static.main() == 0
    assert not (target / 'stale.js').exists()
    assert (target / 'js' / 'app.js').read_text(encoding='utf-8') == 'function add(a,b){return a+b;}\n'
    assert (static_tree / 'js' / 'app.js').read_text(encoding='utf-8') == JS_SOURCE
    assert 'processed=2, changed=2' in capsys.readouterr().out


@pytest.mark.unit
def test_main_minifies_in_place_by_default(static_tree, monkeypatch, capsys):
    """Without a target, the source folder itself is minified."""
    monkeypatch.setattr('sys.argv', ['minify_static.py', str(static_tree)])
    assert minify_static.main() == 0
    assert (static_tree / 'css' / 'main.css').read_text(encoding='utf-8') == '.card{color:red;margin:0}\n'
    assert 'changed=2' in capsys.readouterr().out


@pytest.mark.unit
def test_main_fails_on_missing_source(tmp_path, monkeypatch, capsys):
    """A missing source folder is an error, not an empty build."""
    monkeypatch.setattr('sys.argv', ['minify_static.py', str(tmp_path / 'missing')])
    assert minify_static.main() == 1
    assert '[ERROR] Static directory not found' in capsys.readouterr().out
