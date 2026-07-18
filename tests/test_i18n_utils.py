"""Unit tests for backend i18n utilities (i18n_utils.py)."""

import pytest
from unittest.mock import mock_open, patch

from utils import i18n_utils as module

I18nManager = module.I18nManager
_is_safe_path = module._is_safe_path
create_translated_alert = module.create_translated_alert
get_translated_message = module.get_translated_message
init_i18n_for_request = module.init_i18n_for_request


@pytest.fixture(autouse=True)
def _clear_translation_cache():
    module._translation_cache.clear()
    yield
    module._translation_cache.clear()


def test_is_safe_path_true_for_nested_path(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    candidate = base / "folder" / "en.json"
    candidate.parent.mkdir()
    candidate.write_text("{}", encoding="utf-8")
    assert _is_safe_path(str(base), str(candidate)) is True


def test_load_translation_file_unsupported_language_falls_back_to_default():
    payload = '{"common": {"hello": "Hello"}}'
    with patch("utils.i18n_utils.os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data=payload)
    ):
        data = module._load_translation_file("xx")

    assert data == {"common": {"hello": "Hello"}}


def test_load_translation_file_not_found_returns_empty():
    with patch("utils.i18n_utils.os.path.exists", return_value=False):
        assert module._load_translation_file("en") == {}


def test_i18n_manager_fallback_and_params():
    def fake_loader(language):
        if language == "fr":
            return {"weather_alerts": {}}
        return {"weather_alerts": {"critical_dew_risk": "Dew risk at {time}"}}

    with patch("utils.i18n_utils._load_translation_file", side_effect=fake_loader):
        manager = I18nManager("fr")
        result = manager.t("weather_alerts.critical_dew_risk", time="22:15")

    assert result == "Dew risk at 22:15"


def test_i18n_manager_missing_key_returns_key():
    with patch("utils.i18n_utils._load_translation_file", return_value={}):
        manager = I18nManager("en")
    assert manager.t("missing.namespace") == "missing.namespace"


def test_i18n_manager_set_language_unsupported_keeps_current():
    with patch("utils.i18n_utils._load_translation_file", return_value={}):
        manager = I18nManager("en")
        manager.set_language("xx")
    assert manager.get_language() == "en"


def test_get_namespace_and_supported_languages():
    with patch("utils.i18n_utils._load_translation_file", return_value={"weather_alerts": {"x": "y"}}):
        manager = I18nManager("en")
    assert manager.get_namespace("weather_alerts") == {"x": "y"}
    assert "en" in manager.get_supported_languages()


def test_get_translated_message_calls_manager():
    with patch("utils.i18n_utils.I18nManager") as manager_cls:
        manager_instance = manager_cls.return_value
        manager_instance.t.return_value = "Translated"
        result = get_translated_message("weather_alerts.section_title", "en")

    assert result == "Translated"
    manager_instance.t.assert_called_once_with("weather_alerts.section_title")


def test_create_translated_alert_uses_formatted_time_and_fallback_key():
    with patch("utils.i18n_utils.I18nManager") as manager_cls:
        manager_instance = manager_cls.return_value
        manager_instance.t.return_value = "Alert text"

        alert = create_translated_alert(
            alert_type="DEW_WARNING",
            severity="HIGH",
            time="2026-03-11T21:45:00",
            language="en",
        )

    manager_instance.t.assert_called_once_with("weather_alerts.critical_dew_risk", time="21:45")
    assert alert["message"] == "Alert text"


def test_create_translated_alert_invalid_time_keeps_original_string():
    with patch("utils.i18n_utils.I18nManager") as manager_cls:
        manager_instance = manager_cls.return_value
        manager_instance.t.return_value = "Section"

        create_translated_alert(
            alert_type="UNKNOWN",
            severity="LOW",
            time="not-a-time",
            language="en",
        )

    manager_instance.t.assert_called_once_with("weather_alerts.section_title", time="not-a-time")


# ---------------------------------------------------------------------------
# Additional tests for missing coverage
# ---------------------------------------------------------------------------

def test_is_safe_path_different_drives_returns_false():
    """Paths resolving under a different root than base_dir are rejected."""
    result = _is_safe_path("C:\\base", "D:\\other")
    assert result is False


def test_load_translation_file_cache_hit(tmp_path):
    """Line 69: second call for same language uses cached result."""
    module._translation_cache.clear()
    payload = '{"x": "y"}'
    with patch("utils.i18n_utils.os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data=payload)
    ):
        module._load_translation_file("en")
        # Inject a sentinel to prove the cache is used on the second call
        module._translation_cache["en"]["sentinel"] = True
        second = module._load_translation_file("en")

    assert second.get("sentinel") is True  # same dict object from cache


def test_load_translation_file_json_decode_error_returns_empty(tmp_path):
    """Lines 99-101: JSONDecodeError → empty dict returned."""
    module._translation_cache.clear()
    with patch("utils.i18n_utils.os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data="INVALID JSON {{{")
    ):
        result = module._load_translation_file("en")

    assert result == {}


def test_t_key_found_in_main_translations_loop_exits_normally():
    """Line 146->161: all keys found in main translations → loop exits normally → line 161 executed."""
    with patch("utils.i18n_utils._load_translation_file", return_value={"ns": {"key": "value"}}):
        manager = I18nManager("en")
    result = manager.t("ns.key")
    assert result == "value"


def test_t_key_resolves_to_non_string_returns_key():
    """Line 162: key resolves to a dict (not str) → return key."""
    with patch("utils.i18n_utils._load_translation_file", return_value={"ns": {"sub": "v"}}):
        manager = I18nManager("en")
    # Key "ns" alone resolves to a dict, not a str
    result = manager.t("ns")
    assert result == "ns"


def test_set_language_valid_language_updates_state():
    """Lines 181-182: set_language with a supported language updates self.language."""
    with patch("utils.i18n_utils._load_translation_file", return_value={}):
        manager = I18nManager("en")
        manager.set_language("fr")
    assert manager.get_language() == "fr"


def test_get_namespace_missing_returns_empty():
    """Line 202: namespace not in translations → return {}."""
    with patch("utils.i18n_utils._load_translation_file", return_value={"other": {}}):
        manager = I18nManager("en")
    assert manager.get_namespace("nonexistent") == {}


def test_init_i18n_for_request_returns_manager():
    """Line 283: init_i18n_for_request returns an I18nManager instance."""
    with patch("utils.i18n_utils._load_translation_file", return_value={}):
        result = init_i18n_for_request("en")
    assert isinstance(result, I18nManager)
