"""OpenStreetMap map resources proxy with an on-disk cache.

The browser never contacts a map server: the Leaflet maps load everything they draw from
``/api/map-tiles/...`` and this module fetches each resource from the OpenStreetMap Foundation
servers once, then serves it from ``data/cache/map_tiles/``. The map servers see the server's
address, never the users' addresses.

Four kinds of resources are proxied:

- ``vector``: Shortbread vector tiles, drawn in the browser by MapLibre with the styles in
  ``static/map-styles/`` (built by ``scripts/build_map_styles.py``);
- ``fonts`` and ``sprites``: the label glyphs and icons those styles use;
- ``raster``: pre-rendered PNG tiles, the fallback for browsers without WebGL.

Follows the OpenStreetMap tile usage policies (https://operations.osmfoundation.org/policies/):
an identifying User-Agent, tiles kept for at least a week, few concurrent upstream connections,
and a per-user cap on upstream fetches so the proxy cannot be used for bulk downloading. A stale
resource is still served when the upstream is unreachable.
"""

import gzip
import json
import os
import re
import threading
import time
from dataclasses import dataclass

import requests

from utils.constants import DATA_DIR_CACHE
from utils.logging_config import get_logger
from utils.rate_limit import SlidingWindowCounter
from utils.txtconf_loader import get_repo_version

logger = get_logger(__name__)

MAP_TILES_CACHE_DIR = os.path.join(DATA_DIR_CACHE, 'map_tiles')

REQUEST_TIMEOUT = 10
_DAY = 86400
_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_STYLE_ASSETS_URL = 'https://vector.openstreetmap.org/styles/shortbread'


@dataclass(frozen=True)
class MapResourceKind:
    """How one kind of map resource is fetched, checked, cached and served."""

    name: str
    upstream_url: str
    # Kept this long before being downloaded again (the usage policy asks for a week at least)
    fresh_seconds: int
    browser_max_age: int
    # Decoded size cap: anything larger is not a genuine resource
    max_bytes: int
    # Stored and served gzip-encoded (protobuf payloads compress well; images do not)
    gzip: bool


RASTER = MapResourceKind(
    name='raster',
    upstream_url='https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    fresh_seconds=7 * _DAY,
    browser_max_age=_DAY,
    max_bytes=1024 * 1024,
    gzip=False,
)
VECTOR = MapResourceKind(
    name='vector',
    upstream_url='https://vector.openstreetmap.org/shortbread_v1/{z}/{x}/{y}.mvt',
    fresh_seconds=7 * _DAY,
    browser_max_age=_DAY,
    max_bytes=8 * 1024 * 1024,
    gzip=True,
)
FONTS = MapResourceKind(
    name='fonts',
    upstream_url=_STYLE_ASSETS_URL + '/fonts/{fontstack}/{glyph_range}.pbf',
    fresh_seconds=30 * _DAY,
    browser_max_age=7 * _DAY,
    max_bytes=1024 * 1024,
    gzip=True,
)
SPRITES = MapResourceKind(
    name='sprites',
    upstream_url=_STYLE_ASSETS_URL + '/sprites/basics/{sprite_name}',
    fresh_seconds=30 * _DAY,
    browser_max_age=7 * _DAY,
    max_bytes=2 * 1024 * 1024,
    gzip=False,
)

RASTER_MAX_ZOOM = 19
# Shortbread tiles stop at zoom 14; MapLibre over-zooms them past that
VECTOR_MAX_ZOOM = 14
# The only fonts and sprite set the styles in static/map-styles/ use
FONT_STACKS = frozenset({'noto_sans_regular', 'noto_sans_bold'})
SPRITE_FILES = {
    'sprites.json': 'application/json',
    'sprites.png': 'image/png',
    'sprites@2x.json': 'application/json',
    'sprites@2x.png': 'image/png',
}
_GLYPH_RANGE_RE = re.compile(r'^(\d{1,5})-(\d{1,5})$')

# The cache is trimmed back to 80% of this size, oldest files first.
CACHE_MAX_BYTES = 300 * 1024 * 1024
_PRUNE_EVERY_WRITES = 200

# Upstream concurrency per process (the policy asks for few parallel connections).
_UPSTREAM_SLOTS = threading.BoundedSemaphore(2)

# Upstream fetches per user (cache hits are free): a map view needs a few dozen resources, so
# this is far above interactive use and well below a bulk download.
UPSTREAM_FETCHES_PER_USER = 1000
UPSTREAM_WINDOW_SECONDS = 600
_upstream_budget = SlidingWindowCounter(UPSTREAM_FETCHES_PER_USER, UPSTREAM_WINDOW_SECONDS)

_writes_since_prune = 0
_prune_lock = threading.Lock()


class TileUnavailable(Exception):
    """The resource is neither cached nor fetchable right now."""


class TileBudgetExceeded(Exception):
    """The user fetched too many uncached resources; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: int):
        super().__init__(f'Map tile budget exceeded, retry after {retry_after}s')
        self.retry_after = retry_after


def is_valid_tile(z: int, x: int, y: int, max_zoom: int = RASTER_MAX_ZOOM) -> bool:
    """True when (z, x, y) addresses an existing tile of the Web Mercator pyramid up to ``max_zoom``."""
    if not 0 <= z <= max_zoom:
        return False
    side = 1 << z
    return 0 <= x < side and 0 <= y < side


def is_valid_glyph_range(glyph_range: str) -> bool:
    """True for a MapLibre glyph block name: ``<start>-<start + 255>`` with start a multiple of 256."""
    match = _GLYPH_RANGE_RE.match(glyph_range)
    if not match:
        return False
    start, end = int(match.group(1)), int(match.group(2))
    return start % 256 == 0 and end == start + 255 and end <= 65535


def sprite_content_type(sprite_name: str) -> str | None:
    """Content type of a proxied sprite file, or None when the name is not one of them."""
    return SPRITE_FILES.get(sprite_name)


def cache_path(kind: MapResourceKind, *parts) -> str:
    """Cache file of a resource; ``parts`` are only ever validated integers or whitelisted names."""
    *dirs, filename = (str(part) for part in parts)
    return os.path.join(MAP_TILES_CACHE_DIR, kind.name, *dirs, filename + ('.gz' if kind.gzip else ''))


def _user_agent() -> str:
    return f'MyAstroBoard/{get_repo_version()} (+https://github.com/myastroboard/myastroboard)'


def _read_cached(path: str) -> tuple[bytes, float] | None:
    """Return (content, mtime) of a cached file, or None."""
    try:
        mtime = os.path.getmtime(path)
        with open(path, 'rb') as fh:
            return fh.read(), mtime
    except OSError:
        return None


def _looks_genuine(kind: MapResourceKind, content: bytes, url: str) -> bool:
    """Reject error pages and truncated bodies that a misbehaving upstream might return as 200."""
    if not content:
        return False
    if url.endswith('.png'):
        return content.startswith(_PNG_SIGNATURE)
    if url.endswith('.json'):
        try:
            return isinstance(json.loads(content), dict)
        except ValueError:
            return False
    # Protobuf (tiles, glyphs) has no signature; an HTML or JSON error body is the usual impostor.
    # Neither byte is a valid first field tag of a vector tile or a glyph block.
    return content[:1] not in (b'<', b'{')


def _fetch_upstream(kind: MapResourceKind, url: str) -> bytes:
    """Download one resource (decoded), raising TileUnavailable on any failure."""
    if not _UPSTREAM_SLOTS.acquire(timeout=REQUEST_TIMEOUT):
        raise TileUnavailable('No free upstream slot')
    try:
        resp = requests.get(
            url,
            headers={'User-Agent': _user_agent(), 'Accept-Encoding': 'gzip'},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        try:
            if resp.status_code != 200:
                raise TileUnavailable(f'Upstream answered HTTP {resp.status_code}')
            # Reading the decoded stream caps the decompressed size too
            content = resp.raw.read(kind.max_bytes + 1, decode_content=True)
        finally:
            resp.close()
    except requests.RequestException as exc:
        raise TileUnavailable(f'Upstream request failed: {exc}') from exc
    finally:
        _UPSTREAM_SLOTS.release()

    if len(content) > kind.max_bytes:
        raise TileUnavailable('Upstream resource too large')
    if not _looks_genuine(kind, content, url):
        raise TileUnavailable('Upstream did not return the expected content')
    return content


def _store(path: str, content: bytes) -> None:
    """Write a file atomically (several gunicorn workers may fetch the same resource)."""
    global _writes_since_prune
    tmp_path = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, 'wb') as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning(f'Could not cache map resource {path}: {exc}')
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
    """Delete the oldest cached files once the cache outgrows ``max_bytes``; return how many were removed."""
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
    logger.info(f'Map tile cache trimmed: {removed} files removed, {total // (1024 * 1024)} MiB kept')
    return removed


def get_resource(kind: MapResourceKind, url_params: dict, path_parts: tuple, user_key: str) -> bytes:
    """Return a resource from the cache when fresh, else from OpenStreetMap.

    The bytes are gzip-encoded when ``kind.gzip`` is set. ``url_params`` fill the upstream URL and
    ``path_parts`` name the cache file; both must already be validated. ``user_key`` identifies the
    requester for the upstream fetch budget. A stale cached copy is returned when the upstream fails
    or the budget is spent.

    Raises:
        TileBudgetExceeded: the resource is not cached and the user's upstream budget is spent.
        TileUnavailable: the resource is not cached and could not be fetched.
    """
    path = cache_path(kind, *path_parts)
    label = f'{kind.name}/{"/".join(str(part) for part in path_parts)}'
    cached = _read_cached(path)
    if cached is not None and time.time() - cached[1] < kind.fresh_seconds:
        return cached[0]

    if _upstream_budget.exceeded(user_key):
        if cached is not None:
            return cached[0]
        raise TileBudgetExceeded(_upstream_budget.retry_after(user_key))
    _upstream_budget.record(user_key)

    try:
        content = _fetch_upstream(kind, kind.upstream_url.format(**url_params))
    except TileUnavailable as exc:
        if cached is not None:
            logger.debug(f'Serving stale map resource {label}: {exc}')
            return cached[0]
        logger.warning(f'Map resource {label} unavailable: {exc}')
        raise

    if kind.gzip:
        content = gzip.compress(content, compresslevel=6, mtime=0)
    _store(path, content)
    return content
