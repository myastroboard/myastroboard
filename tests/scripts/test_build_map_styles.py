"""Tests for scripts/build_map_styles.py: localized and night vision basemap styles."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location('build_map_styles', ROOT / 'scripts' / 'build_map_styles.py')
build_map_styles = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_map_styles)


def _style():
    """A small VersaTiles-shaped style."""
    return {
        'version': 8,
        'name': 'versatiles-eclipse',
        'sources': {
            'versatiles-shortbread': {
                'type': 'vector',
                'url': 'https://tiles.versatiles.org/tiles/osm.json',
                'tiles': ['https://tiles.versatiles.org/tiles/osm/{z}/{x}/{y}'],
            }
        },
        'glyphs': 'https://tiles.versatiles.org/assets/glyphs/{fontstack}/{range}.pbf',
        'sprite': [{'id': 'basics', 'url': 'https://tiles.versatiles.org/assets/sprites/basics/sprites'}],
        'layers': [
            {'id': 'background', 'type': 'background', 'paint': {'background-color': '#ffffff'}},
            {
                'id': 'water',
                'type': 'fill',
                'paint': {
                    'fill-color': ['interpolate', ['linear'], ['zoom'], 5, 'rgb(0,0,0)', 10, 'hsla(0,0%,100%,0.5)'],
                    'fill-pattern': 'hatch',
                    'fill-opacity': 0.8,
                },
            },
            {'id': 'label-place-town', 'type': 'symbol', 'minzoom': 9, 'layout': {}},
            {'id': 'label-place-village', 'type': 'symbol', 'minzoom': 11},
            {'id': 'empty-paint', 'type': 'line', 'paint': {}},
            {'id': 'road', 'type': 'line', 'paint': {'line-color': {'stops': [[5, '#000']]}, 'line-width': 2}},
        ],
    }


@pytest.mark.unit
def test_localize_points_every_url_at_the_proxy():
    """Tiles, glyphs and sprites go through the placeholder origin; town and village labels show earlier."""
    style = build_map_styles.localize(_style(), 'dark')
    source = style['sources']['versatiles-shortbread']
    assert source['tiles'] == [build_map_styles.TILES_URL]
    assert 'url' not in source
    assert source['attribution'] == build_map_styles.ATTRIBUTION
    assert style['glyphs'] == build_map_styles.GLYPHS_URL
    assert style['sprite'] == [{'id': 'basics', 'url': build_map_styles.SPRITE_URL}]
    assert style['name'] == 'MyAstroBoard dark'
    minzooms = {layer['id']: layer.get('minzoom') for layer in style['layers']}
    assert minzooms['label-place-town'] == 8
    assert minzooms['label-place-village'] == 10
    assert 'versatiles.org' not in json.dumps(style)


@pytest.mark.unit
def test_localize_rejects_unexpected_sources():
    """A style with another tile source would leak requests to a third party, so it is refused."""
    style = _style()
    style['sources']['other'] = {'type': 'raster'}
    with pytest.raises(ValueError, match='Unexpected sources in the light style'):
        build_map_styles.localize(style, 'light')


@pytest.mark.unit
@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('#fff', (255, 255, 255, 1.0)),
        ('#f008', (255, 0, 0, 0x88 / 255)),
        ('#336699', (0x33, 0x66, 0x99, 1.0)),
        ('#33669980', (0x33, 0x66, 0x99, 0x80 / 255)),
        ('rgb(10, 20, 30)', (10.0, 20.0, 30.0, 1.0)),
        ('rgba(10,20,30,0.25)', (10.0, 20.0, 30.0, 0.25)),
        ('hsl(0, 100%, 50%)', (255.0, 0.0, 0.0, 1.0)),
        ('hsla(120,100%,50%,0.5)', (0.0, 255.0, 0.0, 0.5)),
        (' #000 ', (0, 0, 0, 1.0)),
    ],
)
def test_parse_color_reads_every_css_form(value, expected):
    """Hex (3, 4, 6, 8 digits), rgb(a) and hsl(a) all parse to 0-255 channels and an alpha."""
    assert build_map_styles.parse_color(value) == pytest.approx(expected)


@pytest.mark.unit
@pytest.mark.parametrize('value', ['red', 'interpolate', '#12', 'var(--x)'])
def test_parse_color_rejects_other_strings(value):
    """Named colors and expression operators are not parsed."""
    assert build_map_styles.parse_color(value) is None


@pytest.mark.unit
def test_to_red_keeps_brightness_and_alpha_under_the_cap():
    """White maps to the capped red, black stays black, alpha is kept; non-colors pass through."""
    assert build_map_styles.to_red('#ffffff') == 'rgba(190,19,11,1.0)'
    assert build_map_styles.to_red('rgba(0,0,0,0.5)') == 'rgba(0,0,0,0.5)'
    assert build_map_styles.to_red('linear') == 'linear'
    dim = build_map_styles.parse_color(build_map_styles.to_red('#808080'))
    assert 0 < dim[0] < build_map_styles.RED_MAX
    assert dim[1] < dim[0] * 0.2 and dim[2] < dim[0] * 0.2


@pytest.mark.unit
def test_make_red_recolors_paint_colors_only():
    """Every *-color paint value (inside expressions too) turns red; patterns go; the source is untouched."""
    source = build_map_styles.localize(_style(), 'dark')
    red = build_map_styles.make_red(source)
    assert red['name'] == 'MyAstroBoard red'
    assert red['layers'][0]['paint']['background-color'] == 'rgba(190,19,11,1.0)'
    water = red['layers'][1]['paint']
    assert water['fill-color'] == ['interpolate', ['linear'], ['zoom'], 5, 'rgba(0,0,0,1.0)', 10, 'rgba(190,19,11,0.5)']
    assert 'fill-pattern' not in water
    assert water['fill-opacity'] == 0.8
    assert red['layers'][5]['paint'] == {'line-color': {'stops': [[5, 'rgba(0,0,0,1.0)']]}, 'line-width': 2}
    assert source['layers'][1]['paint']['fill-pattern'] == 'hatch'
    assert source['layers'][0]['paint']['background-color'] == '#ffffff'


@pytest.mark.unit
def test_fetch_style_downloads_with_a_user_agent(monkeypatch):
    """The style is fetched from the published URL with the builder's User-Agent and a timeout."""
    calls = []

    class _Response:
        def raise_for_status(self):
            calls.append('checked')

        def json(self):
            return {'ok': True}

    def fake_get(url, headers, timeout):
        calls.append((url, headers['User-Agent'], timeout))
        return _Response()

    monkeypatch.setattr(build_map_styles.requests, 'get', fake_get)
    assert build_map_styles.fetch_style('eclipse') == {'ok': True}
    assert calls == [(f'{build_map_styles.STYLE_BASE_URL}/eclipse.json', build_map_styles.USER_AGENT, 30), 'checked']


@pytest.mark.unit
def test_main_writes_three_compact_ascii_styles(tmp_path, monkeypatch, capsys):
    """main() writes light, dark and red styles as one-line ASCII JSON in the output folder."""
    out_dir = tmp_path / 'map-styles'
    monkeypatch.setattr(build_map_styles, 'ROOT_DIR', str(tmp_path))
    monkeypatch.setattr(build_map_styles, 'OUTPUT_DIR', str(out_dir))
    fetched = []

    def fake_fetch(name):
        fetched.append(name)
        style = _style()
        style['layers'][0]['paint']['background-color'] = '#000000' if name == 'eclipse' else '#ffffff'
        style['metadata'] = {'note': 'caf' + chr(0xE9)}
        return style

    monkeypatch.setattr(build_map_styles, 'fetch_style', fake_fetch)
    assert build_map_styles.main() == 0
    assert fetched == ['colorful', 'eclipse']
    assert sorted(path.name for path in out_dir.iterdir()) == ['dark.json', 'light.json', 'red.json']
    for path in out_dir.iterdir():
        raw = path.read_bytes()
        assert raw.isascii()
        assert raw.count(b'\n') == 1
    red = json.loads((out_dir / 'red.json').read_text(encoding='utf-8'))
    assert red['layers'][0]['paint']['background-color'] == 'rgba(0,0,0,1.0)'
    assert 'red: 6 layers' in capsys.readouterr().out
