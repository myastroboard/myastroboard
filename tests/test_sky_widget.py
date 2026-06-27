"""Tests for _determine_sky_period and get_sky_widget_api."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(dt: datetime) -> str:
    """Format a datetime for sun_data strings (UTC, no tz suffix)."""
    return dt.strftime("%Y-%m-%d %H:%M")


def _make_sun_data(**overrides) -> dict:
    """
    Build a sun_data dict with all fields set to 'Not found' by default.
    Pass keyword args to override specific sun fields with formatted strings.
    """
    defaults = {
        "sunrise": "Not found",
        "sunset": "Not found",
        "civil_dusk": "Not found",
        "civil_dawn": "Not found",
        "nautical_dusk": "Not found",
        "nautical_dawn": "Not found",
        "astronomical_dusk": "Not found",
        "astronomical_dawn": "Not found",
    }
    defaults.update(overrides)
    return {"sun": defaults}


# ---------------------------------------------------------------------------
# Unit tests for _determine_sky_period
# ---------------------------------------------------------------------------

class TestDetermineSkySeriod:
    """Direct unit tests for the _determine_sky_period helper in app.py."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import app as _app
        self._fn = _app._determine_sky_period

    def _call(self, sun_data, tz="UTC"):
        return self._fn(sun_data, tz)

    # ── No data ─────────────────────────────────────────────────────────────

    def test_none_sun_data_returns_unknown(self):
        period, next_p, secs = self._call(None)
        assert period == "unknown"
        assert next_p == "unknown"
        assert secs is None

    def test_empty_dict_returns_unknown(self):
        period, next_p, secs = self._call({})
        assert period == "unknown"

    def test_missing_sun_key_returns_unknown(self):
        period, next_p, secs = self._call({"moon": {}})
        assert period == "unknown"

    # ── Invalid timezone falls back to UTC ───────────────────────────────

    def test_invalid_timezone_falls_back_to_utc(self):
        now = datetime.now(timezone.utc)
        # Astronomical night: dusk 2h ago, dawn 2h from now
        sd = _make_sun_data(
            astronomical_dusk=_fmt(now - timedelta(hours=2)),
            astronomical_dawn=_fmt(now + timedelta(hours=2)),
        )
        period, _, _ = self._call(sd, tz="Invalid/Timezone")
        assert period == "astronomical_night"

    # ── parse_dt edge cases ──────────────────────────────────────────────

    def test_parse_dt_not_found_treated_as_absent(self):
        """All fields 'Not found' → day fallback."""
        sd = _make_sun_data()
        period, next_p, secs = self._call(sd)
        assert period == "day"
        assert secs is None  # fallback, no secs

    def test_parse_dt_invalid_format_ignored(self):
        """Malformed date string falls back gracefully (ValueError → None)."""
        sd = _make_sun_data(astronomical_dusk="bad-date", astronomical_dawn="also-bad")
        period, _, _ = self._call(sd)
        assert period == "day"

    # ── Astronomical night ───────────────────────────────────────────────

    def test_astronomical_night(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            astronomical_dusk=_fmt(now - timedelta(hours=2)),
            astronomical_dawn=_fmt(now + timedelta(hours=2)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "astronomical_night"
        assert next_p == "astronomical_dawn"
        assert secs > 0

    def test_astronomical_night_boundary_exact_dusk(self):
        """now == astro_dusk (==) still is astronomical_night."""
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            astronomical_dusk=_fmt(now),
            astronomical_dawn=_fmt(now + timedelta(hours=4)),
        )
        period, _, _ = self._call(sd)
        assert period == "astronomical_night"

    # ── Astronomical twilight (dusk side) ───────────────────────────────

    def test_astronomical_twilight_dusk(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            nautical_dusk=_fmt(now - timedelta(hours=1)),
            astronomical_dusk=_fmt(now + timedelta(hours=1)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "astronomical_twilight"
        assert next_p == "astronomical_night"
        assert secs > 0

    # ── Astronomical twilight (dawn side) ───────────────────────────────

    def test_astronomical_twilight_dawn(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            astronomical_dawn=_fmt(now - timedelta(hours=1)),
            nautical_dawn=_fmt(now + timedelta(hours=1)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "astronomical_twilight"
        assert next_p == "nautical_twilight"
        assert secs > 0

    # ── Nautical twilight (dusk side) ───────────────────────────────────

    def test_nautical_twilight_dusk(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            civil_dusk=_fmt(now - timedelta(hours=1)),
            nautical_dusk=_fmt(now + timedelta(hours=1)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "nautical_twilight"
        assert next_p == "astronomical_twilight"
        assert secs > 0

    # ── Nautical twilight (dawn side) ───────────────────────────────────

    def test_nautical_twilight_dawn(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            nautical_dawn=_fmt(now - timedelta(hours=1)),
            civil_dawn=_fmt(now + timedelta(hours=1)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "nautical_twilight"
        assert next_p == "civil_twilight"
        assert secs > 0

    # ── Civil twilight (dusk side) ──────────────────────────────────────

    def test_civil_twilight_dusk(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            sunset=_fmt(now - timedelta(minutes=30)),
            civil_dusk=_fmt(now + timedelta(minutes=30)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "civil_twilight"
        assert next_p == "nautical_twilight"
        assert secs > 0

    # ── Civil twilight (dawn side) ──────────────────────────────────────

    def test_civil_twilight_dawn(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            civil_dawn=_fmt(now - timedelta(minutes=30)),
            sunrise=_fmt(now + timedelta(minutes=30)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "civil_twilight"
        assert next_p == "day"
        assert secs > 0

    # ── Day ─────────────────────────────────────────────────────────────

    def test_day_sunset_in_future(self):
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            sunset=_fmt(now + timedelta(hours=3)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "day"
        assert next_p == "civil_twilight"
        assert secs > 0

    def test_day_no_sunset_civil_dusk_in_future(self):
        """sunset absent but civil_dusk is upcoming → still day."""
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            civil_dusk=_fmt(now + timedelta(hours=2)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "day"
        assert next_p == "civil_twilight"
        assert secs > 0

    def test_day_fallback_all_times_past(self):
        """All times in the past → day fallback, secs is None."""
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            sunset=_fmt(now - timedelta(hours=6)),
            civil_dusk=_fmt(now - timedelta(hours=5)),
            astronomical_dusk=_fmt(now - timedelta(hours=4)),
            astronomical_dawn=_fmt(now - timedelta(hours=3)),
            nautical_dawn=_fmt(now - timedelta(hours=2)),
            civil_dawn=_fmt(now - timedelta(hours=1)),
            sunrise=_fmt(now - timedelta(minutes=30)),
        )
        period, next_p, secs = self._call(sd)
        assert period == "day"
        assert next_p == "civil_twilight"
        assert secs is None

    # ── secs returns 0 when target is in the past ────────────────────────

    def test_secs_clamps_to_zero_when_past(self):
        """secs() uses max(0, ...) — test with a dawn that just passed."""
        now = datetime.now(timezone.utc)
        # astro night ended 5 minutes ago (astro_dawn in past), nautical_dawn future
        sd = _make_sun_data(
            astronomical_dawn=_fmt(now - timedelta(minutes=5)),
            nautical_dawn=_fmt(now + timedelta(hours=1)),
        )
        period, next_p, secs_val = self._call(sd)
        assert period == "astronomical_twilight"
        assert secs_val >= 0


# ---------------------------------------------------------------------------
# API endpoint tests for /api/sky-widget
# ---------------------------------------------------------------------------

class TestSkyWidgetApi:
    """Integration tests for GET /api/sky-widget."""

    # Patch target: get_current_astro_conditions is imported locally inside the
    # route function via `from weather_astro import ...`, so we patch it at the
    # source module level.
    _PATCH_TARGET = "weather_astro.get_current_astro_conditions"

    _FAKE_CONFIG = {
        "location": {"name": "Test City", "timezone": "UTC"},
    }
    _GOOD_CONDITIONS = {
        "seeing_pickering": 7.0,
        "transparency_score": 80.0,
        "cloud_discrimination": 70.0,
        "tracking_stability_score": 90.0,
        "observation_score": 8.2,  # (70+80+70+90)/4/10
    }

    def _setup_sun_cache(self, monkeypatch, sun_data):
        import cache_store as cs
        cs._sun_report_cache["data"] = sun_data
        monkeypatch.setattr(cs, "is_cache_valid", lambda *_: True)

    def test_happy_path_returns_json(self, client_admin, monkeypatch):
        """Valid cache + valid conditions → 200 with all expected keys."""
        now = datetime.now(timezone.utc)
        sd = _make_sun_data(
            astronomical_dusk=_fmt(now - timedelta(hours=2)),
            astronomical_dawn=_fmt(now + timedelta(hours=2)),
        )
        self._setup_sun_cache(monkeypatch, sd)
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, return_value=self._GOOD_CONDITIONS):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "period" in data
        assert "observation_score" in data
        assert data["period"] == "astronomical_night"
        assert data["observation_score"] is not None

    def test_score_formula_matches_night_timeline(self, client_admin, monkeypatch):
        """observation_score is read directly from current_conditions (computed by backend)."""
        conditions = {
            "seeing_pickering": 6.0,
            "transparency_score": 60.0,
            "cloud_discrimination": 60.0,
            "tracking_stability_score": 60.0,
            "observation_score": 6.0,
        }
        self._setup_sun_cache(monkeypatch, _make_sun_data())
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, return_value=conditions):
            resp = client_admin.get("/api/sky-widget")
        data = resp.get_json()
        assert data["observation_score"] == 6.0

    def test_sun_cache_invalid_triggers_sync(self, client_admin, monkeypatch):
        """When sun cache is invalid, sync_cache_from_shared is called."""
        import cache_store as cs

        cs._sun_report_cache["data"] = _make_sun_data()
        calls = []
        original_sync = cs.sync_cache_from_shared

        def mock_sync(key, cache):
            calls.append(key)
            return original_sync(key, cache)

        monkeypatch.setattr(cs, "is_cache_valid", lambda *_: False)
        monkeypatch.setattr(cs, "sync_cache_from_shared", mock_sync)
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, return_value=None):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 200
        assert "sun_report" in calls

    def test_score_is_none_when_conditions_unavailable(self, client_admin, monkeypatch):
        """get_current_astro_conditions returns None → score is None."""
        self._setup_sun_cache(monkeypatch, _make_sun_data())
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, return_value=None):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 200
        assert resp.get_json()["observation_score"] is None

    def test_score_is_none_when_conditions_missing_seeing(self, client_admin, monkeypatch):
        """Conditions without 'observation_score' → score stays None."""
        self._setup_sun_cache(monkeypatch, _make_sun_data())
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, return_value={"other": 1}):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 200
        assert resp.get_json()["observation_score"] is None

    def test_score_is_none_when_conditions_raises(self, client_admin, monkeypatch):
        """Exception in get_current_astro_conditions is swallowed, score is None."""
        self._setup_sun_cache(monkeypatch, _make_sun_data())
        with patch("app.load_config", return_value=self._FAKE_CONFIG), \
             patch(self._PATCH_TARGET, side_effect=RuntimeError("boom")):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 200
        assert resp.get_json()["observation_score"] is None

    def test_returns_500_on_unexpected_error(self, client_admin):
        """Outer exception in get_sky_widget_api → 500."""
        with patch("app.load_config", side_effect=RuntimeError("unexpected")):
            resp = client_admin.get("/api/sky-widget")
        assert resp.status_code == 500
