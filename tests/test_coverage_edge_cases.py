"""Targeted edge-case tests for backend branches that are hard to reach via feature tests.

These tests are intentionally small and focused, and grouped by backend module
to keep behavior-oriented suites readable.
"""

import json
import os
import tempfile
import types
from unittest.mock import MagicMock, patch

import app as _app_mod
from blueprints import locations as _locations_mod
import pytest


def test_validate_location_payload_accepts_none_bortle():
    payload = {
        "name": "Site",
        "latitude": 10,
        "longitude": 20,
        "elevation": 100,
        "timezone": "UTC",
        "bortle": None,
    }
    cleaned, error = _locations_mod._validate_location_payload(payload, partial=False)
    assert error is None
    assert "bortle" in cleaned and cleaned["bortle"] is None


def test_get_combinations_merges_share_status(client_admin, monkeypatch):
    monkeypatch.setattr(
        _app_mod.equipment_profiles,
        "load_user_combinations",
        lambda _uid: {"items": [{"id": "c1", "name": "Combo"}], "created_at": "x", "updated_at": "y"},
    )
    monkeypatch.setattr(
        _app_mod.equipment_profiles,
        "compute_combination_share_status",
        lambda combo, _uid, _index=None: {"is_shared": combo.get("id") == "c1", "shared_scope": "private"},
    )
    monkeypatch.setattr(_app_mod.equipment_profiles, "load_all_shared_combinations", lambda _uid: [])

    resp = client_admin.get("/api/equipment/combinations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"][0]["is_shared"] is True


def test_astrodex_count_pictures_returns_zero_when_dir_missing(monkeypatch):
    from observation import astrodex

    monkeypatch.setattr(astrodex, "ASTRODEX_DIR", os.path.join(tempfile.gettempdir(), "missing-astrodex-dir"))
    assert astrodex.count_pictures_for_location("loc-1") == 0


def test_plan_safe_path_rejects_path_outside_plan_dir():
    from observation import plan_my_night

    with pytest.raises(ValueError):
        plan_my_night._safe_plan_path("D:/not-important.json")


def test_iter_all_plan_files_skips_valueerror(monkeypatch):
    from observation import plan_my_night

    monkeypatch.setattr(plan_my_night, "ensure_plan_directory", lambda: None)
    monkeypatch.setattr(plan_my_night.os, "listdir", lambda _p: ["ok.json"])
    monkeypatch.setattr(plan_my_night, "_safe_plan_path", lambda _p: (_ for _ in ()).throw(ValueError()))
    assert plan_my_night._iter_all_plan_files() == []


def test_repo_config_get_scheduler_locations_import_failure_falls_back(monkeypatch):
    from utils import repo_config

    cfg = {
        "locations": [
            {"id": "default", "is_install_default": True},
            {"id": "other", "is_install_default": False},
        ]
    }

    real_import = __import__

    def _mock_import(name, *args, **kwargs):
        if name == "utils.auth":
            raise ImportError("forced")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _mock_import)
    scheduled = repo_config.get_scheduler_locations(cfg)
    assert [loc["id"] for loc in scheduled] == ["default"]


def test_cache_store_default_status_location_ids_handles_exception(monkeypatch):
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cache_store._default_status_location_ids() == []


def test_cache_store_default_status_location_ids_falls_through_when_no_ids(monkeypatch):
    """No exception, but every scheduler location lacks a truthy id -> falls
    through the `if ids:` check to the trailing `return []` (not the except arc)."""
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: {})
    monkeypatch.setattr("utils.repo_config.get_scheduler_locations", lambda config: [{'name': 'no-id-here'}])
    assert cache_store._default_status_location_ids() == []


def test_cache_store_allsky_job_availability_handles_exception(monkeypatch):
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cache_store._allsky_job_availability() == (False, False)


def test_skytonight_alttime_path_escape_returns_400(client_admin, monkeypatch):
    """_alttime_json_path resolving outside OUTPUT_DIR is rejected by the
    realpath + startswith confinement guard (the pattern CodeQL's
    py/path-injection query recognises as a sanitizer barrier)."""
    from blueprints import skytonight_api

    monkeypatch.setattr(skytonight_api, "_alttime_json_path", lambda *_a, **_k: "/definitely/outside/output_dir.json")
    resp = client_admin.get("/api/skytonight/alttime/valid_target")
    assert resp.status_code == 400


def test_auth_delete_user_cleans_up_astrodex_files_and_images(tmp_path, monkeypatch):
    from utils import auth

    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", str(users_file))
    manager = auth.UserManager()
    admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
    user = manager.create_user("cov_user", "pw", auth.ROLE_USER)

    astrodex_dir = tmp_path / "astrodex"
    images_dir = tmp_path / "astrodex_images"
    astrodex_dir.mkdir()
    images_dir.mkdir()

    monkeypatch.setattr("observation.astrodex.ASTRODEX_DIR", str(astrodex_dir))
    monkeypatch.setattr("observation.astrodex.ASTRODEX_IMAGES_DIR", str(images_dir))

    astrodex_payload = {
        "items": [{"pictures": [{"filename": f"{user.user_id}_img.jpg"}]}]
    }
    (astrodex_dir / f"{user.user_id}_astrodex.json").write_text(json.dumps(astrodex_payload), encoding="utf-8")
    (images_dir / f"{user.user_id}_img.jpg").write_bytes(b"x")
    (images_dir / f"{user.user_id}_other.jpg").write_bytes(b"y")

    manager.delete_user(user.user_id, current_user_id=admin.user_id)
    assert manager.get_user_by_id(user.user_id) is None
    assert not (astrodex_dir / f"{user.user_id}_astrodex.json").exists()
    assert not (images_dir / f"{user.user_id}_img.jpg").exists()
    assert not (images_dir / f"{user.user_id}_other.jpg").exists()


def test_cache_updater_masked_location_log_safe_coord_exceptions():
    from cache import cache_updater

    masked = cache_updater._masked_location_log({"latitude": "x", "longitude": object()})
    assert "lat=?" in masked and "lon=?" in masked


def test_update_allsky_sensor_cache_paths(monkeypatch):
    from cache import cache_updater
    from cache import cache_store

    fake_connector = types.SimpleNamespace(
        AllSkyConnector=lambda _cfg: types.SimpleNamespace(fetch_sensor_data=lambda: {"temp": 1})
    )
    with patch.dict("sys.modules", {"connectors.allsky_connector": fake_connector}):
        cache_store._allsky_sensor_cache = {"data": None, "timestamp": 0}
        cache_updater.update_allsky_sensor_cache(
            {
                "connectors": {
                    "allsky": {
                        "enabled": True,
                        "url": "http://x",
                        "modules": {"sensor_data": {"enabled": True}},
                    }
                }
            }
        )
        assert cache_store._allsky_sensor_cache["data"] == {"temp": 1}


def test_update_allsky_sensor_cache_none_config_and_early_returns(monkeypatch):
    from cache import cache_updater

    monkeypatch.setattr(cache_updater, "load_config", lambda: {"connectors": {"allsky": {"enabled": False}}})
    cache_updater.update_allsky_sensor_cache()

    cache_updater.update_allsky_sensor_cache({"connectors": {"allsky": {"enabled": True, "url": "http://x"}}})


def test_update_allsky_health_cache_paths(monkeypatch):
    from cache import cache_updater
    from cache import cache_store

    fake_connector = types.SimpleNamespace(
        AllSkyConnector=lambda _cfg: types.SimpleNamespace(health_check=lambda: {"ok": True})
    )
    with patch.dict("sys.modules", {"connectors.allsky_connector": fake_connector}):
        cache_store._allsky_health_cache = {"data": None, "timestamp": 0}
        cache_updater.update_allsky_health_cache(
            {"connectors": {"allsky": {"enabled": True, "url": "http://x", "modules": {}}}}
        )
        assert cache_store._allsky_health_cache["data"] == {"ok": True}


def test_update_allsky_health_cache_none_config_and_early_return(monkeypatch):
    from cache import cache_updater

    monkeypatch.setattr(cache_updater, "load_config", lambda: {"connectors": {"allsky": {"enabled": False}}})
    cache_updater.update_allsky_health_cache()

    cache_updater.update_allsky_health_cache({"connectors": {"allsky": {"enabled": True}}})


@pytest.mark.parametrize(
    "fn_name",
    [
        "update_moon_planner_cache",
        "update_sun_report_cache",
        "update_best_window_cache",
        "update_solar_eclipse_cache",
        "update_lunar_eclipse_cache",
        "update_horizon_graph_cache",
        "update_aurora_cache",
        "update_iss_passes_cache",
        "update_planetary_events_cache",
        "update_special_phenomena_cache",
        "update_solar_system_events_cache",
        "update_sidereal_time_cache",
        "update_seeing_forecast_cache",
    ],
)
def test_cache_updater_config_provided_branch_calls_resolve(monkeypatch, fn_name):
    from cache import cache_updater

    fn = getattr(cache_updater, fn_name)
    monkeypatch.setattr(
        cache_updater,
        "_resolve_job_location",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("stop after resolve call")),
    )
    fn(config={"locations": [{"id": "dflt", "is_install_default": True}]})


def test_check_and_handle_config_changes_no_legacy_signature_migrates(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.pop_legacy_location_signature.return_value = None
    mock_cs.is_location_tracked.return_value = True
    mock_cs.has_location_changed.return_value = False

    monkeypatch.setitem(cache_updater._legacy_cache_migration_state, "done", False)
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {"locations": [{"id": "dflt", "is_install_default": True}]},
    )

    cache_updater.check_and_handle_config_changes()
    mock_cs.migrate_legacy_cache_keys.assert_called_once_with("dflt")


def test_fully_initialize_caches_multi_location_labels_and_missing_id(monkeypatch):
    from cache import cache_updater

    calls = []

    def _job(config=None, location=None):
        calls.append(location.get("id"))

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": None, "timestamp": 0}
    mock_cs.is_cache_valid_for_today.return_value = False
    mock_cs.is_cache_valid.side_effect = lambda entry, _ttl: entry is not mock_cs._iers_cache
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": None, "timestamp": 0}
    mock_cs._allsky_sensor_cache = {"data": None, "timestamp": 0}
    mock_cs._allsky_health_cache = {"data": None, "timestamp": 0}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {
            "locations": [
                {"id": "dflt", "name": "Default", "is_install_default": True},
                {"id": None, "name": "NoId", "is_install_default": False},
                {"id": "other", "name": "Second Site", "is_install_default": False},
            ],
            "connectors": {
                "allsky": {
                    "enabled": True,
                    "url": "http://x",
                    "modules": {"sensor_data": {"enabled": True}},
                }
            },
        },
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "slugify_location_name", lambda s: s.lower().replace(" ", "-"))
    monkeypatch.setattr(cache_updater, "update_iers_cache", lambda: None)
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", (("moon_report", "moon_report", "_cov_job", 1, True),))
    monkeypatch.setattr(cache_updater, "_PARALLELIZABLE_JOBS", {"iers"})
    monkeypatch.setattr(cache_updater, "_cov_job", _job, raising=False)

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    assert calls == ["dflt", "other"]
    labels = [c.args[0] for c in mock_cs.record_cache_execution.call_args_list]
    assert any(label.startswith("moon_report@") for label in labels)


def test_fully_initialize_caches_preparallel_iers_failure(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": {}, "timestamp": 1}
    mock_cs.is_cache_valid_for_today.return_value = True
    mock_cs.is_cache_valid.side_effect = lambda entry, _ttl: entry is not mock_cs._iers_cache
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": None, "timestamp": 0}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(cache_updater, "load_config", lambda: {"locations": [{"id": "dflt", "is_install_default": True}]})
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", ())
    monkeypatch.setattr(cache_updater, "_PARALLELIZABLE_JOBS", {"iers"})
    monkeypatch.setattr(cache_updater, "update_iers_cache", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    flags = [c.args[2] for c in mock_cs.record_cache_execution.call_args_list if c.args and c.args[0] == "iers"]
    assert False in flags


def test_fully_initialize_caches_allsky_enabled_without_sensor_module(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": {}, "timestamp": 1}
    mock_cs.is_cache_valid_for_today.return_value = True
    mock_cs.is_cache_valid.return_value = True
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": {}, "timestamp": 1}
    mock_cs._allsky_sensor_cache = {"data": {}, "timestamp": 1}
    mock_cs._allsky_health_cache = {"data": {}, "timestamp": 1}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {
            "locations": [{"id": "dflt", "is_install_default": True}],
            "connectors": {"allsky": {"enabled": True, "url": "http://x", "modules": {}}},
        },
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", ())

    cache_updater.fully_initialize_caches()


def test_fully_initialize_caches_iers_absent_but_not_in_parallel(monkeypatch):
    from cache import cache_updater

    called = []

    def _aurora_job(config=None, location=None):
        called.append(location.get("id"))

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": None, "timestamp": 0}
    mock_cs.is_cache_valid_for_today.return_value = False
    mock_cs.is_cache_valid.return_value = True
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": {}, "timestamp": 1}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {"locations": [{"id": "dflt", "is_install_default": True}]},
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", (("aurora", "aurora", "_cov_aurora", 1, True),))
    monkeypatch.setattr(cache_updater, "_cov_aurora", _aurora_job, raising=False)

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    assert called == ["dflt"]


def test_run_calculations_bortle_to_sqm_and_invalid_bortle(monkeypatch):
    from skytonight import skytonight_calculator as calc

    monkeypatch.setattr(calc, "ensure_skytonight_directories", lambda: None)
    monkeypatch.setattr(calc, "save_json_file", lambda *_a, **_k: None)
    monkeypatch.setattr(calc, "_get_night_window", lambda *_a, **_k: None)

    with patch("weather.sky_quality.bortle_to_sqm", return_value=21.2) as mock_conv:
        calc.run_calculations(
            {
                "locations": [
                    {
                        "id": "dflt",
                        "is_install_default": True,
                        "latitude": 1,
                        "longitude": 2,
                        "elevation": 0,
                        "timezone": "UTC",
                        "name": "x",
                        "bortle": 4,
                        "sqm": None,
                    }
                ],
                "skytonight": {},
            }
        )
        assert mock_conv.called

    result = calc.run_calculations(
        {
            "locations": [
                {
                    "id": "dflt",
                    "is_install_default": True,
                    "latitude": 1,
                    "longitude": 2,
                    "elevation": 0,
                    "timezone": "UTC",
                    "name": "x",
                    "bortle": "bad",
                    "sqm": None,
                }
            ],
            "skytonight": {},
        }
    )
    assert isinstance(result, dict)


def test_run_calculations_sqm_parse_success_and_failure(monkeypatch):
    from skytonight import skytonight_calculator as calc

    monkeypatch.setattr(calc, "ensure_skytonight_directories", lambda: None)
    monkeypatch.setattr(calc, "save_json_file", lambda *_a, **_k: None)
    monkeypatch.setattr(calc, "_get_night_window", lambda *_a, **_k: None)

    base_location = {
        "id": "dflt",
        "is_install_default": True,
        "latitude": 1,
        "longitude": 2,
        "elevation": 0,
        "timezone": "UTC",
        "name": "x",
        "bortle": None,
    }

    ok = dict(base_location)
    ok["sqm"] = "21.8"
    bad = dict(base_location)
    bad["sqm"] = "not-a-number"

    out1 = calc.run_calculations({"locations": [ok], "skytonight": {}})
    out2 = calc.run_calculations({"locations": [bad], "skytonight": {}})
    assert isinstance(out1, dict)
    assert isinstance(out2, dict)


def test_push_scheduler_reuses_cached_location_payload_for_same_location(monkeypatch):
    from utils import push_scheduler

    load_calls = []

    monkeypatch.setattr(push_scheduler, "_pick_active_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n1_plan_start", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n2_next_target", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n7_aurora", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n6_darkness", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n3_iss", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n8_css", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n4_n5_eclipse", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_check_n9_solsys_window", lambda *_a, **_k: None)
    monkeypatch.setattr(push_scheduler, "_get_muted_location_ids", lambda _u: set())
    monkeypatch.setattr(push_scheduler, "_load_cache", lambda key: load_calls.append(key) or {})

    user1 = types.SimpleNamespace(
        user_id="u1",
        username="u1",
        preferences={"notifications": {"enabled": True}},
        push_subscriptions=[{"endpoint": "a"}],
    )
    user2 = types.SimpleNamespace(
        user_id="u2",
        username="u2",
        preferences={"notifications": {"enabled": True}},
        push_subscriptions=[{"endpoint": "b"}],
    )
    fake_um = types.SimpleNamespace(users={"u1": user1, "u2": user2}, _reload_users_if_changed=lambda: None)

    fake_auth = types.SimpleNamespace(user_manager=fake_um)
    fake_repo_config = types.SimpleNamespace(
        load_config=lambda: {},
        get_locations_for_user=lambda _cfg, _u: [{"id": "L1", "name": "Loc"}],
    )
    with patch.dict("sys.modules", {"utils.repo_config": fake_repo_config, "utils.auth": fake_auth}):
        push_scheduler._poll()

    # 7 per-location cache names should be loaded once for the shared location id.
    assert len(load_calls) == 7
