from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from space import iss_passes as mod


class _Deg:
    def __init__(self, degrees):
        self.degrees = degrees


class _Dist:
    def __init__(self, km):
        self.km = km


@pytest.fixture(autouse=True)
def _reset_ephemeris_memo():
    """Reset the process-wide de421 memo so each test's SKYFIELD_LOADER patch applies."""
    mod._EPHEMERIS = None
    mod._EPHEMERIS_ATTEMPTED = False
    yield
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
