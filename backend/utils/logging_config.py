"""
Centralized logging configuration for MyAstroBoard backend
Provides consistent logging setup across all modules with configurable log levels
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional
from utils.constants import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT
from utils.file_lock import interprocess_lock

# Global logger registry to prevent duplicate handlers
_loggers = {}

# The single file handler shared by every logger of this process (created lazily)
_file_handler: Optional[logging.Handler] = None

# Environment variable for log level control (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Time-based retention on top of the size-based rotation: log lines contain usernames
# and IP addresses (personal data), so they should not outlive a configured number of
# days. The number comes from a provider (app settings) registered by the app at
# startup - utils.app_settings imports this module, so it cannot be imported here.
# Checked at most once a day per process, to keep log writes cheap.
LOG_RETENTION_CHECK_INTERVAL_SECONDS = 24 * 3600
_retention_days_provider: Optional[Callable[[], int]] = None

# Leading timestamp written by _ConfiguredTzFormatter: "2026-09-27 17:20:22,646 +0000"
_TIMESTAMP_LENGTH = len('2026-09-27 17:20:22,646 +0000')
_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S,%f %z'
# Bytes read from the head of a log file to find its oldest record
_HEAD_BYTES = 64 * 1024


class _ConfiguredTzFormatter(logging.Formatter):
    """Formatter that timestamps log records using the TZ environment variable.

    The timezone is resolved lazily on the first log record and cached for the
    lifetime of the process. Falls back to UTC if TZ is unset or invalid.
    The UTC offset is always appended to the timestamp so records are
    unambiguous without cross-referencing the container configuration.
    """

    _cached_tz = None
    _tz_resolved = False

    @classmethod
    def _get_tz(cls):
        if cls._tz_resolved:
            return cls._cached_tz
        cls._tz_resolved = True
        try:
            from zoneinfo import ZoneInfo

            tz_name = os.environ.get('TZ', 'UTC')
            cls._cached_tz = ZoneInfo(tz_name)
        except Exception:
            cls._cached_tz = timezone.utc
        return cls._cached_tz

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self._get_tz())
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S') + f',{int(record.msecs):03d}' + dt.strftime(' %z')


class MultiProcessRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that is safe when several processes share one log file.

    The stdlib handler assumes it is the only writer: each instance decides on
    its own when to rotate (from its own view of the file size) and keeps
    writing to its open descriptor after another writer has renamed the file
    away. Under several gunicorn workers that silently sends lines into the
    rotated backups and produces out-of-order backup numbering.

    This subclass serializes every write and rotation across processes with a
    lock file next to the log, reopens the log when another process has
    replaced it, and decides on rotation from the file's real on-disk size.
    On Windows the file is also closed between writes, since another process
    cannot rename a file that is held open there.
    """

    def __init__(self, filename: str, maxBytes: int = 0, backupCount: int = 0, encoding: Optional[str] = None):
        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding, delay=True)
        self.lock_path = self.baseFilename + ".lock"
        self.next_retention_check = 0.0

    def _reopen_if_replaced(self):
        """Drop the open stream when the path no longer points at the file it writes to."""
        if self.stream is None:
            return
        try:
            on_disk = os.stat(self.baseFilename)
            current = os.fstat(self.stream.fileno())
            replaced = (on_disk.st_dev, on_disk.st_ino) != (current.st_dev, current.st_ino)
        except OSError:
            replaced = True  # renamed away or deleted by another process
        if replaced:
            self._release_stream()

    def _release_stream(self):
        """Close the stream without marking the handler closed; the next emit reopens it."""
        stream = self.stream
        if stream is None:
            return
        self.stream = None  # type: ignore[assignment]
        try:
            stream.close()
        except OSError:
            pass  # Best-effort close; the stream is being abandoned anyway

    def shouldRollover(self, record):
        """Rotate based on the real file size, not this process's stream position.

        Another process may have written to, rotated or truncated the file
        (e.g. "Clear logs"), so the stream's own tell() is not trustworthy.
        """
        if self.maxBytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        size = os.fstat(self.stream.fileno()).st_size
        if size == 0:
            return False
        msg = "%s\n" % self.format(record)
        return size + len(msg.encode(self.encoding or "utf-8")) >= self.maxBytes

    def _due_retention_days(self) -> int:
        """Retention in days when the daily pass is due, else 0.

        Called *before* taking the lock: the provider reads app settings, which may log,
        and a log call re-entering emit() while this process holds the (non-reentrant)
        lock would deadlock. The check time is bumped first, so that nested call skips it.
        """
        now = time.time()
        if now < self.next_retention_check:
            return 0
        self.next_retention_check = now + LOG_RETENTION_CHECK_INTERVAL_SECONDS
        return _current_retention_days()

    def emit(self, record):
        try:
            retention_days = self._due_retention_days()
            with interprocess_lock(self.lock_path):
                if retention_days > 0:
                    _apply_retention_unlocked(self.baseFilename, self.backupCount, retention_days, time.time())
                self._reopen_if_replaced()
                super().emit(record)
                if sys.platform == "win32" and self.stream is not None:
                    # Windows refuses to rename a file another process holds open,
                    # so release it between writes to let any worker rotate it.
                    self._release_stream()
        except Exception:
            self.handleError(record)


def _record_time(line: bytes) -> Optional[float]:
    """Epoch time of a log line that starts a record, None for continuation lines."""
    try:
        stamp = line[:_TIMESTAMP_LENGTH].decode('ascii')
        return datetime.strptime(stamp, _TIMESTAMP_FORMAT).timestamp()
    except (UnicodeDecodeError, ValueError):
        return None


def _oldest_record_time(path: str) -> Optional[float]:
    """Time of the first timestamped line in ``path``, None when absent or unreadable."""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(_HEAD_BYTES)
    except OSError:
        return None
    for line in head.splitlines():
        stamp = _record_time(line)
        if stamp is not None:
            return stamp
    return None


def _trim_log_file(path: str, cutoff: float, is_active: bool) -> bool:
    """Drop the records of ``path`` older than ``cutoff``; return True when the file changed.

    A backup with nothing left to keep is deleted; the active file is emptied instead,
    so writers keep a stable path. A traceback belongs to the record above it, so the
    cut is made at the first *timestamped* line recent enough to keep.
    """
    data = b''
    oldest = _oldest_record_time(path)
    if oldest is None:
        # Unknown format: fall back to the last write time for the whole file
        try:
            expired = os.path.getmtime(path) < cutoff
        except OSError:
            return False
        if not expired:
            return False
        keep_from = None
    elif oldest >= cutoff:
        return False
    else:
        with open(path, 'rb') as handle:
            data = handle.read()
        keep_from = None
        offset = 0
        for line in data.splitlines(keepends=True):
            stamp = _record_time(line)
            if stamp is not None and stamp >= cutoff:
                keep_from = offset
                break
            offset += len(line)

    if keep_from is None:
        if is_active:
            open(path, 'wb').close()
        else:
            os.remove(path)
        return True

    tmp_path = path + '.retention.tmp'
    with open(tmp_path, 'wb') as handle:
        handle.write(data[keep_from:])
    os.replace(tmp_path, path)
    return True


def _apply_retention_unlocked(base_path: str, backup_count: int, days: int, now: float) -> int:
    """Trim the log and its rotated backups to ``days``; return how many files changed."""
    cutoff = now - days * 86400
    changed = 0
    paths = [(base_path, True)] + [(f"{base_path}.{index}", False) for index in range(1, backup_count + 1)]
    for path, is_active in paths:
        if not os.path.exists(path):
            continue
        try:
            if _trim_log_file(path, cutoff, is_active):
                changed += 1
        except OSError as error:
            sys.stderr.write(f"Log retention: could not trim {path}: {error}\n")
    return changed


def _current_retention_days() -> int:
    if _retention_days_provider is None:
        return 0
    try:
        return max(0, int(_retention_days_provider()))
    except Exception:
        return 0  # a broken provider must never break logging


def set_log_retention_provider(provider: Optional[Callable[[], int]]) -> None:
    """Register the callable returning the retention in days (0 = size-based rotation only)."""
    global _retention_days_provider
    _retention_days_provider = provider
    if _file_handler is not None:
        _file_handler.next_retention_check = 0.0  # type: ignore[attr-defined]


def apply_log_retention(days: Optional[int] = None) -> int:
    """Apply the retention now (e.g. right after the setting changed); return how many files changed."""
    days = _current_retention_days() if days is None else max(0, int(days))
    if days <= 0:
        return 0
    base_path = os.path.abspath(LOG_FILE)  # same path, hence same lock, as the file handler
    with interprocess_lock(base_path + '.lock'):
        return _apply_retention_unlocked(base_path, LOG_BACKUP_COUNT, days, time.time())


def _get_file_handler() -> logging.Handler:
    """Return this process's single shared log-file handler, creating it on first use.

    Every module logger shares one handler instance: separate handlers on the
    same file would each rotate it independently, even within one process.
    """
    global _file_handler
    if _file_handler is None:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        handler = MultiProcessRotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
        )
        handler.setLevel(_get_log_level())
        handler.setFormatter(
            _ConfiguredTzFormatter('%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s')
        )
        _file_handler = handler
    return _file_handler


def _get_log_level():
    """Convert string log level to logging constant"""
    levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }
    return levels.get(LOG_LEVEL, logging.INFO)


def setup_logger(name: str, include_console: bool = True, console_level: Optional[str] = None) -> logging.Logger:
    """
    Set up a logger with standard configuration for MyAstroBoard

    Args:
        name: Logger name (typically __name__)
        include_console: Whether to include console output (default: True)
        console_level: Override console log level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    # Return existing logger if already configured
    if name in _loggers:
        return _loggers[name]

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all levels

    # Clear any existing handlers, closing them first: Python caches loggers
    # globally by name, so a module reload can reach this point for a logger
    # that still carries file handlers from its previous configuration.
    for old_handler in logger.handlers[:]:
        if old_handler is _file_handler:
            continue  # Shared with every other logger; must stay open
        try:
            old_handler.close()
        except Exception:
            pass  # Best-effort close; stream may already be closed/invalid
    logger.handlers.clear()

    # File handler with rotation (one per process, shared by all loggers) - level based on LOG_LEVEL
    logger.addHandler(_get_file_handler())

    # Console handler (optional) - can have different level
    if include_console:
        console_handler = logging.StreamHandler(sys.stdout)

        # Use specified level or default to WARNING for console to reduce noise
        console_log_level = console_level or os.environ.get('CONSOLE_LOG_LEVEL', 'WARNING')
        console_handler.setLevel(getattr(logging, console_log_level.upper(), logging.WARNING))

        console_formatter = _ConfiguredTzFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    # Register logger
    _loggers[name] = logger

    return logger


def get_logger(name: str, include_console: bool = True, console_level: Optional[str] = None) -> logging.Logger:
    """
    Get or create a logger with standard configuration

    Args:
        name: Logger name (typically __name__)
        include_console: Whether to include console output (default: True)
        console_level: Override console log level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    return setup_logger(name, include_console, console_level)


def set_global_log_level(level: str):
    """
    Change log level for all existing loggers

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    global LOG_LEVEL
    LOG_LEVEL = level.upper()
    new_level = _get_log_level()

    if _file_handler is not None:
        _file_handler.setLevel(new_level)


def get_current_log_level():
    """Get current global log level"""
    return LOG_LEVEL
