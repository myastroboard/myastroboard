"""Framing simulator - sensor geometry of equipment combinations against a target.

For each equipment combination that has a camera sensor and a focal length, this module
computes what the framing simulator draws and says: the field of view, the sensor's
half-extent in tangent-plane units (so the frontend can draw an exact rectangle on a
gnomonic sky image), the target's size in pixels, and a verdict on how the target fits.

The target resolution and the sky image live in ``observation/sky_framing.py``; this
module only knows about optics.
"""

import math
from typing import Any

from equipment import equipment_profiles

# Verdict thresholds, on the ratio "target size / short side of the field". The good
# range matches the 10-60% band the combination recommendations already use
# (blueprints/skytonight_api._fov_match_score), applied here to the short side because
# that is the side a target is cropped by.
_FILL_SMALL_BELOW = 0.10
_FILL_GOOD_UP_TO = 0.60
_FILL_TIGHT_UP_TO = 1.00

# Fill ratio the default selection aims for: the middle of the good band, where the target
# is large in the frame and still has room around it.
_FILL_IDEAL = 0.35

# Overlap assumed between neighbouring panels when estimating a mosaic grid.
_MOSAIC_OVERLAP = 0.15

VERDICT_UNKNOWN = 'unknown'
VERDICT_SMALL = 'small'
VERDICT_GOOD = 'good'
VERDICT_TIGHT = 'tight'
VERDICT_TOO_LARGE = 'too_large'

# Why a combination cannot be framed. "No camera" is a visual setup, or a smart telescope
# whose built-in camera was never added (saved without its preset bundle).
REASON_NO_CAMERA = 'no_camera'
REASON_CAMERA_INCOMPLETE = 'camera_incomplete'
REASON_NO_FOCAL_LENGTH = 'no_focal_length'


def _positive_float(value: Any) -> float | None:
    """Return *value* as a finite float greater than zero, else None."""
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def classify_fit(size_arcmin: float | None, fov_short_arcmin: float) -> tuple[str, float | None]:
    """Classify how a target of *size_arcmin* fits a field whose short side is given.

    Returns ``(verdict, fill_ratio)``. The ratio is None when the size is unknown.
    """
    if size_arcmin is None or size_arcmin <= 0 or fov_short_arcmin <= 0:
        return VERDICT_UNKNOWN, None
    ratio = size_arcmin / fov_short_arcmin
    if ratio < _FILL_SMALL_BELOW:
        return VERDICT_SMALL, ratio
    if ratio <= _FILL_GOOD_UP_TO:
        return VERDICT_GOOD, ratio
    if ratio <= _FILL_TIGHT_UP_TO:
        return VERDICT_TIGHT, ratio
    return VERDICT_TOO_LARGE, ratio


def estimate_mosaic_grid(size_arcmin: float, fov_h_arcmin: float, fov_v_arcmin: float) -> tuple[int, int]:
    """Estimate the ``(columns, rows)`` of panels needed to cover a target.

    Only the target's longest dimension is known, so it is assumed on both axes: the
    result is an upper bound for an elongated object, and is presented as an estimate.
    """
    step_h = fov_h_arcmin * (1.0 - _MOSAIC_OVERLAP)
    step_v = fov_v_arcmin * (1.0 - _MOSAIC_OVERLAP)
    columns = max(1, math.ceil((size_arcmin - fov_h_arcmin) / step_h) + 1)
    rows = max(1, math.ceil((size_arcmin - fov_v_arcmin) / step_v) + 1)
    return columns, rows


def _frame_optics(
    combination: dict[str, Any],
    telescope: dict[str, Any] | None,
    camera: dict[str, Any] | None,
) -> tuple[tuple[float, float, float, float] | None, str | None]:
    """Return ``((sensor_w, sensor_h, pixel_um, focal), None)``, or ``(None, reason)``.

    A combination can be framed when it has a camera with sensor dimensions and pixel
    size, and a focal length: the telescope's effective one, or the combination's own lens
    for a camera-only setup. The guide camera is never part of the field of view. The
    sensor is taken as the camera delivers its images: a camera that records in portrait
    is stored with its short side as the width.
    """
    if not camera:
        return None, REASON_NO_CAMERA
    sensor_w = _positive_float(camera.get('sensor_width_mm'))
    sensor_h = _positive_float(camera.get('sensor_height_mm'))
    pixel_um = _positive_float(camera.get('pixel_size_um'))
    if not (sensor_w and sensor_h and pixel_um):
        return None, REASON_CAMERA_INCOMPLETE
    if telescope:
        focal = _positive_float(telescope.get('effective_focal_length')) or _positive_float(
            telescope.get('focal_length_mm')
        )
    else:
        focal = _positive_float(combination.get('lens_focal_length_mm'))
    if not focal:
        return None, REASON_NO_FOCAL_LENGTH
    return (sensor_w, sensor_h, pixel_um, focal), None


def build_frame(
    combination: dict[str, Any],
    telescope: dict[str, Any] | None,
    camera: dict[str, Any] | None,
    size_arcmin: float | None,
) -> dict[str, Any] | None:
    """Return the framing data of one combination, or None when it cannot be framed.

    See ``_frame_optics`` for what a combination needs to be framed.
    """
    optics, _reason = _frame_optics(combination, telescope, camera)
    if optics is None or camera is None:
        return None
    sensor_w, sensor_h, pixel_um, focal = optics

    fov = equipment_profiles.calculate_fov(focal, sensor_w, sensor_h, pixel_um)
    fov_h_arcmin = fov.horizontal_fov_deg * 60.0
    fov_v_arcmin = fov.vertical_fov_deg * 60.0
    verdict, fill_ratio = classify_fit(size_arcmin, min(fov_h_arcmin, fov_v_arcmin))

    frame: dict[str, Any] = {
        'combination_id': str(combination.get('id') or ''),
        'combination_name': str(combination.get('name') or ''),
        'telescope_name': str(telescope.get('name') or '') if telescope else None,
        'camera_name': str(camera.get('name') or ''),
        'is_shared': bool(combination.get('is_shared', False)),
        'focal_length_mm': round(focal, 1),
        'fov_h_deg': fov.horizontal_fov_deg,
        'fov_v_deg': fov.vertical_fov_deg,
        'fov_diagonal_deg': fov.diagonal_fov_deg,
        'image_scale_arcsec_per_px': fov.image_scale_arcsec_per_px,
        'sampling_classification': fov.sampling_classification,
        # Half-extent of the sensor in tangent-plane units (tan of the half field): what a
        # gnomonic sky image needs to draw the sensor as an exact rectangle.
        'half_width_tan': sensor_w / (2.0 * focal),
        'half_height_tan': sensor_h / (2.0 * focal),
        'verdict': verdict,
        'fill_ratio': round(fill_ratio, 3) if fill_ratio is not None else None,
        'target_size_px': None,
        'mosaic_columns': None,
        'mosaic_rows': None,
    }
    if size_arcmin and size_arcmin > 0 and fov.image_scale_arcsec_per_px > 0:
        frame['target_size_px'] = int(round(size_arcmin * 60.0 / fov.image_scale_arcsec_per_px))
    if verdict == VERDICT_TOO_LARGE and size_arcmin:
        columns, rows = estimate_mosaic_grid(size_arcmin, fov_h_arcmin, fov_v_arcmin)
        frame['mosaic_columns'] = columns
        frame['mosaic_rows'] = rows
    return frame


def pick_default_frame(frames: list[dict[str, Any]]) -> str | None:
    """Return the ``combination_id`` of the frame the simulator selects when it opens.

    The best verdict wins (good, then tight, then anything with a known fill ratio), and
    within a verdict the frame whose fill ratio is closest to ``_FILL_IDEAL``. Closeness
    is measured on a log scale, so half and double the ideal are equally far. When no
    frame has a fill ratio (target of unknown size), the first one - the widest field,
    given how ``build_frames`` sorts - is used. None when there is no frame.
    """
    if not frames:
        return None

    def distance(frame: dict[str, Any]) -> float:
        return abs(math.log(frame['fill_ratio'] / _FILL_IDEAL))

    rated = [frame for frame in frames if frame.get('fill_ratio')]
    for verdict in (VERDICT_GOOD, VERDICT_TIGHT):
        candidates = [frame for frame in rated if frame.get('verdict') == verdict]
        if candidates:
            return min(candidates, key=distance)['combination_id']
    if rated:
        return min(rated, key=distance)['combination_id']
    return frames[0]['combination_id']


def build_frames(
    combinations: list[dict[str, Any]],
    telescopes_by_id: dict[str, dict[str, Any]],
    cameras_by_id: dict[str, dict[str, Any]],
    size_arcmin: float | None,
) -> list[dict[str, Any]]:
    """Return the framing data of every combination that can be framed, widest field first."""
    frames = []
    for combination in combinations:
        telescope = telescopes_by_id.get(combination.get('telescope_id') or '')
        camera = cameras_by_id.get(combination.get('camera_id') or '')
        try:
            frame = build_frame(combination, telescope, camera, size_arcmin)
        except TypeError, ValueError, ZeroDivisionError:
            # Malformed optics numbers on one combination must not hide the others.
            frame = None
        if frame is not None:
            frames.append(frame)
    frames.sort(key=lambda frame: frame['fov_diagonal_deg'], reverse=True)
    return frames


def list_unframeable(
    combinations: list[dict[str, Any]],
    telescopes_by_id: dict[str, dict[str, Any]],
    cameras_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the combinations that cannot be framed, each with the reason.

    Lets the simulator say what is missing instead of only "nothing to show". ``is_own``
    tells whether the user can edit the combination: a shared one carries its owner's id.
    """
    unframeable = []
    for combination in combinations:
        telescope = telescopes_by_id.get(combination.get('telescope_id') or '')
        camera = cameras_by_id.get(combination.get('camera_id') or '')
        optics, reason = _frame_optics(combination, telescope, camera)
        if optics is not None:
            continue
        unframeable.append(
            {
                'combination_id': str(combination.get('id') or ''),
                'combination_name': str(combination.get('name') or ''),
                'reason': reason,
                'is_own': not combination.get('owner_id'),
            }
        )
    return unframeable
