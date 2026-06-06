"""Unit tests for backend cache scheduler (cache_scheduler.py)."""

import types

import pytest

import cache_scheduler as module


class DummyThread:
    def __init__(self, alive=False):
        self.started = False
        self.joined = False
        self._alive = alive

    def start(self):
        self.started = True

    def is_alive(self):
        return self._alive

    def join(self):
        self.joined = True


class DummyFile:
    def __init__(self):
        self.closed = False

    def fileno(self):
        return 1

    def write(self, _value):
        return None

    def flush(self):
        return None

    def close(self):
        self.closed = True


def test_start_starts_thread_when_lock_acquired(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler.thread = DummyThread()
    monkeypatch.setattr(scheduler, "_acquire_lock", lambda: True)

    assert scheduler.start() is True
    assert scheduler.thread.started is True


def test_start_returns_false_when_lock_not_acquired(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler.thread = DummyThread()
    monkeypatch.setattr(scheduler, "_acquire_lock", lambda: False)

    assert scheduler.start() is False
    assert scheduler.thread.started is False


def test_acquire_lock_success_windows_branch(monkeypatch, tmp_path):
    scheduler = module.CacheScheduler(interval_seconds=1)
    dummy_file = DummyFile()

    monkeypatch.setattr(module, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: dummy_file)
    monkeypatch.setattr(module.msvcrt, "locking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.os, "getpid", lambda: 1234)

    assert scheduler._acquire_lock() is True
    assert scheduler._has_lock is True
    assert scheduler._lock_file is dummy_file


def test_acquire_lock_failure_releases_file(monkeypatch, tmp_path):
    scheduler = module.CacheScheduler(interval_seconds=1)
    dummy_file = DummyFile()

    monkeypatch.setattr(module, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: dummy_file)

    def _fail_lock(*_args, **_kwargs):
        raise OSError("locked")

    monkeypatch.setattr(module.msvcrt, "locking", _fail_lock)

    assert scheduler._acquire_lock() is False
    assert scheduler._lock_file is None
    assert dummy_file.closed is True


def test_release_lock_unlinks_file(monkeypatch, tmp_path):
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._lock_file = DummyFile()
    scheduler._has_lock = True

    deleted = []
    monkeypatch.setattr(module, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.msvcrt, "locking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(module.os, "unlink", lambda p: deleted.append(p))

    scheduler._release_lock()

    assert scheduler._has_lock is False
    assert scheduler._lock_file is None
    assert len(deleted) == 1


def test_stop_sets_event_joins_and_releases(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler.thread = DummyThread(alive=True)
    released = []
    monkeypatch.setattr(scheduler, "_release_lock", lambda: released.append(True))

    scheduler.stop()

    assert scheduler._stop_event.is_set() is True
    assert scheduler.thread.joined is True
    assert released == [True]


def test_update_all_caches_success(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)
    called = []
    monkeypatch.setattr(module, "fully_initialize_caches", lambda: called.append(True))

    scheduler.update_all_caches()

    assert called == [True]


def test_update_all_caches_failure_raises(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)

    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "fully_initialize_caches", _raise)

    with pytest.raises(RuntimeError):
        scheduler.update_all_caches()


def test_run_exits_when_stop_event_is_set_after_first_wait(monkeypatch):
    scheduler = module.CacheScheduler(interval_seconds=1)
    calls = []

    monkeypatch.setattr(scheduler, "update_all_caches", lambda: calls.append("run"))

    class OneShotEvent:
        def __init__(self):
            self.wait_calls = 0

        def is_set(self):
            return False

        def wait(self, _interval):
            self.wait_calls += 1
            return True

        def set(self):
            return None

    scheduler._stop_event = OneShotEvent()
    scheduler._run()

    assert calls == ["run"]


def test_acquire_lock_ioerror_from_open(monkeypatch, tmp_path):
    """IOError from open() should cause _acquire_lock to return False."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    monkeypatch.setattr(module, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: (_ for _ in ()).throw(IOError("permission denied")))

    assert scheduler._acquire_lock() is False
    assert scheduler._lock_file is None


def test_release_lock_when_no_lock_file(monkeypatch):
    """_release_lock is a no-op when _lock_file is None."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._lock_file = None
    scheduler._has_lock = False
    scheduler._release_lock()  # Must not raise


def test_release_lock_when_lock_file_not_on_disk(monkeypatch, tmp_path):
    """Lock file already gone from disk — os.path.exists returns False, no unlink."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._lock_file = DummyFile()
    scheduler._has_lock = True

    deleted = []
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.msvcrt, "locking", lambda *_a, **_k: None)
    monkeypatch.setattr(module.os.path, "exists", lambda _p: False)
    monkeypatch.setattr(module.os, "unlink", lambda p: deleted.append(p))

    scheduler._release_lock()
    assert len(deleted) == 0
    assert scheduler._lock_file is None


def test_release_lock_exception_swallowed(monkeypatch, tmp_path):
    """Exception during _release_lock is swallowed (not propagated)."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._lock_file = DummyFile()
    scheduler._has_lock = True

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.msvcrt, "locking", lambda *_a, **_k: (_ for _ in ()).throw(Exception("unlink error")))

    scheduler._release_lock()  # Must not raise


def test_stop_does_not_join_dead_thread(monkeypatch):
    """stop() skips thread.join() when thread is not alive."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler.thread = DummyThread(alive=False)
    monkeypatch.setattr(scheduler, "_release_lock", lambda: None)

    scheduler.stop()
    assert scheduler.thread.joined is False


def test_run_exits_immediately_when_stop_set(monkeypatch):
    """_run loop exits without calling update_all_caches when stop_event is pre-set."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    calls = []
    monkeypatch.setattr(scheduler, "update_all_caches", lambda: calls.append("run"))
    scheduler._stop_event.set()

    scheduler._run()
    assert calls == []


def test_run_continues_loop_then_exits(monkeypatch):
    """_run continues for two iterations when wait returns False then True."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    calls = []

    class TwoIterEvent:
        def __init__(self):
            self._wait_count = 0

        def is_set(self):
            return False

        def wait(self, _interval):
            self._wait_count += 1
            # First wait: False (continue); second wait: True (break)
            return self._wait_count >= 2

        def set(self):
            pass

    monkeypatch.setattr(scheduler, "update_all_caches", lambda: calls.append("run"))
    scheduler._stop_event = TwoIterEvent()
    scheduler._run()

    assert len(calls) == 2


def test_run_second_iteration_uses_debug_log(monkeypatch):
    """Second run through the loop uses the non-first-run log path."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._first_run = False  # Simulate already ran once

    class OneIterEvent:
        def is_set(self):
            return False

        def wait(self, _interval):
            return True

        def set(self):
            pass

    logged = []
    monkeypatch.setattr(scheduler, "update_all_caches", lambda: None)
    monkeypatch.setattr(module.logger, "debug", lambda msg, *_a, **_k: logged.append(msg))
    scheduler._stop_event = OneIterEvent()
    scheduler._run()

    assert any("scheduled" in str(m) for m in logged)


def test_run_does_not_set_cache_ready_twice(monkeypatch):
    """cache_ready_event.set() is called only once even over multiple iterations."""
    scheduler = module.CacheScheduler(interval_seconds=1)

    iteration = [0]

    class TwoIterEvent:
        def is_set(self):
            return False

        def wait(self, _interval):
            iteration[0] += 1
            return iteration[0] >= 2

        def set(self):
            pass

    monkeypatch.setattr(scheduler, "update_all_caches", lambda: None)
    scheduler._stop_event = TwoIterEvent()
    scheduler._run()

    assert scheduler.cache_ready_event.is_set()


def test_acquire_lock_outer_ioerror_covers_lines_69_70(monkeypatch, tmp_path):
    """Lines 69-70: IOError from fcntl on non-windows propagates to outer except.

    Open succeeds (lock_file is set), then flock raises → outer except closes file.
    Lines 61, 69-70, 82 are in the Linux/fcntl branch and are not coverable on Windows
    (fcntl is not imported). This test is skipped on Windows.
    """
    import sys
    if sys.platform == "win32":
        pytest.skip("fcntl branch not coverable on Windows")

    scheduler = module.CacheScheduler(interval_seconds=1)
    dummy_file = DummyFile()

    monkeypatch.setattr(module, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: dummy_file)

    import types
    mock_fcntl = types.SimpleNamespace(
        LOCK_EX=2,
        LOCK_NB=4,
        flock=lambda fd, op: (_ for _ in ()).throw(IOError("device busy")),
    )
    monkeypatch.setattr(module, "fcntl", mock_fcntl)

    assert scheduler._acquire_lock() is False
    assert scheduler._lock_file is None
    assert dummy_file.closed is True


def test_release_lock_logger_raises_is_swallowed(monkeypatch, tmp_path):
    """Lines 91-92: ValueError from logger.error is caught silently."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    scheduler._lock_file = DummyFile()
    scheduler._has_lock = True

    monkeypatch.setattr(module.sys, "platform", "win32")
    # locking raises → outer except → logger.error raises ValueError → lines 91-92
    monkeypatch.setattr(module.msvcrt, "locking", lambda *_a, **_k: (_ for _ in ()).throw(Exception("fail")))
    monkeypatch.setattr(module.logger, "error", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("log closed")))

    scheduler._release_lock()  # must not propagate any exception


def test_run_exception_in_update_all_caches_is_logged(monkeypatch):
    """Line 118 (except Exception): update_all_caches raises → logged, loop continues."""
    scheduler = module.CacheScheduler(interval_seconds=1)
    calls = [0]

    def _failing_update():
        calls[0] += 1
        raise RuntimeError("boom")

    class OneIterEvent:
        def is_set(self):
            return False

        def wait(self, _interval):
            return True  # stop after first iteration

        def set(self):
            pass

    monkeypatch.setattr(scheduler, "update_all_caches", _failing_update)
    scheduler._stop_event = OneIterEvent()
    scheduler._run()  # must not propagate the exception

    assert calls[0] == 1
