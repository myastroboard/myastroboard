"""Unit tests for backend version checker logic."""

from types import SimpleNamespace

import pytest
import requests

import version_checker as module


@pytest.fixture(autouse=True)
def _reset_version_cache(monkeypatch):
    module.cache_store._version_update_cache = {"timestamp": 0, "data": None}
    monkeypatch.setattr(module.cache_store, "sync_cache_from_shared", lambda *_args, **_kwargs: None)
    yield
    module.cache_store._version_update_cache = {"timestamp": 0, "data": None}


def test_is_newer_version_comparisons_and_invalid_input():
    assert module.is_newer_version("1.0.0", "1.0.1") is True
    assert module.is_newer_version("1.2.0", "1.1.9") is False
    assert module.is_newer_version("1.0", "1.0.0") is False
    assert module.is_newer_version("bad", "1.0.0") is False
    # Additional edge cases
    assert module.is_newer_version("1.0.0", "1.0.0") is False     # equal
    assert module.is_newer_version("2.0.0", "1.9.9") is False     # downgrade
    assert module.is_newer_version("1.0.0", "bad") is False       # invalid latest
    assert module.is_newer_version("1.0.0", "1.1.0") is True      # minor bump
    assert module.is_newer_version("1.0.0", "2.0.0") is True      # major bump


def test_save_version_result_writes_cache(monkeypatch):
    """_save_version_result populates in-memory and shared cache."""
    saved = {}
    monkeypatch.setattr(module.time, "time", lambda: 999.0)
    monkeypatch.setattr(
        module.cache_store,
        "update_shared_cache_entry",
        lambda key, data, ts: saved.update({"key": key, "data": data, "ts": ts}),
    )

    result = {"current_version": "1.0.0", "update_available": False}
    module._save_version_result(result)

    assert module.cache_store._version_update_cache["data"] == result
    assert module.cache_store._version_update_cache["timestamp"] == 999.0
    assert saved["key"] == "version_update"
    assert saved["ts"] == 999.0



def test_check_for_updates_returns_cached_data(monkeypatch):
    cached = {"current_version": "1.0.0", "update_available": False}
    module.cache_store._version_update_cache = {"timestamp": 100, "data": cached}

    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")))

    result = module.check_for_updates()
    assert result == cached


def test_check_for_updates_handles_404(monkeypatch):
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.time, "time", lambda: 123.0)

    updates = []
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda key, data, ts: updates.append((key, data, ts)))
    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=404))

    result = module.check_for_updates()

    assert result["error"] == "Repository not found"
    assert result["update_available"] is False
    assert updates and updates[0][0] == "version_update"


def test_check_for_updates_handles_rate_limit_403(monkeypatch):
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.time, "time", lambda: 124.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=403))

    result = module.check_for_updates()

    assert result["error"] == "Rate limit exceeded"
    assert result["update_available"] is False


def test_check_for_updates_success_response(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "tag_name": "v1.2.0",
                "html_url": "https://example/releases/1.2.0",
                "name": "Release 1.2.0",
                "published_at": "2026-03-01T00:00:00Z",
            }

    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.1.0")
    monkeypatch.setattr(module.time, "time", lambda: 125.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: Response())

    result = module.check_for_updates()

    assert result["current_version"] == "1.1.0"
    assert result["latest_version"] == "1.2.0"
    assert result["update_available"] is True


def test_check_for_updates_timeout(monkeypatch):
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.time, "time", lambda: 126.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)

    def _raise_timeout(*_args, **_kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(module.requests, "get", _raise_timeout)

    result = module.check_for_updates()

    assert result["error"] == "Request timed out"
    assert result["update_available"] is False


def test_check_for_updates_request_exception(monkeypatch):
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.time, "time", lambda: 127.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)

    def _raise_request_error(*_args, **_kwargs):
        raise requests.RequestException("network down")

    monkeypatch.setattr(module.requests, "get", _raise_request_error)

    result = module.check_for_updates()

    assert result["error"] == "Request failed"
    assert result["update_available"] is False


def test_check_for_updates_version_changed_invalidates_cache(monkeypatch):
    """Line 64: cache is valid but installed version changed → refetch."""
    cached = {"current_version": "0.9.0", "update_available": False}
    module.cache_store._version_update_cache = {"timestamp": 100, "data": cached}

    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")  # different version
    monkeypatch.setattr(module.time, "time", lambda: 200.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"tag_name": "v1.0.0", "html_url": "", "name": "", "published_at": ""}

    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: Response())

    result = module.check_for_updates()

    # Should have fetched fresh data (not returned the 0.9.0 cache)
    assert result["current_version"] == "1.0.0"


def test_check_for_updates_no_update_available_logs_correctly(monkeypatch):
    """Line 111: update_available=False → 'No update available' log path."""
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.2.0")
    monkeypatch.setattr(module.time, "time", lambda: 130.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            # latest same as current → no update
            return {"tag_name": "v1.2.0", "html_url": "", "name": "", "published_at": ""}

    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: Response())

    result = module.check_for_updates()

    assert result["update_available"] is False
    assert result["current_version"] == "1.2.0"


def test_check_for_updates_unexpected_exception(monkeypatch):
    """Lines 129-133: unexpected non-requests exception → Internal error result."""
    monkeypatch.setattr(module.cache_store, "is_cache_valid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "get_repo_version", lambda: "1.0.0")
    monkeypatch.setattr(module.time, "time", lambda: 131.0)
    monkeypatch.setattr(module.cache_store, "update_shared_cache_entry", lambda *_args, **_kwargs: None)

    def _raise_unexpected(*_args, **_kwargs):
        raise ValueError("unexpected internal error")

    monkeypatch.setattr(module.requests, "get", _raise_unexpected)

    result = module.check_for_updates()

    assert result["error"] == "Internal error"
    assert result["update_available"] is False
