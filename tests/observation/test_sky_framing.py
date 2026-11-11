"""Tests for the framing simulator's target resolution and image cache (observation/sky_framing.py)."""

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
import requests as _req_module

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from observation import object_info as oi  # type: ignore[import-not-found]
from observation import sky_framing  # type: ignore[import-not-found]
from skytonight.skytonight_models import SkyTonightCoordinates, SkyTonightTarget  # type: ignore[import-not-found]


def _target(target_id, ra_hours, dec_degrees, category='deep_sky', object_type='Galaxy', name=None, size=None):
    return SkyTonightTarget(
        target_id=target_id,
        category=category,
        object_type=object_type,
        preferred_name=name or target_id,
        catalogue_names={'OpenNGC': name or target_id},
        coordinates=SkyTonightCoordinates(ra_hours=ra_hours, dec_degrees=dec_degrees),
        size_arcmin=size,
    )


def _patch_dataset(monkeypatch, targets):
    monkeypatch.setattr(
        sky_framing.skytonight_targets,
        'load_targets_dataset',
        lambda *_a, **_k: {'targets': targets},
    )


@pytest.fixture(autouse=True)
def _reset_hips2fits_backoff(monkeypatch):
    """Keep one test's simulated CDS failure from backing off the next one.

    The backoff is a module-level dict mirrored to a file shared by every worker; both
    are isolated here, as in test_object_info.
    """
    oi._backoff_until.clear()
    monkeypatch.setattr(oi, '_load_backoff_state', lambda: {})
    monkeypatch.setattr(oi, '_save_backoff_state', lambda: None)
    yield
    oi._backoff_until.clear()


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------


def test_resolve_target_from_dataset_returns_degrees_size_and_image_key(monkeypatch):
    """A dataset target resolves to degrees, its apparent size and the image key."""
    _patch_dataset(monkeypatch, [_target('NGC0224', 0.712314, 41.26875, name='M 31', size=177.8)])

    result = sky_framing.resolve_target('M31')

    assert result['supported'] is True
    assert result['target_id'] == 'NGC0224'
    assert result['name'] == 'M 31'
    assert result['ra_deg'] == pytest.approx(10.68471)
    assert result['dec_deg'] == pytest.approx(41.26875)
    assert result['size_arcmin'] == pytest.approx(177.8)
    assert result['image_key'] == '10.684710_41.268750'


def test_resolve_target_matches_exact_target_id(monkeypatch):
    """The dataset target id is accepted as an identifier."""
    _patch_dataset(monkeypatch, [_target('NGC7000', 20.98, 44.33, name='North America Nebula')])

    assert sky_framing.resolve_target('NGC7000')['name'] == 'North America Nebula'


@pytest.mark.parametrize('size', [None, 0.0, -3.0])
def test_resolve_target_reports_unknown_size_as_none(monkeypatch, size):
    """A missing or non-positive catalogue size is reported as unknown, never as zero."""
    _patch_dataset(monkeypatch, [_target('NGC1', 1.0, 10.0, size=size)])

    assert sky_framing.resolve_target('NGC1')['size_arcmin'] is None


@pytest.mark.parametrize('category', ['bodies', 'comets'])
def test_resolve_target_rejects_moving_dataset_targets(monkeypatch, category):
    """A planet or a comet has no fixed background: it is reported as a moving target."""
    _patch_dataset(monkeypatch, [_target('mover', 5.0, 20.0, category=category, name='Mover')])

    result = sky_framing.resolve_target('Mover')

    assert result == {'supported': False, 'reason': 'moving_target', 'name': 'Mover'}


def test_resolve_target_without_coordinates_is_not_found(monkeypatch):
    """A dataset target that carries no coordinates cannot be framed."""
    target = _target('NGC2', 1.0, 10.0, name='No coords')
    target = SkyTonightTarget(
        target_id=target.target_id,
        category=target.category,
        object_type=target.object_type,
        preferred_name=target.preferred_name,
        catalogue_names=target.catalogue_names,
        coordinates=None,
    )
    _patch_dataset(monkeypatch, [target])

    result = sky_framing.resolve_target('No coords')

    assert result['supported'] is False and result['reason'] == 'not_found'


def test_resolve_target_falls_back_to_simbad_without_size(monkeypatch):
    """An object outside the dataset is resolved through SIMBAD, with an unknown size."""
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(
        sky_framing.object_info,
        '_resolve_via_simbad',
        lambda *_a, **_k: {'id': 'Vega', 'name': 'Vega', 'type': 'Star', 'ra': 279.2347, 'dec': 38.7837},
    )

    result = sky_framing.resolve_target('Vega')

    assert result['supported'] is True
    assert result['ra_deg'] == pytest.approx(279.2347)
    assert result['size_arcmin'] is None
    assert result['image_key'] == '279.234700_38.783700'


def test_resolve_target_simbad_moving_object_is_rejected(monkeypatch):
    """A SIMBAD hit typed as a solar-system object is reported as a moving target."""
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(
        sky_framing.object_info,
        '_resolve_via_simbad',
        lambda *_a, **_k: {'name': 'Ceres', 'type': 'Minor Planet', 'ra': 10.0, 'dec': 5.0},
    )

    result = sky_framing.resolve_target('Ceres')

    assert result == {'supported': False, 'reason': 'moving_target', 'name': 'Ceres'}


@pytest.mark.parametrize(
    'resolved',
    [
        None,
        {'name': 'X', 'ra': None, 'dec': 5.0},
        {'name': 'X', 'ra': 'abc', 'dec': 5.0},
        {'name': 'X', 'ra': 10.0, 'dec': 95.0},
    ],
)
def test_resolve_target_unusable_simbad_answer_is_not_found(monkeypatch, resolved):
    """No answer, missing, unparsable or out-of-range coordinates all end as not found."""
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(sky_framing.object_info, '_resolve_via_simbad', lambda *_a, **_k: resolved)

    result = sky_framing.resolve_target('X')

    assert result == {'supported': False, 'reason': 'not_found', 'name': 'X'}


# ---------------------------------------------------------------------------
# image filename
# ---------------------------------------------------------------------------


def test_image_filename_round_trips():
    """A generated filename parses back to its coordinates and field of view."""
    filename = sky_framing.image_filename(10.684708, 41.26875, 4.0)

    assert filename == '10.684708_41.268750_4.00.jpg'
    assert sky_framing.parse_image_filename(filename) == (10.684708, 41.26875, 4.0)


def test_parse_image_filename_accepts_every_ladder_step():
    """Every allowed field of view survives the filename round trip."""
    for fov in sky_framing.FOV_LADDER_DEG:
        parsed = sky_framing.parse_image_filename(sky_framing.image_filename(0.0, -45.5, fov))
        assert parsed == (0.0, -45.5, fov)


@pytest.mark.parametrize(
    'filename',
    [
        'not-a-filename.jpg',
        '../../etc/passwd',
        '10.684708_41.268750.jpg',  # object-image shape, no field of view
        '10.684708_41.268750_4.00.png',
        '10.684708_41.268750_4.0.jpg',  # one decimal only
        '10.684708_41.268750_4.01.jpg',  # not a ladder step
        '10.684708_41.268750_90.00.jpg',  # beyond the ladder
        '400.000000_41.268750_4.00.jpg',
        '10.684708_95.000000_4.00.jpg',
    ],
)
def test_parse_image_filename_rejects_invalid_names(filename):
    """Malformed names, out-of-range coordinates and free fields of view are refused."""
    assert sky_framing.parse_image_filename(filename) is None


def test_parse_image_filename_wraps_exact_360_boundary():
    """A right ascension rounded up to the literal 360.000000 wraps to 0."""
    assert sky_framing.parse_image_filename('360.000000_5.000000_1.00.jpg') == (0.0, 5.0, 1.0)


# ---------------------------------------------------------------------------
# ensure_cached_image
# ---------------------------------------------------------------------------


def test_ensure_cached_image_fetches_once_with_requested_field(monkeypatch, tmp_path):
    """A missing image is downloaded at the requested field and size, then written to the cache."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_content.return_value = [b'fake-jpeg-bytes']

    with patch('observation.object_info.requests.get', return_value=mock_resp) as mock_get:
        result = sky_framing.ensure_cached_image(10.684708, 41.26875, 4.0)

    expected_path = os.path.join(str(tmp_path), '10.684708_41.268750_4.00.jpg')
    assert result == expected_path
    mock_get.assert_called_once()
    url = mock_get.call_args.args[0]
    assert 'fov=4.000' in url
    assert f'width={sky_framing.IMAGE_SIZE_PX}' in url and f'height={sky_framing.IMAGE_SIZE_PX}' in url
    assert 'projection=TAN' in url
    assert mock_get.call_args.kwargs['timeout'] == (oi.CONNECT_TIMEOUT, 30)
    with open(expected_path, 'rb') as f:
        assert f.read() == b'fake-jpeg-bytes'


def test_ensure_cached_image_serves_from_disk_without_network(monkeypatch, tmp_path):
    """An image already in the cache is returned without calling CDS."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    cached = tmp_path / '10.684708_41.268750_4.00.jpg'
    cached.write_bytes(b'already-cached')

    with patch('observation.object_info.requests.get') as mock_get:
        result = sky_framing.ensure_cached_image(10.684708, 41.26875, 4.0)

    assert result == str(cached)
    mock_get.assert_not_called()


def test_ensure_cached_image_returns_none_on_upstream_failure(monkeypatch, tmp_path):
    """A CDS failure yields None and leaves no partial file behind."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))

    with patch('observation.object_info.requests.get', side_effect=_req_module.RequestException('timeout')):
        result = sky_framing.ensure_cached_image(10.684708, 41.26875, 4.0)

    assert result is None
    assert os.listdir(str(tmp_path)) == []


def test_ensure_cached_image_respects_shared_hips2fits_backoff(monkeypatch, tmp_path):
    """After CDS and every HiPS mirror failed once, the next image makes no request at all."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))

    with patch('observation.object_info.requests.get', side_effect=_req_module.RequestException('down')) as mock_get:
        assert sky_framing.ensure_cached_image(10.0, 20.0, 1.0) is None
        calls_after_first_image = mock_get.call_count
        assert sky_framing.ensure_cached_image(30.0, 40.0, 2.0) is None

    assert calls_after_first_image > 0
    assert mock_get.call_count == calls_after_first_image


def test_ensure_cached_image_falls_back_to_hips_mirror(monkeypatch, tmp_path):
    """When hips2fits fails, the background is rendered from a mirror at the requested field and size."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    rendered = []

    def fake_render(base_url, ra, dec, fov, size, timeout=None):
        rendered.append((base_url, ra, dec, fov, size))
        return b'mirror-jpeg'

    with patch('observation.object_info.requests.get', side_effect=_req_module.RequestException('down')):
        with patch('observation.hips_cutout.render_cutout', side_effect=fake_render):
            result = sky_framing.ensure_cached_image(10.684708, 41.26875, 4.0)

    assert result == os.path.join(str(tmp_path), '10.684708_41.268750_4.00.jpg')
    assert rendered == [(oi.DSS2_HIPS_MIRRORS[0][1], 10.684708, 41.26875, 4.0, sky_framing.IMAGE_SIZE_PX)]
    with open(result, 'rb') as f:
        assert f.read() == b'mirror-jpeg'


# ---------------------------------------------------------------------------
# prune_cache
# ---------------------------------------------------------------------------


def test_prune_cache_removes_oldest_files_down_to_eighty_percent(monkeypatch, tmp_path):
    """Once over the limit, the oldest images go until the cache is back under 80% of it."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    for index in range(5):
        path = tmp_path / f'{index}.jpg'
        path.write_bytes(b'x' * 100)
        os.utime(path, (1000 + index, 1000 + index))

    removed = sky_framing.prune_cache(max_bytes=450)

    assert removed == 2
    assert sorted(os.listdir(str(tmp_path))) == ['2.jpg', '3.jpg', '4.jpg']


def test_prune_cache_keeps_everything_under_the_limit(monkeypatch, tmp_path):
    """A cache under its limit is left untouched."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    (tmp_path / 'a.jpg').write_bytes(b'x' * 100)

    assert sky_framing.prune_cache(max_bytes=1000) == 0
    assert os.listdir(str(tmp_path)) == ['a.jpg']


def test_prune_cache_skips_files_it_cannot_stat(monkeypatch, tmp_path):
    """A file that vanishes between the listing and the stat is left out of the size count."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    gone = tmp_path / 'gone.jpg'
    gone.write_bytes(b'x' * 5000)
    real_stat = os.stat
    monkeypatch.setattr(
        sky_framing.os,
        'stat',
        lambda path: (_ for _ in ()).throw(FileNotFoundError(path)) if path == str(gone) else real_stat(path),
    )

    assert sky_framing.prune_cache(max_bytes=1000) == 0
    assert gone.exists()


def test_prune_cache_keeps_files_it_cannot_remove(monkeypatch, tmp_path):
    """A file the OS refuses to delete stays, the next ones go, and pruning ends without raising."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    locked = tmp_path / 'locked.jpg'
    other = tmp_path / 'other.jpg'
    for index, path in enumerate((locked, other)):
        path.write_bytes(b'x' * 600)
        os.utime(path, (1000 + index, 1000 + index))
    real_remove = os.remove
    monkeypatch.setattr(
        sky_framing.os,
        'remove',
        lambda path: (_ for _ in ()).throw(PermissionError(path)) if path == str(locked) else real_remove(path),
    )

    assert sky_framing.prune_cache(max_bytes=1000) == 1
    assert locked.exists()
    assert not other.exists()


def test_prune_cache_without_directory_is_a_no_op(monkeypatch, tmp_path):
    """A cache directory that does not exist yet is not an error."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path / 'missing'))

    assert sky_framing.prune_cache() == 0


def test_cache_is_pruned_every_few_writes(monkeypatch, tmp_path):
    """The size check runs once every few downloads, not on each one."""
    monkeypatch.setattr(sky_framing, 'FRAMING_IMAGE_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(sky_framing, '_PRUNE_EVERY_WRITES', 2)
    monkeypatch.setattr(sky_framing, '_writes_since_prune', 0)
    calls = []
    monkeypatch.setattr(sky_framing, 'prune_cache', lambda *a, **k: calls.append(1) or 0)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_content.return_value = [b'bytes']

    with patch('observation.object_info.requests.get', return_value=mock_resp):
        sky_framing.ensure_cached_image(1.0, 1.0, 1.0)
        assert calls == []
        sky_framing.ensure_cached_image(2.0, 2.0, 1.0)

    assert calls == [1]
