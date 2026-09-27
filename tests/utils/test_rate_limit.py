"""Tests for utils.rate_limit.SlidingWindowCounter."""

from utils.rate_limit import SlidingWindowCounter


def test_exceeded_after_max_events_within_window():
    counter = SlidingWindowCounter(max_events=3, window_seconds=60)
    for second in range(3):
        assert counter.exceeded('k', now=100 + second) is False
        counter.record('k', now=100 + second)
    assert counter.exceeded('k', now=103) is True


def test_events_expire_after_window():
    counter = SlidingWindowCounter(max_events=2, window_seconds=60)
    counter.record('k', now=0)
    counter.record('k', now=10)
    assert counter.exceeded('k', now=59) is True
    assert counter.exceeded('k', now=61) is False


def test_retry_after_counts_down_to_the_oldest_blocking_event():
    counter = SlidingWindowCounter(max_events=2, window_seconds=60)
    assert counter.retry_after('k', now=0) == 0
    counter.record('k', now=0)
    counter.record('k', now=30)
    assert counter.retry_after('k', now=40) == 20
    assert counter.retry_after('k', now=61) == 0


def test_keys_are_independent_and_clearable():
    counter = SlidingWindowCounter(max_events=1, window_seconds=60)
    counter.record('a', now=0)
    assert counter.exceeded('a', now=1) is True
    assert counter.exceeded('b', now=1) is False
    counter.clear('a')
    assert counter.exceeded('a', now=1) is False
    counter.record('b', now=0)
    counter.clear()
    assert counter.exceeded('b', now=1) is False


def test_record_prunes_fully_expired_keys_past_threshold(monkeypatch):
    counter = SlidingWindowCounter(max_events=1, window_seconds=60)
    monkeypatch.setattr(SlidingWindowCounter, '_PRUNE_THRESHOLD', 2)
    counter.record('old-1', now=0)
    counter.record('old-2', now=0)
    counter.record('fresh', now=1000)
    assert set(counter._events) == {'fresh'}
