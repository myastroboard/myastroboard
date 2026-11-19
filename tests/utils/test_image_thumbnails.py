"""Tests for utils.image_thumbnails: small WebP previews of uploaded pictures."""

import io
import os

import pytest
from PIL import Image

from utils import image_thumbnails


@pytest.fixture(autouse=True)
def _empty_cache():
    image_thumbnails.clear_cache()
    yield
    image_thumbnails.clear_cache()


def _write(path, image, fmt, **params):
    image.save(path, format=fmt, **params)
    return str(path)


def _open(data):
    return Image.open(io.BytesIO(data))


def test_preview_is_a_webp_no_larger_than_the_max_side_and_keeps_the_shape(tmp_path):
    """A large picture becomes a WebP whose long side is the limit, with the same aspect ratio."""
    path = _write(tmp_path / 'big.jpg', Image.new('RGB', (1600, 900), (40, 80, 120)), 'JPEG')

    data = image_thumbnails.thumbnail_bytes(path, max_side=400)

    assert data is not None
    preview = _open(data)
    assert preview.format == 'WEBP'
    assert max(preview.size) == 400
    assert preview.size[0] / preview.size[1] == pytest.approx(1600 / 900, rel=0.02)
    assert len(data) < os.path.getsize(path)


def test_small_picture_is_never_enlarged(tmp_path):
    """A picture already smaller than the limit keeps its own size."""
    path = _write(tmp_path / 'small.png', Image.new('RGB', (120, 80), (200, 10, 10)), 'PNG')

    preview = _open(image_thumbnails.thumbnail_bytes(path, max_side=400))

    assert preview.size == (120, 80)


def test_exif_orientation_is_applied(tmp_path):
    """A phone photo stored sideways with an orientation tag comes out upright."""
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90 degrees clockwise
    path = _write(tmp_path / 'phone.jpg', Image.new('RGB', (400, 200), (10, 10, 10)), 'JPEG', exif=exif.tobytes())

    preview = _open(image_thumbnails.thumbnail_bytes(path, max_side=100))

    assert preview.size[1] > preview.size[0]


def test_transparency_is_kept(tmp_path):
    """A picture with an alpha channel keeps it in its preview."""
    path = _write(tmp_path / 'alpha.png', Image.new('RGBA', (300, 300), (0, 0, 0, 0)), 'PNG')

    preview = _open(image_thumbnails.thumbnail_bytes(path, max_side=100))

    assert preview.mode == 'RGBA'
    assert preview.getpixel((10, 10))[3] == 0


def test_missing_or_unreadable_file_gives_none(tmp_path):
    """The caller falls back to the original file when no preview can be made."""
    broken = tmp_path / 'broken.jpg'
    broken.write_bytes(b'not a picture')

    assert image_thumbnails.thumbnail_bytes(str(tmp_path / 'missing.jpg')) is None
    assert image_thumbnails.thumbnail_bytes(str(broken)) is None


def test_preview_is_cached_until_the_file_changes(tmp_path, monkeypatch):
    """A second request reuses the preview; a rewritten file gets a new one."""
    path = _write(tmp_path / 'pic.png', Image.new('RGB', (500, 500), (1, 2, 3)), 'PNG')
    calls = []
    real_render = image_thumbnails._render

    def counting_render(file_path, max_side):
        calls.append(file_path)
        return real_render(file_path, max_side)

    monkeypatch.setattr(image_thumbnails, '_render', counting_render)

    first = image_thumbnails.thumbnail_bytes(path, max_side=100)
    second = image_thumbnails.thumbnail_bytes(path, max_side=100)
    assert first == second
    assert len(calls) == 1

    _write(tmp_path / 'pic.png', Image.new('RGB', (640, 320), (9, 9, 9)), 'PNG')
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    third = image_thumbnails.thumbnail_bytes(path, max_side=100)
    assert len(calls) == 2
    assert _open(third).size == (100, 50)


def test_cache_drops_the_oldest_previews_beyond_its_budget(tmp_path, monkeypatch):
    """The memory held by the cache stays within its byte budget."""
    monkeypatch.setattr(image_thumbnails, '_render', lambda _path, _side: b'x' * 400)
    monkeypatch.setattr(image_thumbnails, '_CACHE_MAX_BYTES', 1000)
    paths = []
    for index in range(4):
        file_path = tmp_path / f'{index}.png'
        file_path.write_bytes(bytes([index]))
        paths.append(str(file_path))

    for file_path in paths:
        image_thumbnails.thumbnail_bytes(file_path)

    assert image_thumbnails._cache_bytes <= 1000
    cached_paths = {key[0] for key in image_thumbnails._cache}
    assert os.path.realpath(paths[-1]) in cached_paths
    assert os.path.realpath(paths[0]) not in cached_paths


def test_a_preview_rendered_twice_at_once_is_counted_once():
    """Two requests rendering the same preview together keep the first copy and its size only."""
    key = ('/pictures/m31.jpg', 1, 2, 480)
    image_thumbnails._remember(key, b'first')
    image_thumbnails._remember(key, b'second, longer')

    assert image_thumbnails._cache[key] == b'first'
    assert image_thumbnails._cache_bytes == len(b'first')
