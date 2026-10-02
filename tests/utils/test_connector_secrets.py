"""Tests for utils/connector_secrets.py - the credentials store kept out of the config.

Every test runs on its own database (conftest.isolated_database), so these tests read and
write the store freely.
"""

import threading

from db import settings_store
from utils import connector_secrets as cs


def _stored():
    return settings_store.get_setting(cs.SECRETS_KEY)


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


def test_load_secrets_is_empty_when_nothing_stored():
    assert cs.load_secrets('mqtt') == {}
    assert _stored() is None


def test_save_then_load_round_trip():
    assert cs.save_secrets('mqtt', {'password': 'hunter2'}) is True
    assert cs.load_secrets('mqtt') == {'password': 'hunter2'}
    assert _stored() == {'mqtt': {'password': 'hunter2'}}


def test_save_merges_into_existing_values_and_leaves_other_connectors_alone():
    cs.save_secrets('myastroshine', {'token': 'tok', 'signing_secret': 'sig'})
    cs.save_secrets('mqtt', {'password': 'pw'})
    cs.save_secrets('myastroshine', {'token': 'tok2'})
    assert cs.load_secrets('myastroshine') == {'token': 'tok2', 'signing_secret': 'sig'}
    assert cs.load_secrets('mqtt') == {'password': 'pw'}


def test_blank_value_removes_the_key_and_empty_connector_is_dropped():
    cs.save_secrets('mqtt', {'password': 'pw'})
    cs.save_secrets('mqtt', {'password': ''})
    assert cs.load_secrets('mqtt') == {}
    assert _stored() == {}


def test_values_are_trimmed_and_stringified():
    cs.save_secrets('mqtt', {'password': '  pw  '})
    assert cs.load_secrets('mqtt') == {'password': 'pw'}


def test_malformed_stored_value_reads_as_empty():
    settings_store.put_setting(cs.SECRETS_KEY, ['not', 'a', 'dict'])
    assert cs.load_secrets('mqtt') == {}


def test_unreadable_store_reads_as_empty(monkeypatch):
    def _boom(_key):
        raise OSError('denied')

    monkeypatch.setattr(settings_store, 'get_setting', _boom)
    assert cs.load_secrets('mqtt') == {}


def test_non_string_or_empty_stored_values_are_ignored():
    settings_store.put_setting(cs.SECRETS_KEY, {'mqtt': {'password': 42, 'username': '', 'ok': 'yes'}, 'bad': 'nope'})
    assert cs.load_secrets('mqtt') == {'ok': 'yes'}
    assert cs.load_secrets('bad') == {}


def test_save_reports_failure_when_the_store_fails(monkeypatch):
    def _boom(_key, _mutate):
        raise OSError('disk full')

    monkeypatch.setattr(settings_store, 'modify_setting', _boom)
    assert cs.save_secrets('mqtt', {'password': 'pw'}) is False


def test_concurrent_saves_of_different_connectors_keep_both():
    """Every worker migrates legacy secrets at startup: read-merge-write must not lose a value."""
    threads = [
        threading.Thread(target=cs.save_secrets, args=(name, {'password': name})) for name in ('a', 'b', 'c', 'd')
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert set(_stored()) == {'a', 'b', 'c', 'd'}


def test_revision_moves_on_save():
    before = cs.secrets_revision()
    cs.save_secrets('mqtt', {'password': 'pw'})
    assert cs.secrets_revision() == before + 1


# ---------------------------------------------------------------------------
# merge_secrets
# ---------------------------------------------------------------------------


def test_merge_overlays_sidecar_values_on_the_config_block():
    cs.save_secrets('mqtt', {'password': 'from-sidecar'})
    merged = cs.merge_secrets('mqtt', {'url': 'mqtt://b', 'username': 'u'}, ('password',))
    assert merged == {'url': 'mqtt://b', 'username': 'u', 'password': 'from-sidecar'}


def test_merge_keeps_a_legacy_config_value_when_sidecar_has_none():
    merged = cs.merge_secrets('mqtt', {'password': 'legacy'}, ('password',))
    assert merged['password'] == 'legacy'


def test_merge_prefers_sidecar_over_legacy_config_value():
    cs.save_secrets('mqtt', {'password': 'sidecar'})
    merged = cs.merge_secrets('mqtt', {'password': 'legacy'}, ('password',))
    assert merged['password'] == 'sidecar'


def test_merge_does_not_mutate_the_input_and_handles_none():
    cfg = {'url': 'x'}
    cs.save_secrets('mqtt', {'password': 'pw'})
    merged = cs.merge_secrets('mqtt', cfg, ('password',))
    assert 'password' not in cfg
    assert merged['password'] == 'pw'
    assert cs.merge_secrets('mqtt', None, ('password',)) == {'password': 'pw'}


# ---------------------------------------------------------------------------
# migrate_legacy_secrets
# ---------------------------------------------------------------------------


def test_migration_moves_values_out_of_config_and_reports_change():
    config = {'connectors': {'myastroshine': {'url': 'http://x', 'token': 'tok', 'signing_secret': 'sig'}}}
    changed = cs.migrate_legacy_secrets('myastroshine', ('token', 'signing_secret'), config)
    assert changed is True
    assert config['connectors']['myastroshine'] == {'url': 'http://x'}
    assert cs.load_secrets('myastroshine') == {'token': 'tok', 'signing_secret': 'sig'}


def test_migration_is_a_no_op_without_legacy_values():
    config = {'connectors': {'mqtt': {'url': 'mqtt://b'}}}
    assert cs.migrate_legacy_secrets('mqtt', ('password',), config) is False
    assert config == {'connectors': {'mqtt': {'url': 'mqtt://b'}}}
    assert cs.migrate_legacy_secrets('mqtt', ('password',), {}) is False
    assert cs.migrate_legacy_secrets('mqtt', ('password',), {'connectors': 'oops'}) is False
    assert cs.migrate_legacy_secrets('mqtt', ('password',), {'connectors': {'mqtt': 'oops'}}) is False


def test_migration_strips_an_empty_legacy_key_without_touching_the_sidecar():
    config = {'connectors': {'mqtt': {'url': 'mqtt://b', 'password': ''}}}
    assert cs.migrate_legacy_secrets('mqtt', ('password',), config) is True
    assert 'password' not in config['connectors']['mqtt']
    assert cs.load_secrets('mqtt') == {}


def test_migration_keeps_an_existing_sidecar_value_over_the_legacy_one():
    cs.save_secrets('mqtt', {'password': 'sidecar'})
    config = {'connectors': {'mqtt': {'password': 'legacy'}}}
    assert cs.migrate_legacy_secrets('mqtt', ('password',), config) is True
    assert cs.load_secrets('mqtt') == {'password': 'sidecar'}
    assert 'password' not in config['connectors']['mqtt']


def test_migration_keeps_the_config_value_when_the_sidecar_cannot_be_written(monkeypatch):
    monkeypatch.setattr(cs, 'save_secrets', lambda name, values: False)
    config = {'connectors': {'mqtt': {'password': 'legacy'}}}
    assert cs.migrate_legacy_secrets('mqtt', ('password',), config) is False
    assert config['connectors']['mqtt']['password'] == 'legacy'


def test_migrate_all_runs_every_registered_connector_with_secret_fields():
    class _WithSecret:
        SECRET_FIELDS = ('password',)

    class _WithoutSecret:
        SECRET_FIELDS = ()

    config = {'connectors': {'a': {'password': 'pa'}, 'b': {'url': 'x'}}}
    changed = cs.migrate_all_legacy_secrets(config, {'a': _WithSecret, 'b': _WithoutSecret})
    assert changed is True
    assert config['connectors']['a'] == {}
    assert cs.load_secrets('a') == {'password': 'pa'}
    assert cs.migrate_all_legacy_secrets(config, {'a': _WithSecret, 'b': _WithoutSecret}) is False


def test_migrate_all_defaults_to_the_live_registry():
    config = {'connectors': {'myastroshine': {'token': 'tok'}}}
    assert cs.migrate_all_legacy_secrets(config) is True
    assert cs.load_secrets('myastroshine') == {'token': 'tok'}
