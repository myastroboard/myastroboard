"""Size cap for flat on-disk caches of re-downloadable files (survey images).

A cache directory holds files that can always be fetched again, so the oldest ones can
be deleted whenever it grows too large. ``WritePruner`` counts the writes and trims the
directory every few of them, instead of walking it on each write.
"""

import os
import threading
from collections.abc import Callable

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Once over the cap, the cache is trimmed to this share of it, so the next writes do
# not trigger a trim each.
_TRIM_TO_SHARE = 0.8


def prune_oldest_files(directory: str, max_bytes: int, label: str) -> int:
    """Delete the oldest files of *directory* once it outgrows *max_bytes*; return how many.

    The cache is trimmed to 80 % of *max_bytes*. A file that cannot be read or removed
    is skipped. *label* names the cache in the log line.
    """
    entries = []
    total = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size
    if total <= max_bytes:
        return 0

    target = int(max_bytes * _TRIM_TO_SHARE)
    removed = 0
    for _mtime, size, path in sorted(entries):
        if total <= target:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        removed += 1
    logger.info(f'{label} trimmed: {removed} files removed, {total // (1024 * 1024)} MiB kept')
    return removed


class WritePruner:
    """Run *prune* once every *every_writes* calls to ``note_write()`` (thread-safe)."""

    def __init__(self, prune: Callable[[], object], every_writes: int):
        self._prune = prune
        self._every_writes = every_writes
        self._writes = 0
        self._lock = threading.Lock()

    def note_write(self) -> None:
        with self._lock:
            self._writes += 1
            due = self._writes >= self._every_writes
            if due:
                self._writes = 0
        if due:
            self._prune()
