"""Tests for utils.user_identity - display name, profile record, avatar processing."""

import io
import types

import pytest
from PIL import Image

from utils import user_identity
from utils.user_identity import ProfileError


def _user(**profile):
    return types.SimpleNamespace(user_id='u-1', username='alice', profile=profile or None)


def _image_bytes(fmt='PNG', size=(300, 200), mode='RGB', exif=None):
    buffer = io.BytesIO()
    image = Image.new(mode, size, (10, 120, 200) if mode == 'RGB' else (10, 120, 200, 128))
    kwargs = {'exif': exif} if exif is not None else {}
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


class TestSanitizeProfile:
    def test_defaults_are_private(self):
        profile = user_identity.sanitize_profile(None)
        assert profile['display_name'] is None
        assert profile['community']['listed'] is False
        assert profile['community']['show_equipment'] is False

    def test_junk_values_fall_back_to_defaults(self):
        profile = user_identity.sanitize_profile(
            {
                'display_name': 'x' * 99,
                'bio': 42,
                'avatar': {'filename': '../../etc/passwd'},
                'community': {'listed': 'yes', 'show_stats': False, 'unknown': True},
            }
        )
        assert profile['display_name'] is None
        assert profile['bio'] == ''
        assert profile['avatar'] is None
        assert profile['community']['listed'] is False
        assert profile['community']['show_stats'] is False
        assert 'unknown' not in profile['community']

    def test_valid_avatar_is_kept(self):
        avatar = {'filename': 'u-1_avatar_0123456789abcdef.webp', 'updated_at': '2026-01-01'}
        assert user_identity.sanitize_profile({'avatar': avatar})['avatar'] == avatar

    def test_long_stored_bio_is_truncated(self):
        assert len(user_identity.sanitize_profile({'bio': 'y' * 500})['bio']) == user_identity.BIO_MAX_LENGTH


class TestDisplayName:
    @pytest.mark.parametrize(
        ('raw', 'expected'),
        # NFC: a combining accent is folded into the precomposed letter
        [('  Sam   Lee ', 'Sam Lee'), ('', None), ('   ', None), (None, None), ('Aná', 'Aná')],
    )
    def test_normalization(self, raw, expected):
        assert user_identity.normalize_display_name(raw) == expected

    @pytest.mark.parametrize('raw', ['bad\x00name', 'zero​width', 'x' * 41, 7])
    def test_rejections(self, raw):
        with pytest.raises(ProfileError):
            user_identity.normalize_display_name(raw)

    def test_falls_back_to_login_name(self):
        assert user_identity.display_name_of(_user()) == 'alice'
        assert user_identity.display_name_of(_user(display_name='Alice A.')) == 'Alice A.'
        assert user_identity.display_name_of({'username': 'bob', 'profile': None}) == 'bob'


class TestApplyProfileUpdate:
    def test_partial_update_keeps_the_rest(self):
        start = user_identity.sanitize_profile({'display_name': 'Sam', 'bio': 'Hello'})
        updated = user_identity.apply_profile_update(start, {'community': {'listed': True, 'bogus': 1}})
        assert updated['display_name'] == 'Sam'
        assert updated['bio'] == 'Hello'
        assert updated['community']['listed'] is True

    def test_bio_cleanup(self):
        updated = user_identity.apply_profile_update({}, {'bio': 'a\r\n\r\n\r\n\r\nb\x07  \n'})
        assert updated['bio'] == 'a\n\nb'
        assert user_identity.apply_profile_update({}, {'bio': None})['bio'] == ''

    @pytest.mark.parametrize(
        'updates',
        ['nope', {'bio': 3}, {'bio': 'z' * 281}, {'community': []}, {'community': {'listed': 1}}],
    )
    def test_invalid_updates(self, updates):
        with pytest.raises(ProfileError):
            user_identity.apply_profile_update({}, updates)


class TestVisibility:
    def test_blocks_need_the_member_to_be_listed(self):
        assert not user_identity.shows_block(_user(community={'show_stats': True}), 'stats')
        assert user_identity.shows_block(_user(community={'listed': True}), 'stats')
        assert not user_identity.shows_block(_user(community={'listed': True}), 'equipment')
        assert user_identity.is_listed(_user(community={'listed': True}))

    @pytest.mark.parametrize(
        ('config', 'expected'),
        [({}, True), ({'community': {'enabled': False}}, False), ({'community': 'junk'}, True), (None, True)],
    )
    def test_admin_switch(self, config, expected):
        assert user_identity.community_enabled(config) is expected

    def test_public_identity(self):
        identity = user_identity.public_identity(_user(display_name='Sam'))
        assert identity['display_name'] == 'Sam'
        assert identity['has_avatar'] is False
        assert identity['avatar_url'].startswith('/api/users/u-1/avatar?v=')

    def test_avatar_url_changes_with_the_picture(self):
        first = user_identity.avatar_url(_user(avatar={'filename': 'u-1_avatar_0123456789abcdef.webp'}))
        second = user_identity.avatar_url(_user(avatar={'filename': 'u-1_avatar_fedcba9876543210.webp'}))
        assert first.endswith('v=0123456789abcdef')
        assert first != second


class TestAvatarProcessing:
    @pytest.mark.parametrize(('fmt', 'mode'), [('PNG', 'RGB'), ('PNG', 'RGBA'), ('JPEG', 'RGB'), ('WEBP', 'RGB')])
    def test_output_is_a_square_webp_without_metadata(self, fmt, mode):
        exif = Image.Exif()
        exif[0x010F] = 'CameraMaker'
        data = _image_bytes(fmt, mode=mode, exif=exif if fmt == 'JPEG' else None)
        output = user_identity.process_avatar(data)
        with Image.open(io.BytesIO(output)) as image:
            assert image.format == 'WEBP'
            assert image.size == (user_identity.AVATAR_SIZE, user_identity.AVATAR_SIZE)
            assert not image.info.get('exif')

    def test_rejects_garbage_and_empty(self):
        with pytest.raises(ProfileError):
            user_identity.process_avatar(b'not an image')
        with pytest.raises(ProfileError):
            user_identity.process_avatar(b'')

    def test_rejects_oversized_files_and_pictures(self, monkeypatch):
        monkeypatch.setattr(user_identity, 'AVATAR_MAX_UPLOAD_BYTES', 10)
        with pytest.raises(ProfileError) as raised:
            user_identity.process_avatar(_image_bytes())
        assert raised.value.key == 'profile.error_avatar_too_large'
        monkeypatch.setattr(user_identity, 'AVATAR_MAX_UPLOAD_BYTES', 10_000_000)
        monkeypatch.setattr(user_identity, 'AVATAR_MAX_PIXELS', 100)
        with pytest.raises(ProfileError) as raised:
            user_identity.process_avatar(_image_bytes())
        assert raised.value.key == 'profile.error_avatar_too_large'


class TestAvatarFiles:
    def test_store_and_remove(self, tmp_path, monkeypatch):
        monkeypatch.setattr(user_identity, 'AVATARS_DIR', str(tmp_path))
        filename = user_identity.store_avatar('u-1', b'data')
        assert user_identity.is_avatar_filename(filename)
        assert (tmp_path / filename).read_bytes() == b'data'
        user_identity.remove_avatar_file(filename)
        assert not (tmp_path / filename).exists()
        # Missing and foreign names are ignored
        user_identity.remove_avatar_file(filename)
        user_identity.remove_avatar_file('../secret.webp')
        user_identity.remove_avatar_file(None)

    def test_store_rejects_a_malformed_user_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(user_identity, 'AVATARS_DIR', str(tmp_path))
        with pytest.raises(ProfileError):
            user_identity.store_avatar('../x', b'data')

    def test_avatar_path_refuses_foreign_names(self):
        assert user_identity.avatar_path('../../etc/passwd') is None
        assert user_identity.avatar_path('u-1_avatar_0123456789abcdef.webp').endswith('.webp')

    def test_remove_logs_os_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(user_identity, 'AVATARS_DIR', str(tmp_path))
        filename = user_identity.store_avatar('u-1', b'data')

        def refuse(_path):
            raise PermissionError('locked')

        monkeypatch.setattr(user_identity.os, 'remove', refuse)
        user_identity.remove_avatar_file(filename)


class TestInitials:
    @pytest.mark.parametrize(
        ('name', 'initials'), [('Sam Lee', 'SL'), ('vega', 'VE'), ('jean-luc picard', 'JL'), ('', 'AL')]
    )
    def test_letters(self, name, initials):
        svg = user_identity.initials_svg(_user(display_name=name or None)).decode('utf-8')
        assert f'>{initials}<' in svg

    def test_markup_is_escaped(self):
        svg = user_identity.initials_svg(_user(display_name='<a b')).decode('utf-8')
        assert '&lt;' in svg
        assert '<a' not in svg.replace('<svg', '').replace('<circle', '').replace('<text', '')
