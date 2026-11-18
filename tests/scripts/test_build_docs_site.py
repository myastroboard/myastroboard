"""Tests for scripts/build_docs_site.py: the adaptation of docs/*.md for the documentation site."""

import base64
import hashlib
import importlib.util
import io
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location('build_docs_site', ROOT / 'scripts' / 'build_docs_site.py')
build_docs_site = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_docs_site)

PAGE = ROOT / 'docs' / 'EXAMPLE.md'


@pytest.mark.unit
def test_every_docs_page_is_in_the_site_menu():
    """Each docs/*.md page is listed in docs-site/SUMMARY.md: mdBook does not publish the others."""
    summary = (ROOT / 'docs-site' / 'SUMMARY.md').read_text(encoding='utf-8')
    listed = set(re.findall(r'\]\(([^)]+\.md)\)', summary))
    pages = {path.name for path in (ROOT / 'docs').glob('*.md')}
    assert sorted(pages - listed) == []
    assert sorted(listed - pages) == []


@pytest.mark.unit
def test_links_leaving_docs_become_github_urls():
    """A link out of docs/ points to GitHub, keeping its anchor; links inside docs/ stay relative."""
    text = '[a](../CHANGELOG.md#unreleased) [b](SKYTONIGHT.md#scheduler) [c](https://example.org) [d](#top)'
    converted = build_docs_site.convert_page(text, PAGE)
    assert '(https://github.com/myastroboard/myastroboard/blob/main/CHANGELOG.md#unreleased)' in converted
    assert '(SKYTONIGHT.md#scheduler)' in converted
    assert '(https://example.org)' in converted
    assert '(#top)' in converted


@pytest.mark.unit
def test_display_formula_becomes_its_own_html_block():
    """A $$...$$ line becomes a math-display div between blank lines, with the TeX escaped."""
    converted = build_docs_site.convert_page(r'Before' + '\n' + r'$$a_b < \frac{1}{2}$$' + '\n' + 'After', PAGE)
    assert '\n\n<div class="math-display" data-tex="a_b &lt; \\frac{1}{2}"></div>\n\n' in converted


@pytest.mark.unit
def test_inline_formula_is_protected_but_prices_and_code_are_not():
    """$x_1$ becomes a math span; a lone dollar amount and inline code stay as written."""
    converted = build_docs_site.convert_page(r'Rate $S_\text{sky}$ costs $5 and `$HOME` stays', PAGE)
    assert '<span class="math" data-tex="S_\\text{sky}"></span>' in converted
    assert 'costs $5 and `$HOME` stays' in converted


@pytest.mark.unit
def test_fenced_code_is_left_untouched():
    """Nothing inside a fenced code block is converted, dollar signs and links included."""
    block = '```nginx\nreturn 301 https://$server_name$request_uri;\n[x](../README.md)\n```'
    assert build_docs_site.convert_page(block, PAGE) == block


@pytest.mark.unit
def test_external_image_becomes_its_alt_text():
    """A badge hosted elsewhere is replaced by its alt text, keeping the surrounding link."""
    text = '[![Add repository](https://badges.example.org/b.svg)](https://example.org/add)'
    assert build_docs_site.convert_page(text, PAGE) == '[Add repository](https://example.org/add)'


@pytest.mark.unit
def test_formula_pipe_is_escaped_for_tables():
    """A "|" inside a formula is escaped so it cannot split a Markdown table cell."""
    converted = build_docs_site.convert_page(r'| $|x|$ |', PAGE)
    assert 'data-tex="&#124;x&#124;"' in converted


@pytest.mark.unit
def test_landing_page_puts_the_index_after_the_hero_without_its_title():
    """The home page is the landing template (with the version) followed by docs/README.md minus its H1."""
    page = build_docs_site.landing_page('# MyAstroBoard Documentation\n\nIntro text.\n', '9.9.9')
    assert 'v9.9.9' in page
    assert page.index('mab-hero') < page.index('Intro text.')
    assert '# MyAstroBoard Documentation' not in page


@pytest.mark.unit
def test_converted_images_point_to_webp_copies():
    """References to converted screenshots switch to .webp; other images are left alone."""
    text = '![a](img/shot.png) ![b](img/anim.gif) ![c](img/banner.png)'
    assert build_docs_site.rewrite_images(text, {'shot.png', 'anim.gif'}) == (
        '![a](img/shot.webp) ![b](img/anim.webp) ![c](img/banner.png)'
    )


def _katex_tgz(files):
    """An in-memory npm-style archive holding the given {name: bytes} files, plus a directory entry."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        folder = tarfile.TarInfo('package/dist')
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _integrity(data):
    return 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()


@pytest.mark.unit
def test_katex_archive_with_a_wrong_hash_stops_the_build(tmp_path):
    """An archive that does not match the pinned integrity hash is refused."""
    archive = tmp_path / 'katex.tgz'
    archive.write_bytes(b'not katex')
    with pytest.raises(SystemExit, match='does not match the pinned integrity hash'):
        build_docs_site._katex_archive(archive)


@pytest.mark.unit
def test_katex_archive_is_downloaded_when_no_local_copy_is_given(monkeypatch):
    """Without --katex-tgz the pinned npm URL is fetched, and its hash checked."""
    data = b'katex bytes'
    requested = []

    class _Response:
        def read(self):
            return data

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return _Response()

    monkeypatch.setattr(build_docs_site.urllib.request, 'urlopen', fake_urlopen)
    monkeypatch.setattr(build_docs_site, 'KATEX_INTEGRITY', _integrity(data))
    assert build_docs_site._katex_archive(None) == data
    assert requested == [(build_docs_site.KATEX_URL, 60)]


@pytest.mark.unit
def test_install_katex_extracts_only_the_needed_files(tmp_path, monkeypatch):
    """The script, stylesheet, license and woff2 fonts are extracted; other files are not."""
    data = _katex_tgz(
        {
            'package/dist/katex.min.js': b'js',
            'package/dist/katex.min.css': b'css',
            'package/LICENSE': b'MIT',
            'package/dist/fonts/KaTeX_Main-Regular.woff2': b'woff2',
            'package/dist/fonts/KaTeX_Main-Regular.ttf': b'ttf',
            'package/dist/katex.js': b'unminified',
            'package/README.md': b'readme',
        }
    )
    archive = tmp_path / 'katex.tgz'
    archive.write_bytes(data)
    monkeypatch.setattr(build_docs_site, 'KATEX_INTEGRITY', _integrity(data))
    dest = tmp_path / 'katex'
    build_docs_site.install_katex(dest, archive)
    extracted = sorted(path.relative_to(dest).as_posix() for path in dest.rglob('*') if path.is_file())
    assert extracted == ['LICENSE', 'fonts/KaTeX_Main-Regular.woff2', 'katex.min.css', 'katex.min.js']
    assert (dest / 'katex.min.js').read_bytes() == b'js'


@pytest.mark.unit
def test_install_katex_stops_on_a_file_it_cannot_read(tmp_path, monkeypatch):
    """A needed file the archive cannot hand back stops the build instead of shipping without it."""
    data = _katex_tgz({'package/dist/katex.min.js': b'js'})
    archive = tmp_path / 'katex.tgz'
    archive.write_bytes(data)
    monkeypatch.setattr(build_docs_site, 'KATEX_INTEGRITY', _integrity(data))
    monkeypatch.setattr(tarfile.TarFile, 'extractfile', lambda self, member: None)
    with pytest.raises(SystemExit, match='cannot read package/dist/katex.min.js'):
        build_docs_site.install_katex(tmp_path / 'katex', archive)


@pytest.mark.unit
def test_convert_images_needs_pillow(tmp_path, monkeypatch):
    """Without Pillow the build stops with the command that installs it."""
    import sys

    monkeypatch.setitem(sys.modules, 'PIL', None)
    with pytest.raises(SystemExit, match='Pillow is required'):
        build_docs_site.convert_images(tmp_path)


@pytest.mark.unit
def test_convert_images_turns_screenshots_into_webp(tmp_path):
    """PNG and GIF screenshots become WebP (animated GIFs stay animated); the banner and other files stay."""
    from PIL import Image

    Image.new('RGB', (8, 8), 'red').save(tmp_path / 'shot.png')
    frames = [Image.new('RGB', (8, 8), color) for color in ('red', 'blue')]
    frames[0].save(tmp_path / 'anim.gif', save_all=True, append_images=frames[1:], duration=100)
    Image.new('RGB', (8, 8), 'blue').save(tmp_path / 'banner.png')
    (tmp_path / 'notes.txt').write_text('x', encoding='utf-8')

    assert build_docs_site.convert_images(tmp_path) == {'shot.png', 'anim.gif'}
    assert sorted(path.name for path in tmp_path.iterdir()) == ['anim.webp', 'banner.png', 'notes.txt', 'shot.webp']
    with Image.open(tmp_path / 'anim.webp') as animated:
        assert animated.n_frames == 2
    with Image.open(tmp_path / 'shot.webp') as still:
        assert still.format == 'WEBP'


@pytest.mark.unit
def test_last_updated_reads_the_last_commit_date(monkeypatch):
    """The page's last commit date comes from git log; no output (outside git) gives None."""
    outputs = ['2026-11-01\n', '']
    seen = []

    def fake_run(command, **kwargs):
        seen.append((command, kwargs['cwd']))
        return subprocess.CompletedProcess(command, 0, stdout=outputs.pop(0), stderr='')

    monkeypatch.setattr(build_docs_site.subprocess, 'run', fake_run)
    page = build_docs_site.DOCS / 'SKYTONIGHT.md'
    assert build_docs_site.last_updated(page) == '2026-11-01'
    assert build_docs_site.last_updated(page) is None
    assert seen[0] == (['git', 'log', '-1', '--format=%cs', '--', 'docs/SKYTONIGHT.md'], build_docs_site.ROOT)


@pytest.mark.unit
def test_write_crawler_files_lists_pages_but_not_utility_ones(tmp_path):
    """sitemap.xml lists every real page (index as the site root), and robots.txt points to it."""
    for name in ('index.html', 'SKYTONIGHT.html', '404.html', 'print.html', 'toc.html'):
        (tmp_path / name).write_text('', encoding='utf-8')
    build_docs_site.write_crawler_files(tmp_path)
    sitemap = (tmp_path / 'sitemap.xml').read_text(encoding='utf-8')
    site = build_docs_site.SITE_URL
    assert re.findall(r'<loc>([^<]*)</loc>', sitemap) == [f'{site}SKYTONIGHT.html', site]
    assert (tmp_path / 'robots.txt').read_text(encoding='utf-8').endswith(f'Sitemap: {site}sitemap.xml\n')


@pytest.mark.unit
def test_check_site_reports_dead_links_missing_anchors_and_third_party_assets(tmp_path):
    """Internal links and anchors must resolve and assets must be local; external links are fine."""
    (tmp_path / 'guide').mkdir()
    (tmp_path / 'guide' / 'index.html').write_text('<h1 id="intro">Guide</h1>', encoding='utf-8')
    (tmp_path / 'page.html').write_text('<h2 id="good">Good</h2>', encoding='utf-8')
    (tmp_path / 'logo.svg').write_text('<svg/>', encoding='utf-8')
    links = [
        '<a href="page.html#good">ok</a>',
        '<a href="/page.html">absolute</a>',
        '<a href="guide/#intro">folder</a>',
        '<a href="#top">self</a>',
        '<a href="https://example.org">external</a>',
        '<a href="mailto:someone@example.org">mail</a>',
        '<a href="{{ path }}">template</a>',
        '<img src="logo.svg">',
        '<a href="page.html#bad">bad anchor</a>',
        '<a href="missing.html">dead</a>',
        '<script src="https://cdn.example.org/x.js"></script>',
        '<link href="//fonts.example.org/f.css">',
    ]
    (tmp_path / 'index.html').write_text('<p id="top"></p>' + ''.join(links), encoding='utf-8')
    assert sorted(build_docs_site.check_site(tmp_path)) == [
        'index.html: missing missing.html',
        'index.html: no anchor page.html#bad',
        'index.html: third-party asset //fonts.example.org/f.css',
        'index.html: third-party asset https://cdn.example.org/x.js',
    ]


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A minimal repository layout with build_docs_site's paths pointed at it; KaTeX and git are stubbed."""
    from PIL import Image

    docs = tmp_path / 'docs'
    (docs / 'img').mkdir(parents=True)
    (docs / 'README.md').write_text('# Documentation\n\nSee [the guide](GUIDE.md).\n', encoding='utf-8')
    (docs / 'GUIDE.md').write_text('# Guide\n\n![shot](img/shot.png) $x_1$\n', encoding='utf-8')
    (docs / 'OLD.md').write_text('# Old\n', encoding='utf-8')
    Image.new('RGB', (4, 4), 'red').save(docs / 'img' / 'shot.png')
    (tmp_path / 'VERSION').write_text('9.9.9\n', encoding='utf-8')

    site_src = tmp_path / 'docs-site'
    (site_src / 'theme').mkdir(parents=True)
    for name in ('SUMMARY.md', '404.md', 'book.toml'):
        (site_src / name).write_text(name, encoding='utf-8')
    (site_src / 'landing.html').write_text('<div class="mab-hero">v{{VERSION}}</div>\n', encoding='utf-8')
    for name in ('head.hbs', 'math.js', 'site.js', 'site.css'):
        (site_src / 'theme' / name).write_text(name, encoding='utf-8')

    static = tmp_path / 'static'
    (static / 'ico' / 'android').mkdir(parents=True)
    (static / 'favicon.svg').write_text('<svg/>', encoding='utf-8')
    (static / 'ico' / 'android' / 'launchericon-96x96.png').write_bytes(b'png')
    icons = static / 'vendor' / 'bootstrap-icons' / 'font'
    (icons / 'fonts').mkdir(parents=True)
    (icons / 'bootstrap-icons.min.css').write_text('css', encoding='utf-8')
    (icons / 'fonts' / 'bootstrap-icons.woff2').write_bytes(b'woff2')

    build = site_src / 'build'
    (build / 'stale').mkdir(parents=True)
    monkeypatch.setattr(build_docs_site, 'ROOT', tmp_path)
    monkeypatch.setattr(build_docs_site, 'DOCS', docs)
    monkeypatch.setattr(build_docs_site, 'SITE_SRC', site_src)
    monkeypatch.setattr(build_docs_site, 'BUILD', build)
    monkeypatch.setattr(build_docs_site, 'ICONS', icons)
    katex = []
    monkeypatch.setattr(build_docs_site, 'install_katex', lambda dest, tgz: katex.append((dest, tgz)))
    monkeypatch.setattr(build_docs_site, 'last_updated', lambda page: '2026-11-02' if page.name == 'GUIDE.md' else None)
    return {'build': build, 'katex': katex}


@pytest.mark.unit
def test_prepare_assembles_the_build_folder(fake_repo):
    """prepare() rebuilds docs-site/build with adapted pages, theme, assets, icons and KaTeX."""
    build_docs_site.prepare('local.tgz')
    build = fake_repo['build']
    src = build / 'docs'
    assert not (build / 'stale').exists()
    home = (src / 'README.md').read_text(encoding='utf-8')
    assert home.startswith('<div class="mab-hero">v9.9.9</div>')
    assert '# Documentation' not in home
    guide = (src / 'GUIDE.md').read_text(encoding='utf-8')
    assert '![shot](img/shot.webp)' in guide
    assert '<span class="math" data-tex="x_1"></span>' in guide
    assert guide.endswith('<p class="mab-updated">Last updated 2026-11-02</p>\n')
    assert 'mab-updated' not in (src / 'OLD.md').read_text(encoding='utf-8')
    assert sorted(path.name for path in (src / 'img').iterdir()) == ['shot.webp']
    for path in ('book.toml', 'theme/head.hbs', 'theme/favicon.svg', 'theme/favicon.png'):
        assert (build / path).is_file(), path
    for path in ('SUMMARY.md', '404.md', 'assets/math.js', 'assets/site.js', 'assets/site.css', 'assets/logo.svg'):
        assert (src / path).is_file(), path
    icons = src / 'assets' / 'bootstrap-icons'
    assert (icons / 'bootstrap-icons.min.css').is_file()
    assert (icons / 'fonts' / 'bootstrap-icons.woff2').is_file()
    assert fake_repo['katex'] == [(src / 'assets' / 'katex', 'local.tgz')]


def _fake_mdbook(pages):
    """A subprocess.run stand-in for mdBook that writes the given {name: html} pages into --dest-dir."""
    calls = []

    def run(command, check):
        calls.append(command)
        dest = Path(command[command.index('--dest-dir') + 1])
        dest.mkdir(parents=True, exist_ok=True)
        for name, text in pages.items():
            (dest / name).write_text(text, encoding='utf-8')
        return subprocess.CompletedProcess(command, 0)

    return run, calls


@pytest.mark.unit
def test_prepare_works_on_a_first_build(fake_repo):
    """With no build folder yet, there is nothing to clear and the site is assembled all the same."""
    import shutil

    shutil.rmtree(fake_repo['build'])
    build_docs_site.prepare('local.tgz')
    assert (fake_repo['build'] / 'docs' / 'README.md').exists()


@pytest.mark.unit
def test_main_builds_checks_and_reports_a_clean_site(fake_repo, monkeypatch, capsys):
    """main() prepares, runs mdBook with the given executable, writes crawler files and checks the site."""
    run, calls = _fake_mdbook({'index.html': '<a href="GUIDE.html">g</a>', 'GUIDE.html': '<p>g</p>'})
    monkeypatch.setattr(build_docs_site.subprocess, 'run', run)
    monkeypatch.setattr('sys.argv', ['build_docs_site.py', '--mdbook', 'my-mdbook', '--katex-tgz', 'k.tgz'])
    build_docs_site.main()
    site = fake_repo['build'] / 'site'
    assert calls == [['my-mdbook', 'build', str(fake_repo['build']), '--dest-dir', str(site)]]
    assert (site / 'sitemap.xml').is_file()
    assert fake_repo['katex'][0][1] == 'k.tgz'
    assert 'Site built in' in capsys.readouterr().out


@pytest.mark.unit
def test_main_fails_when_the_site_has_problems(fake_repo, monkeypatch, capsys):
    """A dead link in the generated HTML is printed and makes the build exit non-zero."""
    run, _calls = _fake_mdbook({'index.html': '<a href="nowhere.html">x</a>'})
    monkeypatch.setattr(build_docs_site.subprocess, 'run', run)
    monkeypatch.setattr('sys.argv', ['build_docs_site.py'])
    with pytest.raises(SystemExit, match='1 problem'):
        build_docs_site.main()
    assert 'index.html: missing nowhere.html' in capsys.readouterr().err
