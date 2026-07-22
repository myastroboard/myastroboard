"""Unit tests for ISS pass service and ISS event aggregation."""

from datetime import datetime, timedelta, timezone
from requests import HTTPError
import numpy as np
import pytest

from space import iss_passes as iss_module

ISSPassService = iss_module.ISSPassService
get_iss_passes_report = iss_module.get_iss_passes_report
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = iss_module.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG
from utils.events_aggregator import EventsAggregator

mod = iss_module  # alias used by the merged-in coverage tests below


class TestISSPassServiceScoring:
    """Test score and day/night classification helpers."""

    def test_day_night_classification(self):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        assert service._classify_day_night(-20) == "Astronomical Night"
        assert service._classify_day_night(-15) == "Nautical Twilight"
        assert service._classify_day_night(-8) == "Civil Twilight"
        assert service._classify_day_night(-1) == "Twilight"
        assert service._classify_day_night(10) == "Daylight"

    def test_visibility_score_range(self):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        low_score = service._compute_visibility_score(
            peak_altitude_deg=12,
            duration_minutes=2,
            sun_altitude_deg=8,
        )
        high_score = service._compute_visibility_score(
            peak_altitude_deg=80,
            duration_minutes=10,
            sun_altitude_deg=-20,
        )

        assert 0 <= low_score <= 100
        assert 0 <= high_score <= 100
        assert high_score > low_score

    def test_azimuth_to_cardinal(self):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        assert service._azimuth_to_cardinal(0) == "N"
        assert service._azimuth_to_cardinal(90) == "E"
        assert service._azimuth_to_cardinal(180) == "S"
        assert service._azimuth_to_cardinal(270) == "W"
        assert service._azimuth_to_cardinal(225) == "SW"


class TestISSPassServiceWrapper:
    """Test top-level ISS wrapper behavior."""

    def test_get_iss_passes_report_handles_exceptions(self, monkeypatch):
        def _raise_error(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(ISSPassService, "get_report", _raise_error)

        result = get_iss_passes_report(
            latitude=45.5,
            longitude=-73.5,
            elevation_m=30,
            timezone_str="America/Montreal",
            days=20,
        )

        assert result is None


class TestISSPassServiceSolarTransit:
    """Test ISS solar transit detection helpers."""

    def test_extract_solar_transit_segment_returns_refined_window(self, monkeypatch):
        import numpy as np

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)
        # The ISS sweeps through the Sun's azimuth, so the ISS/Sun separation dips
        # to zero at the window centre (a real transit) and the fine scan pins it.
        center = start_utc + timedelta(seconds=15)

        def fake_iss(times, *args, **kwargs):
            secs = np.array([(t - center).total_seconds() for t in times])
            return np.full(len(times), 30.0), 180.0 + secs * 0.5  # 0.5°/s sweep past the Sun

        def fake_sun(times, *args, **kwargs):
            n = len(times)
            return np.full(n, 30.0), np.full(n, 180.0), np.full(n, 0.27)

        monkeypatch.setattr(service, "_iss_altaz_arrays", fake_iss)
        monkeypatch.setattr(service, "_sun_altaz_radius_arrays", fake_sun)

        transit = service._extract_solar_transit_segment(start_utc, end_utc, None, None, None, None)

        assert transit is not None
        assert transit["is_visible"] is True
        assert transit["pass_type"] == "solar_transit"
        assert transit["sun_altitude_deg"] == 30.0
        assert transit["iss_altitude_deg"] == 30.0
        assert transit["minimum_separation_arcmin"] < 1.0  # closest approach is essentially zero
        peak = datetime.fromisoformat(transit["peak_time"]).astimezone(timezone.utc)
        assert abs((peak - center).total_seconds()) < 1.0  # peak lands at the closest approach

    def test_extract_solar_transit_segment_returns_none_when_iss_never_near_sun(self, monkeypatch):
        import numpy as np

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

        # ISS stays ~40° from the Sun for the whole pass -> rejected at the coarse stage.
        monkeypatch.setattr(
            service, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 70.0), np.full(len(times), 180.0))
        )
        monkeypatch.setattr(
            service,
            "_sun_altaz_radius_arrays",
            lambda times, *a, **k: (np.full(len(times), 30.0), np.full(len(times), 180.0), np.full(len(times), 0.27)),
        )

        assert service._extract_solar_transit_segment(start_utc, end_utc, None, None, None, None) is None


class TestISSPassServiceTleFallback:
    """Test ISS TLE multi-source fallback behavior."""

    @pytest.fixture(autouse=True)
    def _isolate_celestrak_block_state(self, monkeypatch):
        monkeypatch.setattr("space.iss_passes.get_celestrak_status", lambda: {"blocked": False})
        monkeypatch.setattr("space.iss_passes._set_celestrak_block", lambda *args, **kwargs: None)
        monkeypatch.setattr("space.iss_passes._clear_celestrak_block", lambda *args, **kwargs: None)

    def test_fetch_iss_tle_stops_immediately_after_celestrak_http_403(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        calls = {"count": 0}

        monkeypatch.setattr("space.iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.iss_passes._set_tle_error_timestamp", lambda: None)

        class _Response:
            def __init__(self, text: str, error=None):
                self.text = text
                self._error = error

            def raise_for_status(self):
                if self._error is not None:
                    raise self._error

        def _mock_get(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return _Response("", HTTPError("403 Client Error: Forbidden"))
            return _Response(
                "ISS (ZARYA)\n"
                "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991\n"
                "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000\n"
            )

        monkeypatch.setattr("space.iss_passes.requests.get", _mock_get)

        with pytest.raises(RuntimeError):
            service._fetch_iss_tle()

        # Policy compliance: non-200 on Celestrak must stop immediately.
        assert calls["count"] == 1

    def test_fetch_iss_tle_raises_when_all_sources_fail(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.iss_passes._set_tle_error_timestamp", lambda: None)

        class _Response:
            def raise_for_status(self):
                raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("space.iss_passes.requests.get", lambda *args, **kwargs: _Response())

        try:
            service._fetch_iss_tle()
            assert False, "Expected RuntimeError when all TLE sources fail"
        except RuntimeError as exc:
            assert "Failed to fetch ISS TLE from all sources" in str(exc)

    def test_fetch_iss_tle_uses_cache_in_cooldown(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr(
            "space.iss_passes._get_cached_tle",
            lambda max_age_seconds=None: (
                "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
                "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
                0,
            ),
        )
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: True)

        called = {"count": 0}

        def _should_not_call(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("Network should not be called in cooldown with cache")

        monkeypatch.setattr("space.iss_passes.requests.get", _should_not_call)

        line1, line2 = service._fetch_iss_tle()
        assert line1.startswith("1 25544")
        assert line2.startswith("2 25544")
        assert called["count"] == 0

    def test_fetch_iss_tle_uses_stale_cache_after_source_failures(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.iss_passes._set_tle_error_timestamp", lambda: None)

        def _mock_get(*args, **kwargs):
            raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("space.iss_passes.requests.get", _mock_get)

        def _cached(max_age_seconds=None):
            if max_age_seconds is None:
                return (
                    "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
                    "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
                    0,
                )
            return None

        monkeypatch.setattr("space.iss_passes._get_cached_tle", _cached)

        line1, line2 = service._fetch_iss_tle()
        assert line1.startswith("1 25544")
        assert line2.startswith("2 25544")

    def test_parse_iss_tle_from_json_response(self):
        """Parser handles JSON bodies returned by tle.ivanstanojevic.me and wheretheiss.at."""
        import json as _json

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        line1_str = "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
        line2_str = "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000"

        # tle.ivanstanojevic.me-style payload
        payload_ivan = _json.dumps(
            {
                "@type": "TleModel",
                "name": "ISS (ZARYA)",
                "date": "2026-04-10T00:00:00+00:00",
                "line1": line1_str,
                "line2": line2_str,
            }
        )
        l1, l2 = service._parse_iss_tle_from_response(payload_ivan)
        assert l1 == line1_str
        assert l2 == line2_str

        # wheretheiss.at-style payload
        payload_wheretheiss = _json.dumps(
            {
                "name": "ISS (ZARYA)",
                "satelliteId": 25544,
                "line1": line1_str,
                "line2": line2_str,
                "requestedAt": "2026-04-10T00:00:00.000Z",
                "source": "celestrak",
            }
        )
        l1, l2 = service._parse_iss_tle_from_response(payload_wheretheiss)
        assert l1 == line1_str
        assert l2 == line2_str

    def test_fetch_iss_tle_uses_alternative_source_when_celestrak_blocked(self, monkeypatch):
        """Alternative JSON sources are tried after Celestrak timeout/block."""
        import json as _json

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        line1_str = "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
        line2_str = "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000"

        monkeypatch.setattr("space.iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.iss_passes._set_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("space.iss_passes._set_cached_tle", lambda l1, l2: None)

        calls = []

        class _TimeoutError(Exception):
            pass

        def _mock_get(url, **kwargs):
            calls.append(url)
            if "celestrak" in url:
                raise _TimeoutError("Connection timed out")
            # First non-Celestrak URL returns JSON TLE
            return type(
                "R",
                (),
                {
                    "text": _json.dumps({"line1": line1_str, "line2": line2_str}),
                    "raise_for_status": lambda self: None,
                },
            )()

        monkeypatch.setattr("space.iss_passes.requests.get", _mock_get)

        l1, l2 = service._fetch_iss_tle()

        assert l1 == line1_str
        assert l2 == line2_str
        # The first Celestrak URL is tried and fails; the first alternative succeeds
        assert calls[0] == iss_module.ISS_TLE_URLS[0]
        assert "celestrak" not in calls[-1]

    def test_fetch_iss_tle_skips_celestrak_when_block_flag_is_set(self, monkeypatch):
        import json as _json

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        line1_str = "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
        line2_str = "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000"

        monkeypatch.setattr("space.iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.iss_passes._set_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("space.iss_passes._set_cached_tle", lambda l1, l2: None)
        monkeypatch.setattr("space.iss_passes.get_celestrak_status", lambda: {"blocked": True})

        calls = []

        def _mock_get(url, **kwargs):
            calls.append(url)
            if iss_module._is_celestrak_url(url):
                raise AssertionError("Celestrak URL should be skipped when block flag is set")
            return type(
                "R",
                (),
                {
                    "text": _json.dumps({"line1": line1_str, "line2": line2_str}),
                    "status_code": 200,
                    "raise_for_status": lambda self: None,
                },
            )()

        monkeypatch.setattr("space.iss_passes.requests.get", _mock_get)

        l1, l2 = service._fetch_iss_tle()
        assert l1 == line1_str
        assert l2 == line2_str
        assert len(calls) == 1
        assert not iss_module._is_celestrak_url(calls[0])

    def test_fetch_iss_tle_marks_celestrak_blocked_after_3_timeouts(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.iss_passes._in_tle_failure_cooldown", lambda: False)

        cache_payload = {}

        def _mock_read_cache():
            return dict(cache_payload)

        def _mock_write_cache(payload):
            cache_payload.clear()
            cache_payload.update(payload)

        monkeypatch.setattr("space.iss_passes._read_tle_cache", _mock_read_cache)
        monkeypatch.setattr("space.iss_passes._write_tle_cache", _mock_write_cache)

        block_calls = []

        def _mock_set_celestrak_block(status_code, reason, source_url):
            block_calls.append(
                {
                    "status_code": status_code,
                    "reason": reason,
                    "source_url": source_url,
                }
            )

        monkeypatch.setattr("space.iss_passes._set_celestrak_block", _mock_set_celestrak_block)

        class _Response:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

        def _mock_get(url, **kwargs):
            if iss_module._is_celestrak_url(url):
                raise Exception("Connection to celestrak.org timed out. (connect timeout=10)")
            return _Response()

        monkeypatch.setattr("space.iss_passes.requests.get", _mock_get)

        for _ in range(3):
            with pytest.raises(RuntimeError):
                service._fetch_iss_tle()

        assert int(cache_payload.get("celestrak_timeout_streak") or 0) == 3
        assert len(block_calls) == 1
        assert block_calls[0]["status_code"] == 0
        assert "Consecutive Celestrak timeout threshold reached" in block_calls[0]["reason"]


class TestISSCalendarAggregation:
    """Test ISS event integration in event aggregation payload."""

    def test_aggregate_all_events_includes_iss_event(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        base_day = aggregator.local_now.replace(hour=20, minute=0, second=0, microsecond=0)
        pass_1_peak = base_day + timedelta(days=1, minutes=4)
        pass_2_peak = base_day + timedelta(days=3, minutes=6)
        pass_3_peak_outside = base_day + timedelta(days=9, minutes=8)

        iss_payload = {
            "passes": [
                {
                    "start_time": (base_day + timedelta(days=1)).isoformat(),
                    "peak_time": pass_1_peak.isoformat(),
                    "end_time": (base_day + timedelta(days=1, minutes=8)).isoformat(),
                    "peak_altitude_deg": 64.0,
                    "duration_minutes": 8.0,
                    "visibility_score": 82.5,
                    "visibility_day_night": "Astronomical Night",
                    "is_visible": True,
                },
                {
                    "start_time": (base_day + timedelta(days=3)).isoformat(),
                    "peak_time": pass_2_peak.isoformat(),
                    "end_time": (base_day + timedelta(days=3, minutes=10)).isoformat(),
                    "peak_altitude_deg": 52.0,
                    "duration_minutes": 10.0,
                    "visibility_score": 61.0,
                    "visibility_day_night": "Astronomical Night",
                    "is_visible": True,
                },
                {
                    "start_time": (base_day + timedelta(days=9)).isoformat(),
                    "peak_time": pass_3_peak_outside.isoformat(),
                    "end_time": (base_day + timedelta(days=9, minutes=9)).isoformat(),
                    "peak_altitude_deg": 40.0,
                    "duration_minutes": 9.0,
                    "visibility_score": 55.0,
                    "visibility_day_night": "Astronomical Night",
                    "is_visible": True,
                },
            ]
        }

        result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)

        assert result["events_count"] == 2
        assert result["upcoming_events"][0]["event_type"] == "ISS Pass"
        assert result["upcoming_events"][0]["title"] == "ISS Visible Passage"
        assert result["upcoming_events"][0]["structure_key"] == "iss"

    def test_aggregate_all_events_includes_iss_solar_transit(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language="fr")

        peak_time = (aggregator.local_now + timedelta(days=1)).replace(hour=11, minute=30, second=0, microsecond=0)
        iss_payload = {
            "solar_transits": [
                {
                    "start_time": (peak_time - timedelta(seconds=1)).isoformat(),
                    "peak_time": peak_time.isoformat(),
                    "end_time": (peak_time + timedelta(seconds=1)).isoformat(),
                    "duration_seconds": 0.8,
                    "minimum_separation_arcmin": 0.18,
                    "solar_radius_arcmin": 15.9,
                    "sun_altitude_deg": 36.2,
                    "is_visible": True,
                }
            ]
        }

        result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)

        assert result["events_count"] == 1
        event = result["upcoming_events"][0]
        assert event["event_type"] == "ISS Solar Transit"
        assert event["title"] == "Transit solaire de l'ISS"
        assert event["structure_key"] == "iss"
        assert "0.18" in event["description"]

    def test_aggregate_all_events_includes_iss_lunar_transit(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language="fr")

        peak_time = (aggregator.local_now + timedelta(days=2)).replace(hour=22, minute=15, second=0, microsecond=0)
        iss_payload = {
            "lunar_transits": [
                {
                    "start_time": (peak_time - timedelta(seconds=0.5)).isoformat(),
                    "peak_time": peak_time.isoformat(),
                    "end_time": (peak_time + timedelta(seconds=0.5)).isoformat(),
                    "duration_seconds": 0.6,
                    "minimum_separation_arcmin": 0.22,
                    "lunar_radius_arcmin": 14.7,
                    "moon_altitude_deg": 42.5,
                    "moon_azimuth_deg": 195.0,
                    "moon_illumination_pct": 78.0,
                    "iss_altitude_deg": 42.3,
                    "iss_azimuth_deg": 195.1,
                    "pass_type": "lunar_transit",
                    "is_visible": True,
                }
            ]
        }

        result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)

        assert result["events_count"] == 1
        event = result["upcoming_events"][0]
        assert event["event_type"] == "ISS Lunar Transit"
        assert event["title"] == "Transit lunaire de l'ISS"
        assert event["structure_key"] == "iss"
        assert event["importance"] == "critical"
        assert event["score"] == 9.0
        assert "0.22" in event["description"]
        assert "78" in event["description"]

    def test_aggregate_all_events_iss_lunar_transit_all_languages(self):
        """Verify the lunar transit title is present in all supported languages."""
        expected_titles = {
            "en": "ISS Lunar Transit",
            "fr": "Transit lunaire de l'ISS",
            "de": "ISS-Mondtransit",
            "es": "Tránsito lunar de la ISS",
            "it": "Transito lunare della ISS",
            "pt": "Trânsito lunar da ISS",
        }
        for lang, expected_title in expected_titles.items():
            aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language=lang)
            peak_time = (aggregator.local_now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
            iss_payload = {
                "lunar_transits": [
                    {
                        "start_time": (peak_time - timedelta(seconds=0.5)).isoformat(),
                        "peak_time": peak_time.isoformat(),
                        "end_time": (peak_time + timedelta(seconds=0.5)).isoformat(),
                        "duration_seconds": 0.5,
                        "minimum_separation_arcmin": 0.10,
                        "lunar_radius_arcmin": 14.7,
                        "moon_altitude_deg": 30.0,
                        "moon_azimuth_deg": 180.0,
                        "moon_illumination_pct": 50.0,
                        "iss_altitude_deg": 30.1,
                        "iss_azimuth_deg": 180.1,
                        "pass_type": "lunar_transit",
                        "is_visible": True,
                    }
                ]
            }
            result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)
            assert result["events_count"] == 1, f"Expected 1 event for lang={lang}"
            assert result["upcoming_events"][0]["title"] == expected_title, f"Title mismatch for lang={lang}"

    def test_aggregate_all_events_iss_lunar_transit_outside_window_excluded(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        # 10 days out - should be excluded
        peak_time = (aggregator.local_now + timedelta(days=10)).replace(hour=21, minute=0, second=0, microsecond=0)
        iss_payload = {
            "lunar_transits": [
                {
                    "start_time": (peak_time - timedelta(seconds=0.5)).isoformat(),
                    "peak_time": peak_time.isoformat(),
                    "end_time": (peak_time + timedelta(seconds=0.5)).isoformat(),
                    "duration_seconds": 0.5,
                    "minimum_separation_arcmin": 0.10,
                    "lunar_radius_arcmin": 14.7,
                    "moon_altitude_deg": 30.0,
                    "moon_azimuth_deg": 180.0,
                    "moon_illumination_pct": 50.0,
                    "iss_altitude_deg": 30.1,
                    "iss_azimuth_deg": 180.1,
                    "pass_type": "lunar_transit",
                    "is_visible": True,
                }
            ]
        }

        result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)
        assert result["events_count"] == 0

    def test_aggregate_all_events_iss_lunar_transit_uses_next_lunar_transit_fallback(self):
        """next_lunar_transit fallback is used when lunar_transits list is absent."""
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        peak_time = (aggregator.local_now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
        iss_payload = {
            "next_lunar_transit": {
                "start_time": (peak_time - timedelta(seconds=0.5)).isoformat(),
                "peak_time": peak_time.isoformat(),
                "end_time": (peak_time + timedelta(seconds=0.5)).isoformat(),
                "duration_seconds": 0.5,
                "minimum_separation_arcmin": 0.10,
                "lunar_radius_arcmin": 14.7,
                "moon_altitude_deg": 30.0,
                "moon_azimuth_deg": 180.0,
                "moon_illumination_pct": 50.0,
                "iss_altitude_deg": 30.1,
                "iss_azimuth_deg": 180.1,
                "pass_type": "lunar_transit",
                "is_visible": True,
            }
        }

        result = aggregator.aggregate_all_events(iss_passes_data=iss_payload)
        assert result["events_count"] == 1
        assert result["upcoming_events"][0]["event_type"] == "ISS Lunar Transit"


class TestISSPassServiceLunarTransit:
    """Test ISS lunar transit detection helpers."""

    @staticmethod
    def _patch_moon_arrays(monkeypatch, service, center, moon_alt=40.0, illum=75.0):
        import numpy as np

        def fake_iss(times, *args, **kwargs):
            secs = np.array([(t - center).total_seconds() for t in times])
            return np.full(len(times), moon_alt), 195.0 + secs * 0.5

        def fake_moon(times, *args, **kwargs):
            n = len(times)
            return (
                np.full(n, moon_alt),
                np.full(n, 195.0),
                np.full(n, 0.27),
                np.full(n, illum),
            )

        monkeypatch.setattr(service, "_iss_altaz_arrays", fake_iss)
        monkeypatch.setattr(service, "_moon_altaz_radius_illum_arrays", fake_moon)

    def test_extract_lunar_transit_segment_returns_refined_window(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)
        center = start_utc + timedelta(seconds=15)
        self._patch_moon_arrays(monkeypatch, service, center, moon_alt=40.0, illum=75.0)

        transit = service._extract_lunar_transit_segment(start_utc, end_utc, None, None, None, None)

        assert transit is not None
        assert transit["pass_type"] == "lunar_transit"
        assert transit["moon_altitude_deg"] == 40.0
        assert transit["moon_illumination_pct"] == 75.0
        assert transit["minimum_separation_arcmin"] < 1.0
        assert transit["is_visible"] is True
        peak = datetime.fromisoformat(transit["peak_time"]).astimezone(timezone.utc)
        assert abs((peak - center).total_seconds()) < 1.0

    def test_extract_lunar_transit_segment_returns_none_when_no_candidates(self, monkeypatch):
        import numpy as np

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

        # ISS stays ~30° from the Moon for the whole pass -> rejected at the coarse stage.
        monkeypatch.setattr(
            service, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 70.0), np.full(len(times), 195.0))
        )
        monkeypatch.setattr(
            service,
            "_moon_altaz_radius_illum_arrays",
            lambda times, *a, **k: (
                np.full(len(times), 40.0),
                np.full(len(times), 195.0),
                np.full(len(times), 0.27),
                np.full(len(times), 50.0),
            ),
        )

        assert service._extract_lunar_transit_segment(start_utc, end_utc, None, None, None, None) is None

    def test_extract_lunar_transit_segment_returns_none_when_moon_too_low(self, monkeypatch):
        import numpy as np

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

        # Moon below LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG (5°) even though the ISS crosses it.
        monkeypatch.setattr(
            service, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 2.0), np.full(len(times), 195.0))
        )
        monkeypatch.setattr(
            service,
            "_moon_altaz_radius_illum_arrays",
            lambda times, *a, **k: (
                np.full(len(times), 2.0),
                np.full(len(times), 195.0),
                np.full(len(times), 0.27),
                np.full(len(times), 50.0),
            ),
        )

        assert service._extract_lunar_transit_segment(start_utc, end_utc, None, None, None, None) is None

    def test_find_lunar_transits_skipped_without_ephemeris(self, monkeypatch):
        """_find_lunar_transits returns [] gracefully when eph is None."""
        from datetime import datetime, timezone

        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 0, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)

        result = service._find_lunar_transits(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert result == []

    def test_lunar_angular_radius_fallback(self):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        class _BadApparent:
            def distance(self):
                raise ValueError("no distance")

        radius = service._lunar_angular_radius_deg(_BadApparent())
        assert radius == LUNAR_ANGULAR_RADIUS_FALLBACK_DEG

    def test_get_report_includes_lunar_transit_keys(self, monkeypatch):
        """get_report() always returns lunar_transits / next_lunar_transit / total_lunar_transits."""
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr(
            service,
            "_fetch_iss_tle",
            lambda: (
                "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
                "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
            ),
        )
        monkeypatch.setattr(service, "_load_ephemeris", lambda: None)
        monkeypatch.setattr(service, "_build_passes", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_solar_transits", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_lunar_transits", lambda *args, **kwargs: [])

        from skyfield.api import Loader
        import os
        from utils.constants import DATA_DIR_CACHE

        SKYFIELD_CACHE_DIR = os.path.join(DATA_DIR_CACHE, "skyfield")
        os.makedirs(SKYFIELD_CACHE_DIR, exist_ok=True)

        # Patch find_events to return empty sequences
        class _FakeTS:
            def from_datetime(self, dt):
                return dt

            def timescale(self):
                return self

        fake_ts = _FakeTS()
        monkeypatch.setattr(
            iss_module,
            "SKYFIELD_LOADER",
            type(
                "L",
                (),
                {
                    "timescale": lambda self: fake_ts,
                },
            )(),
        )

        class _FakeSatellite:
            def find_events(self, *args, **kwargs):
                return [], []

        monkeypatch.setattr(iss_module, "EarthSatellite", lambda *args, **kwargs: _FakeSatellite())
        monkeypatch.setattr(
            iss_module,
            "wgs84",
            type(
                "W",
                (),
                {
                    "latlon": lambda *args, **kwargs: None,
                },
            )(),
        )

        report = service.get_report(days=1)

        assert "lunar_transits" in report
        assert "next_lunar_transit" in report
        assert "total_lunar_transits" in report
        assert isinstance(report["lunar_transits"], list)
        assert report["total_lunar_transits"] == 0

    def test_aggregate_all_events_localizes_titles_with_language(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language="fr")

        peak_time = (aggregator.local_now + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
        solar_payload = {
            "solar_eclipse": {
                "visible": True,
                "type": "Partial",
                "peak_time": peak_time.isoformat(),
                "start_time": (peak_time - timedelta(minutes=30)).isoformat(),
                "end_time": (peak_time + timedelta(minutes=30)).isoformat(),
                "obscuration_percent": 38.0,
                "peak_altitude_deg": 22.0,
                "astrophotography_score": 6.2,
            }
        }

        result = aggregator.aggregate_all_events(solar_eclipse_data=solar_payload)

        assert result["events_count"] == 1
        event = result["upcoming_events"][0]
        assert event["event_type"] == "Solar Eclipse"
        assert "Éclipse Solaire" in event["title"]
        assert event["structure_key"] == "sun"


# ---------------------------------------------------------------------------
# Merged from former test_iss_passes_coverage_push.py (single-module coverage extension)
# ---------------------------------------------------------------------------
class _Deg:
    def __init__(self, degrees):
        self.degrees = degrees


class _Dist:
    def __init__(self, km):
        self.km = km


@pytest.fixture(autouse=True)
def _reset_ephemeris_memo():
    """Reset the process-wide de421 memo so each test's SKYFIELD_LOADER patch applies.

    Closes a real ephemeris object before discarding the reference - otherwise the
    underlying open file is only reclaimed by the garbage collector later, which
    surfaces as a ResourceWarning attributed to whatever unrelated test happens to
    be running when GC finalizes it.
    """
    if mod._EPHEMERIS is not None and hasattr(mod._EPHEMERIS, "close"):
        mod._EPHEMERIS.close()
    mod._EPHEMERIS = None
    mod._EPHEMERIS_ATTEMPTED = False
    yield
    if mod._EPHEMERIS is not None and hasattr(mod._EPHEMERIS, "close"):
        mod._EPHEMERIS.close()
    mod._EPHEMERIS = None
    mod._EPHEMERIS_ATTEMPTED = False


def _patch_solar_arrays(monkeypatch, svc, center, iss_alt=30.0, sun_alt=30.0, az_rate=0.5):
    """Feed the vectorised solar helpers so the ISS/Sun separation dips at ``center``."""

    def fake_iss(times, *args, **kwargs):
        secs = np.array([(t - center).total_seconds() for t in times])
        return np.full(len(times), iss_alt), 180.0 + secs * az_rate

    def fake_sun(times, *args, **kwargs):
        n = len(times)
        return np.full(n, sun_alt), np.full(n, 180.0), np.full(n, 0.27)

    monkeypatch.setattr(svc, "_iss_altaz_arrays", fake_iss)
    monkeypatch.setattr(svc, "_sun_altaz_radius_arrays", fake_sun)


def _patch_moon_arrays(monkeypatch, svc, center, iss_alt=40.0, moon_alt=40.0, illum=10.0):
    """Feed the vectorised lunar helpers so the ISS/Moon separation dips at ``center``."""

    def fake_iss(times, *args, **kwargs):
        secs = np.array([(t - center).total_seconds() for t in times])
        return np.full(len(times), iss_alt), 180.0 + secs * 0.5

    def fake_moon(times, *args, **kwargs):
        n = len(times)
        return np.full(n, moon_alt), np.full(n, 180.0), np.full(n, 0.27), np.full(n, illum)

    monkeypatch.setattr(svc, "_iss_altaz_arrays", fake_iss)
    monkeypatch.setattr(svc, "_moon_altaz_radius_illum_arrays", fake_moon)


def test_cache_helper_roundtrip_branches(monkeypatch):
    store = {}

    monkeypatch.setattr(mod, "_read_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_tle_cache", lambda payload: (store.clear(), store.update(payload)))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 1000)

    assert mod._get_cached_tle() is None

    mod._set_cached_tle("1 25544 A", "2 25544 B")
    assert store["line1"] == "1 25544 A"
    assert store["line2"] == "2 25544 B"
    assert store["fetched_at"] == 1000
    assert store["last_error_at"] is None

    assert mod._get_cached_tle(max_age_seconds=10) == ("1 25544 A", "2 25544 B", 1000)

    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 2000)
    assert mod._get_cached_tle(max_age_seconds=10) is None


def test_cooldown_false_and_clear_resets_last_error(monkeypatch):
    store = {}
    monkeypatch.setattr(mod, "_read_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_tle_cache", lambda payload: (store.clear(), store.update(payload)))

    assert mod._in_tle_failure_cooldown() is False

    store["last_error_at"] = 42
    mod._clear_celestrak_block(reset_failure_cooldown=True)
    assert store["last_error_at"] is None


def test_read_write_cache_non_dict(monkeypatch):
    seen = {}
    monkeypatch.setattr(mod, "load_json_file", lambda *a, **k: [])
    monkeypatch.setattr(mod, "save_json_file", lambda path, payload: seen.update({"path": path, "payload": payload}))

    assert mod._read_tle_cache() == {}
    mod._write_tle_cache({"x": 1})
    assert seen["payload"] == {"x": 1}


def test_source_info_and_celestrak_status_helpers(monkeypatch):
    store = {
        "last_source_name": " Celestrak ",
        "last_source_url": " https://celestrak.org ",
        "fetched_at": "123",
        "celestrak_blocked": True,
        "celestrak_blocked_at": "10",
        "celestrak_blocked_status_code": "403",
        "celestrak_blocked_reason": " denied ",
        "celestrak_blocked_source_url": " https://celestrak.org/a ",
        "celestrak_timeout_streak": "2",
        "celestrak_last_timeout_at": "11",
        "celestrak_last_timeout_reason": " timeout ",
        "celestrak_last_timeout_source_url": " https://celestrak.org/b ",
    }
    monkeypatch.setattr(mod, "_read_tle_cache", lambda: dict(store))

    info = mod.get_iss_tle_source_info()
    assert info["name"] == "Celestrak"
    assert info["url"] == "https://celestrak.org"
    assert info["fetched_at"] == 123

    status = mod.get_celestrak_status()
    assert status["blocked"] is True
    assert status["blocked_status_code"] == 403
    assert status["blocked_reason"] == "denied"
    assert status["timeout_streak"] == 2
    assert status["last_timeout_reason"] == "timeout"


def test_cooldown_and_block_state_mutators(monkeypatch):
    store = {}
    monkeypatch.setattr(mod, "_read_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_tle_cache", lambda payload: (store.clear(), store.update(payload)))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100)

    mod._set_tle_error_timestamp()
    assert store["last_error_at"] == 100

    assert mod._in_tle_failure_cooldown() is True
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100 + mod.ISS_TLE_FAILURE_COOLDOWN_SECONDS + 1)
    assert mod._in_tle_failure_cooldown() is False

    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 200)
    mod._set_celestrak_block(403, "forbidden", "https://celestrak.org/x")
    assert store["celestrak_blocked"] is True
    assert store["celestrak_blocked_status_code"] == 403

    streak = mod._increment_celestrak_timeout_streak("timed out", "https://celestrak.org/y")
    assert streak == 1
    assert store["celestrak_timeout_streak"] == 1

    mod._reset_celestrak_timeout_streak()
    assert store["celestrak_timeout_streak"] == 0

    mod._clear_celestrak_block(reset_failure_cooldown=False)
    assert store["celestrak_blocked"] is False
    assert store["last_error_at"] == 100


def test_clear_celestrak_block_flag_calls_clear(monkeypatch):
    called = {"clear": 0}
    monkeypatch.setattr(
        mod, "_clear_celestrak_block", lambda reset_failure_cooldown=True: called.update({"clear": called["clear"] + 1})
    )
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": False})
    result = mod.clear_celestrak_block_flag()
    assert called["clear"] == 1
    assert result == {"blocked": False}


def test_get_report_clamps_days_and_filters_visibility(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")

    monkeypatch.setattr(svc, "_fetch_iss_tle", lambda: ("1 25544 X", "2 25544 Y"))
    monkeypatch.setattr(svc, "_load_ephemeris", object)

    class _TS:
        def from_datetime(self, dt):
            return dt

    class _Loader:
        def timescale(self):
            return _TS()

    class _Sat:
        def __init__(self, *args, **kwargs):
            pass

        def find_events(self, *args, **kwargs):
            return [object()], [0]

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    monkeypatch.setattr(mod, "EarthSatellite", _Sat)
    monkeypatch.setattr(mod.wgs84, "latlon", lambda *a, **k: object())
    monkeypatch.setattr(svc, "_build_passes", lambda *a, **k: [{"is_visible": False}, {"is_visible": True, "id": "v1"}])
    monkeypatch.setattr(svc, "_find_solar_transits", lambda *a, **k: [{"id": "s1"}])
    monkeypatch.setattr(svc, "_find_lunar_transits", lambda *a, **k: [{"id": "m1"}])

    report = svc.get_report(days=999)
    assert report["window_days"] == mod.MAX_FORECAST_DAYS
    assert report["next_visible_passage"]["id"] == "v1"
    assert report["next_solar_transit"]["id"] == "s1"
    assert report["next_lunar_transit"]["id"] == "m1"
    assert report["total_passes"] == 1


def test_load_ephemeris_failure_returns_none(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")

    class _Loader:
        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("no eph")

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    assert svc._load_ephemeris() is None


def test_fetch_tle_recent_cache_fast_path(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))
    monkeypatch.setattr(
        mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network should not be called"))
    )
    assert svc._fetch_iss_tle() == ("1 A", "2 B")


def test_fetch_tle_cooldown_without_cache_raises(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: True)
    with pytest.raises(RuntimeError, match="cooldown"):
        svc._fetch_iss_tle()


def test_fetch_tle_celestrak_non_200_sets_block_and_raises(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod, "_reset_celestrak_timeout_streak", lambda: None)
    monkeypatch.setattr(mod, "_set_celestrak_block", lambda *a, **k: None)

    class _Resp:
        status_code = 500
        text = ""

        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())

    with pytest.raises(RuntimeError):
        svc._fetch_iss_tle()


def test_fetch_tle_success_from_celestrak_resets_flags(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": False})

    called = {"reset": 0, "clear": 0}
    monkeypatch.setattr(mod, "_reset_celestrak_timeout_streak", lambda: called.update({"reset": called["reset"] + 1}))
    monkeypatch.setattr(
        mod, "_clear_celestrak_block", lambda reset_failure_cooldown=True: called.update({"clear": called["clear"] + 1})
    )
    monkeypatch.setattr(mod, "_set_cached_tle_with_source", lambda *a, **k: None)

    class _Resp:
        status_code = 200
        text = "1 25544 A\n2 25544 B\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())

    assert svc._fetch_iss_tle() == ("1 25544 A", "2 25544 B")
    assert called["reset"] == 1
    assert called["clear"] == 1


def test_fetch_tle_resets_timeout_streak_on_non_timeout_error(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_cached_tle_with_source", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_set_tle_error_timestamp", lambda: None)

    calls = {"n": 0, "reset": 0}

    def _mock_get(url, **kwargs):
        calls["n"] += 1
        if mod._is_celestrak_url(url):
            raise Exception("boom")

        class _Resp:
            status_code = 200
            text = "1 25544 A\n2 25544 B\n"

            def raise_for_status(self):
                return None

        return _Resp()

    monkeypatch.setattr(mod.requests, "get", _mock_get)
    monkeypatch.setattr(mod, "_reset_celestrak_timeout_streak", lambda: calls.update({"reset": calls["reset"] + 1}))

    assert svc._fetch_iss_tle() == ("1 25544 A", "2 25544 B")
    assert calls["reset"] >= 1


def test_build_passes_and_extract_visible_segment_paths(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    events = [_Evt(start), _Evt(start + timedelta(seconds=5)), _Evt(start + timedelta(seconds=10))]
    types = [0, 1, 2]

    monkeypatch.setattr(svc, "_satellite_altitude_deg", lambda *a, **k: 42.0)
    original_extract = svc._extract_visible_segment
    monkeypatch.setattr(svc, "_extract_visible_segment", lambda **kwargs: {"is_visible": True, "k": 1})
    out = svc._build_passes(events, types, satellite=None, observer=None, ts=None, eph=None)
    assert out == [{"is_visible": True, "k": 1}]

    # Exercise branches where event order is incomplete and no pass is produced.
    sparse_events = [_Evt(start), _Evt(start + timedelta(seconds=2)), _Evt(start + timedelta(seconds=4))]
    sparse_types = [1, 2, 2]
    assert svc._build_passes(sparse_events, sparse_types, satellite=None, observer=None, ts=None, eph=None) == []

    monkeypatch.setattr(svc, "_extract_visible_segment", original_extract)

    monkeypatch.setattr(
        svc,
        "_sample_observation",
        lambda *_a, **_k: {
            "time_utc": start,
            "altitude_deg": 5.0,
            "azimuth_deg": 10.0,
            "sun_altitude_deg": 0.0,
            "is_visible": False,
        },
    )
    assert svc._extract_visible_segment(start, start + timedelta(seconds=10), None, None, None, None) is None


def test_extract_visible_segment_invalid_window_returns_none():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert svc._extract_visible_segment(now, now, None, None, None, None) is None


def test_find_solar_transits_and_extract_segment(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=4)

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    class _Sat:
        def find_events(self, *args, **kwargs):
            return [_Evt(start), _Evt(start + timedelta(seconds=2)), _Evt(end)], [0, 1, 2]

    class _TS:
        def from_datetime(self, dt):
            return dt

    original = svc._extract_solar_transit_segment
    monkeypatch.setattr(svc, "_extract_solar_transit_segment", lambda **kwargs: {"peak_time": "b"})
    out = svc._find_solar_transits(start, end, _Sat(), object(), _TS(), object())
    assert out == [{"peak_time": "b"}]
    monkeypatch.setattr(svc, "_extract_solar_transit_segment", original)

    # Positive path: ISS sweeps through the Sun -> a transit is found and refined.
    window_end = start + timedelta(seconds=30)
    center = start + timedelta(seconds=15)
    _patch_solar_arrays(monkeypatch, svc, center)
    seg = svc._extract_solar_transit_segment(start, window_end, None, None, None, None)
    assert seg is not None
    assert seg["is_visible"] is True

    # No candidate: Sun below the horizon for the whole pass -> None.
    monkeypatch.setattr(
        svc,
        "_sun_altaz_radius_arrays",
        lambda times, *a, **k: (np.full(len(times), -5.0), np.full(len(times), 180.0), np.full(len(times), 0.3)),
    )
    assert svc._extract_solar_transit_segment(start, window_end, None, None, None, None) is None


def test_sample_time_range_and_angular_radius_helpers():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=2)

    one = svc._sample_time_range(start, start, 1.0, lambda when: {"time_utc": when})
    assert len(one) == 1

    many = svc._sample_time_range(start, end, 1.0, lambda when: {"time_utc": when})
    assert many[-1]["time_utc"] == end

    odd = svc._sample_time_range(start, start + timedelta(seconds=2.2), 1.0, lambda when: {"time_utc": when})
    assert odd[-1]["time_utc"] == start + timedelta(seconds=2.2)

    class _Apparent:
        def distance(self):
            return _Dist(mod.SOLAR_RADIUS_KM + 1000)

    assert svc._solar_angular_radius_deg(_Apparent()) > 0.0

    class _Bad:
        def distance(self):
            raise RuntimeError("x")

    assert svc._solar_angular_radius_deg(_Bad()) == mod.SOLAR_ANGULAR_RADIUS_FALLBACK_DEG

    class _TooClose:
        def distance(self):
            return _Dist(mod.SOLAR_RADIUS_KM)

    assert svc._solar_angular_radius_deg(_TooClose()) == mod.SOLAR_ANGULAR_RADIUS_FALLBACK_DEG


def test_vectorised_geometry_helpers():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # _time_grid: normal window, and a window shorter than one step collapses to endpoints.
    grid = svc._time_grid(start, start + timedelta(seconds=20), 5.0)
    assert grid[0] == start and grid[-1] == start + timedelta(seconds=20)
    assert all(grid[i] <= grid[i + 1] for i in range(len(grid) - 1))
    short = svc._time_grid(start, start + timedelta(seconds=3), 10.0)
    assert short == [start, start + timedelta(seconds=3)]
    collapsed = svc._time_grid(start, start, 5.0)
    assert collapsed == [start]
    inverted = svc._time_grid(start, start - timedelta(seconds=5), 5.0)
    assert inverted == [start]

    # _angular_separation_array: identical directions -> 0, opposite azimuths at 0° alt -> 180.
    sep = svc._angular_separation_array(
        np.array([10.0, 0.0]), np.array([180.0, 0.0]), np.array([10.0, 0.0]), np.array([180.0, 180.0])
    )
    assert sep[0] == pytest.approx(0.0, abs=1e-6)
    assert sep[1] == pytest.approx(180.0, abs=1e-6)

    # _iter_geometric_passes: rise(0)/culminate(1)/set(2) -> one (start, end) pass.
    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    passes = list(
        svc._iter_geometric_passes(
            [_Evt(start), _Evt(start + timedelta(seconds=2)), _Evt(start + timedelta(seconds=4))], [0, 1, 2]
        )
    )
    assert passes == [(start, start + timedelta(seconds=4))]


def test_find_lunar_transits_and_extract_segment(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=4)

    assert svc._find_lunar_transits(start, end, None, None, None, None) == []

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    class _Sat:
        def find_events(self, *args, **kwargs):
            return [_Evt(start), _Evt(start + timedelta(seconds=2)), _Evt(end)], [0, 1, 2]

    class _TS:
        def from_datetime(self, dt):
            return dt

    original = svc._extract_lunar_transit_segment
    monkeypatch.setattr(svc, "_extract_lunar_transit_segment", lambda **kwargs: {"peak_time": "a"})
    out = svc._find_lunar_transits(start, end, _Sat(), object(), _TS(), object())
    assert out == [{"peak_time": "a"}]
    monkeypatch.setattr(svc, "_extract_lunar_transit_segment", original)

    # Positive path: ISS sweeps through the Moon -> a transit is found and refined.
    window_end = start + timedelta(seconds=30)
    center = start + timedelta(seconds=15)
    _patch_moon_arrays(monkeypatch, svc, center)
    seg = svc._extract_lunar_transit_segment(start, window_end, None, None, None, object())
    assert seg is not None
    assert seg["pass_type"] == "lunar_transit"

    # No candidate: Moon below its minimum altitude for the whole pass -> None.
    monkeypatch.setattr(
        svc,
        "_moon_altaz_radius_illum_arrays",
        lambda times, *a, **k: (
            np.full(len(times), -1.0),
            np.full(len(times), 180.0),
            np.full(len(times), 0.3),
            np.full(len(times), 0.0),
        ),
    )
    assert svc._extract_lunar_transit_segment(start, window_end, None, None, None, object()) is None


def test_extract_lunar_transit_segment_invalid_window_returns_none():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert svc._extract_lunar_transit_segment(now, now, None, None, None, object()) is None


def test_lunar_angular_radius_helper():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")

    class _Far:
        def distance(self):
            return _Dist(mod.LUNAR_RADIUS_KM + 100000)

    assert svc._lunar_angular_radius_deg(_Far()) > 0.0

    class _Bad:
        def distance(self):
            raise RuntimeError("x")

    assert svc._lunar_angular_radius_deg(_Bad()) == mod.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG

    class _TooClose:
        def distance(self):
            return _Dist(mod.LUNAR_RADIUS_KM)

    assert svc._lunar_angular_radius_deg(_TooClose()) == mod.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG


def test_sample_observation_and_sun_alt_helpers(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _Topo:
        def altaz(self):
            return _Deg(20.0), _Deg(90.0), None

        def is_sunlit(self, _eph):
            return True

    class _Sat:
        def __sub__(self, _observer):
            return self

        def at(self, _event_time):
            return _Topo()

    class _TS:
        def from_datetime(self, dt):
            return dt

    monkeypatch.setattr(svc, "_sun_altitude_deg", lambda _when: -5.0)
    o1 = svc._sample_observation(now, _Sat(), object(), _TS(), None)
    assert o1["is_visible"] is True

    monkeypatch.setattr(svc, "_sun_altitude_deg_skyfield", lambda _obs, _eph, _t: 10.0)
    o2 = svc._sample_observation(now, _Sat(), object(), _TS(), {"earth": object(), "sun": object()})
    assert o2["is_visible"] is False

    monkeypatch.setattr(
        svc,
        "_sun_altitude_deg_skyfield",
        mod.ISSPassService._sun_altitude_deg_skyfield.__get__(svc, mod.ISSPassService),
    )

    class _A:
        def apparent(self):
            return self

        def altaz(self):
            return _Deg(12.0), _Deg(0.0), None

    class _E:
        def __add__(self, _o):
            return self

        def at(self, _t):
            return self

        def observe(self, _s):
            return _A()

    assert svc._sun_altitude_deg_skyfield(object(), {"earth": _E(), "sun": object()}, now) == 12.0


def test_sun_altitude_functions_and_satellite_altitude(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _SunAltAz:
        def __init__(self, alt, az):
            self.alt = alt
            self.az = az

    class _Val:
        def __init__(self, value):
            self._value = value

        def to_value(self, _u):
            return self._value

    class _Sun:
        def __init__(self, alt, az):
            self._alt = alt
            self._az = az

        def transform_to(self, _frame):
            return _SunAltAz(self._alt, self._az)

    monkeypatch.setattr(mod, "get_sun", lambda _t: _Sun(_Val(7.5), _Val(150.0)))
    assert svc._sun_altitude_deg(now) == 7.5
    alt, az = svc._sun_alt_az_deg(now)
    assert (alt, az) == (7.5, 150.0)

    monkeypatch.setattr(mod, "get_sun", lambda _t: _Sun(None, _Val(150.0)))
    with pytest.raises(ValueError):
        svc._sun_altitude_deg(now)
    with pytest.raises(ValueError):
        svc._sun_alt_az_deg(now)

    class _Topo:
        def altaz(self):
            return _Deg(33.0), _Deg(0.0), None

    class _Sat:
        def __sub__(self, _observer):
            return self

        def at(self, _event_time):
            return _Topo()

    assert svc._satellite_altitude_deg(_Sat(), object(), now) == 33.0


@pytest.mark.parametrize("sun_alt", [-25.0, -15.0, -8.0, -1.0, 3.0])
def test_visibility_score_covers_all_light_branches(sun_alt):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    score = svc._compute_visibility_score(80.0, 8.0, sun_alt)
    assert 0.0 <= score <= 100.0


def test_get_current_position_paths(monkeypatch):
    mod._TRACK_CACHE.clear()

    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 1000)

    class _TS:
        def from_datetime(self, dt):
            return dt

    class _Loader:
        def timescale(self):
            return _TS()

        def __call__(self, *_args, **_kwargs):
            return {"earth": _Earth(), "sun": object()}

    class _Topo:
        def altaz(self):
            return _Deg(20.0), _Deg(180.0), None

        def is_sunlit(self, _eph):
            return True

    class _Sat:
        def __init__(self, *_args, **_kwargs):
            pass

        def at(self, t):
            return t

        def __sub__(self, _observer):
            return self

    class _SubPoint:
        def __init__(self, lat, lon, km):
            self.latitude = _Deg(lat)
            self.longitude = _Deg(lon)
            self.elevation = _Dist(km)

    class _WGS84:
        @staticmethod
        def latlon(*_a, **_k):
            return object()

        @staticmethod
        def subpoint(_x):
            return _SubPoint(10.0, 20.0, 430.0)

    class _SunObs:
        def apparent(self):
            return self

        def altaz(self):
            return _Deg(-10.0), _Deg(100.0), None

    class _Earth:
        def __add__(self, _observer):
            return self

        def at(self, _now):
            return self

        def observe(self, _sun):
            return _SunObs()

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    monkeypatch.setattr(mod, "EarthSatellite", _Sat)
    monkeypatch.setattr(mod, "wgs84", _WGS84)

    out = mod.get_current_position()
    assert out["latitude"] == 10.0
    assert len(out["past_track"]) == 50
    assert len(out["future_track"]) == 51

    mod._TRACK_CACHE["computed_at"] = 1000
    mod._TRACK_CACHE["past_track"] = [[1.0, 2.0]]
    mod._TRACK_CACHE["future_track"] = [[3.0, 4.0]]
    out_cached = mod.get_current_position()
    assert out_cached["past_track"] == [[1.0, 2.0]]

    class _TopObsSat(_Sat):
        def at(self, _t):
            return _Topo()

    monkeypatch.setattr(mod, "EarthSatellite", _TopObsSat)
    with_obs = mod.get_current_position(latitude=45.0, longitude=-73.0, elevation_m=20.0)
    assert with_obs["observer"]["is_visible"] is True


def test_get_current_position_fallback_and_no_tle(monkeypatch):
    with pytest.raises(RuntimeError):
        monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
        mod.get_current_position()

    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))

    class _TS:
        def from_datetime(self, dt):
            return dt

    class _Loader:
        def timescale(self):
            return _TS()

        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("no eph")

    class _Sat:
        def __init__(self, *_args, **_kwargs):
            pass

        def at(self, t):
            return self

        def __sub__(self, _observer):
            return self

        def altaz(self):
            return _Deg(12.0), _Deg(100.0), None

    class _SubPoint:
        def __init__(self):
            self.latitude = _Deg(1.0)
            self.longitude = _Deg(2.0)
            self.elevation = _Dist(430.0)

    class _WGS84:
        @staticmethod
        def latlon(*_a, **_k):
            return object()

        @staticmethod
        def subpoint(_x):
            return _SubPoint()

    class _SunAltAz:
        alt = type("A", (), {"deg": 10.0})()

    class _Sun:
        def transform_to(self, _frame):
            return _SunAltAz()

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    monkeypatch.setattr(mod, "EarthSatellite", _Sat)
    monkeypatch.setattr(mod, "wgs84", _WGS84)
    monkeypatch.setattr(mod, "get_sun", lambda _t: _Sun())

    out = mod.get_current_position(latitude=45.0, longitude=-73.0, elevation_m=20.0)
    assert out["observer"]["is_visible"] is False


def test_fetch_tle_cooldown_with_stale_cache(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: True)

    def _cached(max_age_seconds=None):
        if max_age_seconds is None:
            return ("1 A", "2 B", 10)
        return None

    monkeypatch.setattr(mod, "_get_cached_tle", _cached)
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100)
    assert svc._fetch_iss_tle() == ("1 A", "2 B")


def test_fetch_tle_celestrak_403_message_uses_cached_fallback(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(
        mod, "_get_cached_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1) if max_age_seconds is None else None
    )
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod, "_set_celestrak_block", lambda *a, **k: None)

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Forbidden")))
    assert svc._fetch_iss_tle() == ("1 A", "2 B")


def test_parse_tle_prefers_named_iss_pair():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    payload = "OTHER\n" "1 00000 X\n" "2 00000 Y\n" "ISS (ZARYA)\n" "1 25544 A\n" "2 25544 B\n"
    line1, line2 = svc._parse_iss_tle_from_response(payload)
    assert line1 == "1 25544 A"
    assert line2 == "2 25544 B"


def test_parse_tle_uses_first_pair_without_iss_label():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    payload = "1 11111 A\n2 11111 B\n1 25544 A\n2 25544 B\n"
    line1, line2 = svc._parse_iss_tle_from_response(payload)
    assert line1 == "1 11111 A"
    assert line2 == "2 11111 B"


def test_parse_tle_valid_json_without_tle_fields_raises():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    with pytest.raises(ValueError):
        svc._parse_iss_tle_from_response('{"ok": true}')


def test_build_passes_event_edge_branches(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    monkeypatch.setattr(svc, "_satellite_altitude_deg", lambda *a, **k: 30.0)
    monkeypatch.setattr(svc, "_extract_visible_segment", lambda **kwargs: None)

    # event_type=2 with empty current
    assert svc._build_passes([_Evt(now)], [2], None, None, None, None) == []
    # event_type=2 with start but no peak
    assert svc._build_passes([_Evt(now), _Evt(now + timedelta(seconds=5))], [0, 2], None, None, None, None) == []

    # event_type=2 with full segment but no pass_entry
    assert (
        svc._build_passes(
            [_Evt(now), _Evt(now + timedelta(seconds=2)), _Evt(now + timedelta(seconds=4))],
            [0, 1, 2],
            None,
            None,
            None,
            None,
        )
        == []
    )

    # unknown event type should be ignored and loop should continue.
    assert svc._build_passes([_Evt(now), _Evt(now + timedelta(seconds=1))], [9, 9], None, None, None, None) == []


def test_extract_visible_segment_positive_path(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    samples = [
        {"time_utc": start, "altitude_deg": 5.0, "azimuth_deg": 90.0, "sun_altitude_deg": -2.0, "is_visible": False},
        {
            "time_utc": start + timedelta(seconds=5),
            "altitude_deg": 30.0,
            "azimuth_deg": 100.0,
            "sun_altitude_deg": -8.0,
            "is_visible": True,
        },
        {
            "time_utc": start + timedelta(seconds=10),
            "altitude_deg": 40.0,
            "azimuth_deg": 110.0,
            "sun_altitude_deg": -10.0,
            "is_visible": True,
        },
    ]
    idx = {"i": 0}

    def _sample(*_a, **_k):
        i = idx["i"]
        idx["i"] += 1
        return samples[min(i, len(samples) - 1)]

    monkeypatch.setattr(svc, "_sample_observation", _sample)
    out = svc._extract_visible_segment(start, start + timedelta(seconds=10), None, None, None, None)
    assert out is not None
    assert out["is_visible"] is True
    assert out["pass_type"] == "visible"


def test_find_solar_transits_event_edge_branches(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=6)

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    class _Sat:
        def find_events(self, *args, **kwargs):
            return [
                _Evt(start + timedelta(seconds=1)),
                _Evt(start + timedelta(seconds=2)),
                _Evt(start + timedelta(seconds=3)),
                _Evt(start + timedelta(seconds=4)),
                _Evt(start + timedelta(seconds=6)),
            ], [1, 2, 0, 1, 2]

    class _TS:
        def from_datetime(self, dt):
            return dt

    monkeypatch.setattr(svc, "_extract_solar_transit_segment", lambda **kwargs: None)
    assert svc._find_solar_transits(start, end, _Sat(), object(), _TS(), object()) == []

    class _SatUnknown:
        def find_events(self, *args, **kwargs):
            return [_Evt(start), _Evt(start + timedelta(seconds=1))], [9, 9]

    assert svc._find_solar_transits(start, end, _SatUnknown(), object(), _TS(), object()) == []


def test_extract_solar_invalid_window_and_no_fine_candidate(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Zero-length window -> None.
    assert svc._extract_solar_transit_segment(start, start, None, None, None, None) is None

    # Coarse approach is within the margin but never lands on the disk at fine
    # resolution (ISS stays ~4° from the Sun) -> None.
    end = start + timedelta(seconds=30)
    monkeypatch.setattr(
        svc, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 30.0), np.full(len(times), 185.0))
    )
    monkeypatch.setattr(
        svc,
        "_sun_altaz_radius_arrays",
        lambda times, *a, **k: (np.full(len(times), 30.0), np.full(len(times), 180.0), np.full(len(times), 0.27)),
    )
    assert svc._extract_solar_transit_segment(start, end, None, None, None, None) is None


def test_find_lunar_transits_event_edge_branches(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=6)

    class _Evt:
        def __init__(self, dt):
            self._dt = dt

        def utc_datetime(self):
            return self._dt.replace(tzinfo=None)

    class _Sat:
        def find_events(self, *args, **kwargs):
            return [
                _Evt(start + timedelta(seconds=1)),
                _Evt(start + timedelta(seconds=2)),
                _Evt(start + timedelta(seconds=3)),
                _Evt(start + timedelta(seconds=4)),
                _Evt(start + timedelta(seconds=6)),
            ], [1, 2, 0, 1, 2]

    class _TS:
        def from_datetime(self, dt):
            return dt

    monkeypatch.setattr(svc, "_extract_lunar_transit_segment", lambda **kwargs: None)
    assert svc._find_lunar_transits(start, end, _Sat(), object(), _TS(), object()) == []

    class _SatUnknown:
        def find_events(self, *args, **kwargs):
            return [_Evt(start), _Evt(start + timedelta(seconds=1))], [9, 9]

    assert svc._find_lunar_transits(start, end, _SatUnknown(), object(), _TS(), object()) == []


def test_extract_lunar_invalid_window_and_no_fine_candidate(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Zero-length window -> None.
    assert svc._extract_lunar_transit_segment(start, start, None, None, None, object()) is None

    # Coarse approach within the margin but never on the disk at fine resolution -> None.
    end = start + timedelta(seconds=30)
    monkeypatch.setattr(
        svc, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 40.0), np.full(len(times), 185.0))
    )
    monkeypatch.setattr(
        svc,
        "_moon_altaz_radius_illum_arrays",
        lambda times, *a, **k: (
            np.full(len(times), 40.0),
            np.full(len(times), 180.0),
            np.full(len(times), 0.27),
            np.full(len(times), 15.0),
        ),
    )
    assert svc._extract_lunar_transit_segment(start, end, None, None, None, object()) is None


def test_fetch_tle_blocked_celestrak_skips_first_url_and_raises_without_cache(monkeypatch):
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_celestrak_status", lambda: {"blocked": True})
    monkeypatch.setattr(mod, "_set_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    with pytest.raises(RuntimeError):
        svc._fetch_iss_tle()


def test_observer_visibility_false_when_not_sunlit(monkeypatch):
    mod._TRACK_CACHE.clear()
    monkeypatch.setattr(mod, "_get_cached_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))

    class _TS:
        def from_datetime(self, dt):
            return dt

    class _Loader:
        def timescale(self):
            return _TS()

        def __call__(self, *_args, **_kwargs):
            return {"earth": _Earth(), "sun": object()}

    class _Sat:
        def __init__(self, *_args, **_kwargs):
            pass

        def at(self, _t):
            return self

        def __sub__(self, _observer):
            return self

        def altaz(self):
            return _Deg(50.0), _Deg(180.0), None

        def is_sunlit(self, _eph):
            return False

    class _SubPoint:
        latitude = _Deg(0.0)
        longitude = _Deg(0.0)
        elevation = _Dist(430.0)

    class _WGS84:
        @staticmethod
        def latlon(*_a, **_k):
            return object()

        @staticmethod
        def subpoint(_x):
            return _SubPoint()

    class _SunObs:
        def apparent(self):
            return self

        def altaz(self):
            return _Deg(-20.0), _Deg(0.0), None

    class _Earth:
        def __add__(self, _observer):
            return self

        def at(self, _now):
            return self

        def observe(self, _sun):
            return _SunObs()

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    monkeypatch.setattr(mod, "EarthSatellite", _Sat)
    monkeypatch.setattr(mod, "wgs84", _WGS84)

    out = mod.get_current_position(latitude=10.0, longitude=20.0, elevation_m=0.0)
    assert out["observer"]["is_visible"] is False


# ---------------------------------------------------------------------------
# _get_ephemeris — inner double-checked-lock re-check
# ---------------------------------------------------------------------------


class _RaceLock:
    """Lock stand-in simulating another thread finishing the load while we waited."""

    def __enter__(self):
        mod._EPHEMERIS_ATTEMPTED = True
        return self

    def __exit__(self, *exc):
        return False


def test_get_ephemeris_inner_recheck_skips_when_already_attempted(monkeypatch):
    """Inner re-check inside the lock: another thread already flipped _EPHEMERIS_ATTEMPTED
    while we waited for the lock, so this call must not retry the load."""
    monkeypatch.setattr(mod, "_EPHEMERIS_LOCK", _RaceLock())
    calls = []
    monkeypatch.setattr(mod, "SKYFIELD_LOADER", lambda *a, **k: calls.append(a))
    result = mod._get_ephemeris()
    assert result is None
    assert calls == []


# ---------------------------------------------------------------------------
# _sun_altaz_radius_arrays / _sun_altaz_arrays_astropy — Astropy fallback path
# ---------------------------------------------------------------------------


def test_sun_altaz_radius_arrays_falls_back_to_astropy_without_ephemeris():
    """eph=None → uses the Astropy fallback (no Skyfield ephemeris available)."""
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    times_utc = [
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
    ]
    alt, az, radius = svc._sun_altaz_radius_arrays(times_utc, observer=None, ts=None, eph=None)
    assert len(alt) == len(times_utc)
    assert len(az) == len(times_utc)
    assert (radius == mod.SOLAR_ANGULAR_RADIUS_FALLBACK_DEG).all()


def test_sun_altaz_arrays_astropy_direct():
    svc = mod.ISSPassService(45.5, -73.5, 10, "UTC")
    times_utc = [datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)]
    alt, az = svc._sun_altaz_arrays_astropy(times_utc)
    assert len(alt) == 1
    assert len(az) == 1
    assert -90.0 <= alt[0] <= 90.0
    assert 0.0 <= az[0] < 360.0
