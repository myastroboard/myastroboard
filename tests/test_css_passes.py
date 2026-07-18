"""Unit tests for CSS (China Space Station) pass service and CSS event aggregation."""

from datetime import datetime, timedelta, timezone
from requests import HTTPError
import pytest

from space import css_passes as css_module

CSSPassService = css_module.CSSPassService
get_css_passes_report = css_module.get_css_passes_report
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = css_module.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG
from utils.events_aggregator import EventsAggregator


# ─── Minimal valid CSS TLE (NORAD 48274) ────────────────────────────────────
_CSS_TLE_L1 = "1 48274U 21035A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
_CSS_TLE_L2 = "2 48274  41.4700 120.0000 0005000 200.0000 160.0000 15.34000000000000"


class TestCSSPassServiceScoring:
    """Test score and day/night classification helpers."""

    def test_day_night_classification(self):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        assert service._classify_day_night(-20) == "Astronomical Night"
        assert service._classify_day_night(-15) == "Nautical Twilight"
        assert service._classify_day_night(-8)  == "Civil Twilight"
        assert service._classify_day_night(-1)  == "Twilight"
        assert service._classify_day_night(10)  == "Daylight"

    def test_visibility_score_range(self):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

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
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        assert service._azimuth_to_cardinal(0)   == "N"
        assert service._azimuth_to_cardinal(90)  == "E"
        assert service._azimuth_to_cardinal(180) == "S"
        assert service._azimuth_to_cardinal(270) == "W"
        assert service._azimuth_to_cardinal(225) == "SW"


class TestCSSPassServiceWrapper:
    """Test top-level CSS wrapper behavior."""

    def test_get_css_passes_report_handles_exceptions(self, monkeypatch):
        def _raise_error(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(CSSPassService, "get_report", _raise_error)

        result = get_css_passes_report(
            latitude=45.5,
            longitude=-73.5,
            elevation_m=30,
            timezone_str="America/Montreal",
            days=20,
        )

        assert result is None


class TestCSSPassServiceSolarTransit:
    """Test CSS solar transit detection helpers."""

    def test_extract_solar_transit_segment_returns_refined_window(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        coarse_samples = [
            {
                "time_utc":        start_utc + timedelta(seconds=offset),
                "css_altitude_deg": 25.0,
                "css_azimuth_deg":  180.0,
                "sun_altitude_deg": 30.0,
                "sun_azimuth_deg":  180.0,
                "solar_radius_deg": 0.27,
                "separation_deg":   separation,
            }
            for offset, separation in [
                (0, 0.40), (1, 0.26), (2, 0.05), (3, 0.24), (4, 0.38),
            ]
        ]
        refined_samples = [
            {
                "time_utc":        start_utc + timedelta(seconds=offset),
                "css_altitude_deg": 25.0,
                "css_azimuth_deg":  180.0,
                "sun_altitude_deg": 30.0,
                "sun_azimuth_deg":  180.0,
                "solar_radius_deg": 0.27,
                "separation_deg":   separation,
            }
            for offset, separation in [
                (1.8, 0.28), (1.9, 0.20), (2.0, 0.03), (2.1, 0.21), (2.2, 0.29),
            ]
        ]

        def _mock_sample_time_range(start_utc, end_utc, step_seconds, sampler):
            return coarse_samples if step_seconds == 1.0 else refined_samples

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

    def test_extract_solar_transit_segment_returns_none_when_no_transit(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        # All separations exceed solar radius → no transit
        samples = [
            {
                "time_utc": start_utc + timedelta(seconds=i),
                "css_altitude_deg": 25.0,
                "css_azimuth_deg": 180.0,
                "sun_altitude_deg": 30.0,
                "sun_azimuth_deg": 180.0,
                "solar_radius_deg": 0.27,
                "separation_deg": 1.0,
            }
            for i in range(5)
        ]

        monkeypatch.setattr(service, "_sample_time_range", lambda *args, **kwargs: samples)

        transit = service._extract_solar_transit_segment(
            start_utc=start_utc,
            end_utc=end_utc,
            satellite=None,
            observer=None,
            ts=None,
            eph=None,
        )

        assert transit is None


class TestCSSPassServiceTleFallback:
    """Test CSS TLE multi-source fallback and Celestrak block management."""

    @pytest.fixture(autouse=True)
    def _isolate_celestrak_block_state(self, monkeypatch):
        monkeypatch.setattr("space.css_passes.get_css_celestrak_status", lambda: {"blocked": False})
        monkeypatch.setattr("space.css_passes._set_css_celestrak_block", lambda *args, **kwargs: None)
        monkeypatch.setattr("space.css_passes._clear_css_celestrak_block", lambda *args, **kwargs: None)

    def test_fetch_css_tle_stops_immediately_after_celestrak_http_403(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        calls = {"count": 0}

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.css_passes._set_css_tle_error_timestamp", lambda: None)

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
                "CSS (TIANHE)\n"
                + _CSS_TLE_L1 + "\n"
                + _CSS_TLE_L2 + "\n"
            )

        monkeypatch.setattr("space.css_passes.requests.get", _mock_get)

        with pytest.raises(RuntimeError):
            service._fetch_css_tle()

        # Policy compliance: non-200 on Celestrak must stop immediately.
        assert calls["count"] == 1

    def test_fetch_css_tle_raises_when_all_sources_fail(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.css_passes._set_css_tle_error_timestamp", lambda: None)

        class _Response:
            def raise_for_status(self):
                raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("space.css_passes.requests.get", lambda *args, **kwargs: _Response())

        try:
            service._fetch_css_tle()
            assert False, "Expected RuntimeError when all CSS TLE sources fail"
        except RuntimeError as exc:
            assert "CSS TLE" in str(exc)

    def test_fetch_css_tle_uses_cache_in_cooldown(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: (
            _CSS_TLE_L1, _CSS_TLE_L2, 0,
        ))
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: True)

        called = {"count": 0}

        def _should_not_call(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("Network should not be called in cooldown with cache")

        monkeypatch.setattr("space.css_passes.requests.get", _should_not_call)

        line1, line2 = service._fetch_css_tle()
        assert line1.startswith("1 48274")
        assert line2.startswith("2 48274")
        assert called["count"] == 0

    def test_fetch_css_tle_uses_stale_cache_after_source_failures(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.css_passes._set_css_tle_error_timestamp", lambda: None)

        def _mock_get(*args, **kwargs):
            raise HTTPError("503 Service Unavailable")

        monkeypatch.setattr("space.css_passes.requests.get", _mock_get)

        def _cached(max_age_seconds=None):
            if max_age_seconds is None:
                return (_CSS_TLE_L1, _CSS_TLE_L2, 0)
            return None

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", _cached)

        line1, line2 = service._fetch_css_tle()
        assert line1.startswith("1 48274")
        assert line2.startswith("2 48274")

    def test_parse_css_tle_from_json_response(self):
        """Parser handles JSON bodies returned by tle.ivanstanojevic.me."""
        import json as _json
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        # tle.ivanstanojevic.me-style payload
        payload_ivan = _json.dumps({
            "@type": "TleModel",
            "name": "CSS (TIANHE)",
            "date": "2026-04-10T00:00:00+00:00",
            "line1": _CSS_TLE_L1,
            "line2": _CSS_TLE_L2,
        })
        l1, l2 = service._parse_css_tle_from_response(payload_ivan)
        assert l1 == _CSS_TLE_L1
        assert l2 == _CSS_TLE_L2

    def test_parse_css_tle_from_3line_text_response(self):
        """Parser handles plain 3-line TLE text format from Celestrak."""
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        payload_txt = "CSS (TIANHE)\n" + _CSS_TLE_L1 + "\n" + _CSS_TLE_L2 + "\n"
        l1, l2 = service._parse_css_tle_from_response(payload_txt)
        assert l1 == _CSS_TLE_L1
        assert l2 == _CSS_TLE_L2

    def test_fetch_css_tle_uses_alternative_source_when_celestrak_times_out(self, monkeypatch):
        """Alternative JSON sources are tried after Celestrak timeout."""
        import json as _json
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.css_passes._set_css_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("space.css_passes._set_cached_css_tle_with_source", lambda l1, l2, url: None)

        calls = []

        class _TimeoutError(Exception):
            pass

        def _mock_get(url, **kwargs):
            calls.append(url)
            if css_module._is_celestrak_url(url):
                raise _TimeoutError("Connection timed out")
            return type("R", (), {
                "text": _json.dumps({"line1": _CSS_TLE_L1, "line2": _CSS_TLE_L2}),
                "raise_for_status": lambda self: None,
            })()

        monkeypatch.setattr("space.css_passes.requests.get", _mock_get)

        l1, l2 = service._fetch_css_tle()

        assert l1 == _CSS_TLE_L1
        assert l2 == _CSS_TLE_L2
        assert calls[0] == css_module.CSS_TLE_URLS[0]
        assert not css_module._is_celestrak_url(calls[-1])

    def test_fetch_css_tle_skips_celestrak_when_block_flag_is_set(self, monkeypatch):
        import json as _json
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)
        monkeypatch.setattr("space.css_passes._set_css_tle_error_timestamp", lambda: None)
        monkeypatch.setattr("space.css_passes._set_cached_css_tle_with_source", lambda l1, l2, url: None)
        monkeypatch.setattr("space.css_passes.get_css_celestrak_status", lambda: {"blocked": True})

        calls = []

        def _mock_get(url, **kwargs):
            calls.append(url)
            if css_module._is_celestrak_url(url):
                raise AssertionError("Celestrak URL should be skipped when block flag is set")
            return type("R", (), {
                "text": _json.dumps({"line1": _CSS_TLE_L1, "line2": _CSS_TLE_L2}),
                "status_code": 200,
                "raise_for_status": lambda self: None,
            })()

        monkeypatch.setattr("space.css_passes.requests.get", _mock_get)

        l1, l2 = service._fetch_css_tle()
        assert l1 == _CSS_TLE_L1
        assert l2 == _CSS_TLE_L2
        assert len(calls) == 1
        assert not css_module._is_celestrak_url(calls[0])

    def test_fetch_css_tle_marks_celestrak_blocked_after_3_timeouts(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr("space.css_passes._get_cached_css_tle", lambda max_age_seconds=None: None)
        monkeypatch.setattr("space.css_passes._in_css_tle_failure_cooldown", lambda: False)

        cache_payload = {}

        def _mock_read_cache():
            return dict(cache_payload)

        def _mock_write_cache(payload):
            cache_payload.clear()
            cache_payload.update(payload)

        monkeypatch.setattr("space.css_passes._read_css_tle_cache", _mock_read_cache)
        monkeypatch.setattr("space.css_passes._write_css_tle_cache", _mock_write_cache)

        block_calls = []

        def _mock_set_css_celestrak_block(status_code, reason, source_url):
            block_calls.append({
                "status_code": status_code,
                "reason": reason,
                "source_url": source_url,
            })

        monkeypatch.setattr("space.css_passes._set_css_celestrak_block", _mock_set_css_celestrak_block)

        class _Response:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

        def _mock_get(url, **kwargs):
            if css_module._is_celestrak_url(url):
                raise Exception("Connection to celestrak.org timed out. (connect timeout=10)")
            return _Response()

        monkeypatch.setattr("space.css_passes.requests.get", _mock_get)

        for _ in range(3):
            with pytest.raises(RuntimeError):
                service._fetch_css_tle()

        assert int(cache_payload.get("celestrak_timeout_streak") or 0) == 3
        assert len(block_calls) == 1
        assert block_calls[0]["status_code"] == 0
        assert "Consecutive Celestrak timeout threshold reached" in block_calls[0]["reason"]


class TestCSSCelestrakStatus:
    """Test Celestrak status and block/clear lifecycle."""

    def test_get_css_celestrak_status_returns_default_when_no_cache(self, monkeypatch):
        monkeypatch.setattr("space.css_passes._read_css_tle_cache", lambda: {})
        status = css_module.get_css_celestrak_status()

        assert status["blocked"] is False
        assert status["blocked_at"] == 0
        assert "policy_url" in status
        assert "manual_check_url" in status

    def test_clear_css_celestrak_block_flag(self, monkeypatch):
        cleared = {}

        def _mock_clear_block(reset_failure_cooldown=True):
            cleared["called"] = True
            cleared["reset"] = reset_failure_cooldown

        monkeypatch.setattr("space.css_passes._clear_css_celestrak_block", _mock_clear_block)
        monkeypatch.setattr("space.css_passes._read_css_tle_cache", lambda: {})

        css_module.clear_css_celestrak_block_flag()
        assert cleared.get("called") is True
        assert cleared.get("reset") is True


class TestCSSCalendarAggregation:
    """Test CSS event integration in event aggregation payload."""

    def test_aggregate_all_events_includes_css_pass(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        base_day = aggregator.local_now.replace(hour=20, minute=0, second=0, microsecond=0)
        pass_1_peak = (base_day + timedelta(days=1, minutes=4))
        pass_2_peak = (base_day + timedelta(days=3, minutes=6))
        pass_3_peak_outside = (base_day + timedelta(days=9, minutes=8))

        css_payload = {
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

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)

        assert result["events_count"] == 2
        assert result["upcoming_events"][0]["event_type"] == "CSS Pass"
        assert result["upcoming_events"][0]["title"] == "CSS Visible Passage"
        assert result["upcoming_events"][0]["structure_key"] == "css"

    def test_aggregate_all_events_includes_css_solar_transit(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language="fr")

        peak_time = (aggregator.local_now + timedelta(days=1)).replace(hour=11, minute=30, second=0, microsecond=0)
        css_payload = {
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

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)

        assert result["events_count"] == 1
        event = result["upcoming_events"][0]
        assert event["event_type"] == "CSS Solar Transit"
        assert event["structure_key"] == "css"
        assert "0.18" in event["description"]

    def test_aggregate_all_events_includes_css_lunar_transit(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language="fr")

        peak_time = (aggregator.local_now + timedelta(days=2)).replace(hour=22, minute=15, second=0, microsecond=0)
        css_payload = {
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
                    "css_altitude_deg": 42.3,
                    "css_azimuth_deg": 195.1,
                    "pass_type": "lunar_transit",
                    "is_visible": True,
                }
            ]
        }

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)

        assert result["events_count"] == 1
        event = result["upcoming_events"][0]
        assert event["event_type"] == "CSS Lunar Transit"
        assert event["structure_key"] == "css"
        assert event["importance"] == "critical"
        assert "0.22" in event["description"]
        assert "78" in event["description"]

    def test_aggregate_all_events_css_lunar_transit_all_languages(self):
        """Verify the CSS lunar transit title is present in all supported languages."""
        expected_titles = {
            "en": "CSS Lunar Transit",
            "fr": "Transit lunaire CSS",
            "de": "CSS-Mondtransit",
            "es": "Tránsito lunar CSS",
            "it": "Transito lunare CSS",
            "pt": "Trânsito lunar CSS",
        }
        for lang, expected_title in expected_titles.items():
            aggregator = EventsAggregator(45.5, -73.5, "America/Montreal", language=lang)
            peak_time = (aggregator.local_now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
            css_payload = {
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
                        "css_altitude_deg": 30.1,
                        "css_azimuth_deg": 180.1,
                        "pass_type": "lunar_transit",
                        "is_visible": True,
                    }
                ]
            }
            result = aggregator.aggregate_all_events(css_passes_data=css_payload)
            assert result["events_count"] == 1, f"Expected 1 event for lang={lang}"
            assert result["upcoming_events"][0]["title"] == expected_title, f"Title mismatch for lang={lang}"

    def test_aggregate_all_events_css_pass_outside_window_excluded(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        # 10 days out - should be excluded
        peak_time = (aggregator.local_now + timedelta(days=10)).replace(hour=22, minute=0, second=0, microsecond=0)
        css_payload = {
            "passes": [
                {
                    "start_time": (peak_time - timedelta(minutes=3)).isoformat(),
                    "peak_time": peak_time.isoformat(),
                    "end_time": (peak_time + timedelta(minutes=3)).isoformat(),
                    "peak_altitude_deg": 45.0,
                    "duration_minutes": 6.0,
                    "visibility_score": 70.0,
                    "visibility_day_night": "Astronomical Night",
                    "is_visible": True,
                }
            ]
        }

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)
        assert result["events_count"] == 0

    def test_aggregate_all_events_css_pass_skips_invalid_or_past_or_low_score(self):
        """Non-dict entries, entries missing peak_time, and past-dated passes are skipped;
        a pass scoring below 55 gets LOW importance (all edge branches in the passes loop)."""
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")
        base_day = aggregator.local_now.replace(hour=20, minute=0, second=0, microsecond=0)
        past_peak = base_day - timedelta(days=1)
        valid_peak = base_day + timedelta(days=1, minutes=4)

        css_payload = {
            "passes": [
                "not-a-dict",
                {"peak_altitude_deg": 10.0},  # missing peak_time
                {
                    "start_time": past_peak.isoformat(),
                    "peak_time": past_peak.isoformat(),
                    "end_time": past_peak.isoformat(),
                    "peak_altitude_deg": 20.0,
                    "visibility_score": 30.0,
                    "visibility_day_night": "Daylight",
                    "is_visible": False,
                },  # in the past -> skipped
                {
                    "start_time": valid_peak.isoformat(),
                    "peak_time": valid_peak.isoformat(),
                    "end_time": valid_peak.isoformat(),
                    "peak_altitude_deg": 25.0,
                    "visibility_score": 40.0,  # below 55 -> LOW importance
                    "visibility_day_night": "Astronomical Night",
                    "is_visible": True,
                },
            ]
        }

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)

        assert result["events_count"] == 1
        assert result["upcoming_events"][0]["importance"] == "low"

    def test_aggregate_all_events_css_solar_transit_skips_invalid_or_out_of_window(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")
        base_day = aggregator.local_now.replace(hour=11, minute=0, second=0, microsecond=0)
        out_of_window_peak = base_day + timedelta(days=10)

        css_payload = {
            "solar_transits": [
                "not-a-dict",
                {"duration_seconds": 1.0},  # missing peak_time
                {
                    "start_time": out_of_window_peak.isoformat(),
                    "peak_time": out_of_window_peak.isoformat(),
                    "end_time": out_of_window_peak.isoformat(),
                    "duration_seconds": 0.5,
                    "minimum_separation_arcmin": 0.1,
                    "solar_radius_arcmin": 15.9,
                    "sun_altitude_deg": 30.0,
                    "is_visible": True,
                },  # outside the 7-day window -> skipped
            ]
        }

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)
        assert result["events_count"] == 0

    def test_aggregate_all_events_css_lunar_transit_skips_invalid_or_out_of_window(self):
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")
        base_day = aggregator.local_now.replace(hour=22, minute=0, second=0, microsecond=0)
        out_of_window_peak = base_day + timedelta(days=10)

        css_payload = {
            "lunar_transits": [
                "not-a-dict",
                {"duration_seconds": 1.0},  # missing peak_time
                {
                    "start_time": out_of_window_peak.isoformat(),
                    "peak_time": out_of_window_peak.isoformat(),
                    "end_time": out_of_window_peak.isoformat(),
                    "duration_seconds": 0.5,
                    "minimum_separation_arcmin": 0.2,
                    "lunar_radius_arcmin": 14.7,
                    "moon_altitude_deg": 40.0,
                    "moon_illumination_pct": 60.0,
                    "is_visible": True,
                },  # outside the 7-day window -> skipped
            ]
        }

        result = aggregator.aggregate_all_events(css_passes_data=css_payload)
        assert result["events_count"] == 0

    def test_aggregate_all_events_css_and_iss_independent(self):
        """CSS and ISS events are aggregated independently in the same call."""
        aggregator = EventsAggregator(45.5, -73.5, "America/Montreal")

        base_day = aggregator.local_now.replace(hour=20, minute=0, second=0, microsecond=0)
        peak = base_day + timedelta(days=1, minutes=5)

        pass_entry = {
            "start_time": (peak - timedelta(minutes=4)).isoformat(),
            "peak_time": peak.isoformat(),
            "end_time": (peak + timedelta(minutes=4)).isoformat(),
            "peak_altitude_deg": 60.0,
            "duration_minutes": 8.0,
            "visibility_score": 80.0,
            "visibility_day_night": "Astronomical Night",
            "is_visible": True,
        }

        result = aggregator.aggregate_all_events(
            iss_passes_data={"passes": [pass_entry]},
            css_passes_data={"passes": [pass_entry]},
        )

        assert result["events_count"] == 2
        event_types = {e["event_type"] for e in result["upcoming_events"]}
        assert "ISS Pass" in event_types
        assert "CSS Pass" in event_types


class TestCSSPassServiceLunarTransit:
    """Test CSS lunar transit detection helpers."""

    def test_extract_lunar_transit_segment_returns_refined_window(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        coarse_samples = [
            {
                "time_utc":        start_utc + timedelta(seconds=offset),
                "css_altitude_deg": 40.0,
                "css_azimuth_deg":  195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg":  195.0,
                "lunar_radius_deg":  0.27,
                "moon_illumination_pct": 75.0,
                "separation_deg":   separation,
            }
            for offset, separation in [
                (0, 0.40), (1, 0.26), (2, 0.05), (3, 0.24), (4, 0.38),
            ]
        ]
        refined_samples = [
            {
                "time_utc":        start_utc + timedelta(seconds=offset),
                "css_altitude_deg": 40.0,
                "css_azimuth_deg":  195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg":  195.0,
                "lunar_radius_deg":  0.27,
                "moon_illumination_pct": 75.0,
                "separation_deg":   separation,
            }
            for offset, separation in [
                (1.8, 0.28), (1.9, 0.20), (2.0, 0.03), (2.1, 0.21), (2.2, 0.29),
            ]
        ]

        def _mock_sample_time_range(start_utc, end_utc, step_seconds, sampler):
            return coarse_samples if step_seconds == 1.0 else refined_samples

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
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        samples = [
            {
                "time_utc": start_utc + timedelta(seconds=i),
                "css_altitude_deg": 40.0,
                "css_azimuth_deg": 195.0,
                "moon_altitude_deg": 40.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 50.0,
                "separation_deg": 1.5,
            }
            for i in range(5)
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
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=4)

        samples = [
            {
                "time_utc": start_utc + timedelta(seconds=i),
                "css_altitude_deg": 40.0,
                "css_azimuth_deg": 195.0,
                "moon_altitude_deg": 2.0,
                "moon_azimuth_deg": 195.0,
                "lunar_radius_deg": 0.27,
                "moon_illumination_pct": 50.0,
                "separation_deg": 0.05,
            }
            for i in range(5)
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

    def test_find_lunar_transits_skipped_without_ephemeris(self):
        """_find_lunar_transits returns [] gracefully when eph is None."""
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
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
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        class _BadApparent:
            def distance(self):
                raise ValueError("no distance")

        radius = service._lunar_angular_radius_deg(_BadApparent())
        assert radius == LUNAR_ANGULAR_RADIUS_FALLBACK_DEG

    def test_get_report_includes_css_station_key_and_all_transit_fields(self, monkeypatch):
        """get_report() returns station='CSS' and all required transit/pass keys."""
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        monkeypatch.setattr(service, "_fetch_css_tle", lambda: (_CSS_TLE_L1, _CSS_TLE_L2))
        monkeypatch.setattr(service, "_load_ephemeris", lambda: None)
        monkeypatch.setattr(service, "_build_passes", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_solar_transits", lambda *args, **kwargs: [])
        monkeypatch.setattr(service, "_find_lunar_transits", lambda *args, **kwargs: [])

        import os
        from utils.constants import DATA_DIR_CACHE
        SKYFIELD_CACHE_DIR = os.path.join(DATA_DIR_CACHE, "skyfield")
        os.makedirs(SKYFIELD_CACHE_DIR, exist_ok=True)

        class _FakeTS:
            def from_datetime(self, dt):
                return dt
            def timescale(self):
                return self

        fake_ts = _FakeTS()
        monkeypatch.setattr(css_module, "SKYFIELD_LOADER", type("L", (), {
            "timescale": lambda self: fake_ts,
        })())

        class _FakeSatellite:
            def find_events(self, *args, **kwargs):
                return [], []

        monkeypatch.setattr(css_module, "EarthSatellite", lambda *args, **kwargs: _FakeSatellite())
        monkeypatch.setattr(css_module, "wgs84", type("W", (), {
            "latlon": lambda *args, **kwargs: None,
        })())

        report = service.get_report(days=1)

        assert report["station"] == "CSS"
        assert "lunar_transits" in report
        assert "next_lunar_transit" in report
        assert "total_lunar_transits" in report
        assert "solar_transits" in report
        assert "next_solar_transit" in report
        assert "total_solar_transits" in report
        assert "passes" in report
        assert "celestrak_status" in report
        assert isinstance(report["lunar_transits"], list)
        assert report["total_lunar_transits"] == 0
