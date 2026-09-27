"""In-memory sliding-window failure counter.

Counts events (typically failures) per key over a time window. State lives in the
process: under ``gunicorn -w N`` each worker keeps its own counts, so the effective
ceiling is ``max_events`` per worker - still bounded, and the same trade-off the
existing OTP and connector rate limiters accept.
"""

import time
from collections import deque
from threading import Lock
from typing import Dict, Optional


class SlidingWindowCounter:
    """Track timestamps per key and tell when a key reached ``max_events`` within ``window_seconds``."""

    # Past this many keys, a record() also drops every key whose events all expired
    _PRUNE_THRESHOLD = 512

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._events: Dict[str, deque] = {}

    def _expire(self, hits: deque, now: float) -> None:
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()

    def exceeded(self, key: str, now: Optional[float] = None) -> bool:
        """True when ``key`` already has ``max_events`` events inside the window."""
        now = time.time() if now is None else now
        with self._lock:
            hits = self._events.get(key)
            if not hits:
                return False
            self._expire(hits, now)
            return len(hits) >= self.max_events

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until ``key`` drops back under the limit (0 when it is not limited)."""
        now = time.time() if now is None else now
        with self._lock:
            hits = self._events.get(key)
            if not hits:
                return 0
            self._expire(hits, now)
            if len(hits) < self.max_events:
                return 0
            oldest_blocking = hits[len(hits) - self.max_events]
            return max(1, int(oldest_blocking + self.window_seconds - now + 0.999))

    def record(self, key: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            hits = self._events.setdefault(key, deque())
            self._expire(hits, now)
            hits.append(now)
            if len(self._events) > self._PRUNE_THRESHOLD:
                for other in list(self._events):
                    other_hits = self._events[other]
                    self._expire(other_hits, now)
                    if not other_hits:
                        del self._events[other]

    def clear(self, key: Optional[str] = None) -> None:
        """Forget ``key``, or every key when called without one."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
