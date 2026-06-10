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
from constants import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT

# Global logger registry to prevent duplicate handlers
_loggers = {}

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

    # Clear any existing handlers
    logger.handlers.clear()

    # Ensure log directory exists
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # File handler with rotation - always captures all levels based on LOG_LEVEL
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    file_handler.setLevel(_get_log_level())

    # Enhanced formatter with module name and function
    file_formatter = _ConfiguredTzFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

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

    for logger in _loggers.values():
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(new_level)


def get_current_log_level():
    """Get current global log level"""
    return LOG_LEVEL
