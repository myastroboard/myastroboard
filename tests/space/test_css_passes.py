"""Unit tests for CSS (China Space Station) pass service and CSS event aggregation."""

from datetime import datetime, timedelta, timezone
from requests import HTTPError
import numpy as np
import pytest

from space import css_passes as css_module

CSSPassService = css_module.CSSPassService
get_css_passes_report = css_module.get_css_passes_report
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = css_module.LUNAR_ANGULAR_RADIUS_FALLBACK_DEG
from utils.events_aggregator import EventsAggregator

mod = css_module  # alias used by the merged-in coverage tests below

# ─── Minimal valid CSS TLE (NORAD 48274) ────────────────────────────────────
_CSS_TLE_L1 = "1 48274U 21035A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
_CSS_TLE_L2 = "2 48274  41.4700 120.0000 0005000 200.0000 160.0000 15.34000000000000"


class TestCSSPassServiceScoring:
    """Test score and day/night classification helpers."""

    def test_day_night_classification(self):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")

        assert service._classify_day_night(-20) == "Astronomical Night"
        assert service._classify_day_night(-15) == "Nautical Twilight"
        assert service._classify_day_night(-8) == "Civil Twilight"
        assert service._classify_day_night(-1) == "Twilight"
        assert service._classify_day_night(10) == "Daylight"

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

        assert service._azimuth_to_cardinal(0) == "N"
        assert service._azimuth_to_cardinal(90) == "E"
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

    @staticmethod
    def _patch_solar(monkeypatch, service, center, css_alt=30.0, sun_alt=30.0, az_rate=0.5):
        import numpy as np

        def fake_css(times, *args, **kwargs):
            secs = np.array([(t - center).total_seconds() for t in times])
            return np.full(len(times), css_alt), 180.0 + secs * az_rate

        def fake_sun(times, *args, **kwargs):
            n = len(times)
            return np.full(n, sun_alt), np.full(n, 180.0), np.full(n, 0.27)

        monkeypatch.setattr(service, "_iss_altaz_arrays", fake_css)
        monkeypatch.setattr(service, "_sun_altaz_radius_arrays", fake_sun)

    def test_extract_solar_transit_segment_returns_refined_window(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)
        center = start_utc + timedelta(seconds=15)
        self._patch_solar(monkeypatch, service, center)

        transit = service._extract_solar_transit_segment(start_utc, end_utc, None, None, None, None)

        assert transit is not None
        assert transit["is_visible"] is True
        assert transit["pass_type"] == "solar_transit"
        assert transit["css_altitude_deg"] == 30.0
        assert transit["minimum_separation_arcmin"] < 1.0
        peak = datetime.fromisoformat(transit["peak_time"]).astimezone(timezone.utc)
        assert abs((peak - center).total_seconds()) < 1.0

    def test_extract_solar_transit_segment_returns_none_when_no_transit(self, monkeypatch):
        import numpy as np

        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

        # CSS stays ~40° from the Sun for the whole pass -> rejected at the coarse stage.
        monkeypatch.setattr(
            service, "_iss_altaz_arrays", lambda times, *a, **k: (np.full(len(times), 70.0), np.full(len(times), 180.0))
        )
        monkeypatch.setattr(
            service,
            "_sun_altaz_radius_arrays",
            lambda times, *a, **k: (np.full(len(times), 30.0), np.full(len(times), 180.0), np.full(len(times), 0.27)),
        )

        assert service._extract_solar_transit_segment(start_utc, end_utc, None, None, None, None) is None


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
            return _Response("CSS (TIANHE)\n" + _CSS_TLE_L1 + "\n" + _CSS_TLE_L2 + "\n")

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

        monkeypatch.setattr(
            "space.css_passes._get_cached_css_tle",
            lambda max_age_seconds=None: (
                _CSS_TLE_L1,
                _CSS_TLE_L2,
                0,
            ),
        )
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
        payload_ivan = _json.dumps(
            {
                "@type": "TleModel",
                "name": "CSS (TIANHE)",
                "date": "2026-04-10T00:00:00+00:00",
                "line1": _CSS_TLE_L1,
                "line2": _CSS_TLE_L2,
            }
        )
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
            return type(
                "R",
                (),
                {
                    "text": _json.dumps({"line1": _CSS_TLE_L1, "line2": _CSS_TLE_L2}),
                    "raise_for_status": lambda self: None,
                },
            )()

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
            return type(
                "R",
                (),
                {
                    "text": _json.dumps({"line1": _CSS_TLE_L1, "line2": _CSS_TLE_L2}),
                    "status_code": 200,
                    "raise_for_status": lambda self: None,
                },
            )()

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
            block_calls.append(
                {
                    "status_code": status_code,
                    "reason": reason,
                    "source_url": source_url,
                }
            )

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
        pass_1_peak = base_day + timedelta(days=1, minutes=4)
        pass_2_peak = base_day + timedelta(days=3, minutes=6)
        pass_3_peak_outside = base_day + timedelta(days=9, minutes=8)

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

    @staticmethod
    def _patch_moon(monkeypatch, service, center, css_alt=40.0, moon_alt=40.0, illum=75.0):
        import numpy as np

        def fake_css(times, *args, **kwargs):
            secs = np.array([(t - center).total_seconds() for t in times])
            return np.full(len(times), css_alt), 195.0 + secs * 0.5

        def fake_moon(times, *args, **kwargs):
            n = len(times)
            return np.full(n, moon_alt), np.full(n, 195.0), np.full(n, 0.27), np.full(n, illum)

        monkeypatch.setattr(service, "_iss_altaz_arrays", fake_css)
        monkeypatch.setattr(service, "_moon_altaz_radius_illum_arrays", fake_moon)

    def test_extract_lunar_transit_segment_returns_refined_window(self, monkeypatch):
        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)
        center = start_utc + timedelta(seconds=15)
        self._patch_moon(monkeypatch, service, center)

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

        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

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

        service = CSSPassService(45.5, -73.5, 30, "America/Montreal")
        start_utc = datetime(2026, 5, 8, 21, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(seconds=30)

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
        monkeypatch.setattr(
            css_module,
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

        monkeypatch.setattr(css_module, "EarthSatellite", lambda *args, **kwargs: _FakeSatellite())
        monkeypatch.setattr(
            css_module,
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


# ---------------------------------------------------------------------------
# Merged from former test_css_passes_coverage_push.py (single-module coverage extension)
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
    if mod._EPHEMERIS is not None and mod._EPHEMERIS is not mod._EPHEMERIS_UNSET and hasattr(mod._EPHEMERIS, "close"):
        mod._EPHEMERIS.close()
    mod._EPHEMERIS = mod._EPHEMERIS_UNSET
    yield
    if mod._EPHEMERIS is not None and mod._EPHEMERIS is not mod._EPHEMERIS_UNSET and hasattr(mod._EPHEMERIS, "close"):
        mod._EPHEMERIS.close()
    mod._EPHEMERIS = mod._EPHEMERIS_UNSET


def _patch_solar_arrays(monkeypatch, svc, center, css_alt=30.0, sun_alt=30.0, az_rate=0.5):
    """Feed the vectorised solar helpers so the CSS/Sun separation dips at ``center``."""

    def fake_css(times, *args, **kwargs):
        secs = np.array([(t - center).total_seconds() for t in times])
        return np.full(len(times), css_alt), 180.0 + secs * az_rate

    def fake_sun(times, *args, **kwargs):
        n = len(times)
        return np.full(n, sun_alt), np.full(n, 180.0), np.full(n, 0.27)

    monkeypatch.setattr(svc, "_iss_altaz_arrays", fake_css)
    monkeypatch.setattr(svc, "_sun_altaz_radius_arrays", fake_sun)


def _patch_moon_arrays(monkeypatch, svc, center, css_alt=40.0, moon_alt=40.0, illum=10.0):
    """Feed the vectorised lunar helpers so the CSS/Moon separation dips at ``center``."""

    def fake_css(times, *args, **kwargs):
        secs = np.array([(t - center).total_seconds() for t in times])
        return np.full(len(times), css_alt), 180.0 + secs * 0.5

    def fake_moon(times, *args, **kwargs):
        n = len(times)
        return np.full(n, moon_alt), np.full(n, 180.0), np.full(n, 0.27), np.full(n, illum)

    monkeypatch.setattr(svc, "_iss_altaz_arrays", fake_css)
    monkeypatch.setattr(svc, "_moon_altaz_radius_illum_arrays", fake_moon)


def test_cache_helper_roundtrip_branches(monkeypatch):
    store = {}

    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_css_tle_cache", lambda payload: (store.clear(), store.update(payload)))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 1000)

    assert mod._get_cached_css_tle() is None

    mod._set_cached_css_tle("1 48274 A", "2 48274 B")
    assert store["line1"] == "1 48274 A"
    assert store["line2"] == "2 48274 B"
    assert store["fetched_at"] == 1000
    assert store["last_error_at"] is None

    assert mod._get_cached_css_tle(max_age_seconds=10) == ("1 48274 A", "2 48274 B", 1000)

    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 2000)
    assert mod._get_cached_css_tle(max_age_seconds=10) is None


def test_cooldown_false_and_clear_resets_last_error(monkeypatch):
    store = {}
    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_css_tle_cache", lambda payload: (store.clear(), store.update(payload)))

    assert mod._in_css_tle_failure_cooldown() is False

    store["last_error_at"] = 42
    mod._clear_css_celestrak_block(reset_failure_cooldown=True)
    assert store["last_error_at"] is None


def test_read_write_cache_non_dict(monkeypatch):
    seen = {}
    monkeypatch.setattr(mod, "load_json_file", lambda *a, **k: [])
    monkeypatch.setattr(mod, "save_json_file", lambda path, payload: seen.update({"path": path, "payload": payload}))

    assert mod._read_css_tle_cache() == {}
    mod._write_css_tle_cache({"x": 1})
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
    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(store))

    info = mod.get_css_tle_source_info()
    assert info["name"] == "Celestrak"
    assert info["url"] == "https://celestrak.org"
    assert info["fetched_at"] == 123

    status = mod.get_css_celestrak_status()
    assert status["blocked"] is True
    assert status["blocked_status_code"] == 403
    assert status["blocked_reason"] == "denied"
    assert status["timeout_streak"] == 2
    assert status["last_timeout_reason"] == "timeout"


def test_cooldown_and_block_state_mutators(monkeypatch):
    store = {}
    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_css_tle_cache", lambda payload: (store.clear(), store.update(payload)))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100)

    mod._set_css_tle_error_timestamp()
    assert store["last_error_at"] == 100

    assert mod._in_css_tle_failure_cooldown() is True
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100 + mod.CSS_TLE_FAILURE_COOLDOWN_SECONDS + 1)
    assert mod._in_css_tle_failure_cooldown() is False

    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 200)
    mod._set_css_celestrak_block(403, "forbidden", "https://celestrak.org/x")
    assert store["celestrak_blocked"] is True
    assert store["celestrak_blocked_status_code"] == 403

    streak = mod._increment_css_celestrak_timeout_streak("timed out", "https://celestrak.org/y")
    assert streak == 1
    assert store["celestrak_timeout_streak"] == 1

    mod._reset_css_celestrak_timeout_streak()
    assert store["celestrak_timeout_streak"] == 0

    mod._clear_css_celestrak_block(reset_failure_cooldown=False)
    assert store["celestrak_blocked"] is False
    assert store["last_error_at"] == 100


def test_clear_css_celestrak_block_flag_calls_clear(monkeypatch):
    called = {"clear": 0}
    monkeypatch.setattr(
        mod,
        "_clear_css_celestrak_block",
        lambda reset_failure_cooldown=True: called.update({"clear": called["clear"] + 1}),
    )
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})
    result = mod.clear_css_celestrak_block_flag()
    assert called["clear"] == 1
    assert result == {"blocked": False}


def test_set_cached_css_tle_with_source(monkeypatch):
    store = {}
    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(store))
    monkeypatch.setattr(mod, "_write_css_tle_cache", lambda payload: (store.clear(), store.update(payload)))
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 500)

    mod._set_cached_css_tle_with_source("1 48274 A", "2 48274 B", "https://celestrak.org/x")
    assert store["line1"] == "1 48274 A"
    assert store["last_source_name"] == "Celestrak"
    assert store["last_error_at"] is None


def test_get_report_clamps_days_and_filters_visibility(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")

    monkeypatch.setattr(svc, "_fetch_css_tle", lambda: ("1 48274 X", "2 48274 Y"))
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")

    class _Loader:
        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("no eph")

    monkeypatch.setattr(mod, "SKYFIELD_LOADER", _Loader())
    assert svc._load_ephemeris() is None


def test_fetch_css_tle_recent_cache_fast_path(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))
    monkeypatch.setattr(
        mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network should not be called"))
    )
    assert svc._fetch_css_tle() == ("1 A", "2 B")


def test_fetch_css_tle_cooldown_without_cache_raises(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: True)
    with pytest.raises(RuntimeError, match="cooldown"):
        svc._fetch_css_tle()


def test_fetch_css_tle_celestrak_non_200_sets_block_and_raises(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod, "_reset_css_celestrak_timeout_streak", lambda: None)
    monkeypatch.setattr(mod, "_set_css_celestrak_block", lambda *a, **k: None)

    class _Resp:
        status_code = 500
        text = ""

        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())

    with pytest.raises(RuntimeError):
        svc._fetch_css_tle()


def test_fetch_css_tle_success_from_celestrak_resets_flags(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})

    called = {"reset": 0, "clear": 0}
    monkeypatch.setattr(
        mod, "_reset_css_celestrak_timeout_streak", lambda: called.update({"reset": called["reset"] + 1})
    )
    monkeypatch.setattr(
        mod,
        "_clear_css_celestrak_block",
        lambda reset_failure_cooldown=True: called.update({"clear": called["clear"] + 1}),
    )
    monkeypatch.setattr(mod, "_set_cached_css_tle_with_source", lambda *a, **k: None)

    class _Resp:
        status_code = 200
        text = "1 48274 A\n2 48274 B\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())

    assert svc._fetch_css_tle() == ("1 48274 A", "2 48274 B")
    assert called["reset"] == 1
    assert called["clear"] == 1


def test_fetch_css_tle_resets_timeout_streak_on_non_timeout_error(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_cached_css_tle_with_source", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)

    calls = {"n": 0, "reset": 0}

    def _mock_get(url, **kwargs):
        calls["n"] += 1
        if mod._is_celestrak_url(url):
            raise Exception("boom")

        class _Resp:
            status_code = 200
            text = "1 48274 A\n2 48274 B\n"

            def raise_for_status(self):
                return None

        return _Resp()

    monkeypatch.setattr(mod.requests, "get", _mock_get)
    monkeypatch.setattr(mod, "_reset_css_celestrak_timeout_streak", lambda: calls.update({"reset": calls["reset"] + 1}))

    assert svc._fetch_css_tle() == ("1 48274 A", "2 48274 B")
    assert calls["reset"] >= 1


def test_build_passes_and_extract_visible_segment_paths(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert svc._extract_visible_segment(now, now, None, None, None, None) is None


def test_find_solar_transits_and_extract_segment(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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

    # Positive path: CSS sweeps through the Sun -> a transit is found and refined.
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    grid = svc._time_grid(start, start + timedelta(seconds=20), 5.0)
    assert grid[0] == start and grid[-1] == start + timedelta(seconds=20)
    assert all(grid[i] <= grid[i + 1] for i in range(len(grid) - 1))
    short = svc._time_grid(start, start + timedelta(seconds=3), 10.0)
    assert short == [start, start + timedelta(seconds=3)]
    collapsed = svc._time_grid(start, start, 5.0)
    assert collapsed == [start]
    inverted = svc._time_grid(start, start - timedelta(seconds=5), 5.0)
    assert inverted == [start]

    sep = svc._angular_separation_array(
        np.array([10.0, 0.0]), np.array([180.0, 0.0]), np.array([10.0, 0.0]), np.array([180.0, 180.0])
    )
    assert sep[0] == pytest.approx(0.0, abs=1e-6)
    assert sep[1] == pytest.approx(180.0, abs=1e-6)

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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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

    # Positive path: CSS sweeps through the Moon -> a transit is found and refined.
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert svc._extract_lunar_transit_segment(now, now, None, None, None, object()) is None


def test_lunar_angular_radius_helper():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")

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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
        mod.CSSPassService._sun_altitude_deg_skyfield.__get__(svc, mod.CSSPassService),
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    score = svc._compute_visibility_score(80.0, 8.0, sun_alt)
    assert 0.0 <= score <= 100.0


def test_get_css_current_position_paths(monkeypatch):
    mod._CSS_TRACK_CACHE.clear()

    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))
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

    out = mod.get_css_current_position()
    assert out["latitude"] == 10.0
    assert len(out["past_track"]) == 50
    assert len(out["future_track"]) == 51
    assert out["station"] == "CSS"

    mod._CSS_TRACK_CACHE["computed_at"] = 1000
    mod._CSS_TRACK_CACHE["past_track"] = [[1.0, 2.0]]
    mod._CSS_TRACK_CACHE["future_track"] = [[3.0, 4.0]]
    out_cached = mod.get_css_current_position()
    assert out_cached["past_track"] == [[1.0, 2.0]]

    class _TopObsSat(_Sat):
        def at(self, _t):
            return _Topo()

    monkeypatch.setattr(mod, "EarthSatellite", _TopObsSat)
    with_obs = mod.get_css_current_position(latitude=45.0, longitude=-73.0, elevation_m=20.0)
    assert with_obs["observer"]["is_visible"] is True


def test_get_css_current_position_fallback_and_no_tle(monkeypatch):
    with pytest.raises(RuntimeError):
        monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
        mod.get_css_current_position()

    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))

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

    out = mod.get_css_current_position(latitude=45.0, longitude=-73.0, elevation_m=20.0)
    assert out["observer"]["is_visible"] is False


def test_fetch_css_tle_cooldown_with_stale_cache(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: True)

    def _cached(max_age_seconds=None):
        if max_age_seconds is None:
            return ("1 A", "2 B", 10)
        return None

    monkeypatch.setattr(mod, "_get_cached_css_tle", _cached)
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 100)
    assert svc._fetch_css_tle() == ("1 A", "2 B")


def test_fetch_css_tle_celestrak_403_message_uses_cached_fallback(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(
        mod, "_get_cached_css_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1) if max_age_seconds is None else None
    )
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod, "_set_css_celestrak_block", lambda *a, **k: None)

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Forbidden")))
    assert svc._fetch_css_tle() == ("1 A", "2 B")


def test_parse_css_tle_prefers_named_css_pair():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    payload = "OTHER\n" "1 00000 X\n" "2 00000 Y\n" "CSS (TIANHE)\n" "1 48274 A\n" "2 48274 B\n"
    line1, line2 = svc._parse_css_tle_from_response(payload)
    assert line1 == "1 48274 A"
    assert line2 == "2 48274 B"


def test_parse_css_tle_uses_first_pair_without_css_label():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    payload = "1 11111 A\n2 11111 B\n1 48274 A\n2 48274 B\n"
    line1, line2 = svc._parse_css_tle_from_response(payload)
    assert line1 == "1 11111 A"
    assert line2 == "2 11111 B"


def test_parse_css_tle_valid_json_without_tle_fields_raises():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    with pytest.raises(ValueError):
        svc._parse_css_tle_from_response('{"ok": true}')


def test_build_passes_event_edge_branches(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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

    # unknown event type should be ignored and loop should continue
    assert svc._build_passes([_Evt(now), _Evt(now + timedelta(seconds=1))], [9, 9], None, None, None, None) == []


def test_extract_visible_segment_positive_path(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Zero-length window -> None.
    assert svc._extract_solar_transit_segment(start, start, None, None, None, None) is None

    # Coarse approach within the margin but never on the disk at fine resolution -> None.
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
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


def test_fetch_css_tle_blocked_celestrak_skips_first_url_and_raises_without_cache(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": True})
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    with pytest.raises(RuntimeError):
        svc._fetch_css_tle()


def test_observer_visibility_false_when_not_sunlit(monkeypatch):
    mod._CSS_TRACK_CACHE.clear()
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda max_age_seconds=None: ("1 A", "2 B", 1))

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

    out = mod.get_css_current_position(latitude=10.0, longitude=20.0, elevation_m=0.0)
    assert out["observer"]["is_visible"] is False


def test_group_consecutive_indices_empty_and_single():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    assert svc._group_consecutive_indices([]) == []
    assert svc._group_consecutive_indices([3]) == [[3]]
    assert svc._group_consecutive_indices([1, 2, 4, 5]) == [[1, 2], [4, 5]]


def test_is_celestrak_timeout_error():
    import requests as _req

    assert mod._is_celestrak_timeout_error(_req.exceptions.Timeout("timed out")) is True
    assert mod._is_celestrak_timeout_error(Exception("connect timeout")) is True
    assert mod._is_celestrak_timeout_error(Exception("timed out")) is True
    assert mod._is_celestrak_timeout_error(Exception("something else")) is False


def test_source_name_from_url():
    assert mod._source_name_from_url("https://celestrak.org/x") == "Celestrak"
    assert mod._source_name_from_url("https://sub.celestrak.org/x") == "Celestrak"
    assert mod._source_name_from_url("https://tle.ivanstanojevic.me/api/tle/48274") == "TLE API (ivanstanojevic.me)"
    assert mod._source_name_from_url("https://example.com/tle") == "Unknown"
    assert mod._source_name_from_url("") == "Unknown"


def test_is_celestrak_url():
    assert mod._is_celestrak_url("https://celestrak.org/something") is True
    assert mod._is_celestrak_url("https://sub.celestrak.org/path") is True
    assert mod._is_celestrak_url("https://tle.ivanstanojevic.me/api/tle/48274") is False
    assert mod._is_celestrak_url("") is False


# ---------------------------------------------------------------------------
# _classify_day_night — cover all return branches
# ---------------------------------------------------------------------------


def test_classify_day_night_all_branches():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    assert svc._classify_day_night(-20.0) == "Astronomical Night"
    assert svc._classify_day_night(-15.0) == "Nautical Twilight"
    assert svc._classify_day_night(-8.0) == "Civil Twilight"
    assert svc._classify_day_night(-1.0) == "Twilight"
    assert svc._classify_day_night(5.0) == "Daylight"


# ---------------------------------------------------------------------------
# _parse_css_tle_from_response — JSON success path
# ---------------------------------------------------------------------------


def test_parse_css_tle_from_json_response():
    import json as _json

    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    line1_str = "1 48274U 21035A   26100.00000000  .00010000  00000+0  18000-3 0  9991"
    line2_str = "2 48274  41.4700 120.0000 0005000 200.0000 160.0000 15.60000000000000"
    payload = _json.dumps({"line1": line1_str, "line2": line2_str})
    l1, l2 = svc._parse_css_tle_from_response(payload)
    assert l1 == line1_str
    assert l2 == line2_str


# ---------------------------------------------------------------------------
# _fetch_css_tle — timeout streak reaches block threshold
# ---------------------------------------------------------------------------


def test_fetch_css_tle_marks_celestrak_blocked_after_timeout_threshold(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    monkeypatch.setattr(mod, "_get_cached_css_tle", lambda **_: None)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)

    cache_payload = {}

    monkeypatch.setattr(mod, "_read_css_tle_cache", lambda: dict(cache_payload))
    monkeypatch.setattr(mod, "_write_css_tle_cache", lambda p: (cache_payload.clear(), cache_payload.update(p)))

    block_calls = []
    monkeypatch.setattr(
        mod, "_set_css_celestrak_block", lambda status_code, reason, source_url: block_calls.append(reason)
    )
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)

    class _Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

    def _mock_get(url, **_):
        if mod._is_celestrak_url(url):
            raise Exception("Connection to celestrak.org timed out. (connect timeout=10)")
        return _Response()

    monkeypatch.setattr(mod.requests, "get", _mock_get)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            svc._fetch_css_tle()

    assert int(cache_payload.get("celestrak_timeout_streak") or 0) == 3
    assert len(block_calls) == 1
    assert "Consecutive Celestrak timeout threshold reached" in block_calls[0]


# ---------------------------------------------------------------------------
# _fetch_css_tle — stale cache fallback when all sources fail
# ---------------------------------------------------------------------------


def test_fetch_css_tle_all_sources_fail_returns_stale_cache(monkeypatch):
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")

    def _get_cached(max_age_seconds=None):
        if max_age_seconds is None:
            return ("1 48274 STALE", "2 48274 STALE", 1000)
        return None

    monkeypatch.setattr(mod, "_get_cached_css_tle", _get_cached)
    monkeypatch.setattr(mod, "_in_css_tle_failure_cooldown", lambda: False)
    monkeypatch.setattr(mod, "get_css_celestrak_status", lambda: {"blocked": False})
    monkeypatch.setattr(mod, "_set_css_tle_error_timestamp", lambda: None)
    monkeypatch.setattr(mod, "_reset_css_celestrak_timeout_streak", lambda: None)
    monkeypatch.setattr(mod, "_set_css_celestrak_block", lambda **_: None)
    monkeypatch.setattr(mod, "_utc_timestamp", lambda: 2000)

    monkeypatch.setattr(mod.requests, "get", lambda *_: (_ for _ in ()).throw(RuntimeError("all down")))

    l1, l2 = svc._fetch_css_tle()
    assert l1 == "1 48274 STALE"
    assert l2 == "2 48274 STALE"


# ---------------------------------------------------------------------------
# get_css_passes_report — top-level wrapper
# ---------------------------------------------------------------------------


def test_get_css_passes_report_handles_exception(monkeypatch):
    monkeypatch.setattr(mod.CSSPassService, "get_report", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = mod.get_css_passes_report(45.5, -73.5, 10, "UTC")
    assert result is None


# ---------------------------------------------------------------------------
# _sun_altaz_radius_arrays / _sun_altaz_arrays_astropy — Astropy fallback path
# ---------------------------------------------------------------------------


def test_sun_altaz_radius_arrays_falls_back_to_astropy_without_ephemeris():
    """eph=None → uses the Astropy fallback (no Skyfield ephemeris available)."""
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    times_utc = [
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
    ]
    alt, az, radius = svc._sun_altaz_radius_arrays(times_utc, observer=None, ts=None, eph=None)
    assert len(alt) == len(times_utc)
    assert len(az) == len(times_utc)
    assert (radius == mod.SOLAR_ANGULAR_RADIUS_FALLBACK_DEG).all()


def test_sun_altaz_arrays_astropy_direct():
    svc = mod.CSSPassService(45.5, -73.5, 10, "UTC")
    times_utc = [datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)]
    alt, az = svc._sun_altaz_arrays_astropy(times_utc)
    assert len(alt) == 1
    assert len(az) == 1
    assert -90.0 <= alt[0] <= 90.0
    assert 0.0 <= az[0] < 360.0


class TestAngularSeparationDegScalar:
    """Tests for CSSPassService._angular_separation_deg (scalar, non-vectorised variant)."""

    def setup_method(self):
        self.svc = mod.CSSPassService(45.5, -73.5, 50.0, "UTC")

    def test_zero_separation_for_same_point(self):
        result = self.svc._angular_separation_deg(45.0, 90.0, 45.0, 90.0)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_positive_separation(self):
        result = self.svc._angular_separation_deg(30.0, 90.0, 45.0, 180.0)
        assert result > 0.0

    def test_result_in_degrees_range(self):
        result = self.svc._angular_separation_deg(0.0, 0.0, 90.0, 180.0)
        assert 0.0 <= result <= 180.0


# ---------------------------------------------------------------------------
# _get_ephemeris — memoisation short-circuits
# ---------------------------------------------------------------------------


class _RaceLock:
    """Lock stand-in simulating another thread finishing the load while we waited."""

    def __enter__(self):
        mod._EPHEMERIS = None
        return self

    def __exit__(self, *exc):
        return False


def test_get_ephemeris_returns_cached_without_reattempting(monkeypatch):
    """Outer check short-circuits: already-loaded ephemeris is returned without
    touching the lock or SKYFIELD_LOADER again."""
    mod._EPHEMERIS = "cached-ephemeris-object"
    calls = []
    monkeypatch.setattr(mod, "SKYFIELD_LOADER", lambda *a, **k: calls.append(a))
    result = mod._get_ephemeris()
    assert result == "cached-ephemeris-object"
    assert calls == []


def test_get_ephemeris_inner_recheck_skips_when_already_attempted(monkeypatch):
    """Inner re-check inside the lock: another thread already finished the load attempt
    (leaving the memo no longer unset) while we waited for the lock, so this call must
    not retry the load."""
    monkeypatch.setattr(mod, "_EPHEMERIS_LOCK", _RaceLock())
    calls = []
    monkeypatch.setattr(mod, "SKYFIELD_LOADER", lambda *a, **k: calls.append(a))
    result = mod._get_ephemeris()
    assert result is None
    assert calls == []
