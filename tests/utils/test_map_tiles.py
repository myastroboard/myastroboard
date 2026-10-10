"""Tests for utils.map_tiles: the OpenStreetMap tile proxy and its on-disk cache."""

import os
import time

import pytest
import requests

from utils import map_tiles
from utils.rate_limit import SlidingWindowCounter

PNG = map_tiles._PNG_SIGNATURE + b'tile-body'


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


class TestIsValidTile:
    def test_accepts_tiles_inside_the_pyramid(self):
        """Every tile of a zoom level from 0 to 2^z - 1 on both axes is valid, up to the max zoom."""
        assert map_tiles.is_valid_tile(0, 0, 0)
        assert map_tiles.is_valid_tile(3, 7, 7)
        assert map_tiles.is_valid_tile(map_tiles.MAX_ZOOM, 0, 0)

    @pytest.mark.parametrize(
        'z,x,y',
        [(0, 1, 0), (0, 0, 1), (3, 8, 0), (3, 0, 8), (-1, 0, 0), (2, -1, 0), (map_tiles.MAX_ZOOM + 1, 0, 0)],
    )
    def test_rejects_tiles_outside_the_pyramid(self, z, x, y):
        """Coordinates past the edge of their zoom level, negative values and too-deep zooms are refused."""
        assert not map_tiles.is_valid_tile(z, x, y)


class TestGetTile:
    def test_fetches_from_openstreetmap_and_caches(self, tile_env):
        """A missing tile is downloaded from the OSM tile server with an identifying User-Agent and written to disk."""
        assert map_tiles.get_tile(5, 16, 10, user_key='alice') == PNG

        call = tile_env['calls'][0]
        assert call['url'] == 'https://tile.openstreetmap.org/5/16/10.png'
        assert call['headers']['User-Agent'].startswith('MyAstroBoard/9.9.9 (')
        assert (tile_env['dir'] / '5' / '16' / '10.png').read_bytes() == PNG
        assert tile_env['state']['response'].closed

    def test_fresh_cached_tile_is_served_without_upstream_call(self, tile_env):
        """A tile cached less than a week ago is served from disk."""
        map_tiles.get_tile(1, 0, 1, user_key='alice')
        map_tiles.get_tile(1, 0, 1, user_key='alice')
        assert len(tile_env['calls']) == 1

    def test_stale_tile_is_refetched(self, tile_env):
        """A tile older than the freshness window is downloaded again and replaced."""
        map_tiles.get_tile(1, 0, 1, user_key='alice')
        path = map_tiles.tile_path(1, 0, 1)
        old = time.time() - map_tiles.TILE_FRESH_SECONDS - 60
        os.utime(path, (old, old))
        tile_env['state']['response'] = _FakeResponse(content=PNG + b'-new')

        assert map_tiles.get_tile(1, 0, 1, user_key='alice') == PNG + b'-new'
        assert len(tile_env['calls']) == 2

    def test_stale_tile_is_served_when_upstream_fails(self, tile_env):
        """When the tile server is unreachable, an expired cached tile is better than a blank map."""
        map_tiles.get_tile(1, 0, 1, user_key='alice')
        path = map_tiles.tile_path(1, 0, 1)
        old = time.time() - map_tiles.TILE_FRESH_SECONDS - 60
        os.utime(path, (old, old))
        tile_env['state']['response'] = requests.ConnectionError('offline')

        assert map_tiles.get_tile(1, 0, 1, user_key='alice') == PNG

    @pytest.mark.parametrize(
        'failure',
        [
            requests.ConnectionError('offline'),
            _FakeResponse(status_code=429),
            _FakeResponse(content=b'<html>blocked</html>'),
            _FakeResponse(content=map_tiles._PNG_SIGNATURE + b'x' * map_tiles.MAX_TILE_BYTES),
        ],
        ids=['network-error', 'http-error', 'not-a-png', 'too-large'],
    )
    def test_uncached_tile_failure_raises_and_caches_nothing(self, tile_env, failure):
        """A failed download, an error status, a non-PNG body or an oversized body is never cached."""
        tile_env['state']['response'] = failure
        with pytest.raises(map_tiles.TileUnavailable):
            map_tiles.get_tile(2, 1, 1, user_key='alice')
        assert not os.path.exists(map_tiles.tile_path(2, 1, 1))

    def test_budget_limits_upstream_fetches_per_user(self, tile_env):
        """Past the per-user budget, uncached tiles are refused with a retry delay; other users are unaffected."""
        for x in range(5):
            map_tiles.get_tile(3, x, 0, user_key='alice')

        with pytest.raises(map_tiles.TileBudgetExceeded) as excinfo:
            map_tiles.get_tile(3, 5, 0, user_key='alice')
        assert excinfo.value.retry_after > 0
        assert map_tiles.get_tile(3, 5, 0, user_key='bob') == PNG

    def test_budget_does_not_block_cached_tiles(self, tile_env):
        """Cache hits do not consume the budget and stay available once it is spent."""
        for x in range(5):
            map_tiles.get_tile(3, x, 0, user_key='alice')
        assert map_tiles.get_tile(3, 0, 0, user_key='alice') == PNG
        assert len(tile_env['calls']) == 5


class TestPruneCache:
    def _write_tile(self, z, x, y, size, mtime):
        path = map_tiles.tile_path(z, x, y)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'x' * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_no_pruning_under_the_cap(self, tile_env):
        """A cache within its size cap is left alone."""
        path = self._write_tile(1, 0, 0, 100, time.time())
        assert map_tiles.prune_cache(max_bytes=1000) == 0
        assert os.path.exists(path)

    def test_oldest_tiles_are_removed_first(self, tile_env):
        """Over the cap, the oldest tiles go until the cache is back to 80% of the cap."""
        now = time.time()
        oldest = self._write_tile(2, 0, 0, 300, now - 400)
        older = self._write_tile(2, 1, 0, 300, now - 300)
        newer = self._write_tile(2, 2, 0, 300, now - 200)
        newest = self._write_tile(2, 3, 0, 300, now - 100)

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

        map_tiles.get_tile(4, 0, 0, user_key='alice')
        assert runs == []
        map_tiles.get_tile(4, 1, 0, user_key='alice')
        assert runs == [1]
