"""Tests for the framing simulator's sensor geometry (equipment/framing.py)."""

import json
import sys
import types
from pathlib import Path

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from equipment import framing

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


def _rated(combination_id, verdict, fill_ratio):
    return {'combination_id': combination_id, 'verdict': verdict, 'fill_ratio': fill_ratio}


def test_pick_default_frame_prefers_good_fit_closest_to_ideal():
    """Among good fits, the one whose fill is closest to the ideal wins, not the widest."""
    frames = [
        _rated('wide', framing.VERDICT_GOOD, 0.10),
        _rated('ideal', framing.VERDICT_GOOD, 0.40),
        _rated('tight', framing.VERDICT_TIGHT, 0.65),
    ]

    assert framing.pick_default_frame(frames) == 'ideal'


def test_pick_default_frame_measures_closeness_on_a_log_scale():
    """Half and double the ideal are equally far; a fill slightly closer in ratio wins."""
    frames = [_rated('low', framing.VERDICT_GOOD, 0.17), _rated('high', framing.VERDICT_GOOD, 0.60)]

    # 0.35 / 0.17 = 2.06, 0.60 / 0.35 = 1.71: the higher fill is the closer one.
    assert framing.pick_default_frame(frames) == 'high'


def test_pick_default_frame_falls_back_to_tight_then_any_rated():
    """Without a good fit a tight one is used; without either, the closest to the ideal."""
    tight = [_rated('small', framing.VERDICT_SMALL, 0.05), _rated('tight', framing.VERDICT_TIGHT, 0.9)]
    neither = [_rated('small', framing.VERDICT_SMALL, 0.02), _rated('large', framing.VERDICT_TOO_LARGE, 1.2)]

    assert framing.pick_default_frame(tight) == 'tight'
    # 1.2 / 0.35 = 3.4, 0.35 / 0.02 = 17.5.
    assert framing.pick_default_frame(neither) == 'large'


def test_pick_default_frame_without_fill_ratio_uses_first_frame():
    """A target of unknown size has no best fit: the first (widest) frame is selected."""
    frames = [_rated('widest', framing.VERDICT_UNKNOWN, None), _rated('narrow', framing.VERDICT_UNKNOWN, None)]

    assert framing.pick_default_frame(frames) == 'widest'


def test_pick_default_frame_without_frames_is_none():
    """No frame, no default."""
    assert framing.pick_default_frame([]) is None


@pytest.mark.parametrize(
    ('telescope', 'camera', 'combination', 'reason'),
    [
        (_TELESCOPE, None, _COMBINATION, framing.REASON_NO_CAMERA),
        (_TELESCOPE, {**_CAMERA, 'pixel_size_um': None}, _COMBINATION, framing.REASON_CAMERA_INCOMPLETE),
        ({'id': 'tel-1', 'name': 'No focal'}, _CAMERA, _COMBINATION, framing.REASON_NO_FOCAL_LENGTH),
        (None, _CAMERA, {'id': 'combo-3', 'name': 'No lens', 'camera_id': 'cam-1'}, framing.REASON_NO_FOCAL_LENGTH),
    ],
)
def test_list_unframeable_names_what_is_missing(telescope, camera, combination, reason):
    """Each combination left out of the simulator comes with the reason it cannot be framed."""
    telescopes = {'tel-1': telescope} if telescope else {}
    cameras = {'cam-1': camera} if camera else {}

    assert framing.list_unframeable([combination], telescopes, cameras) == [
        {
            'combination_id': combination['id'],
            'combination_name': combination['name'],
            'reason': reason,
            'is_own': True,
        }
    ]


def test_list_unframeable_skips_frameable_and_flags_shared():
    """A complete combination is not listed; a shared one is listed as not the user's own."""
    shared_visual = {'id': 'combo-9', 'name': 'Club Dob', 'telescope_id': 'tel-1', 'owner_id': 'someone-else'}

    unframeable = framing.list_unframeable([_COMBINATION, shared_visual], {'tel-1': _TELESCOPE}, {'cam-1': _CAMERA})

    assert [(item['combination_id'], item['is_own']) for item in unframeable] == [('combo-9', False)]


def test_build_frame_keeps_portrait_sensor_orientation():
    """A camera that records in portrait (short side as width) gives a field taller than wide."""
    portrait = {**_CAMERA, 'sensor_width_mm': 10.0, 'sensor_height_mm': 20.0}

    frame = framing.build_frame(_COMBINATION, _TELESCOPE, portrait, size_arcmin=None)

    assert frame['fov_h_deg'] < frame['fov_v_deg']
    assert frame['half_width_tan'] == pytest.approx(0.005)
    assert frame['half_height_tan'] == pytest.approx(0.01)


def _smart_telescope_presets():
    """Telescope presets bundling their own camera, from static/data/equipment_presets.json."""
    path = Path(__file__).resolve().parents[2] / 'static' / 'data' / 'equipment_presets.json'
    presets = json.loads(path.read_text(encoding='utf-8'))
    return [preset for preset in presets['telescopes'] if preset.get('bundle')]


@pytest.mark.parametrize('preset', _smart_telescope_presets(), ids=lambda preset: preset['id'])
def test_every_smart_telescope_preset_can_be_framed(preset):
    """The combination a smart telescope preset creates has everything the simulator needs."""
    cameras = [item for item in preset['bundle'] if item['kind'] == 'camera']
    assert len(cameras) == 1, 'a bundle carries exactly one imaging camera'
    telescope = {'id': 'tel', 'name': preset['label'], 'focal_length_mm': preset['focal_length_mm']}

    frame = framing.build_frame({'id': 'combo', 'name': preset['label']}, telescope, cameras[0], size_arcmin=10.0)

    assert frame is not None
    assert frame['verdict'] != framing.VERDICT_UNKNOWN


@pytest.mark.parametrize(
    'preset', [p for p in _smart_telescope_presets() if p['manufacturer'] == 'ZWO'], ids=lambda preset: preset['id']
)
def test_seestar_presets_record_in_portrait(preset):
    """Seestar images come out in portrait: the built-in camera's width is its short side."""
    camera = next(item for item in preset['bundle'] if item['kind'] == 'camera')

    assert camera['sensor_width_mm'] < camera['sensor_height_mm']
    assert camera['resolution_w'] < camera['resolution_h']
