"""A bounded, least-recently-used in-process cache that request threads can share.

The web server runs one process with several request threads (gunicorn ``gthread``), so a
plain ``OrderedDict`` LRU is no longer safe: between one thread's ``get`` and its
``move_to_end``, another thread can evict the key and the first one raises ``KeyError``.
Every operation here holds one lock; the value itself is computed outside it, so two
threads missing the same key at once both compute it (harmless, the last write wins) rather
than one blocking the other for the length of a calculation.
"""

import threading
from collections import OrderedDict
from collections.abc import Hashable, Iterator
from typing import Any

_MISSING = object()


class LruCache:
    """A bounded LRU mapping; ``limit`` is read on every ``put`` so tests can lower it."""

    def __init__(self, limit: int):
        self.limit = limit
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        """The cached value (marked most recently used), or *default*."""
        with self._lock:
            value = self._entries.get(key, _MISSING)
            if value is _MISSING:
                return default
            self._entries.move_to_end(key)
            return value

    def put(self, key: Hashable, value: Any, limit: int | None = None) -> Any:
        """Store *value*, evict the least recently used entries past the limit, return *value*."""
        bound = max(1, int(self.limit if limit is None else limit))
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > bound:
                self._entries.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __iter__(self) -> Iterator[Hashable]:
        """A snapshot of the keys, oldest first (safe while other threads write)."""
        with self._lock:
            return iter(list(self._entries))
