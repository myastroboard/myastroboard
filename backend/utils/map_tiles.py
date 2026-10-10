"""OpenStreetMap raster tile proxy with an on-disk cache.

The browser never contacts a tile server: the Leaflet maps load
``/api/map-tiles/<z>/<x>/<y>.png`` and this module fetches each tile from the
OpenStreetMap Foundation tile servers once, then serves it from
``data/cache/map_tiles/``. The tile servers see the server's address, never the
users' addresses.

Follows the OpenStreetMap tile usage policy (https://operations.osmfoundation.org/policies/tiles/):
an identifying User-Agent, tiles kept for at least a week, few concurrent upstream
connections, and a per-user cap on upstream fetches so the proxy cannot be used for
bulk downloading. A stale tile is still served when the upstream is unreachable.
"""

import os
import threading
import time

import requests

from utils.constants import DATA_DIR_CACHE
from utils.logging_config import get_logger
from utils.rate_limit import SlidingWindowCounter
from utils.txtconf_loader import get_repo_version

logger = get_logger(__name__)

MAP_TILES_CACHE_DIR = os.path.join(DATA_DIR_CACHE, 'map_tiles')

OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
MAX_ZOOM = 19
REQUEST_TIMEOUT = 10

# A cached tile is refetched after a week (the minimum the usage policy asks for);
# browsers keep their copy for a day.
TILE_FRESH_SECONDS = 7 * 86400
BROWSER_MAX_AGE_SECONDS = 86400

# OSM tiles weigh 5-50 kB; anything larger is not a tile.
MAX_TILE_BYTES = 1024 * 1024
_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'

# The cache is trimmed back to 80% of this size, oldest tiles first.
CACHE_MAX_BYTES = 200 * 1024 * 1024
_PRUNE_EVERY_WRITES = 200

# Upstream concurrency per process (the policy asks for few parallel connections).
_UPSTREAM_SLOTS = threading.BoundedSemaphore(2)

# Upstream fetches per user (cache hits are free): a map view needs 20-40 tiles, so
# this is far above interactive use and well below a bulk download.
UPSTREAM_FETCHES_PER_USER = 1000
UPSTREAM_WINDOW_SECONDS = 600
_upstream_budget = SlidingWindowCounter(UPSTREAM_FETCHES_PER_USER, UPSTREAM_WINDOW_SECONDS)

_writes_since_prune = 0
_prune_lock = threading.Lock()


class TileUnavailable(Exception):
    """The tile is neither cached nor fetchable right now."""


class TileBudgetExceeded(Exception):
    """The user fetched too many uncached tiles; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: int):
        super().__init__(f'Map tile budget exceeded, retry after {retry_after}s')
        self.retry_after = retry_after


def is_valid_tile(z: int, x: int, y: int) -> bool:
    """True when (z, x, y) addresses an existing tile of the Web Mercator pyramid."""
    if not 0 <= z <= MAX_ZOOM:
        return False
    side = 1 << z
    return 0 <= x < side and 0 <= y < side


def tile_path(z: int, x: int, y: int) -> str:
    """Cache file of a tile; only ever built from validated integers."""
    return os.path.join(MAP_TILES_CACHE_DIR, str(int(z)), str(int(x)), f'{int(y)}.png')


def _user_agent() -> str:
    return f'MyAstroBoard/{get_repo_version()} (+https://github.com/myastroboard/myastroboard)'


def _read_cached(path: str) -> tuple[bytes, float] | None:
    """Return (content, mtime) of a cached tile, or None."""
    try:
        mtime = os.path.getmtime(path)
        with open(path, 'rb') as fh:
            return fh.read(), mtime
    except OSError:
        return None


def _fetch_upstream(z: int, x: int, y: int) -> bytes:
    """Download one tile from the OSM tile servers, raising TileUnavailable on any failure."""
    if not _UPSTREAM_SLOTS.acquire(timeout=REQUEST_TIMEOUT):
        raise TileUnavailable('No free upstream slot')
    try:
        resp = requests.get(
            OSM_TILE_URL.format(z=z, x=x, y=y),
            headers={'User-Agent': _user_agent()},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        try:
            if resp.status_code != 200:
                raise TileUnavailable(f'Upstream answered HTTP {resp.status_code}')
            content = resp.raw.read(MAX_TILE_BYTES + 1, decode_content=True)
        finally:
            resp.close()
    except requests.RequestException as exc:
        raise TileUnavailable(f'Upstream request failed: {exc}') from exc
    finally:
        _UPSTREAM_SLOTS.release()

    if len(content) > MAX_TILE_BYTES:
        raise TileUnavailable('Upstream tile too large')
    if not content.startswith(_PNG_SIGNATURE):
        raise TileUnavailable('Upstream did not return a PNG image')
    return content


def _store(path: str, content: bytes) -> None:
    """Write a tile atomically (several gunicorn workers may fetch the same tile)."""
    global _writes_since_prune
    tmp_path = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, 'wb') as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning(f'Could not cache map tile {path}: {exc}')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return

    with _prune_lock:
        _writes_since_prune += 1
        due = _writes_since_prune >= _PRUNE_EVERY_WRITES
        if due:
            _writes_since_prune = 0
    if due:
        prune_cache()


def prune_cache(max_bytes: int = CACHE_MAX_BYTES) -> int:
    """Delete the oldest cached tiles once the cache outgrows ``max_bytes``; return how many were removed."""
    entries = []
    total = 0
    for root, _dirs, files in os.walk(MAP_TILES_CACHE_DIR):
        for name in files:
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
    if total <= max_bytes:
        return 0

    target = int(max_bytes * 0.8)
    removed = 0
    for _mtime, size, path in sorted(entries):
        if total <= target:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        removed += 1
    logger.info(f'Map tile cache trimmed: {removed} tiles removed, {total // (1024 * 1024)} MiB kept')
    return removed


def get_tile(z: int, x: int, y: int, user_key: str) -> bytes:
    """Return the PNG bytes of a tile, from the cache when fresh, else from OpenStreetMap.

    ``user_key`` identifies the requester for the upstream fetch budget. A stale cached tile
    is returned when the upstream fails or the budget is spent.

    Raises:
        TileBudgetExceeded: the tile is not cached and the user's upstream budget is spent.
        TileUnavailable: the tile is not cached and could not be fetched.
    """
    path = tile_path(z, x, y)
    cached = _read_cached(path)
    if cached is not None and time.time() - cached[1] < TILE_FRESH_SECONDS:
        return cached[0]

    if _upstream_budget.exceeded(user_key):
        if cached is not None:
            return cached[0]
        raise TileBudgetExceeded(_upstream_budget.retry_after(user_key))
    _upstream_budget.record(user_key)

    try:
        content = _fetch_upstream(z, x, y)
    except TileUnavailable as exc:
        if cached is not None:
            logger.debug(f'Serving stale map tile {z}/{x}/{y}: {exc}')
            return cached[0]
        logger.warning(f'Map tile {z}/{x}/{y} unavailable: {exc}')
        raise

    _store(path, content)
    return content
