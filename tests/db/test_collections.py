"""Per-user documents stored relationally: one row per object, assembled back losslessly."""

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db import collections, documents, engine, schema, users_store

UID = 'u-1'


@pytest.fixture(autouse=True)
def owner():
    users_store.upsert_users(
        [{'user_id': UID, 'username': 'alice', 'password_hash': 'x', 'role': 'user', 'created_at': 'now'}]
    )


def _count(table, **where):
    with engine.read() as conn:
        query = select(func.count()).select_from(table)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        return conn.execute(query).scalar_one()


def _round_trip(kind, document, doc_key=''):
    documents.put_document(UID, kind, document, doc_key)
    stored = documents.get_document(UID, kind, doc_key)
    assert json.dumps(stored, sort_keys=True) == json.dumps(document, sort_keys=True)
    return stored


ASTRODEX = {
    'user_id': UID,
    'username': 'alice',
    'created_at': '2026-01-01',
    'items': [
        {
            'id': 'i1',
            'name': 'M 31',
            'catalogue': 'Messier',
            'mag': 3.4,
            'pictures': [
                {'id': 'p1', 'filename': 'a.jpg', 'latitude': 45, 'longitude': 5.5, 'is_main': True},
                {'id': 'p2', 'filename': 'b.jpg', 'latitude': 'unknown', 'future_field': {'x': [1, 2]}},
            ],
        },
        {'id': 'i2', 'name': 'M 42', 'pictures': []},
        {'id': 'i3', 'name': 'M 45'},  # no pictures key at all
    ],
}


def test_astrodex_is_split_into_rows_and_assembled_back():
    _round_trip('astrodex', ASTRODEX)

    assert _count(schema.astrodex_items, user_id=UID) == 3
    assert _count(schema.astrodex_pictures, user_id=UID) == 2
    with engine.read() as conn:
        picture = conn.execute(select(schema.astrodex_pictures).where(schema.astrodex_pictures.c.id == 'p1')).one()
        mismatched = conn.execute(select(schema.astrodex_pictures).where(schema.astrodex_pictures.c.id == 'p2')).one()
    # Query columns are filled when the value has the column's type...
    assert (picture.filename, picture.latitude, picture.is_main) == ('a.jpg', 45.0, True)
    # ...and left empty otherwise; the object itself keeps the original value
    assert mismatched.latitude is None


def test_order_empty_lists_and_missing_keys_survive():
    stored = _round_trip('astrodex', ASTRODEX)
    assert [item['id'] for item in stored['items']] == ['i1', 'i2', 'i3']
    assert stored['items'][1]['pictures'] == []
    assert 'pictures' not in stored['items'][2]


def test_non_object_elements_and_non_list_values_are_kept_as_is():
    _round_trip(
        'observation_sessions',
        {'username': 'alice', 'sessions': ['junk', 7, {'id': 's1', 'nights': 'not-a-list', 'entries': [None]}]},
    )
    _round_trip('wishlist', {'username': 'alice', 'items': 'not-a-list'})


def test_sessions_nights_entries_attachments():
    document = {
        'username': 'alice',
        'sessions': [
            {
                'id': 's1',
                'combination_id': 'c1',
                'nights': [{'id': 'n1', 'date': '2026-02-10'}, {'id': 'n2', 'date': '2026-02-11'}],
                'entries': [{'id': 'e1', 'night_id': 'n2', 'name': 'M 31', 'combination_id': 'c2'}],
                'attachments': [{'id': 'a1', 'filename': 'u-1_notes.txt'}],
            }
        ],
    }
    _round_trip('observation_sessions', document)
    assert _count(schema.observation_nights, user_id=UID) == 2
    assert _count(schema.observation_entries, combination_id='c2') == 1
    assert _count(schema.observation_attachments, filename='u-1_notes.txt') == 1


def test_equipment_types_share_one_table_without_mixing():
    _round_trip('equipment.telescopes', {'items': [{'id': 't1', 'name': 'Newton', 'is_shared': True}]})
    _round_trip('equipment.cameras', {'items': [{'id': 'k1', 'name': 'ASI533'}]})
    _round_trip('equipment.telescopes', {'items': [{'id': 't2', 'name': 'Refractor'}]})

    assert documents.get_document(UID, 'equipment.cameras')['items'] == [{'id': 'k1', 'name': 'ASI533'}]
    assert _count(schema.equipment_items, equipment_type='telescopes') == 1


def test_combination_id_lists_become_link_rows():
    combinations = {
        'items': [
            {'id': 'c1', 'telescope_id': 't1', 'filter_ids': ['f1', 'f2'], 'accessory_ids': []},
            {'id': 'c2', 'filter_ids': ['f2']},
        ]
    }
    _round_trip('equipment.combinations', combinations)
    assert _count(schema.combination_equipment, equipment_id='f2', role='filter') == 2
    assert _count(schema.combination_equipment, role='accessory') == 0


def test_plan_is_one_row_with_entry_rows():
    plan = {'user_id': UID, 'plan': {'location_id': 'loc-1', 'entries': [{'id': 'p1', 'name': 'M 31', 'done': False}]}}
    _round_trip('plan', plan, doc_key='combo-1')
    _round_trip('plan', {'user_id': UID, 'plan': None}, doc_key='default')
    assert _count(schema.plans, location_id='loc-1') == 1
    assert _count(schema.plans, user_id=UID) == 1  # a null plan has no row
    assert _count(schema.plan_entries, user_id=UID) == 1


def test_rewrite_replaces_rows_instead_of_appending():
    documents.put_document(UID, 'astrodex', ASTRODEX)
    documents.put_document(UID, 'astrodex', {'username': 'alice', 'items': [{'id': 'only', 'name': 'NGC 7000'}]})
    assert _count(schema.astrodex_items, user_id=UID) == 1
    assert _count(schema.astrodex_pictures, user_id=UID) == 0


def test_duplicate_ids_in_one_collection_are_refused():
    with pytest.raises(IntegrityError):
        documents.put_document(UID, 'wishlist', {'items': [{'id': 'w', 'name': 'a'}, {'id': 'w', 'name': 'b'}]})
    assert documents.get_document(UID, 'wishlist') is None  # the whole write rolled back


def test_delete_document_and_kind_remove_rows():
    documents.put_document(UID, 'astrodex', ASTRODEX)
    assert documents.delete_document(UID, 'astrodex') is True
    assert _count(schema.astrodex_items) == 0 and _count(schema.astrodex_pictures) == 0

    documents.put_document(UID, 'wishlist', {'items': [{'id': 'w', 'name': 'a'}]})
    documents.delete_kind('wishlist')
    assert _count(schema.wishlist_items) == 0


def test_account_deletion_removes_every_row(enforce_foreign_keys):
    documents.put_document(UID, 'astrodex', ASTRODEX)
    documents.put_document(UID, 'equipment.combinations', {'items': [{'id': 'c', 'filter_ids': ['f']}]})
    users_store.delete_user(UID)
    for table in collections.COLLECTION_TABLES:
        assert _count(table) == 0, table.name


def test_foreign_key_cascade_from_parent_rows(enforce_foreign_keys):
    documents.put_document(UID, 'astrodex', ASTRODEX)
    with engine.transaction() as conn:
        conn.execute(schema.astrodex_items.delete().where(schema.astrodex_items.c.id == 'i1'))
    assert _count(schema.astrodex_pictures) == 0
