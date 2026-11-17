"""API tests for the profile and Community blueprint.

They cover the rules the pure modules cannot: who may see which profile, the admin switch,
the private-by-default directory, the avatar upload and serving, moderation, and the demo
mode guard. The profile blocks, the feed and the totals have their own tests in
tests/community/.
"""

import io
import sys
import types
import uuid

import pytest
from PIL import Image

from observation import achievements
from utils import user_identity
from utils.auth import user_manager

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import community as community_module

LOCATION = {'id': 'loc-test', 'name': 'Test Site', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}
TOTALS = {'Messier': 3}


def _resolve(name, _catalogue):
    key = str(name).replace(' ', '').lower()
    return {'group_id': f'dso-{key}', 'aliases': {'Messier': name}, 'object_type': 'Galaxy', 'category': 'deep_sky'}


def _facts(names, day='2026-11-10'):
    night = {'id': 'n1', 'date': day, 'sqm': None, 'moon_illumination_percent': None}
    entries = [
        {'id': f'e-{name}', 'night_id': 'n1', 'name': name, 'catalogue': 'Messier', 'integration_minutes': 60.0}
        for name in names
    ]
    sessions = [{'id': 's1', 'location_id': 'loc-1', 'nights': [night], 'entries': entries}]
    return achievements.collect_progress(sessions, [], resolve=_resolve)


@pytest.fixture
def community_env(monkeypatch, tmp_path):
    """Stub the per-member data, the location and the catalogue sizes; isolate the avatars."""
    captures: dict[str, list[str]] = {}

    def load(user, location_bortle=None):
        names = captures.get(user.user_id, [])
        items = [
            {
                'id': f'a-{name}',
                'name': name,
                'pictures': [{'id': 'p', 'filename': f'{name}.jpg', 'date': '2026-11-10'}],
            }
            for name in names
        ]
        return {'user': user, 'sessions': [], 'items': items, 'facts': _facts(names)}

    monkeypatch.setattr(community_module.members, 'load_member_data', load)
    monkeypatch.setattr(community_module, '_resolve_active_location', lambda: LOCATION)
    monkeypatch.setattr(community_module, '_location_bortle', lambda: {})
    monkeypatch.setattr(community_module.achievements, 'catalogue_totals', lambda: dict(TOTALS))
    monkeypatch.setattr(
        community_module.activity.achievements,
        'catalogue_members',
        lambda catalogue: [
            {'target_id': f'dso-m{index}', 'identifier': f'M {index}', 'preferred_name': f'M {index}'}
            for index in (1, 2, 3)
        ],
    )
    monkeypatch.setattr(user_identity, 'AVATARS_DIR', str(tmp_path / 'avatars'))
    community_module.clear_caches()
    yield captures
    community_module.clear_caches()


def _new_user(role='user'):
    name = f'member-{uuid.uuid4().hex[:8]}'
    user_manager.create_user(name, 'password-123', role)
    return user_manager.get_user_by_username(name)


def _login(test_client, user):
    with test_client.session_transaction() as session:
        session['user_id'] = user.user_id
        session['username'] = user.username
        session['role'] = user.role


@pytest.fixture
def client(community_env):
    app.config['TESTING'] = True
    with app.test_client() as test_client:
        yield test_client


def _join(user, **community):
    user_manager.update_user_profile(user.user_id, {'community': {'listed': True, **community}})


def _png(size=(400, 300), colour=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new('RGB', size, colour).save(buffer, format='PNG')
    return buffer.getvalue()


class TestOwnProfile:
    def test_requires_login(self, client):
        assert client.get('/api/profile').status_code == 401

    def test_defaults_are_private(self, client):
        user = _new_user()
        _login(client, user)
        payload = client.get('/api/profile').get_json()
        assert payload['username'] == user.username
        assert payload['profile']['community']['listed'] is False
        assert payload['identity']['display_name'] == user.username
        assert payload['community_enabled'] is True

    def test_update_display_name_bio_and_community(self, client):
        user = _new_user()
        _login(client, user)
        response = client.put(
            '/api/profile',
            json={
                'display_name': '  Sam   the  Stargazer ',
                'bio': 'Hi!\n\n\n\nClear skies',
                'community': {'listed': True},
            },
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['profile']['display_name'] == 'Sam the Stargazer'
        assert payload['profile']['bio'] == 'Hi!\n\nClear skies'
        assert payload['identity']['display_name'] == 'Sam the Stargazer'
        assert user_manager.get_user_by_id(user.user_id).display_name == 'Sam the Stargazer'

    @pytest.mark.parametrize(
        ('body', 'key'),
        [
            ({'display_name': 'x' * 41}, 'profile.error_display_name_length'),
            ({'display_name': 'bad​name'}, 'profile.error_display_name_invalid'),
            ({'bio': 'x' * 281}, 'profile.error_bio_length'),
            ({'community': {'listed': 'yes'}}, 'profile.error_invalid'),
            ({'community': 'on'}, 'profile.error_invalid'),
        ],
    )
    def test_invalid_updates_are_rejected_with_a_key(self, client, body, key):
        _login(client, _new_user())
        response = client.put('/api/profile', json=body)
        assert response.status_code == 400
        assert response.get_json()['error_key'] == key

    def test_non_object_payload_is_rejected(self, client):
        _login(client, _new_user())
        assert client.put('/api/profile', json=['x']).status_code == 400

    def test_display_name_cannot_take_another_members_name(self, client):
        other = _new_user()
        user = _new_user()
        _login(client, user)
        response = client.put('/api/profile', json={'display_name': other.username.upper()})
        assert response.get_json()['error_key'] == 'profile.error_display_name_taken'
        user_manager.update_user_profile(other.user_id, {'display_name': 'Orion'})
        response = client.put('/api/profile', json={'display_name': 'orion'})
        assert response.get_json()['error_key'] == 'profile.error_display_name_taken'

    def test_read_only_members_may_edit_their_profile(self, client):
        _login(client, _new_user('read-only'))
        assert client.put('/api/profile', json={'display_name': 'Watcher'}).status_code == 200

    def test_shared_labels_use_the_display_name(self, client):
        user = _new_user()
        user_manager.update_user_profile(user.user_id, {'display_name': 'Vega Fan'})
        assert user_manager.display_names_by_id()[user.user_id] == 'Vega Fan'
        listed = next(entry for entry in user_manager.list_users() if entry['user_id'] == user.user_id)
        assert listed['display_name'] == 'Vega Fan'
        assert listed['avatar_url'].startswith(f'/api/users/{user.user_id}/avatar?v=')


class TestAvatar:
    def test_upload_is_squared_and_served(self, client):
        user = _new_user()
        _login(client, user)
        response = client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})
        assert response.status_code == 200
        identity = response.get_json()['identity']
        assert identity['has_avatar'] is True

        served = client.get(identity['avatar_url'])
        assert served.status_code == 200
        assert served.mimetype == 'image/webp'
        with Image.open(io.BytesIO(served.data)) as image:
            assert image.size == (user_identity.AVATAR_SIZE, user_identity.AVATAR_SIZE)
            assert not image.info.get('exif')

    def test_replacing_deletes_the_previous_file(self, client, tmp_path):
        user = _new_user()
        _login(client, user)
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'one.png')})
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png(colour=(0, 0, 200))), 'two.jpg')})
        files = list((tmp_path / 'avatars').iterdir())
        assert len(files) == 1
        assert files[0].name.startswith(f'{user.user_id}_avatar_')

    def test_delete_falls_back_to_initials(self, client, tmp_path):
        user = _new_user()
        _login(client, user)
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})
        response = client.delete('/api/profile/avatar')
        assert response.get_json()['identity']['has_avatar'] is False
        assert list((tmp_path / 'avatars').iterdir()) == []
        served = client.get(f'/api/users/{user.user_id}/avatar')
        assert served.mimetype == 'image/svg+xml'
        assert b'<svg' in served.data

    @pytest.mark.parametrize(
        ('data', 'filename'),
        [(b'not an image', 'me.png'), (b'', 'me.png'), (b'GIF89a', 'me.exe')],
    )
    def test_bad_uploads_are_rejected(self, client, data, filename):
        _login(client, _new_user())
        response = client.post('/api/profile/avatar', data={'file': (io.BytesIO(data), filename)})
        assert response.status_code == 400
        assert response.get_json()['error_key'] == 'profile.error_avatar_invalid'

    def test_missing_file_is_rejected(self, client):
        _login(client, _new_user())
        assert client.post('/api/profile/avatar', data={}).status_code == 400

    def test_oversized_upload_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(user_identity, 'AVATAR_MAX_UPLOAD_BYTES', 100)
        _login(client, _new_user())
        response = client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})
        assert response.get_json()['error_key'] == 'profile.error_avatar_too_large'

    def test_unknown_user_avatar_is_404(self, client):
        _login(client, _new_user())
        assert client.get('/api/users/nobody/avatar').status_code == 404

    def test_initials_escape_the_name(self, client):
        user = _new_user()
        user_manager.update_user_profile(user.user_id, {'display_name': '<b>& co'})
        _login(client, user)
        body = client.get(f'/api/users/{user.user_id}/avatar').data
        assert b'<b>' not in body
        assert b'&lt;' in body

    def test_missing_avatar_file_serves_initials(self, client, tmp_path):
        user = _new_user()
        _login(client, user)
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})
        for path in (tmp_path / 'avatars').iterdir():
            path.unlink()
        assert client.get(f'/api/users/{user.user_id}/avatar').mimetype == 'image/svg+xml'

    def test_account_deletion_removes_the_avatar(self, client, tmp_path, monkeypatch):
        user = _new_user()
        _login(client, user)
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})
        assert list((tmp_path / 'avatars').iterdir())
        user_manager.delete_user(user.user_id)
        assert list((tmp_path / 'avatars').iterdir()) == []


class TestModeration:
    def test_admin_resets_a_profile(self, client, tmp_path):
        member = _new_user()
        _login(client, member)
        client.put('/api/profile', json={'display_name': 'Rude Name', 'bio': 'spam', 'community': {'listed': True}})
        client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')})

        _login(client, user_manager.get_user_by_username('admin'))
        assert client.delete(f'/api/users/{member.user_id}/profile').status_code == 200
        profile = user_manager.get_user_by_id(member.user_id).profile
        assert profile['display_name'] is None
        assert profile['bio'] == ''
        assert profile['avatar'] is None
        assert profile['community']['listed'] is True
        assert list((tmp_path / 'avatars').iterdir()) == []

    def test_reset_requires_admin(self, client):
        member = _new_user()
        _login(client, _new_user())
        assert client.delete(f'/api/users/{member.user_id}/profile').status_code == 403

    def test_reset_unknown_user_is_404(self, client):
        _login(client, user_manager.get_user_by_username('admin'))
        assert client.delete('/api/users/nobody/profile').status_code == 404


class TestDirectory:
    def test_only_members_who_joined_are_listed_alphabetically(self, client):
        hidden = _new_user()
        zed, amy = _new_user(), _new_user()
        user_manager.update_user_profile(zed.user_id, {'display_name': 'Zed', 'community': {'listed': True}})
        user_manager.update_user_profile(amy.user_id, {'display_name': 'amy', 'community': {'listed': True}})
        _login(client, hidden)
        payload = client.get('/api/community/members').get_json()
        ids = [member['user_id'] for member in payload['members']]
        assert hidden.user_id not in ids
        names = [member['display_name'] for member in payload['members']]
        assert names.index('amy') < names.index('Zed')
        assert payload['you_listed'] is False

    def test_directory_cards_carry_no_figures(self, client):
        member = _new_user()
        _join(member)
        _login(client, member)
        card = next(m for m in client.get('/api/community/members').get_json()['members'] if m['is_you'])
        assert set(card) == {'user_id', 'display_name', 'avatar_url', 'has_avatar', 'bio', 'member_since', 'is_you'}


class TestMemberProfile:
    def test_unlisted_profile_is_404_for_others_but_previewable_by_its_owner(self, client, community_env):
        owner = _new_user()
        community_env[owner.user_id] = ['M 1']
        _login(client, _new_user())
        assert client.get(f'/api/community/members/{owner.user_id}').status_code == 404

        _login(client, owner)
        preview = client.get(f'/api/community/members/{owner.user_id}').get_json()
        assert preview['listed'] is False
        assert preview['is_you'] is True
        assert preview['blocks']['stats']['objects'] == 1

    def test_only_shown_blocks_are_returned(self, client, community_env):
        owner = _new_user()
        community_env[owner.user_id] = ['M 1', 'M 2']
        _join(owner, show_stats=False, show_badges=True, show_pictures=True, show_equipment=False, show_activity=False)
        _login(client, _new_user())
        payload = client.get(f'/api/community/members/{owner.user_id}').get_json()
        assert set(payload['blocks']) == {'badges', 'pictures'}
        assert {picture['item_name'] for picture in payload['blocks']['pictures']} == {'M 1', 'M 2'}

    def test_badges_hidden_when_the_member_turned_badges_off(self, client, community_env):
        owner = _new_user()
        community_env[owner.user_id] = ['M 1']
        _join(owner)
        user_manager.update_user_preferences(owner.user_id, {'achievements_enabled': False})
        _login(client, _new_user())
        assert 'badges' not in client.get(f'/api/community/members/{owner.user_id}').get_json()['blocks']

    def test_private_astrodex_mode_never_shows_pictures(self, client, community_env, monkeypatch):
        owner = _new_user()
        community_env[owner.user_id] = ['M 1']
        _join(owner)
        monkeypatch.setattr(community_module, 'load_config', lambda: {'astrodex': {'private': True}})
        _login(client, _new_user())
        payload = client.get(f'/api/community/members/{owner.user_id}').get_json()
        assert 'pictures' not in payload['blocks']
        assert all(not digest['pictures'] for digest in payload['blocks']['activity'])

    def test_equipment_block_lists_combination_names(self, client, community_env, monkeypatch):
        owner = _new_user()
        _join(owner, show_equipment=True, show_stats=False, show_badges=False, show_pictures=False)
        monkeypatch.setattr(
            community_module.members,
            'equipment_block',
            lambda user_id: [{'name': 'Refractor rig', 'telescope': 'ED80', 'camera': 'ASI533'}],
        )
        _login(client, _new_user())
        payload = client.get(f'/api/community/members/{owner.user_id}').get_json()
        assert payload['blocks']['equipment'][0]['telescope'] == 'ED80'

    def test_unknown_member_is_404(self, client):
        _login(client, _new_user())
        assert client.get('/api/community/members/nobody').status_code == 404


class TestActivity:
    def test_feed_and_together(self, client, community_env):
        first, second = _new_user(), _new_user()
        community_env[first.user_id] = ['M 1']
        community_env[second.user_id] = ['M 1', 'M 2']
        _join(first)
        _join(second)
        _login(client, first)
        payload = client.get('/api/community/activity').get_json()
        together = payload['together']
        assert together['members'] >= 2
        messier = next(row for row in together['catalogues'] if row['catalogue'] == 'Messier')
        assert messier['captured'] >= 2
        assert 'M 3' in messier['remaining_examples']
        authors = {digest['member']['user_id'] for digest in payload['feed']}
        assert {first.user_id, second.user_id} <= authors
        assert payload['you_listed'] is True

    def test_members_who_hide_their_activity_are_not_in_the_feed(self, client, community_env):
        quiet = _new_user()
        community_env[quiet.user_id] = ['M 1']
        _join(quiet, show_activity=False, show_stats=False)
        _login(client, _new_user())
        payload = client.get('/api/community/activity').get_json()
        assert quiet.user_id not in {digest['member']['user_id'] for digest in payload['feed']}

    def test_snapshot_is_cached(self, client, community_env, monkeypatch):
        calls = []
        original = community_module._member_data
        monkeypatch.setattr(community_module, '_member_data', lambda *args: calls.append(1) or original(*args))
        member = _new_user()
        _join(member)
        _login(client, member)
        client.get('/api/community/activity')
        first = len(calls)
        client.get('/api/community/activity')
        assert len(calls) == first


class TestAdminSwitch:
    @pytest.mark.parametrize('path', ['/api/community/members', '/api/community/members/x', '/api/community/activity'])
    def test_community_routes_are_404_when_turned_off(self, client, monkeypatch, path):
        monkeypatch.setattr(community_module, 'load_config', lambda: {'community': {'enabled': False}})
        _login(client, _new_user())
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json()['error_key'] == 'community.disabled'

    def test_profile_still_works_when_turned_off(self, client, monkeypatch):
        monkeypatch.setattr(community_module, 'load_config', lambda: {'community': {'enabled': False}})
        _login(client, _new_user())
        payload = client.get('/api/profile').get_json()
        assert payload['community_enabled'] is False

    def test_config_route_validates_the_switch(self, client):
        _login(client, user_manager.get_user_by_username('admin'))
        response = client.post('/api/config', json={'community': {'enabled': 'no'}})
        assert response.status_code == 400


class TestDemoMode:
    def test_profile_writes_are_blocked_in_demo(self, client, monkeypatch):
        from utils import demo_mode

        user = _new_user()
        monkeypatch.setattr(demo_mode, 'is_demo_session', lambda: True)
        _login(client, user)
        assert client.put('/api/profile', json={'display_name': 'Visitor'}).status_code == 403
        assert client.get('/api/profile').status_code == 200


class TestServerErrors:
    @pytest.mark.parametrize(
        ('method', 'path', 'target'),
        [
            ('get', '/api/profile', '_own_profile_payload'),
            ('get', '/api/community/members', 'members.directory'),
            ('get', '/api/community/activity', '_community_snapshot'),
        ],
    )
    def test_unexpected_errors_are_500(self, client, monkeypatch, method, path, target):
        def boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        owner, _, attribute = target.rpartition('.')
        monkeypatch.setattr(getattr(community_module, owner) if owner else community_module, attribute, boom)
        _login(client, _new_user())
        assert getattr(client, method)(path).status_code == 500


class TestWriteServerErrors:
    """Every route answers 500 (never a stack trace) when an inner call fails unexpectedly."""

    @staticmethod
    def _boom(*_args, **_kwargs):
        raise RuntimeError('boom')

    def test_profile_update(self, client, monkeypatch):
        _login(client, _new_user())
        monkeypatch.setattr(user_manager, 'update_user_profile', self._boom)
        assert client.put('/api/profile', json={'bio': 'x'}).status_code == 500

    def test_avatar_upload_and_delete(self, client, monkeypatch):
        _login(client, _new_user())
        monkeypatch.setattr(user_manager, 'set_user_avatar', self._boom)
        assert client.post('/api/profile/avatar', data={'file': (io.BytesIO(_png()), 'me.png')}).status_code == 500
        assert client.delete('/api/profile/avatar').status_code == 500

    def test_admin_reset(self, client, monkeypatch):
        member = _new_user()
        _login(client, user_manager.get_user_by_username('admin'))
        monkeypatch.setattr(user_manager, 'reset_user_profile', self._boom)
        assert client.delete(f'/api/users/{member.user_id}/profile').status_code == 500

    def test_avatar_serving(self, client, monkeypatch):
        member = _new_user()
        _login(client, member)
        monkeypatch.setattr(community_module.user_identity, 'initials_svg', self._boom)
        assert client.get(f'/api/users/{member.user_id}/avatar').status_code == 500

    def test_member_profile(self, client, monkeypatch):
        member = _new_user()
        _join(member)
        _login(client, member)
        monkeypatch.setattr(community_module.members, 'build_profile', self._boom)
        assert client.get(f'/api/community/members/{member.user_id}').status_code == 500
