"""Build the vector basemap styles served from static/map-styles/.

Downloads the VersaTiles styles published by the OpenStreetMap Foundation for its
Shortbread vector tiles (CC0, https://vector.openstreetmap.org/styles/shortbread/)
and writes three styles for the Leaflet maps:

- light.json: VersaTiles Colorful
- dark.json:  VersaTiles Eclipse
- red.json:   Eclipse recoloured to dim reds only, for the night vision theme

Every URL in the styles (tiles, glyphs, sprites) is rewritten to the server's own
/api/map-tiles proxy under a placeholder origin, which static/js/utils.js swaps for
the real origin at runtime, so the browser never contacts a third party.

Run again after a Shortbread major version (the tile URL embeds the version) or to
pick up style fixes:

    python scripts/build_map_styles.py
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import sys

import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT_DIR, 'static', 'map-styles')

STYLE_BASE_URL = 'https://vector.openstreetmap.org/styles/shortbread'
SOURCE_STYLES = {'light': 'colorful', 'dark': 'eclipse'}
RED_BASE = 'dark'

# Must match _MAP_STYLE_ORIGIN in static/js/utils.js and the routes in backend/blueprints/misc.py
PLACEHOLDER_ORIGIN = 'https://myastroboard.invalid'
TILES_URL = f'{PLACEHOLDER_ORIGIN}/api/map-tiles/vector/{{z}}/{{x}}/{{y}}.mvt'
GLYPHS_URL = f'{PLACEHOLDER_ORIGIN}/api/map-tiles/fonts/{{fontstack}}/{{range}}.pbf'
SPRITE_URL = f'{PLACEHOLDER_ORIGIN}/api/map-tiles/sprites/sprites'

ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
USER_AGENT = 'MyAstroBoard style builder (+https://github.com/myastroboard/myastroboard)'

# Brightest red the night vision style may use, and the green/blue share kept to soften it
RED_MAX = 190
RED_GREEN_RATIO = 0.10
RED_BLUE_RATIO = 0.06

# Place labels one zoom level earlier than VersaTiles does: the minimaps (location cards,
# picture and session locations) show a whole area at MapLibre zoom 8, where the stock styles
# only name regions and cities, which leaves too few landmarks to recognise a site.
LABEL_MINZOOM = {'label-place-town': 8, 'label-place-village': 10}

_COLOR_RE = re.compile(r'^(rgba?|hsla?)\(([^)]*)\)$|^#([0-9a-fA-F]{3,8})$')


def fetch_style(name: str) -> dict:
    """Download one published style."""
    resp = requests.get(f'{STYLE_BASE_URL}/{name}.json', headers={'User-Agent': USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def localize(style: dict, name: str) -> dict:
    """Point every external URL of a style at the server's proxy and apply LABEL_MINZOOM."""
    if set(style['sources']) != {'versatiles-shortbread'}:
        raise ValueError(f'Unexpected sources in the {name} style: {sorted(style["sources"])}')
    source = style['sources']['versatiles-shortbread']
    source['tiles'] = [TILES_URL]
    source['attribution'] = ATTRIBUTION
    source.pop('url', None)
    style['glyphs'] = GLYPHS_URL
    style['sprite'] = [{'id': 'basics', 'url': SPRITE_URL}]
    style['name'] = f'MyAstroBoard {name}'
    for layer in style['layers']:
        if layer['id'] in LABEL_MINZOOM:
            layer['minzoom'] = LABEL_MINZOOM[layer['id']]
    return style


def parse_color(value: str) -> tuple[float, float, float, float] | None:
    """Parse a CSS color used by the styles into (r, g, b, a) with r, g, b in 0-255."""
    match = _COLOR_RE.match(value.strip())
    if not match:
        return None
    func, args, hex_digits = match.groups()
    if hex_digits:
        digits = hex_digits if len(hex_digits) > 4 else ''.join(c * 2 for c in hex_digits)
        r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        a = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return r, g, b, a
    parts = [p.strip() for p in args.split(',')]
    a = float(parts[3]) if len(parts) == 4 else 1.0
    if func.startswith('rgb'):
        r, g, b = (float(p) for p in parts[:3])
        return r, g, b, a
    h = float(parts[0]) / 360
    s = float(parts[1].rstrip('%')) / 100
    lightness = float(parts[2].rstrip('%')) / 100
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return r * 255, g * 255, b * 255, a


def to_red(value: str) -> str:
    """Map a color to a red of the same perceived brightness, capped for night vision."""
    parsed = parse_color(value)
    if parsed is None:
        return value
    r, g, b, a = parsed
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    red = RED_MAX * luminance**0.8
    return f'rgba({round(red)},{round(red * RED_GREEN_RATIO)},{round(red * RED_BLUE_RATIO)},{round(a, 3)})'


def _recolor(node):
    if isinstance(node, str):
        return to_red(node)
    if isinstance(node, list):
        return [_recolor(item) for item in node]
    if isinstance(node, dict):
        return {key: _recolor(value) for key, value in node.items()}
    return node


def make_red(style: dict) -> dict:
    """Recolor every paint color of a style to reds; drop the colored (non-SDF) fill patterns."""
    red = json.loads(json.dumps(style))
    for layer in red['layers']:
        paint = layer.get('paint')
        if not paint:
            continue
        paint.pop('fill-pattern', None)
        for key in list(paint):
            if key.endswith('-color'):
                paint[key] = _recolor(paint[key])
    red['name'] = 'MyAstroBoard red'
    return red


def write_style(variant: str, style: dict) -> str:
    path = os.path.join(OUTPUT_DIR, f'{variant}.json')
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(style, fh, ensure_ascii=True, separators=(',', ':'))
        fh.write('\n')
    return path


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    styles = {}
    for variant, name in SOURCE_STYLES.items():
        styles[variant] = localize(fetch_style(name), variant)
    styles['red'] = make_red(styles[RED_BASE])
    for variant, style in styles.items():
        path = write_style(variant, style)
        print(f'{variant}: {len(style["layers"])} layers -> {os.path.relpath(path, ROOT_DIR)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
