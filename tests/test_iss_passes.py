"""Unit tests for ISS pass service and ISS event aggregation."""

from datetime import datetime, timedelta, timezone
from requests import HTTPError
import pytest

import iss_passes as iss_module

ISSPassService = iss_module.ISSPassService
get_iss_passes_report = iss_module.get_iss_passes_report
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = iss_module.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG
from events_aggregator import EventsAggregator


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
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        coarse_samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 25.0,
                "iss_azimuth_deg": 180.0,
                "sun_altitude_deg": 30.0,
                "sun_azimuth_deg": 180.0,
                "solar_radius_deg": 0.27,
                "separation_deg": separation,
            }
            for offset, separation in [
                (0, 0.40),
                (1, 0.26),
                (2, 0.05),
                (3, 0.24),
                (4, 0.38),
            ]
        ]
        refined_samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 25.0,
                "iss_azimuth_deg": 180.0,
                "sun_altitude_deg": 30.0,
                "sun_azimuth_deg": 180.0,
                "solar_radius_deg": 0.27,
                "separation_deg": separation,
            }
            for offset, separation in [
                (1.8, 0.28),
                (1.9, 0.20),
                (2.0, 0.03),
                (2.1, 0.21),
                (2.2, 0.29),
            ]
        ]

        def _mock_sample_time_range(start_utc, end_utc, step_seconds, sampler):
            if step_seconds == 1.0:
                return coarse_samples
            return refined_samples

        monkeypatch.setattr(service, "_sample_time_range", _mock_sample_time_range)

        transit = service._extract_solar_transit_segment(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert transit is not None
        assert transit["peak_time"] == (start_utc + timedelta(seconds=2)).astimezone(service.timezone).isoformat()
        assert transit["duration_seconds"] == 0.2
        assert transit["minimum_separation_arcmin"] == 1.8
        assert transit["is_visible"] is True


class TestISSPassServiceTleFallback:
    """Test ISS TLE multi-source fallback behavior."""

    @pytest.fixture(autouse=True)
    def _isolate_celestrak_block_state(self, monkeypatch):
        monkeypatch.setattr("iss_passes.get_celestrak_status", lambda: {"blocked": False})
        monkeypatch.setattr("iss_passes._set_celestrak_block", lambda *args, **kwargs: None)
        monkeypatch.setattr("iss_passes._clear_celestrak_block", lambda *args, **kwargs: None)

    def test_fetch_iss_tle_stops_immediately_after_celestrak_http_403(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        calls = {"count": 0}

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("iss_passes._set_tle_error_timestamp", lambda: None)

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

        monkeypatch.setattr("iss_passes.requests.get", _mock_get)

        with pytest.raises(RuntimeError):
            service._fetch_iss_tle()

        # Policy compliance: non-200 on Celestrak must stop immediately.
        assert calls["count"] == 1

    def test_fetch_iss_tle_raises_when_all_sources_fail(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("iss_passes._set_tle_error_timestamp", lambda: None)

        class _Response:
            def raise_for_status(self):
                raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("iss_passes.requests.get", lambda *args, **kwargs: _Response())

        try:
            service._fetch_iss_tle()
            assert False, "Expected RuntimeError when all TLE sources fail"
        except RuntimeError as exc:
            assert "Failed to fetch ISS TLE from all sources" in str(exc)

    def test_fetch_iss_tle_uses_cache_in_cooldown(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: (
            "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
            "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
            0,
        ))
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: True)

        called = {"count": 0}

        def _should_not_call(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("Network should not be called in cooldown with cache")

        monkeypatch.setattr("iss_passes.requests.get", _should_not_call)

        line1, line2 = service._fetch_iss_tle()
        assert line1.startswith("1 25544")
        assert line2.startswith("2 25544")
        assert called["count"] == 0

    def test_fetch_iss_tle_uses_stale_cache_after_source_failures(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("iss_passes._set_tle_error_timestamp", lambda: None)

        def _mock_get(*args, **kwargs):
            raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("iss_passes.requests.get", _mock_get)

        def _cached(max_age_seconds=None):
            if max_age_seconds is None:
                return (
                    "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
                    "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
                    0,
                )
            return None

        monkeypatch.setattr("iss_passes._get_cached_tle", _cached)

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
        payload_ivan = _json.dumps({
            "@type": "TleModel",
            "name": "ISS (ZARYA)",
            "date": "2026-04-10T00:00:00+00:00",
            "line1": line1_str,
            "line2": line2_str,
        })
        l1, l2 = service._parse_iss_tle_from_response(payload_ivan)
        assert l1 == line1_str
        assert l2 == line2_str

        # wheretheiss.at-style payload
        payload_wheretheiss = _json.dumps({
            "name": "ISS (ZARYA)",
            "satelliteId": 25544,
            "line1": line1_str,
            "line2": line2_str,
            "requestedAt": "2026-04-10T00:00:00.000Z",
            "source": "celestrak",
        })
        l1, l2 = service._parse_iss_tle_from_response(payload_wheretheiss)
        assert l1 == line1_str
        assert l2 == line2_str

    def test_fetch_iss_tle_uses_alternative_source_when_celestrak_blocked(self, monkeypatch):
        """Alternative JSON sources are tried after Celestrak timeout/block."""
        import json as _json
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        line1_str = "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
        line2_str = "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000"

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("iss_passes._set_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("iss_passes._set_cached_tle", lambda l1, l2: None)

        calls = []

        class _TimeoutError(Exception):
            pass

        def _mock_get(url, **kwargs):
            calls.append(url)
            if "celestrak" in url:
                raise _TimeoutError("Connection timed out")
            # First non-Celestrak URL returns JSON TLE
            return type("R", (), {
                "text": _json.dumps({"line1": line1_str, "line2": line2_str}),
                "raise_for_status": lambda self: None,
            })()

        monkeypatch.setattr("iss_passes.requests.get", _mock_get)

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

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("iss_passes._set_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("iss_passes._set_cached_tle", lambda l1, l2: None)
        monkeypatch.setattr("iss_passes.get_celestrak_status", lambda: {"blocked": True})

        calls = []

        def _mock_get(url, **kwargs):
            calls.append(url)
            if iss_module._is_celestrak_url(url):
                raise AssertionError("Celestrak URL should be skipped when block flag is set")
            return type("R", (), {
                "text": _json.dumps({"line1": line1_str, "line2": line2_str}),
                "status_code": 200,
                "raise_for_status": lambda self: None,
            })()

        monkeypatch.setattr("iss_passes.requests.get", _mock_get)

        l1, l2 = service._fetch_iss_tle()
        assert l1 == line1_str
        assert l2 == line2_str
        assert len(calls) == 1
        assert not iss_module._is_celestrak_url(calls[0])

    def test_fetch_iss_tle_marks_celestrak_blocked_after_3_timeouts(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("iss_passes._get_cached_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("iss_passes._in_tle_failure_cooldown", lambda: False)

        cache_payload = {}

        def _mock_read_cache():
            return dict(cache_payload)

        def _mock_write_cache(payload):
            cache_payload.clear()
            cache_payload.update(payload)

        monkeypatch.setattr("iss_passes._read_tle_cache", _mock_read_cache)
        monkeypatch.setattr("iss_passes._write_tle_cache", _mock_write_cache)

        block_calls = []

        def _mock_set_celestrak_block(status_code, reason, source_url):
            block_calls.append({
                "status_code": status_code,
                "reason": reason,
                "source_url": source_url,
            })

        monkeypatch.setattr("iss_passes._set_celestrak_block", _mock_set_celestrak_block)

        class _Response:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

        def _mock_get(url, **kwargs):
            if iss_module._is_celestrak_url(url):
                raise Exception("Connection to celestrak.org timed out. (connect timeout=10)")
            return _Response()

        monkeypatch.setattr("iss_passes.requests.get", _mock_get)

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
        pass_1_peak = (base_day + timedelta(days=1, minutes=4))
        pass_2_peak = (base_day + timedelta(days=3, minutes=6))
        pass_3_peak_outside = (base_day + timedelta(days=9, minutes=8))

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

    def test_extract_lunar_transit_segment_returns_refined_window(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        coarse_samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 40.0,
                "iss_azimuth_deg": 195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 75.0,
                "separation_deg": separation,
            }
            for offset, separation in [
                (0, 0.40),
                (1, 0.26),
                (2, 0.05),
                (3, 0.24),
                (4, 0.38),
            ]
        ]
        refined_samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 40.0,
                "iss_azimuth_deg": 195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 75.0,
                "separation_deg": separation,
            }
            for offset, separation in [
                (1.8, 0.28),
                (1.9, 0.20),
                (2.0, 0.03),
                (2.1, 0.21),
                (2.2, 0.29),
            ]
        ]

        def _mock_sample_time_range(start_utc, end_utc, step_seconds, sampler):
            if step_seconds == 1.0:
                return coarse_samples
            return refined_samples

        monkeypatch.setattr(service, "_sample_time_range", _mock_sample_time_range)

        transit = service._extract_lunar_transit_segment(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert transit is not None
        assert transit["pass_type"] == "lunar_transit"
        assert transit["peak_time"] == (start_utc + timedelta(seconds=2)).astimezone(service.timezone).isoformat()
        assert transit["duration_seconds"] == 0.2
        assert transit["minimum_separation_arcmin"] == pytest.approx(0.03 * 60, abs=0.01)
        assert transit["moon_illumination_pct"] == 75.0
        assert transit["is_visible"] is True

    def test_extract_lunar_transit_segment_returns_none_when_no_candidates(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        # All separations exceed the lunar radius → no transit
        samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 40.0,
                "iss_azimuth_deg": 195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 50.0,
                "separation_deg": 1.5,
            }
            for offset in range(5)
        ]

        monkeypatch.setattr(service, "_sample_time_range", lambda *args, **kwargs: samples)

        transit = service._extract_lunar_transit_segment(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert transit is None

    def test_extract_lunar_transit_segment_returns_none_when_moon_too_low(self, monkeypatch):
        service = ISSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        # Moon altitude below LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG (5°) → excluded
        samples = [
            {
                "time_utc": start_utc + timedelta(seconds=offset),
                "iss_altitude_deg": 40.0,
                "iss_azimuth_deg": 195.0,
                "moon_altitude_deg": 2.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 50.0,
                "separation_deg": 0.05,
            }
            for offset in range(5)
        ]

        monkeypatch.setattr(service, "_sample_time_range", lambda *args, **kwargs: samples)

        transit = service._extract_lunar_transit_segment(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert transit is None

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

        monkeypatch.setattr(service, "_fetch_iss_tle", lambda: (
            "1 25544U 98067A   26100.00000000  .00010000  00000+0  18000-3 0  9991",
            "2 25544  51.6400 120.0000 0005000 200.0000 160.0000 15.50000000000000",
        ))
        monkeypatch.setattr(service, "_load_ephemeris", lambda: None)
        monkeypatch.setattr(service, "_build_passes", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_solar_transits", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_lunar_transits", lambda *args, **kwargs: [])

        from skyfield.api import Loader
        import os
        from constants import DATA_DIR_CACHE
        SKYFIELD_CACHE_DIR = os.path.join(DATA_DIR_CACHE, "skyfield")
        os.makedirs(SKYFIELD_CACHE_DIR, exist_ok=True)

        # Patch find_events to return empty sequences
        class _FakeTS:
            def from_datetime(self, dt):
                return dt
            def timescale(self):
                return self

        fake_ts = _FakeTS()
        monkeypatch.setattr(iss_module, "SKYFIELD_LOADER", type("L", (), {
            "timescale": lambda self: fake_ts,
        })())

        class _FakeSatellite:
            def find_events(self, *args, **kwargs):
                return [], []

        monkeypatch.setattr(iss_module, "EarthSatellite", lambda *args, **kwargs: _FakeSatellite())
        monkeypatch.setattr(iss_module, "wgs84", type("W", (), {
            "latlon": lambda *args, **kwargs: None,
        })())

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
