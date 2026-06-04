"""
Tests for skytonight_storage.py
Covers directory creation, file helpers, and trimming.
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch
from skytonight_storage import (
    ensure_skytonight_directories,
    get_location_directory,
    get_dataset_file,
    get_scheduler_status_file,
    get_scheduler_lock_file,
    get_scheduler_trigger_file,
    load_scheduler_status,
    save_scheduler_status,
    append_scheduler_log,
    _trim_log_file,
    has_calculation_results,
    has_bodies_results,
    has_comets_results,
    has_dso_results,
)


class TestEnsureSkytonigtDirectories:
    """Tests for ensure_skytonight_directories."""

    def test_returns_dict_with_required_keys(self):
        dirs = ensure_skytonight_directories()
        for key in ("root", "catalogues", "calculations", "outputs", "logs", "runtime"):
            assert key in dirs

    def test_creates_directories(self):
        dirs = ensure_skytonight_directories()
        for path in dirs.values():
            assert os.path.isdir(path)

    def test_with_location_name_adds_location_keys(self):
        dirs = ensure_skytonight_directories("TestLocation")
        assert "location" in dirs
        assert "location_logs" in dirs
        assert "location_outputs" in dirs
        assert "location_runtime" in dirs

    def test_location_directory_created(self):
        dirs = ensure_skytonight_directories("TestLoc2")
        assert os.path.isdir(dirs["location"])


class TestGetLocationDirectory:
    """Tests for get_location_directory slugification."""

    def test_simple_name(self):
        path = get_location_directory("Paris")
        assert "paris" in path.lower() or "Paris" in path

    def test_spaces_in_name_are_slugified(self):
        path = get_location_directory("New York")
        assert " " not in os.path.basename(path)


class TestGetSchedulerFiles:
    """Tests for file-path accessors."""

    def test_get_dataset_file_returns_string(self):
        result = get_dataset_file()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_scheduler_status_file_returns_string(self):
        result = get_scheduler_status_file()
        assert isinstance(result, str)

    def test_get_scheduler_lock_file_returns_string(self):
        result = get_scheduler_lock_file()
        assert isinstance(result, str)

    def test_get_scheduler_trigger_file_returns_string(self):
        result = get_scheduler_trigger_file()
        assert isinstance(result, str)


class TestLoadSaveSchedulerStatus:
    """Tests for load_scheduler_status / save_scheduler_status round-trip."""

    def test_load_returns_empty_dict_by_default(self):
        # Status file may or may not exist; result must be a dict
        result = load_scheduler_status()
        assert isinstance(result, dict)

    def test_save_and_load_roundtrip(self):
        payload = {"running": True, "mode": "test", "custom_key": 42}
        save_scheduler_status(payload)
        loaded = load_scheduler_status()
        assert loaded.get("running") is True
        assert loaded.get("custom_key") == 42


class TestAppendSchedulerLog:
    """Tests for append_scheduler_log and _trim_log_file."""

    def test_append_creates_log_file(self):
        log_path = append_scheduler_log("test entry", file_name="test_sched.log")
        assert os.path.isfile(log_path)

    def test_append_writes_content(self):
        log_path = append_scheduler_log("hello log", file_name="hello.log")
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "hello log" in content

    def test_trim_log_file_keeps_only_max_lines(self, tmp_path):
        log_file = tmp_path / "test.log"
        lines = [f"line{i}\n" for i in range(20)]
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_log_file(str(log_file), max_lines=5)
        result = log_file.read_text(encoding="utf-8").splitlines()
        assert len(result) == 5
        assert result[-1] == "line19"

    def test_trim_log_file_does_not_truncate_if_under_max(self, tmp_path):
        log_file = tmp_path / "trim_safe.log"
        lines = [f"line{i}\n" for i in range(3)]
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_log_file(str(log_file), max_lines=5)
        result = log_file.read_text(encoding="utf-8").splitlines()
        assert len(result) == 3


class TestHasResultsHelpers:
    """Tests for has_*_results helpers."""

    def test_has_calculation_results_false_when_file_missing(self):
        with patch("skytonight_storage.SKYTONIGHT_RESULTS_FILE", "/nonexistent/path/results.json"):
            assert has_calculation_results() is False

    def test_has_bodies_results_false_when_file_missing(self):
        with patch("skytonight_storage.SKYTONIGHT_BODIES_RESULTS_FILE", "/nonexistent/path/bodies.json"):
            assert has_bodies_results() is False

    def test_has_comets_results_false_when_file_missing(self):
        with patch("skytonight_storage.SKYTONIGHT_COMETS_RESULTS_FILE", "/nonexistent/path/comets.json"):
            assert has_comets_results() is False

    def test_has_dso_results_false_when_file_missing(self):
        with patch("skytonight_storage.SKYTONIGHT_DSO_RESULTS_FILE", "/nonexistent/path/dso.json"):
            assert has_dso_results() is False

    def test_has_calculation_results_true_when_valid_file(self, tmp_path):
        results_file = tmp_path / "results.json"
        results_file.write_text(json.dumps({"metadata": {"in_progress": False}}), encoding="utf-8")
        with patch("skytonight_storage.SKYTONIGHT_RESULTS_FILE", str(results_file)):
            assert has_calculation_results() is True

    def test_has_calculation_results_false_when_in_progress(self, tmp_path):
        results_file = tmp_path / "results_ip.json"
        results_file.write_text(json.dumps({"metadata": {"in_progress": True}}), encoding="utf-8")
        with patch("skytonight_storage.SKYTONIGHT_RESULTS_FILE", str(results_file)):
            assert has_calculation_results() is False
