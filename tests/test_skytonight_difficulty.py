"""Tests for compute_difficulty_score() in skytonight_calculator.py."""

import os
import sys

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from skytonight_calculator import compute_difficulty_score  # noqa: E402
from skytonight_models import SkyTonightTarget  # noqa: E402


def _target(magnitude=None, size_arcmin=None, object_type='Neb'):
    return SkyTonightTarget(
        target_id='t1',
        category='deep_sky',
        object_type=object_type,
        preferred_name='Test Target',
        magnitude=magnitude,
        size_arcmin=size_arcmin,
    )


def test_bright_large_target_scores_beginner():
    score, difficulty = compute_difficulty_score(_target(magnitude=4.0, size_arcmin=90.0))
    assert difficulty == 'beginner'
    assert score <= 35


def test_faint_small_target_scores_higher_than_bright_large():
    bright_score, _ = compute_difficulty_score(_target(magnitude=4.0, size_arcmin=90.0))
    faint_score, faint_difficulty = compute_difficulty_score(_target(magnitude=17.0, size_arcmin=0.5))
    assert faint_score > bright_score
    assert faint_difficulty in ('intermediate', 'advanced')


def test_very_faint_tiny_target_can_reach_advanced():
    score, difficulty = compute_difficulty_score(_target(magnitude=20.0, size_arcmin=0.2))
    assert difficulty == 'advanced'
    assert score > 65


def test_neutral_default_falls_on_intermediate_side_of_midpoint_boundary():
    # (50, 'intermediate') exercises the 35 < score <= 65 branch at its midpoint.
    score, difficulty = compute_difficulty_score(_target(magnitude=None, size_arcmin=None))
    assert 35 < score <= 65
    assert difficulty == 'intermediate'


def test_missing_size_falls_back_to_magnitude_only():
    score, difficulty = compute_difficulty_score(_target(magnitude=3.0, size_arcmin=None))
    assert isinstance(score, int)
    assert difficulty in ('beginner', 'intermediate', 'advanced')
    # With surface_brightness/size zeroed, only magnitude (weight 0.20) contributes -
    # a bright magnitude should keep the raw score low.
    assert score <= 35


def test_missing_magnitude_falls_back_to_neutral_component():
    score, difficulty = compute_difficulty_score(_target(magnitude=None, size_arcmin=10.0))
    assert isinstance(score, int)
    assert 0 <= score <= 100
    assert difficulty in ('beginner', 'intermediate', 'advanced')


def test_both_missing_returns_neutral_default():
    score, difficulty = compute_difficulty_score(_target(magnitude=None, size_arcmin=None))
    assert score == 50
    assert difficulty == 'intermediate'


def test_score_always_in_valid_range_and_difficulty_always_valid():
    cases = [
        (4.0, 90.0), (17.0, 0.5), (20.0, 0.2), (12.0, 30.0), (8.0, 5.0),
        (None, None), (3.0, None), (None, 10.0), (0.0, 1.0), (25.0, 0.05),
    ]
    for magnitude, size_arcmin in cases:
        score, difficulty = compute_difficulty_score(_target(magnitude=magnitude, size_arcmin=size_arcmin))
        assert 0 <= score <= 100
        assert difficulty in ('beginner', 'intermediate', 'advanced')
