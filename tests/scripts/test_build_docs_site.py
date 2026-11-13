"""Tests for scripts/build_docs_site.py: the adaptation of docs/*.md for the documentation site."""

import importlib.util
import re
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
