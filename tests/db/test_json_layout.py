"""The pre-1.7 JSON file layout shared by the importer, the backup and the export."""

import pytest

from db.json_layout import DEFAULT_PLAN_KEY, document_path, parse_document_path

UID = '0b9a0e5c-1111-4c5e-9d1b-2f2a4e3c7a10'


@pytest.mark.parametrize(
    'kind, doc_key, path',
    [
        ('astrodex', '', f'astrodex/{UID}_astrodex.json'),
        ('observation_sessions', '', f'observation_sessions/{UID}_sessions.json'),
        ('wishlist', '', f'wishlist/{UID}_wishlist.json'),
        ('equipment.telescopes', '', f'equipments/{UID}_telescopes.json'),
        ('equipment.combinations', '', f'equipments/{UID}_combinations.json'),
        ('plan', DEFAULT_PLAN_KEY, f'projects/{UID}_plan_my_night.json'),
        ('plan', 'combo-1', f'projects/{UID}_plan_combo-1.json'),
    ],
)
def test_round_trip(kind, doc_key, path):
    """Every kind maps to its historical file name and back."""
    assert document_path(kind, UID, doc_key) == path
    assert parse_document_path(path) == (kind, UID, doc_key)


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        document_path('notes', UID)


@pytest.mark.parametrize(
    'path',
    [
        'astrodex/myastroshine_consumed_handoffs.json',  # a setting, not a document
        f'astrodex/images/{UID}_astrodex.json',  # nested deeper than a document
        f'equipments/{UID}_lenses.json',  # not an equipment type
        f'astrodex/{UID}_astrodex.json.tmp',  # working file
        f'astrodex/../{UID}_astrodex.json',
        'users.json',
    ],
)
def test_non_documents_are_not_parsed(path):
    assert parse_document_path(path) is None


def test_windows_separators_are_accepted():
    assert parse_document_path(f'wishlist\\{UID}_wishlist.json') == ('wishlist', UID, '')
