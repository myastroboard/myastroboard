"""MyAstroShine integration Blueprint. Routes: /api/astrodex/integration/*

The AstroDex <-> MyAstroShine image round-trip (see docs/MYASTROSHINE.md):

- ``/status`` / ``/config`` / ``/test`` - browser-facing (session cookie), drive
  the connector card in Parameters -> Connectors and the "Send to MyAstroShine"
  button in AstroDex.
- ``/handoff`` - browser-facing, mints the signed single-use token the browser
  carries to MyAstroShine.
- ``/source`` / ``/source/image`` / ``/enhanced`` - **no session cookie**: called
  server-to-server by the MyAstroShine container, authenticated by the handoff
  token (and, for ``/enhanced``, an additional HMAC webhook signature). The
  handoff signature is checked first, in constant time, before any disk access.
"""

import ipaddress
import json
import socket
import time
from collections import deque
from threading import Lock
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request, send_file

from observation import astrodex
from observation import myastroshine_integration as integration
from utils.auth import admin_required, get_current_user, login_required, user_required
from utils.constants import (
    MYASTROSHINE_ENHANCED_RATE_LIMIT,
    MYASTROSHINE_ENHANCED_RATE_WINDOW_SECONDS,
    MYASTROSHINE_MAX_IMAGE_BYTES,
    MYASTROSHINE_MIN_VERSION,
)
from utils.logging_config import get_logger
from utils.repo_config import load_config, save_config

logger = get_logger(__name__)

myastroshine_bp = Blueprint('myastroshine_integration', __name__)

_SECRET_FIELDS = ('token', 'signing_secret')

# In-process sliding-window rate limit for the three cookieless endpoints.
_rate_lock = Lock()
_rate_hits: dict[str, deque] = {}


def _rate_limited(client_key: str) -> bool:
    """True when *client_key* has exceeded the cookieless-endpoint call budget."""
    now = time.time()
    window = MYASTROSHINE_ENHANCED_RATE_WINDOW_SECONDS
    with _rate_lock:
        hits = _rate_hits.setdefault(client_key, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= MYASTROSHINE_ENHANCED_RATE_LIMIT:
            return True
        hits.append(now)
        # Opportunistically drop idle buckets so the map can't grow unbounded.
        if len(_rate_hits) > 512:
            for key in [k for k, v in _rate_hits.items() if not v]:
                _rate_hits.pop(key, None)
        return False


def _mask_secret(value: str) -> str:
    """Render a secret as '****' + its last 4 chars, or '' when unset."""
    if not value:
        return ''
    if len(value) <= 4:
        return '****'
    return f"****{value[-4:]}"


def _client_key() -> str:
    return request.remote_addr or 'unknown'


def _verify_handoff_or_none(token: str):
    """Return (cfg, claims) when *token* is a valid handoff, else (cfg, None)."""
    cfg = integration.get_integration_config()
    if not integration.integration_enabled(cfg):
        return cfg, None
    return cfg, integration.verify_handoff(cfg, token or '')


# ---------------------------------------------------------------------------
# Browser-facing (session cookie)
# ---------------------------------------------------------------------------


@myastroshine_bp.route('/api/astrodex/integration/status', methods=['GET'])
@login_required
def integration_status():
    """Whether the AstroDex "Send to MyAstroShine" button should be shown."""
    try:
        return jsonify({'enabled': integration.integration_enabled()})
    except Exception as exc:
        logger.error(f"Error reading MyAstroShine integration status: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/config', methods=['GET'])
@login_required
def get_integration_config_api():
    """Return the connector-card config with secrets masked (never the raw values)."""
    try:
        cfg = integration.get_integration_config()
        return jsonify(
            {
                'enabled': bool(cfg.get('enabled')),
                'label': cfg.get('label') or '',
                'url': cfg.get('url') or '',
                'callback_url_override': cfg.get('callback_url_override') or '',
                'copy_rating': bool(cfg.get('copy_rating')),
                'token': _mask_secret(cfg.get('token') or ''),
                'signing_secret': _mask_secret(cfg.get('signing_secret') or ''),
                'has_token': bool(cfg.get('token')),
                'has_signing_secret': bool(cfg.get('signing_secret')),
                'effective_enabled': integration.integration_enabled(cfg),
                # MyAstroShine is not a BaseConnector, but its card renders the same
                # "appears in" badges — it surfaces inside the AstroDex tab, not Observatory —
                # and the same "Requires <version>" line as a BaseConnector's min_version.
                'target_modules': ['astrodex'],
                'min_version': MYASTROSHINE_MIN_VERSION,
            }
        )
    except Exception as exc:
        logger.error(f"Error reading MyAstroShine integration config: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/config', methods=['POST'])
@admin_required
def save_integration_config_api():
    """Persist the connector-card config. An empty secret field means "keep current"."""
    try:
        payload = request.get_json(silent=True) or {}
        config = load_config()
        connectors = config.setdefault('connectors', {})
        current = dict(connectors.get('myastroshine', {}) or {})

        if 'label' in payload:
            current['label'] = str(payload.get('label') or '').strip()
        if 'url' in payload:
            current['url'] = str(payload.get('url') or '').strip().rstrip('/')
        if 'callback_url_override' in payload:
            current['callback_url_override'] = str(payload.get('callback_url_override') or '').strip().rstrip('/')
        if 'copy_rating' in payload:
            current['copy_rating'] = bool(payload.get('copy_rating'))
        if 'enabled' in payload:
            current['enabled'] = bool(payload.get('enabled'))

        for field in _SECRET_FIELDS:
            if field in payload:
                incoming = str(payload.get(field) or '').strip()
                # Blank (or the masked placeholder echoed back) == keep the stored value.
                if incoming and not incoming.startswith('****'):
                    current[field] = incoming

        connectors['myastroshine'] = current
        if not save_config(config):
            return jsonify({'error': 'Failed to save configuration'}), 500

        return jsonify({'status': 'success', 'effective_enabled': integration.integration_enabled(current)})
    except Exception as exc:
        logger.error(f"Error saving MyAstroShine integration config: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/test', methods=['POST'])
@admin_required
def test_integration_api():
    """Best-effort server-side reachability probe against ``<url>/api/health``.

    MyAstroShine is LAN-only: an "unreachable" result is expected and normal
    when the board runs on a different network. The probe resolves the host and
    refuses loopback / link-local / unspecified / multicast targets, then hits
    the resolved IP directly (not the original hostname) to break the
    user-controlled data flow (SSRF / DNS-rebinding hardening) - same pattern as
    the AllSky connector test.
    """
    try:
        data = request.get_json(silent=True) or {}
        raw_url = (data.get('url') or '').strip().rstrip('/')
        if not raw_url:
            cfg = integration.get_integration_config()
            raw_url = (cfg.get('url') or '').strip().rstrip('/')
        if not raw_url:
            return jsonify({'reachable': False, 'error': 'url required'}), 400

        parsed = urlparse(raw_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return jsonify({'reachable': False, 'error': 'url must be a valid http(s) URL'}), 400

        try:
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            addrinfo = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            resolved_ip = str(addrinfo[0][4][0])
            ip_obj = ipaddress.ip_address(resolved_ip)
            if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_multicast:
                return jsonify({'reachable': False, 'error': 'url host is not allowed'}), 400
        except (socket.gaierror, ValueError):
            return jsonify({'reachable': False, 'error': 'unable to resolve host'}), 400

        safe_scheme = 'https' if parsed.scheme == 'https' else 'http'
        netloc = f"[{resolved_ip}]" if ':' in resolved_ip else resolved_ip
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        probe_url = f"{safe_scheme}://{netloc}/api/health"
        headers = {'Host': parsed.netloc} if parsed.netloc else {}

        try:
            resp = requests.get(probe_url, timeout=5, headers=headers, allow_redirects=False)
            reachable = resp.status_code < 500
        except requests.exceptions.RequestException:
            reachable = False
        return jsonify({'reachable': reachable})
    except Exception as exc:
        logger.error(f"Error testing MyAstroShine reachability: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/handoff', methods=['POST'])
@user_required
def mint_handoff_api():
    """Forge a signed single-use handoff token for one of the caller's own pictures."""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        item_id = str(data.get('item_id') or '').strip()
        picture_id = str(data.get('picture_id') or '').strip()
        # Strict uuid shape: these end up in the handoff token and, on the return
        # trip, in per-user Astrodex file paths (see _HANDOFF_ID_RE).
        if not (integration._is_handoff_id(item_id) and integration._is_handoff_id(picture_id)):
            return jsonify({'error': 'item_id and picture_id must be valid ids'}), 400

        cfg = integration.get_integration_config()
        if not integration.integration_enabled(cfg):
            return jsonify({'error': 'MyAstroShine integration is not configured'}), 403

        item = astrodex.get_astrodex_item(user_id, item_id)
        picture = None
        if item:
            picture = next((p for p in item.get('pictures', []) if p.get('id') == picture_id), None)
        if not item or not picture:
            # The lookup is scoped to the caller's own collection, so "not found"
            # already covers "not yours".
            return jsonify({'error': 'Item or picture not found'}), 404

        override = (cfg.get('callback_url_override') or '').strip()
        callback_base = override or request.url_root
        result = integration.mint_handoff(
            cfg, user_id=user_id, item_id=item_id, picture_id=picture_id, callback_base=callback_base
        )
        return jsonify(result)
    except Exception as exc:
        logger.error(f"Error minting MyAstroShine handoff: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Server-to-server (MyAstroShine container -> board, handoff-token auth only)
# ---------------------------------------------------------------------------


@myastroshine_bp.route('/api/astrodex/integration/source', methods=['GET'])
def integration_source_api():
    """Return the source picture's metadata for a valid handoff token."""
    if _rate_limited(_client_key()):
        return jsonify({'error': 'Too many requests'}), 429
    token = request.args.get('handoff', '')
    cfg, claims = _verify_handoff_or_none(token)
    if not claims:
        return jsonify({'error': 'Invalid or expired handoff'}), 401
    try:
        payload = integration.build_source_payload(claims, token)
        if payload is None:
            return jsonify({'error': 'Source item or picture not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        logger.error(f"Error building MyAstroShine source payload: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/source/image', methods=['GET'])
def integration_source_image_api():
    """Stream the source picture's image bytes for a valid handoff token."""
    if _rate_limited(_client_key()):
        return jsonify({'error': 'Too many requests'}), 429
    cfg, claims = _verify_handoff_or_none(request.args.get('handoff', ''))
    if not claims:
        return jsonify({'error': 'Invalid or expired handoff'}), 401
    try:
        image_path = integration.resolve_source_image_path(claims)
        if not image_path:
            return jsonify({'error': 'Source image not found'}), 404
        return send_file(image_path)
    except Exception as exc:
        logger.error(f"Error streaming MyAstroShine source image: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@myastroshine_bp.route('/api/astrodex/integration/enhanced', methods=['POST'])
def integration_enhanced_api():
    """Create the enhanced duplicate picture from a MyAstroShine multipart callback."""
    if _rate_limited(_client_key()):
        return jsonify({'error': 'Too many requests'}), 429

    cfg, claims = _verify_handoff_or_none(request.form.get('handoff', ''))
    if not claims:
        return jsonify({'error': 'Invalid or expired handoff'}), 401

    content_length = request.content_length or 0
    if content_length and content_length > MYASTROSHINE_MAX_IMAGE_BYTES + 1024 * 1024:
        return jsonify({'error': 'Payload too large'}), 413

    upload = request.files.get('image')
    if upload is None or not upload.filename:
        return jsonify({'error': 'image part is required'}), 400
    image_bytes = upload.read()
    if not image_bytes:
        return jsonify({'error': 'image part is empty'}), 400
    if len(image_bytes) > MYASTROSHINE_MAX_IMAGE_BYTES:
        return jsonify({'error': 'Image too large'}), 413

    try:
        payload_obj = json.loads(request.form.get('payload', '') or '{}')
        if not isinstance(payload_obj, dict):
            raise ValueError('payload must be a JSON object')
    except (ValueError, json.JSONDecodeError):
        return jsonify({'error': 'payload must be valid JSON'}), 400

    signature = request.headers.get('X-Webhook-Signature', '')
    if not integration.verify_return_signature(cfg, payload_obj, image_bytes, signature):
        return jsonify({'error': 'Invalid signature'}), 401

    try:
        result = integration.create_enhanced_duplicate(claims, image_bytes, payload_obj)
        return jsonify(result), 201
    except integration.EnhancedDuplicateError as exc:
        return jsonify({'error': exc.message}), exc.status
    except Exception as exc:
        logger.error(f"Error creating MyAstroShine enhanced duplicate: {exc}")
        return jsonify({'error': 'Internal server error'}), 500
