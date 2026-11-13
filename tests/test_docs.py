"""Documentation checks: internal links, the API route inventory, ASCII punctuation.

The docs drift silently when code moves: a renamed heading breaks every link to its anchor, a new
route never reaches docs/API_ENDPOINTS.md, and a pasted em dash slips past review. These tests turn
each of those into a failure that names the file and the problem.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Pages whose links and punctuation are checked. CHANGELOG.md links are checked too (the What's new
# window renders them), but its released text is history and keeps the punctuation it shipped with.
DOC_FILES = sorted(ROOT.glob('docs/*.md')) + [
    ROOT / name for name in ('README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'DOCKER_HUB.md', 'ROADMAP.md')
]
LINK_CHECKED_FILES = DOC_FILES + [ROOT / 'CHANGELOG.md']

# Characters that look like an ASCII one and break searches and diffs (org standards, section 3),
# plus the arrow and ellipsis characters the docs replace with "->" and "...".
FORBIDDEN_PUNCTUATION = {
    chr(0x2013): 'en dash (use -)',
    chr(0x2014): 'em dash (use -)',
    chr(0x2018): "curly apostrophe (use ')",
    chr(0x2019): "curly apostrophe (use ')",
    chr(0x201C): 'curly quote (use ")',
    chr(0x201D): 'curly quote (use ")',
    chr(0x2026): 'ellipsis character (use ...)',
    chr(0x2192): 'arrow character (use ->)',
    chr(0x2190): 'arrow character (use <-)',
}

_FENCE_RE = re.compile(r'^(```|~~~).*?^\1', re.M | re.S)
_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*#*\s*$', re.M)
_LINK_RE = re.compile(r'\]\(([^)\s]+)\)')
_HTML_ANCHOR_RE = re.compile(r'<a\s+(?:name|id)="([^"]+)"')


def _strip_code(text):
    """Drop fenced code blocks and inline code, where link-like text is not a link."""
    text = _FENCE_RE.sub('', text)
    return re.sub(r'`[^`\n]*`', '', text)


def _github_slug(heading):
    """Anchor GitHub generates for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', heading)  # keep a link's text only
    text = re.sub(r'<[^>]+>', '', text).replace('`', '').lower()
    return ''.join(ch if (ch.isalnum() or ch in '-_') else '-' if ch == ' ' else '' for ch in text)


def _anchors(path):
    """Every anchor a Markdown file defines, duplicates suffixed the way GitHub does."""
    text = _FENCE_RE.sub('', path.read_text(encoding='utf-8'))
    seen = {}
    anchors = set(_HTML_ANCHOR_RE.findall(text))
    for heading in _HEADING_RE.findall(text):
        slug = _github_slug(heading)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f'{slug}-{count}')
    return anchors


def _broken_links(path):
    """Internal links of one file whose target file or anchor does not exist."""
    problems = []
    for target in _LINK_RE.findall(_strip_code(path.read_text(encoding='utf-8'))):
        if re.match(r'^[a-z][a-z0-9+.-]*:', target, re.I):  # http:, https:, mailto:...
            continue
        file_part, _, anchor = target.partition('#')
        dest = (path.parent / file_part).resolve() if file_part else path
        if not dest.exists():
            problems.append(f'{target}: no such file')
        elif anchor and dest.suffix == '.md' and anchor.lower() not in _anchors(dest):
            problems.append(f'{target}: no such heading')
    return problems


@pytest.mark.unit
@pytest.mark.parametrize('path', LINK_CHECKED_FILES, ids=lambda p: p.name)
def test_internal_links_resolve(path):
    """Every relative link points to an existing file, and every #anchor to an existing heading."""
    assert _broken_links(path) == []


@pytest.mark.unit
@pytest.mark.parametrize('path', DOC_FILES, ids=lambda p: p.name)
def test_docs_use_ascii_punctuation(path):
    """Docs use ASCII dashes, apostrophes, quotes, arrows and ellipses, never their look-alikes."""
    found = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        for char, name in FORBIDDEN_PUNCTUATION.items():
            if char in line:
                found.append(f'line {number}: {name}')
    assert found == []


def _normalize_route(path):
    """Route path with its query string dropped and every <param> reduced to <>."""
    return re.sub(r'<[^>]*>', '<>', path.split('?', 1)[0])


def _documented_routes():
    """(method, path) pairs written as `METHOD /path` or `GET|POST /path` in API_ENDPOINTS.md."""
    text = (ROOT / 'docs' / 'API_ENDPOINTS.md').read_text(encoding='utf-8')
    routes = set()
    for methods, path in re.findall(
        r'`((?:GET|POST|PUT|PATCH|DELETE)(?:[|/](?:GET|POST|PUT|PATCH|DELETE))*)\s+(/[^`\s]*)`', text
    ):
        for method in re.split(r'[|/]', methods):
            routes.add((method, _normalize_route(path)))
    return routes


@pytest.mark.unit
def test_every_route_is_in_api_endpoints_doc():
    """Each route the app declares (static files aside) is listed in docs/API_ENDPOINTS.md."""
    from app import app

    documented = _documented_routes()
    missing = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            if (method, _normalize_route(rule.rule)) not in documented:
                missing.append(f'{method} {rule.rule}')
    assert missing == []
