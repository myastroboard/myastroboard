"""Tests for observation/hips_cutout.py - DSS2 cut-outs rendered from HiPS mirror tiles."""

import io
import math
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests
from PIL import Image

from observation import hips_cutout as hc

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
MIRROR = 'https://mirror.example/DSSColor'

# M83, whose central 0.1 degree lies inside a single order-7 tile of the DSS2 colour HiPS.
M83_RA, M83_DEC = 204.253958, -29.865417
M83_TILE = 175526


def _tile_response(rgb=None, status=200, content=None):
    resp = MagicMock()
    resp.status_code = status
    if content is None and rgb is not None:
        buf = io.BytesIO()
        Image.new('RGB', (hc.TILE_WIDTH, hc.TILE_WIDTH), rgb).save(buf, format='JPEG')
        content = buf.getvalue()
    resp.content = content or b''
    if status >= 400 and status != 404:
        resp.raise_for_status.side_effect = requests.HTTPError(f'{status}')
    else:
        resp.raise_for_status.return_value = None
    return resp


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])


# ---------------------------------------------------------------------------
# HEALPix NESTED indexing
# ---------------------------------------------------------------------------


def test_spread_and_compact_bits_are_inverse():
    """Interleaving then de-interleaving the bits of a coordinate gives it back."""
    values = np.array([0, 1, 2, 3, 255, 511, 12345, 2**18 - 1], dtype=np.int64)
    assert np.array_equal(hc._compact_bits(hc._spread_bits(values)), values)
    assert np.array_equal(hc._compact_bits(hc._spread_bits(values) << 1 >> 1), values)


def test_ang2pix_nest_base_faces_at_order_zero():
    """At order 0 the index is the base face: poles on faces 0-3 and 8-11, equator on 4-7."""
    ra = np.radians(np.array([45.0, 0.0, 45.0]))
    dec = np.radians(np.array([80.0, 0.0, -80.0]))
    assert hc.ang2pix_nest(0, ra, dec).tolist() == [0, 4, 8]


def test_ang2pix_nest_is_hierarchical():
    """A pixel at order k + 1 lies inside its parent at order k (the defining NESTED property)."""
    rng = np.random.default_rng(1)
    ra = rng.uniform(0, 2 * np.pi, 5000)
    dec = np.arcsin(rng.uniform(-1, 1, 5000))
    for order in (3, 8, 15):
        assert np.array_equal(hc.ang2pix_nest(order + 1, ra, dec) >> 2, hc.ang2pix_nest(order, ra, dec))


def test_ang2pix_nest_pixels_have_equal_area():
    """Uniformly spread sky positions fill every pixel evenly - HEALPix pixels are equal-area."""
    rng = np.random.default_rng(2)
    n = 400_000
    ra = rng.uniform(0, 2 * np.pi, n)
    dec = np.arcsin(rng.uniform(-1, 1, n))
    counts = np.bincount(hc.ang2pix_nest(2, ra, dec), minlength=192)
    assert len(counts) == 192
    expected = n / 192
    assert counts.min() > expected - 5 * math.sqrt(expected)
    assert counts.max() < expected + 5 * math.sqrt(expected)


# ---------------------------------------------------------------------------
# Image geometry
# ---------------------------------------------------------------------------


def test_tan_grid_is_centred_north_up_east_left():
    """The grid is centred on the target, declination grows upwards and RA to the left."""
    ra, dec = hc.tan_grid(100.0, 20.0, 1.0, 101)
    assert math.degrees(ra[50, 50]) == pytest.approx(100.0)
    assert math.degrees(dec[50, 50]) == pytest.approx(20.0)
    assert dec[0, 50] > dec[100, 50]
    assert ra[50, 0] > ra[50, 100]


def test_tan_grid_spans_the_requested_field():
    """Edge pixel centres along the equator are one field of view apart, minus one pixel."""
    ra, _ = hc.tan_grid(10.0, 0.0, 2.0, 200)
    span = math.degrees(ra[100, 0] - ra[100, 199])
    assert span == pytest.approx(2.0 * 199 / 200, rel=1e-3)


def test_tan_grid_handles_the_pole():
    """A grid centred on the celestial pole yields valid coordinates, the corners furthest away."""
    ra, dec = hc.tan_grid(0.0, 90.0, 10.0, 64)
    assert np.isfinite(ra).all() and np.isfinite(dec).all()
    # Corner pixel centre: 31.5 pixels from the centre along both axes, gnomonic distance.
    corner_rho = math.hypot(31.5, 31.5) * math.radians(10.0) / 64
    assert math.degrees(dec.min()) == pytest.approx(90.0 - math.degrees(math.atan(corner_rho)))


@pytest.mark.parametrize(
    'fov, size, expected',
    [(0.5, 400, 7), (45.0, 1000, 2), (0.25, 1000, 9), (0.01, 1000, 9)],
)
def test_tile_order_matches_output_resolution(fov, size, expected):
    """The tile order is the shallowest whose pixels are not coarser than an output pixel."""
    assert hc.tile_order_for(fov, size) == expected


def test_tile_url_follows_hips_layout():
    """Tiles are grouped by ten thousand in Dir folders."""
    assert hc.tile_url(MIRROR + '/', 7, 175526) == f'{MIRROR}/Norder7/Dir170000/Npix175526.jpg'
    assert hc.tile_url(MIRROR, 3, 42) == f'{MIRROR}/Norder3/Dir0/Npix42.jpg'


# ---------------------------------------------------------------------------
# render_cutout
# ---------------------------------------------------------------------------


def test_render_cutout_matches_hips2fits_on_real_tile():
    """A cut-out rebuilt from a real DSS2 tile matches the image hips2fits made of the same field.

    The reference is the centre of a hips2fits image of M83; the tile is the order-7 DSS2
    colour tile covering it. A wrong in-tile orientation (rows and columns swapped or
    mirrored) drops the correlation close to zero.
    """
    with open(os.path.join(FIXTURES, 'hips_dss2_norder7_npix175526.jpg'), 'rb') as f:
        tile_bytes = f.read()
    reference = np.asarray(Image.open(os.path.join(FIXTURES, 'hips2fits_m83_ref_0.1deg_80px.jpg')).convert('L'))

    def fake_get(url, timeout=None):
        assert url == hc.tile_url(MIRROR, 7, M83_TILE)
        return _tile_response(content=tile_bytes)

    with patch.object(hc.requests, 'get', side_effect=fake_get):
        data = hc.render_cutout(MIRROR, M83_RA, M83_DEC, 0.1, 80)

    rendered = np.asarray(Image.open(io.BytesIO(data)).convert('L'))
    assert rendered.shape == reference.shape
    assert _correlation(rendered, reference) > 0.9
    assert _correlation(rendered[:, ::-1], reference) < 0.5


def test_render_cutout_returns_a_jpeg_of_the_requested_size():
    """The output is a size x size JPEG painted from the tiles."""
    with patch.object(hc.requests, 'get', return_value=_tile_response((200, 100, 50))):
        data = hc.render_cutout(MIRROR, 10.0, 20.0, 1.0, 64)

    image = Image.open(io.BytesIO(data))
    assert image.format == 'JPEG'
    assert image.size == (64, 64)
    r, g, b = np.asarray(image.convert('RGB')).reshape(-1, 3).mean(axis=0)
    assert abs(r - 200) < 6 and abs(g - 100) < 6 and abs(b - 50) < 6


def test_render_cutout_leaves_missing_tiles_black():
    """A tile the mirror does not have (404) is left black instead of failing the image."""
    urls = sorted(
        hc.tile_url(MIRROR, hc.tile_order_for(8.0, 512), int(t))
        for t in np.unique(hc.ang2pix_nest(hc.tile_order_for(8.0, 512) + 9, *hc.tan_grid(10.0, 20.0, 8.0, 512)) >> 18)
    )
    assert len(urls) > 1

    def fake_get(url, timeout=None):
        return _tile_response((255, 255, 255)) if url == urls[0] else _tile_response(status=404)

    with patch.object(hc.requests, 'get', side_effect=fake_get):
        data = hc.render_cutout(MIRROR, 10.0, 20.0, 8.0, 512)

    values = np.asarray(Image.open(io.BytesIO(data)).convert('L'))
    assert values.max() > 200 and values.min() < 20


def test_render_cutout_raises_when_mirror_has_no_tile():
    """A mirror with none of the tiles (wrong or emptied base URL) is a failure."""
    with patch.object(hc.requests, 'get', return_value=_tile_response(status=404)):
        with pytest.raises(requests.RequestException):
            hc.render_cutout(MIRROR, 10.0, 20.0, 1.0, 32)


def test_render_cutout_raises_on_server_error():
    """A 5xx answer from the mirror propagates as a request failure."""
    with patch.object(hc.requests, 'get', return_value=_tile_response(status=503)):
        with pytest.raises(requests.RequestException):
            hc.render_cutout(MIRROR, 10.0, 20.0, 1.0, 32)


def test_render_cutout_raises_on_undecodable_tile():
    """A tile that is not an image (an HTML error page served with 200) is a failure."""
    with patch.object(hc.requests, 'get', return_value=_tile_response(content=b'<html>maintenance</html>')):
        with pytest.raises(requests.RequestException):
            hc.render_cutout(MIRROR, 10.0, 20.0, 1.0, 32)
