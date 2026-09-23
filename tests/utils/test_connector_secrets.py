"""Tests for utils/connector_secrets.py - the credentials sidecar kept out of config.json.

The autouse ``isolate_connector_secrets`` fixture in conftest.py already points the sidecar
at a per-test file, so these tests read and write it freely.
"""

import json
import os

from utils import connector_secrets as cs


def _sidecar_path():
    return cs._SECRETS_FILE


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


def test_load_secrets_is_empty_when_no_file():
    assert cs.load_secrets('mqtt') == {}
    assert not os.path.exists(_sidecar_path())


def test_save_then_load_round_trip():
    assert cs.save_secrets('mqtt', {'password': 'hunter2'}) is True
    assert cs.load_secrets('mqtt') == {'password': 'hunter2'}
    on_disk = json.load(open(_sidecar_path(), encoding='utf-8'))
    assert on_disk == {'mqtt': {'password': 'hunter2'}}


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
    assert json.load(open(_sidecar_path(), encoding='utf-8')) == {}


def test_values_are_trimmed_and_stringified():
    cs.save_secrets('mqtt', {'password': '  pw  '})
    assert cs.load_secrets('mqtt') == {'password': 'pw'}


def test_write_leaves_no_tmp_file_behind():
    cs.save_secrets('mqtt', {'password': 'pw'})
    folder, base = os.path.split(_sidecar_path())
    assert not [name for name in os.listdir(folder) if name.startswith(base) and name.endswith('.tmp')]


def test_unreadable_or_malformed_file_reads_as_empty():
    with open(_sidecar_path(), 'w', encoding='utf-8') as handle:
        handle.write('{not json')
    assert cs.load_secrets('mqtt') == {}

    with open(_sidecar_path(), 'w', encoding='utf-8') as handle:
        json.dump(['not', 'a', 'dict'], handle)
    assert cs.load_secrets('mqtt') == {}


def test_non_string_or_empty_values_on_disk_are_ignored():
    with open(_sidecar_path(), 'w', encoding='utf-8') as handle:
        json.dump({'mqtt': {'password': 42, 'username': '', 'ok': 'yes'}, 'bad': 'nope'}, handle)
    assert cs.load_secrets('mqtt') == {'ok': 'yes'}
    assert cs.load_secrets('bad') == {}


def test_save_reports_failure_when_directory_is_unwritable(monkeypatch):
    """Note: this actually fails inside save_secrets's own interprocess_lock() acquisition
    (it also calls os.makedirs, for the lock file's directory, before _write_all ever
    runs) - not inside _write_all's own try/except. See
    test_write_failure_before_tmp_file_exists_skips_cleanup below for that path."""
    monkeypatch.setattr(cs, '_SECRETS_FILE', os.path.join(_sidecar_path(), 'nested', 'x.json'))
    # The parent "directory" is a plain file path that does not exist and cannot be created
    # under a file - makedirs raises and the save must report False rather than raise.
    with open(os.path.dirname(os.path.dirname(cs._SECRETS_FILE)), 'w', encoding='utf-8') as handle:
        handle.write('{}')
    assert cs.save_secrets('mqtt', {'password': 'pw'}) is False


def test_write_failure_before_tmp_file_exists_skips_cleanup(monkeypatch):
    """When the failure happens before the tmp file is even created (unlike
    test_write_failure_reports_false_and_cleans_up_tmp_file, where os.replace fails after
    a real tmp file was written), there is nothing to clean up - os.path.exists(tmp_path)
    must be False and the removal must simply be skipped."""
    import builtins

    original_open = builtins.open

    def raising_open(path, mode='r', **kwargs):
        if 'w' in mode and str(path).endswith('.tmp'):
            raise OSError("disk full")
        return original_open(path, mode, **kwargs)

    monkeypatch.setattr(builtins, 'open', raising_open)

    assert cs.save_secrets('mqtt', {'password': 'pw'}) is False


def test_chmod_failure_does_not_prevent_saving(monkeypatch):
    """Windows / exotic filesystems may not honour chmod - best effort only, the write
    itself (and the fact the file lives outside backups) is what actually matters."""
    monkeypatch.setattr(cs.os, 'chmod', lambda *a, **k: (_ for _ in ()).throw(OSError("chmod not supported")))
    assert cs.save_secrets('mqtt', {'password': 'pw'}) is True
    assert cs.load_secrets('mqtt') == {'password': 'pw'}


def test_write_failure_reports_false_and_cleans_up_tmp_file(monkeypatch):
    monkeypatch.setattr(cs.os, 'replace', lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert cs.save_secrets('mqtt', {'password': 'pw'}) is False
    folder, base = os.path.split(_sidecar_path())
    assert not [name for name in os.listdir(folder) if name.startswith(base) and name.endswith('.tmp')]


def test_write_failure_cleanup_remove_error_is_also_swallowed(monkeypatch):
    """If the replace fails and the cleanup's own os.remove then also fails, save_secrets
    must still report failure cleanly rather than raise."""
    monkeypatch.setattr(cs.os, 'replace', lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(cs.os, 'remove', lambda *a, **k: (_ for _ in ()).throw(OSError("remove failed")))
    assert cs.save_secrets('mqtt', {'password': 'pw'}) is False


def test_save_merges_under_cross_process_lock(monkeypatch):
    """Every worker migrates legacy secrets at startup, so read-merge-write must be serialized across processes."""
    from contextlib import contextmanager

    events = []

    @contextmanager
    def _recording_lock(lock_path):
        events.append(('acquire', lock_path))
        yield
        events.append(('release', lock_path))

    real_write_all = cs._write_all
    monkeypatch.setattr(cs, 'interprocess_lock', _recording_lock)
    monkeypatch.setattr(cs, '_write_all', lambda data: events.append(('write', None)) or real_write_all(data))

    assert cs.save_secrets('mqtt', {'password': 'pw'}) is True
    lock_path = cs._SECRETS_FILE + '.lock'
    assert events == [('acquire', lock_path), ('write', None), ('release', lock_path)]


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
