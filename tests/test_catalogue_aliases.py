"""Unit tests for catalogue alias utilities (catalogue_aliases.py)."""

from unittest.mock import mock_open, patch

from observation import catalogue_aliases as module

get_alias_entry = module.get_alias_entry
get_aliases_map = module.get_aliases_map
get_group_id = module.get_group_id
load_aliases_table = module.load_aliases_table
make_lookup_key = module.make_lookup_key
merge_item_with_alias_entry = module.merge_item_with_alias_entry
normalize_object_name = module.normalize_object_name


def test_normalize_object_name_handles_empty_and_symbols():
    assert normalize_object_name("") == ""
    assert normalize_object_name(None) == ""
    assert normalize_object_name(" M 31 ") == "m31"
    assert normalize_object_name("NGC-7000!") == "ngc7000"


def test_make_lookup_key_normalizes_catalogue_and_name():
    assert make_lookup_key(" Messier ", " M 31 ") == "messier::m31"


def test_load_aliases_table_missing_file_returns_empty():
    with patch("observation.catalogue_aliases.os.path.exists", return_value=False):
        assert load_aliases_table(force_reload=True) == {}


def test_load_aliases_table_non_dict_payload_returns_empty():
    module._aliases_cache = {}
    module._aliases_mtime = None
    with patch("observation.catalogue_aliases.os.path.exists", return_value=True), patch(
        "observation.catalogue_aliases.os.path.getmtime", return_value=123.0
    ), patch("builtins.open", mock_open(read_data='["not-a-dict"]')):
        assert load_aliases_table(force_reload=True) == {}


def test_load_aliases_table_uses_cache_when_mtime_unchanged():
    cached = {"lookup": {"messier::m31": {"group_id": "g1"}}}
    module._aliases_cache = cached
    module._aliases_mtime = 111.0

    with patch("observation.catalogue_aliases.os.path.exists", return_value=True), patch(
        "observation.catalogue_aliases.os.path.getmtime", return_value=111.0
    ), patch("builtins.open", side_effect=AssertionError("open should not be called")):
        result = load_aliases_table(force_reload=False)

    assert result == cached


def test_get_alias_helpers_return_expected_values():
    aliases_table = {
        "lookup": {
            "messier::m31": {
                "group_id": "grp-1",
                "aliases": {"openngc": "NGC224"},
            }
        }
    }

    with patch("observation.catalogue_aliases.load_aliases_table", return_value=aliases_table), \
         patch("observation.catalogue_aliases.skytonight_targets.get_lookup_entry", return_value={}):
        entry = get_alias_entry("Messier", "M 31")
        aliases = get_aliases_map("Messier", "M 31")
        group_id = get_group_id("Messier", "M 31")

    assert entry["group_id"] == "grp-1"
    assert aliases == {"openngc": "NGC224"}
    assert group_id == "grp-1"


def test_get_alias_entry_invalid_input_returns_empty_dict():
    assert get_alias_entry("", "M31") == {}
    assert get_alias_entry("Messier", "") == {}


def test_merge_item_with_alias_entry_adds_or_removes_aliases():
    item = {
        "catalogue": "Messier",
        "name": "M31",
        "catalogue_group_id": "legacy",
    }

    with patch(
        "observation.catalogue_aliases.get_alias_entry",
        return_value={"aliases": {"openngc": "NGC224"}},
    ):
        merged = merge_item_with_alias_entry(item.copy())

    assert "catalogue_group_id" not in merged
    assert merged["catalogue_aliases"] == {"openngc": "NGC224"}

    with patch("observation.catalogue_aliases.get_alias_entry", return_value={}):
        merged_no_entry = merge_item_with_alias_entry(item.copy())

    assert "catalogue_aliases" not in merged_no_entry


def test_merge_item_with_alias_entry_non_dict_passthrough():
    assert merge_item_with_alias_entry("raw") == "raw"


def test_load_aliases_table_exception_returns_empty(monkeypatch):
    """Lines 51-53: exception during file open → return empty dict."""
    module._aliases_cache = {}
    module._aliases_mtime = None
    with patch("observation.catalogue_aliases.os.path.exists", return_value=True), \
         patch("observation.catalogue_aliases.os.path.getmtime", return_value=99.0), \
         patch("builtins.open", side_effect=IOError("disk error")):
        result = load_aliases_table(force_reload=True)
    assert result == {}


def test_merge_item_no_catalogue_removes_aliases_key():
    """Lines 95-96: missing catalogue → pop catalogue_aliases and return item."""
    item = {'name': 'M31', 'catalogue_aliases': {'x': 'y'}}
    result = merge_item_with_alias_entry(item)
    assert 'catalogue_aliases' not in result
    assert result['name'] == 'M31'


def test_merge_item_no_name_removes_aliases_key():
    """Lines 95-96: missing name → pop catalogue_aliases and return item."""
    item = {'catalogue': 'Messier', 'catalogue_aliases': {'x': 'y'}}
    result = merge_item_with_alias_entry(item)
    assert 'catalogue_aliases' not in result


def test_merge_item_empty_aliases_dict_removes_aliases_key():
    """Line 108: aliases is empty dict → pop catalogue_aliases from item."""
    item = {'catalogue': 'Messier', 'name': 'M31', 'catalogue_aliases': {'old': 'data'}}
    with patch("observation.catalogue_aliases.get_alias_entry", return_value={"aliases": {}}):
        result = merge_item_with_alias_entry(item)
    assert 'catalogue_aliases' not in result
