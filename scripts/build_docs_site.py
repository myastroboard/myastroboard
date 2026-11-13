"""Build the documentation site (docs.myastroboard.org) from docs/*.md with mdBook.

The Markdown files stay written for GitHub; this script adapts a copy of them for the site:

1. copies docs/ and docs-site/SUMMARY.md into docs-site/build/docs/;
2. turns links that leave docs/ (../CHANGELOG.md, ../backend/...) into GitHub URLs;
3. moves every $...$ and $$...$$ formula into a data-tex attribute, rendered in the browser by the
   bundled KaTeX, so that Markdown never reads the underscores or backslashes of a formula;
4. downloads KaTeX at a pinned version (checked against its npm integrity hash) into the site:
   no asset is loaded from a third party at runtime;
5. builds the landing page (docs-site/landing.html, then docs/README.md without its title), adds a
   "last updated" line to each page from its last commit, converts the screenshots to WebP, and
   bundles the logo and the Bootstrap Icons font the application already vendors;
6. runs mdBook, writes sitemap.xml and robots.txt, then checks the generated HTML: every internal
   link and #anchor resolves, and no page loads a script, stylesheet, font or image from another
   host.

The "last updated" dates need the git history: in CI, check out with fetch-depth 0.

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
SITE_URL = 'https://docs.myastroboard.org/'
ICONS = ROOT / 'static' / 'vendor' / 'bootstrap-icons' / 'font'
# Kept as PNG: the link preview image (og:image) of every page.
KEEP_ORIGINAL_IMAGES = {'banner.png'}

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


def landing_page(readme_text, version):
    """Site home page: the landing template, then the docs index without its own title."""
    template = (SITE_SRC / 'landing.html').read_text(encoding='utf-8').replace('{{VERSION}}', version)
    body = re.sub(r'\A\s*# [^\n]*\n', '', readme_text, count=1)
    return template.rstrip() + '\n\n' + body.lstrip()


def rewrite_images(text, converted):
    """Point img/<name>.png|gif references to the WebP copy made for the site."""
    return re.sub(
        r'(img/)([\w.-]+?)\.(png|gif)\b',
        lambda m: f'{m.group(1)}{m.group(2)}.webp' if f'{m.group(2)}.{m.group(3)}' in converted else m.group(0),
        text,
    )


def convert_images(img_dir):
    """Replace the PNG / GIF screenshots by WebP (animated for a GIF); return the converted names."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit('Pillow is required to build the site (pip install Pillow)')
    converted = set()
    for path in sorted(img_dir.iterdir()):
        if path.suffix.lower() not in ('.png', '.gif') or path.name in KEEP_ORIGINAL_IMAGES:
            continue
        with Image.open(path) as image:
            target = path.with_suffix('.webp')
            if getattr(image, 'is_animated', False):
                image.save(target, 'WEBP', save_all=True, quality=70, method=4)
            else:
                image.save(target, 'WEBP', quality=85, method=6)
        path.unlink()
        converted.add(path.name)
    return converted


def last_updated(page):
    """Date (YYYY-MM-DD) of the last commit that changed a docs page, or None outside a git checkout."""
    result = subprocess.run(
        ['git', 'log', '-1', '--format=%cs', '--', page.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def prepare(katex_tgz):
    """Assemble docs-site/build/ (book.toml, theme, pages, assets) from docs/ and docs-site/."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    # Named like the repository folder, so that mdBook's {path} in edit links is docs/<page>.md.
    src = BUILD / 'docs'
    shutil.copytree(DOCS, src)
    converted = convert_images(src / 'img')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    for page in src.glob('*.md'):
        original = DOCS / page.name
        text = original.read_text(encoding='utf-8')
        if page.name == 'README.md':
            text = landing_page(text, version)
        else:
            updated = last_updated(original)
            if updated:
                text = text.rstrip() + f'\n\n<p class="mab-updated">Last updated {updated}</p>\n'
        page.write_text(rewrite_images(convert_page(text, original), converted), encoding='utf-8', newline='\n')
    shutil.copy2(SITE_SRC / 'SUMMARY.md', src / 'SUMMARY.md')
    shutil.copy2(SITE_SRC / '404.md', src / '404.md')
    shutil.copy2(SITE_SRC / 'book.toml', BUILD / 'book.toml')
    theme = BUILD / 'theme'
    theme.mkdir()
    shutil.copy2(SITE_SRC / 'theme' / 'head.hbs', theme / 'head.hbs')
    shutil.copy2(ROOT / 'static' / 'favicon.svg', theme / 'favicon.svg')
    shutil.copy2(ROOT / 'static' / 'ico' / 'android' / 'launchericon-96x96.png', theme / 'favicon.png')
    assets = src / 'assets'
    assets.mkdir()
    for name in ('math.js', 'site.js', 'site.css'):
        shutil.copy2(SITE_SRC / 'theme' / name, assets / name)
    shutil.copy2(ROOT / 'static' / 'favicon.svg', assets / 'logo.svg')
    icons = assets / 'bootstrap-icons'
    (icons / 'fonts').mkdir(parents=True)
    shutil.copy2(ICONS / 'bootstrap-icons.min.css', icons / 'bootstrap-icons.min.css')
    for font in (ICONS / 'fonts').glob('bootstrap-icons.woff*'):
        shutil.copy2(font, icons / 'fonts' / font.name)
    install_katex(assets / 'katex', katex_tgz)


def write_crawler_files(site):
    """sitemap.xml with every page, and a robots.txt pointing to it."""
    skipped = {'404.html', 'print.html', 'toc.html'}
    pages = sorted(p.name for p in site.glob('*.html') if p.name not in skipped)
    urls = ''.join(f'  <url><loc>{SITE_URL}{"" if page == "index.html" else page}</loc></url>\n' for page in pages)
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + '</urlset>\n'
    )
    (site / 'sitemap.xml').write_text(sitemap, encoding='utf-8')
    (site / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n', encoding='utf-8')


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
    write_crawler_files(site)
    problems = check_site(site.resolve())
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        sys.exit(f'{len(problems)} problem(s) in the generated site')
    print(f'Site built in {site.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
