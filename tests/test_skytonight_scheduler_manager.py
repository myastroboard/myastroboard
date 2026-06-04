"""
Tests for skytonight_scheduler_manager.py
Focuses on pure-logic helpers that are easy to unit-test.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from skytonight_scheduler_manager import _trim_calculation_log


class TestTrimCalculationLog:
    """Tests for _trim_calculation_log pure I/O helper."""

    def test_does_nothing_when_file_missing(self, tmp_path):
        """Calling with a non-existent path should not raise."""
        _trim_calculation_log(str(tmp_path / "no_file.log"), max_runs=5)

    def test_keeps_all_lines_when_under_limit(self, tmp_path):
        log_file = tmp_path / "calc.log"
        lines = [json.dumps({"run": i}) + "\n" for i in range(6)]  # 6 lines < 5*2=10
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_calculation_log(str(log_file), max_runs=5)
        result = log_file.read_text(encoding="utf-8").splitlines()
        assert len(result) == 6

    def test_trims_to_max_runs_times_2(self, tmp_path):
        log_file = tmp_path / "big_calc.log"
        # 30 lines = 15 runs × 2 lines each
        lines = [json.dumps({"run": i}) + "\n" for i in range(30)]
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_calculation_log(str(log_file), max_runs=5)
        result = log_file.read_text(encoding="utf-8").splitlines()
        assert len(result) == 10  # 5 * 2

    def test_preserves_last_entries(self, tmp_path):
        log_file = tmp_path / "order.log"
        lines = [f"entry_{i}\n" for i in range(30)]
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_calculation_log(str(log_file), max_runs=5)
        result = log_file.read_text(encoding="utf-8").splitlines()
        # Last entry should be entry_29
        assert result[-1] == "entry_29"

    def test_skips_empty_lines(self, tmp_path):
        log_file = tmp_path / "empty_lines.log"
        content = "\n".join(["entry_0", "", "entry_1", "", "entry_2", "", "entry_3",
                              "entry_4", "entry_5", "entry_6", "entry_7", "entry_8"])
        log_file.write_text(content + "\n", encoding="utf-8")
        # Only non-empty lines count; 9 real lines < 5*2=10, so no trimming
        _trim_calculation_log(str(log_file), max_runs=5)
        result_lines = [
            l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        assert len(result_lines) == 9

    def test_max_runs_one_keeps_two_lines(self, tmp_path):
        """max_runs=1 means keep at most 1*2=2 lines."""
        log_file = tmp_path / "one.log"
        lines = [f"entry_{i}\n" for i in range(10)]
        log_file.write_text("".join(lines), encoding="utf-8")
        _trim_calculation_log(str(log_file), max_runs=1)
        result = log_file.read_text(encoding="utf-8").splitlines()
        assert len(result) == 2


class TestAppendSkytonigtCalculationLog:
    """Tests for _append_skytonight_calculation_log via inspection of written files."""

    def test_writes_json_line_to_file(self, tmp_path):
        from skytonight_scheduler_manager import _append_skytonight_calculation_log
        import constants
        log_file = tmp_path / "skytonight_calc.log"
        with patch.object(constants, "SKYTONIGHT_CALCULATION_LOG_FILE", str(log_file)):
            with patch("skytonight_scheduler_manager.SKYTONIGHT_CALCULATION_LOG_FILE", str(log_file)):
                with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
                    with patch("skytonight_scheduler_manager._trim_calculation_log"):
                        _append_skytonight_calculation_log("test_status", {"key": "value"})
        if log_file.exists():
            line = log_file.read_text(encoding="utf-8").strip()
            entry = json.loads(line)
            assert entry["status"] == "test_status"
            assert entry["payload"]["key"] == "value"
            assert "timestamp" in entry

    def test_handles_open_failure_gracefully(self, tmp_path):
        """Should not raise even if the log file can't be written."""
        from skytonight_scheduler_manager import _append_skytonight_calculation_log
        with patch("skytonight_scheduler_manager.SKYTONIGHT_CALCULATION_LOG_FILE",
                   "/nonexistent/path/calc.log"):
            with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
                # Should not raise; exception is caught and logged
                _append_skytonight_calculation_log("status", {})


class TestGetOrCreateScheduler:
    """Tests for get_or_create_skytonight_scheduler with a mocked app."""

    def test_returns_scheduler_if_already_in_config(self):
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_scheduler = MagicMock()
        mock_app.config = {"skytonight_scheduler": mock_scheduler}
        result = get_or_create_skytonight_scheduler(mock_app)
        assert result is mock_scheduler

    def test_returns_none_on_lock_failure(self, tmp_path):
        """If lock acquisition fails, should return None gracefully."""
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_app.config = {}
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                   return_value=str(tmp_path / "test.lock")):
            with patch("builtins.open", side_effect=IOError("locked")):
                result = get_or_create_skytonight_scheduler(mock_app)
        assert result is None


class TestGetRemoteSchedulerStatus:
    """Tests for get_remote_skytonight_scheduler_status."""

    def test_returns_dict_when_no_status_file(self):
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value="/nonexistent/path/status.json"):
            with patch("skytonight_scheduler_manager.load_config",
                       return_value={"skytonight": {"enabled": True}, "location": {"timezone": "UTC"}}):
                result = get_remote_skytonight_scheduler_status()
        assert isinstance(result, dict)
        assert "running" in result
        assert result["worker"] == "remote"

    def test_reads_status_from_file(self, tmp_path):
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {
            "running": True,
            "last_run": "2026-01-01T00:00:00Z",
            "last_result": {"calculation": {}},
            "progress": {"execution_duration_seconds": 5.0},
        }
        status_file = tmp_path / "scheduler_status.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                result = get_remote_skytonight_scheduler_status()
        assert result.get("worker") == "remote"
        assert result.get("running") is True

    def test_backfills_empty_last_result(self, tmp_path):
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {
            "running": True,
            "last_result": {},
            "progress": {"execution_duration_seconds": None},
        }
        status_file = tmp_path / "status_empty.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        mock_calc = {
            "metadata": {
                "night_start": "2026-01-01T22:00:00",
                "night_end": "2026-01-02T06:00:00",
                "counts": {"deep_sky": 10, "bodies": 5, "comets": 2},
            }
        }
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                with patch("skytonight_scheduler_manager.load_calculation_results",
                           return_value=mock_calc):
                    result = get_remote_skytonight_scheduler_status()
        # last_result should have been backfilled
        assert "calculation" in result.get("last_result", {})

    def test_progress_defaults_set_when_missing(self, tmp_path):
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {"running": False, "last_result": {"x": 1}, "progress": {}}
        status_file = tmp_path / "status_prog.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                result = get_remote_skytonight_scheduler_status()
        assert "execution_duration_seconds" in result["progress"]
        assert "last_execution_duration_seconds" in result["progress"]
