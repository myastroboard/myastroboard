"""Cross-user searches answered in SQL (db/queries.py)."""

from db import documents, queries

A, B = 'user-a', 'user-b'


def _seed():
    documents.put_document(
        A,
        'astrodex',
        {
            'items': [
                {
                    'id': 'i1',
                    'name': 'M 31',
                    'pictures': [
                        {'id': 'p1', 'filename': 'a.jpg', 'location_id': 'loc-1', 'combination_id': 'c1'},
                        {'id': 'p2', 'filename': 'b.jpg', 'location_id': 'loc-2'},
                    ],
                }
            ]
        },
    )
    documents.put_document(
        B, 'astrodex', {'items': [{'id': 'i9', 'name': 'M 42', 'pictures': [{'id': 'p9', 'location_id': 'loc-1'}]}]}
    )
    documents.put_document(
        A,
        'observation_sessions',
        {
            'sessions': [
                {
                    'id': 's1',
                    'location_id': 'loc-1',
                    'combination_id': 'c1',
                    'entries': [{'id': 'e', 'combination_id': 'c1'}],
                },
                {'id': 's2', 'combination_id': 'c0', 'entries': [{'id': 'e2', 'combination_id': 'c1'}]},
                {'id': 's3', 'combination_id': 'c0'},
            ]
        },
    )
    documents.put_document(A, 'plan', {'plan': {'location_id': 'loc-1', 'combination_id': 'c1'}}, 'c1')
    documents.put_document(B, 'plan', {'plan': {'location_id': 'loc-1'}}, 'default')
    documents.put_document(
        A, 'equipment.telescopes', {'items': [{'id': 't1', 'name': 'Newton', 'is_shared': True}, {'id': 't2'}]}
    )
    documents.put_document(
        B,
        'equipment.combinations',
        {
            'items': [
                {'id': 'c1', 'name': 'Rig', 'telescope_id': 't1', 'filter_ids': ['f1']},
                {'id': 'c2', 'name': 'Guide', 'guide_camera_id': 'k1', 'accessory_ids': ['x1']},
            ]
        },
    )


def test_astrodex_picture_counts_and_lookup():
    _seed()
    assert queries.count_astrodex_pictures(location_id='loc-1') == 2
    assert queries.count_astrodex_pictures(combination_id='c1') == 1
    assert queries.astrodex_picture_exists('a.jpg') is True
    assert queries.astrodex_picture_exists('a.jpg', user_id=B) is False
    assert queries.astrodex_picture_exists('missing.jpg') is False


def test_session_counts_include_entry_level_combinations_once():
    _seed()
    assert queries.count_sessions_for_location('loc-1') == 1
    assert queries.count_sessions_for_combination('c1') == 2  # s1 (session + entry) counted once, s2 by entry
    assert queries.count_sessions_for_combination('c0') == 2


def test_plan_counts_and_lookup():
    _seed()
    assert queries.count_plans(location_id='loc-1') == 2
    assert queries.count_plans(combination_id='c1') == 1
    assert sorted(queries.plans_for_location('loc-1')) == [(A, 'c1'), (B, 'default')]


def test_combinations_referencing_scalar_and_list_fields():
    _seed()
    assert queries.combinations_referencing('telescopes', 't1') == [{'name': 'Rig', 'owner_id': B}]
    assert queries.combinations_referencing('cameras', 'k1') == [{'name': 'Guide', 'owner_id': B}]
    assert queries.combinations_referencing('filters', 'f1') == [{'name': 'Rig', 'owner_id': B}]
    assert queries.combinations_referencing('accessories', 'x1') == [{'name': 'Guide', 'owner_id': B}]
    assert queries.combinations_referencing('mounts', 'nothing') == []
    assert queries.combinations_referencing('unknown-type', 't1') == []


def test_shared_equipment_excludes_the_viewer_and_private_items():
    _seed()
    assert queries.shared_equipment('telescopes', exclude_user_id=B) == [
        (A, {'id': 't1', 'name': 'Newton', 'is_shared': True})
    ]
    assert queries.shared_equipment('telescopes', exclude_user_id=A) == []
