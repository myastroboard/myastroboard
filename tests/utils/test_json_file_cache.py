"""Tests for utils.json_file_cache, the shared parsed copies of large result files."""

import json
import os
import threading
import time

import pytest

from utils import json_file_cache


@pytest.fixture(autouse=True)
def _empty_cache():
    json_file_cache.clear()
    yield
    json_file_cache.clear()


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding='utf-8')


def _count_loads(monkeypatch, delay=0.0):
    loads = []
    real_load = json_file_cache.load_json_file

    def counting_load(path, default=None):
        loads.append(path)
        if delay:
            time.sleep(delay)
        return real_load(path, default=default)

    monkeypatch.setattr(json_file_cache, 'load_json_file', counting_load)
    return loads


def test_second_read_is_served_from_memory(tmp_path, monkeypatch):
    """An unchanged file is parsed once; later reads return the very same object."""
    path = tmp_path / 'dso_results.json'
    _write(path, {'deep_sky': [1, 2, 3]})
    loads = _count_loads(monkeypatch)

    first = json_file_cache.load_shared_json(str(path), default={})
    second = json_file_cache.load_shared_json(str(path), default={})

    assert first == {'deep_sky': [1, 2, 3]}
    assert second is first
    assert len(loads) == 1


def test_a_rewritten_file_is_parsed_again(tmp_path):
    """A new calculation replaces the file: the next read sees the new content."""
    path = tmp_path / 'dso_results.json'
    _write(path, {'run': 1})
    assert json_file_cache.load_shared_json(str(path))['run'] == 1
    _write(path, {'run': 2, 'longer': True})
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert json_file_cache.load_shared_json(str(path))['run'] == 2


def test_missing_file_returns_the_default_and_is_not_cached(tmp_path):
    """No file yet gives the caller's default; once it appears, it is read."""
    path = tmp_path / 'later.json'
    default = {'deep_sky': []}
    assert json_file_cache.load_shared_json(str(path), default=default) is default
    _write(path, {'deep_sky': ['m31']})
    assert json_file_cache.load_shared_json(str(path), default=default) == {'deep_sky': ['m31']}


def test_file_removed_while_waiting_for_the_load_returns_the_default(tmp_path, monkeypatch):
    """A file seen at first but gone once the load lock is held gives the default, uncached."""
    path = tmp_path / 'dso_results.json'
    _write(path, {'deep_sky': []})
    real_signature = json_file_cache._signature
    answers = [real_signature(str(path)), None]
    monkeypatch.setattr(json_file_cache, '_signature', lambda _path: answers.pop(0))
    loads = _count_loads(monkeypatch)

    default = {'missing': True}
    assert json_file_cache.load_shared_json(str(path), default=default) is default
    assert loads == []


def test_unreadable_file_returns_the_default_and_is_retried(tmp_path):
    """A corrupt file is not remembered as an empty result."""
    path = tmp_path / 'broken.json'
    path.write_text('{not json', encoding='utf-8')
    assert json_file_cache.load_shared_json(str(path), default={'empty': True}) == {'empty': True}
    _write(path, {'fixed': True})
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert json_file_cache.load_shared_json(str(path), default={}) == {'fixed': True}


def test_threads_arriving_together_share_one_parse(tmp_path, monkeypatch):
    """Several requests opening SkyTonight at once parse the file once, not once each.

    One parsed copy of a location's DSO results is about 40 MB; a copy per request in flight
    was enough to push a small host out of memory.
    """
    path = tmp_path / 'dso_results.json'
    _write(path, {'deep_sky': list(range(100))})
    loads = _count_loads(monkeypatch, delay=0.2)
    results = []
    start = threading.Barrier(6)

    def worker():
        start.wait()
        results.append(json_file_cache.load_shared_json(str(path), default={}))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(loads) == 1
    assert len(results) == 6
    assert all(result is results[0] for result in results)


def test_idle_files_are_dropped(tmp_path, monkeypatch):
    """A file nobody read for IDLE_SECONDS is forgotten, giving the memory back."""
    path = tmp_path / 'dso_results.json'
    _write(path, {'deep_sky': []})
    loads = _count_loads(monkeypatch)
    json_file_cache.load_shared_json(str(path))

    assert json_file_cache.drop_idle(now=time.monotonic() + 1) == 0
    assert json_file_cache.drop_idle(now=time.monotonic() + json_file_cache.IDLE_SECONDS + 1) == 1
    json_file_cache.load_shared_json(str(path))
    assert len(loads) == 2


def test_number_of_files_kept_is_bounded(tmp_path, monkeypatch):
    """Past MAX_FILES, the least recently read file is dropped."""
    monkeypatch.setattr(json_file_cache, 'MAX_FILES', 2)
    paths = []
    for index in range(3):
        path = tmp_path / f'file{index}.json'
        _write(path, {'index': index})
        paths.append(str(path))
        json_file_cache.load_shared_json(str(path))
        time.sleep(0.01)  # distinct last-used times
    loads = _count_loads(monkeypatch)
    json_file_cache.load_shared_json(paths[0])
    json_file_cache.load_shared_json(paths[2])
    assert loads == [paths[0]]
