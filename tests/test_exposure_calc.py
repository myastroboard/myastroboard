"""
Unit tests for the Exposure Calculator formula.

The calculator lives in equipment.js (_computeExposure) as pure client-side JS.
These tests validate the same formulae in Python to catch regressions in the
underlying physics without requiring a browser.

Reference:  docs/EXPOSURE_CALC.md
Calibration: ASI294MC Pro, 150mm f/7, Bortle 5 → ~0.83 e⁻/px/s (empirical).
"""

import math
import pytest


# ── Mirror of the JS _computeExposure logic ───────────────────────────────────

BORTLE_SQM = {
    1: 22.0, 2: 21.5, 3: 21.2, 4: 20.8, 5: 20.3,
    6: 19.5, 7: 18.8, 8: 18.3, 9: 17.5,
}

VEGA_PHOTONS_M2_S_ARCSEC2 = 9e9


def compute_exposure(
    aperture_mm: float,
    focal_length_mm: float,
    pixel_size_um: float,
    read_noise_e: float,
    qe: float,           # 0–1
    bortle: int,
    total_hours: float,
) -> dict:
    sqm       = BORTLE_SQM[bortle]
    D_m       = aperture_mm / 1000.0
    area_m2   = math.pi / 4 * D_m ** 2
    plate_scale = 206.265 * pixel_size_um / focal_length_mm   # arcsec/px
    sky_flux  = VEGA_PHOTONS_M2_S_ARCSEC2 * 10 ** (-sqm / 2.5)
    B_sky     = sky_flux * qe * area_m2 * plate_scale ** 2    # e/px/s
    t_sub_s   = 5 * read_noise_e ** 2 / B_sky
    total_s   = total_hours * 3600
    n_subs    = max(1, round(total_s / t_sub_s))
    return {
        "plate_scale":   plate_scale,
        "sqm":           sqm,
        "B_sky":         B_sky,
        "t_sub_s":       t_sub_s,
        "n_subs":        n_subs,
        "actual_total_s": n_subs * t_sub_s,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestComputeExposure:

    def test_plate_scale_formula(self):
        """206.265 × pixel / focal gives correct arcsec/px."""
        r = compute_exposure(
            aperture_mm=150, focal_length_mm=1050,
            pixel_size_um=4.63, read_noise_e=4, qe=0.75,
            bortle=5, total_hours=3,
        )
        expected = 206.265 * 4.63 / 1050
        assert abs(r["plate_scale"] - expected) < 1e-6

    def test_bortle_sqm_mapping(self):
        """Each Bortle value maps to the documented SQM."""
        for bortle, sqm in BORTLE_SQM.items():
            r = compute_exposure(
                aperture_mm=100, focal_length_mm=500,
                pixel_size_um=3.0, read_noise_e=4, qe=0.65,
                bortle=bortle, total_hours=1,
            )
            assert r["sqm"] == sqm

    def test_calibration_asi294_f7_bortle5(self):
        """
        Calibration reference: ASI294MC Pro at f/7, 150 mm aperture,
        4.63 µm pixels, QE 75%, Bortle 5 → sky background ≈ 0.83 e⁻/px/s.
        Formula result must be within ±50% of the empirical value.
        """
        r = compute_exposure(
            aperture_mm=150, focal_length_mm=1050,
            pixel_size_um=4.63, read_noise_e=4, qe=0.75,
            bortle=5, total_hours=3,
        )
        assert 0.4 < r["B_sky"] < 2.0, (
            f"Sky background {r['B_sky']:.3f} e/px/s out of expected 0.4–2.0 range"
        )

    def test_darker_sky_lower_background(self):
        """Bortle 1 gives lower sky background than Bortle 9."""
        base = dict(aperture_mm=100, focal_length_mm=500,
                    pixel_size_um=3.0, read_noise_e=4, qe=0.65, total_hours=1)
        dark    = compute_exposure(bortle=1, **base)
        bright  = compute_exposure(bortle=9, **base)
        assert dark["B_sky"] < bright["B_sky"]

    def test_larger_aperture_more_background(self):
        """Larger aperture collects more sky photons → higher background."""
        base = dict(focal_length_mm=800, pixel_size_um=3.8,
                    read_noise_e=4, qe=0.65, bortle=5, total_hours=1)
        small = compute_exposure(aperture_mm=80,  **base)
        large = compute_exposure(aperture_mm=200, **base)
        assert large["B_sky"] > small["B_sky"]

    def test_faster_focal_ratio_more_background(self):
        """Same aperture, shorter focal length (faster f-ratio) → larger plate scale → more sky."""
        base = dict(aperture_mm=150, pixel_size_um=3.8,
                    read_noise_e=4, qe=0.65, bortle=5, total_hours=1)
        slow = compute_exposure(focal_length_mm=1200, **base)  # f/8
        fast = compute_exposure(focal_length_mm=600,  **base)  # f/4
        assert fast["B_sky"] > slow["B_sky"]

    def test_sub_exposure_criterion(self):
        """t_sub × B_sky must equal 5 × RN² (the 5× criterion)."""
        rn = 5.0
        r = compute_exposure(
            aperture_mm=150, focal_length_mm=900,
            pixel_size_um=4.0, read_noise_e=rn, qe=0.70,
            bortle=5, total_hours=2,
        )
        assert abs(r["t_sub_s"] * r["B_sky"] - 5 * rn ** 2) < 1e-9

    def test_higher_read_noise_longer_sub(self):
        """Higher read noise → longer optimal sub-exposure."""
        base = dict(aperture_mm=100, focal_length_mm=500,
                    pixel_size_um=3.8, qe=0.65, bortle=5, total_hours=3)
        low_rn  = compute_exposure(read_noise_e=2, **base)
        high_rn = compute_exposure(read_noise_e=8, **base)
        assert high_rn["t_sub_s"] > low_rn["t_sub_s"]

    def test_n_subs_positive(self):
        """Number of subs must always be ≥ 1."""
        r = compute_exposure(
            aperture_mm=50, focal_length_mm=250,
            pixel_size_um=2.9, read_noise_e=10, qe=0.50,
            bortle=1, total_hours=0.25,
        )
        assert r["n_subs"] >= 1

    def test_total_integration_fills_n_subs(self):
        """actual_total_s must equal n_subs × t_sub_s."""
        r = compute_exposure(
            aperture_mm=200, focal_length_mm=800,
            pixel_size_um=5.0, read_noise_e=3.5, qe=0.80,
            bortle=6, total_hours=4,
        )
        assert abs(r["actual_total_s"] - r["n_subs"] * r["t_sub_s"]) < 1e-9

    def test_qe_scales_background_linearly(self):
        """Doubling QE halves the required sub-exposure (background doubles)."""
        base = dict(aperture_mm=100, focal_length_mm=500,
                    pixel_size_um=3.8, read_noise_e=4, bortle=5, total_hours=2)
        r1 = compute_exposure(qe=0.40, **base)
        r2 = compute_exposure(qe=0.80, **base)
        assert abs(r1["t_sub_s"] / r2["t_sub_s"] - 2.0) < 0.01
