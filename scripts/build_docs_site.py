"""Build the documentation site (docs.myastroboard.org) from docs/*.md with mdBook.

The Markdown files stay written for GitHub; this script adapts a copy of them for the site:

1. copies docs/ and docs-site/SUMMARY.md into docs-site/build/docs/;
2. turns links that leave docs/ (../CHANGELOG.md, ../backend/...) into GitHub URLs;
3. moves every $...$ and $$...$$ formula into a data-tex attribute, rendered in the browser by the
   bundled KaTeX, so that Markdown never reads the underscores or backslashes of a formula;
4. downloads KaTeX at a pinned version (checked against its npm integrity hash) into the site:
   no asset is loaded from a third party at runtime;
5. runs mdBook, then checks the generated HTML: every internal link and #anchor resolves, and no
   page loads a script, stylesheet, font or image from another host.

Usage:
    python scripts/build_docs_site.py [--mdbook PATH] [--katex-tgz PATH]

mdBook must be on PATH, or given with --mdbook. The site lands in docs-site/build/site/.
"""

import argparse
import base64
import hashlib
import html
import io
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
SITE_SRC = ROOT / 'docs-site'
BUILD = SITE_SRC / 'build'
GITHUB_BLOB = 'https://github.com/myastroboard/myastroboard/blob/main/'

KATEX_VERSION = '0.19.1'
KATEX_URL = f'https://registry.npmjs.org/katex/-/katex-{KATEX_VERSION}.tgz'
KATEX_INTEGRITY = 'sha512-jG8uKntjSEcm2EpQOh0XturpPuuC9r3Sq5HLHdsFdWZT27E672SF19QEi+of0/YeOy15lDgRhKvr5614uRrEfA=='

_FENCE_RE = re.compile(r'^\s*(```|~~~)')
_EXTERNAL_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\((?:https?:)?//[^)\s]+\)')
_LINK_RE = re.compile(r'(\]\()([^)\s]+)(\))')
_INLINE_CODE_RE = re.compile(r'(`+)(.+?)\1')
_DISPLAY_MATH_RE = re.compile(r'^(\s*)\$\$(.+?)\$\$\s*$')
_INLINE_MATH_RE = re.compile(r'(?<![\\$\w])\$(?=[^\s$])([^$\n]+?)(?<=[^\s\\])\$(?![\w$])')


def _tex_attr(tex):
    """A formula as an HTML attribute value; "|" is escaped too so a formula never splits a table."""
    return html.escape(tex.strip(), quote=True).replace('|', '&#124;')


def _rewrite_link(target, page):
    """GitHub URL for a link that leaves docs/, the link unchanged otherwise."""
    if re.match(r'^[a-z][a-z0-9+.-]*:', target, re.I) or target.startswith('#'):
        return target
    path_part, hash_sign, anchor = target.partition('#')
    resolved = (page.parent / path_part).resolve()
    try:
        resolved.relative_to(DOCS)
        return target
    except ValueError:
        relative = resolved.relative_to(ROOT).as_posix()
        return GITHUB_BLOB + relative + (hash_sign + anchor if hash_sign else '')


def _convert_inline(text, page):
    """Rewrite links and inline formulas in one line, leaving inline code untouched."""
    parts = []
    last = 0
    for match in _INLINE_CODE_RE.finditer(text):
        parts.append(('text', text[last : match.start()]))
        parts.append(('code', match.group(0)))
        last = match.end()
    parts.append(('text', text[last:]))
    out = []
    for kind, chunk in parts:
        if kind == 'text':
            # An image from another host (a badge) becomes its alt text: the site loads nothing from third parties.
            chunk = _EXTERNAL_IMAGE_RE.sub(lambda m: m.group(1), chunk)
            chunk = _LINK_RE.sub(lambda m: m.group(1) + _rewrite_link(m.group(2), page) + m.group(3), chunk)
            chunk = _INLINE_MATH_RE.sub(
                lambda m: f'<span class="math" data-tex="{_tex_attr(m.group(1))}"></span>', chunk
            )
        out.append(chunk)
    return ''.join(out)


def convert_page(text, page):
    """Adapt one Markdown page for the site (links leaving docs/, formulas)."""
    lines = text.split('\n')
    out = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        display = _DISPLAY_MATH_RE.match(line)
        if display:
            indent, tex = display.groups()
            # A blank line on each side makes the <div> its own HTML block, kept as is by Markdown.
            out.extend(['', f'{indent}<div class="math-display" data-tex="{_tex_attr(tex)}"></div>', ''])
            continue
        out.append(_convert_inline(line, page))
    return '\n'.join(out)


def _katex_archive(local_tgz):
    """KaTeX package archive, downloaded unless a local copy is given, checked against its hash."""
    data = Path(local_tgz).read_bytes() if local_tgz else urllib.request.urlopen(KATEX_URL, timeout=60).read()
    digest = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != KATEX_INTEGRITY:
        sys.exit(f'KaTeX archive does not match the pinned integrity hash ({digest})')
    return data


def install_katex(dest, local_tgz):
    """Extract the KaTeX script, stylesheet and woff2 fonts into dest."""
    with tarfile.open(fileobj=io.BytesIO(_katex_archive(local_tgz)), mode='r:gz') as archive:
        for member in archive.getmembers():
            name = member.name
            if not member.isfile():
                continue
            if name in ('package/dist/katex.min.js', 'package/dist/katex.min.css', 'package/LICENSE') or (
                name.startswith('package/dist/fonts/') and name.endswith('.woff2')
            ):
                source = archive.extractfile(member)
                if source is None:
                    sys.exit(f'KaTeX archive: cannot read {name}')
                target = dest / Path(name).relative_to('package/dist' if name.startswith('package/dist') else 'package')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())


def prepare(katex_tgz):
    """Assemble docs-site/build/ (book.toml, theme, src) from docs/ and docs-site/."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    # Named like the repository folder, so that mdBook's {path} in edit links is docs/<page>.md.
    src = BUILD / 'docs'
    shutil.copytree(DOCS, src)
    for page in src.glob('*.md'):
        original = DOCS / page.name
        page.write_text(convert_page(original.read_text(encoding='utf-8'), original), encoding='utf-8', newline='\n')
    shutil.copy2(SITE_SRC / 'SUMMARY.md', src / 'SUMMARY.md')
    shutil.copy2(SITE_SRC / 'book.toml', BUILD / 'book.toml')
    (BUILD / 'theme').mkdir()
    shutil.copy2(SITE_SRC / 'theme' / 'head.hbs', BUILD / 'theme' / 'head.hbs')
    assets = src / 'assets'
    assets.mkdir()
    for name in ('math.js', 'site.css'):
        shutil.copy2(SITE_SRC / 'theme' / name, assets / name)
    install_katex(assets / 'katex', katex_tgz)


_ATTR_RE = re.compile(r'\b(href|src)="([^"]*)"')
_ID_RE = re.compile(r'\bid="([^"]+)"')
_ASSET_TAG_RE = re.compile(r'<(script|link|img|source|iframe)\b[^>]*>', re.I)


def check_site(site):
    """Problems in the generated HTML: dead internal links or anchors, assets from another host."""
    ids = {page: set(_ID_RE.findall(page.read_text(encoding='utf-8'))) for page in site.rglob('*.html')}
    problems = []
    for page in ids:
        text = page.read_text(encoding='utf-8')
        for match in _ASSET_TAG_RE.finditer(text):
            for _attr, value in _ATTR_RE.findall(match.group(0)):
                if re.match(r'^(https?:)?//', value):
                    problems.append(f'{page.relative_to(site)}: third-party asset {value}')
        for _attr, value in _ATTR_RE.findall(text):
            if re.match(r'^([a-z][a-z0-9+.-]*:|//)', value, re.I) or value.startswith('{{'):
                continue
            path_part, _, anchor = value.partition('#')
            if path_part.startswith('/'):
                target = (site / path_part.lstrip('/')).resolve()
            else:
                target = (page.parent / path_part).resolve() if path_part else page
            if target.is_dir():
                target = target / 'index.html'
            if not target.exists():
                problems.append(f'{page.relative_to(site)}: missing {value}')
            elif anchor and target.suffix == '.html' and anchor not in ids.get(target, set()):
                problems.append(f'{page.relative_to(site)}: no anchor {value}')
    return problems


def main():
    """Build the site, then check it; exit non-zero on any problem."""
    parser = argparse.ArgumentParser(description='Build the documentation site from docs/*.md with mdBook.')
    parser.add_argument('--mdbook', default='mdbook', help='mdBook executable (default: mdbook on PATH)')
    parser.add_argument('--katex-tgz', help='local copy of the KaTeX npm archive instead of downloading it')
    args = parser.parse_args()

    prepare(args.katex_tgz)
    site = BUILD / 'site'
    subprocess.run([args.mdbook, 'build', str(BUILD), '--dest-dir', str(site)], check=True)
    problems = check_site(site.resolve())
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        sys.exit(f'{len(problems)} problem(s) in the generated site')
    print(f'Site built in {site.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
