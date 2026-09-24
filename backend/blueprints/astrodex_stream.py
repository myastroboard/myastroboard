"""Astrodex Stream Blueprint. Routes: /api/astrodex/stream/*, /api/connectors/astrodex_stream/rotate

Serves the "current frame" of a user's (or the shared) Astrodex slideshow as a single JPEG -
see backend/observation/astrodex_stream.py for the rendering engine and
docs/ASTRODEX_STREAM.md for the design rationale (this is deliberately not a real video
stream).

- ``/urls`` is browser-facing (session cookie): drives the Astrodex page's stream modal.
- ``/<user_id>/<token>/current.jpg`` and ``/shared/<token>/current.jpg`` are cookieless -
  polled by Home Assistant's Generic Camera integration or a plain ``<img>`` tag,
  authenticated by the HMAC token embedded in the URL rather than a session. Same
  sliding-window rate-limit shape as connectors_myastroshine.py's cookieless endpoints.
- ``/rotate`` (admin-only) issues a new signing secret, invalidating every URL handed out so
  far - the only revocation mechanism for a leaked personal URL.
"""

import time
from collections import deque
from threading import Lock

from flask import Blueprint, Response, jsonify, request

from connectors.astrodex_stream_connector import AstrodexStreamConnector
from observation import astrodex_stream
from utils.auth import admin_required, get_current_user, login_required
from utils.logging_config import get_logger
from utils.repo_config import load_config

logger = get_logger(__name__)

astrodex_stream_bp = Blueprint('astrodex_stream', __name__)

_RATE_LIMIT = 120
_RATE_WINDOW_SECONDS = 60
_rate_lock = Lock()
_rate_hits: dict = {}


def _rate_limited(client_key: str) -> bool:
    now = time.time()
    with _rate_lock:
        hits = _rate_hits.setdefault(client_key, deque())
        while hits and hits[0] <= now - _RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _RATE_LIMIT:
            return True
        hits.append(now)
        if len(_rate_hits) > 512:
            for key in [k for k, v in _rate_hits.items() if not v]:
                _rate_hits.pop(key, None)
        return False


def _client_key(*parts: str) -> str:
    return "|".join((request.remote_addr or 'unknown', *parts))


def _connector_block() -> dict:
    config = load_config()
    return (config.get('connectors') or {}).get(AstrodexStreamConnector.name) or {}


def _connector_config() -> dict:
    """This connector's CONFIG_FIELDS, defaults overlaid with whatever was saved."""
    block = _connector_block()
    merged = dict(AstrodexStreamConnector.CONFIG_FIELDS)
    merged.update({k: v for k, v in block.items() if k in AstrodexStreamConnector.CONFIG_FIELDS})
    return merged


def _enabled() -> bool:
    return AstrodexStreamConnector(_connector_block()).is_enabled()


def _not_found():
    return jsonify({'error': 'not found'}), 404


@astrodex_stream_bp.route('/api/astrodex/stream/urls', methods=['GET'])
@login_required
def get_stream_urls():
    user = get_current_user()
    if not user:  # pragma: no cover
        return jsonify({'error': 'User not authenticated'}), 401
    if not _enabled():
        return jsonify({'enabled': False})

    config = load_config()
    private_mode = bool(config.get('astrodex', {}).get('private', False))
    base = request.host_url.rstrip('/')
    personal_token = astrodex_stream.personal_token(user.user_id)
    payload = {
        'enabled': True,
        'personal_url': f"{base}/api/astrodex/stream/{user.user_id}/{personal_token}/current.jpg",
        'shared_url': None,
    }
    if not private_mode:
        payload['shared_url'] = f"{base}/api/astrodex/stream/shared/{astrodex_stream.shared_token()}/current.jpg"
    return jsonify(payload)


@astrodex_stream_bp.route('/api/astrodex/stream/<user_id>/<token>/current.jpg', methods=['GET'])
def personal_stream(user_id, token):
    if not _enabled():
        return _not_found()
    if not astrodex_stream.verify_personal_token(user_id, token):
        return _not_found()
    if _rate_limited(_client_key('personal', user_id)):
        return jsonify({'error': 'rate limited'}), 429
    data = astrodex_stream.personal_frame(user_id, _connector_config())
    return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})


@astrodex_stream_bp.route('/api/astrodex/stream/shared/<token>/current.jpg', methods=['GET'])
def shared_stream(token):
    if not _enabled():
        return _not_found()
    config = load_config()
    if bool(config.get('astrodex', {}).get('private', False)):
        return _not_found()
    if not astrodex_stream.verify_shared_token(token):
        return _not_found()
    if _rate_limited(_client_key('shared')):
        return jsonify({'error': 'rate limited'}), 429
    data = astrodex_stream.shared_frame(_connector_config())
    return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})


@astrodex_stream_bp.route('/api/connectors/astrodex_stream/rotate', methods=['POST'])
@admin_required
def rotate_stream_keys():
    try:
        astrodex_stream.rotate_signing_secret()
    except RuntimeError as exc:
        logger.error(f"Astrodex Stream: rotate failed: {exc}")
        return jsonify({'error': 'Failed to rotate keys'}), 500
    return jsonify({'status': 'success'})
