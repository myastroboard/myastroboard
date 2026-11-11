"""Render a sky cut-out from HiPS tiles - the local stand-in for CDS hips2fits.

hips2fits is a CDS service: it reads the HiPS tiles of a survey and reprojects them into
the image asked for. When CDS is unreachable (as during its November 2026 incident), the
DSS2 colour HiPS itself is still published, tile for tile, by mirror sites (ESA, MAST,
CSIRO, China-VO). This module does the reprojection hips2fits would have done, so the
same image can be built from any of those mirrors:

* each output pixel of a square gnomonic (TAN) image, north up and east left, is mapped
  back to the sky;
* each sky position is located in the HEALPix NESTED grid at the resolution of the
  survey tiles, which names the tile to download and the pixel to read in it;
* the colour of that pixel is copied, averaged over a 2x2 sub-pixel grid to soften the
  aliasing of point-like stars.

No network state lives here: the caller chooses the mirror, and handles backoff and
caching. A network failure is raised as ``requests.RequestException``.

HiPS standard: https://www.ivoa.net/documents/HiPS/ - HEALPix NESTED scheme: Gorski et
al. 2005, ApJ 622, 759.
"""

import io
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

from utils.logging_config import get_logger

logger = get_logger(__name__)

# requests timeout: seconds, or a (connect, read) pair.
Timeout = float | tuple[float, float]

# Side of a HiPS tile in pixels (``hips_tile_width`` of the DSS2 colour survey), and its
# base-2 logarithm: a tile at order k holds the HEALPix pixels of order k + 9.
TILE_WIDTH = 512
_TILE_ORDER_OFFSET = 9

# Deepest tile order the DSS2 colour HiPS publishes (``hips_order``).
MAX_TILE_ORDER = 9

# Sub-pixel grid per side used to average each output pixel.
_SUPERSAMPLE = 2

_JPEG_QUALITY = 90
_TILE_FETCH_WORKERS = 6

# Bit masks of the classic "spread / compact" bit interleaving used by the NESTED scheme.
_SPREAD_MASKS = (
    (16, 0x0000FFFF0000FFFF),
    (8, 0x00FF00FF00FF00FF),
    (4, 0x0F0F0F0F0F0F0F0F),
    (2, 0x3333333333333333),
    (1, 0x5555555555555555),
)
_COMPACT_MASKS = (
    (1, 0x3333333333333333),
    (2, 0x0F0F0F0F0F0F0F0F),
    (4, 0x00FF00FF00FF00FF),
    (8, 0x0000FFFF0000FFFF),
    (16, 0x00000000FFFFFFFF),
)


def _spread_bits(values: np.ndarray) -> np.ndarray:
    """Insert a zero bit between each bit of *values* (32-bit inputs)."""
    out = values & 0x00000000FFFFFFFF
    for shift, mask in _SPREAD_MASKS:
        out = (out | (out << shift)) & mask
    return out


def _compact_bits(values: np.ndarray) -> np.ndarray:
    """Keep every other bit of *values* (the inverse of ``_spread_bits``)."""
    out = values & 0x5555555555555555
    for shift, mask in _COMPACT_MASKS:
        out = (out | (out >> shift)) & mask
    return out


def ang2pix_nest(order: int, ra_rad: np.ndarray, dec_rad: np.ndarray) -> np.ndarray:
    """HEALPix NESTED pixel index of each sky position, at resolution *order*.

    Vectorised transcription of the reference ``ang2pix_nest`` algorithm: the sphere is
    split into 12 base faces, each subdivided into ``nside x nside`` pixels with
    ``nside = 2**order``; the index interleaves the bits of the in-face coordinates.
    """
    nside = np.int64(1) << order
    z = np.sin(dec_rad)
    za = np.abs(z)
    tt = np.mod(ra_rad, 2 * np.pi) / (np.pi / 2)  # in [0, 4)

    # Equatorial belt (|z| <= 2/3).
    temp1 = nside * (0.5 + tt)
    temp2 = nside * z * 0.75
    jp = (temp1 - temp2).astype(np.int64)
    jm = (temp1 + temp2).astype(np.int64)
    ifp = jp >> order
    ifm = jm >> order
    face_eq = np.where(ifp == ifm, ifp | 4, np.where(ifp < ifm, ifp, ifm + 8))
    ix_eq = jm & (nside - 1)
    iy_eq = nside - (jp & (nside - 1)) - 1

    # Polar caps.
    ntt = np.minimum(3, tt.astype(np.int64))
    tp = tt - ntt
    tmp = nside * np.sqrt(3 * (1 - za))
    jp_cap = np.minimum((tp * tmp).astype(np.int64), nside - 1)
    jm_cap = np.minimum(((1 - tp) * tmp).astype(np.int64), nside - 1)
    north = z >= 0
    face_cap = np.where(north, ntt, ntt + 8)
    ix_cap = np.where(north, nside - jm_cap - 1, jp_cap)
    iy_cap = np.where(north, nside - jp_cap - 1, jm_cap)

    equatorial = za <= 2.0 / 3.0
    face = np.where(equatorial, face_eq, face_cap)
    ix = np.where(equatorial, ix_eq, ix_cap)
    iy = np.where(equatorial, iy_eq, iy_cap)
    return (face << (2 * order)) + _spread_bits(ix) + (_spread_bits(iy) << 1)


def tan_grid(ra_deg: float, dec_deg: float, fov_deg: float, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Sky coordinates (radians) of the pixel centres of a square TAN image.

    The image is ``size`` pixels wide, covers *fov_deg* across, and is centred on
    (*ra_deg*, *dec_deg*), north up and east left - the hips2fits conventions.
    """
    scale = math.radians(fov_deg) / size
    centre = (size - 1) / 2
    offsets = (np.arange(size) - centre) * scale
    xi = np.broadcast_to(-offsets[np.newaxis, :], (size, size))  # east is left
    eta = np.broadcast_to(-offsets[:, np.newaxis], (size, size))  # north is up

    ra0 = math.radians(ra_deg)
    dec0 = math.radians(dec_deg)
    rho = np.hypot(xi, eta)
    c = np.arctan(rho)
    sin_c, cos_c = np.sin(c), np.cos(c)
    safe_rho = np.where(rho > 0, rho, 1.0)
    dec = np.arcsin(np.clip(cos_c * math.sin(dec0) + eta * sin_c * math.cos(dec0) / safe_rho, -1.0, 1.0))
    ra = ra0 + np.arctan2(xi * sin_c, rho * math.cos(dec0) * cos_c - eta * math.sin(dec0) * sin_c)
    return np.where(rho > 0, ra, ra0), np.where(rho > 0, dec, dec0)


def tile_order_for(fov_deg: float, size: int) -> int:
    """Shallowest tile order whose pixels are no larger than an output pixel (as hips2fits)."""
    scale = math.radians(fov_deg) / size
    for order in range(MAX_TILE_ORDER + 1):
        pixel = math.sqrt(4 * math.pi / (12 * 4 ** (order + _TILE_ORDER_OFFSET)))
        if pixel <= scale:
            return order
    return MAX_TILE_ORDER


def tile_url(base_url: str, order: int, npix: int) -> str:
    """URL of one HiPS tile, following the standard ``Norder/Dir/Npix`` layout."""
    return f'{base_url.rstrip("/")}/Norder{order}/Dir{(npix // 10000) * 10000}/Npix{npix}.jpg'


def _fetch_tile(base_url: str, order: int, npix: int, timeout: Timeout) -> np.ndarray | None:
    """Download and decode one tile; None when the mirror has no such tile (404)."""
    resp = requests.get(tile_url(base_url, order, npix), timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    try:
        return np.asarray(Image.open(io.BytesIO(resp.content)).convert('RGB'))
    except OSError as exc:
        raise requests.RequestException(f'undecodable tile Norder{order}/Npix{npix}: {exc}') from exc


def render_cutout(
    base_url: str, ra_deg: float, dec_deg: float, fov_deg: float, size: int, timeout: Timeout = 10
) -> bytes:
    """Build a JPEG cut-out of the HiPS survey published at *base_url*.

    Same geometry as a hips2fits ``projection=TAN`` request: *size* x *size* pixels
    covering *fov_deg*, centred on (*ra_deg*, *dec_deg*), north up, east left.

    Raises ``requests.RequestException`` when a tile cannot be downloaded, or when the
    mirror has none of the tiles needed (most likely a wrong or emptied mirror).
    """
    order = tile_order_for(fov_deg, size)
    sub = size * _SUPERSAMPLE
    ra, dec = tan_grid(ra_deg, dec_deg, fov_deg, sub)
    ipix = ang2pix_nest(order + _TILE_ORDER_OFFSET, ra, dec)

    pixels_per_tile_bits = 2 * _TILE_ORDER_OFFSET
    tile_ids = ipix >> pixels_per_tile_bits
    local = ipix & ((1 << pixels_per_tile_bits) - 1)
    # Inside a tile, the de-interleaved x addresses the image row and y the column.
    rows = _compact_bits(local)
    cols = _compact_bits(local >> 1)

    unique_tiles = [int(t) for t in np.unique(tile_ids)]
    with ThreadPoolExecutor(max_workers=min(_TILE_FETCH_WORKERS, len(unique_tiles))) as pool:
        tiles = dict(
            zip(
                unique_tiles,
                pool.map(lambda npix: _fetch_tile(base_url, order, npix, timeout), unique_tiles),
                strict=True,
            )
        )
    if all(tile is None for tile in tiles.values()):
        raise requests.RequestException(f'no tile found on {base_url} at order {order}')

    canvas = np.zeros((sub, sub, 3), dtype=np.uint8)
    for npix, tile in tiles.items():
        if tile is None:
            logger.debug(f'HiPS tile Norder{order}/Npix{npix} missing on {base_url}, left black')
            continue
        mask = tile_ids == npix
        canvas[mask] = tile[rows[mask], cols[mask]]

    image = canvas.reshape(size, _SUPERSAMPLE, size, _SUPERSAMPLE, 3).mean(axis=(1, 3))
    out = io.BytesIO()
    Image.fromarray(np.round(image).astype(np.uint8)).save(out, format='JPEG', quality=_JPEG_QUALITY)
    return out.getvalue()
