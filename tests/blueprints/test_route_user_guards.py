"""A session whose account no longer exists, against every API route.

A session can outlive its account: the account was deleted by an admin, or replaced by a backup
restore, while the browser kept its cookie. The auth decorators (``login_required``,
``user_required``, ``admin_required``) sign such a session out: every route that needs a sign-in
answers 401 and clears it, so it never reads install data nor reaches a route that expects a user.

This walks the live URL map, so a route added later is covered without editing this file.
"""

import re

import pytest

from app import app as flask_app

# Public routes (no sign-in required): they answer the same with or without a session. The
# Astrodex stream and MyAstroShine integration routes authenticate with a token, not a session.
_PUBLIC_ENDPOINTS = {
    'astrodex_stream.personal_stream',
    'astrodex_stream.shared_stream',
    'auth.auth_status',
    'auth.login',
    'auth.logout',
    'auth.verify_login_2fa',
    'connectors_myastroshine.integration_enhanced_api',
    'connectors_myastroshine.integration_source_api',
    'connectors_myastroshine.integration_source_image_api',
    'misc.health_api',
    'push.get_vapid_public_key',
}


def _api_calls():
    """(method, url, endpoint) for every API route, path parameters filled with dummies."""
    calls = []
    for rule in flask_app.url_map.iter_rules():
        if not rule.rule.startswith('/api/'):
            continue
        url = re.sub(r'<(int:)?[^>]+>', lambda m: '1' if m.group(1) else 'x1', rule.rule)
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            calls.append((method, url, rule.endpoint))
    return calls


_CALLS = _api_calls()


@pytest.fixture
def deleted_account_client():
    """A client signed in as an account that does not exist (deleted after sign-in)."""
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 'deleted-user-id'
            sess['username'] = 'deleted-account'
            sess['role'] = 'user'
        yield c


def test_the_route_list_is_not_empty():
    """Guard against a URL map that silently stopped matching: the walk must see the API."""
    assert len(_CALLS) > 200


def test_every_public_endpoint_still_exists():
    """A renamed public route must be renamed here too, or its successor would be skipped silently."""
    assert _PUBLIC_ENDPOINTS <= {endpoint for _m, _u, endpoint in _CALLS}


@pytest.mark.parametrize('method, url, endpoint', _CALLS, ids=[f'{m} {u}' for m, u, _e in _CALLS])
def test_a_session_without_its_account_is_signed_out(deleted_account_client, method, url, endpoint):
    """Every route that needs a sign-in answers 401 and clears the session; public routes still answer."""
    resp = deleted_account_client.open(url, method=method, json={})

    assert resp.status_code < 500, f'{method} {url} crashed for a session without account'
    if endpoint in _PUBLIC_ENDPOINTS:
        return
    assert resp.status_code == 401, f'{method} {url} answered {resp.status_code}'
    with deleted_account_client.session_transaction() as sess:
        assert 'username' not in sess, f'{method} {url} kept the session of a missing account'
