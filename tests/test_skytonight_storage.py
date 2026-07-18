"""
Tests for skytonight_storage.py
Covers directory creation, file helpers, and trimming.
"""

import os
import json
from unittest.mock import patch
from skytonight import skytonight_storage

ensure_skytonight_directories = skytonight_storage.ensure_skytonight_directories
get_location_directory = skytonight_storage.get_location_directory
get_dataset_file = skytonight_storage.get_dataset_file
get_results_file = skytonight_storage.get_results_file
get_scheduler_status_file = skytonight_storage.get_scheduler_status_file
get_scheduler_lock_file = skytonight_storage.get_scheduler_lock_file
get_scheduler_trigger_file = skytonight_storage.get_scheduler_trigger_file
load_scheduler_status = skytonight_storage.load_scheduler_status
save_scheduler_status = skytonight_storage.save_scheduler_status
append_scheduler_log = skytonight_storage.append_scheduler_log
_trim_log_file = skytonight_storage._trim_log_file
has_calculation_results = skytonight_storage.has_calculation_results
has_bodies_results = skytonight_storage.has_bodies_results
has_comets_results = skytonight_storage.has_comets_results
has_dso_results = skytonight_storage.has_dso_results


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


def _isolated_layout(tmp_path):
    """Patch the storage module onto a temp per-location layout."""
    return (
        patch.object(skytonight_storage, "SKYTONIGHT_CALCULATIONS_DIR", str(tmp_path / "calc")),
        patch.object(skytonight_storage, "SKYTONIGHT_OUTPUT_DIR", str(tmp_path / "outputs")),
    )


class TestHasResultsHelpers:
    """Tests for has_*_results helpers (per-location layout, v1.2)."""

    def test_has_calculation_results_false_when_file_missing(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert has_calculation_results("loc-missing") is False

    def test_has_bodies_results_false_when_file_missing(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert has_bodies_results("loc-missing") is False

    def test_has_comets_results_false_when_file_missing(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert has_comets_results("loc-missing") is False

    def test_has_dso_results_false_when_file_missing(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert has_dso_results("loc-missing") is False

    def test_has_calculation_results_true_when_valid_file(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            results_file = skytonight_storage.get_results_file("loc-1")
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump({"metadata": {"in_progress": False}}, f)
            assert has_calculation_results("loc-1") is True

    def test_has_calculation_results_false_when_in_progress(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            results_file = skytonight_storage.get_results_file("loc-2")
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump({"metadata": {"in_progress": True}}, f)
            assert has_calculation_results("loc-2") is False

    def test_results_are_isolated_between_locations(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            results_file = skytonight_storage.get_results_file("loc-a")
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump({"metadata": {"in_progress": False}}, f)
            assert has_calculation_results("loc-a") is True
            assert has_calculation_results("loc-b") is False


class TestPerLocationResultsLayout:
    """v1.2 per-location result directories: paths, migration, cleanup."""

    def test_result_file_paths_are_scoped_by_location_id(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert os.path.join("calc", "loc-a") in skytonight_storage.get_results_file("loc-a")
            assert skytonight_storage.get_dso_results_file("loc-a").endswith("dso_results.json")
            assert skytonight_storage.get_bodies_results_file("loc-a").endswith("bodies_results.json")
            assert skytonight_storage.get_comets_results_file("loc-a").endswith("comets_results.json")
            assert skytonight_storage.get_skymap_file("loc-a").endswith("skymap_data.json")

    def test_get_alttime_dir_scoped_and_created(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            path = skytonight_storage.get_alttime_dir("loc-x")
            assert os.path.isdir(path)
            assert os.path.basename(path) == "loc-x"

    def test_drop_location_results_removes_both_dirs(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            results_file = skytonight_storage.get_results_file("loc-drop")
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump({}, f)
            alttime_dir = skytonight_storage.get_alttime_dir("loc-drop")
            assert skytonight_storage.drop_location_results("loc-drop") is True
            assert not os.path.isdir(os.path.dirname(results_file))
            assert not os.path.isdir(alttime_dir)

    def test_drop_location_results_false_for_missing_or_empty_id(self, tmp_path):
        p1, p2 = _isolated_layout(tmp_path)
        with p1, p2:
            assert skytonight_storage.drop_location_results("never-existed") is False
            assert skytonight_storage.drop_location_results("") is False


class TestRemainingStorageGapArcs:
    """Targeted coverage for the last defensive/error-handling arcs."""

    def test_default_location_id_returns_none_on_exception(self, monkeypatch):
        from utils import repo_config

        def _raise():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(repo_config, "load_config", _raise)
        assert skytonight_storage._default_location_id() is None

    def test_drop_location_results_oserror_is_swallowed(self, tmp_path):
        calc_dir = tmp_path / "calc"
        out_dir = tmp_path / "outputs"
        (calc_dir / "loc-locked").mkdir(parents=True)
        out_dir.mkdir()

        with patch.object(skytonight_storage, "SKYTONIGHT_CALCULATIONS_DIR", str(calc_dir)), patch.object(
            skytonight_storage, "SKYTONIGHT_OUTPUT_DIR", str(out_dir)
        ), patch.object(skytonight_storage.shutil, "rmtree", side_effect=OSError("locked")):
            assert skytonight_storage.drop_location_results("loc-locked") is False


class TestAppendSchedulerLogNewlineBranch:
    """Tests for the message-ends-with-newline branch (line 91->93)."""

    def test_message_already_ends_with_newline_is_not_doubled(self, tmp_path):
        with patch.object(skytonight_storage, 'SKYTONIGHT_LOGS_DIR', str(tmp_path)):
            log_path = append_scheduler_log("already newline\n", file_name="nl_test.log")
        with open(log_path, encoding="utf-8") as file_obj:
            content = file_obj.read()
        assert content.count("\n") == 1


class TestTrimLogFileException:
    """Test that _trim_log_file silently handles unreadable files (lines 105-106)."""

    def test_trim_log_file_ignores_exception_on_missing_path(self):
        # FileNotFoundError when opening a non-existent path triggers except Exception: pass
        _trim_log_file("/nonexistent/path/that/does/not/exist.log", max_lines=5)
        # No exception raised = pass


class TestGetResultsFile:
    """Test get_results_file returns the expected path (lines 111-112)."""

    def test_get_results_file_returns_string(self):
        result = get_results_file()
        assert isinstance(result, str)
        assert len(result) > 0
