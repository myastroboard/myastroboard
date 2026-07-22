"""
Unit tests for backend/sky_quality.py.

All functions under test are pure (no I/O), so no fixtures are needed.
"""

import math
import sys
import os

import pytest

from weather.sky_quality import (
    BORTLE_SQM_MIDPOINTS,
    bortle_to_sqm,
    sqm_to_bortle,
    light_pollution_factor,
    object_lp_factor,
)


class TestBortleToSqm:
    def test_bortle_1_is_darkest(self):
        assert bortle_to_sqm(1) == BORTLE_SQM_MIDPOINTS[1]
        assert bortle_to_sqm(1) > 21.9

    def test_bortle_5_suburban(self):
        sqm = bortle_to_sqm(5)
        assert 20.3 < sqm < 20.8

    def test_bortle_9_inner_city(self):
        sqm = bortle_to_sqm(9)
        assert sqm < 17.0

    def test_all_classes_covered(self):
        for b in range(1, 10):
            sqm = bortle_to_sqm(b)
            assert isinstance(sqm, float)
            assert sqm > 0

    def test_invalid_bortle_raises(self):
        with pytest.raises(ValueError):
            bortle_to_sqm(0)
        with pytest.raises(ValueError):
            bortle_to_sqm(10)


class TestSqmToBortle:
    def test_pristine_sky(self):
        assert sqm_to_bortle(22.5) == 1

    def test_boundary_above_21_9(self):
        assert sqm_to_bortle(21.91) == 1

    def test_boundary_21_5_to_21_9(self):
        assert sqm_to_bortle(21.7) == 2

    def test_suburban(self):
        assert sqm_to_bortle(20.5) == 5

    def test_city(self):
        assert sqm_to_bortle(18.0) == 8

    def test_inner_city(self):
        assert sqm_to_bortle(16.0) == 9
        assert sqm_to_bortle(12.0) == 9

    def test_round_trip_midpoints(self):
        for bortle in range(1, 10):
            sqm = bortle_to_sqm(bortle)
            recovered = sqm_to_bortle(sqm)
            # Midpoints should round-trip to the same or adjacent class
            assert abs(recovered - bortle) <= 1, (
                f"Bortle {bortle} → SQM {sqm} → Bortle {recovered}"
            )


class TestLightPollutionFactor:
    def test_dark_sky_near_one(self):
        factor = light_pollution_factor(22.0)
        assert factor >= 0.98, f"Expected near 1.0 for pristine sky, got {factor}"

    def test_sqm_17_is_zero(self):
        assert light_pollution_factor(17.0) == 0.0

    def test_inner_city_near_zero(self):
        factor = light_pollution_factor(16.0)
        assert factor == 0.0  # clamped

    def test_suburban_midpoint(self):
        # SQM 20.0: normalized = (20.0-17)/5 = 0.6; 0.6^1.5 ≈ 0.4648
        factor = light_pollution_factor(20.0)
        expected = round(0.6 ** 1.5, 4)
        assert math.isclose(factor, expected, rel_tol=1e-4)

    def test_monotone_increasing(self):
        sqm_values = [16.0, 17.0, 18.5, 19.5, 20.5, 21.5, 22.0]
        factors = [light_pollution_factor(s) for s in sqm_values]
        for i in range(len(factors) - 1):
            assert factors[i] <= factors[i + 1], (
                f"Factor not increasing: SQM {sqm_values[i]} → {factors[i]}, "
                f"SQM {sqm_values[i+1]} → {factors[i+1]}"
            )

    def test_output_in_range(self):
        for sqm in [15.0, 17.0, 19.0, 21.0, 23.0]:
            f = light_pollution_factor(sqm)
            assert 0.0 <= f <= 1.0


class TestObjectLpFactor:
    def test_planet_nearly_immune(self):
        # Planet sensitivity = 0.05 → even at worst sky, factor stays near 1.0
        factor = object_lp_factor(17.0, 'planet')
        # base=0.0, sensitivity=0.05 → 1 - 0.05*(1-0) = 0.95
        assert math.isclose(factor, 0.95, rel_tol=1e-3)

    def test_moon_completely_immune(self):
        factor = object_lp_factor(17.0, 'moon')
        assert factor == 1.0

    def test_galaxy_takes_full_penalty(self):
        # At SQM 17 (base=0), galaxy sensitivity=1.0 → factor = 1-(1*1)= 0.0
        factor = object_lp_factor(17.0, 'galaxy')
        assert factor == 0.0

    def test_dark_sky_galaxy_high(self):
        # At SQM 22 (base≈1), even galaxy is near 1.0
        factor = object_lp_factor(22.0, 'galaxy')
        assert factor >= 0.98

    def test_none_object_type_uses_default(self):
        factor_none = object_lp_factor(20.0, None)
        factor_empty = object_lp_factor(20.0, '')
        assert math.isclose(factor_none, factor_empty, rel_tol=1e-6)

    def test_unknown_object_type_uses_default_sensitivity(self):
        # Default sensitivity = 0.80
        sqm = 19.0
        base = light_pollution_factor(sqm)
        expected = round(1.0 - (0.80 * (1.0 - base)), 4)
        factor = object_lp_factor(sqm, 'unknown_type')
        assert math.isclose(factor, expected, rel_tol=1e-4)

    def test_case_insensitive_object_type(self):
        assert object_lp_factor(20.0, 'Galaxy') == object_lp_factor(20.0, 'galaxy')
        assert object_lp_factor(20.0, 'PLANET') == object_lp_factor(20.0, 'planet')

    def test_output_always_in_range(self):
        for sqm in [17.0, 19.0, 21.0]:
            for otype in ['galaxy', 'nebula', 'cluster', 'planet', 'moon', None]:
                f = object_lp_factor(sqm, otype)
                assert 0.0 <= f <= 1.0, f"Out of range: sqm={sqm}, type={otype}, f={f}"
