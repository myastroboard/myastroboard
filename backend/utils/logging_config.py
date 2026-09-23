"""
Centralized logging configuration for MyAstroBoard backend
Provides consistent logging setup across all modules with configurable log levels
"""

import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional
from utils.constants import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT
from utils.file_lock import interprocess_lock

# Global logger registry to prevent duplicate handlers
_loggers = {}

# The single file handler shared by every logger of this process (created lazily)
_file_handler: Optional[logging.Handler] = None

# Environment variable for log level control (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()


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

    def emit(self, record):
        try:
            with interprocess_lock(self.lock_path):
                self._reopen_if_replaced()
                super().emit(record)
                if sys.platform == "win32" and self.stream is not None:
                    # Windows refuses to rename a file another process holds open,
                    # so release it between writes to let any worker rotate it.
                    self._release_stream()
        except Exception:
            self.handleError(record)


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
