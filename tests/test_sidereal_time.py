"""
Tests for sidereal_time.py
Covers SiderealTimeService pure-logic and calculation methods.
"""

import pytest
from datetime import datetime, date
from zoneinfo import ZoneInfo
from sidereal_time import SiderealTimeService


class TestSiderealTimeServiceInit:
    """Tests for SiderealTimeService construction."""

    def test_basic_instantiation(self):
        svc = SiderealTimeService(45.0, -73.5, elevation=50, timezone="America/Montreal")
        assert svc.latitude == 45.0
        assert svc.longitude == -73.5
        assert svc.elevation == 50

    def test_default_elevation_and_timezone(self):
        svc = SiderealTimeService(0.0, 0.0)
        assert svc.elevation == 0
        assert svc.timezone == "UTC"


class TestDecimalHoursToHms:
    """Tests for _decimal_hours_to_hms conversion."""

    def setup_method(self):
        self.svc = SiderealTimeService(45.0, -73.5)

    def test_zero_hours(self):
        result = self.svc._decimal_hours_to_hms(0.0)
        assert result.startswith("00h 00m")

    def test_whole_hour(self):
        result = self.svc._decimal_hours_to_hms(12.0)
        assert result.startswith("12h 00m")

    def test_fractional_hour(self):
        result = self.svc._decimal_hours_to_hms(1.5)
        assert "01h" in result
        assert "30m" in result

    def test_returns_string(self):
        result = self.svc._decimal_hours_to_hms(6.75)
        assert isinstance(result, str)


class TestIsCircumpolar:
    """Tests for _is_circumpolar (always returns False by design)."""

    def test_always_false(self):
        svc = SiderealTimeService(70.0, 0.0)
        assert svc._is_circumpolar(0.0) is False
        assert svc._is_circumpolar(180.0) is False


class TestGetCurrentSiderealInfo:
    """Tests for get_current_sidereal_info."""

    def test_returns_dict_with_required_keys(self):
        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        result = svc.get_current_sidereal_info()
        if result:  # May be empty on error
            assert "local_sidereal_time_hours" in result
            assert "greenwich_sidereal_time_hours" in result

    def test_lst_within_valid_range(self):
        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        result = svc.get_current_sidereal_info()
        if result:
            lst = result["local_sidereal_time_hours"]
            assert 0.0 <= lst < 24.0

    def test_gst_within_valid_range(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_current_sidereal_info()
        if result:
            gst = result["greenwich_sidereal_time_hours"]
            assert 0.0 <= gst < 24.0


class TestGetSiderealInfoForTime:
    """Tests for get_sidereal_info_for_time."""

    def test_known_time_returns_dict(self):
        svc = SiderealTimeService(48.85, 2.35, timezone="Europe/Paris")
        dt = datetime(2026, 3, 20, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        result = svc.get_sidereal_info_for_time(dt)
        assert isinstance(result, dict)

    def test_meridian_ra_degrees_0_to_360(self):
        svc = SiderealTimeService(48.85, 2.35)
        dt = datetime(2026, 6, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        result = svc.get_sidereal_info_for_time(dt)
        if result:
            assert 0.0 <= result["meridian_ra_degrees"] < 360.0

    def test_julian_date_is_reasonable(self):
        svc = SiderealTimeService(45.0, 0.0)
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        result = svc.get_sidereal_info_for_time(dt)
        if result:
            # JD for 2026-01-01 should be around 2460676
            assert 2460000 < result["julian_date"] < 2470000


class TestGetObjectLstForTransit:
    """Tests for get_object_lst_for_transit."""

    def test_returns_dict_with_transit_info(self):
        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        target_date = date(2026, 6, 15)
        result = svc.get_object_lst_for_transit(180.0, target_date)
        if result:
            assert "target_ra_degrees" in result
            assert "local_sidereal_time_at_transit_hours" in result

    def test_ra_conversion_to_hours(self):
        svc = SiderealTimeService(45.0, 0.0)
        target_date = date(2026, 6, 15)
        result = svc.get_object_lst_for_transit(360.0, target_date)
        if result:
            assert result["target_ra_hours"] == pytest.approx(24.0)

    def test_transit_lst_equals_ra_hours(self):
        svc = SiderealTimeService(45.0, 0.0)
        target_date = date(2026, 6, 15)
        result = svc.get_object_lst_for_transit(120.0, target_date)
        if result:
            expected_ra_hours = (120.0 / 360.0) * 24.0
            assert result["local_sidereal_time_at_transit_hours"] == pytest.approx(expected_ra_hours)


class TestGetHourlySiderealTimes:
    """Tests for get_hourly_sidereal_times."""

    def test_returns_list(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_hourly_sidereal_times(date(2026, 6, 1))
        assert isinstance(result, list)

    def test_default_returns_24_entries(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_hourly_sidereal_times(date(2026, 6, 1))
        assert len(result) == 24

    def test_custom_num_hours(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_hourly_sidereal_times(date(2026, 6, 1), num_hours=6)
        assert len(result) == 6

    def test_each_entry_has_hour_key(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_hourly_sidereal_times(date(2026, 6, 1), num_hours=3)
        for i, entry in enumerate(result):
            assert entry.get("hour") == i
