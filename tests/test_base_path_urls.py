"""Guard: frontend URLs must survive being served under a sub-path (Home Assistant ingress).

Under ingress the app lives at ``/api/hassio_ingress/<token>/``. A root-absolute URL such as
``'/api/...'`` or ``'/static/...'`` handed to the browser escapes that prefix and hits Home
Assistant itself, and CI never runs under a prefix, so a regression would only show up on a
real HA install. These scans fail as soon as a new unprefixed URL appears:

- JS: a root-absolute literal must be passed to ``fetch()`` / ``fetchJSON*()`` /
  ``fetchWithRetry()`` (``api_helper.js`` prefixes those) or wrapped in ``appUrl()``.
- Templates: ``src`` / ``href`` / ``action`` attributes start with ``{{ base }}``.
- CSS: ``url()`` is relative to the stylesheet.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "static" / "js"
CSS_DIR = ROOT / "static" / "css"
TEMPLATES_DIR = ROOT / "templates"

# Defines appUrl()/resolveEndpoint() themselves
_JS_EXEMPT = {"api_helper.js"}

_ROOT_LITERAL = re.compile(r"""['"`]/(?:api|static)/|['"`]/(?:login|offline\.html|sw\.js)['"`?]""")
_NAVIGATION_TO_ROOT = re.compile(r"""location\.(?:href\s*=|replace\(|assign\()\s*['"`]/""")
# Prefixed on the way out, or only compared against (pathname.includes('/login') holds under a prefix too)
_SAFE = re.compile(
    r"""\bappUrl\(|\b(?:fetch|fetchJSON\w*|fetchWithRetry)\(|\$\{API_BASE\}|\.(?:includes|startsWith|endsWith)\("""
)
_COMMENT = re.compile(r"^\s*(?://|/?\*)")

_TEMPLATE_ATTR = re.compile(r"""\b(?:src|href|action)="/""")
_CSS_ROOT_URL = re.compile(r"""url\(\s*['"]?/""")


def _js_files():
    return sorted(p for p in JS_DIR.rglob("*.js") if not p.name.endswith(".min.js") and p.name not in _JS_EXEMPT)


@pytest.mark.unit
def test_js_has_no_unprefixed_root_urls():
    """Every root-absolute app URL in static/js goes through fetch() or appUrl()."""
    offenders = []
    for path in _js_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _COMMENT.match(line):
                continue
            if (_ROOT_LITERAL.search(line) or _NAVIGATION_TO_ROOT.search(line)) and not _SAFE.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    assert (
        not offenders
    ), "Root-absolute URLs that break under a sub-path (HA ingress); wrap them in appUrl():\n" + "\n".join(offenders)


@pytest.mark.unit
def test_templates_prefix_their_urls():
    """Template src/href/action attributes carry the {{ base }} prefix (the PWA manifest links excepted)."""
    offenders = []
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # The manifest is only linked when base is empty (no PWA under a prefix)
            if _TEMPLATE_ATTR.search(line) and 'rel="manifest"' not in line:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "Template URLs missing the {{ base }} prefix:\n" + "\n".join(offenders)


@pytest.mark.unit
def test_css_urls_are_relative():
    """Stylesheet url()s are relative to the CSS file, which works with and without a prefix."""
    offenders = []
    for path in sorted(CSS_DIR.glob("*.css")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _CSS_ROOT_URL.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "Root-absolute url() in CSS (use ../img/..., ../vendor/...):\n" + "\n".join(offenders)
