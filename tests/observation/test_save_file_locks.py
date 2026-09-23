"""Per-user JSON saves must hold a cross-process file lock, not only a thread lock.

Each gunicorn worker is a separate process with its own thread locks. Without a
file lock, two workers saving the same user's file at once share one fixed
``.tmp`` path, and a failed ``os.replace`` in one "restores from backup" over
the other worker's successful save.
"""

from contextlib import contextmanager

import pytest

from observation import astrodex, observation_sessions, plan_my_night, wishlist

_USER = "11111111-2222-3333-4444-555555555555"

_SAVE_PATHS = [
    (astrodex, "save_user_astrodex", "_save_user_astrodex_locked", "get_user_astrodex_file"),
    (observation_sessions, "save_user_sessions", "_save_user_sessions_locked", "get_user_sessions_file"),
    (wishlist, "save_user_wishlist", "_save_user_wishlist_locked", "get_user_wishlist_file"),
    (plan_my_night, "save_user_plan", "_save_user_plan_locked", "get_user_plan_file"),
]


@pytest.mark.parametrize("module, save_name, locked_name, path_name", _SAVE_PATHS)
def test_save_runs_inside_interprocess_lock_on_the_user_file(
    monkeypatch, tmp_path, module, save_name, locked_name, path_name
):
    file_path = str(tmp_path / "user_data.json")
    monkeypatch.setattr(module, path_name, lambda *_args, **_kwargs: file_path)

    events = []

    @contextmanager
    def _recording_lock(lock_path):
        events.append(("acquire", lock_path))
        yield
        events.append(("release", lock_path))

    def _fake_locked_save(*_args, **_kwargs):
        events.append(("save", None))
        return True

    monkeypatch.setattr(module, "interprocess_lock", _recording_lock)
    monkeypatch.setattr(module, locked_name, _fake_locked_save)

    assert getattr(module, save_name)(_USER, {}) is True
    assert events == [("acquire", file_path + ".lock"), ("save", None), ("release", file_path + ".lock")]
