"""Tests for utils/mqtt_connections.py - the broker profiles shared by the MQTT connectors.

Every test runs on its own database (conftest.isolated_database), so the secrets store is
read and written freely. Configs are plain dicts: the module never loads or saves one itself.
"""

from utils import mqtt_connections as mc
from utils.connector_secrets import load_secrets, save_secrets


def _config(connections=None, mqtt_block=None):
    config = {'connectors': {}, 'mqtt_connections': list(connections or [])}
    if mqtt_block is not None:
        config['connectors']['mqtt'] = mqtt_block
    return config


def _conn(cid='c1', name='Home', url='mqtt://broker.lan:1883', username='', tls_insecure=False):
    return {'id': cid, 'name': name, 'url': url, 'username': username, 'tls_insecure': tls_insecure}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class TestReading:
    def test_list_connections_cleans_entries_and_drops_unusable_ones(self):
        """Entries without an id or that are not dicts are ignored; the rest get every field."""
        config = {'mqtt_connections': [{'id': 'a', 'url': 'mqtt://b/'}, {'name': 'no id'}, 'junk']}
        assert mc.list_connections(config) == [
            {'id': 'a', 'name': 'a', 'url': 'mqtt://b', 'username': '', 'tls_insecure': False}
        ]

    def test_list_connections_without_the_key_is_empty(self):
        """A config that never had connections lists none."""
        assert mc.list_connections({}) == []
        assert mc.list_connections({'mqtt_connections': 'oops'}) == []

    def test_get_connection_by_id(self):
        """A connection is found by its id; a blank or unknown id finds nothing."""
        config = _config([_conn('c1'), _conn('c2', name='Other')])
        assert mc.get_connection(config, 'c2')['name'] == 'Other'
        assert mc.get_connection(config, '') is None
        assert mc.get_connection(config, 'nope') is None

    def test_connection_password_reads_the_secrets_store(self):
        """The password lives in the connector secrets store under the connection id."""
        save_secrets('mqtt_connection:c1', {'password': 'pw'})
        assert mc.connection_password('c1') == 'pw'
        assert mc.connection_password('c2') == ''
        assert mc.connection_password(None) == ''

    def test_legacy_connection_falls_back_to_the_old_connector_password(self):
        """The migrated Home Assistant connection still finds the pre-migration password."""
        save_secrets('mqtt', {'password': 'old-pw'})
        assert mc.connection_password(mc.LEGACY_CONNECTION_ID) == 'old-pw'
        assert mc.connection_password('c1') == ''  # no fallback for any other connection

        save_secrets(f'mqtt_connection:{mc.LEGACY_CONNECTION_ID}', {'password': 'new-pw'})
        assert mc.connection_password(mc.LEGACY_CONNECTION_ID) == 'new-pw'

    def test_used_by_lists_connectors_pointing_at_the_connection(self):
        """A connector counts as a user whether it is enabled or not."""
        config = _config([_conn('c1')], mqtt_block={'mqtt_connection_id': 'c1', 'enabled': False})
        assert mc.used_by(config, 'c1') == ['mqtt']
        assert mc.used_by(config, 'c2') == []
        assert mc.used_by({}, 'c1') == []

    def test_public_connection_masks_the_password(self):
        """The browser sees a fixed mask (no tail, no length), a has_password flag and the users."""
        save_secrets('mqtt_connection:c1', {'password': 'hunter22'})
        config = _config([_conn('c1', username='u')], mqtt_block={'mqtt_connection_id': 'c1'})
        public = mc.public_connection(config, mc.get_connection(config, 'c1'))
        assert public['password'] == mc.PASSWORD_MASK == '********'
        assert 'er22' not in str(public)
        assert public['has_password'] is True
        assert public['used_by'] == ['mqtt']
        assert 'hunter22' not in str(public)

    def test_connection_for_returns_the_picked_connection_without_its_password(self):
        """The connector gets its connection apart from its block; the password never comes with it."""

        class _Picks:
            CONNECTION_FIELD = 'mqtt_connection_id'

        save_secrets('mqtt_connection:c1', {'password': 'pw'})
        config = _config([_conn('c1', url='mqtts://b', username='u', tls_insecure=True)])
        block = {'mqtt_connection_id': 'c1', 'url': 'http://allsky.lan'}
        assert mc.connection_for(_Picks, block, config) == _conn('c1', url='mqtts://b', username='u', tls_insecure=True)
        assert block == {'mqtt_connection_id': 'c1', 'url': 'http://allsky.lan'}  # the block is left alone

    def test_connection_for_without_a_usable_connection(self):
        """No connection field, no pick, or an unknown id all give None."""

        class _Picks:
            CONNECTION_FIELD = 'mqtt_connection_id'

        class _NoConnection:
            CONNECTION_FIELD = ''

        config = _config([_conn('c1')])
        assert mc.connection_for(_Picks, {'mqtt_connection_id': 'gone'}, config) is None
        assert mc.connection_for(_Picks, None, config) is None
        assert mc.connection_for(_NoConnection, {'mqtt_connection_id': 'c1'}, config) is None


class TestClientIdConflict:
    def test_same_explicit_client_id_on_the_same_connection_conflicts(self):
        """Another connector on the same connection with the same client id is reported."""
        config = _config([_conn('c1')], mqtt_block={'mqtt_connection_id': 'c1', 'client_id': 'board'})
        assert mc.client_id_conflict(config, 'other', 'c1', 'board') == 'mqtt'

    def test_no_conflict_cases(self):
        """A blank id, another connection, another client id or the connector itself never conflict."""
        config = _config([_conn('c1')], mqtt_block={'mqtt_connection_id': 'c1', 'client_id': 'board'})
        assert mc.client_id_conflict(config, 'other', 'c1', '') is None
        assert mc.client_id_conflict(config, 'other', 'c2', 'board') is None
        assert mc.client_id_conflict(config, 'other', 'c1', 'board-2') is None
        assert mc.client_id_conflict(config, 'mqtt', 'c1', 'board') is None
        assert mc.client_id_conflict(config, 'other', '', 'board') is None
        assert mc.client_id_conflict({}, 'other', 'c1', 'board') is None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_adds_the_connection_and_stores_the_password_apart(self):
        """The connection lands in the config with a fresh id; the password in the secrets store."""
        config = _config()
        connection, error = mc.create_connection(
            config, {'name': ' Home ', 'url': 'mqtt://b:1883/', 'username': 'u', 'password': 'pw'}
        )
        assert error is None
        assert connection['name'] == 'Home' and connection['url'] == 'mqtt://b:1883'
        assert config['mqtt_connections'] == [connection]
        assert 'password' not in connection
        assert mc.connection_password(connection['id']) == 'pw'

    def test_create_without_username_stores_no_password(self):
        """A password without a username is useless to the broker and is not kept."""
        config = _config()
        connection, _ = mc.create_connection(config, {'name': 'A', 'url': 'mqtt://b', 'password': 'pw'})
        assert mc.connection_password(connection['id']) == ''

    def test_create_validates_name_url_and_username(self):
        """Every invalid field is refused with a reason, and nothing is added."""
        config = _config([_conn('c1', name='Home')])
        cases = [
            ({'url': 'mqtt://b'}, 'name required'),
            ({'name': 'x' * 65, 'url': 'mqtt://b'}, 'name must be at most 64 characters'),
            ({'name': 'home', 'url': 'mqtt://b'}, 'a connection with this name already exists'),
            ({'name': 'A'}, 'url required'),
            ({'name': 'A', 'url': 'http://b'}, 'url must start with mqtt:// or mqtts://'),
            ({'name': 'A', 'url': 'mqtt://b', 'username': 'u' * 257}, 'username must be at most 256 characters'),
        ]
        for data, expected in cases:
            assert mc.create_connection(config, data) == (None, expected)
        assert len(config['mqtt_connections']) == 1

    def test_create_reports_a_password_store_failure(self, monkeypatch):
        """A password that cannot be stored aborts the creation."""
        monkeypatch.setattr(mc, 'save_secrets', lambda name, values: False)
        config = _config()
        data = {'name': 'A', 'url': 'mqtt://b', 'username': 'u', 'password': 'pw'}
        assert mc.create_connection(config, data) == (None, 'could not store the password')
        assert config['mqtt_connections'] == []


class TestUpdate:
    def test_update_changes_only_the_submitted_fields(self):
        """Fields absent from the payload keep their value."""
        config = _config([_conn('c1', username='u', tls_insecure=True)])
        connection, error = mc.update_connection(config, 'c1', {'url': 'mqtts://new'})
        assert error is None
        assert connection == _conn('c1', url='mqtts://new', username='u', tls_insecure=True)
        assert config['mqtt_connections'] == [connection]

    def test_blank_or_masked_password_keeps_the_stored_one(self):
        """The masked value handed out by the list never overwrites the real password."""
        save_secrets('mqtt_connection:c1', {'password': 'keep'})
        config = _config([_conn('c1', username='u')])
        for echoed in ('', mc.PASSWORD_MASK):
            mc.update_connection(config, 'c1', {'password': echoed})
            assert mc.connection_password('c1') == 'keep'
        mc.update_connection(config, 'c1', {'password': 'new'})
        assert mc.connection_password('c1') == 'new'

    def test_clearing_the_username_drops_the_password(self):
        """An anonymous connection keeps no password."""
        save_secrets('mqtt_connection:c1', {'password': 'pw'})
        config = _config([_conn('c1', username='u')])
        mc.update_connection(config, 'c1', {'username': ''})
        assert mc.connection_password('c1') == ''

    def test_update_may_keep_its_own_name(self):
        """Renaming check ignores the connection being edited."""
        config = _config([_conn('c1', name='Home'), _conn('c2', name='Other')])
        assert mc.update_connection(config, 'c1', {'name': 'HOME'})[1] is None
        assert mc.update_connection(config, 'c1', {'name': 'other'})[1] == 'a connection with this name already exists'

    def test_update_unknown_or_invalid(self, monkeypatch):
        """An unknown id, an invalid field and a password store failure are all refused."""
        config = _config([_conn('c1', username='u')])
        assert mc.update_connection(config, 'nope', {}) == (None, 'not found')
        assert mc.update_connection(config, 'c1', {'url': 'ftp://x'})[1] == 'url must start with mqtt:// or mqtts://'
        monkeypatch.setattr(mc, 'save_secrets', lambda name, values: False)
        assert mc.update_connection(config, 'c1', {'password': 'pw'}) == (None, 'could not store the password')


class TestDelete:
    def test_delete_removes_the_connection_and_its_password(self):
        """An unused connection goes, with its stored password."""
        save_secrets('mqtt_connection:c1', {'password': 'pw'})
        config = _config([_conn('c1'), _conn('c2', name='Other')])
        assert mc.delete_connection(config, 'c1') == ([], None)
        assert [c['id'] for c in config['mqtt_connections']] == ['c2']
        assert load_secrets('mqtt_connection:c1') == {}

    def test_delete_refused_while_a_connector_uses_it(self):
        """A connection in use is kept, and the connectors using it are named."""
        config = _config([_conn('c1')], mqtt_block={'mqtt_connection_id': 'c1'})
        assert mc.delete_connection(config, 'c1') == (['mqtt'], 'connection in use')
        assert len(config['mqtt_connections']) == 1

    def test_delete_unknown(self):
        """Deleting an id that does not exist reports it."""
        assert mc.delete_connection(_config(), 'nope') == ([], 'not found')


# ---------------------------------------------------------------------------
# Home Assistant connector blocks from 1.7.1 or earlier
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    def _legacy(self, **overrides):
        block = {
            'enabled': True,
            'url': 'mqtt://ha.lan:1883',
            'username': 'ha',
            'tls_insecure': True,
            'base_topic': 'myastroboard',
            'client_id': 'board',
        }
        block.update(overrides)
        return {'connectors': {'mqtt': block}}

    def test_legacy_block_becomes_the_home_assistant_connection(self):
        """The broker fields leave the block for a fixed-id connection the block then picks."""
        config = self._legacy()
        mc.normalize_legacy_mqtt(config)
        assert config['mqtt_connections'] == [
            {
                'id': mc.LEGACY_CONNECTION_ID,
                'name': mc.LEGACY_CONNECTION_NAME,
                'url': 'mqtt://ha.lan:1883',
                'username': 'ha',
                'tls_insecure': True,
            }
        ]
        assert config['connectors']['mqtt'] == {
            'enabled': True,
            'base_topic': 'myastroboard',
            'client_id': 'board',
            'mqtt_connection_id': mc.LEGACY_CONNECTION_ID,
        }

    def test_normalize_is_idempotent_and_does_not_touch_the_input_objects(self):
        """A second pass changes nothing; the stored payload's dict and list are not mutated."""
        raw_block = self._legacy()['connectors']['mqtt']
        raw_list = []
        config = {'connectors': {'mqtt': raw_block}, 'mqtt_connections': raw_list}
        mc.normalize_legacy_mqtt(config)
        snapshot = repr(config)
        mc.normalize_legacy_mqtt(config)
        assert repr(config) == snapshot
        assert raw_block['url'] == 'mqtt://ha.lan:1883' and raw_list == []

    def test_existing_legacy_connection_is_reused(self):
        """Two reads of an old backup never produce two connections."""
        config = self._legacy()
        config['mqtt_connections'] = [_conn(mc.LEGACY_CONNECTION_ID, name='Kept')]
        mc.normalize_legacy_mqtt(config)
        assert [c['name'] for c in config['mqtt_connections']] == ['Kept']
        assert config['connectors']['mqtt']['mqtt_connection_id'] == mc.LEGACY_CONNECTION_ID

    def test_block_without_url_only_loses_its_broker_keys(self):
        """An unconfigured legacy block gets no connection."""
        config = self._legacy(url='')
        mc.normalize_legacy_mqtt(config)
        assert 'mqtt_connections' not in config
        assert 'mqtt_connection_id' not in config['connectors']['mqtt']
        assert 'url' not in config['connectors']['mqtt']

    def test_new_shape_and_missing_blocks_are_left_alone(self):
        """A config already on connections, or without an MQTT block, is not changed."""
        config = _config([_conn('c1')], mqtt_block={'mqtt_connection_id': 'c1'})
        snapshot = repr(config)
        mc.normalize_legacy_mqtt(config)
        assert repr(config) == snapshot
        mc.normalize_legacy_mqtt({})
        mc.normalize_legacy_mqtt({'connectors': {'mqtt': 'junk'}})

    def test_legacy_pending_detects_broker_keys_in_the_stored_block(self):
        """Only a stored block still holding a broker key (or a password) needs persisting."""
        assert mc.legacy_mqtt_pending(self._legacy()) is True
        assert mc.legacy_mqtt_pending({'connectors': {'mqtt': {'password': 'x'}}}) is True
        assert mc.legacy_mqtt_pending({'connectors': {'mqtt': {'mqtt_connection_id': 'c1'}}}) is False
        assert mc.legacy_mqtt_pending({}) is False
        assert mc.legacy_mqtt_pending(None) is False

    def test_migrate_moves_the_connector_password_to_the_connection(self):
        """The password the connector held in the secrets store follows its broker."""
        save_secrets('mqtt', {'password': 'pw'})
        config = self._legacy()
        mc.normalize_legacy_mqtt(config)
        assert mc.migrate_legacy_mqtt(config) is False  # the config itself did not change
        assert load_secrets(f'mqtt_connection:{mc.LEGACY_CONNECTION_ID}') == {'password': 'pw'}
        assert load_secrets('mqtt') == {}
        assert mc.connection_password(mc.LEGACY_CONNECTION_ID) == 'pw'

    def test_migrate_moves_a_password_still_in_the_config_block(self):
        """A password left in the block by an older version is moved and stripped."""
        config = self._legacy(password='in-config')
        mc.normalize_legacy_mqtt(config)
        assert mc.migrate_legacy_mqtt(config) is True
        assert 'password' not in config['connectors']['mqtt']
        assert mc.connection_password(mc.LEGACY_CONNECTION_ID) == 'in-config'

    def test_migrate_never_overwrites_a_connection_password(self):
        """A connection that already has a password keeps it."""
        save_secrets(f'mqtt_connection:{mc.LEGACY_CONNECTION_ID}', {'password': 'current'})
        save_secrets('mqtt', {'password': 'old'})
        config = self._legacy()
        mc.normalize_legacy_mqtt(config)
        mc.migrate_legacy_mqtt(config)
        assert mc.connection_password(mc.LEGACY_CONNECTION_ID) == 'current'

    def test_migrate_keeps_the_password_when_it_cannot_be_stored(self, monkeypatch):
        """A store failure leaves the password where it was."""
        config = self._legacy(password='in-config')
        mc.normalize_legacy_mqtt(config)
        monkeypatch.setattr(mc, 'save_secrets', lambda name, values: False)
        assert mc.migrate_legacy_mqtt(config) is False
        assert config['connectors']['mqtt']['password'] == 'in-config'

    def test_migrate_without_an_mqtt_block_does_nothing(self):
        """No connector block, nothing to migrate."""
        assert mc.migrate_legacy_mqtt({}) is False
        assert mc.migrate_legacy_mqtt({'connectors': {}}) is False

    def test_load_config_reads_a_legacy_block_as_a_connection(self):
        """repo_config.load_config() hands every caller the connection shape."""
        from utils import repo_config

        config = repo_config.load_config()
        config['connectors']['mqtt'] = self._legacy()['connectors']['mqtt']
        config.pop('mqtt_connections', None)
        assert repo_config.save_config(config)

        loaded = repo_config.load_config()
        assert loaded['connectors']['mqtt']['mqtt_connection_id'] == mc.LEGACY_CONNECTION_ID
        assert mc.get_connection(loaded, mc.LEGACY_CONNECTION_ID)['url'] == 'mqtt://ha.lan:1883'
        assert 'url' not in loaded['connectors']['mqtt']
