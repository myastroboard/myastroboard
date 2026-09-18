"""Tests for connectors/mqtt_payloads.py - the Home Assistant wire format.

Every data source is planted by monkeypatching the module attribute the builders reach through
their lazy imports (cache_store, SkyTonight results, astrodex, plan, equipment, sessions), so
these tests never touch the shared temp DATA_DIR.
"""

import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from connectors import mqtt_payloads as mp
from connectors.mqtt_connector import MqttConnector

NOW = datetime(2026, 9, 17, 20, 30, tzinfo=timezone.utc)
LOCATION = {"id": "loc-1", "name": "Backyard", "timezone": "Europe/Paris", "latitude": 48.8, "longitude": 2.3}


def _connector(modules=None, **cfg):
    config = {"url": "mqtt://broker", "enabled": True, "base_topic": "mab", "discovery_prefix": "ha"}
    config.update(cfg)
    config["modules"] = {slug: {"enabled": True} for slug in (modules or [])}
    return MqttConnector(config)


@pytest.fixture
def caches(monkeypatch):
    """A dict of per-location cache payloads the builders read through cache_store."""
    from cache import cache_store

    store = {}
    monkeypatch.setattr(
        cache_store,
        "load_location_cache",
        lambda name, location_id: {"data": store.get((name, location_id)), "timestamp": 1_700_000_000},
    )
    monkeypatch.setattr(cache_store, "load_shared_cache_entry", lambda name: {"data": store.get(name)})
    monkeypatch.setattr(cache_store, "is_astronomical_cache_ready", lambda location_ids=None: True)
    return store


@pytest.fixture
def no_skytonight(monkeypatch):
    from skytonight import skytonight_calculator, skytonight_storage

    monkeypatch.setattr(skytonight_calculator, "load_calculation_results", lambda location_id=None: {})
    monkeypatch.setattr(skytonight_storage, "load_scheduler_status", lambda default=None: {})


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


class TestValueHelpers:

    def test_to_iso_localises_naive_report_strings(self):
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Paris")
        assert mp.to_iso("2026-01-29 17:45", tz) == "2026-01-29T17:45:00+01:00"
        assert mp.to_iso("2026-07-29 17:45:30", tz) == "2026-07-29T17:45:30+02:00"  # DST honoured

    def test_to_iso_keeps_offsets_and_handles_utc_z(self):
        assert mp.to_iso("2026-02-03T20:28:00+01:00") == "2026-02-03T20:28:00+01:00"
        assert mp.to_iso("2026-02-03T20:28:00Z") == "2026-02-03T20:28:00+00:00"
        assert mp.to_iso(NOW) == "2026-09-17T20:30:00+00:00"
        assert mp.to_iso("2026-02-03T20:28:00") == "2026-02-03T20:28:00+00:00"  # naive ISO -> UTC by default

    @pytest.mark.parametrize("value", [None, "", "Not found", "None", "n/a", "garbage", "2026-13-45 99:99"])
    def test_to_iso_rejects_placeholders_and_garbage(self, value):
        assert mp.to_iso(value) is None

    def test_to_date_num_text(self):
        assert mp.to_date("2026-09-17T01:00:00") == "2026-09-17"
        assert mp.to_date("nope") is None
        assert mp.num("3.14159", 2) == 3.14
        assert mp.num(True) is None
        assert mp.num("x") is None
        assert mp.num(float("nan")) is None
        assert mp.text("  hi  ") == "hi"
        assert mp.text("") is None
        assert len(mp.text("x" * 500)) == mp.MAX_STATE_LEN


# ---------------------------------------------------------------------------
# Component specs and assembly
# ---------------------------------------------------------------------------


class TestAssembly:

    def test_sensor_and_binary_sensor_specs(self):
        key, spec = mp.sensor("score", "Score", device_class="enum", options=["a"], unit="%", state_class="measurement",
                              icon="mdi:x", precision=1, diagnostic=True, attributes=True)
        assert key == "score"
        assert spec["p"] == "sensor" and spec["val_tpl"] == "{{ value_json.score }}"
        assert spec["dev_cla"] == "enum" and spec["ops"] == ["a"] and spec["unit_of_meas"] == "%"
        assert spec["stat_cla"] == "measurement" and spec["ic"] == "mdi:x" and spec["sug_dsp_prc"] == 1
        assert spec["ent_cat"] == "diagnostic"
        assert spec["json_attr_tpl"] == "{{ value_json.score_attributes | tojson }}"

        key, spec = mp.binary_sensor("night", "Night", device_class="running")
        assert spec["p"] == "binary_sensor" and "'None' if value_json.night is none" in spec["val_tpl"]

    def test_assemble_builds_a_complete_device_discovery(self):
        connector = _connector()
        device = mp._assemble(
            connector, kind="location", object_id="loc-1", name="MyAstroBoard - Backyard", model="Location",
            version="1.6.0", components=[mp.sensor("a", "A", attributes=True), mp.binary_sensor("b", "B")],
            state={"a": 1, "a_attributes": {}, "b": True},
        )
        assert device.device_id == "mab_loc_loc-1"
        assert device.discovery_topic == "ha/device/mab_loc_loc-1/config"
        assert device.state_topic == "mab/location/loc-1/state"
        assert device.entity_count == 2
        disc = device.discovery
        assert disc["dev"] == {"ids": ["mab_loc_loc-1"], "name": "MyAstroBoard - Backyard", "mf": "MyAstroBoard",
                               "mdl": "Location", "sw": "1.6.0", "via_device": "mab_board"}
        assert disc["o"]["name"] == "MyAstroBoard" and disc["o"]["url"] == mp.HOMEPAGE
        assert disc["avty_t"] == "mab/status"
        assert "stat_t" not in disc  # per component, never shared (an image component would refuse it)
        comp = disc["cmps"]["a"]
        assert comp["uniq_id"] == "mab_loc_loc-1_a"
        assert comp["stat_t"] == "mab/location/loc-1/state"
        assert comp["json_attr_t"] == "mab/location/loc-1/state"
        assert "json_attr_t" not in disc["cmps"]["b"]
        json.dumps(disc)  # serialisable

    def test_board_device_has_no_via_device(self, caches, no_skytonight):
        device = mp.build_board_device(_connector(), {"last_publish": NOW, "locations": 2, "users": 1})
        assert "via_device" not in device.discovery["dev"]
        assert device.device_id == "mab_board"


# ---------------------------------------------------------------------------
# Board device
# ---------------------------------------------------------------------------


class TestBoardDevice:

    def test_state_reflects_version_update_scheduler_and_publisher_info(self, caches, monkeypatch):
        from skytonight import skytonight_storage

        caches["version_update"] = {"update_available": True, "latest_version": "1.7.0"}
        monkeypatch.setattr(skytonight_storage, "load_scheduler_status", lambda default=None: {
            "is_executing": False, "last_run": "2026-09-17T06:00:00+02:00", "next_run": "2026-09-17T18:30:00+02:00",
        })
        monkeypatch.setattr(mp, "_app_version", lambda: "1.6.0")
        device = mp.build_board_device(_connector(), {"last_publish": NOW, "locations": 2, "users": 1})
        assert device.state == {
            "version": "1.6.0",
            "update_available": True,
            "latest_version": "1.7.0",
            "caches_ready": True,
            "skytonight_running": False,
            "skytonight_last_run": "2026-09-17T06:00:00+02:00",
            "skytonight_next_run": "2026-09-17T18:30:00+02:00",
            "last_publish": "2026-09-17T20:30:00+00:00",
            "locations_published": 2,
            "users_published": 1,
        }
        assert set(device.discovery["cmps"]) == set(device.state)
        assert all(c.get("ent_cat") == "diagnostic" for c in device.discovery["cmps"].values())

    def test_missing_sources_publish_nulls(self, caches, monkeypatch):
        from cache import cache_store
        from skytonight import skytonight_storage

        def boom(*a, **k):
            raise RuntimeError("no")

        monkeypatch.setattr(cache_store, "is_astronomical_cache_ready", boom)
        monkeypatch.setattr(skytonight_storage, "load_scheduler_status", boom)
        device = mp.build_board_device(_connector(), {})
        assert device.state["update_available"] is None
        assert device.state["caches_ready"] is None
        assert device.state["skytonight_last_run"] is None
        assert device.state["last_publish"] is None


# ---------------------------------------------------------------------------
# Location device
# ---------------------------------------------------------------------------


def _plant_sky(caches, monkeypatch):
    from skytonight import skytonight_calculator, skytonight_storage

    caches[("sun_report", "loc-1")] = {"sun": {
        "sunrise": "2026-09-17 07:30", "sunset": "2026-09-17 19:55", "civil_dusk": "2026-09-17 20:25",
        "civil_dawn": "2026-09-17 07:00", "nautical_dusk": "2026-09-17 21:02", "nautical_dawn": "2026-09-17 06:23",
        "astronomical_dusk": "2026-09-17 21:41", "astronomical_dawn": "2026-09-17 05:44", "true_night_hours": 8.05,
    }}
    caches[("astro_weather", "loc-1")] = {
        "current_conditions": {"observation_score": 7.25, "seeing_pickering": 6.4, "transparency_score": 7.1,
                               "limiting_magnitude": 5.6, "dew_risk_level": "moderate", "dew_point_spread": 2.2,
                               "wind_tracking_impact": "LOW", "tracking_stability_score": 8.0},
        "weather_alerts": [{"message": "Dew likely after 02:00", "level": "warning"}],
    }
    caches[("moon_report", "loc-1")] = {"moon": {
        "phase_name": "Waxing Crescent", "illumination_percent": 33.4, "altitude_deg": -12.2, "azimuth_deg": 250.0,
        "distance_km": 384400.4, "next_moonrise": "2026-09-18T12:10:00+02:00", "next_moonset": "Not found",
        "next_full_moon": "2026-09-26T05:49:00+02:00", "next_new_moon": "2026-10-10T20:50:00+02:00",
    }}
    caches[("dark_window", "loc-1")] = {"next_dark_night": {"start": "2026-09-17 22:30", "end": "2026-09-18 05:44"}}
    caches[("best_window_practical", "loc-1")] = {"best_window": {
        "start": "2026-09-17 22:30", "end": "2026-09-18 03:10", "duration_hours": 4.67, "moon_condition": "Moon set", "score": 82,
    }}
    monkeypatch.setattr(skytonight_calculator, "load_calculation_results", lambda location_id=None: {
        "metadata": {"night_start": "2026-09-17T21:41:00+02:00", "night_end": "2026-09-18T05:44:00+02:00",
                     "calculated_at": "2026-09-17T16:00:00+00:00"},
        "deep_sky": [
            {"preferred_name": "M31", "object_type": "Galaxy", "constellation": "Andromeda", "magnitude": 3.4,
             "observation": {"max_altitude": 78.2, "observable_hours": 6.5}, "astro_score": 0.91},
            {"preferred_name": "M33", "object_type": "Galaxy", "constellation": "Triangulum", "magnitude": 5.7,
             "observation": {"max_altitude": 70.0}, "astro_score": 0.95},
            {"preferred_name": "NGC 7000", "object_type": "Nebula", "constellation": "Cygnus", "magnitude": None,
             "observation": {"max_altitude": 85.0}, "astro_score": 0.91},
            "not-a-dict",
        ],
    })
    monkeypatch.setattr(skytonight_storage, "load_scheduler_status", lambda default=None: {})


class TestLocationDevice:

    def test_no_location_module_enabled_means_no_device(self, caches):
        assert mp.build_location_device(_connector(["board_diagnostics"]), {}, LOCATION, NOW) is None

    def test_sky_conditions_state_and_components(self, caches, monkeypatch):
        _plant_sky(caches, monkeypatch)
        device = mp.build_location_device(_connector(["sky_conditions"]), {}, LOCATION, NOW)
        assert device is not None
        assert device.name == "MyAstroBoard - Backyard"
        s = device.state
        assert s["location_id"] == "loc-1" and s["timezone"] == "Europe/Paris"
        # 20:30 UTC = 22:30 Paris, between astronomical dusk (21:41) and dawn (05:44) - but the helper uses the
        # real clock, so only assert the shape here; the exact branch is covered by test_sky_widget.py.
        assert s["sky_period"] in mp.SKY_PERIOD_OPTIONS
        assert s["astronomical_dusk"] == "2026-09-17T21:41:00+02:00"
        assert s["sunrise"] == "2026-09-17T07:30:00+02:00"
        assert s["true_night_hours"] == 8.05
        assert s["observation_score"] == 7.2
        assert s["moon_phase"] == "Waxing Crescent" and s["moon_illumination"] == 33 and s["moon_distance"] == 384400
        assert s["next_moonrise"] == "2026-09-18T12:10:00+02:00" and s["next_moonset"] is None
        assert s["dark_window_start"] == "2026-09-17T22:30:00+02:00"
        assert s["best_window_end"] == "2026-09-18T03:10:00+02:00" and s["best_window_score"] == 82
        assert s["best_window_moon"] == "Moon set"
        # Top target: highest AstroScore first, ties by max altitude
        assert s["top_target"] == "M33" and s["top_target_score"] == 0.95
        names = [t["name"] for t in s["top_target_attributes"]["top_targets"]]
        assert names == ["M33", "NGC 7000", "M31"]
        assert s["top_target_attributes"]["constellation"] == "Triangulum"
        assert s["night_start"] == "2026-09-17T21:41:00+02:00"
        assert s["skytonight_calculated_at"] == "2026-09-17T16:00:00+00:00"
        # Every component template has a state key behind it
        for key, comp in device.discovery["cmps"].items():
            assert key in s, key
            if "json_attr_tpl" in comp:
                assert f"{key}_attributes" in s
        assert device.discovery["cmps"]["sky_period"]["ops"] == mp.SKY_PERIOD_OPTIONS

    def test_sky_conditions_with_empty_caches_is_all_null_but_complete(self, caches, no_skytonight):
        device = mp.build_location_device(_connector(["sky_conditions"]), {}, LOCATION, NOW)
        assert device is not None
        s = device.state
        assert s["sky_period"] == "unknown" and s["is_astronomical_night"] is None
        assert s["top_target"] is None and s["top_target_attributes"] == {}
        assert all(s[key] is None for key in ("sunrise", "moon_phase", "best_window_score", "night_start"))
        assert set(device.discovery["cmps"]) <= set(s)

    def test_sky_period_failure_degrades_to_unknown(self, caches, no_skytonight, monkeypatch):
        from astroweather import sun_phases

        def boom(*a, **k):
            raise RuntimeError("tz")

        monkeypatch.setattr(sun_phases, "determine_sky_period", boom)
        device = mp.build_location_device(_connector(["sky_conditions"]), {}, LOCATION, NOW)
        assert device.state["sky_period"] == "unknown" and device.state["next_period"] == "unknown"
        assert device.state["is_astronomical_night"] is None

    def test_sky_period_maps_astronomical_dawn_to_a_period(self, caches, no_skytonight, monkeypatch):
        from astroweather import sun_phases

        monkeypatch.setattr(sun_phases, "determine_sky_period", lambda *a, **k: ("astronomical_night", "astronomical_dawn", 600))
        device = mp.build_location_device(_connector(["sky_conditions"]), {}, LOCATION, NOW)
        assert device.state["sky_period"] == "astronomical_night"
        assert device.state["next_period"] == "astronomical_twilight"
        assert device.state["next_period_at"] == "2026-09-17T20:40:00+00:00"
        assert device.state["is_astronomical_night"] is True

    def test_weather_now_picks_the_nearest_hour_and_astro_numbers(self, caches, monkeypatch):
        _plant_sky(caches, monkeypatch)
        caches[("weather_forecast", "loc-1")] = {"hourly": [
            {"date": "2026-09-17T19:00:00+0000", "temperature_2m": 18.0, "cloud_cover": 90},
            {"date": "2026-09-17T21:00:00+0000", "temperature_2m": 14.26, "relative_humidity_2m": 71.4,
             "dew_point_2m": 9.1, "cloud_cover": 12, "cloud_cover_low": 5, "cloud_cover_mid": 7, "cloud_cover_high": 0,
             "wind_speed_10m": 8.44, "wind_direction_10m": 225.0, "precipitation_probability": 3,
             "precipitation": 0.0, "surface_pressure": 1017.6, "visibility": 24140.0, "weather_code": 1},
            "junk",
            {"date": "not a date"},
        ]}
        device = mp.build_location_device(_connector(["weather_now"]), {}, LOCATION, NOW)
        s = device.state
        assert s["temperature"] == 14.3 and s["humidity"] == 71 and s["cloud_cover"] == 12
        assert s["wind_speed"] == 8.4 and s["pressure"] == 1018 and s["weather_code"] == 1
        assert s["seeing"] == 6.4 and s["transparency"] == 7.1 and s["limiting_magnitude"] == 5.6
        assert s["dew_risk"] == "MODERATE" and s["wind_tracking_impact"] == "LOW"
        assert s["weather_alert"] == "Dew likely after 02:00"
        assert s["weather_alert_attributes"]["count"] == 1
        assert s["forecast_updated_at"] == "2023-11-14T22:13:20+00:00"
        assert "sky_period" not in s  # module off
        assert set(device.discovery["cmps"]) <= set(s)

    def test_weather_now_unknown_enum_values_become_null(self, caches, no_skytonight):
        caches[("astro_weather", "loc-1")] = {"current_conditions": {"dew_risk_level": "weird", "wind_tracking_impact": ""}}
        device = mp.build_location_device(_connector(["weather_now"]), {}, LOCATION, NOW)
        assert device.state["dew_risk"] is None and device.state["wind_tracking_impact"] is None
        assert device.state["weather_alert"] is None and device.state["temperature"] is None

    def test_upcoming_events_passes_aurora_eclipses_and_aggregator(self, caches, no_skytonight, monkeypatch):
        caches[("iss_passes", "loc-1")] = {"passes": [
            {"start_time": "2026-09-17T19:00:00+02:00", "end_time": "2026-09-17T19:06:00+02:00"},  # already over
            {"start_time": "2026-09-17T23:13:00+02:00", "peak_time": "2026-09-17T23:16:00+02:00",
             "end_time": "2026-09-17T23:19:00+02:00", "peak_altitude_deg": 64.2, "duration_minutes": 6.4,
             "visibility_score": 8.7},
            {"start_time": "2026-09-18T22:00:00+02:00", "end_time": "2026-09-18T22:05:00+02:00"},
            "junk",
        ]}
        caches[("css_passes", "loc-1")] = {"passes": []}
        caches[("aurora", "loc-1")] = {"current": {"kp_index": 4.33, "probability": 22.5, "visibility_level": "Low"}}
        caches[("solar_eclipse", "loc-1")] = {"solar_eclipse": {
            "type": "Partial", "obscuration_percent": 45.0, "peak_time": "2026-08-12 14:32:15",
            "start_time": "2026-08-12 13:05:00", "end_time": "2026-08-12 15:59:00", "visible": True}}
        caches[("lunar_eclipse", "loc-1")] = {"lunar_eclipse": None}

        class _FakeAggregator:
            def __init__(self, lat, lon, tz, language="en"):
                self.args = (lat, lon, tz, language)

            def aggregate_all_events(self, **kwargs):
                assert set(kwargs) == {
                    "solar_eclipse_data", "lunar_eclipse_data", "aurora_data", "iss_passes_data", "css_passes_data",
                    "moon_phases_data", "planetary_events_data", "special_phenomena_data", "solar_system_events_data",
                }
                return {"events_count": 3, "next_event": {
                    "title": "ISS pass", "event_type": "iss_pass", "description": "Bright pass",
                    "start_time": "2026-09-17T23:13:00+02:00", "peak_time": "2026-09-17T23:16:00+02:00",
                    "end_time": None, "days_until_event": 0, "importance": "high", "visibility": True}}

        from utils import events_aggregator

        monkeypatch.setattr(events_aggregator, "EventsAggregator", _FakeAggregator)
        device = mp.build_location_device(_connector(["upcoming_events"]), {"language": "fr"}, LOCATION, NOW)
        s = device.state
        assert s["next_iss_pass_at"] == "2026-09-17T23:13:00+02:00"
        assert s["next_iss_pass_peak_altitude"] == 64 and s["next_iss_pass_duration"] == 6.4 and s["next_iss_pass_score"] == 8.7
        assert s["next_css_pass_at"] is None
        assert s["aurora_kp"] == 4.3 and s["aurora_probability"] == 22 and s["aurora_visibility"] == "Low"
        assert s["next_solar_eclipse_at"] == "2026-08-12T14:32:15+02:00"
        assert s["next_solar_eclipse_at_attributes"]["type"] == "Partial"
        assert s["next_lunar_eclipse_at"] is None and s["next_lunar_eclipse_at_attributes"] == {}
        assert s["next_event"] == "ISS pass" and s["next_event_at"] == "2026-09-17T23:16:00+02:00"
        assert s["next_event_attributes"]["events_count"] == 3 and s["next_event_attributes"]["importance"] == "high"
        assert set(device.discovery["cmps"]) <= set(s)

    def test_upcoming_events_survive_an_aggregator_failure(self, caches, no_skytonight, monkeypatch):
        from utils import events_aggregator

        class _Broken:
            def __init__(self, *a, **k):
                raise RuntimeError("boom")

        monkeypatch.setattr(events_aggregator, "EventsAggregator", _Broken)
        device = mp.build_location_device(_connector(["upcoming_events"]), {}, LOCATION, NOW)
        assert device.state["next_event"] is None

    def test_all_three_modules_compose_into_one_device(self, caches, monkeypatch):
        _plant_sky(caches, monkeypatch)
        device = mp.build_location_device(_connector(["sky_conditions", "weather_now", "upcoming_events"]), {}, LOCATION, NOW)
        cmps = device.discovery["cmps"]
        assert {"sky_period", "temperature", "next_event"} <= set(cmps)
        assert device.entity_count == len(mp.SKY_COMPONENTS) + len(mp.WEATHER_COMPONENTS) + len(mp.EVENTS_COMPONENTS)
        json.dumps(device.state)


# ---------------------------------------------------------------------------
# User device
# ---------------------------------------------------------------------------


def _user(opted_in=True, user_id="u-1", username="alice"):
    return SimpleNamespace(user_id=user_id, username=username, preferences={"mqtt_publish_enabled": opted_in})


@pytest.fixture
def user_sources(monkeypatch):
    """Plant astrodex / plan / equipment / sessions for user u-1."""
    from equipment import equipment_profiles
    from observation import astrodex, observation_sessions, plan_my_night

    astro = {"items": [
        {"id": "i1", "name": "M31", "catalogue": "Messier", "type": "Galaxy", "constellation": "Andromeda",
         "pictures": [
             {"id": "p1", "filename": "a.jpg", "date": "2026-08-01", "created_at": "2026-08-01T22:00:00+00:00", "device": "Old rig"},
             {"id": "p2", "filename": "b.jpg", "date": "2026-09-10", "created_at": "2026-09-10T23:30:00+00:00",
              "device": "Newton 200/1000", "rating": 4.5, "integration_minutes": 90},
         ]},
        {"id": "i2", "name": "M42", "catalogue": "Messier", "type": "Nebula", "constellation": "orion", "pictures": []},
        {"id": "i3", "name": "NGC 7000", "catalogue": "NGC", "type": "Nebula", "constellation": "", "pictures": []},
    ]}
    monkeypatch.setattr(astrodex, "load_user_astrodex", lambda user_id, username=None: astro)
    monkeypatch.setattr(astrodex, "_resolve_image_file_path", lambda filename: f"/img/{filename}")

    plan_payload = {
        "state": "current",
        "timeline": {"is_inside_night": True, "progress_percent": 42.6, "current_target_id": "e2"},
        "current_banner": {"id": "e2", "name": "M33", "catalogue": "Messier", "type": "Galaxy", "planned_minutes": 60,
                           "timeline_start": "2026-09-17T22:00:00+02:00", "timeline_end": "2026-09-17T23:00:00+02:00",
                           "visibility": {"status": "ok"}, "meridian_flip": {"state": "mid"}},
        "plan": {
            "night_start": "2026-09-17T21:41:00+02:00", "night_end": "2026-09-18T05:44:00+02:00",
            "location_id": "loc-1", "combination_id": "c1",
            "entries": [{"id": "e1", "name": "M31", "done": True}, {"id": "e2", "name": "M33", "done": False},
                        {"id": "e3", "name": "M45", "done": False}, "junk"],
        },
    }
    monkeypatch.setattr(plan_my_night, "pick_active_plan", lambda user_id, username: plan_payload)

    monkeypatch.setattr(equipment_profiles, "get_combination", lambda user_id, cid: {
        "id": "c1", "name": "Newton rig", "telescope_id": "t1", "camera_id": "cam1", "mount_id": "m1",
        "filter_ids": ["f1", "missing"], "accessory_ids": [], "is_disabled": False,
    } if cid == "c1" else None)
    monkeypatch.setattr(equipment_profiles, "load_all_shared_combinations", lambda user_id: [])
    monkeypatch.setattr(equipment_profiles, "index_owned_and_shared_equipment", lambda user_id: (
        {"t1": {"name": "Newton 200/1000", "focal_length_mm": 1000, "aperture_mm": 200}, "cam1": {"name": "ASI533"},
         "m1": {"name": "EQ6-R"}, "f1": {"name": "L-eNhance"}},
        {},
    ))

    # Entries hang off the session and point at a night by id (observation_sessions.py model).
    sessions = [
        {"id": "s1", "nights": [{"id": "n1", "date": "2026-09-10"}],
         "entries": [{"id": "x", "night_id": "n1", "frame_count": 30, "sub_exposure_seconds": 120}]},
        {"id": "s2", "nights": [{"id": "n2", "date": "2026-08-01"}],
         "entries": [{"id": "y", "night_id": "n2", "integration_minutes": 45}]},
    ]
    monkeypatch.setattr(observation_sessions, "get_user_sessions", lambda user_id: sessions)
    return {"astro": astro, "plan": plan_payload, "sessions": sessions}


class TestUserDevice:

    def test_requires_opt_in_and_an_enabled_module(self, user_sources):
        assert mp.build_user_device(_connector(["user_activity"]), {}, _user(opted_in=False), NOW) is None
        assert mp.build_user_device(_connector(["sky_conditions"]), {}, _user(), NOW) is None
        assert mp.build_user_device(_connector(["user_activity"]), {}, SimpleNamespace(user_id="", username="x", preferences={}), NOW) is None
        assert mp.user_opted_in(SimpleNamespace(preferences=None)) is False

    def test_user_activity_state(self, user_sources, monkeypatch):
        from utils import repo_config

        monkeypatch.setattr(repo_config, "get_location_by_id", lambda config, lid: {"name": "Backyard"} if lid == "loc-1" else None)
        device = mp.build_user_device(_connector(["user_activity"]), {"locations": []}, _user(), NOW)
        assert device is not None
        assert device.name == "MyAstroBoard - alice" and device.device_id == "mab_user_u-1"
        s = device.state
        assert s["astrodex_objects"] == 3 and s["astrodex_objects_with_pictures"] == 1 and s["astrodex_pictures"] == 2
        assert s["astrodex_constellations"] == 2  # 'orion' counts, '' does not
        assert s["astrodex_last_picture_at"] == "2026-09-10T23:30:00+00:00"
        assert s["astrodex_last_picture_object"] == "M31"
        assert s["astrodex_last_picture_object_attributes"]["equipment"] == "Newton 200/1000"
        assert s["astrodex_last_picture_object_attributes"]["rating"] == 4.5
        assert s["plan_state"] == "current" and s["plan_active"] is True and s["plan_progress"] == 43
        assert s["plan_current_target"] == "M33" and s["plan_next_target"] == "M45"
        assert s["plan_current_target_attributes"]["meridian_flip"] == "mid"
        assert s["plan_night_start"] == "2026-09-17T21:41:00+02:00"
        assert s["plan_targets_total"] == 3 and s["plan_targets_done"] == 1
        assert s["plan_location"] == "Backyard"
        assert s["active_equipment"] == "Newton rig"
        eq = s["active_equipment_attributes"]
        assert eq["telescope"] == "Newton 200/1000" and eq["camera"] == "ASI533" and eq["mount"] == "EQ6-R"
        assert eq["filters"] == ["L-eNhance"] and eq["focal_length_mm"] == 1000 and eq["aperture_mm"] == 200
        assert s["sessions_total"] == 2
        assert s["integration_hours_total"] == 1.8  # 30 x 120 s = 60 min + 45 min
        assert s["last_session_date"] == "2026-09-10"
        assert device.image_topic is None
        for key, comp in device.discovery["cmps"].items():
            assert key in s, key
        assert device.discovery["cmps"]["plan_state"]["ops"] == mp.PLAN_STATE_OPTIONS

    def test_user_without_plan_or_pictures(self, user_sources, monkeypatch):
        from observation import astrodex, plan_my_night

        monkeypatch.setattr(plan_my_night, "pick_active_plan", lambda user_id, username: None)
        monkeypatch.setattr(astrodex, "load_user_astrodex", lambda user_id, username=None: {"items": []})
        device = mp.build_user_device(_connector(["user_activity", "astrodex_image"]), {}, _user(), NOW)
        s = device.state
        assert s["plan_state"] == "none" and s["plan_active"] is False and s["plan_progress"] == 0
        assert s["plan_targets_total"] == 0 and s["plan_current_target"] is None
        assert s["astrodex_objects"] == 0 and s["astrodex_last_picture_at"] is None
        assert s["active_equipment"] is None
        assert device.image_topic == "mab/user/u-1/astrodex/latest_image"
        assert device.image_id is None and device.image_loader is None
        assert s["latest_picture_attributes"] == {}
        assert device.discovery["cmps"]["latest_picture"]["p"] == "image"

    def test_source_failures_leave_nulls(self, user_sources, monkeypatch):
        from equipment import equipment_profiles
        from observation import astrodex, observation_sessions, plan_my_night

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(astrodex, "load_user_astrodex", boom)
        monkeypatch.setattr(plan_my_night, "pick_active_plan", boom)
        monkeypatch.setattr(equipment_profiles, "get_combination", boom)
        monkeypatch.setattr(observation_sessions, "get_user_sessions", boom)
        device = mp.build_user_device(_connector(["user_activity"]), {}, _user(), NOW)
        s = device.state
        assert s["astrodex_objects"] is None and s["plan_state"] == "none" and s["sessions_total"] is None

    def test_shared_combination_and_missing_combination(self, user_sources, monkeypatch):
        from equipment import equipment_profiles

        monkeypatch.setattr(equipment_profiles, "get_combination", lambda user_id, cid: None)
        monkeypatch.setattr(equipment_profiles, "load_all_shared_combinations", lambda user_id: [
            {"id": "c1", "name": "Shared rig", "telescope_id": None, "lens_focal_length_mm": 135, "is_disabled": True}])
        device = mp.build_user_device(_connector(["user_activity"]), {}, _user(), NOW)
        eq = device.state["active_equipment_attributes"]
        assert device.state["active_equipment"] == "Shared rig"
        assert eq["telescope"] is None and eq["focal_length_mm"] == 135 and eq["disabled"] is True

        monkeypatch.setattr(equipment_profiles, "load_all_shared_combinations", lambda user_id: [])
        device = mp.build_user_device(_connector(["user_activity"]), {}, _user(), NOW)
        assert device.state["active_equipment"] is None

    def test_image_module_alone_still_finds_the_latest_picture(self, user_sources, monkeypatch):
        monkeypatch.setattr(mp, "encode_thumbnail", lambda path, edge, size, q: b"JPEGBYTES:" + path.encode())
        device = mp.build_user_device(_connector(["astrodex_image"]), {}, _user(), NOW)
        assert device.entity_count == 1
        assert "astrodex_objects" not in device.state
        assert device.image_id == "p2"
        assert device.image_loader() == b"JPEGBYTES:/img/b.jpg"
        attrs = device.state["latest_picture_attributes"]
        assert attrs["object"] == "M31" and attrs["picture_id"] == "p2" and attrs["date"] == "2026-09-10"
        comp = device.discovery["cmps"]["latest_picture"]
        assert comp["img_t"] == "mab/user/u-1/astrodex/latest_image"
        assert comp["content_type"] == "image/jpeg"
        assert comp["json_attr_t"] == "mab/user/u-1/state"
        assert comp["uniq_id"] == "mab_user_u-1_latest_picture"
        assert "stat_t" not in comp and "val_tpl" not in comp

    def test_image_loader_handles_a_rejected_path(self, user_sources, monkeypatch):
        from observation import astrodex

        monkeypatch.setattr(astrodex, "_resolve_image_file_path", lambda filename: None)
        device = mp.build_user_device(_connector(["astrodex_image"]), {}, _user(), NOW)
        assert device.image_loader() is None

        def boom(filename):
            raise RuntimeError("no")

        monkeypatch.setattr(astrodex, "_resolve_image_file_path", boom)
        assert device.image_loader() is None


class TestEncodeThumbnail:

    @staticmethod
    def _png(tmp_path, size=(3000, 2000)):
        from PIL import Image

        path = tmp_path / "big.png"
        img = Image.new("RGB", size, (20, 30, 40))
        for x in range(0, size[0], 7):
            for y in range(0, size[1], 11):
                img.putpixel((x, y), (x % 255, y % 255, (x + y) % 255))
        img.save(path)
        return str(path)

    def test_resizes_to_the_edge_and_returns_jpeg(self, tmp_path):
        from PIL import Image

        data = mp.encode_thumbnail(self._png(tmp_path), 1280, 1_000_000, 82)
        assert data and data[:2] == b"\xff\xd8"
        with Image.open(io.BytesIO(data)) as out:
            assert max(out.size) == 1280

    def test_steps_down_when_over_the_byte_cap(self, tmp_path):
        from PIL import Image

        data = mp.encode_thumbnail(self._png(tmp_path), 1280, 60_000, 82)
        assert data is not None
        assert len(data) <= 60_000
        with Image.open(io.BytesIO(data)) as out:
            assert max(out.size) < 1280

    def test_gives_up_when_nothing_fits(self, tmp_path):
        assert mp.encode_thumbnail(self._png(tmp_path), 1280, 500, 82) is None

    def test_unreadable_file_is_none(self, tmp_path):
        assert mp.encode_thumbnail(str(tmp_path / "missing.jpg"), 1280, 1_000_000, 82) is None


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------


class TestCollect:

    def test_collects_locations_users_and_board_in_order(self, caches, no_skytonight, user_sources, monkeypatch):
        from utils import auth, repo_config

        monkeypatch.setattr(repo_config, "get_scheduler_locations", lambda config: [LOCATION, {"name": "no id"}, "junk"])
        users = {"u-1": _user(), "u-2": _user(opted_in=False, user_id="u-2", username="bob")}
        monkeypatch.setattr(auth, "user_manager", SimpleNamespace(users=users, _reload_users_if_changed=lambda: None))
        connector = _connector(["sky_conditions", "user_activity", "board_diagnostics"])
        devices = mp.collect(connector, {}, {"last_publish": NOW}, NOW)
        assert [d.kind for d in devices] == ["location", "user", "board"]
        board = devices[-1]
        assert board.state["locations_published"] == 1 and board.state["users_published"] == 1

    def test_board_only_when_nothing_else_is_enabled(self, caches, no_skytonight, monkeypatch):
        from utils import repo_config

        monkeypatch.setattr(repo_config, "get_scheduler_locations", lambda config: pytest.fail("must not list locations"))
        devices = mp.collect(_connector(["board_diagnostics"]), {}, {}, NOW)
        assert [d.kind for d in devices] == ["board"]
        assert devices[0].state["locations_published"] == 0

    def test_a_failing_builder_is_skipped_not_fatal(self, caches, no_skytonight, user_sources, monkeypatch):
        from utils import auth, repo_config

        monkeypatch.setattr(repo_config, "get_scheduler_locations", lambda config: [LOCATION, dict(LOCATION, id="loc-2")])
        original = mp.build_location_device

        def flaky(connector, config, location, now=None):
            if location["id"] == "loc-2":
                raise RuntimeError("boom")
            return original(connector, config, location, now)

        monkeypatch.setattr(mp, "build_location_device", flaky)
        monkeypatch.setattr(auth, "user_manager", SimpleNamespace(users={"u-1": _user()}, _reload_users_if_changed=lambda: None))
        monkeypatch.setattr(mp, "build_user_device", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(mp, "build_board_device", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        devices = mp.collect(_connector(["sky_conditions", "user_activity", "board_diagnostics"]), {}, {}, NOW)
        assert [d.object_id for d in devices] == ["loc-1"]

    def test_listing_failures_are_logged_not_raised(self, caches, no_skytonight, monkeypatch):
        from utils import auth, repo_config

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(repo_config, "get_scheduler_locations", boom)
        monkeypatch.setattr(auth, "user_manager", SimpleNamespace(users={}, _reload_users_if_changed=boom))
        devices = mp.collect(_connector(["sky_conditions", "user_activity"]), {}, {}, NOW)
        assert devices == []


class TestLongTermStatistics:

    def test_only_the_users_cumulative_counters_record_statistics(self):
        """Home Assistant keeps long-term statistics for every sensor with a state_class, and keeps
        them after the entity is removed. Ephemeris and forecast values must not opt in."""
        with_stats = {
            key
            for components in (mp.BOARD_COMPONENTS, mp.SKY_COMPONENTS, mp.WEATHER_COMPONENTS, mp.EVENTS_COMPONENTS, mp.USER_COMPONENTS)
            for key, spec in components
            if "stat_cla" in spec
        }
        assert with_stats == {
            "astrodex_objects", "astrodex_objects_with_pictures", "astrodex_pictures", "astrodex_constellations",
            "sessions_total", "integration_hours_total",
        }
        # Counters can decrease (a deleted picture): "total", never "total_increasing"
        assert all(spec["stat_cla"] == "total" for _, spec in mp.USER_COMPONENTS if "stat_cla" in spec)
