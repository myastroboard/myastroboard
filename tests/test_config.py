"""
Unit tests for configuration management (repo_config.py, config_defaults.py)
"""
import json
import os

import pytest

import repo_config
import config_defaults

load_config = repo_config.load_config
save_config = repo_config.save_config
_merge_defaults = repo_config._merge_defaults

DEFAULT_LOCATION = config_defaults.DEFAULT_LOCATION
DEFAULT_ASTRODEX = config_defaults.DEFAULT_ASTRODEX
DEFAULT_CONSTRAINTS = config_defaults.DEFAULT_CONSTRAINTS
DEFAULT_SKYTONIGHT = config_defaults.DEFAULT_SKYTONIGHT
DEFAULT_SKYTONIGHT_SCHEDULER = config_defaults.DEFAULT_SKYTONIGHT_SCHEDULER
DEFAULT_SKYTONIGHT_DATASETS = config_defaults.DEFAULT_SKYTONIGHT_DATASETS
DEFAULT_CONFIG = config_defaults.DEFAULT_CONFIG


def _set_config_file(monkeypatch, path):
    """Patch CONFIG_FILE in both constants and repo_config modules."""
    import constants
    monkeypatch.setattr(constants, "CONFIG_FILE", path)
    monkeypatch.setattr(repo_config, "CONFIG_FILE", path)


class TestDefaultConfig:
    """Test default configuration constants."""

    def test_default_location_structure(self):
        for key in ("name", "latitude", "longitude", "elevation", "timezone"):
            assert key in DEFAULT_LOCATION

    def test_default_location_values(self):
        assert isinstance(DEFAULT_LOCATION["name"], str)
        assert isinstance(DEFAULT_LOCATION["latitude"], (int, float))
        assert isinstance(DEFAULT_LOCATION["longitude"], (int, float))
        assert isinstance(DEFAULT_LOCATION["elevation"], (int, float))
        assert isinstance(DEFAULT_LOCATION["timezone"], str)
        assert -90 <= DEFAULT_LOCATION["latitude"] <= 90
        assert -180 <= DEFAULT_LOCATION["longitude"] <= 180

    def test_default_constraints_structure(self):
        expected = [
            "altitude_constraint_min",
            "altitude_constraint_max",
            "airmass_constraint",
            "size_constraint_min",
            "size_constraint_max",
            "moon_separation_min",
            "moon_separation_use_illumination",
            "fraction_of_time_observable_threshold",
            "north_to_east_ccw",
        ]
        for key in expected:
            assert key in DEFAULT_CONSTRAINTS, f"Missing constraint key: {key}"

    def test_default_constraints_valid_ranges(self):
        assert 0 <= DEFAULT_CONSTRAINTS["altitude_constraint_min"] <= 90
        assert 0 <= DEFAULT_CONSTRAINTS["altitude_constraint_max"] <= 90
        assert DEFAULT_CONSTRAINTS["altitude_constraint_min"] < DEFAULT_CONSTRAINTS["altitude_constraint_max"]
        assert DEFAULT_CONSTRAINTS["airmass_constraint"] > 0
        assert DEFAULT_CONSTRAINTS["size_constraint_min"] < DEFAULT_CONSTRAINTS["size_constraint_max"]
        assert 0 <= DEFAULT_CONSTRAINTS["moon_separation_min"] <= 180

    def test_default_skytonight_structure(self):
        assert DEFAULT_SKYTONIGHT["constraints_always_enabled"] is True
        for key in ("enabled", "constraints", "scheduler", "datasets", "preferred_name_order"):
            assert key in DEFAULT_SKYTONIGHT, f"Missing skytonight key: {key}"

    def test_default_skytonight_scheduler(self):
        sched = DEFAULT_SKYTONIGHT["scheduler"]
        assert sched["mode"] == "fallback-6h"
        assert "next_run" in sched
        assert "last_run" in sched

    def test_default_skytonight_datasets(self):
        ds = DEFAULT_SKYTONIGHT["datasets"]
        assert ds["catalogues"]["deep_sky"] is True
        assert ds["comets"]["source"] == "mpc+jpl"

    def test_default_skytonight_contains_constraints_copy(self):
        """constraints nested in skytonight must equal but be independent of DEFAULT_CONSTRAINTS."""
        assert DEFAULT_SKYTONIGHT["constraints"] == DEFAULT_CONSTRAINTS
        assert DEFAULT_SKYTONIGHT["constraints"] is not DEFAULT_CONSTRAINTS

    def test_default_config_top_level_keys(self):
        for key in ("location", "min_altitude", "astrodex", "skytonight"):
            assert key in DEFAULT_CONFIG, f"Missing key: {key}"

    def test_default_config_no_legacy_keys(self):
        """Keys removed in the config refactor must not appear in DEFAULT_CONFIG."""
        legacy = [
            "selected_catalogues", "use_constraints", "features",
            "constraints", "bucket_list", "done_list",
            "custom_targets", "horizon", "output_datestamp",
        ]
        for key in legacy:
            assert key not in DEFAULT_CONFIG, f"Legacy key still present: {key}"

    def test_default_config_references_other_defaults(self):
        assert DEFAULT_CONFIG["location"] == DEFAULT_LOCATION
        assert DEFAULT_CONFIG["astrodex"] == DEFAULT_ASTRODEX
        assert DEFAULT_CONFIG["skytonight"] == DEFAULT_SKYTONIGHT


class TestMergeDefaults:
    """Unit tests for the _merge_defaults helper."""

    def test_empty_config_gets_all_defaults(self):
        defaults = {"a": 1, "b": {"c": 2}}
        assert _merge_defaults({}, defaults) == defaults

    def test_existing_keys_are_preserved(self):
        result = _merge_defaults({"a": 99}, {"a": 1, "b": 2})
        assert result["a"] == 99
        assert result["b"] == 2

    def test_missing_keys_filled_from_defaults(self):
        result = _merge_defaults({"a": 10}, {"a": 1, "b": 2, "c": 3})
        assert result["b"] == 2
        assert result["c"] == 3

    def test_nested_dicts_merged_recursively(self):
        defaults = {"nested": {"x": 1, "y": 2}}
        result = _merge_defaults({"nested": {"x": 99}}, defaults)
        assert result["nested"]["x"] == 99
        assert result["nested"]["y"] == 2

    def test_non_dict_config_returns_copy_of_defaults(self):
        defaults = {"a": 1}
        assert _merge_defaults("not-a-dict", defaults) == defaults

    def test_non_dict_defaults_returns_copy_of_defaults(self):
        """When defaults itself is not a dict, a deepcopy of it is returned."""
        result = _merge_defaults({"a": 1}, "scalar-default")
        assert result == "scalar-default"

    def test_list_values_not_merged(self):
        """List values in config replace the default entirely."""
        defaults = {"items": [1, 2, 3]}
        assert _merge_defaults({"items": [4, 5]}, defaults)["items"] == [4, 5]

    def test_result_is_independent_copy(self):
        """Mutating the result must not affect the original defaults dict."""
        defaults = {"nested": {"a": 1}}
        result = _merge_defaults({}, defaults)
        result["nested"]["a"] = 999
        assert defaults["nested"]["a"] == 1


class TestConfigLoading:
    """Test load_config behavior."""

    def test_load_config_returns_dict(self):
        assert isinstance(load_config(), dict)

    def test_load_config_nonexistent_file_returns_defaults(self, temp_dir, monkeypatch):
        _set_config_file(monkeypatch, os.path.join(temp_dir, "nonexistent.json"))
        config = load_config()
        assert isinstance(config, dict)
        assert "location" in config
        assert "skytonight" in config

    def test_load_config_has_required_fields(self, temp_dir, monkeypatch):
        _set_config_file(monkeypatch, os.path.join(temp_dir, "required.json"))
        config = load_config()
        for field in ("location", "min_altitude", "astrodex", "skytonight"):
            assert field in config

    def test_load_config_strips_legacy_top_level_constraints(self, temp_dir, monkeypatch):
        """A file with a top-level 'constraints' key must have it removed on load."""
        path = os.path.join(temp_dir, "legacy.json")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump({"location": DEFAULT_LOCATION, "constraints": {"altitude_constraint_min": 20}}, fp)
        _set_config_file(monkeypatch, path)
        config = load_config()
        assert "constraints" not in config

    def test_load_config_merges_partial_skytonight(self, temp_dir, monkeypatch):
        """Partial skytonight blocks are completed with defaults on load."""
        path = os.path.join(temp_dir, "partial.json")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump({
                "location": {
                    "name": "Legacy", "latitude": 40.0, "longitude": -3.0,
                    "elevation": 100, "timezone": "Europe/Madrid",
                },
                "skytonight": {"constraints": {"altitude_constraint_min": 35}},
            }, fp)
        _set_config_file(monkeypatch, path)

        config = load_config()
        assert config["location"]["name"] == "Legacy"
        assert config["skytonight"]["constraints"]["altitude_constraint_min"] == 35
        assert config["skytonight"]["constraints"]["airmass_constraint"] == DEFAULT_CONSTRAINTS["airmass_constraint"]
        assert config["skytonight"]["scheduler"]["mode"] == "fallback-6h"
        assert "datasets" in config["skytonight"]

    def test_load_config_preserves_custom_location(self, temp_dir, monkeypatch):
        path = os.path.join(temp_dir, "custom_loc.json")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump({"location": {"name": "Tokyo", "latitude": 35.6, "longitude": 139.7, "elevation": 40, "timezone": "Asia/Tokyo"}}, fp)
        _set_config_file(monkeypatch, path)
        config = load_config()
        assert config["location"]["name"] == "Tokyo"
        assert config["location"]["latitude"] == 35.6


class TestConfigSaving:
    """Test save_config behavior."""

    def test_save_config_success(self, temp_dir, sample_config, monkeypatch):
        path = os.path.join(temp_dir, "saved.json")
        _set_config_file(monkeypatch, path)
        assert save_config(sample_config) is True
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as fp:
            assert json.load(fp) == sample_config

    def test_save_config_creates_parent_directory(self, temp_dir, sample_config, monkeypatch):
        path = os.path.join(temp_dir, "nested", "dir", "config.json")
        _set_config_file(monkeypatch, path)
        assert save_config(sample_config) is True
        assert os.path.exists(path)

    def test_save_and_load_roundtrip(self, temp_dir, sample_config, monkeypatch):
        path = os.path.join(temp_dir, "roundtrip.json")
        _set_config_file(monkeypatch, path)
        assert save_config(sample_config) is True
        loaded = load_config()
        assert loaded["location"] == sample_config["location"]
        assert loaded["min_altitude"] == sample_config["min_altitude"]
        assert loaded["skytonight"]["constraints"]["altitude_constraint_min"] == (
            sample_config["skytonight"]["constraints"]["altitude_constraint_min"]
        )
        assert "skytonight" in loaded

    def test_save_config_with_unicode(self, temp_dir, monkeypatch):
        path = os.path.join(temp_dir, "unicode.json")
        _set_config_file(monkeypatch, path)
        cfg = {"location": {"name": "Montréal", "latitude": 45.5, "longitude": -73.5, "elevation": 0, "timezone": "America/Montreal"}}
        assert save_config(cfg) is True
        assert load_config()["location"]["name"] == "Montréal"


class TestConfigIntegration:
    """Integration tests for config load/save cycle."""

    def test_modify_and_save_config(self, temp_dir, monkeypatch):
        _set_config_file(monkeypatch, os.path.join(temp_dir, "integration.json"))
        config = load_config()
        config["location"]["name"] = "Modified Location"
        config["min_altitude"] = 25
        save_config(config)
        reloaded = load_config()
        assert reloaded["location"]["name"] == "Modified Location"
        assert reloaded["min_altitude"] == 25

    def test_skytonight_constraints_survive_roundtrip(self, temp_dir, monkeypatch):
        _set_config_file(monkeypatch, os.path.join(temp_dir, "st_roundtrip.json"))
        config = load_config()
        config["skytonight"]["constraints"]["altitude_constraint_min"] = 42
        save_config(config)
        reloaded = load_config()
        assert reloaded["skytonight"]["constraints"]["altitude_constraint_min"] == 42
        assert "airmass_constraint" in reloaded["skytonight"]["constraints"]
