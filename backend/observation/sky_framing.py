"""Framing simulator - target resolution and sky background images.

The framing simulator draws the sensor rectangle of an equipment combination over a real
image of the sky around a target. This module owns the two server-side pieces that do not
depend on equipment:

* resolving a target identifier to fixed equatorial coordinates and an apparent size;
* serving the background image: a square DSS2 colour cut-out from CDS hips2fits (or,
  when CDS is down, rendered from a mirror of its HiPS tiles - see
  ``object_info.download_dss_image``), fetched once by the server and cached on disk, so
  the browser never calls those servers itself.

The image is north up, east left, in gnomonic (TAN) projection centred on the target. A
camera sensor at the focal plane is a gnomonic projection too, so a sensor centred on the
target is an exact rectangle on the image, whatever the field of view.

To keep the cache bounded, the field of view of a background image is not free: it must
be one of ``FOV_LADDER_DEG``. The frontend picks the smallest step that contains what it
has to draw. The sensor geometry itself lives in ``equipment/framing.py``.
"""

import os
import re
import threading
from typing import Any

from observation import object_info
from skytonight import skytonight_targets
from utils.constants import DATA_DIR_CACHE
from utils.logging_config import get_logger

logger = get_logger(__name__)

# On-disk cache of background images, keyed by (ra, dec, field of view). DSS2 never
# changes, so an image is valid forever; the cache is only trimmed for size.
FRAMING_IMAGE_CACHE_DIR = os.path.join(DATA_DIR_CACHE, 'framing_images')
FRAMING_IMAGE_CACHE_MAX_BYTES = 200 * 1024 * 1024

# Side of the square background image, in pixels.
IMAGE_SIZE_PX = 1000

# Allowed fields of view (degrees, full width of the image). From a long-focal planetary
# setup to a camera lens.
FOV_LADDER_DEG: tuple[float, ...] = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 45.0)

# (connect, read) seconds. A wide cut-out takes CDS noticeably longer to render than the
# 400 px object thumbnails, hence the long read timeout; the short connect timeout keeps
# an unreachable CDS from holding a worker for that long before the mirrors are tried.
_IMAGE_REQUEST_TIMEOUT = (object_info.CONNECT_TIMEOUT, 30)

# Solar-system targets move: a background centred on catalogue coordinates is meaningless.
_MOVING_CATEGORIES = {'bodies', 'comets'}
_MOVING_OTYPE_TOKENS = ('planet', 'comet', 'asteroid', 'moon', 'minor')

# "<ra>_<dec>_<fov>.jpg", e.g. "10.684708_41.268750_4.00.jpg". Validates the image route's
# path segment (path traversal safety) and recovers what to fetch when the file is missing.
_IMAGE_FILENAME_RE = re.compile(r'^(-?\d{1,3}\.\d{6})_(-?\d{1,2}\.\d{6})_(\d{1,2}\.\d{2})\.jpg$')

_PRUNE_EVERY_WRITES = 20
_prune_lock = threading.Lock()
_writes_since_prune = 0


def resolve_target(identifier: str) -> dict[str, Any]:
    """Resolve *identifier* to the fixed coordinates and size the simulator needs.

    The result always carries ``supported`` (bool) and ``name``. When supported it also has
    ``target_id``, ``object_type``, ``ra_deg``, ``dec_deg``, ``size_arcmin`` (None when
    unknown) and ``image_key``. When not, it carries ``reason``: ``'moving_target'`` for a
    solar-system body or comet, ``'not_found'`` otherwise.
    """
    match = skytonight_targets.find_target(identifier)
    if match is not None:
        name = match.preferred_name or identifier
        if match.category in _MOVING_CATEGORIES:
            return {'supported': False, 'reason': 'moving_target', 'name': name}
        if match.coordinates is None:
            return {'supported': False, 'reason': 'not_found', 'name': name}
        ra_deg = (match.coordinates.ra_hours * 15.0) % 360.0
        dec_deg = match.coordinates.dec_degrees
        size = match.size_arcmin if match.size_arcmin and match.size_arcmin > 0 else None
        return {
            'supported': True,
            'target_id': match.target_id,
            'name': name,
            'object_type': match.object_type,
            'ra_deg': ra_deg,
            'dec_deg': dec_deg,
            'size_arcmin': size,
            'image_key': image_key(ra_deg, dec_deg),
        }

    # Fallback: SIMBAD - covers Astrodex items outside the SkyTonight dataset. It gives
    # coordinates but no apparent size.
    resolved = object_info._resolve_via_simbad(identifier)
    if not resolved or resolved.get('ra') is None or resolved.get('dec') is None:
        return {'supported': False, 'reason': 'not_found', 'name': identifier}
    object_type = str(resolved.get('type') or '')
    name = str(resolved.get('name') or identifier)
    if any(token in object_type.lower() for token in _MOVING_OTYPE_TOKENS):
        return {'supported': False, 'reason': 'moving_target', 'name': name}
    try:
        ra_deg = float(resolved['ra']) % 360.0
        dec_deg = float(resolved['dec'])
    except TypeError, ValueError:
        return {'supported': False, 'reason': 'not_found', 'name': identifier}
    if not -90.0 <= dec_deg <= 90.0:
        return {'supported': False, 'reason': 'not_found', 'name': identifier}
    return {
        'supported': True,
        'target_id': str(resolved.get('id') or identifier),
        'name': name,
        'object_type': object_type,
        'ra_deg': ra_deg,
        'dec_deg': dec_deg,
        'size_arcmin': None,
        'image_key': image_key(ra_deg, dec_deg),
    }


def image_key(ra_deg: float, dec_deg: float) -> str:
    """Return the coordinate part of a background image filename ("<ra>_<dec>")."""
    return f'{ra_deg:.6f}_{dec_deg:.6f}'


def image_filename(ra_deg: float, dec_deg: float, fov_deg: float) -> str:
    """Return the cache filename of the background image for (ra, dec) at *fov_deg*."""
    return f'{image_key(ra_deg, dec_deg)}_{fov_deg:.2f}.jpg'


def parse_image_filename(filename: str) -> tuple[float, float, float] | None:
    """Validate an image route path segment and recover ``(ra_deg, dec_deg, fov_deg)``.

    Returns None when the filename does not match the expected pattern, the coordinates
    are out of range, or the field of view is not a step of ``FOV_LADDER_DEG``.
    """
    m = _IMAGE_FILENAME_RE.match(filename)
    if not m:
        return None
    ra, dec, fov = float(m.group(1)), float(m.group(2)), float(m.group(3))
    # f'{ra:.6f}' can round a value just under 360 up to the literal "360.000000".
    if ra == 360.0:
        ra = 0.0
    if not (0.0 <= ra < 360.0) or not (-90.0 <= dec <= 90.0):
        return None
    if not any(m.group(3) == f'{step:.2f}' for step in FOV_LADDER_DEG):
        return None
    return ra, dec, fov


def ensure_cached_image(ra_deg: float, dec_deg: float, fov_deg: float) -> str | None:
    """Make sure the background image for (ra, dec, fov) is in the on-disk cache.

    Returns the absolute local file path (downloading it first when missing), or None
    when no server could deliver it.
    """
    local_path = os.path.join(FRAMING_IMAGE_CACHE_DIR, image_filename(ra_deg, dec_deg, fov_deg))
    if os.path.isfile(local_path):
        return local_path

    label = f'framing ra={ra_deg:.4f}, dec={dec_deg:.4f}, fov={fov_deg}'
    if not object_info.download_dss_image(
        ra_deg, dec_deg, fov_deg, IMAGE_SIZE_PX, local_path, label, timeout=_IMAGE_REQUEST_TIMEOUT
    ):
        return None
    _note_cache_write()
    return local_path


def _note_cache_write() -> None:
    """Trim the cache every few writes instead of walking the directory on each one."""
    global _writes_since_prune
    with _prune_lock:
        _writes_since_prune += 1
        due = _writes_since_prune >= _PRUNE_EVERY_WRITES
        if due:
            _writes_since_prune = 0
    if due:
        prune_cache()


def prune_cache(max_bytes: int = FRAMING_IMAGE_CACHE_MAX_BYTES) -> int:
    """Delete the oldest cached images once the cache outgrows *max_bytes*; return how many."""
    entries = []
    total = 0
    try:
        names = os.listdir(FRAMING_IMAGE_CACHE_DIR)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(FRAMING_IMAGE_CACHE_DIR, name)
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
    logger.info(f'Framing image cache trimmed: {removed} files removed, {total // (1024 * 1024)} MiB kept')
    return removed
