"""The operator's privacy notice and the cleanup of older pictures (App settings -> Configuration).

Covers the admin settings route, the public /privacy page, the links on the login page and in
the app, and the picture metadata cleanup route.
"""

import sys
import types

import pytest

from utils import app_settings
from utils.auth import user_manager

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import admin as admin_module


def _login(test_client, username):
    user = user_manager.get_user_by_username(username) or user_manager.create_user(username, f'{username}-pw', 'user')
    with test_client.session_transaction() as session:
        session['user_id'] = user.user_id
        session['username'] = user.username
        session['role'] = user.role


@pytest.fixture
def client():
    app.config['TESTING'] = True
    saved = dict(app_settings.get_app_settings())
    with app.test_client() as test_client:
        yield test_client
    app_settings.save_app_settings(saved)


def _set_notice(url='', text=''):
    settings = dict(app_settings.get_app_settings())
    settings.update({'privacy_notice_url': url, 'privacy_notice_text': text})
    app_settings.save_app_settings(settings)


class TestAdminSettings:
    def test_round_trip(self, client):
        _login(client, 'admin')
        response = client.post(
            '/api/admin/app-settings',
            json={'privacy_notice_url': ' https://club.example.org/privacy ', 'privacy_notice_text': 'Hello\r\nworld'},
        )
        assert response.status_code == 200
        payload = client.get('/api/admin/app-settings').get_json()
        assert payload['privacy_notice_url'] == 'https://club.example.org/privacy'
        assert payload['privacy_notice_text'] == 'Hello\nworld'
        assert payload['privacy_notice_text_max_length'] == app_settings.PRIVACY_NOTICE_TEXT_MAX_LENGTH

    @pytest.mark.parametrize(
        ('body', 'key'),
        [
            ({'privacy_notice_url': 'javascript:alert(1)'}, 'settings.privacy_notice_url_invalid'),
            ({'privacy_notice_text': 'x' * 20001}, 'settings.privacy_notice_text_too_long'),
        ],
    )
    def test_invalid_values_are_refused(self, client, body, key):
        _login(client, 'admin')
        response = client.post('/api/admin/app-settings', json=body)
        assert response.status_code == 400
        assert response.get_json()['error_key'] == key

    def test_other_settings_keep_the_notice(self, client):
        _set_notice(text='Kept')
        _login(client, 'admin')
        client.post('/api/admin/app-settings', json={'search_engine_indexing': False})
        assert app_settings.get_privacy_notice()['text'] == 'Kept'


class TestPrivacyPage:
    def test_not_found_when_unset(self, client):
        _set_notice()
        assert client.get('/privacy').status_code == 404

    def test_redirects_to_the_operator_address(self, client):
        _set_notice(url='https://club.example.org/privacy', text='ignored')
        response = client.get('/privacy')
        assert response.status_code == 302
        assert response.headers['Location'] == 'https://club.example.org/privacy'

    def test_text_is_public_and_escaped(self, client):
        _set_notice(text='Controller: Club <script>alert(1)</script>\nContact: board@club.example')
        response = client.get('/privacy')
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert '&lt;script&gt;' in body and '<script>alert' not in body
        assert 'Contact: board@club.example' in body
        assert 'noindex' in body
        assert '/login' in body

    def test_signed_in_member_gets_back_to_the_app(self, client):
        _set_notice(text='Notice')
        _login(client, 'privacy-reader')
        body = client.get('/privacy').get_data(as_text=True)
        assert 'privacy_notice.back_to_app' in body


class TestLinks:
    def test_login_page_links_the_notice_only_when_set(self, client):
        _set_notice()
        assert 'privacy_notice.link' not in client.get('/login').get_data(as_text=True)
        _set_notice(text='Notice')
        assert 'href="/privacy"' in client.get('/login').get_data(as_text=True)

    def test_external_address_opens_in_a_new_tab(self, client):
        _set_notice(url='https://club.example.org/privacy')
        body = client.get('/login').get_data(as_text=True)
        assert 'href="https://club.example.org/privacy" target="_blank" rel="noopener noreferrer"' in body

    def test_app_footer_and_your_data(self, client):
        _set_notice(text='Notice')
        _login(client, 'admin')
        body = client.get('/').get_data(as_text=True)
        assert body.count('href="/privacy"') == 2

    def test_a_settings_error_never_breaks_a_page(self, client, monkeypatch):
        def broken(_base=''):
            raise RuntimeError('db down')

        monkeypatch.setattr(app_settings, 'privacy_notice_link', broken)
        assert client.get('/login').status_code == 200


class TestStripPictureMetadata:
    def test_requires_admin(self, client):
        _login(client, 'privacy-member')
        assert client.post('/api/admin/privacy/strip-picture-metadata', json={}).status_code == 403

    @pytest.mark.parametrize(('body', 'dry_run'), [({'dry_run': True}, True), ({}, False), ({'dry_run': 'yes'}, False)])
    def test_runs_over_every_per_user_directory(self, client, monkeypatch, tmp_path, body, dry_run):
        seen = {}

        def fake_strip(directories, dry_run=False):
            seen['directories'], seen['dry_run'] = directories, dry_run
            return {'scanned': 2, 'cleaned': 1, 'unchanged': 1, 'failed': 0}

        monkeypatch.setattr(admin_module, 'strip_stored_pictures', fake_strip)
        monkeypatch.setattr(admin_module, 'DATA_DIR', str(tmp_path))
        _login(client, 'admin')
        payload = client.post('/api/admin/privacy/strip-picture-metadata', json=body).get_json()
        assert payload == {
            'status': 'success',
            'dry_run': dry_run,
            'scanned': 2,
            'cleaned': 1,
            'unchanged': 1,
            'failed': 0,
        }
        assert seen['dry_run'] is dry_run
        assert len(seen['directories']) >= 3

    def test_failure_is_a_500(self, client, monkeypatch, tmp_path):
        def broken(directories, dry_run=False):
            raise RuntimeError('disk')

        monkeypatch.setattr(admin_module, 'strip_stored_pictures', broken)
        monkeypatch.setattr(admin_module, 'DATA_DIR', str(tmp_path))
        _login(client, 'admin')
        assert client.post('/api/admin/privacy/strip-picture-metadata', json={}).status_code == 500
