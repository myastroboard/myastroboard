"""Per-user saves are atomic: a failure half-way leaves the previous data, whole.

Saving used to mean ``.tmp`` + ``os.replace`` under a cross-process file lock. Now a save
is one database transaction that rewrites the user's rows; these tests break it in the
middle (after the first row) and check nothing of the new version was kept.
"""

import pytest

from db import collections
from observation import astrodex, observation_sessions, plan_my_night, wishlist

_USER = "11111111-2222-3333-4444-555555555555"


def _astrodex(names):
    return {'username': 'u', 'items': [{'id': name, 'name': name, 'pictures': []} for name in names]}


def _sessions(names):
    return {
        'username': 'u',
        'sessions': [
            {'id': name, 'nights': [{'id': f'{name}-n', 'date': '2026-01-01'}], 'entries': []} for name in names
        ],
    }


def _wishlist(names):
    return {'username': 'u', 'items': [{'id': name, 'name': name, 'priority': 'normal'} for name in names]}


def _plan(names):
    return {'username': 'u', 'plan': {'entries': [{'id': name, 'name': name} for name in names]}}


_CASES = [
    (astrodex.save_user_astrodex, astrodex.load_user_astrodex, _astrodex, lambda d: [i['id'] for i in d['items']]),
    (
        observation_sessions.save_user_sessions,
        observation_sessions.load_user_sessions,
        _sessions,
        lambda d: [s['id'] for s in d['sessions']],
    ),
    (wishlist.save_user_wishlist, wishlist.load_user_wishlist, _wishlist, lambda d: [i['id'] for i in d['items']]),
    (
        plan_my_night.save_user_plan,
        plan_my_night.load_user_plan,
        _plan,
        lambda d: [e['id'] for e in (d['plan'] or {}).get('entries', [])],
    ),
]


@pytest.mark.parametrize("save, load, build, ids", _CASES)
def test_failed_save_keeps_the_previous_version(monkeypatch, save, load, build, ids):
    assert save(_USER, build(['a', 'b'])) is True

    real_insert = collections._insert
    calls = {'n': 0}

    def _insert_then_fail(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] > 1:
            raise OSError('disk full')
        return real_insert(*args, **kwargs)

    monkeypatch.setattr(collections, '_insert', _insert_then_fail)
    assert save(_USER, build(['c', 'd', 'e'])) is False

    monkeypatch.setattr(collections, '_insert', real_insert)
    assert ids(load(_USER)) == ['a', 'b']
