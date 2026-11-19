"""Strip privacy-sensitive metadata (EXIF GPS, camera serials, XMP, IPTC, comments) from images.

Photos uploaded to the Astrodex or attached to an observation session are served to other users
of the instance. Camera and phone files routinely embed the GPS position they were taken at -
usually the observer's garden - plus camera serial numbers and owner names. This module removes
that metadata before the file is written to disk.

The stripping works on the container structure only (JPEG segments, PNG chunks, WebP RIFF chunks):
the compressed pixel data is copied byte for byte and is never decoded or re-encoded, so an
astrophoto keeps its exact quality and bit depth. Kept on purpose:

- JPEG: JFIF (APP0), ICC colour profile (APP2 ``ICC_PROFILE``), Adobe colour transform (APP14),
  and the EXIF orientation - rewritten as a minimal EXIF block holding only that tag, so phone
  photos are not displayed sideways.
- PNG: every chunk except the text/metadata ones (``tEXt``, ``zTXt``, ``iTXt``, ``eXIf``, ``tIME``).
- WebP: every chunk except ``EXIF`` / ``XMP``; the orientation is re-added as a minimal EXIF chunk.

Anything after the end-of-image marker is dropped (phones append secondary images there - HDR gain
maps, depth maps - each with its own EXIF). GIF has no EXIF/GPS in practice and is returned as is.
"""

import io
import os
from typing import Any

from PIL import Image

from utils.logging_config import get_logger

logger = get_logger(__name__)

_EXIF_ORIENTATION_TAG = 0x0112
_EXIF_HEADER = b'Exif\x00\x00'

_JPEG_SOI = b'\xff\xd8'
_JPEG_KEEP_APP_MARKERS = {0xE0, 0xEE}  # APP0 (JFIF), APP14 (Adobe); APP2 is filtered by payload
_JPEG_SOS = 0xDA
_JPEG_EOI = 0xD9

_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_PNG_DROP_CHUNKS = {b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'tIME'}

_WEBP_VP8X_EXIF_FLAG = 0x08
_WEBP_VP8X_XMP_FLAG = 0x04


def _read_orientation(exif_payload: bytes) -> int | None:
    """Return the EXIF orientation (2-8) found in ``exif_payload``, or None when absent/normal/unreadable."""
    try:
        exif = Image.Exif()
        exif.load(exif_payload)
        value = exif.get(_EXIF_ORIENTATION_TAG)
    except Exception:  # malformed EXIF is simply dropped
        return None
    return value if isinstance(value, int) and 2 <= value <= 8 else None


def _orientation_exif(orientation: int) -> bytes:
    """A minimal EXIF block (with the ``Exif\\0\\0`` header) that only carries the orientation."""
    exif = Image.Exif()
    exif[_EXIF_ORIENTATION_TAG] = orientation
    return exif.tobytes()


def _is_standalone_jpeg_marker(marker: int) -> bool:
    """Markers without a length field: RST0-RST7 and TEM."""
    return 0xD0 <= marker <= 0xD7 or marker == 0x01


def _keep_jpeg_segment(marker: int, payload: bytes) -> bool:
    if marker == 0xE2:
        return payload.startswith(b'ICC_PROFILE\x00')
    if 0xE0 <= marker <= 0xEF:
        return marker in _JPEG_KEEP_APP_MARKERS
    return marker != 0xFE  # COM


def _skip_entropy_data(data: bytes, pos: int) -> int:
    """Return the offset of the next real marker after entropy-coded data starting at ``pos``.

    Inside scan data a 0xFF byte is followed by 0x00 (stuffing) or RSTn; anything else is a marker.
    Returns ``len(data)`` when the file ends without one (truncated file, kept as is).
    """
    while True:
        ff = data.find(b'\xff', pos)
        if ff == -1 or ff + 1 >= len(data):
            return len(data)
        following = data[ff + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7 or following == 0xFF:
            pos = ff + 1 if following == 0xFF else ff + 2
            continue
        return ff


def _strip_jpeg(data: bytes) -> bytes:
    chunks: list[bytes] = []
    insert_at = 0  # index in ``chunks`` right after the leading APP0 segments
    orientation: int | None = None
    pos = len(_JPEG_SOI)
    while True:
        if pos >= len(data) or data[pos] != 0xFF:
            raise ValueError('Malformed JPEG segment structure')
        while pos < len(data) and data[pos] == 0xFF:  # fill bytes
            pos += 1
        if pos >= len(data):
            raise ValueError('Truncated JPEG')
        marker = data[pos]
        pos += 1
        if marker == _JPEG_EOI:
            chunks.append(b'\xff\xd9')
            break  # trailing data (secondary images, vendor blobs) is dropped
        if _is_standalone_jpeg_marker(marker):
            chunks.append(bytes((0xFF, marker)))
            continue
        if pos + 2 > len(data):
            raise ValueError('Truncated JPEG')
        length = int.from_bytes(data[pos : pos + 2], 'big')
        if length < 2 or pos + length > len(data):
            raise ValueError('Invalid JPEG segment length')
        payload = data[pos + 2 : pos + length]
        segment = bytes((0xFF, marker)) + data[pos : pos + length]
        pos += length

        if marker == 0xE1 and orientation is None and payload.startswith(_EXIF_HEADER):
            orientation = _read_orientation(payload)
        if _keep_jpeg_segment(marker, payload):
            chunks.append(segment)
            if marker == 0xE0 and insert_at == len(chunks) - 1:
                insert_at = len(chunks)

        if marker == _JPEG_SOS:
            end = _skip_entropy_data(data, pos)
            chunks.append(data[pos:end])
            pos = end
            if pos >= len(data):
                break  # no EOI: keep what we have, browsers render truncated JPEGs

    if orientation is not None:
        exif = _orientation_exif(orientation)
        chunks.insert(insert_at, b'\xff\xe1' + (len(exif) + 2).to_bytes(2, 'big') + exif)
    return _JPEG_SOI + b''.join(chunks)


def _strip_png(data: bytes) -> bytes:
    chunks: list[bytes] = [_PNG_SIGNATURE]
    pos = len(_PNG_SIGNATURE)
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], 'big')
        chunk_type = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError('Invalid PNG chunk length')
        if chunk_type not in _PNG_DROP_CHUNKS:
            chunks.append(data[pos:end])
        pos = end
        if chunk_type == b'IEND':
            break  # trailing data is dropped
    if len(chunks) == 1:
        raise ValueError('PNG without chunks')
    return b''.join(chunks)


def _webp_chunk(fourcc: bytes, payload: bytes) -> bytes:
    return fourcc + len(payload).to_bytes(4, 'little') + payload + (b'\x00' if len(payload) % 2 else b'')


def _strip_webp(data: bytes) -> bytes:
    chunks: list[bytearray] = []
    vp8x_index: int | None = None
    orientation: int | None = None
    pos = 12
    while pos + 8 <= len(data):
        fourcc = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], 'little')
        end = pos + 8 + size
        if end > len(data):
            raise ValueError('Invalid WebP chunk length')
        padded_end = min(end + (size % 2), len(data))
        if fourcc == b'EXIF':
            orientation = orientation or _read_orientation(data[pos + 8 : end])
        elif fourcc != b'XMP ':
            if fourcc == b'VP8X':
                vp8x_index = len(chunks)
            chunks.append(bytearray(data[pos:padded_end]))
        pos = padded_end
    if not chunks:
        raise ValueError('WebP without chunks')

    if vp8x_index is not None and len(chunks[vp8x_index]) > 8:
        flags = chunks[vp8x_index][8] & ~(_WEBP_VP8X_EXIF_FLAG | _WEBP_VP8X_XMP_FLAG)
        if orientation is not None:
            flags |= _WEBP_VP8X_EXIF_FLAG
            # The spec places EXIF after the image data, i.e. at the end of the file.
            chunks.append(bytearray(_webp_chunk(b'EXIF', _orientation_exif(orientation)[len(_EXIF_HEADER) :])))
        chunks[vp8x_index][8] = flags

    body = b'WEBP' + b''.join(bytes(chunk) for chunk in chunks)
    return b'RIFF' + len(body).to_bytes(4, 'little') + body


def strip_image_metadata(data: bytes) -> bytes:
    """Return ``data`` without its privacy-sensitive metadata; see the module docstring.

    The format is detected from the file signature, not the extension. Raises ``ValueError``
    when ``data`` is not a JPEG, PNG, WebP or GIF image, or its structure is corrupt.
    """
    if data.startswith(_JPEG_SOI):
        return _strip_jpeg(data)
    if data.startswith(_PNG_SIGNATURE):
        return _strip_png(data)
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return _strip_webp(data)
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return data
    raise ValueError('Unsupported or unrecognised image format')


# ---------------------------------------------------------------------------
# Pictures stored before the upload stripping existed (before 1.6.4)
# ---------------------------------------------------------------------------

_PICTURE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


def _decodes(data: bytes) -> bool:
    """True when ``data`` still opens as an image (a safety net before replacing a file)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        return True
    except Exception:
        return False


def strip_stored_pictures(directories: list[str], dry_run: bool = False) -> dict[str, Any]:
    """Strip the metadata of every picture already stored in ``directories`` (not recursive).

    For pictures uploaded before the upload stripping existed. Same lossless stripping as on
    upload; a file is replaced only when something was removed and the result still decodes,
    and the replacement is atomic (temporary file, then rename). Files that are not pictures
    are left alone. ``dry_run`` counts without writing (and skips the decode check, which only
    guards a write).

    Returns ``{'scanned', 'cleaned', 'unchanged', 'failed'}``.
    """
    counts = {'scanned': 0, 'cleaned': 0, 'unchanged': 0, 'failed': 0}
    for directory in directories:
        base_dir = os.path.realpath(directory)
        if not os.path.isdir(base_dir):
            continue
        for filename in sorted(os.listdir(base_dir)):
            if not filename.lower().endswith(_PICTURE_EXTENSIONS):
                continue
            path = os.path.realpath(os.path.join(base_dir, filename))
            if not path.startswith(base_dir + os.sep) or not os.path.isfile(path):
                continue
            counts['scanned'] += 1
            try:
                with open(path, 'rb') as handle:
                    original = handle.read()
                cleaned = strip_image_metadata(original)
                if cleaned == original:
                    counts['unchanged'] += 1
                    continue
                # Decoding is the slow part: only done before a file is actually replaced
                if not dry_run:
                    if not _decodes(cleaned):
                        raise ValueError('stripped picture no longer decodes')
                    temporary = f'{path}.tmp'
                    with open(temporary, 'wb') as handle:
                        handle.write(cleaned)
                    os.replace(temporary, path)
                counts['cleaned'] += 1
            except Exception as error:
                counts['failed'] += 1
                logger.warning(f'Picture metadata: could not clean {filename}: {error}')
    return counts
