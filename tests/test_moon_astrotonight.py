"""
Tests for moon_astrotonight.py (AstroTonightService).
Focuses on pure-logic _score, BestWindow dataclass, and mocked best_windows_all_modes.
"""

import pytest
from unittest.mock import patch, MagicMock
from moon_astrotonight import AstroTonightService, BestWindow


class TestAstroTonightScore:
    """Tests for AstroTonightService._score pure logic."""

    def setup_method(self):
        self.svc = AstroTonightService(45.5, -73.5, "America/Montreal")

    def test_score_6_plus_returns_100(self):
        assert self.svc._score(6) == 100
        assert self.svc._score(8) == 100

    def test_score_4_to_6_returns_85(self):
        assert self.svc._score(4) == 85
        assert self.svc._score(5.9) == 85

    def test_score_2_to_4_returns_65(self):
        assert self.svc._score(2) == 65
        assert self.svc._score(3.9) == 65

    def test_score_gt0_lt2_returns_40(self):
        assert self.svc._score(0.1) == 40
        assert self.svc._score(1.99) == 40

    def test_score_0_returns_10(self):
        assert self.svc._score(0) == 10

    def test_score_negative_returns_10(self):
        assert self.svc._score(-5) == 10


class TestBestWindowDataclass:
    """Tests for the BestWindow dataclass."""

    def test_creation(self):
        bw = BestWindow(
            start="2026-01-30 22:00",
            end="2026-01-31 04:00",
            duration_hours=6.0,
            moon_condition="strict",
            score=100,
        )
        assert bw.start == "2026-01-30 22:00"
        assert bw.duration_hours == 6.0
        assert bw.score == 100

    def test_not_found_window(self):
        bw = BestWindow(
            start="Not found",
            end="Not found",
            duration_hours=0,
            moon_condition="unfavorable",
            score=0,
        )
        assert bw.score == 0


class TestBestWindowsTonightMocked:
    """Tests for best_windows_all_modes with mocked astronomical calls."""

    def _make_service(self):
        return AstroTonightService(45.5, -73.5, "America/Montreal")

    def test_best_windows_returns_three_modes(self):
        svc = self._make_service()
        mock_result = {
            "strict": BestWindow("2026-06-04 23:00", "2026-06-05 03:00", 4.0, "strict", 85),
            "practical": BestWindow("2026-06-04 22:30", "2026-06-05 03:30", 5.0, "practical", 85),
            "illumination": BestWindow("Not found", "Not found", 0, "unfavorable", 0),
        }
        with patch.object(svc, "best_windows_all_modes", return_value=mock_result):
            result = svc.best_windows_all_modes()
        assert "strict" in result
        assert "practical" in result
        assert "illumination" in result

    def test_best_window_tonight_uses_strict_by_default(self):
        svc = self._make_service()
        mock_strict = BestWindow("2026-06-04 23:00", "2026-06-05 04:00", 5.0, "strict", 85)
        mock_result = {
            "strict": mock_strict,
            "practical": BestWindow("2026-06-04 23:00", "2026-06-05 04:00", 5.0, "practical", 85),
            "illumination": BestWindow("Not found", "Not found", 0, "unfavorable", 0),
        }
        with patch.object(svc, "best_windows_all_modes", return_value=mock_result):
            result = svc.best_window_tonight()
        assert result is mock_strict

    def test_best_window_tonight_with_explicit_mode(self):
        svc = self._make_service()
        mock_practical = BestWindow("2026-06-04 22:30", "2026-06-05 04:30", 6.0, "practical", 100)
        mock_result = {
            "strict": BestWindow("2026-06-04 23:00", "2026-06-05 04:00", 5.0, "strict", 85),
            "practical": mock_practical,
            "illumination": BestWindow("Not found", "Not found", 0, "unfavorable", 0),
        }
        with patch.object(svc, "best_windows_all_modes", return_value=mock_result):
            result = svc.best_window_tonight(mode="practical")
        assert result is mock_practical


class TestAstroTonightInit:
    """Tests for AstroTonightService initialization."""

    def test_init_stores_location(self):
        svc = AstroTonightService(51.5, -0.1, "Europe/London")
        assert svc.latitude == 51.5
        assert svc.longitude == -0.1

    def test_location_object_created(self):
        svc = AstroTonightService(0.0, 0.0, "UTC")
        assert svc.location is not None


class TestBestWindowsAllModesReal:
    """Tests for best_windows_all_modes using real astropy computation."""

    def test_returns_dict_with_three_mode_keys(self):
        """Call the actual implementation to exercise it."""
        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        result = svc.best_windows_all_modes()
        assert isinstance(result, dict)
        for mode in ("strict", "practical", "illumination"):
            assert mode in result

    def test_each_window_is_bestwindow_instance(self):
        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        result = svc.best_windows_all_modes()
        for mode, window in result.items():
            assert isinstance(window, BestWindow)

    def test_duration_is_non_negative(self):
        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        result = svc.best_windows_all_modes()
        for mode, window in result.items():
            assert window.duration_hours >= 0.0

    def test_score_is_valid(self):
        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        result = svc.best_windows_all_modes()
        valid_scores = {0, 10, 40, 65, 85, 100}
        for mode, window in result.items():
            assert window.score in valid_scores

    def test_moon_illumination_returns_float(self):
        import datetime
        from zoneinfo import ZoneInfo
        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        dt = datetime.datetime(2026, 6, 4, 22, 0, 0, tzinfo=ZoneInfo("America/Montreal"))
        result = svc._moon_illumination(dt)
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0
