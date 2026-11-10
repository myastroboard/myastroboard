"""Tests for the framing simulator's sensor geometry (equipment/framing.py)."""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from equipment import framing  # type: ignore[import-not-found]

# A 1000 mm telescope with a 20 x 10 mm sensor: 1.146 x 0.573 degrees, 68.76 x 34.38 arcmin.
_TELESCOPE = {'id': 'tel-1', 'name': 'Newton 200/1000', 'focal_length_mm': 1000, 'effective_focal_length': 1000}
_CAMERA = {'id': 'cam-1', 'name': 'Cam', 'sensor_width_mm': 20.0, 'sensor_height_mm': 10.0, 'pixel_size_um': 5.0}
_COMBINATION = {'id': 'combo-1', 'name': 'Newton + Cam', 'telescope_id': 'tel-1', 'camera_id': 'cam-1'}


def test_build_frame_reports_field_scale_and_tangent_half_extent():
    """A complete combination yields its field of view, image scale and tangent-plane half extent."""
    frame = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=None)

    assert frame is not None
    assert frame['combination_id'] == 'combo-1'
    assert frame['combination_name'] == 'Newton + Cam'
    assert frame['telescope_name'] == 'Newton 200/1000'
    assert frame['fov_h_deg'] == pytest.approx(1.146, abs=1e-3)
    assert frame['fov_v_deg'] == pytest.approx(0.573, abs=1e-3)
    assert frame['image_scale_arcsec_per_px'] == pytest.approx(1.0313, abs=1e-4)
    assert frame['half_width_tan'] == pytest.approx(0.01)
    assert frame['half_height_tan'] == pytest.approx(0.005)


def test_build_frame_without_size_has_unknown_verdict():
    """A target of unknown size gets no fill ratio, pixel size or mosaic estimate."""
    frame = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=None)

    assert frame['verdict'] == framing.VERDICT_UNKNOWN
    assert frame['fill_ratio'] is None
    assert frame['target_size_px'] is None
    assert frame['mosaic_columns'] is None and frame['mosaic_rows'] is None


def test_build_frame_uses_effective_focal_length_over_native():
    """A reducer changes the field: the effective focal length wins over the native one."""
    reduced = {**_TELESCOPE, 'effective_focal_length': 500}
    frame = framing.build_frame(_COMBINATION, reduced, _CAMERA, size_arcmin=None)

    assert frame['focal_length_mm'] == 500
    assert frame['half_width_tan'] == pytest.approx(0.02)


def test_build_frame_camera_only_uses_lens_focal_length():
    """A camera-only combination is framed with the lens declared on the combination."""
    combination = {'id': 'combo-2', 'name': 'DSLR 135', 'camera_id': 'cam-1', 'lens_focal_length_mm': 135}
    frame = framing.build_frame(combination, None, _CAMERA, size_arcmin=None)

    assert frame is not None
    assert frame['telescope_name'] is None
    assert frame['focal_length_mm'] == 135
    assert frame['half_width_tan'] == pytest.approx(20.0 / 270.0)


@pytest.mark.parametrize(
    ('telescope', 'camera', 'combination'),
    [
        (_TELESCOPE, None, _COMBINATION),
        (_TELESCOPE, {**_CAMERA, 'sensor_width_mm': None}, _COMBINATION),
        (_TELESCOPE, {**_CAMERA, 'pixel_size_um': 0}, _COMBINATION),
        (_TELESCOPE, {**_CAMERA, 'sensor_height_mm': 'abc'}, _COMBINATION),
        ({'id': 'tel-1', 'name': 'No focal'}, _CAMERA, _COMBINATION),
        (None, _CAMERA, {'id': 'combo-3', 'name': 'No lens', 'camera_id': 'cam-1'}),
    ],
)
def test_build_frame_returns_none_when_optics_are_incomplete(telescope, camera, combination):
    """Without a sensor, a pixel size or a focal length there is nothing to draw."""
    assert framing.build_frame(combination, telescope, camera, size_arcmin=30.0) is None


@pytest.mark.parametrize(
    ('size_arcmin', 'expected'),
    [
        (2.0, framing.VERDICT_SMALL),  # 2 / 34.38 = 0.06
        (10.0, framing.VERDICT_GOOD),  # 0.29
        (30.0, framing.VERDICT_TIGHT),  # 0.87
        (60.0, framing.VERDICT_TOO_LARGE),  # 1.75
    ],
)
def test_build_frame_verdict_follows_fill_of_short_side(size_arcmin, expected):
    """The verdict is driven by the target size against the short side of the field."""
    frame = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=size_arcmin)

    assert frame['verdict'] == expected
    assert frame['fill_ratio'] == pytest.approx(size_arcmin / 34.38, abs=2e-3)


def test_build_frame_reports_target_size_in_pixels():
    """A 10 arcmin target at 1.0313 arcsec/px spans about 582 pixels."""
    frame = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=10.0)

    assert frame['target_size_px'] == 582


def test_build_frame_estimates_mosaic_only_when_too_large():
    """A mosaic grid is estimated for a target larger than the field, and only then."""
    fitting = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=10.0)
    too_large = framing.build_frame(_COMBINATION, _TELESCOPE, _CAMERA, size_arcmin=120.0)

    assert fitting['mosaic_columns'] is None and fitting['mosaic_rows'] is None
    # 120 arcmin over a 68.76 x 34.38 arcmin field with 15% overlap.
    assert (too_large['mosaic_columns'], too_large['mosaic_rows']) == (2, 4)


def test_estimate_mosaic_grid_covers_the_target():
    """The estimated grid, with its overlap, spans at least the target on both axes."""
    columns, rows = framing.estimate_mosaic_grid(200.0, 60.0, 40.0)

    assert 60.0 + (columns - 1) * 60.0 * 0.85 >= 200.0
    assert 40.0 + (rows - 1) * 40.0 * 0.85 >= 200.0
    # One panel fewer would not cover it.
    assert 60.0 + (columns - 2) * 60.0 * 0.85 < 200.0
    assert 40.0 + (rows - 2) * 40.0 * 0.85 < 200.0


def test_classify_fit_boundaries():
    """The good band is 10% to 60% of the short side, inclusive; up to 100% is tight."""
    assert framing.classify_fit(10.0, 100.0)[0] == framing.VERDICT_GOOD
    assert framing.classify_fit(60.0, 100.0)[0] == framing.VERDICT_GOOD
    assert framing.classify_fit(100.0, 100.0)[0] == framing.VERDICT_TIGHT
    assert framing.classify_fit(100.1, 100.0)[0] == framing.VERDICT_TOO_LARGE
    assert framing.classify_fit(0.0, 100.0) == (framing.VERDICT_UNKNOWN, None)
    assert framing.classify_fit(10.0, 0.0) == (framing.VERDICT_UNKNOWN, None)


def test_build_frames_skips_unframeable_and_sorts_widest_first():
    """Only combinations with complete optics are returned, widest field first."""
    wide_camera = {
        'id': 'cam-2',
        'name': 'Wide',
        'sensor_width_mm': 36.0,
        'sensor_height_mm': 24.0,
        'pixel_size_um': 4.0,
    }
    combinations = [
        _COMBINATION,
        {'id': 'combo-2', 'name': 'Wide', 'telescope_id': 'tel-1', 'camera_id': 'cam-2'},
        {'id': 'combo-3', 'name': 'Visual only', 'telescope_id': 'tel-1'},
        {'id': 'combo-4', 'name': 'Unknown gear', 'telescope_id': 'gone', 'camera_id': 'gone'},
    ]
    frames = framing.build_frames(
        combinations, {'tel-1': _TELESCOPE}, {'cam-1': _CAMERA, 'cam-2': wide_camera}, size_arcmin=10.0
    )

    assert [frame['combination_id'] for frame in frames] == ['combo-2', 'combo-1']


def test_build_frames_survives_one_malformed_combination(monkeypatch):
    """A combination whose optics raise must not hide the others."""
    real_build_frame = framing.build_frame

    def flaky(combination, telescope, camera, size_arcmin):
        if combination['id'] == 'bad':
            raise ZeroDivisionError
        return real_build_frame(combination, telescope, camera, size_arcmin)

    monkeypatch.setattr(framing, 'build_frame', flaky)
    combinations = [{'id': 'bad', 'telescope_id': 'tel-1', 'camera_id': 'cam-1'}, _COMBINATION]
    frames = framing.build_frames(combinations, {'tel-1': _TELESCOPE}, {'cam-1': _CAMERA}, size_arcmin=None)

    assert [frame['combination_id'] for frame in frames] == ['combo-1']
