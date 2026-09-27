"""Tests for utils.image_privacy - metadata stripping of uploaded pictures."""

import io

import pytest
from PIL import Image, PngImagePlugin

from utils.image_privacy import strip_image_metadata

_ORIENTATION = 0x0112
_GPS_IFD = 0x8825


def _exif(orientation=None):
    exif = Image.Exif()
    exif[0x010F] = 'CameraMaker'
    exif[0xA431] = 'SERIAL-12345'  # BodySerialNumber
    exif.get_ifd(_GPS_IFD)[2] = (48.0, 51.0, 24.0)  # GPSLatitude
    if orientation:
        exif[_ORIENTATION] = orientation
    return exif


def _image():
    return Image.new('RGB', (32, 24), (10, 120, 200))


def _encode(fmt, **kwargs):
    buffer = io.BytesIO()
    _image().save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def _pixels(data):
    with Image.open(io.BytesIO(data)) as img:
        return img.tobytes()


class TestJpeg:
    @pytest.mark.parametrize('progressive', [False, True])
    def test_removes_gps_serial_and_comment_without_touching_pixels(self, progressive):
        raw = _encode('JPEG', exif=_exif(), comment=b'owner name', progressive=progressive)
        out = strip_image_metadata(raw)

        assert b'SERIAL-12345' not in out
        assert b'owner name' not in out
        with Image.open(io.BytesIO(out)) as img:
            assert not img.getexif().get_ifd(_GPS_IFD)
        assert _pixels(out) == _pixels(raw)

    def test_keeps_orientation_only(self):
        out = strip_image_metadata(_encode('JPEG', exif=_exif(orientation=6)))
        with Image.open(io.BytesIO(out)) as img:
            assert dict(img.getexif()) == {_ORIENTATION: 6}

    def test_keeps_icc_profile(self):
        icc = b'\x00' * 128
        out = strip_image_metadata(_encode('JPEG', exif=_exif(), icc_profile=icc))
        with Image.open(io.BytesIO(out)) as img:
            assert img.info.get('icc_profile') == icc

    def test_drops_data_appended_after_end_of_image(self):
        raw = _encode('JPEG') + b'\xff\xd8secondary-image-with-gps'
        out = strip_image_metadata(raw)
        assert out.endswith(b'\xff\xd9')
        assert b'secondary' not in out

    def test_is_idempotent(self):
        once = strip_image_metadata(_encode('JPEG', exif=_exif(orientation=3)))
        assert strip_image_metadata(once) == once

    def test_rejects_corrupt_segment_structure(self):
        with pytest.raises(ValueError):
            strip_image_metadata(b'\xff\xd8\xff' + b'\x00' * 20)


class TestPng:
    def test_removes_text_and_exif_chunks_without_touching_pixels(self):
        info = PngImagePlugin.PngInfo()
        info.add_text('Author', 'Jane Observer')
        raw = _encode('PNG', pnginfo=info, exif=_exif())
        out = strip_image_metadata(raw)

        assert b'Jane Observer' not in out
        assert b'SERIAL-12345' not in out
        assert _pixels(out) == _pixels(raw)

    def test_rejects_truncated_chunk(self):
        raw = _encode('PNG')
        with pytest.raises(ValueError):
            strip_image_metadata(raw[:8] + b'\x00\x00\xff\xffIHDR')


class TestWebp:
    @pytest.mark.parametrize('lossless', [False, True])
    def test_removes_exif_and_xmp_keeping_orientation(self, lossless):
        raw = _encode('WEBP', exif=_exif(orientation=8), xmp=b'<x:xmpmeta>secret</x:xmpmeta>', lossless=lossless)
        out = strip_image_metadata(raw)

        assert b'SERIAL-12345' not in out
        assert b'secret' not in out
        with Image.open(io.BytesIO(out)) as img:
            img.load()
            assert dict(img.getexif()) == {_ORIENTATION: 8}
        assert _pixels(out) == _pixels(raw)

    def test_without_metadata_is_unchanged(self):
        raw = _encode('WEBP', lossless=True)
        assert strip_image_metadata(raw) == raw


def test_gif_is_returned_as_is():
    raw = _encode('GIF')
    assert strip_image_metadata(raw) == raw


def test_rejects_non_image_data():
    with pytest.raises(ValueError):
        strip_image_metadata(b'this is not a picture')
