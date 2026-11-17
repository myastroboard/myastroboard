"""Tests for community.activity - the feed and the shared "together" totals.

No ranking anywhere: the feed is ordered by day, the totals are a union.
"""

import datetime
import types

from community import activity, members
from observation import achievements

TODAY = datetime.date(2026, 11, 17)
TOTALS = {'Messier': 3}


def _resolve(name, _catalogue):
    key = str(name).replace(' ', '').lower()
    return {
        'group_id': f'dso-{key}',
        'aliases': {'Messier': name},
        'object_type': 'Galaxy',
        'category': 'deep_sky',
        'constellation': 'And' if name != 'M 2' else 'Aqr',
    }


def _member(user_id, names_by_day, pictures=(), preferences=None, **community):
    nights, entries = [], []
    for index, (day, names) in enumerate(names_by_day.items()):
        nights.append({'id': f'n{index}', 'date': day})
        entries.extend(
            {'id': f'e-{name}', 'night_id': f'n{index}', 'name': name, 'integration_minutes': 30.0} for name in names
        )
    sessions = [{'id': 's', 'location_id': 'loc', 'nights': nights, 'entries': entries}]
    items = [{'name': name, 'pictures': [{'filename': f'{name}.jpg', 'date': day}]} for name, day in pictures]
    facts = achievements.collect_progress(sessions, [], resolve=_resolve)
    user = types.SimpleNamespace(
        user_id=user_id,
        username=user_id,
        preferences=preferences or {},
        profile={'community': {'listed': True, **community}},
    )
    badges = members.earned_badges(facts, TOTALS) if members.badges_allowed(user) else []
    return {'user': user, 'facts': facts, 'items': items, 'badges': badges}


class TestFeed:
    def test_one_digest_per_member_and_day_newest_first(self):
        alice = _member(
            'alice', {'2026-11-10': ['M 1', 'M 2'], '2026-11-12': ['M 3']}, pictures=[('M 1', '2026-11-10')]
        )
        bob = _member('bob', {'2026-11-11': ['M 1']})
        feed = activity.build_feed([alice, bob], TODAY, pictures_shared=True)
        assert [(digest['date'], digest['member']['user_id']) for digest in feed] == [
            ('2026-11-12', 'alice'),
            ('2026-11-11', 'bob'),
            ('2026-11-10', 'alice'),
        ]
        day = feed[2]
        assert [item['name'] for item in day['new_objects']] == ['M 1', 'M 2']
        assert day['pictures'] == [{'filename': 'M 1.jpg', 'item_name': 'M 1'}]
        assert any(badge['rule'] == 'first_class' for badge in day['badges'])

    def test_hidden_parts_stay_out(self):
        quiet = _member('quiet', {'2026-11-10': ['M 1']}, show_activity=False)
        no_badges = _member('nob', {'2026-11-10': ['M 1']}, show_badges=False, pictures=[('M 1', '2026-11-10')])
        feed = activity.build_feed([quiet, no_badges], TODAY, pictures_shared=False)
        assert [digest['member']['user_id'] for digest in feed] == ['nob']
        assert feed[0]['badges'] == []
        assert feed[0]['pictures'] == []

    def test_window_limit_and_future_days(self):
        member = _member('m', {'2026-01-01': ['M 1'], '2026-11-10': ['M 2'], '2026-12-25': ['M 3']})
        assert [d['date'] for d in activity.build_feed([member], TODAY, pictures_shared=True)] == [
            '2026-11-10',
            '2026-01-01',
        ]
        windowed = activity.build_feed([member], TODAY, pictures_shared=True, days=30)
        assert [d['date'] for d in windowed] == ['2026-11-10']
        assert len(activity.build_feed([member], TODAY, pictures_shared=True, limit=1)) == 1

    def test_long_days_are_capped_but_counted(self):
        names = [f'M {index}' for index in range(1, 11)]
        member = _member('m', {'2026-11-10': names})
        digest = activity.build_feed([member], TODAY, pictures_shared=True)[0]
        assert digest['new_objects_count'] == 10
        assert len(digest['new_objects']) == activity.FEED_ITEMS_PER_KIND
        # Natural order: M 2 before M 10
        assert [item['name'] for item in digest['new_objects']][:2] == ['M 1', 'M 2']


class TestTogether:
    def test_union_of_members_who_show_their_figures(self, monkeypatch):
        monkeypatch.setattr(
            achievements,
            'catalogue_members',
            lambda catalogue: [
                {'target_id': f'dso-m{index}', 'identifier': f'M {index}', 'preferred_name': f'M {index}'}
                for index in (1, 2, 3, 10)
            ],
        )
        alice = _member('alice', {'2026-11-10': ['M 1', 'M 2']})
        bob = _member('bob', {'2026-11-11': ['M 1']})
        hidden = _member('hid', {'2026-11-11': ['M 3']}, show_stats=False)
        together = activity.build_together([alice, bob, hidden], TOTALS)
        assert together['members'] == 2
        assert together['objects'] == 2
        assert together['integration_minutes'] == 90.0
        assert together['nights'] == 2
        assert together['constellations'] == 2
        messier = together['catalogues'][0]
        assert (messier['captured'], messier['total']) == (2, 3)
        assert messier['remaining_examples'] == ['M 3', 'M 10']

    def test_complete_and_empty_catalogues(self, monkeypatch):
        def broken(_catalogue):
            raise RuntimeError('dataset missing')

        monkeypatch.setattr(achievements, 'catalogue_members', broken)
        member = _member('m', {'2026-11-10': ['M 1', 'M 2', 'M 3']})
        together = activity.build_together([member], {'Messier': 3, 'Caldwell': 109})
        assert [row['catalogue'] for row in together['catalogues']] == ['Messier']
        assert together['catalogues'][0]['remaining_examples'] == []
        partial = activity.build_together([_member('p', {'2026-11-10': ['M 1']})], TOTALS)
        assert partial['catalogues'][0]['remaining_examples'] == []

    def test_nobody_taking_part(self):
        together = activity.build_together([], TOTALS)
        assert together['members'] == 0
        assert together['catalogues'] == []


class TestTtlCache:
    def test_expiry_and_bound(self):
        cache = activity.TtlCache(ttl=10, max_entries=2)
        cache.put('a', 1, now=0)
        assert cache.get('a', now=5) == 1
        assert cache.get('a', now=11) is None
        cache.put('b', 2, now=0)
        cache.put('c', 3, now=0)
        cache.put('d', 4, now=0)
        assert cache.get('b', now=1) is None
        cache.clear()
        assert cache.get('d', now=1) is None


def test_natural_order_handles_letters_after_numbers():
    """Names such as "NGC 7000A" sort by their number first, then by the letter."""
    names = ['NGC 7000B', 'NGC 891', 'NGC 7000A', 'IC 5']
    assert sorted(names, key=activity._natural_key) == ['IC 5', 'NGC 891', 'NGC 7000A', 'NGC 7000B']
