"""Extended unit tests for plan_my_night.py pure helper functions."""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from db import documents

from observation import plan_my_night

_build_target_payload = plan_my_night._build_target_payload
_is_valid_combination_id = plan_my_night._is_valid_combination_id
_is_valid_user_id = plan_my_night._is_valid_user_id
_minutes_to_hhmm = plan_my_night._minutes_to_hhmm
_parse_datetime = plan_my_night._parse_datetime
_parse_hhmm_to_minutes = plan_my_night._parse_hhmm_to_minutes
get_plan_state = plan_my_night.get_plan_state
is_target_in_current_plan = plan_my_night.is_target_in_current_plan
load_user_plan = plan_my_night.load_user_plan
save_user_plan = plan_my_night.save_user_plan


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
# _is_valid_combination_id
# ---------------------------------------------------------------------------


class TestIsValidCombinationId:

    def test_default_is_valid(self):
        assert _is_valid_combination_id("default") is True

    def test_uuid_is_valid(self):
        assert _is_valid_combination_id(str(uuid.uuid4())) is True

    def test_none_returns_false(self):
        assert _is_valid_combination_id(None) is False

    def test_empty_string_returns_false(self):
        assert _is_valid_combination_id("") is False

    def test_arbitrary_string_returns_false(self):
        assert _is_valid_combination_id("my-telescope") is False

    def test_integer_string_returns_false(self):
        assert _is_valid_combination_id("1") is False


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
# validate_plan_data
# ---------------------------------------------------------------------------


class TestValidatePlanData:
    """validate_plan_data contract (run before every save)."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"user_id": "user123"},
            {"user_id": "user123", "plan": None},
            {"user_id": "user123", "plan": {"entries": [{"id": "1", "name": "M31"}, {"id": "2", "name": "M42"}]}},
        ],
    )
    def test_valid_payloads(self, payload):
        assert plan_my_night.validate_plan_data(payload) == (True, "")

    @pytest.mark.parametrize(
        "payload, fragment",
        [
            (["not", "a", "dict"], "object"),
            ({"plan": {}}, "user_id"),
            ({"user_id": "u", "plan": "not a dict"}, "object or null"),
            ({"user_id": "u", "plan": {"entries": "not a list"}}, "list"),
            ({"user_id": "u", "plan": {"entries": [42]}}, "object"),
            ({"user_id": "u", "plan": {"entries": [{"name": "M31"}]}}, "id"),
            ({"user_id": "u", "plan": {"entries": [{"id": "1"}]}}, "name"),
        ],
    )
    def test_invalid_payloads(self, payload, fragment):
        is_valid, error = plan_my_night.validate_plan_data(payload)
        assert is_valid is False
        assert fragment in error


# ---------------------------------------------------------------------------
# load_user_plan
# ---------------------------------------------------------------------------


class TestLoadUserPlan:

    def test_returns_default_when_no_file(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        result = load_user_plan(user_id, "alice")
        assert result["user_id"] == user_id
        assert result["plan"] is None

    def test_loads_existing_plan(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        payload = {"user_id": user_id, "plan": None}
        documents.put_document(user_id, 'plan', payload, 'default')
        result = load_user_plan(user_id, "alice")
        assert result["user_id"] == user_id


# ---------------------------------------------------------------------------
# save_user_plan
# ---------------------------------------------------------------------------


class TestSaveUserPlan:

    def test_saves_plan_successfully(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        payload = {"user_id": user_id, "plan": None}
        result = save_user_plan(user_id, payload, username="alice")
        assert result is True
        assert plan_my_night.list_user_plan_combination_ids(user_id) == [None]

    def test_saves_with_combination_id(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        combo_id = str(uuid.uuid4())
        payload = {"user_id": user_id, "plan": None}
        result = save_user_plan(user_id, payload, username="bob", combination_id=combo_id)
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


class TestListUserPlanCombinationIds:

    def test_invalid_user_returns_empty(self):
        assert plan_my_night.list_user_plan_combination_ids("not-a-uuid") == []

    def test_default_and_combination_plans(self):
        user_id = str(uuid.uuid4())
        combo_id = str(uuid.uuid4())
        save_user_plan(user_id, {"plan": None}, username="u")
        save_user_plan(user_id, {"plan": None}, username="u", combination_id=combo_id)
        assert sorted(plan_my_night.list_user_plan_combination_ids(user_id), key=str) == sorted(
            [None, combo_id], key=str
        )

    def test_other_user_plans_ignored(self):
        user_id = str(uuid.uuid4())
        save_user_plan(user_id, {"plan": None}, username="u")
        save_user_plan(str(uuid.uuid4()), {"plan": None}, username="v")
        assert plan_my_night.list_user_plan_combination_ids(user_id) == [None]


# ---------------------------------------------------------------------------
# load_user_plan — error paths
# ---------------------------------------------------------------------------


class TestLoadUserPlanErrors:

    def test_corrupted_json_returns_default(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        documents.put_document(user_id, 'plan', 'corrupt', 'default')
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None
        assert result["user_id"] == user_id

    def test_non_dict_root_returns_default(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        documents.put_document(user_id, 'plan', [1, 2, 3], 'default')
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None


# ---------------------------------------------------------------------------
# is_target_in_current_plan
# ---------------------------------------------------------------------------


class TestIsTargetInCurrentPlan:

    def test_no_plan_returns_false(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False

    def test_empty_entries_returns_false(self, tmp_path, monkeypatch):
        from datetime import timezone, timedelta

        user_id = str(uuid.uuid4())
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        payload = {
            "user_id": user_id,
            "plan": {"entries": [], "night_end": future},
        }
        documents.put_document(user_id, 'plan', payload, 'default')
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False

    def test_previous_plan_returns_false(self, tmp_path, monkeypatch):
        from datetime import timezone, timedelta

        user_id = str(uuid.uuid4())
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        payload = {
            "user_id": user_id,
            "plan": {"entries": [{"id": "e1", "name": "M42"}], "night_end": past},
        }
        documents.put_document(user_id, 'plan', payload, 'default')
        result = is_target_in_current_plan(user_id, "alice", "Messier", "M42")
        assert result is False


# ---------------------------------------------------------------------------
# More save_user_plan error paths
# ---------------------------------------------------------------------------


class TestSaveUserPlanEdgeCases:

    def test_save_creates_backup_of_existing_file(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        # Save once to create the file
        save_user_plan(user_id, {"user_id": user_id, "plan": None}, username="alice")
        # Save again — should create backup of existing file
        result = save_user_plan(user_id, {"user_id": user_id, "plan": None}, username="alice")
        assert result is True

    def test_save_with_combination_uses_the_combination_key(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        combo_id = str(uuid.uuid4())
        result = save_user_plan(user_id, {"user_id": user_id}, username="bob", combination_id=combo_id)
        assert result is True
        assert plan_my_night.list_user_plan_combination_ids(user_id) == [combo_id]


# ---------------------------------------------------------------------------
# invalid user ids
# ---------------------------------------------------------------------------


class TestInvalidUserId:

    def test_load_with_invalid_user_id_raises(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            plan_my_night.load_user_plan("not-a-uuid")

    def test_save_with_invalid_user_id_raises(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            plan_my_night.save_user_plan("not-a-uuid", {"plan": None})


# ---------------------------------------------------------------------------
# load_user_plan — plan is not a dict
# ---------------------------------------------------------------------------


class TestLoadUserPlanPlanNotDict:

    def test_plan_field_not_dict_is_reset_to_none(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        documents.put_document(user_id, 'plan', {"user_id": user_id, "plan": "this_is_not_a_dict"}, 'default')
        result = load_user_plan(user_id, "alice")
        assert result["plan"] is None


# ---------------------------------------------------------------------------
# count_plans_for_combination
# ---------------------------------------------------------------------------


class TestCountPlansForCombination:

    def test_empty_combination_id_returns_zero(self, tmp_path, monkeypatch):
        assert plan_my_night.count_plans_for_combination("") == 0
        assert plan_my_night.count_plans_for_combination(None) == 0

    def test_counts_matching_plans_across_users(self, tmp_path, monkeypatch):
        combo_id = str(uuid.uuid4())
        other_combo_id = str(uuid.uuid4())
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())

        save_user_plan(user_a, {"plan": {"combination_id": combo_id}}, username="alice", combination_id=combo_id)
        save_user_plan(user_b, {"plan": {"combination_id": combo_id}}, username="bob", combination_id=combo_id)
        save_user_plan(
            user_a, {"plan": {"combination_id": other_combo_id}}, username="alice", combination_id=other_combo_id
        )

        assert plan_my_night.count_plans_for_combination(combo_id) == 2
        assert plan_my_night.count_plans_for_combination(other_combo_id) == 1

    def test_plan_referencing_different_combination_not_counted(self, tmp_path, monkeypatch):
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        save_user_plan(user_id, {"plan": {"combination_id": other_id}}, username="alice", combination_id=other_id)
        assert plan_my_night.count_plans_for_combination(str(uuid.uuid4())) == 0

    def test_malformed_plan_does_not_count(self):
        combo_id = str(uuid.uuid4())
        documents.put_document(str(uuid.uuid4()), "plan", "corrupt", combo_id)
        assert plan_my_night.count_plans_for_combination(combo_id) == 0


# ---------------------------------------------------------------------------
# purge_legacy_telescope_plans
# ---------------------------------------------------------------------------


class TestPurgeLegacyTelescopePlans:

    def _store(self, plan):
        user_id = str(uuid.uuid4())
        documents.put_document(user_id, "plan", {"plan": plan}, "default")
        return user_id

    def test_deletes_plan_with_legacy_telescope_id_key(self):
        user_id = self._store({"telescope_id": "abc", "entries": []})
        assert plan_my_night.purge_legacy_telescope_plans() == 1
        assert plan_my_night.list_user_plan_combination_ids(user_id) == []

    def test_keeps_plan_with_combination_id_key(self):
        user_id = self._store({"combination_id": "abc", "entries": []})
        assert plan_my_night.purge_legacy_telescope_plans() == 0
        assert plan_my_night.list_user_plan_combination_ids(user_id) == [None]

    def test_keeps_plan_with_null_plan(self):
        user_id = self._store(None)
        assert plan_my_night.purge_legacy_telescope_plans() == 0
        assert plan_my_night.list_user_plan_combination_ids(user_id) == [None]
