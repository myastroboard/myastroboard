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


class TestMalformedInput:
    """Hand-built files exercising the parsers' edge cases: odd but valid ones pass, broken ones raise."""

    SOI = b'\xff\xd8'
    EOI = b'\xff\xd9'

    def test_unreadable_exif_is_dropped(self, monkeypatch):
        from utils import image_privacy

        def broken_load(self, data):
            raise SyntaxError('not a TIFF')

        monkeypatch.setattr(image_privacy.Image.Exif, 'load', broken_load)
        assert image_privacy._read_orientation(b'Exif\x00\x00II*\x00') is None

    def test_jpeg_standalone_markers_and_entropy_bytes_are_kept(self):
        sos = b'\xff\xda\x00\x02'
        scan = b'\x12\xff\x00\x34\xff\xd0\x56\xff\xff\xd1\x78'
        data = self.SOI + b'\xff\xd0' + sos + scan + self.EOI
        assert strip_image_metadata(data) == data

    def test_jpeg_scan_without_end_of_image_is_kept(self):
        data = self.SOI + b'\xff\xda\x00\x02' + b'\x12\x34\x56'
        assert strip_image_metadata(data) == data

    def test_jpeg_scan_ending_on_a_lone_ff_is_kept(self):
        data = self.SOI + b'\xff\xda\x00\x02' + b'\x12\xff'
        assert strip_image_metadata(data) == data

    @pytest.mark.parametrize(
        'tail, message',
        [
            (b'', 'Malformed'),
            (b'\x00', 'Malformed'),
            (b'\xff\xff', 'Truncated'),
            (b'\xff\xe0\x00', 'Truncated'),
            (b'\xff\xe0\x00\x01', 'Invalid JPEG segment length'),
        ],
    )
    def test_broken_jpeg_is_rejected(self, tail, message):
        with pytest.raises(ValueError, match=message):
            strip_image_metadata(self.SOI + tail)

    def test_png_chunk_past_the_end_is_rejected(self):
        signature = b'\x89PNG\r\n\x1a\n'
        chunk = (1000).to_bytes(4, 'big') + b'IHDR' + b'\x00' * 8
        with pytest.raises(ValueError, match='Invalid PNG chunk length'):
            strip_image_metadata(signature + chunk)

    @staticmethod
    def _riff(body):
        return b'RIFF' + (len(body) + 4).to_bytes(4, 'little') + b'WEBP' + body

    def test_webp_chunk_past_the_end_is_rejected(self):
        with pytest.raises(ValueError, match='Invalid WebP chunk length'):
            strip_image_metadata(self._riff(b'VP8L' + (1000).to_bytes(4, 'little') + b'\x00' * 4))

    def test_webp_without_chunks_is_rejected(self):
        with pytest.raises(ValueError, match='WebP without chunks'):
            strip_image_metadata(self._riff(b''))

    def test_webp_extended_header_without_exif_clears_the_flags(self):
        xmp = b'<x:xmpmeta>owner</x:xmpmeta>'
        out = strip_image_metadata(_encode('WEBP', lossless=True, xmp=xmp))
        assert b'owner' not in out
        assert _pixels(out) == _pixels(_encode('WEBP', lossless=True))
