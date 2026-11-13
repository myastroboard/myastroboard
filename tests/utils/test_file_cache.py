"""Tests for utils/file_cache.py - the size cap of on-disk caches of re-downloadable files."""

import os

from utils import file_cache


def _fill(directory, count, size=100):
    for index in range(count):
        path = directory / f'{index}.jpg'
        path.write_bytes(b'x' * size)
        os.utime(path, (1000 + index, 1000 + index))


def test_prune_removes_oldest_files_down_to_eighty_percent(tmp_path):
    """Once over the limit, the oldest files go until the cache is back under 80% of it."""
    _fill(tmp_path, 5)

    assert file_cache.prune_oldest_files(str(tmp_path), 450, 'Test cache') == 2
    assert sorted(os.listdir(str(tmp_path))) == ['2.jpg', '3.jpg', '4.jpg']


def test_prune_keeps_everything_under_the_limit(tmp_path):
    """A cache under its limit is left untouched."""
    _fill(tmp_path, 1)

    assert file_cache.prune_oldest_files(str(tmp_path), 1000, 'Test cache') == 0
    assert os.listdir(str(tmp_path)) == ['0.jpg']


def test_prune_skips_files_it_cannot_stat(monkeypatch, tmp_path):
    """A file that vanishes between the listing and the stat is left out of the size count."""
    gone = tmp_path / 'gone.jpg'
    gone.write_bytes(b'x' * 5000)
    real_stat = os.stat
    monkeypatch.setattr(
        file_cache.os,
        'stat',
        lambda path: (_ for _ in ()).throw(FileNotFoundError(path)) if path == str(gone) else real_stat(path),
    )

    assert file_cache.prune_oldest_files(str(tmp_path), 1000, 'Test cache') == 0
    assert gone.exists()


def test_prune_keeps_files_it_cannot_remove(monkeypatch, tmp_path):
    """A file the OS refuses to delete stays, the next ones go, and pruning ends without raising."""
    locked = tmp_path / 'locked.jpg'
    other = tmp_path / 'other.jpg'
    for index, path in enumerate((locked, other)):
        path.write_bytes(b'x' * 600)
        os.utime(path, (1000 + index, 1000 + index))
    real_remove = os.remove
    monkeypatch.setattr(
        file_cache.os,
        'remove',
        lambda path: (_ for _ in ()).throw(PermissionError(path)) if path == str(locked) else real_remove(path),
    )

    assert file_cache.prune_oldest_files(str(tmp_path), 1000, 'Test cache') == 1
    assert locked.exists()
    assert not other.exists()


def test_prune_without_directory_is_a_no_op(tmp_path):
    """A cache directory that does not exist yet is not an error."""
    assert file_cache.prune_oldest_files(str(tmp_path / 'missing'), 1000, 'Test cache') == 0


def test_write_pruner_runs_once_every_few_writes():
    """The prune callback runs on every Nth write only."""
    calls = []
    pruner = file_cache.WritePruner(lambda: calls.append(1), 3)
    for _ in range(7):
        pruner.note_write()
    assert calls == [1, 1]
