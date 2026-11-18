"""Tests for utils.lru_cache.LruCache, the bounded LRU shared by request threads."""

import random
import sys
import threading

from utils.lru_cache import LruCache


class TestLruCacheBehaviour:
    def test_get_returns_default_on_a_miss(self):
        """A missing key gives the default, None unless one is passed."""
        cache = LruCache(2)
        assert cache.get('a') is None
        assert cache.get('a', 'fallback') == 'fallback'

    def test_put_returns_the_value_and_stores_it(self):
        """put() hands the value back so callers can cache and return in one line."""
        cache = LruCache(2)
        assert cache.put('a', 1) == 1
        assert cache.get('a') == 1
        assert 'a' in cache
        assert len(cache) == 1

    def test_evicts_the_least_recently_used_entry(self):
        """Reading a key protects it: the entry evicted is the one not touched for longest."""
        cache = LruCache(2)
        cache.put('a', 1)
        cache.put('b', 2)
        cache.get('a')
        cache.put('c', 3)
        assert 'b' not in cache
        assert list(cache) == ['a', 'c']

    def test_limit_passed_to_put_wins_over_the_constructor_one(self):
        """Modules pass their limit constant on every put, so a test can lower it at runtime."""
        cache = LruCache(10)
        for key in range(5):
            cache.put(key, key, limit=2)
        assert list(cache) == [3, 4]

    def test_limit_is_at_least_one(self):
        """A zero or negative limit still keeps the latest value instead of failing."""
        cache = LruCache(0)
        cache.put('a', 1)
        assert cache.get('a') == 1

    def test_clear_empties_the_cache(self):
        cache = LruCache(3)
        cache.put('a', 1)
        cache.clear()
        assert len(cache) == 0
        assert cache.get('a') is None

    def test_iteration_is_a_snapshot(self):
        """Iterating while writing does not raise, since the keys are copied first."""
        cache = LruCache(10)
        for key in range(3):
            cache.put(key, key)
        for key in cache:
            cache.put(key + 100, key)
        assert len(cache) == 6


class TestLruCacheUnderThreads:
    def test_concurrent_gets_and_puts_never_raise(self):
        """Readers and writers hammering a tiny cache from many threads see no KeyError.

        With a plain OrderedDict, a reader's move_to_end raced with a writer evicting the
        same key; a request thread then failed with KeyError (HTTP 500).
        """
        cache = LruCache(4)
        errors: list[BaseException] = []
        start = threading.Barrier(8)

        def worker(seed: int) -> None:
            rng = random.Random(seed)
            start.wait()
            try:
                for _ in range(5000):
                    key = rng.randrange(12)
                    if cache.get(key) is None:
                        cache.put(key, key)
                    list(cache)
            except BaseException as error:  # pragma: no cover - only reached on a regression
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(seed,)) for seed in range(8)]
        previous = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)  # switch threads as often as possible to expose races
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            sys.setswitchinterval(previous)
        assert errors == []
        assert len(cache) <= 4
