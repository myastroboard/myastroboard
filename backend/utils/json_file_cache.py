"""Large JSON files parsed once and shared by the request threads of the process.

The SkyTonight results of a location (``dso_results.json``) are a 15 MB file that parses into
about 40 MB of Python objects. Reading it on every request cost about 100 ms of CPU each time,
and as many 40 MB copies as there were requests in flight: a few members opening SkyTonight
together could push a small host out of memory. Here one parsed copy is kept per file, reloaded
when the file changes, and dropped once nobody has asked for it for a few minutes.

The returned objects are shared: callers must treat them as read-only (build new rows, sort a
new list). A caller that needs to change the data loads the file itself.
"""

import os
import threading
import time
from typing import Any

from utils import load_json_file
from utils.logging_config import get_logger

logger = get_logger(__name__)

# A file nobody read for this long is dropped, so an idle instance gives the memory back.
IDLE_SECONDS = 300.0
# At most this many files are kept (one per location for each kind of file shared).
MAX_FILES = 8

_entries: dict[str, dict[str, Any]] = {}
_entries_lock = threading.Lock()
# One parse at a time: threads asking for the same file while it loads wait and share it.
_load_lock = threading.Lock()


def _signature(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _cached(path: str, signature: tuple[int, int], now: float) -> Any:
    """The cached data for *path* when it matches *signature* (caller holds the entries lock)."""
    entry = _entries.get(path)
    if entry is None or entry['signature'] != signature:
        return None
    entry['last_used'] = now
    return entry['data']


def drop_idle(now: float | None = None) -> int:
    """Forget the files not read for IDLE_SECONDS; return how many were dropped."""
    now = time.monotonic() if now is None else now
    with _entries_lock:
        idle = [path for path, entry in _entries.items() if now - entry['last_used'] > IDLE_SECONDS]
        for path in idle:
            del _entries[path]
    return len(idle)


def clear() -> None:
    """Forget every file (tests)."""
    with _entries_lock:
        _entries.clear()


def load_shared_json(path: str, default: Any = None) -> Any:
    """The parsed content of *path*, shared with other threads: never modify it.

    Returns *default* when the file is missing or unreadable (that answer is not cached, so
    the file is read again once it appears).
    """
    signature = _signature(path)
    if signature is None:
        return default
    now = time.monotonic()
    with _entries_lock:
        data = _cached(path, signature, now)
    if data is not None:
        return data

    with _load_lock:
        signature = _signature(path)
        if signature is None:
            return default
        with _entries_lock:
            data = _cached(path, signature, now)
        if data is not None:
            return data
        unreadable: dict[str, Any] = {}
        data = load_json_file(path, default=unreadable)
        if data is unreadable:
            return default
        with _entries_lock:
            _entries[path] = {'signature': signature, 'data': data, 'last_used': now}
            while len(_entries) > MAX_FILES:
                oldest = min(_entries, key=lambda key: _entries[key]['last_used'])
                del _entries[oldest]
    drop_idle(now)
    return data
