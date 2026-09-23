"""Unit tests for backend logging configuration helpers."""

import logging
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from utils import logging_config as module

_ConfiguredTzFormatter = module._ConfiguredTzFormatter


class DummyRotatingHandler(logging.Handler):
    """Minimal rotating handler replacement for tests."""

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _reset_logging_module_state(monkeypatch):
    module._loggers.clear()
    monkeypatch.setattr(module, "LOG_LEVEL", "INFO")
    monkeypatch.setattr(module, "_file_handler", None)
    yield
    module._loggers.clear()


def test_get_log_level_defaults_to_info_for_unknown_level(monkeypatch):
    monkeypatch.setattr(module, "LOG_LEVEL", "NOT_A_LEVEL")
    assert module._get_log_level() == logging.INFO


def test_setup_logger_without_console_adds_only_file_handler(monkeypatch):
    monkeypatch.setattr(module, "MultiProcessRotatingFileHandler", DummyRotatingHandler)
    monkeypatch.setattr(module.os, "makedirs", lambda *_args, **_kwargs: None)

    logger = module.setup_logger("test.no_console", include_console=False)

    assert logger.name == "test.no_console"
    assert logger.propagate is False
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], DummyRotatingHandler)


class _BrokenCloseHandler(logging.Handler):
    """A handler whose close() raises, simulating an already-broken file handle."""

    def close(self):
        raise OSError("close failed")


def test_setup_logger_closes_stale_handlers_ignoring_close_errors(monkeypatch):
    """A module reload can re-enter setup_logger for an already-configured stdlib
    logger name (Python caches loggers globally by name); if one of its old
    handlers raises on close, that must not prevent the rest of the
    reconfiguration from completing."""
    monkeypatch.setattr(module, "MultiProcessRotatingFileHandler", DummyRotatingHandler)
    monkeypatch.setattr(module.os, "makedirs", lambda *_args, **_kwargs: None)

    logger = module.setup_logger("test.close_exc", include_console=False)
    logger.addHandler(_BrokenCloseHandler())
    module._loggers.clear()  # simulate losing our own cache without losing the stdlib logger

    reconfigured = module.setup_logger("test.close_exc", include_console=False)

    assert reconfigured is logger
    assert len(reconfigured.handlers) == 1
    assert isinstance(reconfigured.handlers[0], DummyRotatingHandler)


def test_setup_logger_with_console_level_override(monkeypatch):
    monkeypatch.setattr(module, "MultiProcessRotatingFileHandler", DummyRotatingHandler)
    monkeypatch.setattr(module.os, "makedirs", lambda *_args, **_kwargs: None)

    logger = module.setup_logger("test.console", include_console=True, console_level="error")

    assert len(logger.handlers) == 2
    console_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(console_handlers) == 1
    assert console_handlers[0].level == logging.ERROR


def test_get_logger_returns_cached_instance(monkeypatch):
    monkeypatch.setattr(module, "MultiProcessRotatingFileHandler", DummyRotatingHandler)
    monkeypatch.setattr(module.os, "makedirs", lambda *_args, **_kwargs: None)

    first = module.setup_logger("test.cached", include_console=False)
    second = module.get_logger("test.cached", include_console=True)

    assert first is second


def test_set_global_log_level_updates_file_handlers(monkeypatch):
    monkeypatch.setattr(module, "MultiProcessRotatingFileHandler", DummyRotatingHandler)
    monkeypatch.setattr(module.os, "makedirs", lambda *_args, **_kwargs: None)

    logger = module.setup_logger("test.level_update", include_console=True)
    module.set_global_log_level("error")

    file_handlers = [h for h in logger.handlers if isinstance(h, DummyRotatingHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.ERROR
    assert module.get_current_log_level() == "ERROR"


def test_configured_tz_formatter_loads_tz_from_env(monkeypatch):
    """_get_tz() reads the TZ environment variable and returns the matching ZoneInfo."""
    # Reset class state so the lazy loader runs again
    _ConfiguredTzFormatter._cached_tz = None
    _ConfiguredTzFormatter._tz_resolved = False

    monkeypatch.setenv("TZ", "Europe/Paris")

    tz = _ConfiguredTzFormatter._get_tz()
    assert tz is not None
    assert str(tz) == "Europe/Paris"

    # Restore class state so other tests are not affected
    _ConfiguredTzFormatter._cached_tz = None
    _ConfiguredTzFormatter._tz_resolved = False


def test_configured_tz_formatter_falls_back_to_utc_on_invalid_tz(monkeypatch):
    """_get_tz() falls back to UTC when TZ names an invalid timezone."""
    _ConfiguredTzFormatter._cached_tz = None
    _ConfiguredTzFormatter._tz_resolved = False

    monkeypatch.setenv("TZ", "Not/A/Valid/Timezone")

    tz = _ConfiguredTzFormatter._get_tz()
    assert tz is not None
    from datetime import timezone

    assert tz == timezone.utc

    _ConfiguredTzFormatter._cached_tz = None
    _ConfiguredTzFormatter._tz_resolved = False


def test_format_time_with_datefmt():
    """formatTime returns strftime-formatted string when datefmt is provided."""
    formatter = _ConfiguredTzFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    result = formatter.formatTime(record, datefmt="%Y/%m/%d")
    # Should be a date string in YYYY/MM/DD format
    assert "/" in result
    assert len(result) == 10


# ---------------------------------------------------------------------------
# Shared, multi-process-safe file handler
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


def _make_record(msg="hello"):
    return logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_all_loggers_share_one_file_handler(monkeypatch, tmp_path):
    """Separate handlers on one file would each rotate it on their own, even in a single process."""
    monkeypatch.setattr(module, "LOG_FILE", str(tmp_path / "app.log"))

    first = module.setup_logger("test.shared_a", include_console=False)
    second = module.setup_logger("test.shared_b", include_console=False)

    assert first.handlers[0] is second.handlers[0]
    assert isinstance(first.handlers[0], module.MultiProcessRotatingFileHandler)
    first.handlers[0].close()


def test_reconfiguring_a_logger_keeps_the_shared_file_handler_open(monkeypatch, tmp_path):
    log_path = tmp_path / "app.log"
    monkeypatch.setattr(module, "LOG_FILE", str(log_path))

    other = module.setup_logger("test.keep_open_other", include_console=False)
    module.setup_logger("test.keep_open", include_console=False)
    module._loggers.pop("test.keep_open")
    module.setup_logger("test.keep_open", include_console=False)

    other.warning("still written")
    other.handlers[0].close()
    assert "still written" in log_path.read_text(encoding="utf-8")


def test_set_global_log_level_updates_shared_file_handler(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "LOG_FILE", str(tmp_path / "app.log"))

    logger = module.setup_logger("test.shared_level", include_console=False)
    module.set_global_log_level("error")

    assert logger.handlers[0].level == logging.ERROR
    logger.handlers[0].close()


def test_set_global_log_level_without_file_handler_only_records_level():
    module.set_global_log_level("debug")
    assert module.get_current_log_level() == "DEBUG"


def test_handler_reopens_log_renamed_by_another_writer(tmp_path):
    """Lines must go to the current log file, not a file another process rotated away."""
    log_path = tmp_path / "app.log"
    handler = module.MultiProcessRotatingFileHandler(str(log_path), maxBytes=0, backupCount=0, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(_make_record("before"))
        # Keep a stream open across the rename, as a Linux worker does between writes
        handler.stream = handler._open()
        stale = handler.stream
        if sys.platform == "win32":
            handler._release_stream()  # Windows refuses to rename an open file
        os.replace(log_path, tmp_path / "app.log.1")
        if sys.platform == "win32":
            handler.stream = stale = open(tmp_path / "app.log.1", "a", encoding="utf-8")
        handler.emit(_make_record("after"))
        assert stale.closed
    finally:
        handler.close()

    assert log_path.read_text(encoding="utf-8").splitlines() == ["after"]
    assert (tmp_path / "app.log.1").read_text(encoding="utf-8").splitlines() == ["before"]


def test_handler_drops_stream_when_log_path_is_gone(tmp_path):
    log_path = tmp_path / "app.log"
    handler = module.MultiProcessRotatingFileHandler(str(log_path), encoding="utf-8")
    try:
        handler.stream = open(tmp_path / "elsewhere.log", "a", encoding="utf-8")
        handler._reopen_if_replaced()  # app.log does not exist
        assert handler.stream is None
    finally:
        handler.close()


def test_release_stream_ignores_close_errors(tmp_path):
    handler = module.MultiProcessRotatingFileHandler(str(tmp_path / "app.log"), encoding="utf-8")

    class _BrokenStream:
        def close(self):
            raise OSError("close failed")

    handler.stream = _BrokenStream()  # type: ignore[assignment]
    handler._release_stream()
    assert handler.stream is None
    handler.close()


def test_release_stream_is_noop_when_already_none(tmp_path):
    handler = module.MultiProcessRotatingFileHandler(str(tmp_path / "app.log"), encoding="utf-8")
    assert handler.stream is None  # delay=True: nothing opened yet
    handler._release_stream()  # must be a no-op, not raise
    assert handler.stream is None
    handler.close()


def test_emit_keeps_stream_open_on_non_windows(tmp_path, monkeypatch):
    """The Windows-only close-between-writes step must not fire on other platforms.

    Patches logging_config's own `sys` name (not sys.platform globally) - mutating the
    real sys module's platform would also flip file_lock.interprocess_lock's own
    win32/posix branch, which imports fcntl only under the posix branch and would then
    fail for real on this Windows test machine.
    """
    import types

    handler = module.MultiProcessRotatingFileHandler(str(tmp_path / "app.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(module, "sys", types.SimpleNamespace(platform="linux"))
    try:
        handler.emit(_make_record("hello"))
        assert handler.stream is not None
    finally:
        handler.close()


def test_rollover_uses_on_disk_size_after_truncation(tmp_path):
    """After "Clear logs" truncates the file, no process may rotate a near-empty file."""
    log_path = tmp_path / "app.log"
    handler = module.MultiProcessRotatingFileHandler(str(log_path), maxBytes=200, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.stream = handler._open()
        for i in range(5):
            handler.stream.write(f"line {i:02d} " + "x" * 30 + "\n")
        handler.stream.flush()
        assert handler.stream.tell() > 150
        open(log_path, "w").close()  # what clear_logs_api does
        assert not handler.shouldRollover(_make_record("small"))
        handler.emit(_make_record("after clear"))
    finally:
        handler.close()

    assert not (tmp_path / "app.log.1").exists()
    assert log_path.read_text(encoding="utf-8").splitlines() == ["after clear"]


def test_rollover_triggers_when_file_would_exceed_max_bytes(tmp_path):
    log_path = tmp_path / "app.log"
    handler = module.MultiProcessRotatingFileHandler(str(log_path), maxBytes=50, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        assert handler.shouldRollover(_make_record("x" * 60)) is False  # empty file never rotates
        handler.emit(_make_record("x" * 40))
        handler.emit(_make_record("y" * 40))
    finally:
        handler.close()

    assert log_path.read_text(encoding="utf-8").splitlines() == ["y" * 40]
    assert (tmp_path / "app.log.1").read_text(encoding="utf-8").splitlines() == ["x" * 40]


def test_rollover_disabled_when_max_bytes_is_zero(tmp_path):
    handler = module.MultiProcessRotatingFileHandler(str(tmp_path / "app.log"), maxBytes=0, encoding="utf-8")
    assert handler.shouldRollover(_make_record()) is False
    handler.close()


def test_emit_errors_are_routed_to_handle_error(tmp_path, monkeypatch):
    handler = module.MultiProcessRotatingFileHandler(str(tmp_path / "app.log"), encoding="utf-8")
    handled = []
    monkeypatch.setattr(handler, "handleError", lambda record: handled.append(record))

    def _failing_lock(_path):
        raise OSError("lock unavailable")

    monkeypatch.setattr(module, "interprocess_lock", _failing_lock)

    record = _make_record()
    handler.emit(record)

    assert handled == [record]
    handler.close()


_WRITER_SCRIPT = textwrap.dedent("""
    import logging, sys
    from utils.logging_config import MultiProcessRotatingFileHandler

    log_path, worker, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    handler = MultiProcessRotatingFileHandler(log_path, maxBytes=2048, backupCount=500, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("writer")
    logger.propagate = False
    logger.addHandler(handler)
    for i in range(count):
        logger.warning("worker=%s line=%05d %s", worker, i, "x" * 40)
    handler.close()
    """)


@pytest.mark.slow
def test_concurrent_processes_lose_no_lines_and_keep_backups_ordered(tmp_path):
    """Several real OS processes (like gunicorn workers) write and rotate one log file under load."""
    log_path = tmp_path / "app.log"
    workers, lines_per_worker = 4, 300
    env = dict(os.environ, PYTHONPATH=str(_BACKEND_DIR), DATA_DIR=str(tmp_path / "data"))

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WRITER_SCRIPT, str(log_path), str(w), str(lines_per_worker)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for w in range(workers)
    ]
    for proc in procs:
        _out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        assert "Traceback" not in err, err  # handleError() prints logging failures to stderr

    backups = sorted((int(p.name.rsplit(".", 1)[1]), p) for p in tmp_path.glob("app.log.*") if p.suffix != ".lock")
    ordered_newest_first = [log_path] + [p for _num, p in backups]
    contents = [p.read_text(encoding="utf-8").splitlines() for p in reversed(ordered_newest_first)]

    # No line lost or duplicated
    written = [line.rsplit(" ", 1)[0] for lines in contents for line in lines]
    expected = {f"worker={w} line={i:05d}" for w in range(workers) for i in range(lines_per_worker)}
    assert len(written) == len(expected)
    assert set(written) == expected

    # Rotation happened, every file respects the size cap, and backup numbering is
    # monotonic: reading backups from highest number to the live file replays each
    # worker's lines in the order it wrote them.
    assert len(backups) > 1
    for path in ordered_newest_first:
        assert path.stat().st_size <= 2048
    for w in range(workers):
        seq = [int(m.group(1)) for m in (re.match(rf"worker={w} line=(\d+)", s) for s in written) if m]
        assert seq == list(range(lines_per_worker))
