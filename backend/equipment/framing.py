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

# Overlap assumed between neighbouring panels when estimating a mosaic grid.
_MOSAIC_OVERLAP = 0.15

VERDICT_UNKNOWN = 'unknown'
VERDICT_SMALL = 'small'
VERDICT_GOOD = 'good'
VERDICT_TIGHT = 'tight'
VERDICT_TOO_LARGE = 'too_large'


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


def build_frame(
    combination: dict[str, Any],
    telescope: dict[str, Any] | None,
    camera: dict[str, Any] | None,
    size_arcmin: float | None,
) -> dict[str, Any] | None:
    """Return the framing data of one combination, or None when it cannot be framed.

    A combination can be framed when it has a camera with sensor dimensions and pixel
    size, and a focal length: the telescope's effective one, or the combination's own lens
    for a camera-only setup. The guide camera is never part of the field of view.
    """
    if not camera:
        return None
    sensor_w = _positive_float(camera.get('sensor_width_mm'))
    sensor_h = _positive_float(camera.get('sensor_height_mm'))
    pixel_um = _positive_float(camera.get('pixel_size_um'))
    if telescope:
        focal = _positive_float(telescope.get('effective_focal_length')) or _positive_float(
            telescope.get('focal_length_mm')
        )
    else:
        focal = _positive_float(combination.get('lens_focal_length_mm'))
    if not (sensor_w and sensor_h and pixel_um and focal):
        return None

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
