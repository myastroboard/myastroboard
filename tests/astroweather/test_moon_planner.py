"""
Tests for moon_planner.py
Focuses on pure-logic (score) and mocked _night_data for next_n_nights.
"""

import datetime

from astroweather.moon_planner import MoonPlanner, night_body_altitude_grid


class TestMoonPlannerScore:
    """Tests for MoonPlanner._score pure logic."""

    def setup_method(self):
        self.planner = MoonPlanner(45.5, -73.5, "America/Montreal")

    def test_score_6_hours_returns_100(self):
        assert self.planner._score(6) == 100

    def test_score_exactly_6_returns_100(self):
        assert self.planner._score(6.0) == 100

    def test_score_above_6_returns_100(self):
        assert self.planner._score(8.0) == 100

    def test_score_4_hours_returns_80(self):
        assert self.planner._score(4) == 80

    def test_score_5_hours_returns_80(self):
        assert self.planner._score(5) == 80

    def test_score_2_hours_returns_60(self):
        assert self.planner._score(2) == 60

    def test_score_3_hours_returns_60(self):
        assert self.planner._score(3) == 60

    def test_score_gt_0_lt_2_returns_40(self):
        assert self.planner._score(0.5) == 40
        assert self.planner._score(1.9) == 40

    def test_score_0_returns_10(self):
        assert self.planner._score(0) == 10

    def test_score_negative_returns_10(self):
        assert self.planner._score(-1) == 10


class TestMoonPlannerInit:
    """Tests for MoonPlanner initialization."""

    def test_basic_init(self):
        p = MoonPlanner(48.85, 2.35, "Europe/Paris")
        assert p.latitude == 48.85
        assert p.longitude == 2.35


class TestMoonIllumination:
    """The thin wrapper delegating to the shared astroplan illumination helper."""

    def test_moon_illumination_delegates_and_returns_percent(self):
        import datetime

        planner = MoonPlanner(48.85, 2.35, "Europe/Paris")
        value = planner._moon_illumination(datetime.datetime(2026, 9, 11, 22, 0))
        assert 0.0 <= value <= 100.0

    def test_location_is_set(self):
        p = MoonPlanner(0.0, 0.0, "UTC")
        assert p.location is not None


class TestNextNNights:
    """Tests for next_n_nights with mocked _night_data."""

    def _fake_night_data(self, date):
        return {
            "hours_strict": 5.0,
            "hours_practical": 6.0,
            "hours_illumination": 7.0,
            "moon_max_alt": 25.0,
            "illumination": 10.0,
        }

    def test_returns_list_of_n_items(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_n_nights(3)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_item_has_expected_keys(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_n_nights(1)
        item = result[0]
        assert "date" in item
        assert "dark_hours" in item
        assert "moon" in item
        assert "astrophoto_score" in item

    def test_dark_hours_structure(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_n_nights(1)
        dark_hours = result[0]["dark_hours"]
        assert "strict" in dark_hours
        assert "practical" in dark_hours
        assert "illumination" in dark_hours

    def test_moon_structure(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_n_nights(1)
        moon = result[0]["moon"]
        assert "max_altitude" in moon
        assert "illumination_percent" in moon

    def test_score_is_computed_correctly(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data  # strict=5.0 → score 80
        result = planner.next_n_nights(1)
        assert result[0]["astrophoto_score"] == 80

    def test_next_7_nights_returns_7_items(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_7_nights()
        assert len(result) == 7

    def test_dates_are_sequential(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        planner._night_data = self._fake_night_data
        result = planner.next_n_nights(3)
        dates = [r["date"] for r in result]
        # Each date must be 1 day after the previous
        from datetime import date, timedelta

        for i in range(1, len(dates)):
            d0 = date.fromisoformat(dates[i - 1])
            d1 = date.fromisoformat(dates[i])
            assert d1 == d0 + timedelta(days=1)


class TestNightBodyAltitudeGrid:
    """Real (unmocked) ephemeris computation for the shared altitude-grid helper."""

    def test_grid_has_expected_keys_and_array_shapes(self):
        grid = night_body_altitude_grid(45.5, -73.5, "America/Montreal", datetime.date(2026, 1, 15), step_minutes=30)
        assert set(grid.keys()) == {"time", "sun_alt_deg", "moon_alt_deg", "moon_illumination_pct"}
        assert len(grid["sun_alt_deg"]) == len(grid["moon_alt_deg"]) == len(grid["time"])
        # 18:00 -> 06:00 next day (12h) at 30-min steps, inclusive of both ends: 25 points
        assert len(grid["sun_alt_deg"]) == 25

    def test_grid_sun_dips_below_astronomical_twilight_overnight(self):
        grid = night_body_altitude_grid(45.5, -73.5, "America/Montreal", datetime.date(2026, 1, 15), step_minutes=30)
        assert grid["sun_alt_deg"].min() < -18

    def test_grid_illumination_percent_is_in_range(self):
        grid = night_body_altitude_grid(48.85, 2.35, "Europe/Paris", datetime.date(2026, 6, 1), step_minutes=60)
        assert 0.0 <= grid["moon_illumination_pct"] <= 100.0

    def test_grid_default_step_minutes_produces_finer_grid(self):
        grid = night_body_altitude_grid(45.5, -73.5, "America/Montreal", datetime.date(2026, 1, 15))
        # Default step is 10 minutes over the same 12h window -> 73 points
        assert len(grid["sun_alt_deg"]) == 73


class TestNightDataRealComputation:
    """Exercises MoonPlanner._night_data end-to-end (no mocking) for real coverage."""

    def test_night_data_returns_expected_keys_and_ranges(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        result = planner._night_data(datetime.date(2026, 1, 15))
        assert set(result.keys()) == {
            "hours_strict",
            "hours_practical",
            "hours_illumination",
            "moon_max_alt",
            "illumination",
        }
        assert 0.0 <= result["illumination"] <= 100.0
        assert -90.0 <= result["moon_max_alt"] <= 90.0
        # Strict mode (moon below horizon) can never exceed practical mode (moon < 5deg)
        assert result["hours_strict"] <= result["hours_practical"]

    def test_night_data_illumination_hours_positive_near_new_moon(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        result = planner._night_data(datetime.date(2026, 9, 10))  # near-new moon (~0.02% illuminated)
        assert result["illumination"] < 15
        assert result["hours_illumination"] > 0

    def test_night_data_illumination_hours_zero_near_full_moon(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        result = planner._night_data(datetime.date(2026, 9, 25))  # near-full moon (~99.6% illuminated)
        assert result["illumination"] >= 15
        assert result["hours_illumination"] == 0.0

    def test_next_n_nights_end_to_end_without_mocking(self):
        planner = MoonPlanner(45.5, -73.5, "America/Montreal")
        result = planner.next_n_nights(1)
        assert len(result) == 1
        night = result[0]
        assert night["astrophoto_score"] in (10, 40, 60, 80, 100)
        assert 0.0 <= night["moon"]["illumination_percent"] <= 100.0
