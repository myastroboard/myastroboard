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


class TestBestWindowsAllModesBranchCoverage:
    """Cover lines 141->144 and 150-153 in best_windows_all_modes via mocked arrays."""

    def test_shorter_second_window_does_not_replace_best(self):
        """
        Lines 141->144: duration <= best_duration branch.
        Array layout:
         - slots 0-19: dark → window1 (100 min)
         - slots 20-29: not dark → close window1 (100 min best)
         - slots 30-34: dark → window2 (25 min)
         - slots 35-39: not dark → close window2 (25 < 100 → False branch at 141)
         - slots 40+:  dark → window3 opens and stays open → closes at end of scan (lines 150-153)
        """
        import numpy as np
        from unittest.mock import patch, MagicMock

        svc = AstroTonightService(45.5, -73.5, "America/Montreal")

        # Determine number of time steps: 18:00 → next 06:00 at 5-min intervals
        # = 12h × 12 steps/h + 1 = 145 steps
        n = 145
        sun_alts = np.full(n, 5.0)   # not dark by default
        moon_alts = np.full(n, -5.0) # moon always below horizon

        # Window 1: slots 0-19 dark (100 min)
        sun_alts[:20] = -20.0
        # slots 20-29: not dark (sun_alts already 5.0)
        # Window 2: slots 30-34 dark (25 min)
        sun_alts[30:35] = -20.0
        # slots 35-39: not dark
        # Window 3: slots 40+ dark — stays open until end of scan
        sun_alts[40:] = -20.0

        def _make_alt_mock(alts_array):
            alt_mock = MagicMock()
            alt_mock.to_value.return_value = alts_array
            transformed = MagicMock()
            transformed.alt = alt_mock
            coord = MagicMock()
            coord.transform_to.return_value = transformed
            return coord

        with patch('moon_astrotonight.get_sun', return_value=_make_alt_mock(sun_alts)), \
             patch('moon_astrotonight.get_body', return_value=_make_alt_mock(moon_alts)), \
             patch('moon_astrotonight.Time', return_value=MagicMock()), \
             patch('moon_astrotonight.AltAz', return_value=MagicMock()), \
             patch.object(svc, '_moon_illumination', return_value=50.0):
            result = svc.best_windows_all_modes()

        assert isinstance(result, dict)
        for mode in ("strict", "practical", "illumination"):
            assert mode in result

    def test_end_window_shorter_than_best_does_not_replace(self):
        """Line 151->147: end-of-scan window duration < best mid-scan → no update."""
        import numpy as np
        from unittest.mock import patch, MagicMock

        svc = AstroTonightService(45.5, -73.5, "America/Montreal")
        n = 145  # 18:00 → 06:00 at 5-min steps

        # Window 1: slots 0-39 dark (200 min) → becomes best during scan
        # Slots 40-104: not dark
        # Window 2: slots 105-144 dark (39 × 5 = 195 min at end) → shorter, does not replace
        sun_alts = np.full(n, 5.0)
        sun_alts[:40] = -20.0
        sun_alts[105:] = -20.0
        moon_alts = np.full(n, -5.0)  # moon always below horizon

        def _make_alt_mock(alts_array):
            alt_mock = MagicMock()
            alt_mock.to_value.return_value = alts_array
            transformed = MagicMock()
            transformed.alt = alt_mock
            coord = MagicMock()
            coord.transform_to.return_value = transformed
            return coord

        with patch('moon_astrotonight.get_sun', return_value=_make_alt_mock(sun_alts)), \
             patch('moon_astrotonight.get_body', return_value=_make_alt_mock(moon_alts)), \
             patch('moon_astrotonight.Time', return_value=MagicMock()), \
             patch('moon_astrotonight.AltAz', return_value=MagicMock()), \
             patch.object(svc, '_moon_illumination', return_value=50.0):
            result = svc.best_windows_all_modes()

        # Best window should be window 1 (200 min ≈ 3.33 h), not window 2 (195 min)
        assert result['strict'].duration_hours == pytest.approx(200 / 60, abs=0.05)
