"""Smaller copies of uploaded pictures, for pages that show many of them at once.

An Astrodex picture is often a full-resolution astrophoto (16 megapixels, several MB). A page
that lists dozens of them (the Community feed, the Astrodex grid, a montage) would otherwise
download every file whole and decode each one into a bitmap of tens of MB, which makes it slow
to load and jerky to scroll. A preview is a WebP whose long side is at most one of the
``PREVIEW_SIZES``: ``thumb`` for small tiles, ``medium`` for cards and montage tiles.

Previews are kept in memory only, in a cache bounded in bytes and keyed by the file's
path, size and modification time. Nothing is written to disk, so a preview never outlives
its picture: deleting the picture (or the account) leaves nothing behind to erase or export.
"""

import io
import os
import threading
from collections import OrderedDict

from PIL import Image, ImageOps

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Long side of a preview, in pixels. ``thumb``: a 72 px tile on a 3x phone screen needs 216, a
# gallery cell about 360 on a 2x screen. ``medium``: an Astrodex card (about 300 x 200 on a 2x
# screen, cropped to fill) and a 540 px montage tile, and the width of a share card.
THUMBNAIL_MAX_SIDE = 400
MEDIUM_MAX_SIDE = 1080
PREVIEW_SIZES = {'thumb': THUMBNAIL_MAX_SIDE, 'medium': MEDIUM_MAX_SIDE}
THUMBNAIL_QUALITY = 80
THUMBNAIL_MIMETYPE = 'image/webp'
# Memory held by the cache of each worker process (a thumb is about 10-40 KB, a medium
# preview about 50-200 KB).
_CACHE_MAX_BYTES = 16 * 1024 * 1024

_cache: OrderedDict[tuple, bytes] = OrderedDict()
_cache_bytes = 0
_lock = threading.Lock()


def _cache_key(path: str, max_side: int) -> tuple | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.realpath(path), stat.st_size, stat.st_mtime_ns, max_side)


def _render(path: str, max_side: int) -> bytes:
    with Image.open(path) as image:
        # A JPEG can be decoded straight at a fraction of its size: much faster on a 16 MP file.
        image.draft('RGB', (max_side * 2, max_side * 2))
        image = ImageOps.exif_transpose(image)
        has_alpha = image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)
        image = image.convert('RGBA' if has_alpha else 'RGB')
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS, reducing_gap=2.0)
        output = io.BytesIO()
        image.save(output, format='WEBP', quality=THUMBNAIL_QUALITY, method=4)
        return output.getvalue()


def _remember(key: tuple, data: bytes) -> None:
    global _cache_bytes
    with _lock:
        if key in _cache:
            return
        _cache[key] = data
        _cache_bytes += len(data)
        while _cache_bytes > _CACHE_MAX_BYTES and _cache:
            _old_key, old = _cache.popitem(last=False)
            _cache_bytes -= len(old)


def thumbnail_bytes(path: str, max_side: int = THUMBNAIL_MAX_SIDE) -> bytes | None:
    """The WebP preview of the picture at ``path``, or None when it cannot be made.

    The caller checks that the requester may see the picture, and serves the original file
    when this returns None (a format Pillow cannot read, a damaged file).
    """
    key = _cache_key(path, max_side)
    if key is None:
        return None
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    try:
        data = _render(path, max_side)
    except Exception as error:
        logger.warning(f'Could not make a preview of {os.path.basename(path)}: {error}')
        return None
    _remember(key, data)
    return data


def clear_cache() -> None:
    """Forget every preview (tests)."""
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0
