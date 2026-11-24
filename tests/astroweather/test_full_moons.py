"""Tests for full_moons - pure ephemeris, deterministic.

Reference values are well-documented Full Moons: the November and December 2026
supermoons, the May 2026 Blue Moon micromoon and the October 2020 Hunter's Blue Moon.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest
from astronomy import SearchMoonPhase, Time

from astroweather.full_moons import describe_full_moon, upcoming_full_moons

PARIS = "Europe/Paris"


def _full_moon_after(year: int, month: int, day: int, timezone: str = PARIS) -> dict:
    """Details of the first Full Moon after the given UTC date."""
    t = SearchMoonPhase(180, Time.Make(year, month, day, 0, 0, 0), 32)
    assert t is not None
    return describe_full_moon(t, timezone)


class TestDescribeFullMoon:
    """describe_full_moon() - one Full Moon instant."""

    def test_shape(self):
        """Every documented key is present with the right type."""
        details = _full_moon_after(2026, 11, 20)
        assert set(details) == {
            "time",
            "date",
            "distance_km",
            "angular_diameter_arcmin",
            "size_vs_mean_percent",
            "supermoon",
            "micromoon",
            "blue_moon",
            "folk_name",
        }
        assert isinstance(details["distance_km"], int)
        assert isinstance(details["supermoon"], bool)

    def test_november_2026_is_the_beaver_supermoon(self):
        """The 2026-11-24 Full Moon is near perigee and carries November's name."""
        details = _full_moon_after(2026, 11, 20)
        assert details["date"] == "2026-11-24"
        assert details["time"].startswith("2026-11-24T15:5")
        assert details["distance_km"] == pytest.approx(360_754, abs=50)
        assert details["supermoon"] is True
        assert details["micromoon"] is False
        assert details["folk_name"] == "beaver"

    def test_supermoon_looks_larger_than_at_mean_distance(self):
        """A supermoon's apparent size is above the mean, around 33 arcminutes."""
        details = _full_moon_after(2026, 12, 20)
        assert details["supermoon"] is True
        assert details["size_vs_mean_percent"] > 7
        assert 33.0 < details["angular_diameter_arcmin"] < 34.0

    def test_full_moon_near_apogee_is_a_micromoon(self):
        """The July 2027 Full Moon, near apogee, is a micromoon and looks smaller."""
        details = _full_moon_after(2027, 7, 10)
        assert details["micromoon"] is True
        assert details["supermoon"] is False
        assert details["size_vs_mean_percent"] < 0

    def test_ordinary_full_moon_is_neither(self):
        """A Full Moon mid-way between perigee and apogee gets no flag."""
        details = _full_moon_after(2026, 3, 1)
        assert details["supermoon"] is False
        assert details["micromoon"] is False

    def test_second_full_moon_of_the_month_is_a_blue_moon(self):
        """2026-05-31 follows the 2026-05-01 Full Moon: Blue Moon; the first one is not."""
        first = _full_moon_after(2026, 4, 28)
        second = _full_moon_after(2026, 5, 20)
        assert first["date"] == "2026-05-01"
        assert first["blue_moon"] is False
        assert second["date"] == "2026-05-31"
        assert second["blue_moon"] is True

    def test_blue_moon_uses_the_local_calendar_month(self):
        """The Blue Moon month is the local one: a Full Moon is placed on its local date."""
        tokyo = _full_moon_after(2026, 5, 20, "Asia/Tokyo")
        assert tokyo["date"] == "2026-05-31"
        assert tokyo["time"].endswith("+09:00")

    def test_harvest_moon_is_the_full_moon_nearest_the_september_equinox(self):
        """2026: September's Full Moon is the Harvest Moon, October's the Hunter's Moon."""
        assert _full_moon_after(2026, 9, 20)["folk_name"] == "harvest"
        assert _full_moon_after(2026, 10, 20)["folk_name"] == "hunters"

    def test_harvest_moon_can_fall_in_october(self):
        """2020: Harvest Moon on Oct 1, so September's is the Corn Moon and Oct 31 the Hunter's Blue Moon."""
        september = _full_moon_after(2020, 8, 25, "UTC")
        october_1 = _full_moon_after(2020, 9, 25, "UTC")
        october_31 = _full_moon_after(2020, 10, 25, "UTC")
        assert september["folk_name"] == "corn"
        assert october_1["folk_name"] == "harvest"
        assert october_31["folk_name"] == "hunters"
        assert october_31["blue_moon"] is True


class TestUpcomingFullMoons:
    """upcoming_full_moons() - the next N Full Moons from a start instant."""

    def test_returns_count_in_chronological_order(self):
        """Twelve consecutive Full Moons, about a synodic month apart."""
        start = datetime.datetime(2026, 1, 1, tzinfo=ZoneInfo(PARIS))
        moons = upcoming_full_moons(start, 12, PARIS)
        assert len(moons) == 12
        times = [datetime.datetime.fromisoformat(m["time"]) for m in moons]
        gaps = [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:], strict=False)]
        assert all(29.2 < gap < 29.9 for gap in gaps)

    def test_first_result_is_after_start(self):
        """The search starts at ``start``: an earlier Full Moon is not returned."""
        start = datetime.datetime(2026, 11, 25, tzinfo=ZoneInfo(PARIS))
        moons = upcoming_full_moons(start, 1, PARIS)
        assert moons[0]["date"] == "2026-12-24"

    def test_zero_count_returns_empty_list(self):
        """No search is made for count 0."""
        assert upcoming_full_moons(datetime.datetime(2026, 1, 1, tzinfo=ZoneInfo(PARIS)), 0, PARIS) == []
