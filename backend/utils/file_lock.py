"""
Cross-process file lock for state shared between gunicorn workers.

Every gunicorn worker is a separate OS process, so a ``threading.Lock`` only
serializes threads inside one worker. Code that read-modify-writes a file on
disk (or rotates one) must also hold this lock to be safe against the other
workers.

This module deliberately imports nothing from the rest of the backend so the
logging setup can use it without an import cycle.
"""

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator

if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover
    import fcntl


def _msvcrt_lock(fileno: int) -> None:
    """Acquire a 1-byte msvcrt lock, retrying past the default ~10s deadlock timeout.

    msvcrt.locking(LK_LOCK) raises OSError after ~10 blocked seconds; under brief
    contention between workers that is a false failure rather than a real
    deadlock, so retry a few times before giving up.
    """
    attempts = 6
    for attempt in range(attempts):  # pragma: no branch - fixed positive literal, always >= 1 iteration
        try:
            msvcrt.locking(fileno, msvcrt.LK_LOCK, 1)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2)


@contextmanager
def interprocess_lock(lock_path: str) -> Iterator[None]:
    """Hold an exclusive lock on ``lock_path`` across processes (flock on POSIX, msvcrt on Windows).

    The lock file is created if missing and left in place afterwards. It is
    opened per acquisition rather than kept open, so a lock object inherited
    across fork() never shares one open file description (and hence one flock)
    between parent and child. Two threads of the same process also exclude each
    other, since each acquisition opens its own descriptor.
    """
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    lock_file = open(lock_path, "a+")
    try:
        if sys.platform == "win32":
            lock_file.seek(0)
            _msvcrt_lock(lock_file.fileno())
        else:  # pragma: no cover
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
