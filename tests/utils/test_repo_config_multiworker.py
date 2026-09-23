"""config.json creation / migration when several gunicorn workers start at once.

Seeding the config generates fresh location uuids that cache slots and user
prefs are keyed by, so a worker that loses the race must adopt the winner's ids
instead of persisting its own over them.
"""

import json
from contextlib import contextmanager

import pytest

from utils import repo_config


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(repo_config, "CONFIG_FILE", str(path))
    monkeypatch.setattr(repo_config, "_attribute_new_location_to_all_users", lambda _loc_id: None)
    return path


def _config_written_by_other_worker(path, location_id):
    other = repo_config.deepcopy(repo_config.DEFAULT_CONFIG)
    repo_config._ensure_locations(other, seeded_location_ids=[])
    other["locations"][0]["id"] = location_id
    path.write_text(json.dumps(other), encoding="utf-8")


def test_loser_of_first_boot_race_adopts_the_winners_location_id(config_path, monkeypatch):
    @contextmanager
    def _lock_won_by_other_worker_first(_lock_path):
        # While this worker waited for the lock, the other one created config.json
        _config_written_by_other_worker(config_path, "winner-location-id")
        yield

    monkeypatch.setattr(repo_config, "interprocess_lock", _lock_won_by_other_worker_first)

    config = repo_config.load_config()

    assert [loc["id"] for loc in config["locations"]] == ["winner-location-id"]
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert [loc["id"] for loc in on_disk["locations"]] == ["winner-location-id"]


def test_first_boot_seeds_persists_and_attributes_after_releasing_lock(config_path, monkeypatch):
    events = []

    @contextmanager
    def _recording_lock(lock_path):
        events.append(("acquire", lock_path))
        yield
        events.append(("release", lock_path))

    monkeypatch.setattr(repo_config, "interprocess_lock", _recording_lock)
    monkeypatch.setattr(repo_config, "_attribute_new_location_to_all_users", lambda loc_id: events.append(("attr", loc_id)))

    config = repo_config.load_config()

    seeded_id = config["locations"][0]["id"]
    lock_path = str(config_path) + ".lock"
    assert events == [("acquire", lock_path), ("release", lock_path), ("attr", seeded_id)]
    assert json.loads(config_path.read_text(encoding="utf-8"))["locations"][0]["id"] == seeded_id


def test_valid_config_is_read_without_taking_the_lock(config_path, monkeypatch):
    repo_config.load_config()  # seed a valid file

    def _unexpected_lock(_lock_path):
        raise AssertionError("the common read path must not lock")

    monkeypatch.setattr(repo_config, "interprocess_lock", _unexpected_lock)
    assert repo_config.load_config()["locations"]


def test_legacy_migration_done_by_other_worker_is_not_redone(config_path, monkeypatch):
    legacy = repo_config.deepcopy(repo_config.DEFAULT_CONFIG)
    legacy.pop("locations", None)
    legacy["location"] = {"name": "Old site", "latitude": 45.0, "longitude": 5.0}
    config_path.write_text(json.dumps(legacy), encoding="utf-8")

    @contextmanager
    def _other_worker_migrated_first(_lock_path):
        _config_written_by_other_worker(config_path, "migrated-by-other-worker")
        yield

    monkeypatch.setattr(repo_config, "interprocess_lock", _other_worker_migrated_first)

    config = repo_config.load_config()

    assert [loc["id"] for loc in config["locations"]] == ["migrated-by-other-worker"]
