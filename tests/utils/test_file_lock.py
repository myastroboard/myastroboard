"""Tests for the cross-process file lock shared by gunicorn workers (utils/file_lock.py)."""

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from utils import file_lock
from utils.file_lock import interprocess_lock

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


def test_lock_creates_missing_parent_directory(tmp_path):
    lock_path = tmp_path / "nested" / "dir" / "state.json.lock"
    with interprocess_lock(str(lock_path)):
        assert lock_path.exists()


def test_lock_is_released_when_body_raises(tmp_path):
    lock_path = str(tmp_path / "state.lock")
    with pytest.raises(RuntimeError):
        with interprocess_lock(lock_path):
            raise RuntimeError("boom")
    with interprocess_lock(lock_path):
        pass  # would block (or raise on Windows) if the first lock leaked


def test_threads_of_one_process_exclude_each_other(tmp_path):
    lock_path = str(tmp_path / "state.lock")
    counter = tmp_path / "counter.txt"
    counter.write_text("0")

    def _bump(times):
        for _ in range(times):
            with interprocess_lock(lock_path):
                value = int(counter.read_text())
                counter.write_text(str(value + 1))

    threads = [threading.Thread(target=_bump, args=(50,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert int(counter.read_text()) == 200


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt retry path only exists on Windows")
def test_msvcrt_lock_retries_then_gives_up(monkeypatch):
    calls = []

    def _always_busy(*_args):
        calls.append(1)
        raise OSError("busy")

    monkeypatch.setattr(file_lock.msvcrt, "locking", _always_busy)
    monkeypatch.setattr(file_lock.time, "sleep", lambda _s: None)
    with pytest.raises(OSError):
        file_lock._msvcrt_lock(0)
    assert len(calls) == 6


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt retry path only exists on Windows")
def test_msvcrt_lock_succeeds_after_transient_contention(monkeypatch):
    outcomes = [OSError("busy"), None]

    def _busy_once(*_args):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome

    monkeypatch.setattr(file_lock.msvcrt, "locking", _busy_once)
    monkeypatch.setattr(file_lock.time, "sleep", lambda _s: None)
    file_lock._msvcrt_lock(0)
    assert outcomes == []


_BUMP_SCRIPT = textwrap.dedent(
    """
    import sys
    from utils.file_lock import interprocess_lock

    lock_path, counter_path, times = sys.argv[1], sys.argv[2], int(sys.argv[3])
    for _ in range(times):
        with interprocess_lock(lock_path):
            with open(counter_path, encoding="utf-8") as handle:
                value = int(handle.read())
            with open(counter_path, "w", encoding="utf-8") as handle:
                handle.write(str(value + 1))
    """
)


@pytest.mark.slow
def test_separate_processes_exclude_each_other(tmp_path):
    """Real OS processes (like gunicorn workers) doing read-modify-write never lose an update."""
    lock_path = tmp_path / "state.lock"
    counter = tmp_path / "counter.txt"
    counter.write_text("0", encoding="utf-8")
    workers, times = 4, 100
    env = dict(os.environ, PYTHONPATH=str(_BACKEND_DIR), DATA_DIR=str(tmp_path / "data"))

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _BUMP_SCRIPT, str(lock_path), str(counter), str(times)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(workers)
    ]
    for proc in procs:
        _out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err

    assert int(counter.read_text(encoding="utf-8")) == workers * times
