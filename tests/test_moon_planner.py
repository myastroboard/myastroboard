"""
Tests for moon_planner.py
Focuses on pure-logic (score) and mocked _night_data for next_n_nights.
"""

from moon_planner import MoonPlanner


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
