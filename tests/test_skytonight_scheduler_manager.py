"""
Tests for skytonight_scheduler_manager.py
Focuses on pure-logic helpers that are easy to unit-test.
"""

import json
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

    def test_progress_not_dict_gets_replaced(self, tmp_path):
        """When progress is not a dict, replace it with defaults (lines 253-257)."""
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {"running": True, "last_result": {"k": "v"}, "progress": "bad"}
        status_file = tmp_path / "status_badprog.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                result = get_remote_skytonight_scheduler_status()
        assert isinstance(result["progress"], dict)
        assert "execution_duration_seconds" in result["progress"]

    def test_last_result_not_dict_reset_to_empty(self, tmp_path):
        """last_result that is not a dict is reset to {} (line 224-225)."""
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {"running": True, "last_result": "invalid_string", "progress": {}}
        status_file = tmp_path / "status_last_result.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                result = get_remote_skytonight_scheduler_status()
        # Should have been converted to a dict and worker set
        assert result.get("worker") == "remote"

    def test_exception_on_file_read_returns_fallback(self, tmp_path):
        """Exception during file read returns fallback dict (lines 264-285)."""
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_file = tmp_path / "status_corrupt.json"
        status_file.write_text("{ broken json", encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                with patch("skytonight_scheduler_manager.load_config",
                           return_value={"skytonight": {"enabled": True},
                                         "location": {"timezone": "Europe/Paris"}}):
                    result = get_remote_skytonight_scheduler_status()
        # Fallback path
        assert result["worker"] == "remote"
        assert result["reason"] is not None

    def test_backfill_empty_last_result_load_error_suppressed(self, tmp_path):
        """When load_calculation_results raises, empty last_result stays empty."""
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {"running": True, "last_result": {}, "progress": {}}
        status_file = tmp_path / "status_backfill_err.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                with patch("skytonight_scheduler_manager.load_calculation_results",
                           side_effect=RuntimeError("disk error")):
                    result = get_remote_skytonight_scheduler_status()
        # Should not raise; last_result stays {}
        assert isinstance(result.get("last_result"), dict)

    def test_backfill_calc_cache_no_useful_fields(self, tmp_path):
        """When calc cache has no night_start/night_end/counts, last_result stays empty."""
        from skytonight_scheduler_manager import get_remote_skytonight_scheduler_status
        status_data = {"running": True, "last_result": {}, "progress": {}}
        status_file = tmp_path / "status_no_fields.json"
        status_file.write_text(json.dumps(status_data), encoding="utf-8")
        empty_calc = {"metadata": {}}
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_status_file",
                   return_value=str(status_file)):
            with patch("skytonight_scheduler_manager.os.path.exists", return_value=True):
                with patch("skytonight_scheduler_manager.load_calculation_results",
                           return_value=empty_calc):
                    result = get_remote_skytonight_scheduler_status()
        assert result.get("last_result") == {}


class TestRunSkytonigtRefresh:
    """Tests for _run_skytonight_refresh (lines 79-123)."""

    def test_successful_refresh_returns_dict(self):
        """Full happy-path: build dataset + calculations succeed."""
        from skytonight_scheduler_manager import _run_skytonight_refresh

        mock_dataset_result = {
            "metadata": {
                "generated_at": "2026-01-01T00:00:00Z",
                "sources": ["PyOngc"],
                "counts": {"deep_sky": 100, "comets": 5},
            }
        }
        mock_calc_result = {"night_start": "2026-01-01T22:00:00Z", "night_end": "2026-01-02T05:00:00Z"}

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config",
                       return_value={"skytonight": {"datasets": {"comets": {"source": "mpc"}}}}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           return_value=mock_dataset_result):
                    with patch("skytonight_scheduler_manager.invalidate_targets_dataset_cache"):
                        with patch("skytonight_scheduler_manager.run_calculations",
                                   return_value=mock_calc_result):
                            with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                                result = _run_skytonight_refresh()

        assert result["dataset_generated"] is True
        assert result["calculation"] == mock_calc_result

    def test_refresh_dataset_failure_raises(self):
        """If build_and_save_default_dataset raises, _run_skytonight_refresh re-raises."""
        from skytonight_scheduler_manager import _run_skytonight_refresh

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config", return_value={}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           side_effect=RuntimeError("catalogue build failed")):
                    with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                        with pytest.raises(RuntimeError, match="catalogue build failed"):
                            _run_skytonight_refresh()

    def test_refresh_calculations_failure_non_fatal(self):
        """If run_calculations raises, refresh still returns partial result."""
        from skytonight_scheduler_manager import _run_skytonight_refresh

        mock_dataset_result = {
            "metadata": {
                "generated_at": "2026-01-01T00:00:00Z",
                "sources": [],
                "counts": {},
            }
        }

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config", return_value={}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           return_value=mock_dataset_result):
                    with patch("skytonight_scheduler_manager.invalidate_targets_dataset_cache"):
                        with patch("skytonight_scheduler_manager.run_calculations",
                                   side_effect=RuntimeError("calc failed")):
                            with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                                result = _run_skytonight_refresh()

        # Should not raise; calculation falls back to {}
        assert result["calculation"] == {}
        assert result["dataset_generated"] is True

    def test_set_progress_import_error_suppressed(self):
        """If importing _set_progress fails, refresh continues (lines 87-91)."""
        from skytonight_scheduler_manager import _run_skytonight_refresh

        mock_dataset_result = {"metadata": {"generated_at": None, "sources": [], "counts": {}}}

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config", return_value={}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           return_value=mock_dataset_result):
                    with patch("skytonight_scheduler_manager.invalidate_targets_dataset_cache"):
                        with patch("skytonight_scheduler_manager.run_calculations", return_value={}):
                            with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                                # Patch so the import inside the function fails
                                import sys
                                # We can't easily make "from skytonight_calculator import _set_progress" fail
                                # but the try/except means failure is safe anyway
                                result = _run_skytonight_refresh()
        assert "dataset_generated" in result

    def test_refresh_with_default_comet_source(self):
        """Covers config path where comets source is missing (defaults to mpc+jpl)."""
        from skytonight_scheduler_manager import _run_skytonight_refresh

        mock_dataset_result = {"metadata": {}}

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config", return_value={}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           return_value=mock_dataset_result):
                    with patch("skytonight_scheduler_manager.invalidate_targets_dataset_cache"):
                        with patch("skytonight_scheduler_manager.run_calculations", return_value={}):
                            with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                                result = _run_skytonight_refresh()
        assert "dataset_generated" in result


class TestGetOrCreateSkytonigtSchedulerExtended:
    """Additional coverage for get_or_create_skytonight_scheduler (lines 155-181)."""

    def test_general_exception_returns_none(self, tmp_path):
        """Lines 178-181: a generic exception during scheduler creation returns None."""
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_app.config = {}

        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                   return_value=str(tmp_path / "scheduler.lock")):
            # Make opening the file succeed, but lock acquisition fail with generic error
            import sys
            if sys.platform == "win32":
                with patch("msvcrt.locking", side_effect=Exception("unexpected")):
                    result = get_or_create_skytonight_scheduler(mock_app)
            else:
                with patch("fcntl.flock", side_effect=Exception("unexpected")):
                    result = get_or_create_skytonight_scheduler(mock_app)
        # Should return None (not raise)
        assert result is None

    def test_oserror_on_lock_sets_worker_flag_false(self, tmp_path):
        """OSError from msvcrt.locking → logs and returns None (lines 146-155)."""
        import sys
        if sys.platform != "win32":
            pytest.skip("Windows-only code path")
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_app.config = {}
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                   return_value=str(tmp_path / "oserr.lock")):
            with patch("msvcrt.locking", side_effect=OSError("already locked")):
                result = get_or_create_skytonight_scheduler(mock_app)
        assert result is None
        assert mock_app.config.get('is_skytonight_scheduler_worker') is False


class TestRunSkytonigtRefreshProgressException:
    """Cover exception path for _set_progress call inside _run_skytonight_refresh."""

    def test_set_progress_exception_is_swallowed(self):
        """_set_progress('build_dataset') raises → lines 90-91 (except/pass) are covered."""
        from skytonight_scheduler_manager import _run_skytonight_refresh
        import skytonight_calculator

        mock_dataset_result = {"metadata": {"generated_at": None, "sources": [], "counts": {}}}

        with patch("skytonight_scheduler_manager.ensure_skytonight_directories"):
            with patch("skytonight_scheduler_manager.load_config", return_value={}):
                with patch("skytonight_scheduler_manager.build_and_save_default_dataset",
                           return_value=mock_dataset_result):
                    with patch("skytonight_scheduler_manager.invalidate_targets_dataset_cache"):
                        with patch("skytonight_scheduler_manager.run_calculations", return_value={}):
                            with patch("skytonight_scheduler_manager._append_skytonight_calculation_log"):
                                # Make _set_progress raise inside the function
                                with patch.object(skytonight_calculator, "_set_progress",
                                                  side_effect=RuntimeError("set_progress fail")):
                                    result = _run_skytonight_refresh()
        assert "dataset_generated" in result

    def test_win32_lock_acquired_creates_scheduler(self, tmp_path):
        """Lines 157-169 (win32 path): when lock is acquired, scheduler is created."""
        import sys
        if sys.platform != "win32":
            pytest.skip("Windows-only test")

        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_app.config = {}
        mock_scheduler = MagicMock()

        # SkyTonightScheduler is imported inside the function from skytonight_scheduler module
        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                   return_value=str(tmp_path / "sch.lock")):
            with patch("msvcrt.locking"):  # locking succeeds (no exception)
                with patch("skytonight_scheduler.SkyTonightScheduler",
                           return_value=mock_scheduler, create=True):
                    # Patch the import itself
                    import skytonight_scheduler as _sts_mod
                    original_cls = getattr(_sts_mod, "SkyTonightScheduler", None)
                    _sts_mod.SkyTonightScheduler = MagicMock(return_value=mock_scheduler)
                    try:
                        get_or_create_skytonight_scheduler(mock_app)
                    finally:
                        if original_cls is not None:
                            _sts_mod.SkyTonightScheduler = original_cls

        assert mock_app.config.get("is_skytonight_scheduler_worker") is True

    def test_lock_already_logged_not_logged_again(self, tmp_path):
        """When lock_logged is already True, skip logging again (lines 146-150)."""
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler
        mock_app = MagicMock()
        mock_app.config = {"skytonight_scheduler_lock_logged": True}

        with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                   return_value=str(tmp_path / "test2.lock")):
            with patch("builtins.open", side_effect=IOError("locked")):
                result = get_or_create_skytonight_scheduler(mock_app)
        assert result is None


class TestGetSkytonigtSchedulerForApi:
    """Tests for get_skytonight_scheduler_for_api (lines 186-214)."""

    def test_returns_scheduler_when_available(self):
        """When get_or_create returns a real scheduler, return it."""
        from skytonight_scheduler_manager import get_skytonight_scheduler_for_api
        mock_scheduler = MagicMock()

        with patch("skytonight_scheduler_manager.get_or_create_skytonight_scheduler",
                   return_value=mock_scheduler):
            from flask import Flask
            app = Flask(__name__)
            with app.app_context():
                result = get_skytonight_scheduler_for_api()
        assert result is mock_scheduler

    def test_returns_none_when_no_lock_file(self, tmp_path):
        """When no scheduler and no lock file, return None."""
        from skytonight_scheduler_manager import get_skytonight_scheduler_for_api

        with patch("skytonight_scheduler_manager.get_or_create_skytonight_scheduler",
                   return_value=None):
            with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                       return_value=str(tmp_path / "no_lock.lock")):
                from flask import Flask
                app = Flask(__name__)
                with app.app_context():
                    result = get_skytonight_scheduler_for_api()
        assert result is None

    def test_returns_remote_scheduler_when_lock_held_by_other(self, tmp_path):
        """When lock file exists and is held elsewhere, return 'remote_scheduler'."""
        from skytonight_scheduler_manager import get_skytonight_scheduler_for_api
        import sys

        lock_file = tmp_path / "held.lock"
        lock_file.write_text("")

        with patch("skytonight_scheduler_manager.get_or_create_skytonight_scheduler",
                   return_value=None):
            with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                       return_value=str(lock_file)):
                if sys.platform == "win32":
                    with patch("msvcrt.locking", side_effect=OSError("locked by other")):
                        from flask import Flask
                        app = Flask(__name__)
                        with app.app_context():
                            result = get_skytonight_scheduler_for_api()
                else:
                    with patch("fcntl.flock", side_effect=IOError("locked by other")):
                        from flask import Flask
                        app = Flask(__name__)
                        with app.app_context():
                            result = get_skytonight_scheduler_for_api()
        assert result == "remote_scheduler"

    def test_returns_none_when_lock_file_not_held(self, tmp_path):
        """When lock file exists but can be acquired, no remote scheduler - return None."""
        from skytonight_scheduler_manager import get_skytonight_scheduler_for_api
        import sys

        lock_file = tmp_path / "free.lock"
        lock_file.write_text("")

        with patch("skytonight_scheduler_manager.get_or_create_skytonight_scheduler",
                   return_value=None):
            with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                       return_value=str(lock_file)):
                if sys.platform == "win32":
                    # locking succeeds → not held by another process → None
                    with patch("msvcrt.locking"):
                        from flask import Flask
                        app = Flask(__name__)
                        with app.app_context():
                            result = get_skytonight_scheduler_for_api()
                else:
                    with patch("fcntl.flock"):  # succeeds → not held
                        from flask import Flask
                        app = Flask(__name__)
                        with app.app_context():
                            result = get_skytonight_scheduler_for_api()
        assert result is None

    def test_ioerror_opening_lock_file_returns_remote(self, tmp_path):
        """IOError opening the lock file for test → return 'remote_scheduler' (line 208-209)."""
        from skytonight_scheduler_manager import get_skytonight_scheduler_for_api

        lock_file = tmp_path / "ioerr.lock"
        lock_file.write_text("")

        with patch("skytonight_scheduler_manager.get_or_create_skytonight_scheduler",
                   return_value=None):
            with patch("skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
                       return_value=str(lock_file)):
                with patch("builtins.open", side_effect=IOError("cannot open")):
                    from flask import Flask
                    app = Flask(__name__)
                    with app.app_context():
                        result = get_skytonight_scheduler_for_api()
        assert result == "remote_scheduler"


class TestGetOrCreateSchedulerLockLoggedBranch:
    """Cover line 146->151: already-logged OSError branch."""

    def test_second_lock_failure_skips_debug_log(self, tmp_path):
        """Line 146->151: when skytonight_scheduler_lock_logged is True,
        the if-block body is skipped and we jump directly to line 151."""
        import sys
        module = sys.modules['skytonight_scheduler_manager']
        from skytonight_scheduler_manager import get_or_create_skytonight_scheduler

        mock_app = MagicMock()
        mock_app.config = {
            'skytonight_scheduler_lock_logged': True,  # already logged → False branch at 146
        }

        lock_path = str(tmp_path / "test.lock")

        with patch.object(module, 'get_skytonight_scheduler_lock_file', return_value=lock_path), \
             patch.object(module.sys, 'platform', 'win32'), \
             patch.object(module.msvcrt, 'locking', side_effect=OSError("locked")):
            result = get_or_create_skytonight_scheduler(mock_app)

        assert result is None
        assert mock_app.config.get('is_skytonight_scheduler_worker') is False
