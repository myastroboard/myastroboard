"""Extended unit tests for plan_my_night.py pure helper functions."""
import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest

import plan_my_night
_build_target_payload = plan_my_night._build_target_payload
_is_valid_telescope_id = plan_my_night._is_valid_telescope_id
_is_valid_user_id = plan_my_night._is_valid_user_id
_minutes_to_hhmm = plan_my_night._minutes_to_hhmm
_parse_datetime = plan_my_night._parse_datetime
_parse_hhmm_to_minutes = plan_my_night._parse_hhmm_to_minutes
delete_plan_for_telescope = plan_my_night.delete_plan_for_telescope
get_all_plan_files = plan_my_night.get_all_plan_files
get_plan_state = plan_my_night.get_plan_state
is_target_in_current_plan = plan_my_night.is_target_in_current_plan
load_user_plan = plan_my_night.load_user_plan
save_user_plan = plan_my_night.save_user_plan
validate_plan_json = plan_my_night.validate_plan_json


# ---------------------------------------------------------------------------
# _is_valid_user_id
# ---------------------------------------------------------------------------


class TestIsValidUserId:

    def test_valid_uuid(self):
        assert _is_valid_user_id(str(uuid.uuid4())) is True

    def test_known_uuid_format(self):
        assert _is_valid_user_id("550e8400-e29b-41d4-a716-446655440000") is True

    def test_uppercase_uuid(self):
        assert _is_valid_user_id("550E8400-E29B-41D4-A716-446655440000") is True

    def test_none_returns_false(self):
        assert _is_valid_user_id(None) is False

    def test_empty_string_returns_false(self):
        assert _is_valid_user_id("") is False

    def test_plain_string_returns_false(self):
        assert _is_valid_user_id("admin") is False

    def test_integer_string_returns_false(self):
        assert _is_valid_user_id("12345") is False

    def test_uuid_without_hyphens_returns_false(self):
        assert _is_valid_user_id("550e8400e29b41d4a716446655440000") is False

    def test_too_short_returns_false(self):
        assert _is_valid_user_id("550e8400-e29b-41d4-a716") is False


# ---------------------------------------------------------------------------
# _is_valid_telescope_id
# ---------------------------------------------------------------------------


class TestIsValidTelescopeId:

    def test_default_is_valid(self):
        assert _is_valid_telescope_id("default") is True

    def test_uuid_is_valid(self):
        assert _is_valid_telescope_id(str(uuid.uuid4())) is True

    def test_none_returns_false(self):
        assert _is_valid_telescope_id(None) is False

    def test_empty_string_returns_false(self):
        assert _is_valid_telescope_id("") is False

    def test_arbitrary_string_returns_false(self):
        assert _is_valid_telescope_id("my-telescope") is False

    def test_integer_string_returns_false(self):
        assert _is_valid_telescope_id("1") is False


# ---------------------------------------------------------------------------
# _safe_plan_path
# ---------------------------------------------------------------------------


class TestSafePlanPath:

    def test_valid_path_inside_plan_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        valid = os.path.join(str(tmp_path), "user_plan.json")
        result = plan_my_night._safe_plan_path(valid)
        assert result == os.path.realpath(valid)

    def test_path_traversal_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        evil = os.path.join(str(tmp_path), "..", "etc", "passwd")
        with pytest.raises(ValueError, match="outside plan directory"):
            plan_my_night._safe_plan_path(evil)

    def test_plan_dir_itself_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        with pytest.raises(ValueError):
            plan_my_night._safe_plan_path(str(tmp_path))


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:

    def test_none_returns_none(self):
        assert _parse_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_datetime("") is None

    def test_datetime_object_returns_itself(self):
        dt = datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)
        result = _parse_datetime(dt)
        assert result is not None
        assert result.year == 2026

    def test_iso_format_string(self):
        result = _parse_datetime("2026-06-15T21:30:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_iso_format_with_timezone(self):
        result = _parse_datetime("2026-06-15T21:30:00+02:00")
        assert result is not None
        assert result.year == 2026

    def test_legacy_space_format(self):
        result = _parse_datetime("2026-06-15 21:30")
        assert result is not None
        assert result.hour == 21
        assert result.minute == 30

    def test_invalid_string_returns_none(self):
        assert _parse_datetime("not-a-date") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_datetime("   ") is None


# ---------------------------------------------------------------------------
# _parse_hhmm_to_minutes
# ---------------------------------------------------------------------------


class TestParseHhmmToMinutes:

    def test_zero(self):
        assert _parse_hhmm_to_minutes("00:00") == 0

    def test_one_hour(self):
        assert _parse_hhmm_to_minutes("01:00") == 60

    def test_mixed(self):
        assert _parse_hhmm_to_minutes("02:30") == 150

    def test_max_value_clamped(self):
        result = _parse_hhmm_to_minutes("25:00")
        assert result == 24 * 60

    def test_invalid_minutes_returns_none(self):
        assert _parse_hhmm_to_minutes("01:60") is None

    def test_negative_hours_returns_none(self):
        assert _parse_hhmm_to_minutes("-01:00") is None

    def test_empty_string_returns_none(self):
        assert _parse_hhmm_to_minutes("") is None

    def test_no_colon_returns_none(self):
        assert _parse_hhmm_to_minutes("0130") is None

    def test_non_numeric_returns_none(self):
        assert _parse_hhmm_to_minutes("ab:cd") is None

    def test_too_many_parts_returns_none(self):
        assert _parse_hhmm_to_minutes("01:30:00") is None


# ---------------------------------------------------------------------------
# _minutes_to_hhmm
# ---------------------------------------------------------------------------


class TestMinutesToHhmm:

    def test_zero(self):
        assert _minutes_to_hhmm(0) == "00:00"

    def test_one_hour(self):
        assert _minutes_to_hhmm(60) == "01:00"

    def test_mixed(self):
        assert _minutes_to_hhmm(90) == "01:30"

    def test_large_value(self):
        assert _minutes_to_hhmm(24 * 60) == "24:00"

    def test_negative_clamped_to_zero(self):
        assert _minutes_to_hhmm(-10) == "00:00"

    def test_single_minutes(self):
        assert _minutes_to_hhmm(5) == "00:05"

    def test_padding(self):
        assert _minutes_to_hhmm(65) == "01:05"


# ---------------------------------------------------------------------------
# get_plan_state
# ---------------------------------------------------------------------------


class TestGetPlanState:

    def test_none_plan_returns_none(self):
        assert get_plan_state(None) == "none"

    def test_empty_dict_plan_returns_none(self):
        assert get_plan_state({}) == "none"

    def test_future_night_end_returns_current(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        plan = {"night_end": future}
        assert get_plan_state(plan) == "current"

    def test_past_night_end_returns_previous(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        plan = {"night_end": past}
        assert get_plan_state(plan) == "previous"

    def test_explicit_now_dt(self):
        night_end = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        plan = {"night_end": night_end.isoformat()}
        before = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        after = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        assert get_plan_state(plan, now_dt=before) == "current"
        assert get_plan_state(plan, now_dt=after) == "previous"

    def test_no_night_end_returns_current(self):
        plan = {"entries": []}
        assert get_plan_state(plan) == "current"


# ---------------------------------------------------------------------------
# validate_plan_json
# ---------------------------------------------------------------------------


class TestValidatePlanJson:

    def _write_plan(self, tmp_path, monkeypatch, payload):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "valid_plan.json")
        with open(fname, "w") as f:
            json.dump(payload, f)
        return fname

    def test_valid_plan_returns_true(self, tmp_path, monkeypatch):
        fname = self._write_plan(tmp_path, monkeypatch, {
            "user_id": str(uuid.uuid4()),
            "plan": {
                "entries": [{"id": "e1", "name": "M42"}]
            }
        })
        ok, msg = validate_plan_json(fname)
        assert ok is True
        assert msg == ""

    def test_missing_user_id_returns_false(self, tmp_path, monkeypatch):
        fname = self._write_plan(tmp_path, monkeypatch, {"plan": None})
        ok, msg = validate_plan_json(fname)
        assert ok is False
        assert "user_id" in msg

    def test_plan_none_is_valid(self, tmp_path, monkeypatch):
        fname = self._write_plan(tmp_path, monkeypatch, {
            "user_id": str(uuid.uuid4()),
            "plan": None
        })
        ok, _ = validate_plan_json(fname)
        assert ok is True

    def test_entry_missing_id_returns_false(self, tmp_path, monkeypatch):
        fname = self._write_plan(tmp_path, monkeypatch, {
            "user_id": str(uuid.uuid4()),
            "plan": {"entries": [{"name": "M31"}]}
        })
        ok, msg = validate_plan_json(fname)
        assert ok is False
        assert "id" in msg

    def test_invalid_json_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "bad.json")
        with open(fname, "w") as f:
            f.write("{not valid json")
        ok, msg = validate_plan_json(fname)
        assert ok is False
        assert "JSON" in msg

    def test_nonexistent_file_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "ghost.json")
        ok, msg = validate_plan_json(fname)
        assert ok is False


# ---------------------------------------------------------------------------
# load_user_plan
# ---------------------------------------------------------------------------


class TestLoadUserPlan:

    def test_returns_default_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        result = load_user_plan(user_id, "alice")
        assert result["user_id"] == user_id
        assert result["plan"] is None

    def test_loads_existing_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        payload = {"user_id": user_id, "plan": None}
        plan_file.write_text(json.dumps(payload))
        result = load_user_plan(user_id, "alice")
        assert result["user_id"] == user_id


# ---------------------------------------------------------------------------
# save_user_plan
# ---------------------------------------------------------------------------


class TestSaveUserPlan:

    def test_saves_plan_successfully(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        payload = {"user_id": user_id, "plan": None}
        result = save_user_plan(user_id, payload, username="alice")
        assert result is True
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        assert plan_file.exists()

    def test_saves_with_telescope_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        payload = {"user_id": user_id, "plan": None}
        result = save_user_plan(user_id, payload, username="bob", telescope_id=tel_id)
        assert result is True


# ---------------------------------------------------------------------------
# _build_target_payload
# ---------------------------------------------------------------------------


class TestBuildTargetPayload:

    def test_basic_fields(self):
        item = {
            "name": "M42",
            "type": "Nebula",
            "constellation": "Orion",
            "ra": "05h35m",
            "dec": "-05d",
            "mag": 4.0,
        }
        result = _build_target_payload(item, "Messier")
        assert result["name"] == "M42"
        assert result["catalogue"] == "Messier"
        assert result["type"] == "Nebula"
        assert result["done"] is False
        assert result["planned_duration"] == "01:00"
        assert "id" in result

    def test_custom_planned_minutes(self):
        item = {"name": "NGC 891", "planned_minutes": 90}
        result = _build_target_payload(item, "OpenNGC")
        assert result["planned_minutes"] == 90
        assert result["planned_duration"] == "01:30"

    def test_invalid_planned_minutes_defaults_to_60(self):
        item = {"name": "IC 342", "planned_minutes": "bad"}
        result = _build_target_payload(item, "OpenNGC")
        assert result["planned_minutes"] == 60

    def test_done_flag(self):
        item = {"name": "M51", "done": True}
        result = _build_target_payload(item, "Messier")
        assert result["done"] is True


# ---------------------------------------------------------------------------
# get_all_plan_files
# ---------------------------------------------------------------------------


class TestGetAllPlanFiles:

    def test_invalid_user_returns_empty(self):
        assert get_all_plan_files("not-a-uuid") == []

    def test_returns_existing_plan_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        (tmp_path / f"{user_id}_plan_my_night.json").write_text("{}")
        files = get_all_plan_files(user_id)
        assert len(files) == 1

    def test_ignores_backup_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        (tmp_path / f"{user_id}_plan_my_night.json").write_text("{}")
        (tmp_path / f"{user_id}_plan_my_night.json.backup").write_text("{}")
        files = get_all_plan_files(user_id)
        assert len(files) == 1

    def test_returns_multiple_telescope_plans(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        (tmp_path / f"{user_id}_plan_my_night.json").write_text("{}")
        (tmp_path / f"{user_id}_plan_{tel_id}.json").write_text("{}")
        files = get_all_plan_files(user_id)
        assert len(files) == 2

    def test_other_user_files_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        (tmp_path / f"{user_id}_plan_my_night.json").write_text("{}")
        (tmp_path / f"{other_id}_plan_my_night.json").write_text("{}")
        files = get_all_plan_files(user_id)
        assert len(files) == 1


# ---------------------------------------------------------------------------
# delete_plan_for_telescope
# ---------------------------------------------------------------------------


class TestDeletePlanForTelescope:

    def test_invalid_user_returns_false(self):
        assert delete_plan_for_telescope("not-a-uuid", "default") is False

    def test_invalid_telescope_id_returns_false(self):
        assert delete_plan_for_telescope(str(uuid.uuid4()), "bad-telescope") is False

    def test_nonexistent_file_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        result = delete_plan_for_telescope(user_id, tel_id)
        assert result is True

    def test_existing_file_deleted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        plan_file = tmp_path / f"{user_id}_plan_{tel_id}.json"
        plan_file.write_text("{}")
        result = delete_plan_for_telescope(user_id, tel_id)
        assert result is True
        assert not plan_file.exists()

    def test_default_telescope_id_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        result = delete_plan_for_telescope(user_id, "default")
        assert result is True


# ---------------------------------------------------------------------------
# load_user_plan — error paths
# ---------------------------------------------------------------------------


class TestLoadUserPlanErrors:

    def test_corrupted_json_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        plan_file.write_text("{invalid json{{")
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None
        assert result["user_id"] == user_id

    def test_non_dict_root_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        plan_file.write_text("[1, 2, 3]")
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None


# ---------------------------------------------------------------------------
# is_target_in_current_plan
# ---------------------------------------------------------------------------


class TestIsTargetInCurrentPlan:

    def test_no_plan_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False

    def test_empty_entries_returns_false(self, tmp_path, monkeypatch):
        from datetime import timezone, timedelta
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        payload = {
            "user_id": user_id,
            "plan": {"entries": [], "night_end": future},
        }
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        plan_file.write_text(json.dumps(payload))
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False

    def test_previous_plan_returns_false(self, tmp_path, monkeypatch):
        from datetime import timezone, timedelta
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        payload = {
            "user_id": user_id,
            "plan": {"entries": [{"id": "e1", "name": "M42"}], "night_end": past},
        }
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        plan_file.write_text(json.dumps(payload))
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False


# ---------------------------------------------------------------------------
# More save_user_plan error paths
# ---------------------------------------------------------------------------


class TestSaveUserPlanEdgeCases:

    def test_save_creates_backup_of_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        # Save once to create the file
        save_user_plan(user_id, {"user_id": user_id, "plan": None}, username="alice")
        # Save again — should create backup of existing file
        result = save_user_plan(user_id, {"user_id": user_id, "plan": None}, username="alice")
        assert result is True

    def test_save_with_telescope_creates_correct_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        result = save_user_plan(user_id, {"user_id": user_id}, username="bob", telescope_id=tel_id)
        assert result is True
        expected = tmp_path / f"{user_id}_plan_{tel_id}.json"
        assert expected.exists()


# ---------------------------------------------------------------------------
# validate_plan_json — entry missing name
# ---------------------------------------------------------------------------


class TestValidatePlanJsonExtended:

    def test_entry_missing_name_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "entry_no_name.json")
        with open(fname, "w") as f:
            json.dump({
                "user_id": str(uuid.uuid4()),
                "plan": {"entries": [{"id": "e1"}]}
            }, f)
        ok, msg = validate_plan_json(fname)
        assert ok is False
        assert "name" in msg

    def test_plan_entries_not_list_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "bad_entries.json")
        with open(fname, "w") as f:
            json.dump({
                "user_id": str(uuid.uuid4()),
                "plan": {"entries": "not_a_list"}
            }, f)
        ok, msg = validate_plan_json(fname)
        assert ok is False

    def test_entry_not_dict_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        fname = str(tmp_path / "entry_not_dict.json")
        with open(fname, "w") as f:
            json.dump({
                "user_id": str(uuid.uuid4()),
                "plan": {"entries": [42]}  # entry is int, not dict → line 241
            }, f)
        ok, msg = validate_plan_json(fname)
        assert ok is False
        assert "object" in msg


# ---------------------------------------------------------------------------
# get_user_plan_file — invalid user_id raises (line 116)
# ---------------------------------------------------------------------------


class TestGetUserPlanFile:

    def test_invalid_user_id_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="Invalid user_id"):
            plan_my_night.get_user_plan_file("not-a-uuid")

    def test_valid_user_id_returns_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        path = plan_my_night.get_user_plan_file(str(uuid.uuid4()))
        assert "plan_my_night.json" in path


# ---------------------------------------------------------------------------
# load_user_plan — plan is not a dict (line 215)
# ---------------------------------------------------------------------------


class TestLoadUserPlanPlanNotDict:

    def test_plan_field_not_dict_is_reset_to_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_my_night, "PLAN_DIR", str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f"{user_id}_plan_my_night.json"
        plan_file.write_text(json.dumps({
            "user_id": user_id,
            "plan": "this_is_not_a_dict"  # triggers line 215
        }))
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None
