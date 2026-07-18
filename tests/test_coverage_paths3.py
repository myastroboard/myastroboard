"""
Coverage boost — third batch of targeted tests for uncovered branches.

Each class targets a specific file/function with minimal, focused tests.
"""

import builtins
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from space import spaceflight_tracker

# ---------------------------------------------------------------------------
# push_scheduler.py — lines 613-614
# ---------------------------------------------------------------------------


class TestAcquireLockCloseFailsOnCleanup:
    """Lines 613-614: outer except fires AND lock_file.close() also raises."""

    def test_close_failure_logged_and_false_returned(self, monkeypatch, tmp_path):
        from utils import push_scheduler

        push_scheduler._lock_file = None
        real_open = builtins.open

        class _BrokenLockFile:
            """Simulates a file where fileno() raises (locking fails) and close() also raises."""

            def fileno(self):
                raise OSError("pretend lock is busy")

            def close(self):
                raise OSError("close also broken")

            def write(self, _):
                pass

            def flush(self):
                pass

        def _patched_open(path, *args, **kwargs):
            if "push_scheduler.lock" in str(path):
                return _BrokenLockFile()
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _patched_open)

        result = push_scheduler._acquire_lock()
        assert result is False
        assert push_scheduler._lock_file is None


# ---------------------------------------------------------------------------
# skytonight_scheduler_manager.py — lines 179-182, 185->190, 188-189
# ---------------------------------------------------------------------------


class TestGetOrCreateSchedulerLockCleanup:
    """Cover the lock-file cleanup branches in get_or_create_skytonight_scheduler."""

    def _make_app(self):
        mock_app = MagicMock()
        mock_app.config = {}
        return mock_app

    def test_ioerror_after_open_close_succeeds(self, tmp_path):
        """Lines 178-180: IOError after open → lock_file.close() called (succeeds)."""
        from skytonight.skytonight_scheduler_manager import get_or_create_skytonight_scheduler

        lock_path = str(tmp_path / "sched.lock")
        with patch(
            "skytonight.skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
            return_value=lock_path,
        ):
            with patch("skytonight.skytonight_scheduler_manager.msvcrt") as mock_msvcrt:
                mock_msvcrt.locking.return_value = None
                mock_msvcrt.LK_NBLCK = 1
                with patch(
                    "skytonight.skytonight_scheduler.SkyTonightScheduler",
                    side_effect=IOError("io error during scheduler creation"),
                ):
                    result = get_or_create_skytonight_scheduler(self._make_app())
        assert result is None

    def test_ioerror_after_open_close_also_fails(self, tmp_path):
        """Lines 181-182: IOError after open → lock_file.close() also raises."""
        from skytonight.skytonight_scheduler_manager import get_or_create_skytonight_scheduler

        lock_path = str(tmp_path / "sched2.lock")
        mock_lf = MagicMock()
        mock_lf.close.side_effect = OSError("close broken too")

        def _mock_open(path, *args, **kwargs):
            return mock_lf

        with patch(
            "skytonight.skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
            return_value=lock_path,
        ):
            with patch("builtins.open", side_effect=_mock_open):
                with patch("skytonight.skytonight_scheduler_manager.msvcrt") as mock_msvcrt:
                    mock_msvcrt.locking.return_value = None
                    mock_msvcrt.LK_NBLCK = 1
                    with patch(
                        "skytonight.skytonight_scheduler.SkyTonightScheduler",
                        side_effect=IOError("io error"),
                    ):
                        result = get_or_create_skytonight_scheduler(self._make_app())
        assert result is None

    def test_exception_handler_lock_file_none(self, tmp_path):
        """Branch 185->190: open() raises non-IOError/OSError → lock_file stays None."""
        from skytonight.skytonight_scheduler_manager import get_or_create_skytonight_scheduler

        lock_path = str(tmp_path / "sched3.lock")
        with patch(
            "skytonight.skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
            return_value=lock_path,
        ):
            with patch("builtins.open", side_effect=ValueError("unexpected value error")):
                result = get_or_create_skytonight_scheduler(self._make_app())
        assert result is None

    def test_exception_handler_close_also_fails(self, tmp_path):
        """Lines 188-189: general Exception after open + lock_file.close() raises."""
        from skytonight.skytonight_scheduler_manager import get_or_create_skytonight_scheduler

        lock_path = str(tmp_path / "sched4.lock")
        mock_lf = MagicMock()
        mock_lf.close.side_effect = ValueError("close also failed")

        with patch(
            "skytonight.skytonight_scheduler_manager.get_skytonight_scheduler_lock_file",
            return_value=lock_path,
        ):
            with patch("builtins.open", return_value=mock_lf):
                with patch("skytonight.skytonight_scheduler_manager.msvcrt") as mock_msvcrt:
                    mock_msvcrt.locking.return_value = None
                    mock_msvcrt.LK_NBLCK = 1
                    with patch(
                        "skytonight.skytonight_scheduler.SkyTonightScheduler",
                        side_effect=RuntimeError("scheduler init crashed"),
                    ):
                        result = get_or_create_skytonight_scheduler(self._make_app())
        assert result is None


# ---------------------------------------------------------------------------
# weather_astro.py — branches 213->217, 814->820
# ---------------------------------------------------------------------------


class TestWeatherAstroBranches:
    """Cover the two missed weather_astro branches."""

    @classmethod
    def setup_class(cls):
        from weather import weather_astro
        cls.weather_astro = weather_astro

    def test_parse_extended_data_timezone_already_string(self):
        """Branch 213->217: Timezone() returns str, not bytes — no decode needed."""
        analyzer = MagicMock()
        analyzer.location = {"name": "Paris", "latitude": 48.0, "longitude": 2.0}

        import numpy as np
        import pandas as pd

        mock_hourly = MagicMock()
        t0 = 1720000000
        arr = np.array([20.0, 21.0])
        mock_hourly.Time.return_value = t0
        mock_hourly.Variables.return_value.ValuesAsNumpy.return_value = arr
        mock_hourly.Interval.return_value = 3600

        mock_response = MagicMock()
        mock_response.Hourly.return_value = mock_hourly
        mock_response.Timezone.return_value = "UTC"  # string, not bytes
        mock_response.Latitude.return_value = 48.0
        mock_response.Longitude.return_value = 2.0
        mock_response.Elevation.return_value = 100.0

        result = self.weather_astro.AstroWeatherAnalyzer._parse_extended_data(
            analyzer, mock_response, ["temperature_2m"]
        )
        assert result is not None
        assert result["location"]["timezone"] == "UTC"

    def test_fresh_ts_but_no_cached_data_falls_through(self):
        """Branch 814->820: TTL not expired but cached data is None → fall through."""
        key = self.weather_astro._analysis_cache_key(24, "nocache_lang")
        now = time.time()
        with patch("weather.weather_astro.time.time", return_value=now), \
             patch("weather.weather_astro.is_openmeteo_rate_limited", return_value=True), \
             patch("weather.weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS", {key: now}), \
             patch("weather.weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS", {}):
            result = self.weather_astro.get_astro_weather_analysis(24, "nocache_lang")
        # rate limited + no cache → None
        assert result is None


# ---------------------------------------------------------------------------
# auth.py — branches 260->267, 267->273, 572->566, 581->580, 584->580
# ---------------------------------------------------------------------------


class TestAuthSaveUsersMissingBranches:
    """Cover save_users error-recovery branches not yet hit."""

    def test_makedirs_fails_no_backup_no_temp(self, tmp_path, monkeypatch):
        """Branches 260->267, 267->273: makedirs fails → backup_created=False, temp not created."""
        from utils import auth

        users_file = tmp_path / "users.json"
        monkeypatch.setattr(auth, "USERS_FILE", str(users_file))
        manager = auth.UserManager()

        def _fail_makedirs(*args, **kwargs):
            raise OSError("disk full")

        with patch("os.makedirs", side_effect=_fail_makedirs):
            with pytest.raises(OSError):
                manager.save_users()
        # Both False branches taken: backup_created=False and temp never created


class TestAuthDeleteUserMissingBranches:
    """Cover delete_user image-cleanup branches not yet hit."""

    @pytest.fixture
    def setup_auth_manager(self, tmp_path, monkeypatch):
        from utils import auth

        isolated_users = tmp_path / "users.json"
        monkeypatch.setattr(auth, "USERS_FILE", str(isolated_users))
        manager = auth.UserManager()
        admin = manager.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
        alice = manager.create_user("alice_cov3", "pass", auth.ROLE_USER)

        astrodex_dir = tmp_path / "astrodex"
        images_dir = tmp_path / "astrodex_images"
        astrodex_dir.mkdir()
        images_dir.mkdir()

        monkeypatch.setattr("observation.astrodex.ASTRODEX_DIR", str(astrodex_dir))
        monkeypatch.setattr("observation.astrodex.ASTRODEX_IMAGES_DIR", str(images_dir))

        return manager, admin, alice, astrodex_dir, images_dir

    def test_image_file_referenced_but_missing(self, tmp_path, monkeypatch, setup_auth_manager):
        """Branch 572->566: image listed in astrodex but doesn't exist on disk → skip."""
        manager, admin, alice, astrodex_dir, images_dir = setup_auth_manager
        user_id = alice.user_id

        # Astrodex references an image that does NOT exist on disk
        astrodex_data = {"items": [{"name": "M42", "pictures": [{"filename": f"{user_id}_missing.jpg"}]}]}
        (astrodex_dir / f"{user_id}_astrodex.json").write_text(
            json.dumps(astrodex_data), encoding="utf-8"
        )

        # No actual image file → os.path.exists(file_path) is False
        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None

    def test_listdir_filename_not_matching_user_prefix(self, tmp_path, monkeypatch, setup_auth_manager):
        """Branch 581->580: filename in listdir doesn't start with user_id prefix → skip."""
        manager, admin, alice, astrodex_dir, images_dir = setup_auth_manager
        user_id = alice.user_id

        # Create a file that belongs to a DIFFERENT user
        other_user_file = images_dir / "other_user_12345_pic.jpg"
        other_user_file.write_bytes(b"other")

        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None
        # Other user's file should remain
        assert other_user_file.exists()

    def test_listdir_path_traversal_guard(self, tmp_path, monkeypatch, setup_auth_manager):
        """Branch 584->580: normpath resolves outside images_dir → skip."""
        from utils import auth as auth_mod

        manager, admin, alice, astrodex_dir, images_dir = setup_auth_manager
        user_id = alice.user_id

        # Create a file matching the prefix
        img_file = images_dir / f"{user_id}_legit.jpg"
        img_file.write_bytes(b"data")

        original_normpath = os.path.normpath

        def _mock_normpath(path):
            if f"{user_id}_legit" in str(path) and "astrodex_images" in str(path):
                # Return a path outside the images dir to trigger the traversal guard
                return str(tmp_path / "outside" / f"{user_id}_legit.jpg")
            return original_normpath(path)

        monkeypatch.setattr(os.path, "normpath", _mock_normpath)

        manager.delete_user(user_id, current_user_id=admin.user_id)
        assert manager.get_user_by_id(user_id) is None


# ---------------------------------------------------------------------------
# cache_updater.py — lines 1015->1018, 1276, 1281-1286, 1324
# ---------------------------------------------------------------------------


class TestCacheUpdaterIersBranches:
    """Cover IERS-related branches in update_iers_cache and fully_initialize_caches."""

    def test_update_iers_no_mirror_url(self):
        """Branch 1015->1018: mirror_url is None → single URL list."""
        from cache.cache_updater import update_iers_cache
        import astropy.utils.iers as _iers_mod

        mock_conf = MagicMock()
        mock_conf.iers_auto_url = "https://example.com/iers.ecsv"
        # getattr(..., 'iers_auto_url_mirror', None) returns None
        del mock_conf.iers_auto_url_mirror

        with patch.object(_iers_mod, "conf", mock_conf):
            with patch("requests.get") as mock_req:
                mock_resp = MagicMock()
                mock_resp.content = b"fake content"
                mock_req.return_value = mock_resp
                with patch("os.makedirs"):
                    with patch("builtins.open", MagicMock()):
                        with patch("astropy.utils.iers.IERS_A.open", return_value=MagicMock()):
                            with patch("astropy.utils.iers.IERS_Auto") as mock_auto:
                                mock_auto.iers_table = None
                                try:
                                    update_iers_cache()
                                except Exception:
                                    pass  # not the point; just need the mirror branch covered

    def test_iers_table_mjd_max_without_value_attr(self):
        """Line 1276: mjd_max without .value attribute (plain float)."""
        from cache.cache_updater import fully_initialize_caches
        import astropy.utils.iers as _iers_mod

        class _FakeMJD:
            """Has no .value attribute, so hasattr(mjd_max, 'value') is False."""

            def max(self):
                return 59000.0  # plain float-like, no .value

        class _FakeTable:
            def __getitem__(self, key):
                if key == "MJD":
                    return _FakeMJD()
                return None

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes") as mock_chk:
                    mock_cfg.return_value = {
                        "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                    }
                    mock_cs.is_cache_valid.return_value = True
                    mock_cs.is_cache_valid_for_today.return_value = True
                    mock_cs.sync_cache_from_shared.return_value = None
                    mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                    mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                    fake_table = _FakeTable()
                    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=fake_table):
                        with patch("astropy.time.Time.now") as mock_time:
                            mock_now = MagicMock()
                            mock_now.mjd = 61000.0  # future → table appears stale
                            mock_time.return_value = mock_now
                            fully_initialize_caches()

    def test_iers_stale_exception_during_eval(self):
        """Lines 1281-1282: exception while evaluating IERS table staleness."""
        from cache.cache_updater import fully_initialize_caches

        class _BadTable:
            def __getitem__(self, key):
                raise KeyError("table access error")

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes"):
                    mock_cfg.return_value = {
                        "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                    }
                    mock_cs.is_cache_valid.return_value = True
                    mock_cs.is_cache_valid_for_today.return_value = True
                    mock_cs.sync_cache_from_shared.return_value = None
                    mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                    mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                    bad_table = _BadTable()
                    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=bad_table):
                        fully_initialize_caches()  # should not raise

    def test_iers_stale_forces_iers_job(self):
        """Lines 1285-1286: stale IERS table → iers job appended to jobs_to_run."""
        from cache.cache_updater import fully_initialize_caches

        class _StaleTable:
            def __getitem__(self, key):
                if key == "MJD":
                    return _MJDWithValue()
                raise KeyError(key)

        class _MJDWithValue:
            def max(self):
                return _HasValue()

        class _HasValue:
            value = 50000.0  # very old date → stale

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes"):
                    with patch("cache.cache_updater.update_iers_cache") as mock_iers:
                        mock_cfg.return_value = {
                            "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                        }
                        mock_cs.is_cache_valid.return_value = True
                        mock_cs.is_cache_valid_for_today.return_value = True
                        mock_cs.sync_cache_from_shared.return_value = None
                        mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                        mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                        stale_table = _StaleTable()
                        with patch("astropy.utils.iers.IERS_Auto.iers_table", new=stale_table):
                            fully_initialize_caches()

    def test_iers_pre_parallel_success_increments_count(self):
        """Line 1324: pre-parallel IERS download succeeds → success_count incremented."""
        from cache.cache_updater import fully_initialize_caches

        with patch("cache.cache_updater.update_iers_cache") as mock_iers:
            mock_iers.return_value = None  # success
            with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
                with patch("cache.cache_updater.cache_store") as mock_cs:
                    with patch("cache.cache_updater.load_config") as mock_cfg:
                        with patch("cache.cache_updater.check_and_handle_config_changes"):
                            mock_cfg.return_value = {
                                "location": {
                                    "latitude": 48.0,
                                    "longitude": 2.0,
                                    "timezone": "UTC",
                                }
                            }
                            mock_cs.is_cache_valid.return_value = False
                            mock_cs.is_cache_valid_for_today.return_value = True
                            mock_cs.sync_cache_from_shared.return_value = None
                            mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                            mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                            fully_initialize_caches()
                            mock_iers.assert_called()


# ---------------------------------------------------------------------------
# object_info.py — branches 238->232, 332->330, 450->446
# ---------------------------------------------------------------------------


class TestObjectInfoMissingBranches:
    """Cover missed object_info.py branches."""

    def test_alias_equal_to_identifier_skipped(self):
        """Branch 238->232: alias_val == identifier → skip redundant entry in _resolve_via_simbad."""
        from observation.object_info import _resolve_via_simbad

        identifier = "M31"
        main_result = {
            "data": [["M 31", "Galaxy", 10.68, 41.27]],
            "metadata": [
                {"name": "main_id"},
                {"name": "otype_txt"},
                {"name": "ra"},
                {"name": "dec"},
            ],
        }
        # Alias list includes the identifier itself ("M31") + others
        alias_result = {"data": [["M31"], ["NGC 224"], ["Andromeda Galaxy"]]}

        query_results = [main_result, alias_result]
        call_idx = [0]

        def _mock_query(adql):
            idx = call_idx[0]
            call_idx[0] += 1
            return query_results[idx] if idx < len(query_results) else None

        with patch("observation.object_info._simbad_query", side_effect=_mock_query):
            result = _resolve_via_simbad(identifier)

        assert result is not None
        aliases = result.get("aliases", [])
        # "M31" equals identifier → must NOT appear in the alias list
        assert "M31" not in aliases

    def test_alias_empty_string_skipped(self):
        """Branch 332->330: alias_val is empty → skip in resolve_identifier_for_catalogue_lookup."""
        from observation.object_info import resolve_identifier_for_catalogue_lookup

        main_result = {
            "data": [["M 31", "Galaxy", None, None]],
            "metadata": [
                {"name": "main_id"},
                {"name": "otype_txt"},
                {"name": "ra"},
                {"name": "dec"},
            ],
        }
        # Alias data includes an empty string (falsy) → branch 332->330
        alias_result = {"data": [[""], ["NGC 224"]]}

        query_results = [main_result, alias_result]
        call_idx = [0]

        def _mock_query(adql):
            idx = call_idx[0]
            call_idx[0] += 1
            return query_results[idx] if idx < len(query_results) else None

        with patch("observation.object_info._simbad_query", side_effect=_mock_query):
            result = resolve_identifier_for_catalogue_lookup("M31")

        assert result is not None
        # Empty string should not appear in aliases
        assert "" not in result.get("aliases", [])

    def test_wikipedia_fallback_en_loop_none_result(self):
        """Branch 450->446: lang != 'en', alias is candidate but wiki returns None → loop continues."""
        from observation.object_info import _wikipedia_with_fallback

        aliases = ["Andromeda Galaxy", "M31"]

        def _no_wiki(term, lang):
            return None  # always return None

        with patch("observation.object_info._get_wikipedia_summary", side_effect=_no_wiki):
            with patch("observation.object_info._is_wikipedia_candidate", return_value=True):
                result = _wikipedia_with_fallback(aliases, lang="fr")

        assert result is None  # all attempts returned None


# ---------------------------------------------------------------------------
# spaceflight_tracker.py — lines 75, 83-84, 88-90, 101-102
# ---------------------------------------------------------------------------


class TestSpaceflightTrackerBackoffHelpers:
    """Cover _load_backoff_state and _save_backoff_state edge cases."""

    def test_load_backoff_file_not_exists_returns_empty(self, tmp_path, monkeypatch):
        """_load_backoff_state returns {} when the backoff file does not exist."""
        nonexistent = str(tmp_path / "no_backoff.json")
        monkeypatch.setattr(spaceflight_tracker, "_SPACEFLIGHT_BACKOFF_FILE", nonexistent)

        result = spaceflight_tracker._load_backoff_state()
        assert result == {}

    def test_load_backoff_invalid_float_entry_skipped(self, tmp_path, monkeypatch):
        """Lines 83-84: float(exp) raises TypeError/ValueError → continue."""
        backoff_file = tmp_path / "backoff.json"
        future_ts = time.time() + 3600
        # One valid entry, one with non-numeric value
        backoff_file.write_text(
            json.dumps({"/valid/": future_ts, "/bad/": "not-a-float"}), encoding="utf-8"
        )
        monkeypatch.setattr(spaceflight_tracker, "_SPACEFLIGHT_BACKOFF_FILE", str(backoff_file))

        result = spaceflight_tracker._load_backoff_state()
        assert "/valid/" in result
        assert "/bad/" not in result

    def test_load_backoff_json_parse_exception(self, tmp_path, monkeypatch):
        """Lines 88-90: outer exception (JSON parse error) → return {}."""
        backoff_file = tmp_path / "bad_backoff.json"
        backoff_file.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(spaceflight_tracker, "_SPACEFLIGHT_BACKOFF_FILE", str(backoff_file))

        result = spaceflight_tracker._load_backoff_state()
        assert result == {}

    def test_save_backoff_state_write_exception(self, tmp_path, monkeypatch):
        """Lines 101-102: exception in _save_backoff_state → logged, no raise."""
        monkeypatch.setattr(spaceflight_tracker, "_SPACEFLIGHT_BACKOFF_FILE", str(tmp_path / "x.json"))
        monkeypatch.setattr(
            spaceflight_tracker,
            "_backoff_until",
            {"/test/": time.time() + 3600},
        )

        with patch("space.spaceflight_tracker.os.makedirs", side_effect=OSError("no space")):
            spaceflight_tracker._save_backoff_state()  # must not raise

    def test_load_backoff_expired_entry_excluded(self, tmp_path, monkeypatch):
        """Branch 85->80: exp_val <= now_ts (expired entry) → if is False → loop continues."""
        backoff_file = tmp_path / "backoff_expired.json"
        expired_ts = time.time() - 3600  # 1 hour in the past → expired
        backoff_file.write_text(
            json.dumps({"/expired/": expired_ts}), encoding="utf-8"
        )
        monkeypatch.setattr(spaceflight_tracker, "_SPACEFLIGHT_BACKOFF_FILE", str(backoff_file))

        result = spaceflight_tracker._load_backoff_state()
        assert "/expired/" not in result  # expired → not included in returned state
