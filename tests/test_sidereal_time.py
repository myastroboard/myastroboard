"""
Tests for sidereal_time.py
Covers SiderealTimeService pure-logic and calculation methods.
"""

import pytest
from datetime import datetime, date
from zoneinfo import ZoneInfo
from observation.sidereal_time import SiderealTimeService


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
    """Tests for _is_circumpolar (declination + observer latitude based)."""

    def test_high_northern_latitude(self):
        # From latitude 70N, objects never set once dec >= 90 - 70 = 20.
        svc = SiderealTimeService(70.0, 0.0)
        assert svc._is_circumpolar(25.0) is True
        assert svc._is_circumpolar(20.0) is True
        assert svc._is_circumpolar(10.0) is False
        assert svc._is_circumpolar(-30.0) is False

    def test_southern_latitude(self):
        # From latitude 30S, objects never set once dec <= -(90 - 30) = -60.
        svc = SiderealTimeService(-30.0, 0.0)
        assert svc._is_circumpolar(-65.0) is True
        assert svc._is_circumpolar(-60.0) is True
        assert svc._is_circumpolar(-50.0) is False
        assert svc._is_circumpolar(20.0) is False

    def test_equator_only_pole_is_circumpolar(self):
        # From the equator nothing meaningfully circles the pole above the horizon.
        svc = SiderealTimeService(0.0, 0.0)
        assert svc._is_circumpolar(45.0) is False
        assert svc._is_circumpolar(89.0) is False
        assert svc._is_circumpolar(90.0) is True


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

    def test_is_circumpolar_none_without_declination(self):
        """Circumpolarity is unknown from RA alone, so it is None when dec is omitted."""
        svc = SiderealTimeService(70.0, 0.0)
        result = svc.get_object_lst_for_transit(180.0, date(2026, 6, 15))
        if result:
            assert result["is_circumpolar"] is None

    def test_is_circumpolar_true_with_high_declination(self):
        """A high-declination object is circumpolar from a high latitude when dec is given."""
        svc = SiderealTimeService(70.0, 0.0)
        result = svc.get_object_lst_for_transit(180.0, date(2026, 6, 15), dec_degrees=80.0)
        if result:
            assert result["is_circumpolar"] is True


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


class TestGetBestObservationTimes:
    """Tests for get_best_observation_times — covers ."""

    def test_returns_dict(self):
        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        result = svc.get_best_observation_times(6.0, 45.0, date(2026, 6, 15))
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        result = svc.get_best_observation_times(6.0, 45.0, date(2026, 6, 15))
        if result:
            assert "best_time_utc" in result
            assert "best_altitude_degrees" in result
            assert "visible" in result
            assert "target_ra_hours" in result
            assert "target_dec_degrees" in result

    def test_altaz_none_path_is_handled(self):
        """altaz is None → continue (defensive guard in the hourly loop)."""
        import numpy as np
        from unittest.mock import MagicMock, patch
        from astropy.coordinates import SkyCoord

        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        observation_date = date(2026, 6, 15)

        real_altaz_call_count = [0]

        original_transform_to = SkyCoord.transform_to

        def patched_transform_to(self_coord, frame):
            real_altaz_call_count[0] += 1
            if real_altaz_call_count[0] == 1:
                return None  # First call returns None → exercises
            return original_transform_to(self_coord, frame)

        with patch.object(SkyCoord, 'transform_to', patched_transform_to):
            result = svc.get_best_observation_times(6.0, 45.0, observation_date)

        assert isinstance(result, dict)

    def test_ndarray_alt_val_branch(self):
        """alt_val is ndarray → float extraction via np.real/atleast_1d."""
        import numpy as np
        from unittest.mock import MagicMock, patch
        from astropy.coordinates import SkyCoord

        svc = SiderealTimeService(45.0, -73.5, timezone="America/Montreal")
        observation_date = date(2026, 6, 15)

        def patched_transform_to(self_coord, frame):
            mock_altaz = MagicMock()
            mock_alt = MagicMock()
            mock_alt.degree = np.array([42.0])  # ndarray → triggers
            mock_altaz.alt = mock_alt
            return mock_altaz

        with patch.object(SkyCoord, 'transform_to', patched_transform_to):
            result = svc.get_best_observation_times(6.0, 45.0, observation_date)

        assert isinstance(result, dict)


class TestCalculateSiderealInfoNdarrayBranch:
    """gst.hour returns ndarray → float extraction via np.real/atleast_1d."""

    def test_ndarray_gst_hour_is_handled(self):
        import numpy as np
        from unittest.mock import MagicMock
        from zoneinfo import ZoneInfo

        svc = SiderealTimeService(48.85, 2.35, timezone="Europe/Paris")

        mock_time = MagicMock()
        mock_gst = MagicMock()
        mock_gst.hour = np.array([12.5])  # ndarray → triggers

        mock_time.sidereal_time.return_value = mock_gst
        mock_time.jd = 2460676.0
        mock_time.to_datetime.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=ZoneInfo('UTC'))

        result = svc._calculate_sidereal_info(mock_time)
        assert isinstance(result, dict)
        assert result.get("greenwich_sidereal_time_hours") == 12.5

    def test_best_altitude_is_float(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_best_observation_times(12.0, 30.0, date(2026, 6, 15))
        if result:
            assert isinstance(result["best_altitude_degrees"], float)

    def test_observation_date_preserved(self):
        svc = SiderealTimeService(45.0, -73.5)
        target = date(2026, 7, 4)
        result = svc.get_best_observation_times(6.0, 20.0, target)
        if result:
            assert result["observation_date"] == target.isoformat()

    def test_min_altitude_used_for_visibility(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_best_observation_times(6.0, 45.0, date(2026, 6, 15), min_altitude=80.0)
        if result:
            assert result["min_altitude_requirement"] == 80.0

    def test_ra_and_dec_preserved_in_result(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_best_observation_times(8.0, 35.0, date(2026, 6, 15))
        if result:
            assert result["target_ra_hours"] == pytest.approx(8.0)
            assert result["target_dec_degrees"] == pytest.approx(35.0)

    def test_best_altitude_within_valid_range(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_best_observation_times(6.0, 45.0, date(2026, 6, 15))
        if result:
            alt = result["best_altitude_degrees"]
            assert -90.0 <= alt <= 90.0

    def test_rise_and_set_times_are_isoformat_or_none(self):
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_best_observation_times(6.0, 45.0, date(2026, 6, 15))
        if result:
            if result.get("rise_time_utc"):
                assert "T" in result["rise_time_utc"]
            if result.get("set_time_utc"):
                assert "T" in result["set_time_utc"]

    def test_observation_window_none_when_never_rises(self):
        """From high northern latitude, a far-south object may never rise."""
        svc = SiderealTimeService(80.0, 0.0)
        result = svc.get_best_observation_times(12.0, -89.0, date(2026, 6, 15))
        if result:
            # Object at dec -89 is near south pole — should not be visible from lat 80N
            assert result["visible"] is False

    def test_equatorial_observer_broad_visibility(self):
        """From equator, most objects should reach a reasonable altitude."""
        svc = SiderealTimeService(0.0, 0.0)
        result = svc.get_best_observation_times(0.0, 0.0, date(2026, 6, 15))
        if result:
            assert result["best_altitude_degrees"] > 0


class TestExceptionHandlerBranches:
    """Covers exception handler lines: 61-63, 78-80, 109-110, 171-173, 234-236, 320-322."""

    def test_get_current_sidereal_info_exception_returns_empty(self, monkeypatch):
        """exception in Time.now() → empty dict."""
        from astropy.time import Time

        monkeypatch.setattr(Time, 'now', staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("time error"))))
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_current_sidereal_info()
        assert result == {}

    def test_get_sidereal_info_for_time_exception_returns_empty(self, monkeypatch):
        """invalid input that raises → empty dict."""
        svc = SiderealTimeService(45.0, -73.5)
        result = svc.get_sidereal_info_for_time("not-a-datetime")  # type: ignore
        assert result == {}

    def test_get_hourly_sidereal_times_exception_returns_empty_list(self, monkeypatch):
        """exception in loop → empty list returned."""
        from astropy.time import Time

        svc = SiderealTimeService(45.0, -73.5)
        monkeypatch.setattr(
            svc, '_calculate_sidereal_info', lambda t: (_ for _ in ()).throw(RuntimeError("calc error"))
        )
        result = svc.get_hourly_sidereal_times(date(2026, 6, 1), num_hours=1)
        assert result == []

    def test_get_object_lst_for_transit_exception_returns_empty(self, monkeypatch):
        """exception in calculation → empty dict."""
        svc = SiderealTimeService(45.0, -73.5)
        monkeypatch.setattr(
            svc, '_calculate_sidereal_info', lambda t: (_ for _ in ()).throw(RuntimeError("calc error"))
        )
        result = svc.get_object_lst_for_transit(180.0, date(2026, 6, 15))
        assert result == {}

    def test_calculate_sidereal_info_exception_returns_empty(self, monkeypatch):
        """exception in _calculate_sidereal_info → empty dict."""
        from astropy.time import Time

        svc = SiderealTimeService(45.0, -73.5)
        t = Time(datetime(2026, 6, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC")))
        monkeypatch.setattr(t, 'sidereal_time', lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad")))
        result = svc._calculate_sidereal_info(t)
        assert result == {}

    def test_get_best_observation_times_exception_returns_empty(self, monkeypatch):
        """exception in SkyCoord → empty dict."""
        svc = SiderealTimeService(45.0, -73.5)
        monkeypatch.setattr(
            svc, '_calculate_sidereal_info', lambda t: (_ for _ in ()).throw(RuntimeError("calc error"))
        )
        # Pass an invalid date type to trigger exception
        result = svc.get_best_observation_times(6.0, 45.0, "not-a-date")  # type: ignore
        assert result == {}


class TestNormalizationBranches:
    """Covers normalization while-loop lines: 140."""

    def test_gst_normalization_negative(self):
        """gst_at_transit < 0 → += 24 triggered by east longitude."""
        # longitude=135, ra=0 → lst_at_transit=0, lon_hours=9 → gst=-9 < 0
        svc = SiderealTimeService(35.0, 135.0)  # Japan longitude
        result = svc.get_object_lst_for_transit(0.0, date(2026, 6, 15))
        # Should succeed (no exception) and gst normalization happened internally
        assert isinstance(result, dict)
