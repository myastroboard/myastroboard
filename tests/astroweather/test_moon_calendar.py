"""Tests for moon_calendar - pure ephemeris, deterministic."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from astroweather.moon_calendar import _SAMPLE_HOUR, _illumination_percent, build_phase_calendar, phase_at

PARIS = "Europe/Paris"


class TestIlluminationPercent:
    """The phase-angle -> illuminated-fraction formula shared with the Moon report."""

    def test_new_moon_angle_is_zero_percent(self):
        assert _illumination_percent(0.0) == pytest.approx(0.0)

    def test_full_moon_angle_is_hundred_percent(self):
        assert _illumination_percent(180.0) == pytest.approx(100.0)

    def test_quarter_angle_is_half(self):
        assert _illumination_percent(90.0) == pytest.approx(50.0)


class TestPhaseAt:
    """phase_at() - single-instant sample (the per-day building block)."""

    def test_shape_and_ranges(self):
        result = phase_at(datetime.datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo(PARIS)))
        assert set(result) == {"illumination_percent", "waxing", "moonless"}
        assert 0.0 <= result["illumination_percent"] <= 100.0
        assert isinstance(result["waxing"], bool)
        assert result["moonless"] is (result["illumination_percent"] < 15.0)

    def test_near_full_moon_is_waning_and_bright(self):
        # 2026 full moon is ~2026-09-26 18:49 local; a day later it is waning.
        result = phase_at(datetime.datetime(2026, 9, 27, 18, 0, tzinfo=ZoneInfo(PARIS)))
        assert result["waxing"] is False
        assert result["illumination_percent"] > 90.0

    def test_illumination_changes_within_the_same_day(self):
        tz = ZoneInfo(PARIS)
        morning = phase_at(datetime.datetime(2026, 9, 4, 6, 0, tzinfo=tz))["illumination_percent"]
        evening = phase_at(datetime.datetime(2026, 9, 4, 22, 0, tzinfo=tz))["illumination_percent"]
        assert morning != evening

    def test_calendar_cells_are_sampled_at_the_fixed_night_hour(self):
        tz = ZoneInfo(PARIS)
        night = phase_at(datetime.datetime(2026, 9, 15, _SAMPLE_HOUR, tzinfo=tz))
        day_15 = build_phase_calendar(2026, 9, PARIS)["days"][14]
        assert day_15["illumination_percent"] == night["illumination_percent"]
        assert day_15["waxing"] == night["waxing"]
        # And NOT the noon value (the two differ enough to tell apart).
        noon = phase_at(datetime.datetime(2026, 9, 15, 12, tzinfo=tz))
        assert day_15["illumination_percent"] != noon["illumination_percent"]


class TestDayGrid:
    """Per-day structure of the returned calendar."""

    def test_day_count_matches_31_day_month(self):
        result = build_phase_calendar(2026, 1, PARIS)
        assert len(result["days"]) == 31
        assert result["days"][0]["day"] == 1
        assert result["days"][-1]["day"] == 31

    def test_day_count_matches_30_day_month(self):
        assert len(build_phase_calendar(2026, 9, PARIS)["days"]) == 30

    def test_day_count_matches_february_common_year(self):
        assert len(build_phase_calendar(2026, 2, PARIS)["days"]) == 28

    def test_day_count_matches_february_leap_year(self):
        assert len(build_phase_calendar(2028, 2, PARIS)["days"]) == 29

    def test_each_day_has_expected_fields_and_ranges(self):
        for day in build_phase_calendar(2026, 9, PARIS)["days"]:
            assert set(day) == {"date", "day", "illumination_percent", "waxing", "moonless", "phase_event"}
            assert 0.0 <= day["illumination_percent"] <= 100.0
            assert isinstance(day["waxing"], bool)
            assert day["moonless"] is (day["illumination_percent"] < 15.0)
            assert day["date"] == f"2026-09-{day['day']:02d}"


class TestPrincipalPhases:
    """The four principal phases for a month with known 2026 ephemeris."""

    def setup_method(self):
        self.result = build_phase_calendar(2026, 9, PARIS)

    def test_all_four_phase_types_present_once(self):
        types = [p["type"] for p in self.result["principal_phases"]]
        assert sorted(types) == ["first_quarter", "full", "last_quarter", "new"]

    def test_new_moon_falls_on_sept_11(self):
        new_moon = next(p for p in self.result["principal_phases"] if p["type"] == "new")
        assert new_moon["date"] == "2026-09-11"

    def test_full_moon_falls_on_sept_26(self):
        full_moon = next(p for p in self.result["principal_phases"] if p["type"] == "full")
        assert full_moon["date"] == "2026-09-26"

    def test_phase_event_is_attached_to_matching_day(self):
        day_11 = self.result["days"][10]
        assert day_11["day"] == 11
        assert day_11["phase_event"] is not None
        assert day_11["phase_event"]["type"] == "new"
        # The stored instant is a local ISO timestamp for the active timezone.
        assert day_11["phase_event"]["time"].startswith("2026-09-11T")
        assert "+02:00" in day_11["phase_event"]["time"]

    def test_new_moon_day_is_flagged_moonless(self):
        day_11 = self.result["days"][10]
        assert day_11["moonless"] is True
        assert day_11["illumination_percent"] < 5.0

    def test_days_without_a_phase_have_none(self):
        assert self.result["days"][0]["phase_event"] is None


class TestTimezoneBucketing:
    """A phase instant near local midnight must land on the correct local day."""

    def test_same_month_different_timezone_can_shift_the_day(self):
        # The Sept 2026 first-quarter instant is ~20:44 UTC on the 18th; in a far
        # eastern timezone that rolls into the 19th local.
        paris = {p["type"]: p["date"] for p in build_phase_calendar(2026, 9, PARIS)["principal_phases"]}
        kiritimati = {
            p["type"]: p["date"] for p in build_phase_calendar(2026, 9, "Pacific/Kiritimati")["principal_phases"]
        }
        assert paris["first_quarter"] == "2026-09-18"
        assert kiritimati["first_quarter"] == "2026-09-19"

    def test_principal_phase_dates_are_within_the_requested_month(self):
        result = build_phase_calendar(2026, 12, PARIS)
        for phase in result["principal_phases"]:
            parsed = datetime.date.fromisoformat(phase["date"])
            assert parsed.year == 2026 and parsed.month == 12

    def test_quarter_in_two_day_lookback_window_is_stepped_over(self):
        # The 2025 new moon is on Feb 28 (UTC); querying March starts the quarter
        # search two days earlier, so the first hit is that out-of-month phase and
        # must be skipped rather than recorded against March.
        result = build_phase_calendar(2025, 3, "UTC")
        assert result["principal_phases"]
        for phase in result["principal_phases"]:
            assert datetime.date.fromisoformat(phase["date"]).month == 3
        assert "2025-02-28" not in [p["time"][:10] for p in result["principal_phases"]]


class TestFullMoonDetails:
    """Full Moon events carry the astroweather.full_moons details."""

    def test_full_moon_event_carries_supermoon_details(self):
        """November 2026: the Full Moon cell and footer entry hold the Beaver supermoon."""
        result = build_phase_calendar(2026, 11, PARIS)
        day_24 = result["days"][23]
        assert day_24["phase_event"]["type"] == "full"
        details = day_24["phase_event"]["full_moon"]
        assert details["supermoon"] is True
        assert details["folk_name"] == "beaver"
        full = next(p for p in result["principal_phases"] if p["type"] == "full")
        assert full["full_moon"] == details
        assert full["date"] == "2026-11-24"

    def test_other_principal_phases_have_no_full_moon_details(self):
        """New Moon and quarters stay {type, time} (+ date in the footer list)."""
        result = build_phase_calendar(2026, 11, PARIS)
        for phase in result["principal_phases"]:
            if phase["type"] != "full":
                assert "full_moon" not in phase
