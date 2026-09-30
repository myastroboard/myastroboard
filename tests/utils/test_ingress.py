"""Home Assistant ingress support (utils/ingress.py): middleware, session cookie, base URL.

The middleware is only wired in app.py when MYASTROBOARD_HA_INGRESS is set, so the Flask
level tests wrap ``app.wsgi_app`` themselves and send requests the way the Supervisor does.
"""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from utils import app_settings
from utils import ingress

PREFIX = '/api/hassio_ingress/tok3n-XyZ'
SUPERVISOR = {'REMOTE_ADDR': ingress.SUPERVISOR_IP}
INGRESS_HEADERS = {
    'X-Ingress-Path': PREFIX,
    'X-Forwarded-For': '203.0.113.7, 172.30.32.1',
    'X-Forwarded-Proto': 'https',
    'X-Forwarded-Host': 'ha.example.org',
}


def _run(environ, proxy_ip=None):
    """Pass ``environ`` through the middleware and return what the wrapped app received."""
    seen = {}

    def inner(env, start_response):
        seen.update(env)
        return [b'']

    base = {'REMOTE_ADDR': '127.0.0.1', 'PATH_INFO': '/api/x', 'SCRIPT_NAME': '', 'wsgi.url_scheme': 'http'}
    base.update(environ)
    ingress.IngressMiddleware(inner, proxy_ip=proxy_ip)(base, lambda *a: None)
    return seen


def _supervisor_environ(**extra):
    env = {
        'REMOTE_ADDR': ingress.SUPERVISOR_IP,
        'HTTP_X_INGRESS_PATH': PREFIX,
        'HTTP_X_FORWARDED_FOR': '203.0.113.7, 172.30.32.1',
        'HTTP_X_FORWARDED_PROTO': 'https',
        'HTTP_X_FORWARDED_HOST': 'ha.example.org',
        'HTTP_HOST': 'a0d7b954-myastroboard:5000',
    }
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class TestMiddleware:

    def test_request_without_ingress_header_is_untouched(self):
        seen = _run({'HTTP_X_FORWARDED_FOR': '198.51.100.1'})
        assert seen['SCRIPT_NAME'] == ''
        assert seen['REMOTE_ADDR'] == '127.0.0.1'
        # Left for ProxyFix (trust_proxy_headers) to handle, as before
        assert seen['HTTP_X_FORWARDED_FOR'] == '198.51.100.1'
        assert 'myastroboard.ingress' not in seen

    def test_supervisor_request_gets_prefix_client_ip_scheme_and_host(self):
        seen = _run(_supervisor_environ())
        assert seen['SCRIPT_NAME'] == PREFIX
        assert seen['PATH_INFO'] == '/api/x'
        assert seen['REMOTE_ADDR'] == '203.0.113.7'
        assert seen['wsgi.url_scheme'] == 'https'
        assert seen['HTTP_HOST'] == 'ha.example.org'
        assert seen['myastroboard.ingress'] is True

    def test_forwarded_headers_are_consumed(self):
        """An inner ProxyFix must not re-apply them and swap the client IP for the HA core hop."""
        seen = _run(_supervisor_environ(HTTP_X_FORWARDED_PREFIX='/evil'))
        for key in (
            'HTTP_X_INGRESS_PATH',
            'HTTP_X_FORWARDED_FOR',
            'HTTP_X_FORWARDED_PROTO',
            'HTTP_X_FORWARDED_HOST',
            'HTTP_X_FORWARDED_PREFIX',
        ):
            assert key not in seen

    def test_ingress_header_from_another_address_is_stripped_and_ignored(self):
        """On the directly published port anyone can send X-Ingress-Path."""
        seen = _run(_supervisor_environ(REMOTE_ADDR='192.168.1.50'))
        assert seen['SCRIPT_NAME'] == ''
        assert seen['REMOTE_ADDR'] == '192.168.1.50'
        assert 'HTTP_X_INGRESS_PATH' not in seen
        assert 'myastroboard.ingress' not in seen

    @pytest.mark.parametrize('prefix', ['relative/path', '/a//b', '/a/<script>', '/a b', ''])
    def test_malformed_prefix_is_ignored(self, prefix):
        seen = _run(_supervisor_environ(HTTP_X_INGRESS_PATH=prefix))
        assert seen['SCRIPT_NAME'] == ''
        assert 'myastroboard.ingress' not in seen

    def test_trailing_slash_is_dropped_from_the_prefix(self):
        seen = _run(_supervisor_environ(HTTP_X_INGRESS_PATH=PREFIX + '/'))
        assert seen['SCRIPT_NAME'] == PREFIX

    def test_prefix_forwarded_in_the_path_is_stripped(self):
        seen = _run(_supervisor_environ(PATH_INFO=PREFIX + '/api/x'))
        assert seen['PATH_INFO'] == '/api/x'

    def test_invalid_forwarded_proto_keeps_the_scheme(self):
        seen = _run(_supervisor_environ(HTTP_X_FORWARDED_PROTO='gopher'))
        assert seen['wsgi.url_scheme'] == 'http'

    def test_missing_forwarded_for_keeps_the_supervisor_address(self):
        env = _supervisor_environ()
        del env['HTTP_X_FORWARDED_FOR']
        assert _run(env)['REMOTE_ADDR'] == ingress.SUPERVISOR_IP

    def test_trusted_proxy_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv(ingress.INGRESS_PROXY_ENV, '127.0.0.1')
        assert ingress.trusted_proxy_ip() == '127.0.0.1'
        seen = _run(_supervisor_environ(REMOTE_ADDR='127.0.0.1'), proxy_ip=ingress.trusted_proxy_ip())
        assert seen['SCRIPT_NAME'] == PREFIX


class TestClientIp:

    @pytest.mark.parametrize(
        'forwarded, expected',
        [
            ('203.0.113.7, 172.30.32.1', '203.0.113.7'),
            # Everything left of the hop HA core appended can be spoofed by the browser
            ('6.6.6.6, 203.0.113.7, 172.30.32.1', '203.0.113.7'),
            ('2001:db8::1, 172.30.33.5', '2001:db8::1'),
            ('203.0.113.7, not-an-ip, 172.30.32.1', '203.0.113.7'),
            ('172.30.32.1, 172.30.32.2', None),
            ('', None),
        ],
    )
    def test_rightmost_hop_outside_the_hassio_network(self, forwarded, expected):
        assert ingress._client_ip(forwarded) == expected


class TestEnabledFlag:

    @pytest.mark.parametrize('value, expected', [('1', True), ('true', True), ('ON', True), ('0', False), ('', False)])
    def test_flag_values(self, monkeypatch, value, expected):
        monkeypatch.setenv(ingress.INGRESS_ENV_FLAG, value)
        assert ingress.ingress_enabled() is expected

    def test_unset_flag_is_disabled(self, monkeypatch):
        monkeypatch.delenv(ingress.INGRESS_ENV_FLAG, raising=False)
        assert ingress.ingress_enabled() is False


# ---------------------------------------------------------------------------
# Through the real Flask app
# ---------------------------------------------------------------------------


@pytest.fixture
def flask_app(monkeypatch):
    from app import app as _flask_app

    _flask_app.config['TESTING'] = True
    monkeypatch.setattr(_flask_app, 'wsgi_app', ingress.IngressMiddleware(_flask_app.wsgi_app))
    return _flask_app


@pytest.fixture
def ingress_client(flask_app):
    with flask_app.test_client() as c:
        yield c


class TestPagesUnderIngress:

    def test_login_page_prefixes_assets_and_skips_the_pwa_manifest(self, ingress_client):
        resp = ingress_client.get('/login', headers=INGRESS_HEADERS, environ_base=SUPERVISOR)
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert f'href="{PREFIX}/static/css/bs_main.css' in html
        assert f'src="{PREFIX}/static/js/api_helper.js' in html
        assert f'action="{PREFIX}/api/auth/login"' in html
        assert f'<meta name="app-base" content="{PREFIX}">' in html
        assert 'rel="manifest"' not in html
        assert '"/static/' not in html

    def test_login_page_without_ingress_is_unchanged(self, ingress_client):
        """Plain Docker installs: root-relative URLs, PWA manifest, empty base."""
        html = ingress_client.get('/login').get_data(as_text=True)
        assert 'href="/static/css/bs_main.css' in html
        assert 'rel="manifest"' in html
        assert '<meta name="app-base" content="">' in html

    def test_unauthenticated_root_redirects_inside_the_prefix(self, ingress_client):
        resp = ingress_client.get('/', headers=INGRESS_HEADERS, environ_base=SUPERVISOR)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'{PREFIX}/login')

    def test_dashboard_under_ingress_prefixes_assets(self, flask_app):
        from utils.auth import user_manager

        user = user_manager.get_user_by_username('admin')
        assert user is not None
        with flask_app.test_client() as c:
            with c.session_transaction(environ_overrides={'myastroboard.ingress': True, 'SCRIPT_NAME': PREFIX}) as sess:
                sess['user_id'] = user.user_id
                sess['username'] = user.username
                sess['role'] = user.role
            resp = c.get(PREFIX + '/', headers=INGRESS_HEADERS, environ_base=SUPERVISOR)
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert f'src="{PREFIX}/static/js/app.js' in html
        assert 'id="pwa-manifest"' not in html
        assert '"/static/' not in html


class TestSessionCookie:

    def test_ingress_cookie_has_its_own_name_and_the_prefix_as_path(self, flask_app):
        with flask_app.test_request_context(environ_overrides={'myastroboard.ingress': True, 'SCRIPT_NAME': PREFIX}):
            assert flask_app.session_interface.get_cookie_name(flask_app) == ingress.INGRESS_SESSION_COOKIE_NAME
            assert flask_app.session_interface.get_cookie_path(flask_app) == PREFIX

    def test_direct_access_keeps_the_flask_defaults(self, flask_app):
        """No forced re-login for existing Docker installs."""
        with flask_app.test_request_context():
            assert flask_app.session_interface.get_cookie_name(flask_app) == 'session'
            assert flask_app.session_interface.get_cookie_path(flask_app) == '/'

    def test_login_sets_the_prefixed_cookie(self, ingress_client):
        from utils.auth import user_manager

        username = 'ingress_cookie_user'
        if not user_manager.get_user_by_username(username):
            user_manager.create_user(username, 'password123', 'user')
        resp = ingress_client.post(
            '/api/auth/login',
            json={'username': username, 'password': 'password123'},
            headers=INGRESS_HEADERS,
            environ_base=SUPERVISOR,
        )
        assert resp.status_code == 200
        cookies = [h for h in resp.headers.getlist('Set-Cookie') if h.startswith('myastroboard_session=')]
        assert cookies and f'Path={PREFIX}' in cookies[0]


class TestClientIpReachesTheApp:

    def test_failed_login_is_counted_against_the_real_client(self, ingress_client):
        """One ingress user's failed logins must not lock out every other ingress user."""
        from blueprints import auth as auth_bp_module

        ingress_client.post(
            '/api/auth/login',
            json={'username': 'nobody_here', 'password': 'wrong'},
            headers=INGRESS_HEADERS,
            environ_base=SUPERVISOR,
        )
        keys = set(auth_bp_module._login_failures_by_ip._events)
        assert '203.0.113.7' in keys
        assert ingress.SUPERVISOR_IP not in keys


# ---------------------------------------------------------------------------
# External base URL
# ---------------------------------------------------------------------------


class TestExternalBaseUrl:

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        self.saved = {}
        monkeypatch.setattr(app_settings, 'get_app_settings', lambda: dict(self.saved))

    def test_setting_wins(self, flask_app):
        self.saved['external_base_url'] = 'https://astro.example.org/'
        with flask_app.test_request_context(environ_overrides={'myastroboard.ingress': True}):
            assert ingress.external_base_url() == 'https://astro.example.org'

    def test_ingress_without_setting_has_no_usable_address(self, flask_app):
        with flask_app.test_request_context(environ_overrides={'myastroboard.ingress': True, 'SCRIPT_NAME': PREFIX}):
            assert ingress.external_base_url() is None

    def test_direct_access_falls_back_to_the_request_address(self, flask_app):
        with flask_app.test_request_context(base_url='http://192.168.1.9:5000/sub'):
            assert ingress.external_base_url() == 'http://192.168.1.9:5000/sub'

    @pytest.mark.parametrize(
        'value, expected',
        [
            ('', ''),
            ('   ', ''),
            (None, ''),
            ('https://astro.example.org/', 'https://astro.example.org'),
            ('http://192.168.1.9:5000/board', 'http://192.168.1.9:5000/board'),
            ('ftp://example.org', None),
            ('example.org', None),
            ('https://example.org/?x=1', None),
            ('https://user:pw@example.org', None),
            ('http://example.org:99999', None),
        ],
    )
    def test_normalize(self, value, expected):
        assert app_settings.normalize_external_base_url(value) == expected


class TestAdminSetting:

    @pytest.fixture(autouse=True)
    def _store(self, monkeypatch):
        self.saved = {}
        monkeypatch.setattr(app_settings, 'get_app_settings', lambda: dict(self.saved))
        monkeypatch.setattr(app_settings, 'save_app_settings', lambda s: self.saved.update(s))

    def test_valid_url_is_saved_normalized(self, client_admin):
        resp = client_admin.post('/api/admin/app-settings', json={'external_base_url': 'https://astro.example.org/'})
        assert resp.status_code == 200
        assert self.saved['external_base_url'] == 'https://astro.example.org'
        assert (
            client_admin.get('/api/admin/app-settings').get_json()['external_base_url'] == 'https://astro.example.org'
        )

    def test_invalid_url_is_rejected(self, client_admin):
        resp = client_admin.post('/api/admin/app-settings', json={'external_base_url': 'javascript:alert(1)'})
        assert resp.status_code == 400
        assert self.saved == {}
