"""Config creation / migration when several gunicorn workers start at once.

Seeding the config generates fresh location uuids that cache slots and user
prefs are keyed by, so a worker that loses the race must adopt the winner's ids
instead of persisting its own over them.
"""

from contextlib import contextmanager

import pytest

from db import settings_store
from tests.db_helpers import delete_setting
from utils import repo_config


@pytest.fixture(autouse=True)
def no_stored_config(monkeypatch):
    """Start from a brand-new install (no config) and skip user attribution."""
    delete_setting(repo_config.CONFIG_KEY)
    monkeypatch.setattr(repo_config, "_attribute_new_location_to_all_users", lambda _loc_id: None)


def _config_written_by_other_worker(location_id):
    other = repo_config.deepcopy(repo_config.DEFAULT_CONFIG)
    repo_config._ensure_locations(other, seeded_location_ids=[])
    other["locations"][0]["id"] = location_id
    settings_store.put_setting(repo_config.CONFIG_KEY, other)


def _transaction_entered_after(callback):
    """A transaction() stand-in running ``callback`` first: another worker wrote while this one waited."""
    real_transaction = repo_config.transaction

    @contextmanager
    def _transaction():
        callback()
        with real_transaction() as conn:
            yield conn

    return _transaction


def test_loser_of_first_boot_race_adopts_the_winners_location_id(monkeypatch):
    monkeypatch.setattr(
        repo_config, "transaction", _transaction_entered_after(lambda: _config_written_by_other_worker("winner-id"))
    )

    config = repo_config.load_config()

    assert [loc["id"] for loc in config["locations"]] == ["winner-id"]
    stored = settings_store.get_setting(repo_config.CONFIG_KEY)
    assert [loc["id"] for loc in stored["locations"]] == ["winner-id"]


def test_first_boot_seeds_persists_and_attributes_after_commit(monkeypatch):
    events = []
    real_transaction = repo_config.transaction

    @contextmanager
    def _recording_transaction():
        events.append("begin")
        with real_transaction() as conn:
            yield conn
        events.append("commit")

    monkeypatch.setattr(repo_config, "transaction", _recording_transaction)
    monkeypatch.setattr(repo_config, "_attribute_new_location_to_all_users", lambda loc_id: events.append(loc_id))

    config = repo_config.load_config()

    seeded_id = config["locations"][0]["id"]
    assert events == ["begin", "commit", seeded_id]
    assert settings_store.get_setting(repo_config.CONFIG_KEY)["locations"][0]["id"] == seeded_id


def test_valid_config_is_read_without_a_write_transaction(monkeypatch):
    repo_config.load_config()  # seed a valid config

    def _unexpected_transaction():
        raise AssertionError("the common read path must not open a write transaction")

    monkeypatch.setattr(repo_config, "transaction", _unexpected_transaction)
    assert repo_config.load_config()["locations"]


def test_legacy_migration_done_by_other_worker_is_not_redone(monkeypatch):
    legacy = repo_config.deepcopy(repo_config.DEFAULT_CONFIG)
    legacy.pop("locations", None)
    legacy["location"] = {"name": "Old site", "latitude": 45.0, "longitude": 5.0}
    settings_store.put_setting(repo_config.CONFIG_KEY, legacy)

    monkeypatch.setattr(
        repo_config,
        "transaction",
        _transaction_entered_after(lambda: _config_written_by_other_worker("migrated-by-other-worker")),
    )

    config = repo_config.load_config()

    assert [loc["id"] for loc in config["locations"]] == ["migrated-by-other-worker"]
