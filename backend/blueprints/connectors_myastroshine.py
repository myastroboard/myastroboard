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

import json
import time
from collections import deque
from threading import Lock

from flask import Blueprint, jsonify, request, send_file

from connectors.myastroshine_connector import MyAstroShineConnector
from observation import astrodex
from observation import myastroshine_integration as integration
from utils.auth import get_current_user, login_required, user_required
from utils.constants import (
    MYASTROSHINE_ENHANCED_RATE_LIMIT,
    MYASTROSHINE_ENHANCED_RATE_WINDOW_SECONDS,
    MYASTROSHINE_MAX_IMAGE_BYTES,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

connectors_myastroshine_bp = Blueprint('connectors_myastroshine', __name__)

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


@connectors_myastroshine_bp.route('/api/astrodex/integration/status', methods=['GET'])
@login_required
def integration_status():
    """Whether the AstroDex "Send to MyAstroShine" button should be shown."""
    try:
        return jsonify({'enabled': integration.integration_enabled()})
    except Exception as exc:
        logger.error(f"Error reading MyAstroShine integration status: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@connectors_myastroshine_bp.route('/api/connectors/myastroshine/health', methods=['GET', 'POST'])
@login_required
def myastroshine_health_api():
    """Reachability probe against ``<url>/api/health``, in the shape every connector uses.

    POST {"url": "..."} - probe an arbitrary URL, for the test button before saving.
    GET - probe the saved URL.

    MyAstroShine is LAN-only, so "unreachable" is expected and normal when the board runs on
    a different network. The probe itself (host resolution, SSRF guards) lives on the
    connector class.
    """
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            url = str(data.get('url') or '').strip().rstrip('/')
        else:
            url = str(integration.get_integration_config().get('url') or '').strip().rstrip('/')

        if not url:
            return jsonify({'reachable': False, 'modules': {}, 'error': 'url required'}), 400

        result = MyAstroShineConnector({'url': url}).health_check()
        status = 400 if result.get('error') else 200
        return jsonify(result), status
    except Exception as exc:
        logger.error(f"Error probing MyAstroShine reachability: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@connectors_myastroshine_bp.route('/api/astrodex/integration/handoff', methods=['POST'])
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


@connectors_myastroshine_bp.route('/api/astrodex/integration/source', methods=['GET'])
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


@connectors_myastroshine_bp.route('/api/astrodex/integration/source/image', methods=['GET'])
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


@connectors_myastroshine_bp.route('/api/astrodex/integration/enhanced', methods=['POST'])
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
