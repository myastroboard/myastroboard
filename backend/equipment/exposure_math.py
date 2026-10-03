"""Shared sky-background and integration-time math for astrophotography planning.

The sub-exposure half of this (plate scale, sky photon rate, the 5x sky-limited
sub-exposure) mirrors the front-end Exposure Calculator (``static/js/equipment.js``
``_computeExposure``) and is documented in ``docs/EXPOSURE_CALC.md``.

``estimate_min_integration_hours`` is new: it answers "roughly how much total
integration does this target need?", which the Exposure Calculator never does (it
only ever sizes subs *from* a total the user supplies). It is a deliberately rough
planning heuristic - see ``docs/EXPOSURE_CALC.md`` for the derivation, assumptions,
and limitations.
"""

from __future__ import annotations

import math

# Bortle class -> sky surface brightness (SQM, mag/arcsec^2, V-band). Matches the
# table in docs/EXPOSURE_CALC.md and BORTLE_SQM in static/js/equipment.js.
BORTLE_SQM: dict[int, float] = {
    1: 22.0,
    2: 21.5,
    3: 21.2,
    4: 20.8,
    5: 20.3,
    6: 19.5,
    7: 18.8,
    8: 18.3,
    9: 17.5,
}
_DEFAULT_SQM = BORTLE_SQM[5]

# Vega V-band zero-point flux, photons / m^2 / s / arcsec^2.
VEGA_PHOTONS_M2_S_ARCSEC2 = 9.0e9

# Default sensor quantum efficiency when the camera profile does not record one.
DEFAULT_QUANTUM_EFFICIENCY = 0.60

# Per-pixel SNR on the target's mean surface brightness that
# ``estimate_min_integration_hours`` solves for. ~15 is "detectable and
# processable", not "publication quality" - see docs/EXPOSURE_CALC.md.
DEFAULT_TARGET_SNR = 15.0

# Add this to a surface brightness expressed per arcmin^2 to get it per arcsec^2
# (2.5 * log10(3600)).
_ARCMIN2_TO_ARCSEC2_MAG = 2.5 * math.log10(3600.0)


def sqm_for_bortle(bortle: float | None) -> float:
    """Return the SQM (mag/arcsec^2) for a Bortle class, defaulting to Bortle 5."""
    if bortle is None:
        return _DEFAULT_SQM
    try:
        return BORTLE_SQM.get(int(round(float(bortle))), _DEFAULT_SQM)
    except TypeError, ValueError:
        return _DEFAULT_SQM


def surface_brightness_per_arcsec2(sb_per_arcmin2: float | None) -> float | None:
    """Convert a surface brightness in mag/arcmin^2 to mag/arcsec^2."""
    if sb_per_arcmin2 is None:
        return None
    return float(sb_per_arcmin2) + _ARCMIN2_TO_ARCSEC2_MAG


def plate_scale_arcsec_per_px(pixel_size_um: float, focal_length_mm: float) -> float | None:
    """Angular size of one pixel on the sky (arcsec/px)."""
    if not pixel_size_um or not focal_length_mm:
        return None
    return 206.265 * float(pixel_size_um) / float(focal_length_mm)


def photon_rate_e_per_px_s(
    surface_brightness_arcsec2: float,
    aperture_mm: float,
    plate_scale: float,
    quantum_efficiency: float = DEFAULT_QUANTUM_EFFICIENCY,
) -> float:
    """Photo-electron rate (e-/px/s) from a source of the given surface brightness.

    ``B = F0 * 10^(-SB/2.5) * QE * (pi/4) * D_m^2 * plate_scale^2`` - the same form the
    Exposure Calculator uses for the sky background.
    """
    aperture_m = float(aperture_mm) / 1000.0
    collecting_area_m2 = math.pi / 4.0 * aperture_m * aperture_m
    sky_flux = VEGA_PHOTONS_M2_S_ARCSEC2 * (10.0 ** (-float(surface_brightness_arcsec2) / 2.5))
    return sky_flux * float(quantum_efficiency) * collecting_area_m2 * (float(plate_scale) ** 2)


def estimate_min_integration_hours(
    surface_brightness_per_arcmin2: float | None,
    focal_length_mm: float | None,
    focal_ratio: float | None,
    pixel_size_um: float | None,
    bortle: float | None = None,
    quantum_efficiency: float | None = None,
    target_snr: float = DEFAULT_TARGET_SNR,
    sqm: float | None = None,
) -> float | None:
    """Rough total integration time (hours) to reach ``target_snr`` per pixel on the
    target's mean surface brightness, in the sky-limited regime.

    Sky-limited CCD equation: with per-pixel target rate ``S`` and sky rate ``B``
    (e-/px/s), after total time ``T`` the per-pixel SNR is
    ``sqrt(T) * S / sqrt(S + B)``. Solving for ``T``:
        ``T = SNR^2 * (S + B) / S^2``

    Returns ``None`` when any required input is missing so callers keep the row
    tagged "unknown" rather than dropping it.
    """
    sb_arcsec2 = surface_brightness_per_arcsec2(surface_brightness_per_arcmin2)
    if sb_arcsec2 is None or not focal_length_mm or not focal_ratio or not pixel_size_um:
        return None

    # focal length & pixel size are validated non-falsy above, so plate scale is always a positive float.
    plate_scale = plate_scale_arcsec_per_px(pixel_size_um, focal_length_mm)
    if not plate_scale:
        return None  # pragma: no cover - defensive; unreachable with validated inputs

    aperture_mm = float(focal_length_mm) / float(focal_ratio)
    if aperture_mm <= 0:
        return None

    qe = quantum_efficiency if quantum_efficiency and quantum_efficiency > 0 else DEFAULT_QUANTUM_EFFICIENCY
    # A user-measured SQM (mag/arcsec^2) wins over the Bortle-class lookup when available.
    sky_sqm = float(sqm) if sqm is not None else sqm_for_bortle(bortle)

    s_target = photon_rate_e_per_px_s(sb_arcsec2, aperture_mm, plate_scale, qe)
    b_sky = photon_rate_e_per_px_s(sky_sqm, aperture_mm, plate_scale, qe)
    if s_target <= 0.0:
        return None

    t_total_seconds = (target_snr**2) * (s_target + b_sky) / (s_target**2)
    return t_total_seconds / 3600.0
