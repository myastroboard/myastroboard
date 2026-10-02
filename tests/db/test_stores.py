"""Generic stores: transactions, revisions, documents, settings and accounts."""

import threading

import pytest

from db import documents, engine, settings_store, users_store


def _user(user_id='u-1', username='alice'):
    return {
        'user_id': user_id,
        'username': username,
        'password_hash': 'hash',
        'role': 'user',
        'created_at': '2026-01-01T00:00:00+00:00',
    }


class TestTransactions:
    def test_rollback_on_error(self):
        """An exception inside a transaction leaves nothing behind."""
        with pytest.raises(RuntimeError):
            with engine.transaction():
                settings_store.put_setting('k', {'a': 1})
                raise RuntimeError('boom')
        assert settings_store.get_setting('k') is None

    def test_nested_transaction_joins_outer(self):
        """A nested transaction is part of the outer one and rolls back with it."""
        with pytest.raises(RuntimeError):
            with engine.transaction():
                with engine.transaction():
                    settings_store.put_setting('k', 1)
                raise RuntimeError('boom')
        assert settings_store.get_setting('k') is None

    def test_reads_inside_transaction_see_own_writes(self):
        """A read helper called inside a write transaction sees the uncommitted write."""
        with engine.transaction():
            settings_store.put_setting('k', 'v')
            assert settings_store.get_setting('k') == 'v'

    def test_revision_increments_per_write(self):
        """Each write bumps its store's revision."""
        assert settings_store.setting_revision('k') == 0
        settings_store.put_setting('k', 1)
        settings_store.put_setting('k', 2)
        assert settings_store.setting_revision('k') == 2

    def test_concurrent_read_modify_write_loses_nothing(self):
        """Parallel modify_setting() calls are serialized: every increment is kept."""
        settings_store.put_setting('counter', 0)

        def worker():
            for _ in range(20):
                settings_store.modify_setting('counter', lambda value: (value + 1, None))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert settings_store.get_setting('counter') == 80


class TestSettings:
    def test_round_trip_keeps_unicode_and_types(self):
        """Values come back exactly as stored."""
        value = {'name': 'Observatoire du Pic', 'n': 1.5, 'flags': [True, None], 'deg': '°'}
        settings_store.put_setting('config', value)
        assert settings_store.get_setting('config') == value

    def test_modify_keeps_value_when_mutator_returns_none(self):
        """A mutator returning None as the new value leaves the stored value alone."""
        settings_store.put_setting('k', 5)
        assert settings_store.modify_setting('k', lambda value: (None, value * 2)) == 10
        assert settings_store.get_setting('k') == 5


class TestDocuments:
    def test_document_requires_existing_user(self, enforce_foreign_keys):
        """The foreign key rejects a document for an unknown user."""
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            documents.put_document('nobody', 'astrodex', {'items': []})

    def test_put_get_list_delete(self):
        """Basic document lifecycle, with several doc keys of one kind."""
        users_store.upsert_users([_user()])
        documents.put_document('u-1', 'plan', {'plan': 1}, doc_key='default')
        documents.put_document('u-1', 'plan', {'plan': 2}, doc_key='combo-1')

        assert documents.get_document('u-1', 'plan', 'combo-1') == {'plan': 2}
        assert documents.list_user_documents('u-1', 'plan') == [('combo-1', {'plan': 2}), ('default', {'plan': 1})]
        assert [row[1] for row in documents.list_documents('plan')] == ['combo-1', 'default']

        assert documents.delete_document('u-1', 'plan', 'combo-1') is True
        assert documents.get_document('u-1', 'plan', 'combo-1') is None

    def test_plain_documents_and_missing_ones(self):
        """A kind with no collection tables is stored whole; deleting what is not there reports False."""
        users_store.upsert_users([_user()])
        documents.put_document('u-1', 'notes', {'text': 'clear skies'})
        documents.put_document('u-1', 'plan', {'plan': 1}, doc_key='combo-1')
        documents.put_document('u-1', 'plan', {'plan': 2}, doc_key='combo-2')

        assert documents.list_documents('plan', doc_key='combo-2') == [('u-1', 'combo-2', {'plan': 2})]
        assert documents.delete_document('u-1', 'notes', 'other-key') is False
        documents.delete_kind('notes')
        assert documents.get_document('u-1', 'notes') is None
        assert documents.delete_document('u-1', 'notes') is False

    def test_replace_keeps_created_at(self):
        """Replacing a document updates it but keeps its first created_at column."""
        users_store.upsert_users([_user()])
        documents.put_document('u-1', 'astrodex', {'created_at': '2026-01-01', 'items': []})
        documents.put_document('u-1', 'astrodex', {'created_at': '2027-01-01', 'items': [1]})
        assert documents.get_document('u-1', 'astrodex') == {'created_at': '2027-01-01', 'items': [1]}

    def test_deleting_user_cascades_to_documents(self, enforce_foreign_keys):
        """Removing an account removes every document it owns (right to erasure)."""
        users_store.upsert_users([_user(), _user('u-2', 'bob')])
        documents.put_document('u-1', 'astrodex', {'items': []})
        documents.put_document('u-2', 'astrodex', {'items': []})

        assert users_store.delete_user('u-1') is True

        assert documents.get_document('u-1', 'astrodex') is None
        assert documents.get_document('u-2', 'astrodex') == {'items': []}

    def test_numpy_values_are_serialized(self):
        """numpy scalars and arrays reaching a document are stored as plain JSON numbers/lists."""
        np = pytest.importorskip('numpy')
        users_store.upsert_users([_user()])
        documents.put_document('u-1', 'plan', {'alt': np.float64(12.5), 'curve': np.array([1, 2])})
        assert documents.get_document('u-1', 'plan') == {'alt': 12.5, 'curve': [1, 2]}


class TestUsersStore:
    def test_upsert_and_lookup(self):
        """Accounts are inserted then updated in place."""
        users_store.upsert_users([_user()])
        users_store.upsert_users([dict(_user(), role='admin')])
        assert users_store.get_user('u-1')['role'] == 'admin'
        assert 'u-1' in users_store.get_all_users()

    def test_username_is_unique(self):
        """Two accounts cannot share a username."""
        from sqlalchemy.exc import IntegrityError

        users_store.upsert_users([_user()])
        with pytest.raises(IntegrityError):
            users_store.upsert_users([_user('u-2', 'alice')])

    def test_upsert_nothing_is_a_no_op(self):
        """An empty batch does not bump the revision."""
        before = users_store.users_revision()
        users_store.upsert_users([])
        assert users_store.users_revision() == before

    def test_deleting_an_unknown_account(self):
        """Deleting an account that does not exist changes nothing and reports False."""
        before = users_store.users_revision()
        assert users_store.delete_user('nobody') is False
        assert users_store.users_revision() == before
