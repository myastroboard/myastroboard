"""Tests for utils.map_tiles: the OpenStreetMap map resources proxy and its on-disk cache."""

import gzip
import os
import time

import pytest
import requests

from utils import map_tiles
from utils.rate_limit import SlidingWindowCounter

PNG = map_tiles._PNG_SIGNATURE + b'tile-body'
# A vector tile starts with field 3 (layers) of the MVT protobuf
MVT = b'\x1a\x05layer-body'


class _FakeRaw:
    def __init__(self, content):
        self._content = content

    def read(self, amount, decode_content=False):
        return self._content[:amount]


class _FakeResponse:
    def __init__(self, status_code=200, content=PNG):
        self.status_code = status_code
        self.raw = _FakeRaw(content)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def tile_env(tmp_path, monkeypatch):
    """Point the cache at a temp dir, give every test a fresh budget, and record upstream calls."""
    monkeypatch.setattr(map_tiles, 'MAP_TILES_CACHE_DIR', str(tmp_path / 'map_tiles'))
    monkeypatch.setattr(map_tiles, '_upstream_budget', SlidingWindowCounter(5, 600))
    monkeypatch.setattr(map_tiles, 'get_repo_version', lambda: '9.9.9')
    calls = []
    state = {'response': _FakeResponse()}

    def fake_get(url, headers=None, timeout=None, stream=False):
        calls.append({'url': url, 'headers': headers, 'timeout': timeout})
        if isinstance(state['response'], Exception):
            raise state['response']
        return state['response']

    monkeypatch.setattr(map_tiles.requests, 'get', fake_get)
    return {'calls': calls, 'state': state, 'dir': tmp_path / 'map_tiles'}


def _raster(z, x, y, user_key='alice'):
    return map_tiles.get_resource(map_tiles.RASTER, {'z': z, 'x': x, 'y': y}, (z, x, f'{y}.png'), user_key)


def _vector(z, x, y, user_key='alice'):
    return map_tiles.get_resource(map_tiles.VECTOR, {'z': z, 'x': x, 'y': y}, (z, x, f'{y}.mvt'), user_key)


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


class TestValidation:
    def test_accepts_tiles_inside_the_pyramid(self):
        """Every tile of a zoom level from 0 to 2^z - 1 on both axes is valid, up to the max zoom."""
        assert map_tiles.is_valid_tile(0, 0, 0)
        assert map_tiles.is_valid_tile(3, 7, 7)
        assert map_tiles.is_valid_tile(map_tiles.RASTER_MAX_ZOOM, 0, 0)

    @pytest.mark.parametrize(
        'z,x,y',
        [(0, 1, 0), (0, 0, 1), (3, 8, 0), (3, 0, 8), (-1, 0, 0), (2, -1, 0), (map_tiles.RASTER_MAX_ZOOM + 1, 0, 0)],
    )
    def test_rejects_tiles_outside_the_pyramid(self, z, x, y):
        """Coordinates past the edge of their zoom level, negative values and too-deep zooms are refused."""
        assert not map_tiles.is_valid_tile(z, x, y)

    def test_vector_tiles_stop_at_their_own_max_zoom(self):
        """Shortbread vector tiles exist up to zoom 14 only."""
        assert map_tiles.is_valid_tile(14, 0, 0, map_tiles.VECTOR_MAX_ZOOM)
        assert not map_tiles.is_valid_tile(15, 0, 0, map_tiles.VECTOR_MAX_ZOOM)

    @pytest.mark.parametrize('glyph_range', ['0-255', '256-511', '65280-65535'])
    def test_accepts_glyph_blocks(self, glyph_range):
        """Glyph blocks are 256 characters long and aligned on 256."""
        assert map_tiles.is_valid_glyph_range(glyph_range)

    @pytest.mark.parametrize('glyph_range', ['0-511', '1-256', '65536-65791', '../0-255', '0-255.pbf', 'a-b'])
    def test_rejects_other_glyph_ranges(self, glyph_range):
        """Misaligned, oversized, out-of-Unicode-plane and non-numeric ranges are refused."""
        assert not map_tiles.is_valid_glyph_range(glyph_range)

    def test_only_known_sprite_files_are_proxied(self):
        """The sprite index and sheet, at both pixel ratios, are the only sprite files served."""
        assert map_tiles.sprite_content_type('sprites.json') == 'application/json'
        assert map_tiles.sprite_content_type('sprites@2x.png') == 'image/png'
        assert map_tiles.sprite_content_type('../sprites.json') is None
        assert map_tiles.sprite_content_type('other.png') is None


class TestGetResource:
    def test_fetches_from_openstreetmap_and_caches(self, tile_env):
        """A missing tile is downloaded from the OSM tile server with an identifying User-Agent and written to disk."""
        assert _raster(5, 16, 10) == PNG

        call = tile_env['calls'][0]
        assert call['url'] == 'https://tile.openstreetmap.org/5/16/10.png'
        assert call['headers']['User-Agent'].startswith('MyAstroBoard/9.9.9 (')
        assert (tile_env['dir'] / 'raster' / '5' / '16' / '10.png').read_bytes() == PNG
        assert tile_env['state']['response'].closed

    def test_vector_tiles_are_stored_and_returned_gzipped(self, tile_env):
        """Protobuf resources are kept gzip-encoded, ready to be served with Content-Encoding: gzip."""
        tile_env['state']['response'] = _FakeResponse(content=MVT)
        content = _vector(5, 16, 10)

        assert tile_env['calls'][0]['url'] == 'https://vector.openstreetmap.org/shortbread_v1/5/16/10.mvt'
        assert gzip.decompress(content) == MVT
        assert (tile_env['dir'] / 'vector' / '5' / '16' / '10.mvt.gz').read_bytes() == content

    def test_glyphs_and_sprites_come_from_the_style_assets(self, tile_env):
        """Fonts and sprites are fetched from the Shortbread style assets of the vector server."""
        tile_env['state']['response'] = _FakeResponse(content=b'\x0a\x10glyphs')
        map_tiles.get_resource(
            map_tiles.FONTS,
            {'fontstack': 'noto_sans_bold', 'glyph_range': '0-255'},
            ('noto_sans_bold', '0-255.pbf'),
            'alice',
        )
        tile_env['state']['response'] = _FakeResponse(content=b'{"icon": {}}')
        assert (
            map_tiles.get_resource(map_tiles.SPRITES, {'sprite_name': 'sprites.json'}, ('sprites.json',), 'alice')
            == b'{"icon": {}}'
        )

        base = 'https://vector.openstreetmap.org/styles/shortbread'
        assert [call['url'] for call in tile_env['calls']] == [
            f'{base}/fonts/noto_sans_bold/0-255.pbf',
            f'{base}/sprites/basics/sprites.json',
        ]

    def test_fresh_cached_resource_is_served_without_upstream_call(self, tile_env):
        """A tile cached less than a week ago is served from disk."""
        _raster(1, 0, 1)
        _raster(1, 0, 1)
        assert len(tile_env['calls']) == 1

    def test_stale_resource_is_refetched(self, tile_env):
        """A tile older than the freshness window is downloaded again and replaced."""
        _raster(1, 0, 1)
        _age(map_tiles.cache_path(map_tiles.RASTER, 1, 0, '1.png'), map_tiles.RASTER.fresh_seconds + 60)
        tile_env['state']['response'] = _FakeResponse(content=PNG + b'-new')

        assert _raster(1, 0, 1) == PNG + b'-new'
        assert len(tile_env['calls']) == 2

    def test_stale_resource_is_served_when_upstream_fails(self, tile_env):
        """When the map server is unreachable, an expired cached tile is better than a blank map."""
        _raster(1, 0, 1)
        _age(map_tiles.cache_path(map_tiles.RASTER, 1, 0, '1.png'), map_tiles.RASTER.fresh_seconds + 60)
        tile_env['state']['response'] = requests.ConnectionError('offline')

        assert _raster(1, 0, 1) == PNG

    @pytest.mark.parametrize(
        'failure',
        [
            requests.ConnectionError('offline'),
            _FakeResponse(status_code=429),
            _FakeResponse(content=b'<html>blocked</html>'),
            _FakeResponse(content=b''),
            _FakeResponse(content=map_tiles._PNG_SIGNATURE + b'x' * map_tiles.RASTER.max_bytes),
        ],
        ids=['network-error', 'http-error', 'not-a-png', 'empty', 'too-large'],
    )
    def test_uncached_raster_failure_raises_and_caches_nothing(self, tile_env, failure):
        """A failed download, an error status, a non-PNG, empty or oversized body is never cached."""
        tile_env['state']['response'] = failure
        with pytest.raises(map_tiles.TileUnavailable):
            _raster(2, 1, 1)
        assert not os.path.exists(map_tiles.cache_path(map_tiles.RASTER, 2, 1, '1.png'))

    @pytest.mark.parametrize('body', [b'<html>error</html>', b'{"error": "rate limited"}'])
    def test_error_page_is_not_taken_for_a_vector_tile(self, tile_env, body):
        """An HTML or JSON error body returned with HTTP 200 is not cached as a protobuf tile."""
        tile_env['state']['response'] = _FakeResponse(content=body)
        with pytest.raises(map_tiles.TileUnavailable):
            _vector(2, 1, 1)

    def test_invalid_sprite_index_is_rejected(self, tile_env):
        """A sprite index that is not a JSON object is refused."""
        tile_env['state']['response'] = _FakeResponse(content=b'not json')
        with pytest.raises(map_tiles.TileUnavailable):
            map_tiles.get_resource(map_tiles.SPRITES, {'sprite_name': 'sprites.json'}, ('sprites.json',), 'alice')

    def test_budget_limits_upstream_fetches_per_user(self, tile_env):
        """Past the per-user budget, uncached resources are refused with a retry delay; other users are unaffected."""
        for x in range(5):
            _raster(3, x, 0)

        with pytest.raises(map_tiles.TileBudgetExceeded) as excinfo:
            _raster(3, 5, 0)
        assert excinfo.value.retry_after > 0
        assert _raster(3, 5, 0, user_key='bob') == PNG

    def test_budget_does_not_block_cached_resources(self, tile_env):
        """Cache hits do not consume the budget and stay available once it is spent."""
        for x in range(5):
            _raster(3, x, 0)
        assert _raster(3, 0, 0) == PNG
        assert len(tile_env['calls']) == 5


class TestPruneCache:
    def _write_file(self, x, size, mtime):
        path = map_tiles.cache_path(map_tiles.RASTER, 2, x, '0.png')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'x' * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_no_pruning_under_the_cap(self, tile_env):
        """A cache within its size cap is left alone."""
        path = self._write_file(0, 100, time.time())
        assert map_tiles.prune_cache(max_bytes=1000) == 0
        assert os.path.exists(path)

    def test_oldest_files_are_removed_first(self, tile_env):
        """Over the cap, the oldest files go until the cache is back to 80% of the cap."""
        now = time.time()
        oldest = self._write_file(0, 300, now - 400)
        older = self._write_file(1, 300, now - 300)
        newer = self._write_file(2, 300, now - 200)
        newest = self._write_file(3, 300, now - 100)

        # 1200 bytes against a 1000-byte cap: trimmed down to 800 bytes or less
        assert map_tiles.prune_cache(max_bytes=1000) == 2
        assert not os.path.exists(oldest)
        assert not os.path.exists(older)
        assert os.path.exists(newer)
        assert os.path.exists(newest)

    def test_prune_runs_after_enough_writes(self, tile_env, monkeypatch):
        """The cache size is checked every few downloads, not on every one."""
        runs = []
        monkeypatch.setattr(map_tiles, '_PRUNE_EVERY_WRITES', 2)
        monkeypatch.setattr(map_tiles, '_writes_since_prune', 0)
        monkeypatch.setattr(map_tiles, 'prune_cache', lambda: runs.append(1))

        _raster(4, 0, 0)
        assert runs == []
        _raster(4, 1, 0)
        assert runs == [1]
