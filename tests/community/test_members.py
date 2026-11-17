"""Tests for community.members - directory and profile blocks.

The visibility rules are the point: a member who has not joined is never listed, and only
the blocks they turned on are built.
"""

import types

from community import members
from observation import achievements

TOTALS = {'Messier': 110, 'Caldwell': 109}


def _resolve(name, _catalogue):
    key = str(name).replace(' ', '').lower()
    return {
        'group_id': f'dso-{key}',
        'aliases': {'Messier': name},
        'object_type': 'Galaxy',
        'category': 'deep_sky',
        'constellation': 'And',
    }


def _facts(names, minutes=60.0, day='2026-10-01'):
    night = {'id': 'n1', 'date': day, 'sqm': None, 'moon_illumination_percent': None}
    entries = [
        {'id': f'e-{name}', 'night_id': 'n1', 'name': name, 'catalogue': 'Messier', 'integration_minutes': minutes}
        for name in names
    ]
    sessions = [{'id': 's1', 'location_id': 'loc', 'nights': [night], 'entries': entries}]
    return achievements.collect_progress(sessions, [], resolve=_resolve)


def _user(user_id='u1', name='alice', created='2026-03-04T10:00:00+00:00', preferences=None, **community):
    return types.SimpleNamespace(
        user_id=user_id,
        username=name,
        created_at=created,
        preferences=preferences or {},
        profile={'display_name': None, 'bio': 'Hello', 'community': community},
    )


class TestDirectory:
    def test_only_listed_members_alphabetically_and_without_figures(self):
        users = [
            _user('u1', 'zoe', listed=True),
            _user('u2', 'Adam', listed=True),
            _user('u3', 'hidden', listed=False),
        ]
        rows = members.directory(users, viewer_id='u1')
        assert [row['display_name'] for row in rows] == ['Adam', 'zoe']
        assert [row['is_you'] for row in rows] == [False, True]
        assert rows[0]['member_since'] == '2026-03-04'
        assert rows[0]['bio'] == 'Hello'

    def test_can_view_profile(self):
        assert members.can_view_profile(_user(listed=True), 'someone')
        assert not members.can_view_profile(_user(listed=False), 'someone')
        assert members.can_view_profile(_user(listed=False), 'u1')
        assert not members.can_view_profile(_user(listed=False), None)


class TestBlocks:
    def test_stats_block(self):
        stats = members.stats_block(_facts(['M 31', 'M 33']), TOTALS)
        assert stats['objects'] == 2
        assert stats['integration_minutes'] == 120.0
        assert stats['nights'] == 1
        assert stats['constellations'] == 1
        assert stats['catalogues'] == [{'catalogue': 'Messier', 'captured': 2, 'total': 110}]

    def test_earned_badges_newest_first(self):
        badges = members.earned_badges(_facts(['M 31']), TOTALS)
        assert badges and all(badge['earned_on'] for badge in badges)
        assert {'id', 'rule', 'icon', 'target', 'earned_on'} <= set(badges[0])
        assert badges == sorted(badges, key=lambda badge: badge['earned_on'], reverse=True)

    def test_member_pictures_newest_first_and_junk_skipped(self):
        items = [
            {
                'name': 'M 31',
                'pictures': [
                    {'filename': 'a.jpg', 'date': '2026-01-02T22:00:00'},
                    {'filename': '', 'date': '2026-05-01'},
                    'junk',
                ],
            },
            {'name': 'M 42', 'pictures': [{'filename': 'b.jpg', 'created_at': '2026-04-01', 'is_main': True}]},
            {'name': 'M 1', 'pictures': [{'filename': 'c.jpg'}]},
            'junk',
        ]
        pictures = members.member_pictures(items)
        assert [picture['filename'] for picture in pictures] == ['b.jpg', 'a.jpg', 'c.jpg']
        assert pictures[1]['date'] == '2026-01-02'
        assert pictures[0]['is_main'] is True

    def test_badges_allowed(self):
        assert members.badges_allowed(_user(listed=True))
        assert not members.badges_allowed(_user(listed=True, show_badges=False))
        assert not members.badges_allowed(_user(listed=True, preferences={'achievements_enabled': False}))


class TestEquipment:
    def test_active_combinations_with_names(self, monkeypatch):
        from equipment import equipment_profiles

        monkeypatch.setattr(
            equipment_profiles,
            'load_user_combinations',
            lambda _uid: {
                'items': [
                    {'name': 'Rig', 'telescope_id': 't1', 'camera_id': 'c1'},
                    {'name': 'Old', 'telescope_id': 't1', 'is_disabled': True},
                    {'name': 'Lens', 'camera_id': 'missing'},
                ]
            },
        )
        monkeypatch.setattr(
            equipment_profiles, 'load_user_telescopes', lambda _uid: {'items': [{'id': 't1', 'name': 'ED80'}]}
        )
        monkeypatch.setattr(
            equipment_profiles, 'load_user_cameras', lambda _uid: {'items': [{'id': 'c1', 'name': 'ASI533'}]}
        )
        assert members.equipment_block('u1') == [
            {'name': 'Rig', 'telescope': 'ED80', 'camera': 'ASI533'},
            {'name': 'Lens', 'telescope': None, 'camera': None},
        ]

    def test_read_errors_give_an_empty_list(self, monkeypatch):
        from equipment import equipment_profiles

        def broken(_uid):
            raise RuntimeError('db down')

        monkeypatch.setattr(equipment_profiles, 'load_user_combinations', broken)
        assert members.equipment_block('u1') == []


class TestBuildProfile:
    def _loader(self, calls):
        def load(user):
            calls.append(user.user_id)
            return {'facts': _facts(['M 31']), 'items': [{'name': 'M 31', 'pictures': [{'filename': 'a.jpg'}]}]}

        return load

    def test_only_shown_blocks(self, monkeypatch):
        monkeypatch.setattr(members, 'equipment_block', lambda _uid: [{'name': 'Rig'}])
        calls = []
        user = _user(listed=True, show_stats=False, show_badges=False, show_pictures=False, show_equipment=True)
        payload = members.build_profile(user, self._loader(calls), TOTALS, pictures_shared=True, activity=[])
        assert set(payload['blocks']) == {'equipment', 'activity'}
        # Nothing needed the log or the Astrodex: they were not read
        assert calls == []

    def test_private_astrodex_hides_pictures(self):
        calls = []
        payload = members.build_profile(_user(listed=True), self._loader(calls), TOTALS, pictures_shared=False)
        assert 'pictures' not in payload['blocks']
        assert {'stats', 'badges'} <= set(payload['blocks'])
        assert 'activity' not in payload['blocks']  # no activity passed in
        assert calls == ['u1']

    def test_badges_off_in_preferences(self):
        user = _user(listed=True, preferences={'achievements_enabled': False})
        payload = members.build_profile(user, self._loader([]), TOTALS, pictures_shared=True)
        assert 'badges' not in payload['blocks']
        assert payload['blocks']['pictures'][0]['filename'] == 'a.jpg'


class TestLoadMemberData:
    def test_reads_log_and_astrodex(self, monkeypatch):
        from observation import astrodex, observation_sessions

        monkeypatch.setattr(observation_sessions, 'load_user_sessions', lambda uid, name: {'sessions': 'junk'})
        monkeypatch.setattr(
            astrodex, 'load_user_astrodex', lambda uid, name: {'items': [{'name': 'M 31', 'pictures': []}]}
        )
        data = members.load_member_data(_user())
        assert data['sessions'] == []
        assert len(data['items']) == 1
        assert data['facts']['captures']

    def test_read_errors_give_empty_data(self, monkeypatch):
        from observation import astrodex, observation_sessions

        def broken(uid, name):
            raise RuntimeError('db down')

        monkeypatch.setattr(observation_sessions, 'load_user_sessions', broken)
        monkeypatch.setattr(astrodex, 'load_user_astrodex', broken)
        data = members.load_member_data(_user())
        assert data['sessions'] == [] and data['items'] == []
        assert data['facts']['captures'] == {}
