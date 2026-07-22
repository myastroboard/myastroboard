"""
Extended tests for iss_passes.py.
Supplements the existing 26-test file to push coverage above 50%.
"""

import pytest
import json
from space.iss_passes import (
    ISSPassService,
    _source_name_from_url,
    _is_celestrak_url,
    _is_celestrak_timeout_error,
)


class TestSourceNameFromUrl:
    """Tests for _source_name_from_url pure logic."""

    def test_celestrak_url(self):
        result = _source_name_from_url("https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE")
        assert result == "Celestrak"

    def test_ivanstanojevic_url(self):
        result = _source_name_from_url("https://tle.ivanstanojevic.me/api/tle/25544")
        assert result == "TLE API (ivanstanojevic.me)"

    def test_wheretheiss_url(self):
        result = _source_name_from_url("https://api.wheretheiss.at/v1/satellites/25544/tles")
        assert result == "WhereTheISS"

    def test_unknown_url(self):
        result = _source_name_from_url("https://example.com/tle")
        assert result == "Unknown"

    def test_empty_url(self):
        result = _source_name_from_url("")
        assert result == "Unknown"


class TestIsCelestrakUrl:
    """Tests for _is_celestrak_url."""

    def test_celestrak_org(self):
        assert _is_celestrak_url("https://celestrak.org/something") is True

    def test_subdomain_celestrak(self):
        assert _is_celestrak_url("https://sub.celestrak.org/path") is True

    def test_non_celestrak(self):
        assert _is_celestrak_url("https://tle.ivanstanojevic.me/api/tle/25544") is False

    def test_empty_url(self):
        assert _is_celestrak_url("") is False


class TestIsCelestrakTimeoutError:
    """Tests for _is_celestrak_timeout_error."""

    def test_requests_timeout_exception(self):
        import requests
        exc = requests.exceptions.Timeout("timed out")
        assert _is_celestrak_timeout_error(exc) is True

    def test_plain_exception_with_timeout_message(self):
        exc = Exception("connection timed out after 10s")
        assert _is_celestrak_timeout_error(exc) is True

    def test_non_timeout_exception(self):
        exc = Exception("some other error")
        assert _is_celestrak_timeout_error(exc) is False

    def test_connect_timeout_message(self):
        exc = Exception("connect timeout")
        assert _is_celestrak_timeout_error(exc) is True


class TestISSPassServiceInit:
    """Tests for ISSPassService initialization."""

    def test_basic_init(self):
        svc = ISSPassService(45.5, -73.5, 50.0, "America/Montreal")
        assert svc.latitude == 45.5
        assert svc.longitude == -73.5
        assert svc.elevation_m == 50.0

    def test_location_created(self):
        svc = ISSPassService(0.0, 0.0, 0.0, "UTC")
        assert svc.location is not None


class TestAzimuthToCardinal:
    """Tests for ISSPassService._azimuth_to_cardinal."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "America/Montreal")

    def test_north(self):
        assert self.svc._azimuth_to_cardinal(0.0) == "N"
        assert self.svc._azimuth_to_cardinal(360.0) == "N"

    def test_south(self):
        assert self.svc._azimuth_to_cardinal(180.0) == "S"

    def test_east(self):
        assert self.svc._azimuth_to_cardinal(90.0) == "E"

    def test_west(self):
        assert self.svc._azimuth_to_cardinal(270.0) == "W"

    def test_northeast(self):
        assert self.svc._azimuth_to_cardinal(45.0) == "NE"

    def test_all_cardinals_are_strings(self):
        for az in range(0, 360, 22):
            result = self.svc._azimuth_to_cardinal(float(az))
            assert isinstance(result, str)
            assert len(result) > 0


class TestClassifyDayNight:
    """Tests for ISSPassService._classify_day_night."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "America/Montreal")

    def test_astronomical_night(self):
        assert self.svc._classify_day_night(-20.0) == "Astronomical Night"

    def test_nautical_twilight(self):
        assert self.svc._classify_day_night(-15.0) == "Nautical Twilight"

    def test_civil_twilight(self):
        assert self.svc._classify_day_night(-8.0) == "Civil Twilight"

    def test_twilight(self):
        assert self.svc._classify_day_night(-2.0) == "Twilight"

    def test_daylight(self):
        assert self.svc._classify_day_night(5.0) == "Daylight"


class TestComputeVisibilityScore:
    """Tests for ISSPassService._compute_visibility_score."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "America/Montreal")

    def test_returns_value_in_0_100(self):
        score = self.svc._compute_visibility_score(45.0, 5.0, -20.0)
        assert 0.0 <= score <= 100.0

    def test_high_altitude_scores_higher(self):
        low_score = self.svc._compute_visibility_score(10.0, 5.0, -20.0)
        high_score = self.svc._compute_visibility_score(80.0, 5.0, -20.0)
        assert high_score > low_score

    def test_astronomical_night_scores_higher_than_daylight(self):
        night_score = self.svc._compute_visibility_score(45.0, 5.0, -20.0)
        day_score = self.svc._compute_visibility_score(45.0, 5.0, 10.0)
        assert night_score > day_score

    def test_longer_duration_scores_higher(self):
        short_score = self.svc._compute_visibility_score(45.0, 1.0, -20.0)
        long_score = self.svc._compute_visibility_score(45.0, 10.0, -20.0)
        assert long_score > short_score


class TestGroupConsecutiveIndices:
    """Tests for ISSPassService._group_consecutive_indices."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "America/Montreal")

    def test_empty_list(self):
        result = self.svc._group_consecutive_indices([])
        assert result == []

    def test_single_index(self):
        result = self.svc._group_consecutive_indices([5])
        assert result == [[5]]

    def test_consecutive_group(self):
        result = self.svc._group_consecutive_indices([1, 2, 3])
        assert result == [[1, 2, 3]]

    def test_two_separate_groups(self):
        result = self.svc._group_consecutive_indices([1, 2, 5, 6, 7])
        assert len(result) == 2
        assert result[0] == [1, 2]
        assert result[1] == [5, 6, 7]

    def test_non_consecutive_singles(self):
        result = self.svc._group_consecutive_indices([0, 3, 7])
        assert len(result) == 3


class TestParseTleFromResponse:
    """Tests for ISSPassService._parse_iss_tle_from_response."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "UTC")

    def test_parses_json_format(self):
        json_payload = json.dumps({
            "line1": "1 25544U 98067A   26001.00000000  .00001234  00000-0  12345-4 0  9999",
            "line2": "2 25544  51.6400 001.0000 0001234  00.0000  00.0000 15.50000000123456",
        })
        line1, line2 = self.svc._parse_iss_tle_from_response(json_payload)
        assert line1.startswith("1 ")
        assert line2.startswith("2 ")

    def test_parses_plain_text_format(self):
        tle_text = (
            "ISS (ZARYA)\n"
            "1 25544U 98067A   26001.00000000  .00001234  00000-0  12345-4 0  9999\n"
            "2 25544  51.6400 001.0000 0001234  00.0000  00.0000 15.50000000123456\n"
        )
        line1, line2 = self.svc._parse_iss_tle_from_response(tle_text)
        assert line1.startswith("1 ")
        assert line2.startswith("2 ")

    def test_raises_on_invalid_payload(self):
        with pytest.raises(ValueError, match="Could not parse"):
            self.svc._parse_iss_tle_from_response("not a valid TLE or JSON")


class TestAngularSeparationDeg:
    """Tests for ISSPassService._angular_separation_deg."""

    def setup_method(self):
        self.svc = ISSPassService(45.5, -73.5, 50.0, "UTC")

    def test_zero_separation_for_same_point(self):
        result = self.svc._angular_separation_deg(45.0, 90.0, 45.0, 90.0)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_positive_separation(self):
        result = self.svc._angular_separation_deg(30.0, 90.0, 45.0, 180.0)
        assert result > 0.0

    def test_result_in_degrees_range(self):
        result = self.svc._angular_separation_deg(0.0, 0.0, 90.0, 180.0)
        assert 0.0 <= result <= 180.0
