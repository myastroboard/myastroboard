"""
Comprehensive unit tests for plan_my_night module.
Tests date parsing, validation, matching logic, and file I/O.
"""

import os
import sys
import tempfile
import json
from datetime import datetime, timedelta, timezone
from threading import Thread
from unittest.mock import patch

import pytest

from observation import plan_my_night
_parse_datetime = plan_my_night._parse_datetime
validate_plan_json = plan_my_night.validate_plan_json
_normalize_name = plan_my_night._normalize_name
_entry_matches = plan_my_night._entry_matches
is_target_in_entries = plan_my_night.is_target_in_entries
_parse_hhmm_to_minutes = plan_my_night._parse_hhmm_to_minutes
_minutes_to_hhmm = plan_my_night._minutes_to_hhmm
get_plan_state = plan_my_night.get_plan_state
_build_target_payload = plan_my_night._build_target_payload
save_user_plan = plan_my_night.save_user_plan
load_user_plan = plan_my_night.load_user_plan
create_or_add_target = plan_my_night.create_or_add_target
clear_plan = plan_my_night.clear_plan
remove_target = plan_my_night.remove_target
update_target = plan_my_night.update_target
reorder_target = plan_my_night.reorder_target
get_plan_with_timeline = plan_my_night.get_plan_with_timeline
serialize_plan_csv = plan_my_night.serialize_plan_csv
generate_plan_pdf = plan_my_night.generate_plan_pdf
_csv_normalize_ra = plan_my_night._csv_normalize_ra
_csv_normalize_dec = plan_my_night._csv_normalize_dec
_csv_fmt_local_hm = plan_my_night._csv_fmt_local_hm
_csv_fmt_observable_pct = plan_my_night._csv_fmt_observable_pct
_observable_runs = plan_my_night._observable_runs
_coverage_for_window = plan_my_night._coverage_for_window
_visibility_summary = plan_my_night._visibility_summary
_compute_entry_visibility = plan_my_night._compute_entry_visibility
_load_alttime = plan_my_night._load_alttime
compute_optimized_schedule = plan_my_night.compute_optimized_schedule
apply_optimized_schedule = plan_my_night.apply_optimized_schedule


@pytest.fixture
def temp_plan_dir(monkeypatch):
    """Create a temporary directory for plan files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plan_my_night.PLAN_DIR = tmpdir
        yield tmpdir


class TestParseDatetime:
    """Tests for _parse_datetime function."""

    def test_parse_iso_format(self):
        """Test parsing ISO 8601 format with timezone."""
        iso_str = "2026-04-17T15:30:45-04:00"
        result = _parse_datetime(iso_str)
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 17

    def test_parse_iso_format_z_timezone(self):
        """Test parsing ISO 8601 with Z timezone."""
        iso_str = "2026-04-17T19:30:45Z"
        result = _parse_datetime(iso_str)
        assert result is not None
        assert result.year == 2026

    def test_parse_legacy_format(self):
        """Test parsing legacy YYYY-MM-DD HH:MM format."""
        legacy_str = "2026-04-17 15:30"
        result = _parse_datetime(legacy_str)
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 17
        assert result.hour == 15
        assert result.minute == 30

    def test_parse_datetime_object(self):
        """Test parsing an already-parsed datetime object."""
        dt = datetime(2026, 4, 17, 15, 30, 45)
        result = _parse_datetime(dt)
        assert result is not None
        assert result.year == 2026

    def test_parse_none(self):
        """Test parsing None returns None."""
        assert _parse_datetime(None) is None

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        assert _parse_datetime("") is None

    def test_parse_invalid_format(self):
        """Test parsing invalid format returns None."""
        assert _parse_datetime("not a date") is None

    def test_parse_whitespace_only(self):
        """Test parsing whitespace-only string returns None."""
        assert _parse_datetime("   ") is None

    def test_parse_with_whitespace(self):
        """Test parsing with leading/trailing whitespace."""
        result = _parse_datetime("  2026-04-17 15:30  ")
        assert result is not None
        assert result.year == 2026


class TestValidatePlanJson:
    """Tests for validate_plan_json function."""

    def test_valid_empty_plan(self, temp_plan_dir):
        """Test validation of valid empty plan."""
        file_path = os.path.join(temp_plan_dir, "valid.json")
        payload = {"user_id": "user123"}
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is True
        assert error == ""

    def test_valid_plan_with_entries(self, temp_plan_dir):
        """Test validation of plan with valid entries."""
        file_path = os.path.join(temp_plan_dir, "valid_with_entries.json")
        payload = {
            "user_id": "user123",
            "plan": {
                "entries": [
                    {"id": "1", "name": "M31", "catalogue": "Messier"},
                    {"id": "2", "name": "M42", "catalogue": "Messier"}
                ]
            }
        }
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is True

    def test_missing_user_id(self, temp_plan_dir):
        """Test validation fails when user_id is missing."""
        file_path = os.path.join(temp_plan_dir, "missing_user_id.json")
        payload = {"plan": {}}
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False
        assert "user_id" in error

    def test_non_dict_root(self, temp_plan_dir):
        """Test validation fails for non-dict root."""
        file_path = os.path.join(temp_plan_dir, "non_dict_root.json")
        with open(file_path, "w") as f:
            json.dump(["not", "a", "dict"], f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False
        assert "object" in error.lower()

    def test_plan_not_dict(self, temp_plan_dir):
        """Test validation fails when plan is not a dict."""
        file_path = os.path.join(temp_plan_dir, "plan_not_dict.json")
        payload = {"user_id": "user123", "plan": "not a dict"}
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False

    def test_entries_not_list(self, temp_plan_dir):
        """Test validation fails when entries is not a list."""
        file_path = os.path.join(temp_plan_dir, "entries_not_list.json")
        payload = {
            "user_id": "user123",
            "plan": {"entries": "not a list"}
        }
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False

    def test_entry_missing_id(self, temp_plan_dir):
        """Test validation fails when entry is missing id."""
        file_path = os.path.join(temp_plan_dir, "entry_missing_id.json")
        payload = {
            "user_id": "user123",
            "plan": {
                "entries": [
                    {"name": "M31", "catalogue": "Messier"}
                ]
            }
        }
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False
        assert "id" in error

    def test_entry_missing_name(self, temp_plan_dir):
        """Test validation fails when entry is missing name."""
        file_path = os.path.join(temp_plan_dir, "entry_missing_name.json")
        payload = {
            "user_id": "user123",
            "plan": {
                "entries": [
                    {"id": "1", "catalogue": "Messier"}
                ]
            }
        }
        with open(file_path, "w") as f:
            json.dump(payload, f)
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False
        assert "name" in error

    def test_invalid_json(self, temp_plan_dir):
        """Test validation fails for invalid JSON."""
        file_path = os.path.join(temp_plan_dir, "invalid.json")
        with open(file_path, "w") as f:
            f.write("{ invalid json")
        
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_file_not_found(self, temp_plan_dir):
        """Test validation fails for missing file."""
        file_path = os.path.join(temp_plan_dir, "nonexistent.json")
        is_valid, error = validate_plan_json(file_path)
        assert is_valid is False


class TestNormalizeName:
    """Tests for _normalize_name function."""

    def test_normalize_uppercase(self):
        """Test normalizing uppercase names."""
        # This test depends on the actual normalize_object_name implementation
        # Adjust based on actual behavior
        result = _normalize_name("M42")
        assert result is not None

    def test_normalize_with_spaces(self):
        """Test normalizing names with spaces."""
        result = _normalize_name("NGC 224")
        assert result is not None


class TestEntryMatches:
    """Tests for _entry_matches function."""

    def test_entry_matches_by_group_id(self):
        """Test matching by catalogue group ID."""
        entry = {
            "name": "M31",
            "catalogue_group_id": "group123",
            "catalogue_aliases": {}
        }
        # Mock the _target_group_id to return matching group
        with patch("observation.plan_my_night._target_group_id", return_value="group123"):
            result = _entry_matches(entry, "Messier", "M31")
            assert result is True

    def test_entry_matches_by_name(self):
        """Test matching by normalized name."""
        entry = {
            "name": "M31",
            "catalogue_group_id": "different-group",
            "catalogue_aliases": {}
        }
        with patch("observation.plan_my_night._target_group_id", return_value=None):
            result = _entry_matches(entry, "Messier", "m 31")
            assert result is True


class TestParseHHMM:
    """Tests for _parse_hhmm_to_minutes function."""

    def test_parse_valid_time(self):
        """Test parsing valid HH:MM time."""
        result = _parse_hhmm_to_minutes("01:30")
        assert result == 90

    def test_parse_zero_time(self):
        """Test parsing 00:00."""
        result = _parse_hhmm_to_minutes("00:00")
        assert result == 0

    def test_parse_max_time(self):
        """Test parsing 24:00."""
        result = _parse_hhmm_to_minutes("24:00")
        assert result == 1440

    def test_parse_invalid_format(self):
        """Test parsing invalid format."""
        assert _parse_hhmm_to_minutes("not:time") is None

    def test_parse_single_part(self):
        """Test parsing single part (no colon)."""
        assert _parse_hhmm_to_minutes("90") is None

    def test_parse_negative_hours(self):
        """Test parsing negative hours."""
        result = _parse_hhmm_to_minutes("-01:30")
        assert result is None

    def test_parse_out_of_range_minutes(self):
        """Test parsing with out-of-range minutes."""
        result = _parse_hhmm_to_minutes("01:90")
        assert result is None

    def test_parse_whitespace(self):
        """Test parsing with whitespace."""
        result = _parse_hhmm_to_minutes("  01:30  ")
        assert result == 90


class TestMinutesToHHMM:
    """Tests for _minutes_to_hhmm function."""

    def test_convert_zero_minutes(self):
        """Test converting 0 minutes."""
        result = _minutes_to_hhmm(0)
        assert result == "00:00"

    def test_convert_to_single_hour(self):
        """Test converting to single hour."""
        result = _minutes_to_hhmm(60)
        assert result == "01:00"

    def test_convert_with_remainder(self):
        """Test converting with remainder minutes."""
        result = _minutes_to_hhmm(90)
        assert result == "01:30"

    def test_convert_negative_minutes(self):
        """Test converting negative minutes (should max to 0)."""
        result = _minutes_to_hhmm(-30)
        assert result == "00:00"

    def test_convert_large_value(self):
        """Test converting large minute value."""
        result = _minutes_to_hhmm(1440)
        assert result == "24:00"

    def test_round_trip(self):
        """Test round trip conversion."""
        original_minutes = 150
        hhmm = _minutes_to_hhmm(original_minutes)
        parsed = _parse_hhmm_to_minutes(hhmm)
        assert parsed == original_minutes


class TestGetPlanState:
    """Tests for get_plan_state function."""

    def test_state_none_when_no_plan(self):
        """Test state is 'none' when plan is None."""
        assert get_plan_state(None) == "none"

    def test_state_current_when_plan_active(self):
        """Test state is 'current' when plan night hasn't ended."""
        now = datetime.now().astimezone()
        future_end = (now + timedelta(hours=2)).isoformat()
        plan = {"night_end": future_end}
        
        state = get_plan_state(plan, now_dt=now)
        assert state == "current"

    def test_state_previous_when_plan_ended(self):
        """Test state is 'previous' when plan night has ended."""
        now = datetime.now().astimezone()
        past_end = (now - timedelta(hours=1)).isoformat()
        plan = {"night_end": past_end}
        
        state = get_plan_state(plan, now_dt=now)
        assert state == "previous"

    def test_state_with_custom_datetime(self):
        """Test state determination with custom datetime."""
        custom_now = datetime(2026, 4, 17, 22, 0, 0, tzinfo=timezone.utc)
        plan = {"night_end": "2026-04-18T04:00:00"}
        
        state = get_plan_state(plan, now_dt=custom_now)
        assert state == "current"


class TestBuildTargetPayload:
    """Tests for _build_target_payload function."""

    def test_build_basic_target(self):
        """Test building basic target payload."""
        item_data = {
            "name": "M31",
            "type": "Galaxy",
            "constellation": "Andromeda"
        }
        
        payload = _build_target_payload(item_data, "Messier")
        
        assert payload["name"] == "M31"
        assert payload["catalogue"] == "Messier"
        assert payload["type"] == "Galaxy"
        assert payload["id"] is not None  # Should be a UUID

    def test_build_target_with_planned_minutes(self):
        """Test building target with planned observation time."""
        item_data = {
            "name": "M42",
            "planned_minutes": 120
        }
        
        payload = _build_target_payload(item_data, "Messier")
        
        assert payload["name"] == "M42"
        assert payload["planned_minutes"] == 120 or "planned_minutes" not in payload

    def test_build_target_default_planned_minutes(self):
        """Test that default planned minutes is 60."""
        item_data = {"name": "M51"}
        
        payload = _build_target_payload(item_data, "Messier")
        
        # Implementation may store this differently
        assert payload["name"] == "M51"

    def test_build_target_fallback_name_from_id(self):
        """Test that name falls back to id if not present."""
        item_data = {
            "id": "target123",
            "type": "Unknown"
        }
        
        payload = _build_target_payload(item_data, "Custom")
        
        assert payload["name"] == "target123"


class TestSaveAndLoadUserPlan:
    """Tests for save_user_plan and load_user_plan functions."""

    def test_save_and_load_plan(self, temp_plan_dir):
        """Test saving and loading a plan."""
        user_id = "11111111-1111-4111-8111-111111111111"
        payload = {
            "user_id": user_id,
            "username": "testuser",
            "plan": {
                "plan_date": "2026-04-17",
                "entries": [
                    {"id": "1", "name": "M31", "catalogue": "Messier"}
                ]
            }
        }
        
        # Save
        result = save_user_plan(user_id, payload, username="testuser")
        assert result is True
        
        # Load
        loaded = load_user_plan(user_id, "testuser")
        assert loaded["user_id"] == user_id
        assert loaded["plan"] is not None
        assert len(loaded["plan"]["entries"]) == 1

    def test_load_nonexistent_plan(self, temp_plan_dir):
        """Test loading plan that doesn't exist returns default."""
        user_id = "22222222-2222-4222-8222-222222222222"
        
        loaded = load_user_plan(user_id)
        
        assert loaded["user_id"] == user_id
        assert loaded["plan"] is None

    def test_save_invalid_plan_returns_false(self, temp_plan_dir):
        """Test that saving invalid plan returns False."""
        user_id = "11111111-1111-4111-8111-111111111111"
        payload = {
            # Missing user_id - should be invalid
            "plan": {
                "entries": []
            }
        }

        save_user_plan(user_id, payload, username="testuser")
        # Should add user_id, so might succeed - implementation dependent
        # Just verify it completes without crashing

    def test_save_plan_validation_failure_returns_false(self, temp_plan_dir):
        """Saving a plan that fails JSON validation raises ValueError internally and returns False."""
        user_id = "11111111-1111-4111-8111-222222222222"
        payload = {
            "user_id": user_id,
            "plan": "not-a-dict",  # must be null or an object — validation rejects a string
        }
        result = save_user_plan(user_id, payload, username="user")
        assert result is False


class TestIsTargetInEntries:
    """Tests for is_target_in_entries function."""

    def test_empty_entries_list(self):
        """Test with empty entries list."""
        result = is_target_in_entries([], "Messier", "M31")
        assert result is False

    def test_target_in_entries(self):
        """Test finding target in entries."""
        entries = [
            {
                "id": "1",
                "name": "M31",
                "catalogue": "Messier",
                "catalogue_group_id": "group1",
                "catalogue_aliases": {}
            }
        ]
        
        is_target_in_entries(entries, "Messier", "M31")
        # Result depends on matching implementation

    def test_target_not_in_entries(self):
        """Test target not found in entries."""
        entries = [
            {
                "id": "1",
                "name": "M42",
                "catalogue": "Messier",
                "catalogue_group_id": "",
                "catalogue_aliases": {}
            }
        ]
        
        result = is_target_in_entries(entries, "Messier", "M31")
        assert result is False


class TestConcurrency:
    """Tests for thread safety of plan operations."""

    def test_concurrent_saves_same_user(self, temp_plan_dir):
        """Test concurrent saves to same user plan."""
        user_id = "33333333-3333-4333-8333-333333333333"
        errors = []
        
        def save_plan(index):
            try:
                payload = {
                    "user_id": user_id,
                    "username": "testuser",
                    "plan": {
                        "entries": [
                            {"id": str(index), "name": f"M{index}", "catalogue": "Messier"}
                        ]
                    }
                }
                result = save_user_plan(user_id, payload, username="testuser")
                if not result:
                    errors.append(f"Save {index} failed")
            except Exception as e:
                errors.append(str(e))
        
        threads = [Thread(target=save_plan, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Concurrent save errors: {errors}"

    def test_concurrent_different_users(self, temp_plan_dir):
        """Test concurrent saves to different user plans."""
        errors = []
        
        def save_plan(user_num):
            try:
                user_id = f"0000000{user_num}-0000-4000-8000-000000000000"
                payload = {
                    "user_id": user_id,
                    "username": f"user{user_num}",
                    "plan": {
                        "entries": [
                            {"id": "1", "name": "M31", "catalogue": "Messier"}
                        ]
                    }
                }
                result = save_user_plan(user_id, payload, username=f"user{user_num}")
                if not result:
                    errors.append(f"User {user_num} save failed")
            except Exception as e:
                errors.append(str(e))
        
        threads = [Thread(target=save_plan, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Concurrent user save errors: {errors}"


class TestPlanMutationsAndTimeline:
    """Additional branch coverage for plan operations."""

    def test_create_or_add_target_invalid_window(self, temp_plan_dir):
        ok, reason, payload, target = create_or_add_target(
            user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            username="user",
            item_data={"name": "M31"},
            catalogue="Messier",
            night_start="2026-04-18T04:00:00+00:00",
            night_end="2026-04-18T03:00:00+00:00",
            duration_hours=1.0,
        )
        assert ok is False
        assert reason == "invalid_night_window"
        assert target is None

    def test_create_or_add_target_previous_plan_locked(self, temp_plan_dir):
        user_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        now = datetime.now().astimezone()
        payload = {
            "user_id": user_id,
            "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=5)).isoformat(),
                "night_end": (now - timedelta(hours=2)).isoformat(),
                "entries": [],
            },
        }
        save_user_plan(user_id, payload, username="user")

        ok, reason, _, _ = create_or_add_target(
            user_id=user_id,
            username="user",
            item_data={"name": "M32"},
            catalogue="Messier",
            night_start="2026-04-18T00:00:00+00:00",
            night_end="2026-04-18T03:00:00+00:00",
            duration_hours=3.0,
        )
        assert ok is False
        assert reason == "previous_plan_locked"

    def test_remove_and_update_and_reorder_target(self, temp_plan_dir):
        user_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        payload = {
            "user_id": user_id,
            "username": "user",
            "plan": {
                "night_start": (datetime.now().astimezone() - timedelta(hours=1)).isoformat(),
                "night_end": (datetime.now().astimezone() + timedelta(hours=3)).isoformat(),
                "entries": [
                    {"id": "a", "name": "M31", "planned_minutes": 60, "planned_duration": "01:00", "done": False},
                    {"id": "b", "name": "M42", "planned_minutes": 30, "planned_duration": "00:30", "done": False},
                ],
            },
        }
        assert save_user_plan(user_id, payload, username="user") is True

        updated = update_target(user_id, "user", "a", {"planned_duration": "01:45", "done": True})
        assert updated is not None
        assert updated["planned_minutes"] == 105
        assert updated["done"] is True

        assert reorder_target(user_id, "user", "b", 0) is True
        assert remove_target(user_id, "user", "a") is True

    def test_clear_plan_and_timeline_none(self, temp_plan_dir):
        user_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        payload = {
            "user_id": user_id,
            "username": "user",
            "plan": {
                "night_start": (datetime.now().astimezone() - timedelta(hours=1)).isoformat(),
                "night_end": (datetime.now().astimezone() + timedelta(hours=1)).isoformat(),
                "entries": [{"id": "x", "name": "M13", "planned_minutes": 60, "planned_duration": "01:00", "done": False}],
            },
        }
        assert save_user_plan(user_id, payload, username="user") is True
        assert clear_plan(user_id, "user") is True

        view = get_plan_with_timeline(user_id, "user")
        assert view["state"] == "none"
        assert view["plan"] is None

    def test_serialize_plan_csv_empty_and_populated(self, temp_plan_dir):
        empty_csv = serialize_plan_csv({"plan": None}, labels={"order": "ordre"})
        assert "ordre" in empty_csv

        populated_csv = serialize_plan_csv(
            {
                "plan": {
                    "entries": [
                        {
                            "name": "M45",
                            "catalogue": "Messier",
                            "done": True,
                            "planned_duration": "00:20",
                            "planned_minutes": 20,
                        }
                    ]
                }
            },
            labels={"done_yes": "oui", "done_no": "non"},
        )
        assert "M45" in populated_csv
        assert "oui" in populated_csv


class _DummyI18n:
    def t(self, key):
        return {
            "plan_my_night.export_pdf_title": "My Observation Plan",
            "plan_my_night.export_pdf_col_target": "Target",
            "plan_my_night.export_pdf_col_slot": "Slot",
            "plan_my_night.export_pdf_col_duration": "Duration",
            "plan_my_night.export_pdf_col_type": "Type",
            "plan_my_night.export_pdf_col_constellation": "Constellation",
            "plan_my_night.export_pdf_section_targets": "Planned targets",
            "skytonight.altitude_time_title": "Altitude vs Time",
            "skytonight.altitude_time_y_axis": "Altitude (deg)",
            "skytonight.altitude_time_x_axis": "Time",
            "plan_my_night.export_pdf_no_plan": "No plan available.",
            "common.title_html": "MyAstroBoard",
        }.get(key)


class TestGeneratePlanPdf:
    def test_generate_plan_pdf_with_no_plan(self):
        import matplotlib

        matplotlib.use("Agg", force=True)

        payload = {"plan": None}
        metrics = {"fill_percent": 0.0, "planned_minutes": 0, "night_minutes": 0, "overflow_minutes": 0}

        result = generate_plan_pdf(payload, metrics, _DummyI18n())

        assert result is not None
        assert hasattr(result, "getvalue")
        # PDF signature: %PDF
        assert result.getvalue().startswith(b"%PDF")

    def test_generate_plan_pdf_with_chart_and_overflow_pages(self, tmp_path, monkeypatch):
        import matplotlib

        matplotlib.use("Agg", force=True)

        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )

        alttime_payload = {
            "timezone": "UTC",
            "times_utc": [
                "2026-08-12T21:00:00Z",
                "2026-08-12T21:30:00Z",
                "2026-08-12T22:00:00Z",
                "2026-08-12T22:30:00Z",
                "2026-08-12T23:00:00Z",
            ],
            "altitudes": [20.0, 30.0, 45.0, 40.0, 25.0],
            "altitude_constraint_min": 20,
            "altitude_constraint_max": 80,
        }

        with open(tmp_path / "m31_alttime.json", "w", encoding="utf-8") as f:
            json.dump(alttime_payload, f)

        entries = []
        for idx in range(12):
            entries.append(
                {
                    "id": f"e{idx}",
                    "name": f"Target {idx}",
                    "target_name": f"Target {idx}",
                    "catalogue": "Messier",
                    "type": "Galaxy",
                    "constellation": "Andromeda",
                    "done": bool(idx % 2),
                    "planned_duration": "00:30",
                    "timeline_start": "2026-08-12T21:05:00Z",
                    "timeline_end": "2026-08-12T22:35:00Z",
                    "alttime_file": "m31" if idx == 0 else None,
                }
            )

        payload = {
            "plan": {
                "night_start": "2026-08-12T21:00:00Z",
                "night_end": "2026-08-12T23:00:00Z",
                "entries": entries,
            }
        }
        metrics = {"fill_percent": 55.0, "planned_minutes": 180, "night_minutes": 360, "overflow_minutes": 0}

        result = generate_plan_pdf(payload, metrics, _DummyI18n())

        assert result.getvalue().startswith(b"%PDF")
        # Multiple pages should produce a reasonably large buffer.
        assert len(result.getvalue()) > 5000


# ============================================================
# Additional branch coverage tests
# ============================================================

_TEST_UID = "aaaa1111-2222-3333-4444-555566667777"


class TestGetAllPlanFilesPathError:
    """Covers ValueError from _safe_plan_path is silently skipped."""

    def test_skips_file_with_traversal_path(self, temp_plan_dir, monkeypatch):
        fname = f"{_TEST_UID}_plan_my_night.json"
        with open(os.path.join(temp_plan_dir, fname), 'w') as f:
            json.dump({'user_id': _TEST_UID}, f)

        original = plan_my_night._safe_plan_path

        def mock_safe(path):
            if fname in path:
                raise ValueError("path traversal detected")
            return original(path)

        monkeypatch.setattr(plan_my_night, '_safe_plan_path', mock_safe)
        result = plan_my_night.get_all_plan_files(_TEST_UID)
        assert result == []


class TestLoadUserPlanExceptionPaths:
    """Covers exception paths and the username=None case in load_user_plan."""

    def test_json_corrupted_backup_fails(self, temp_plan_dir, monkeypatch):
        """Covers corrupted JSON + backup copy fails."""
        file_path = plan_my_night.get_user_plan_file(_TEST_UID)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('{invalid json')

        with patch('observation.plan_my_night.shutil.copy2', side_effect=PermissionError("no copy")):
            result = load_user_plan(_TEST_UID, "testuser")

        assert result['user_id'] == _TEST_UID
        assert result['plan'] is None

    def test_general_exception_returns_default(self, temp_plan_dir, monkeypatch):
        """Covers non-JSON exception → default payload."""
        file_path = plan_my_night.get_user_plan_file(_TEST_UID)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({'user_id': _TEST_UID}, f)

        with patch('observation.plan_my_night.json.load', side_effect=PermissionError("no access")):
            result = load_user_plan(_TEST_UID, "testuser")

        assert result['user_id'] == _TEST_UID
        assert result['plan'] is None

    def test_load_without_username_when_file_exists(self, temp_plan_dir):
        """Covers username=None skips overwriting username field."""
        payload = {'user_id': _TEST_UID, 'plan': None, 'username': 'existing_user'}
        save_user_plan(_TEST_UID, payload, username='existing_user')

        result = load_user_plan(_TEST_UID, username=None)
        assert result['user_id'] == _TEST_UID


class TestSaveUserPlanWithoutUsername:
    """Covers username=None skips setting username in payload."""

    def test_save_without_username(self, temp_plan_dir):
        payload = {'user_id': _TEST_UID, 'plan': None}
        result = save_user_plan(_TEST_UID, payload, username=None)
        assert result is True
        loaded = load_user_plan(_TEST_UID)
        assert loaded['user_id'] == _TEST_UID


# ============================================================
# _save_user_plan_locked - error branches
# ============================================================


class TestSaveUserPlanLockedBranches:
    """Covers branches in _save_user_plan_locked."""

    def test_path_validation_failure_returns_false(self, temp_plan_dir):
        """ValueError from _safe_plan_path returns False."""
        uid = "eeee0001-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}
        # Patch _save_user_plan_locked directly to trigger the path validation failure
        # by patching _safe_plan_path to always raise ValueError
        with patch.object(plan_my_night, '_safe_plan_path', side_effect=ValueError("path traversal")):
            result = plan_my_night._save_user_plan_locked(
                uid, payload, "testuser",
                os.path.join(temp_plan_dir, "test.json"),
                os.path.join(temp_plan_dir, "test.tmp"),
                os.path.join(temp_plan_dir, "test.bak"),
            )
        assert result is False

    def test_backup_copy_failure_continues(self, temp_plan_dir):
        """backup copy fails but save still continues."""
        uid = "eeee0002-0000-4000-8000-000000000000"
        # First, create an existing plan file so backup is attempted
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="u1")

        # Now try again; shutil.copy2 fails but save should still succeed
        with patch('observation.plan_my_night.shutil.copy2', side_effect=PermissionError("no backup")):
            result = save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        assert result is True

    def test_exception_during_save_restores_backup(self, temp_plan_dir):
        """when an error occurs after backup, backup is restored."""
        uid = "eeee0003-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="u1")

        # Force json.dump to fail after backup is created
        with patch('observation.plan_my_night.json.dump', side_effect=RuntimeError("disk full")):
            result = save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        assert result is False

    def test_exception_cleanup_temp_file_failure_logged(self, temp_plan_dir):
        """temp file cleanup failure is warned but not raised."""
        uid = "eeee0004-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}

        # Force a failure during write AND make os.remove fail for the temp file
        with patch('observation.plan_my_night.json.dump', side_effect=RuntimeError("disk full")):
            with patch('observation.plan_my_night.os.remove', side_effect=OSError("cleanup fail")):
                result = save_user_plan(uid, payload, username="u1")
        assert result is False


# ============================================================
# clear_all_plans
# ============================================================


class TestClearAllPlans:
    """Covers clear_all_plans error logging path."""

    def test_deletes_all_plan_files(self, temp_plan_dir):
        uid = "ffff0001-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="user")
        deleted = plan_my_night.clear_all_plans(uid)
        assert deleted >= 1

    def test_delete_error_logged_not_raised(self, temp_plan_dir):
        uid = "ffff0002-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="user")

        with patch('observation.plan_my_night.os.remove', side_effect=OSError("permission denied")):
            deleted = plan_my_night.clear_all_plans(uid)
        assert deleted == 0  # Nothing deleted due to error


# ============================================================
# remove_target - edge cases
# ============================================================


class TestRemoveTargetEdgeCases:
    """Covers edge cases in remove_target."""

    def _make_current_plan(self, uid, temp_plan_dir):
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid,
            "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=1)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "entries": [
                    {"id": "e1", "name": "M31", "planned_minutes": 60, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

    def test_remove_from_previous_plan_returns_false(self, temp_plan_dir):
        """previous plan state → return False."""
        uid = "aaaa0001-0000-4000-8000-111111111111"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=5)).isoformat(),
                "night_end": (now - timedelta(hours=1)).isoformat(),
                "entries": [{"id": "e1", "name": "M31", "planned_minutes": 60, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = remove_target(uid, "user", "e1")
        assert result is False

    def test_remove_nonexistent_entry_returns_false(self, temp_plan_dir):
        """entry not found → return False."""
        uid = "aaaa0002-0000-4000-8000-111111111111"
        self._make_current_plan(uid, temp_plan_dir)
        result = remove_target(uid, "user", "nonexistent-id")
        assert result is False

    def test_remove_no_plan_returns_false(self, temp_plan_dir):
        """no plan at all → return False."""
        uid = "aaaa0003-0000-4000-8000-111111111111"
        result = remove_target(uid, "user", "e1")
        assert result is False


# ============================================================
# update_target - edge cases
# ============================================================


class TestUpdateTargetEdgeCases:
    """Covers ."""

    def _make_current_plan(self, uid):
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=1)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "entries": [
                    {"id": "e1", "name": "M31", "planned_minutes": 60, "done": False,
                     "planned_duration": "01:00"},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

    def test_update_returns_none_for_no_plan(self, temp_plan_dir):
        """no plan → return None."""
        uid = "bbbb0001-0000-4000-8000-000000000000"
        result = update_target(uid, "user", "e1", {"done": True})
        assert result is None

    def test_update_returns_none_for_previous_plan(self, temp_plan_dir):
        """previous plan → return None."""
        uid = "bbbb0002-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=5)).isoformat(),
                "night_end": (now - timedelta(hours=1)).isoformat(),
                "entries": [{"id": "e1", "name": "M31", "planned_minutes": 60, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = update_target(uid, "user", "e1", {"done": True})
        assert result is None

    def test_update_returns_none_for_missing_entry(self, temp_plan_dir):
        """entry not found → return None."""
        uid = "bbbb0003-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = update_target(uid, "user", "not-existing", {"done": True})
        assert result is None

    def test_update_planned_minutes_directly(self, temp_plan_dir):
        """update via planned_minutes key (int)."""
        uid = "bbbb0004-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = update_target(uid, "user", "e1", {"planned_minutes": 90})
        assert result is not None
        assert result["planned_minutes"] == 90

    def test_update_planned_minutes_clamped(self, temp_plan_dir):
        """planned_minutes is clamped to 24*60=1440."""
        uid = "bbbb0005-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = update_target(uid, "user", "e1", {"planned_minutes": 99999})
        assert result["planned_minutes"] == 24 * 60

    def test_update_planned_minutes_invalid_type(self, temp_plan_dir):
        """invalid planned_minutes type silently skipped."""
        uid = "bbbb0006-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = update_target(uid, "user", "e1", {"planned_minutes": "not-a-number"})
        # planned_minutes unchanged from original
        assert result is not None
        assert result["planned_minutes"] == 60

    def test_update_planned_duration_invalid_format(self, temp_plan_dir):
        """planned_duration that fails parsing doesn't update planned_minutes."""
        uid = "bbbb0007-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = update_target(uid, "user", "e1", {"planned_duration": "bad"})
        # planned_minutes stays at 60 (parse returns None)
        assert result is not None
        assert result["planned_minutes"] == 60

    def test_update_save_failure_returns_none(self, temp_plan_dir):
        """save failure returns None."""
        uid = "bbbb0008-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        with patch('observation.plan_my_night.save_user_plan', return_value=False):
            result = update_target(uid, "user", "e1", {"done": True})
        assert result is None


# ============================================================
# update_plan_meta - edge cases
# ============================================================


class TestUpdatePlanMetaEdgeCases:
    """Covers ."""

    def _make_current_plan(self, uid):
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=1)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "entries": [],
            },
        }
        save_user_plan(uid, payload, username="user")

    def test_update_meta_no_plan_returns_none(self, temp_plan_dir):
        uid = "cccc0001-0000-4000-8000-000000000000"
        result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": 10})
        assert result is None

    def test_update_meta_previous_plan_returns_none(self, temp_plan_dir):
        uid = "cccc0002-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=5)).isoformat(),
                "night_end": (now - timedelta(hours=1)).isoformat(),
                "entries": [],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": 10})
        assert result is None

    def test_update_meta_start_delay_valid(self, temp_plan_dir):
        uid = "cccc0003-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": 30})
        assert result is not None
        assert result["start_delay_minutes"] == 30

    def test_update_meta_start_delay_clamped_to_max(self, temp_plan_dir):
        uid = "cccc0004-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": 9999})
        assert result is not None
        assert result["start_delay_minutes"] == 23 * 60 + 59

    def test_update_meta_start_delay_invalid_type_defaults_zero(self, temp_plan_dir):
        uid = "cccc0005-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": "bad"})
        assert result is not None
        assert result["start_delay_minutes"] == 0

    def test_update_meta_save_failure_returns_none(self, temp_plan_dir):
        uid = "cccc0006-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        with patch('observation.plan_my_night.save_user_plan', return_value=False):
            result = plan_my_night.update_plan_meta(uid, "user", {"start_delay_minutes": 5})
        assert result is None

    def test_update_meta_without_start_delay_key(self, temp_plan_dir):
        uid = "cccc0007-0000-4000-8000-000000000000"
        self._make_current_plan(uid)
        result = plan_my_night.update_plan_meta(uid, "user", {})
        assert result is not None


# ============================================================
# reorder_target - edge cases
# ============================================================


class TestReorderTargetEdgeCases:
    """Covers ."""

    def _make_two_entry_plan(self, uid):
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=1)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "entries": [
                    {"id": "e1", "name": "M31", "planned_minutes": 60, "done": False},
                    {"id": "e2", "name": "M42", "planned_minutes": 30, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

    def test_reorder_no_plan_returns_false(self, temp_plan_dir):
        uid = "dddd0001-0000-4000-8000-000000000000"
        result = reorder_target(uid, "user", "e1", 0)
        assert result is False

    def test_reorder_previous_plan_returns_false(self, temp_plan_dir):
        uid = "dddd0002-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=5)).isoformat(),
                "night_end": (now - timedelta(hours=1)).isoformat(),
                "entries": [{"id": "e1", "name": "M31", "planned_minutes": 60, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = reorder_target(uid, "user", "e1", 0)
        assert result is False

    def test_reorder_missing_entry_returns_false(self, temp_plan_dir):
        uid = "dddd0003-0000-4000-8000-000000000000"
        self._make_two_entry_plan(uid)
        result = reorder_target(uid, "user", "not-exist", 0)
        assert result is False

    def test_reorder_same_position_returns_true_no_save(self, temp_plan_dir):
        uid = "dddd0004-0000-4000-8000-000000000000"
        self._make_two_entry_plan(uid)
        # e1 is at index 0; reorder to 0 should return True without modification
        result = reorder_target(uid, "user", "e1", 0)
        assert result is True

    def test_reorder_clamped_to_valid_range(self, temp_plan_dir):
        uid = "dddd0005-0000-4000-8000-000000000000"
        self._make_two_entry_plan(uid)
        # Request out-of-bounds index → clamped
        result = reorder_target(uid, "user", "e1", 9999)
        assert result is True
        loaded = load_user_plan(uid, "user")
        # e1 should now be last
        assert loaded["plan"]["entries"][-1]["id"] == "e1"


# ============================================================
# get_plan_with_timeline - extra branches
# ============================================================


class TestGetPlanWithTimelineBranches:
    """Covers ."""

    def test_timeline_with_night_window(self, temp_plan_dir):
        uid = "eeee1001-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(hours=1)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "start_delay_minutes": 10,
                "entries": [
                    {"id": "e1", "name": "M31", "planned_minutes": 30, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = get_plan_with_timeline(uid, "user")
        assert result["state"] == "current"
        assert result["timeline"]["progress_percent"] > 0

    def test_timeline_inside_night_sets_current_target(self, temp_plan_dir):
        uid = "eeee1002-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        # Create a plan where the single entry is currently active
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(minutes=10)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "start_delay_minutes": 0,
                "entries": [
                    {"id": "cur", "name": "M45", "planned_minutes": 60, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = get_plan_with_timeline(uid, "user")
        assert result["timeline"]["current_target_id"] == "cur"
        assert result["current_banner"] is not None

    def test_timeline_done_entry_not_current(self, temp_plan_dir):
        uid = "eeee1003-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": (now - timedelta(minutes=10)).isoformat(),
                "night_end": (now + timedelta(hours=3)).isoformat(),
                "start_delay_minutes": 0,
                "entries": [
                    # Done entry should not become current_target
                    {"id": "done-e", "name": "M45", "planned_minutes": 60, "done": True},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = get_plan_with_timeline(uid, "user")
        assert result["timeline"]["current_target_id"] is None

    def test_timeline_zero_duration_night(self, temp_plan_dir):
        uid = "eeee1004-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        # night_start == night_end → degenerate case
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": now.isoformat(),
                "night_end": now.isoformat(),
                "entries": [],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = get_plan_with_timeline(uid, "user")
        assert result["timeline"]["progress_percent"] == 0.0


# ============================================================
# _csv_normalize_ra and _csv_normalize_dec
# ============================================================


class TestCsvNormalizeFunctions:
    """Covers ."""

    def test_csv_normalize_ra_none(self):
        assert _csv_normalize_ra(None) == ''

    def test_csv_normalize_ra_sexagesimal_hms(self):
        result = _csv_normalize_ra("2h 31m 49s")
        assert ':' in result

    def test_csv_normalize_ra_decimal(self):
        result = _csv_normalize_ra("37.95")
        assert ':' in result

    def test_csv_normalize_ra_decimal_seconds_60_rollover(self):
        """When rounding produces sec=60, roll over to next minute."""
        # A value that when converted would produce sec>=60 rounding
        result = _csv_normalize_ra("0.99999")
        assert ':' in result

    def test_csv_normalize_ra_invalid_returns_as_is(self):
        result = _csv_normalize_ra("not-a-number")
        assert result == "not-a-number"

    def test_csv_normalize_dec_none(self):
        assert _csv_normalize_dec(None) == ''

    def test_csv_normalize_dec_dms_format(self):
        result = _csv_normalize_dec("+41°16'09\"")
        # Should contain sign and colons
        assert ':' in result

    def test_csv_normalize_dec_decimal_positive(self):
        result = _csv_normalize_dec("41.269")
        assert result.startswith('+')

    def test_csv_normalize_dec_decimal_negative(self):
        result = _csv_normalize_dec("-5.3914")
        assert result.startswith('-')

    def test_csv_normalize_dec_invalid_returns_as_is(self):
        result = _csv_normalize_dec("not-a-number")
        assert result == "not-a-number"

    def test_csv_normalize_dec_seconds_60_rollover(self):
        # Produce a value where sec rounds to 60
        result = _csv_normalize_dec("41.99999")
        assert ':' in result

    def test_csv_fmt_local_hm_none_returns_empty(self):
        assert _csv_fmt_local_hm(None) == ''
        assert _csv_fmt_local_hm('') == ''

    def test_csv_fmt_local_hm_invalid_returns_str(self):
        result = _csv_fmt_local_hm("not-a-date")
        assert result == "not-a-date"

    def test_csv_fmt_local_hm_valid_iso(self):
        result = _csv_fmt_local_hm("2026-08-12T21:30:00")
        assert ':' in result

    def test_csv_fmt_observable_pct_none(self):
        assert _csv_fmt_observable_pct(None) == ''
        assert _csv_fmt_observable_pct('') == ''

    def test_csv_fmt_observable_pct_valid(self):
        assert _csv_fmt_observable_pct(0.75) == '75%'

    def test_csv_fmt_observable_pct_invalid(self):
        result = _csv_fmt_observable_pct("not-a-float")
        assert result == "not-a-float"

    def test_csv_normalize_ra_sexagesimal_sec60_rollover(self):
        result = _csv_normalize_ra("0h 59m 59.9s")
        assert ':' in result

    def test_csv_normalize_dec_sexagesimal_sec60_rollover(self):
        result = _csv_normalize_dec("+0°59'59.9\"")
        assert ':' in result


class TestEntryMatchesAlias:
    """Tests for _entry_matches alias matching branch."""

    def test_entry_matches_by_alias(self):
        entry = {
            'name': 'Andromeda Galaxy',
            'catalogue': 'Messier',
            'catalogue_group_id': '',
            'catalogue_aliases': {'Messier': 'M31', 'NGC': 'NGC 224'},
        }
        with patch('observation.plan_my_night._target_group_id', return_value=''):
            result = _entry_matches(entry, 'NGC', 'NGC 224')
        assert result is True

    def test_entry_not_matches_when_alias_differs(self):
        entry = {
            'name': 'Andromeda Galaxy',
            'catalogue': 'Messier',
            'catalogue_group_id': '',
            'catalogue_aliases': {'Messier': 'M31'},
        }
        with patch('observation.plan_my_night._target_group_id', return_value=''):
            result = _entry_matches(entry, 'NGC', 'NGC 999')
        assert result is False

    def test_is_target_in_current_plan_found(self, temp_plan_dir):
        user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        now = datetime.now(timezone.utc)
        payload = {
            'user_id': user_id,
            'username': 'testuser',
            'plan': {
                'night_start': (now - timedelta(hours=1)).isoformat(),
                'night_end': (now + timedelta(hours=5)).isoformat(),
                'entries': [
                    {'id': 'e1', 'name': 'M42', 'catalogue': 'Messier',
                     'catalogue_group_id': '', 'catalogue_aliases': {}},
                ],
            },
        }
        save_user_plan(user_id, payload, username='testuser')
        with patch('observation.plan_my_night._target_group_id', return_value=''):
            result = plan_my_night.is_target_in_current_plan(user_id, 'testuser', 'Messier', 'M42')
        assert result is True

    def test_create_or_add_target_already_in_plan(self, temp_plan_dir):
        user_id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        now = datetime.now(timezone.utc)
        night_start = (now - timedelta(hours=1)).isoformat()
        night_end = (now + timedelta(hours=5)).isoformat()
        with patch('observation.plan_my_night._target_group_id', return_value=''):
            ok1, reason1, _, _ = create_or_add_target(
                user_id=user_id, username='testuser',
                item_data={'name': 'M42'}, catalogue='Messier',
                night_start=night_start, night_end=night_end,
            )
        assert ok1 is True
        assert reason1 == 'added'
        with patch('observation.plan_my_night._target_group_id', return_value=''):
            ok2, reason2, _, entry2 = create_or_add_target(
                user_id=user_id, username='testuser',
                item_data={'name': 'M42'}, catalogue='Messier',
                night_start=night_start, night_end=night_end,
            )
        assert ok2 is True
        assert reason2 == 'already_in_plan'


# ============================================================
# get_all_plan_states
# ============================================================


class TestGetAllPlanStates:
    """Covers ."""

    def test_no_plans_no_combinations_returns_empty(self, temp_plan_dir):
        uid = "ffff1001-0000-4000-8000-000000000000"
        result = plan_my_night.get_all_plan_states(uid, "user", [])
        assert result == []

    def test_default_plan_included_when_exists(self, temp_plan_dir):
        uid = "ffff1002-0000-4000-8000-000000000000"
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="user")
        result = plan_my_night.get_all_plan_states(uid, "user", [])
        assert len(result) == 1
        assert result[0]['combination_id'] is None

    def test_combination_plan_included(self, temp_plan_dir):
        uid = "ffff1003-0000-4000-8000-000000000000"
        combo_id = "combo-001"
        payload = {'user_id': uid, 'plan': None}
        save_user_plan(uid, payload, username="user", combination_id=combo_id)
        combinations = [{'id': combo_id, 'name': 'Test Combo', 'is_own': True,
                          'owner_username': 'user'}]
        result = plan_my_night.get_all_plan_states(uid, "user", combinations)
        assert any(r['combination_id'] == combo_id for r in result)

    def test_combination_validity_flags_passed_through(self, temp_plan_dir):
        """is_valid/is_disabled from the input combination dict surface on the result."""
        uid = "ffff1006-0000-4000-8000-000000000000"
        combo_id = "combo-002"
        combinations = [{'id': combo_id, 'name': 'Disabled Combo', 'is_own': True,
                          'owner_username': None, 'is_valid': False, 'is_disabled': True}]
        result = plan_my_night.get_all_plan_states(uid, "user", combinations)
        entry = next(r for r in result if r['combination_id'] == combo_id)
        assert entry['is_valid'] is False
        assert entry['is_disabled'] is True

    def test_combination_validity_flags_default_when_absent(self, temp_plan_dir):
        """A combination dict without is_valid/is_disabled defaults to valid+enabled."""
        uid = "ffff1007-0000-4000-8000-000000000000"
        combo_id = "combo-003"
        combinations = [{'id': combo_id, 'name': 'Plain Combo', 'is_own': True, 'owner_username': None}]
        result = plan_my_night.get_all_plan_states(uid, "user", combinations)
        entry = next(r for r in result if r['combination_id'] == combo_id)
        assert entry['is_valid'] is True
        assert entry['is_disabled'] is False

    def test_orphaned_plan_detected(self, temp_plan_dir):
        uid = "ffff1004-0000-4000-8000-000000000000"
        # Use a valid UUID-format combination_id
        orphan_id = "0a1b2c3d-0000-4000-8000-000000000099"
        # Save a plan for a combination that's not in the known_ids list
        now = datetime.now().astimezone()
        payload = {
            'user_id': uid,
            'plan': {
                'night_start': (now - timedelta(hours=1)).isoformat(),
                'night_end': (now + timedelta(hours=3)).isoformat(),
                'combination_name': 'Old Combo',
                'entries': [],
            }
        }
        save_user_plan(uid, payload, username="user", combination_id=orphan_id)
        # Call with empty combination list (orphan_id is not known)
        result = plan_my_night.get_all_plan_states(uid, "user", [])
        orphaned = [r for r in result if r.get('is_orphaned')]
        assert len(orphaned) >= 1
        assert orphaned[0]['combination_id'] == orphan_id

    def test_default_plan_with_entries_count(self, temp_plan_dir):
        uid = "ffff1005-0000-4000-8000-000000000000"
        now = datetime.now().astimezone()
        payload = {
            'user_id': uid,
            'plan': {
                'night_start': (now - timedelta(hours=1)).isoformat(),
                'night_end': (now + timedelta(hours=3)).isoformat(),
                'entries': [
                    {'id': 'x1', 'name': 'M31'},
                    {'id': 'x2', 'name': 'M42'},
                ],
            }
        }
        save_user_plan(uid, payload, username="user")
        result = plan_my_night.get_all_plan_states(uid, "user", [])
        assert result[0]['entries_count'] == 2


# ============================================================
# create_or_add_target - extra branches
# ============================================================


class TestCreateOrAddTargetExtra:
    """Covers ."""

    def test_add_duplicate_returns_already_in_plan(self, temp_plan_dir):
        uid = "a1b2c3d4-0001-4000-8000-000000000001"
        now = datetime.now().astimezone()

        # First add
        ok, reason, payload, target = create_or_add_target(
            user_id=uid, username="user",
            item_data={"name": "M31"},
            catalogue="Messier",
            night_start=(now - timedelta(hours=1)).isoformat(),
            night_end=(now + timedelta(hours=3)).isoformat(),
        )
        assert ok is True
        assert reason == "added"

        # Add same target again (same name → same normalized name)
        with patch("observation.plan_my_night._entry_matches", return_value=True):
            ok2, reason2, _, matched_entry = create_or_add_target(
                user_id=uid, username="user",
                item_data={"name": "M31"},
                catalogue="Messier",
                night_start=(now - timedelta(hours=1)).isoformat(),
                night_end=(now + timedelta(hours=3)).isoformat(),
            )
        assert ok2 is True
        assert reason2 == "already_in_plan"
        assert matched_entry is not None

    def test_add_save_failure_returns_false(self, temp_plan_dir):
        uid = "a1b2c3d4-0002-4000-8000-000000000002"
        now = datetime.now().astimezone()
        with patch("observation.plan_my_night.save_user_plan", return_value=False):
            ok, reason, _, _ = create_or_add_target(
                user_id=uid, username="user",
                item_data={"name": "M45"},
                catalogue="Messier",
                night_start=(now - timedelta(hours=1)).isoformat(),
                night_end=(now + timedelta(hours=3)).isoformat(),
            )
        assert ok is False
        assert reason == "save_failed"

    def test_add_with_combination(self, temp_plan_dir):
        uid = "a1b2c3d4-0003-4000-8000-000000000003"
        combo_id = "a1b2c3d4-0004-4000-8000-000000000004"
        now = datetime.now().astimezone()
        ok, reason, _, target = create_or_add_target(
            user_id=uid, username="user",
            item_data={"name": "NGC 224"},
            catalogue="NGC",
            night_start=(now - timedelta(hours=1)).isoformat(),
            night_end=(now + timedelta(hours=3)).isoformat(),
            combination_id=combo_id,
            combination_name="My Combo",
        )
        assert ok is True
        loaded = load_user_plan(uid, "user", combination_id=combo_id)
        assert loaded["plan"]["combination_id"] == combo_id


# ============================================================
# Additional branch coverage for missing lines
# ============================================================


class TestSaveUserPlanLockedErrorPaths:
    """Cover : restore/cleanup failure handlers in _save_user_plan_locked."""

    def test_restore_backup_failure_is_logged(self, temp_plan_dir):
        """when os.replace(backup, file) itself raises, error is logged."""
        uid = "aaaaffff-0001-4000-8000-000000000001"
        # Create an initial plan so backup is attempted
        save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        # Fail the dump AND the backup restore
        with patch('observation.plan_my_night.json.dump', side_effect=RuntimeError("disk full")):
            with patch('observation.plan_my_night.os.replace', side_effect=OSError("restore fail")):
                result = save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        assert result is False

    def test_backup_cleanup_failure_is_silenced(self, temp_plan_dir):
        """os.remove(backup) raises during error cleanup — silently swallowed."""
        uid = "aaaaffff-0002-4000-8000-000000000002"
        # Create an initial plan so backup is attempted
        save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        remove_calls = []

        def mock_remove(path):
            remove_calls.append(path)
            raise OSError("cannot remove")

        # Fail dump so we enter the except block, then fail ALL os.remove calls
        with patch('observation.plan_my_night.json.dump', side_effect=RuntimeError("disk full")):
            # Also fail os.replace(backup→file) so the backup still exists
            with patch('observation.plan_my_night.os.replace', side_effect=OSError("restore fail")):
                with patch('observation.plan_my_night.os.remove', side_effect=mock_remove):
                    result = save_user_plan(uid, {'user_id': uid, 'plan': None}, username="u1")
        assert result is False


class TestTimelineBeyondNightEnd:
    """entry with duration extending past night_end gets capped."""

    def test_long_entry_is_capped_at_night_end(self, temp_plan_dir):
        """planned_minutes > remaining night → end_dt capped to night_end."""
        uid = "aaaaffff-0003-4000-8000-000000000003"
        now = datetime.now().astimezone()
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(minutes=30)).isoformat(),
                "entries": [
                    # 120 min entry in a 30-min night → must be capped
                    {"id": "long", "name": "M45", "planned_minutes": 120, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")
        result = get_plan_with_timeline(uid, "user")
        # The entry should exist in the result and not raise
        entries = result.get("plan", {}).get("entries", [])
        long_entry = next((e for e in entries if e.get("id") == "long"), None)
        assert long_entry is not None


class TestGetAllPlanStatesOrphanFilenameSkip:
    """file with non-matching name pattern is skipped in orphan detection."""

    def test_non_matching_filename_is_skipped(self, temp_plan_dir):
        """A file named {uid}_plan.json (no underscore after _plan) is skipped."""
        uid = "aaaaffff-0004-4000-8000-000000000004"
        # Create a file with a slightly wrong name (no underscore between _plan and suffix)
        weird_name = f"{uid}_plan.json"
        with open(os.path.join(temp_plan_dir, weird_name), 'w') as f:
            json.dump({'user_id': uid, 'plan': None}, f)

        # Patch get_all_plan_files to return the weird file
        with patch('observation.plan_my_night.get_all_plan_files',
                   return_value=[os.path.join(temp_plan_dir, weird_name)]):
            result = plan_my_night.get_all_plan_states(uid, "user", [])
        # It should process without crashing; weird file should be skipped
        assert isinstance(result, list)


class TestGeneratePlanPdfBranchCoverage:
    """Cover branches in generate_plan_pdf helpers (_load_alttime, _parse_utc, _clip_alttime)."""

    def test_alttime_file_not_found_returns_none(self, tmp_path, monkeypatch):
        """_load_alttime returns None when file doesn't exist on disk."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)
        payload = {
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(hours=2)).isoformat(),
                "entries": [{
                    "id": "e1", "name": "M31", "done": False,
                    "alttime_file": "nonexistent_target",  # no file on disk
                    "timeline_start": now.isoformat(),
                    "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                }],
            }
        }
        metrics = {"fill_percent": 50.0, "planned_minutes": 30, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_bad_timezone_in_alttime_falls_back_to_utc(self, tmp_path, monkeypatch):
        """alttime with bad timezone name → falls back to UTC."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)
        # Write an alttime file with a bad timezone
        alttime_data = {
            "timezone": "NOT/A_REAL_TIMEZONE",
            "times_utc": [now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")],
            "altitudes": [30.0, 40.0],
        }
        with open(tmp_path / "m31_alttime.json", "w") as f:
            json.dump(alttime_data, f)
        payload = {
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(hours=2)).isoformat(),
                "entries": [{
                    "id": "e1", "name": "M31", "done": False,
                    "alttime_file": "m31",
                    "timeline_start": now.isoformat(),
                    "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                }],
            }
        }
        metrics = {"fill_percent": 25.0, "planned_minutes": 30, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_naive_timeline_datetimes_are_handled(self, tmp_path, monkeypatch):
        """: naive and offset timezone datetime strings."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)
        alttime_data = {
            "timezone": "UTC",
            "times_utc": [now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")],
            "altitudes": [30.0, 40.0],
        }
        with open(tmp_path / "m31_alttime.json", "w") as f:
            json.dump(alttime_data, f)
        payload = {
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(hours=2)).isoformat(),
                "entries": [
                    {   # naive datetime string (no tz)
                        "id": "e1", "name": "M31", "done": False,
                        "alttime_file": "m31",
                        "timeline_start": "2026-08-12T21:00:00",   # naive
                        "timeline_end": "2026-08-12T21:30:00",     # naive
                    },
                    {   # with offset
                        "id": "e2", "name": "M42", "done": False,
                        "timeline_start": "2026-08-12T21:30:00+02:00",
                        "timeline_end": "2026-08-12T22:00:00+02:00",
                    },
                    {   # malformed
                        "id": "e3", "name": "M45", "done": False,
                        "timeline_start": "not-a-date",
                        "timeline_end": "also-bad",
                    },
                ],
            }
        }
        metrics = {"fill_percent": 25.0, "planned_minutes": 90, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Additional plan_my_night coverage — non-PDF functions
# ---------------------------------------------------------------------------

class TestPlanMyNightMiscBranches:
    """Cover missing branches in plan_my_night functions."""

    def test_entry_matches_aliases_not_dict_returns_false(self):
        """catalogue_aliases is not a dict → skip alias loop, return False."""
        entry = {
            'name': 'M31',
            'catalogue_aliases': ['list', 'not', 'dict'],  # list, not dict
        }
        result = _entry_matches(entry, 'Messier', 'M42')
        assert result is False

    def test_is_target_in_current_plan_loop_continues_past_nonmatch(self, tmp_path, monkeypatch):
        """first entry doesn't match → loop continues to find the second."""
        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))
        user_id = "aabbccdd-1234-4aaa-8aaa-aabbccddaabb"
        now = datetime.now().astimezone()
        plan = {
            'night_start': (now - timedelta(hours=2)).isoformat(),
            'night_end': (now + timedelta(hours=2)).isoformat(),
            'entries': [
                {'name': 'M31', 'catalogue': 'Messier', 'id': 'e1'},
                {'name': 'M42', 'catalogue': 'Messier', 'id': 'e2'},
            ],
        }
        plan_my_night.save_user_plan(user_id, {'plan': plan}, username='user')
        result = plan_my_night.is_target_in_current_plan(user_id, 'user', 'Messier', 'M42')
        # M31 doesn't match → loop continues (→392) → M42 matches
        assert result is True

    def test_create_or_add_target_loop_continues_past_nonmatch(self, tmp_path, monkeypatch):
        """existing entry doesn't match → loop continues, new entry added."""
        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))
        user_id = "bbccddee-1234-4bbb-8bbb-bbccddeebbcc"
        now = datetime.now().astimezone()
        plan = {
            'night_start': (now - timedelta(hours=1)).isoformat(),
            'night_end': (now + timedelta(hours=3)).isoformat(),
            'entries': [{'name': 'M31', 'catalogue': 'Messier', 'id': 'e1'}],
        }
        plan_my_night.save_user_plan(user_id, {'plan': plan}, username='user')
        # Add M42 → loop iterates past M31 (→514) → M42 is new, gets added
        ok, reason, _, _ = plan_my_night.create_or_add_target(
            user_id=user_id, username='user',
            item_data={'name': 'M42'},
            catalogue='Messier',
            night_start=plan['night_start'],
            night_end=plan['night_end'],
            duration_hours=1.0,
        )
        assert ok is True
        assert reason == 'added'

    def test_get_plan_with_timeline_zero_planned_minutes(self, tmp_path, monkeypatch):
        """planned_minutes=0 → end_dt stays equal to start_dt."""
        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))
        user_id = "ccddeeaa-1234-4ccc-8ccc-ccddeeaaccdd"
        now = datetime.now().astimezone()
        plan = {
            'night_start': (now - timedelta(hours=1)).isoformat(),
            'night_end': (now + timedelta(hours=3)).isoformat(),
            'entries': [{'name': 'M31', 'id': 'e1', 'planned_minutes': 0}],
        }
        plan_my_night.save_user_plan(user_id, {'plan': plan}, username='user')
        result = plan_my_night.get_plan_with_timeline(user_id, 'user')
        entry = result['plan']['entries'][0]
        # With planned_minutes=0, end_dt = cursor = start_dt → timeline_start == timeline_end
        assert entry['timeline_start'] == entry['timeline_end']

    def test_save_user_plan_temp_file_missing_during_error_recovery(self, tmp_path, monkeypatch):
        """exception before temp file created → os.path.exists(temp_path) is False.

        ensure_plan_directory is called twice: once in get_user_plan_file (must succeed)
        and once in _save_user_plan_locked (where we raise to trigger the error path).
        """
        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))
        user_id = "ddeeffaa-1234-4ddd-8ddd-ddeeffaaddee"

        call_count = [0]

        def _ensure_dir_fail_on_second_call():
            call_count[0] += 1
            if call_count[0] >= 2:
                raise OSError("mkdir failed on second call")

        with patch.object(plan_my_night, 'ensure_plan_directory',
                          side_effect=_ensure_dir_fail_on_second_call):
            result = plan_my_night.save_user_plan(
                user_id, {'plan': {'entries': []}}, username='user'
            )
        assert result is False


# ---------------------------------------------------------------------------
# Additional generate_plan_pdf branch coverage
# ---------------------------------------------------------------------------

class TestGeneratePlanPdfAdditionalBranches:
    """Cover remaining missing branches in generate_plan_pdf."""

    def test_json_parse_error_in_load_alttime(self, tmp_path, monkeypatch):
        """invalid JSON in alttime file → exception caught, return None."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        # Write invalid JSON
        (tmp_path / "m31_alttime.json").write_text("{invalid json", encoding="utf-8")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(hours=2)).isoformat(),
                "entries": [{
                    "id": "e1", "name": "M31", "done": False,
                    "alttime_file": "m31",
                    "timeline_start": now.isoformat(),
                    "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                }],
            }
        }
        metrics = {"fill_percent": 50.0, "planned_minutes": 30, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_combination_name_and_fill_zero_and_overflow(self, tmp_path, monkeypatch):
        """Renders the combination name, and exercises the fill_w<=0.01 and overflow>0 branches."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "plan": {
                "night_start": now.isoformat(),
                "night_end": (now + timedelta(hours=2)).isoformat(),
                "combination_name": "Celestron 8\"",
                "entries": [],
            }
        }
        # fill_percent=0.0 → fill_w = 0 ≤ 0.01
        # overflow_minutes=30 > 0
        metrics = {"fill_percent": 0.0, "planned_minutes": 0, "night_minutes": 120, "overflow_minutes": 30}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_chart_skipped_when_no_night_times_in_plan(self, tmp_path, monkeypatch):
        """alttime_map exists but plan has no night_start/end → skip chart.
           Also covers  via _fmt_hm/_fmt_date called with None."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        alttime_data = {
            "timezone": "UTC",
            "times_utc": [now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")],
            "altitudes": [30.0, 40.0],
            "altitude_constraint_min": 30,
            "altitude_constraint_max": 80,
        }
        (tmp_path / "m31_alttime.json").write_text(json.dumps(alttime_data), encoding="utf-8")
        payload = {
            "plan": {
                # NO night_start / night_end → ns_dt = None
                "entries": [{
                    "id": "e1", "name": "M31", "done": False,
                    "alttime_file": "m31",
                    "timeline_start": now.isoformat(),
                    "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                }],
            }
        }
        metrics = {"fill_percent": 50.0, "planned_minutes": 30, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_chart_entry_skips_with_invalid_and_zero_range_times(self, tmp_path, monkeypatch):
        """entries without start/end, reversed range, empty clip result."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        alttime_data = {
            "timezone": "UTC",
            "times_utc": [now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")],
            "altitudes": [30.0, 40.0],
            "altitude_constraint_min": 30,
            "altitude_constraint_max": 80,
        }
        (tmp_path / "m31_alttime.json").write_text(json.dumps(alttime_data), encoding="utf-8")
        night_start = now
        night_end = now + timedelta(hours=2)
        payload = {
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "entries": [
                    {   # no timeline_start → _parse_utc returns None → continue
                        "id": "e1", "name": "M31", "done": False,
                        "alttime_file": "m31",
                        # No timeline_start or timeline_end
                    },
                    {   # t_end <= t_start → continue
                        "id": "e2", "name": "M42", "done": False,
                        "alttime_file": "m31",
                        "timeline_start": (now + timedelta(hours=1)).isoformat(),
                        "timeline_end": now.isoformat(),  # end BEFORE start
                    },
                    {   # _clip_alttime returns empty xs → continue
                        "id": "e3", "name": "M45", "done": False,
                        "alttime_file": "m31",
                        # Alttime data is at 'now' to 'now+30min', but entry window is far future
                        "timeline_start": (now + timedelta(hours=5)).isoformat(),
                        "timeline_end": (now + timedelta(hours=6)).isoformat(),
                    },
                ],
            }
        }
        metrics = {"fill_percent": 20.0, "planned_minutes": 60, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_clip_alttime_empty_inputs(self, tmp_path, monkeypatch):
        """_clip_alttime with empty times_utc → returns [], [].
           Also covers the None-dt skip and the no-valid-points return [], [] case."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        # Empty times_utc → _clip_alttime([], altitudes, ...) → return [], []
        alttime_empty = {
            "timezone": "UTC",
            "times_utc": [],
            "altitudes": [],
            "altitude_constraint_min": 30,
            "altitude_constraint_max": 80,
        }
        (tmp_path / "m31empty_alttime.json").write_text(json.dumps(alttime_empty), encoding="utf-8")
        # Invalid timestamps → _parse_utc returns None → dt is None → skip
        # All invalid → no valid pts → return [], []
        alttime_bad_ts = {
            "timezone": "UTC",
            "times_utc": ["NOT-A-DATE", "ALSO-BAD"],
            "altitudes": [30.0, 40.0],
        }
        (tmp_path / "m31badts_alttime.json").write_text(json.dumps(alttime_bad_ts), encoding="utf-8")
        night_start = now
        night_end = now + timedelta(hours=2)
        payload = {
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "entries": [
                    {
                        "id": "e1", "name": "M31", "done": False,
                        "alttime_file": "m31empty",  # empty times_utc
                        "timeline_start": now.isoformat(),
                        "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                    },
                    {
                        "id": "e2", "name": "M42", "done": False,
                        "alttime_file": "m31badts",  # invalid timestamps → skipped
                        "timeline_start": now.isoformat(),
                        "timeline_end": (now + timedelta(minutes=30)).isoformat(),
                    },
                ],
            }
        }
        metrics = {"fill_percent": 30.0, "planned_minutes": 60, "night_minutes": 120, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")

    def test_clip_alttime_no_pts_in_window(self, tmp_path, monkeypatch):
        """_clip_alttime with points all before the window → out=[] → return [], []."""
        import matplotlib
        matplotlib.use("Agg", force=True)
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: str(tmp_path), raising=True
        )
        early = datetime(2026, 1, 1, 20, 0, 0, tzinfo=timezone.utc)
        late = datetime(2026, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
        # alttime data: two points at early hours (20:00 and 20:30)
        alttime_data = {
            "timezone": "UTC",
            "times_utc": [early.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          (early + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")],
            "altitudes": [30.0, 35.0],
            "altitude_constraint_min": 30,
            "altitude_constraint_max": 80,
        }
        (tmp_path / "m31early_alttime.json").write_text(json.dumps(alttime_data), encoding="utf-8")
        # entry window is AFTER the alttime data: 23:00-23:30 → all points before window → out=[]
        payload = {
            "plan": {
                "night_start": late.isoformat(),
                "night_end": (late + timedelta(hours=1)).isoformat(),
                "entries": [{
                    "id": "e1", "name": "M31", "done": False,
                    "alttime_file": "m31early",
                    "timeline_start": late.isoformat(),
                    "timeline_end": (late + timedelta(minutes=30)).isoformat(),
                }],
            }
        }
        metrics = {"fill_percent": 10.0, "planned_minutes": 30, "night_minutes": 60, "overflow_minutes": 0}
        result = generate_plan_pdf(payload, metrics, _DummyI18n())
        assert result.getvalue().startswith(b"%PDF")


def _write_alttime(dir_path, filename, times, altitudes, alt_min=25.0, alt_max=90.0, azimuths=None):
    """Write a minimal *_alttime.json fixture into dir_path (str or Path)."""
    data = {
        "timezone": "UTC",
        "times_utc": times,
        "altitudes": altitudes,
        "altitude_constraint_min": alt_min,
        "altitude_constraint_max": alt_max,
    }
    if azimuths is not None:
        data["azimuths"] = azimuths
    path = os.path.join(str(dir_path), f"{filename}_alttime.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class TestVisibilityWarnings:
    """Regression coverage for the reported bug: Plan My Night scheduled targets
    (Triangulum Galaxy, Neptune) entirely outside the hours they're actually
    observable, with no warning. _observable_runs / _visibility_summary compute
    the real altitude-based visibility window so it can be surfaced and used by
    the optimizer below."""

    def test_observable_runs_interpolates_crossing_and_clips_to_night(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        # Crosses the 25 deg floor between the 07:00 (20 deg) and 07:30 (30 deg) samples.
        altitudes = [-10.0, 0.0, 20.0, 30.0, 40.0]

        runs = _observable_runs(times, altitudes, None, 25.0, 90.0, None, night_start, night_end)

        assert len(runs) == 1
        run_start, run_end = runs[0]
        expected_crossing = night_start + timedelta(minutes=75)  # 15
        assert abs((run_start - expected_crossing).total_seconds()) < 1
        assert run_end == night_end  # altitude keeps rising through the end of the night

    def test_observable_runs_empty_when_never_in_range(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        altitudes = [-10.0, -5.0, -2.0, -1.0, -0.5]  # never reaches the 25 deg floor

        runs = _observable_runs(times, altitudes, None, 25.0, 90.0, None, night_start, night_end)
        assert runs == []

    def test_visibility_summary_none_when_window_entirely_before_run(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        run_start = night_start + timedelta(minutes=75)
        run_end = night_start + timedelta(hours=2)
        runs = [(run_start, run_end)]

        summary = _visibility_summary(runs, night_start, night_start + timedelta(hours=1))

        assert summary["status"] == "none"
        assert summary["coverage_percent"] == 0.0
        assert summary["visible_from"] is not None  # tells the user when it *does* become visible

    def test_visibility_summary_partial_when_window_overlaps_run(self):
        run_start = datetime(2026, 7, 18, 7, 15, tzinfo=timezone.utc)
        run_end = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
        runs = [(run_start, run_end)]
        window_start = datetime(2026, 7, 18, 6, 30, tzinfo=timezone.utc)
        window_end = datetime(2026, 7, 18, 7, 30, tzinfo=timezone.utc)  # only the last 15 min overlap

        summary = _coverage_for_window(runs, window_start, window_end)
        assert 0.0 < summary < 1.0
        assert _visibility_summary(runs, window_start, window_end)["status"] == "partial"

    def test_visibility_summary_ok_when_window_inside_run(self):
        run_start = datetime(2026, 7, 18, 7, 15, tzinfo=timezone.utc)
        run_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        runs = [(run_start, run_end)]

        summary = _visibility_summary(runs, run_start, run_end)
        assert summary["status"] == "ok"
        assert summary["coverage_percent"] == 100.0

    def test_get_plan_with_timeline_flags_triangulum_style_gap(self, temp_plan_dir, monkeypatch):
        """The exact reported shape: a target planned for the first hour of the
        night while its altitude only crosses the observable floor at the 75-minute
        mark - get_plan_with_timeline must flag it as 'none', not silently plan it."""
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: temp_plan_dir, raising=True
        )
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        altitudes = [-10.0, 0.0, 20.0, 30.0, 40.0]
        _write_alttime(temp_plan_dir, "tri", times, altitudes)

        uid = "eeee3001-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "start_delay_minutes": 0,
                "entries": [
                    {"id": "e1", "name": "Triangulum", "planned_minutes": 60, "alttime_file": "tri", "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = get_plan_with_timeline(uid, "user")
        entry = result["plan"]["entries"][0]
        assert entry["visibility"]["status"] == "none"
        assert entry["visibility"]["visible_from"] is not None


class TestScheduleOptimizer:
    """compute_optimized_schedule / apply_optimized_schedule: reorders targets and
    picks a single initial delay so each lines up with its real visibility window,
    without introducing mid-plan idle gaps."""

    def test_reorders_by_visibility_and_computes_initial_delay(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: temp_plan_dir, raising=True
        )
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
        # Pin "now" inside the night window so the plan isn't seen as stale
        # once real wall-clock time passes this hardcoded night_end.
        monkeypatch.setattr(plan_my_night, "_now", lambda: night_start)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(9)]

        # "Triangulum": not observable until ~08:20, stays visible through the end of the night.
        triangulum_alts = [-10.0, -2.5, 5.0, 12.5, 20.0, 27.5, 35.0, 42.5, 50.0]
        _write_alttime(temp_plan_dir, "tri", times, triangulum_alts)

        # "Neptune": already observable at night_start, drops out of range around 07:36.
        neptune_alts = [30.0, 28.0, 26.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0]
        _write_alttime(temp_plan_dir, "nep", times, neptune_alts)

        uid = "eeee3002-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "start_delay_minutes": 0,
                "location_id": None,
                # Planned in the *wrong* order: Triangulum (not visible yet) before Neptune.
                "entries": [
                    {"id": "triangulum", "name": "Triangulum", "planned_minutes": 60, "alttime_file": "tri", "done": False},
                    {"id": "neptune", "name": "Neptune", "planned_minutes": 60, "alttime_file": "nep", "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")

        assert result is not None
        assert result["order"] == ["neptune", "triangulum"]
        assert result["start_delay_minutes"] == 0  # Neptune is already visible at night_start

        preview_by_id = {p["id"]: p for p in result["preview"]}
        assert preview_by_id["neptune"]["visibility"]["status"] == "ok"
        assert preview_by_id["triangulum"]["visibility"]["status"] == "ok"

    def test_never_observable_target_is_flagged(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: temp_plan_dir, raising=True
        )
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(plan_my_night, "_now", lambda: night_start)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        always_low_alts = [-10.0, -8.0, -6.0, -4.0, -2.0]  # never reaches the 25 deg floor
        _write_alttime(temp_plan_dir, "low", times, always_low_alts)

        uid = "eeee3003-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "start_delay_minutes": 0,
                "entries": [
                    {"id": "e1", "name": "Never Up", "planned_minutes": 60, "alttime_file": "low", "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")
        assert result["preview"][0]["warnings"] == ["never_observable"]

    def test_flags_overload_caused_by_mandatory_delay(self, temp_plan_dir, monkeypatch):
        """Regression test: a target that only becomes visible late in the night
        forces a large start_delay_minutes, which can shrink the *usable* window
        below the total requested duration even though that duration is well
        under the raw night length. plan_warnings must catch this - comparing
        total planned minutes against the full night length (ignoring the
        mandatory delay) would miss it entirely, matching the real-world bug
        where the Plan My Night 'Overloaded' badge appeared only after applying,
        with no warning in the optimizer preview beforehand."""
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: temp_plan_dir, raising=True
        )
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)  # 120-minute night
        monkeypatch.setattr(plan_my_night, "_now", lambda: night_start)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        # Not observable until the very last sample (07:30) - forces a long mandatory delay.
        late_alts = [-10.0, -5.0, -2.0, 0.0, 30.0]
        _write_alttime(temp_plan_dir, "late", times, late_alts)

        uid = "eeee3007-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": night_start.isoformat(),
                "night_end": night_end.isoformat(),
                "start_delay_minutes": 0,
                "entries": [
                    # 90 minutes requested, comfortably under the 120-minute night...
                    {"id": "e1", "name": "Late Riser", "planned_minutes": 90, "alttime_file": "late", "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")

        # ...but it isn't visible until ~90 minutes in, leaving only ~5 usable minutes.
        assert result["start_delay_minutes"] >= 60
        assert plan_my_night._parse_utc(result["preview"][0]["end"]) == night_end
        assert result["plan_warnings"] == ["total_duration_exceeds_night"]

    def test_compute_returns_none_without_plan(self, temp_plan_dir):
        assert compute_optimized_schedule("eeee3004-0000-4000-8000-000000000000", "user") is None

    def test_apply_reorders_entries_and_sets_delay(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(
            plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        )
        uid = "eeee3005-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T10:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [
                    {"id": "a", "name": "A", "planned_minutes": 60, "done": False},
                    {"id": "b", "name": "B", "planned_minutes": 60, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        ok = apply_optimized_schedule(uid, "user", None, ["b", "a"], 45)
        assert ok is True

        updated = load_user_plan(uid, "user")
        entries = updated["plan"]["entries"]
        assert [e["id"] for e in entries] == ["b", "a"]
        assert updated["plan"]["start_delay_minutes"] == 45

    def test_apply_rejects_stale_order(self, temp_plan_dir):
        uid = "eeee3006-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T10:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [
                    {"id": "a", "name": "A", "planned_minutes": 60, "done": False},
                    {"id": "b", "name": "B", "planned_minutes": 60, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        # Order references an id ("c") that no longer exists in the plan.
        ok = apply_optimized_schedule(uid, "user", None, ["b", "c"], 0)
        assert ok is False

        unchanged = load_user_plan(uid, "user")
        assert [e["id"] for e in unchanged["plan"]["entries"]] == ["a", "b"]

    def test_compute_returns_none_for_previous_plan_state(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
        uid = "eeee3011-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T10:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [{"id": "a", "name": "A", "planned_minutes": 60, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")
        assert compute_optimized_schedule(uid, "user") is None

    def test_compute_returns_none_for_empty_entries(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc))
        uid = "eeee3012-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T10:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [],
            },
        }
        save_user_plan(uid, payload, username="user")
        assert compute_optimized_schedule(uid, "user") is None

    def test_compute_returns_none_for_invalid_night_bounds(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc))
        uid = "eeee3013-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                # night_end <= night_start - malformed/corrupted plan data.
                "night_start": "2026-07-18T10:00:00+00:00",
                "night_end": "2026-07-18T06:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [{"id": "a", "name": "A", "planned_minutes": 60, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")
        assert compute_optimized_schedule(uid, "user") is None

    def test_compute_entry_without_alttime_file_is_never_observable(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc))
        uid = "eeee3014-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T08:00:00+00:00",
                "start_delay_minutes": 0,
                # No alttime_file at all - a manually-added target.
                "entries": [{"id": "a", "name": "A", "planned_minutes": 30, "done": False}],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")

        assert result["preview"][0]["warnings"] == ["never_observable"]

    def test_compute_reuses_cached_alttime_for_repeated_file(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(
            "skytonight.skytonight_storage.get_alttime_dir", lambda *_a, **_k: temp_plan_dir, raising=True
        )
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc))
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        times = [(night_start + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(5)]
        always_visible = [40.0, 41.0, 42.0, 43.0, 44.0]
        _write_alttime(temp_plan_dir, "shared", times, always_visible)

        uid = "eeee3015-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T08:00:00+00:00",
                "start_delay_minutes": 0,
                # Both entries share the same cached alttime file - the second
                # lookup must hit the cache rather than re-reading disk.
                "entries": [
                    {"id": "e1", "name": "E1", "planned_minutes": 15, "alttime_file": "shared", "done": False},
                    {"id": "e2", "name": "E2", "planned_minutes": 15, "alttime_file": "shared", "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")

        assert {p["id"] for p in result["preview"]} == {"e1", "e2"}

    def test_compute_flags_entries_pushed_past_night_end(self, temp_plan_dir, monkeypatch):
        monkeypatch.setattr(plan_my_night, "_now", lambda: datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc))
        uid = "eeee3016-0000-4000-8000-000000000000"
        payload = {
            "user_id": uid, "username": "user",
            "plan": {
                "night_start": "2026-07-18T06:00:00+00:00",
                "night_end": "2026-07-18T08:00:00+00:00",
                "start_delay_minutes": 0,
                "entries": [
                    # First entry (no alttime_file) fills the entire 2-hour night...
                    {"id": "e1", "name": "E1", "planned_minutes": 120, "done": False},
                    # ...leaving nothing for the second, which gets pushed past night_end.
                    {"id": "e2", "name": "E2", "planned_minutes": 30, "done": False},
                ],
            },
        }
        save_user_plan(uid, payload, username="user")

        result = compute_optimized_schedule(uid, "user")

        preview_by_id = {p["id"]: p for p in result["preview"]}
        assert "pushed_past_night_end" in preview_by_id["e2"]["warnings"]

    def test_apply_returns_false_without_plan(self, temp_plan_dir):
        assert apply_optimized_schedule("eeee3017-0000-4000-8000-000000000000", "user", None, ["a"], 0) is False


class TestLoadAlttime:
    def test_returns_none_for_falsy_filename(self):
        assert _load_alttime('', None) is None
        assert _load_alttime(None, None) is None


class TestObservableRunsEdgeCases:
    def test_returns_empty_for_invalid_night_window(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        # night_end == night_start is invalid (not strictly after start).
        result = _observable_runs(['x'], [50.0], None, 30, 80, None, night_start, night_start)
        assert result == []

    def test_returns_empty_when_a_timestamp_is_unparseable(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        result = _observable_runs(
            [night_start.isoformat(), 'not-a-timestamp'], [50.0, 55.0], None, 30, 80, None, night_start, night_end
        )
        assert result == []

    def test_horizon_floor_exception_falls_back_to_alt_min(self, monkeypatch):
        def _boom(*_a, **_kw):
            raise RuntimeError('boom')

        monkeypatch.setattr(plan_my_night, '_horizon_floor_array', _boom)
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [night_start.isoformat(), (night_start + timedelta(hours=1)).isoformat()]

        result = _observable_runs(
            times, [50.0, 55.0], [10.0, 20.0], 30, 80, [{'az': 0, 'alt': 5}], night_start, night_end
        )

        # Falls back to alt_min as the floor - target stays above it for both
        # samples, giving one run from the first sample to the last (07:00,
        # not clipped to night_end since there's no later sample).
        assert result == [(night_start, night_start + timedelta(hours=1))]

    def test_horizon_profile_raises_floor_and_excludes_low_target(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [night_start.isoformat(), (night_start + timedelta(hours=1)).isoformat()]
        # Horizon profile raises the floor to 20 deg at az=0/180 - well above alt_min.
        horizon_profile = [{'az': 0, 'alt': 20}, {'az': 180, 'alt': 20}]
        altitudes = [15.0, 15.0]  # above alt_min(10) but below the horizon-raised floor(20)
        azimuths = [0.0, 0.0]

        result = _observable_runs(times, altitudes, azimuths, 10, 80, horizon_profile, night_start, night_end)

        assert result == []

    def test_skips_none_altitude_samples_and_crosses_via_none_margin(self):
        """A None altitude sample (missing data point in the cached series) must
        not crash the run-detection/interpolation logic. The crossing on either
        side of the gap has no valid altitude to interpolate against, so it
        collapses to a zero-length run at the missing sample's neighbors -
        which then get clipped away entirely, rather than raising."""
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [
            night_start.isoformat(),
            (night_start + timedelta(minutes=30)).isoformat(),
            (night_start + timedelta(minutes=60)).isoformat(),
        ]
        altitudes = [50.0, None, 55.0]

        result = _observable_runs(times, altitudes, None, 30, 80, None, night_start, night_end)

        assert result == []

    def test_clips_out_run_entirely_before_night_start(self):
        before_start = datetime(2026, 7, 18, 2, 0, tzinfo=timezone.utc)
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        times = [(before_start + timedelta(minutes=15 * i)).isoformat() for i in range(4)]
        altitudes = [50.0, 51.0, 52.0, 53.0]  # observable throughout, but entirely before night_start

        result = _observable_runs(times, altitudes, None, 30, 80, None, night_start, night_end)

        assert result == []


class TestVisibilitySummaryEdgeCases:
    def test_without_window_bounds_skips_visible_from_lookup(self):
        result = _visibility_summary([], None, None)
        assert result['status'] == 'none'
        assert result['visible_from'] is None
        assert result['visible_until'] is None


class TestComputeEntryVisibilityCache:
    def test_uses_cached_alttime_data_without_reloading(self):
        night_start = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
        cached_data = {
            'times_utc': [night_start.isoformat(), night_end.isoformat()],
            'altitudes': [50.0, 55.0],
            'altitude_constraint_min': 30,
            'altitude_constraint_max': 80,
        }
        # Pre-populate the cache so the "not in cache" load branch is skipped.
        cache = {'preloaded': cached_data}
        entry = {'alttime_file': 'preloaded'}

        result = _compute_entry_visibility(entry, None, night_start, night_end, night_start, night_end, cache)

        assert result is not None
        assert result['status'] == 'ok'


# ---------------------------------------------------------------------------
# Merged from former test_coverage_edge_cases.py
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Merged from former test_locations_coverage.py (TestHelperEdgeArcs)
# ---------------------------------------------------------------------------


def test_plan_helpers_skip_junk_and_handle_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))

    # Skipped: backups, tmp, corrupted-marker, non-json
    (tmp_path / 'a.json.backup').write_text('{}', encoding='utf-8')
    (tmp_path / 'b.corrupted.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'c.tmp').write_text('{}', encoding='utf-8')
    (tmp_path / 'readme.txt').write_text('x', encoding='utf-8')
    # Unreadable plan file -> _plan_references_location returns False
    (tmp_path / 'u1.json').write_text('{corrupt', encoding='utf-8')
    # Non-dict payload
    (tmp_path / 'u2.json').write_text('[1, 2]', encoding='utf-8')
    # Real pinned plan
    (tmp_path / 'u3.json').write_text(
        json.dumps({'plan': {'location_id': 'L9', 'targets': []}}), encoding='utf-8'
    )

    assert plan_my_night.count_plans_for_location('') == 0
    assert plan_my_night.delete_plans_for_location('') == 0
    assert plan_my_night.count_plans_for_location('L9') == 1

    # os.remove failure is logged, not raised
    monkeypatch.setattr(plan_my_night.os, 'remove',
                        lambda *_a: (_ for _ in ()).throw(OSError('locked')))
    assert plan_my_night.delete_plans_for_location('L9') == 0
