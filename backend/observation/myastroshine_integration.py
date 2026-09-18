"""MyAstroShine integration - AstroDex <-> MyAstroShine image round-trip.

This module owns the server side of the "pull + webhook" handoff (see
docs/MYASTROSHINE.md):

- the browser opens MyAstroShine with a signed, single-use ``handoff`` token
  minted here (:func:`mint_handoff`);
- the MyAstroShine container calls back server-to-server, authenticated by that
  same token, to read the source picture (:func:`build_source_payload`) and to
  post the enhanced result (:func:`create_enhanced_duplicate`).

It is deliberately **not** a ``BaseConnector``: the feature is bidirectional,
lives in the AstroDex tab, and has its own routes. Its config is only stored
under ``config["connectors"]["myastroshine"]`` so it rides along in the backup
ZIP and stays consistent with the rest of the connector config.

Module boundaries: this imports :mod:`observation.astrodex` (same package) and
:mod:`utils.repo_config` only - no new cross-feature import cycle.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from observation import astrodex
from utils import load_json_file, save_json_file
from connectors.myastroshine_connector import MyAstroShineConnector
from utils.connector_secrets import merge_secrets
from utils.logging_config import get_logger
from utils.repo_config import load_config

logger = get_logger(__name__)

# Handoff payload fields copied from the source picture onto the enhanced
# duplicate. Location and equipment are copied as a frozen snapshot (we do not
# re-resolve them from user input the way blueprints/astrodex.py does - this is
# a duplicate of an already-resolved picture, not a fresh upload).
_COPIED_PICTURE_FIELDS = (
    'date',
    'exposition_time',
    'frames',
    'integration_minutes',
    'iso',
    'device',
    'filters',
    'notes',
    'location_id',
    'location_name',
    'latitude',
    'longitude',
    'elevation',
    'combination_id',
    'combination_used_components',
)

# Immutable provenance fields stamped on the enhanced duplicate. These are NOT
# in update_picture()'s allowed_fields - once set they never change (they are
# not edit-form fields).
ENHANCED_PICTURE_FIELDS = (
    'enhanced_by',
    'enhanced_at',
    'enhanced_from_picture_id',
    'enhanced_parameters',
    'enhanced_source_version',
)

# Consumed handoff jti store. In-memory (fast path) with a best-effort JSON
# mirror so a worker restart inside the token's TTL window still rejects a
# replay. jti -> expiry epoch seconds.
_consumed_lock = threading.Lock()
_consumed: Dict[str, float] = {}
_CONSUMED_FILENAME = 'myastroshine_consumed_handoffs.json'


def _consumed_file_path() -> str:
    """Resolved fresh from astrodex.ASTRODEX_DIR so tests that repoint it still work.

    The name does not end in ``_astrodex.json`` so load_all_users_astrodex()
    never mistakes it for a user's collection.
    """
    return os.path.join(astrodex.ASTRODEX_DIR, _CONSUMED_FILENAME)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def get_integration_config(config: Optional[Dict] = None) -> Dict[str, Any]:
    """Return the ``connectors.myastroshine`` config block, credentials included.

    The token and signing secret live in the connector-secrets sidecar (utils/connector_secrets.py),
    not in config.json; ``merge_secrets`` overlays them (and still honours a legacy value left in
    the config block on an install that has not been migrated yet).
    """
    if config is None:
        config = load_config()
    block = config.get('connectors', {}).get('myastroshine', {}) or {}
    return merge_secrets(MyAstroShineConnector.name, block, MyAstroShineConnector.SECRET_FIELDS)


def integration_enabled(cfg: Optional[Dict] = None) -> bool:
    """Effective-enabled: the switch is on AND url/token/signing_secret are all set."""
    if cfg is None:
        cfg = get_integration_config()
    return bool(cfg.get('enabled') and cfg.get('url') and cfg.get('token') and cfg.get('signing_secret'))


def _token_kid(token: str) -> str:
    """The key id shared with MyAstroShine: the first 12 chars of the token."""
    return (token or '')[:12]


# The user/item/picture ids carried by a handoff are all server-minted uuid4
# strings. They flow into per-user Astrodex file paths, so every entry point
# re-checks their shape before any disk access - defence in depth on top of the
# already-verified HMAC signature, and a CodeQL py/path-injection sanitizer
# barrier. Same lenient uuid-shape pattern the rest of the codebase uses
# (e.g. blueprints/tracking.py for launch ids).
_HANDOFF_ID_RE = re.compile(r'^[0-9a-f-]{36}$')


def _is_handoff_id(value: Any) -> bool:
    return isinstance(value, str) and _HANDOFF_ID_RE.match(value) is not None


# ---------------------------------------------------------------------------
# base64url helpers (no padding, matching the MyAstroShine contract)
# ---------------------------------------------------------------------------


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64url_decode(value: str) -> bytes:
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ---------------------------------------------------------------------------
# Canonical JSON + webhook signature (must match
# app/services/astrodex_integration.py:canonical_json on the MyAstroShine side)
# ---------------------------------------------------------------------------


def canonical_json(payload: Any) -> str:
    """Deterministic JSON string used as HMAC signing input (sorted keys, no whitespace)."""
    return json.dumps(payload, separators=(',', ':'), sort_keys=True)


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


def verify_return_signature(cfg: Dict, payload_obj: Any, image_bytes: bytes, signature_header: str) -> bool:
    """Constant-time check of the ``X-Webhook-Signature`` on an inbound enhanced upload.

    The signing input is ``canonical_json(payload) + "\\n" + sha256_hex(image_bytes)``:
    the image travels as its own multipart part, so its hash is bound into the
    signature rather than the (large) blob itself.
    """
    secret = cfg.get('signing_secret') or ''
    if not secret or not signature_header:
        return False
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    signing_input = f"{canonical_json(payload_obj)}\n{image_hash}".encode('utf-8')
    expected = f"sha256={_hmac_hex(secret, signing_input)}"
    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Handoff token
# ---------------------------------------------------------------------------


def mint_handoff(cfg: Dict, *, user_id: str, item_id: str, picture_id: str, callback_base: str) -> Dict[str, str]:
    """Mint an opaque, single-use handoff token for the browser to carry.

    ``callback_base`` is set by the board (never user input) - it is the URL the
    MyAstroShine container will call back. Returns ``{handoff, myastroshine_url,
    open_url}``.
    """
    secret = cfg['signing_secret']
    now = int(time.time())
    payload = {
        'kid': _token_kid(cfg.get('token', '')),
        'callback_base': callback_base.rstrip('/'),
        'item_id': item_id,
        'picture_id': picture_id,
        'user_id': user_id,
        'iat': now,
        'exp': now + MyAstroShineConnector.HANDOFF_TTL_SECONDS,
        'jti': str(uuid.uuid4()),
    }
    body = _b64url_encode(canonical_json(payload).encode('utf-8'))
    signature = _b64url_encode(hmac.new(secret.encode('utf-8'), body.encode('ascii'), hashlib.sha256).digest())
    token = f"{body}.{signature}"

    base_url = (cfg.get('url') or '').rstrip('/')
    return {
        'handoff': token,
        'myastroshine_url': base_url,
        'open_url': f"{base_url}/#/?handoff={token}",
    }


def verify_handoff(cfg: Dict, token: str) -> Optional[Dict[str, Any]]:
    """Verify a handoff token's signature, ``kid`` and expiry. Returns claims or None.

    Does NOT check the single-use ``jti`` - read endpoints (``/source``,
    ``/source/image``) may be called repeatedly while the user edits. The
    consume check belongs to :func:`create_enhanced_duplicate`.
    """
    secret = cfg.get('signing_secret') or ''
    configured_token = cfg.get('token') or ''
    if not secret or not configured_token or not token or '.' not in token:
        return None

    body, _, signature = token.partition('.')
    expected_sig = _b64url_encode(hmac.new(secret.encode('utf-8'), body.encode('ascii'), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected_sig):
        logger.warning("MyAstroShine handoff rejected: bad signature")
        return None

    try:
        claims = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError):
        logger.warning("MyAstroShine handoff rejected: undecodable payload")
        return None

    if not isinstance(claims, dict):
        return None
    if claims.get('kid') != _token_kid(configured_token):
        logger.warning("MyAstroShine handoff rejected: kid mismatch (token rotated?)")
        return None
    try:
        expires = int(claims.get('exp', 0))
    except (TypeError, ValueError):
        return None
    if time.time() >= expires:
        logger.info("MyAstroShine handoff rejected: expired")
        return None

    if not all(_is_handoff_id(claims.get(key)) for key in ('user_id', 'item_id', 'picture_id')):
        logger.warning("MyAstroShine handoff rejected: malformed identifiers")
        return None
    return claims


# ---------------------------------------------------------------------------
# Single-use jti tracking
# ---------------------------------------------------------------------------


def _load_consumed_from_disk() -> None:
    data = load_json_file(_consumed_file_path(), default={})
    if not isinstance(data, dict):
        return
    now = time.time()
    with _consumed_lock:
        for jti, expiry in data.items():
            try:
                expiry_f = float(expiry)
            except (TypeError, ValueError):
                continue
            if expiry_f > now:
                _consumed[jti] = expiry_f


def _prune_and_persist_locked() -> None:
    now = time.time()
    expired = [jti for jti, expiry in _consumed.items() if expiry <= now]
    for jti in expired:
        _consumed.pop(jti, None)
    try:
        astrodex.ensure_astrodex_directories()
        save_json_file(_consumed_file_path(), dict(_consumed))
    except OSError as exc:  # pragma: no cover - best-effort mirror only
        logger.warning("Could not persist consumed handoff jti store: %s", exc)


def is_handoff_consumed(jti: str) -> bool:
    """Whether this handoff's jti has already been used to create a duplicate."""
    with _consumed_lock:
        expiry = _consumed.get(jti)
        if expiry is None:
            return False
        if expiry <= time.time():
            _consumed.pop(jti, None)
            return False
        return True


def mark_handoff_consumed(jti: str, expiry_epoch: Optional[float] = None) -> None:
    """Record a handoff's jti as spent so a later replay is rejected with 409."""
    if expiry_epoch is None:
        expiry_epoch = time.time() + MyAstroShineConnector.HANDOFF_TTL_SECONDS
    with _consumed_lock:
        _consumed[jti] = float(expiry_epoch)
        _prune_and_persist_locked()


_load_consumed_from_disk()


# ---------------------------------------------------------------------------
# Source picture payload (board -> MyAstroShine)
# ---------------------------------------------------------------------------


def _find_item_and_picture(user_id: str, item_id: str, picture_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    # user_id builds a per-user file path inside load_user_astrodex(); re-check
    # its shape here, right before that call, regardless of upstream validation.
    if not _is_handoff_id(user_id):
        return None, None
    data = astrodex.load_user_astrodex(user_id)
    for item in data.get('items', []):
        if item.get('id') != item_id:
            continue
        for picture in item.get('pictures', []):
            if picture.get('id') == picture_id:
                return item, picture
        return item, None
    return None, None


def build_source_payload(claims: Dict[str, Any], token: str = '') -> Optional[Dict[str, Any]]:
    """Build the source-picture metadata payload MyAstroShine loads into an edit session.

    ``token`` is the raw handoff string; it is echoed back into ``image.url`` so
    MyAstroShine can fetch the bytes without reassembling the query itself.
    Returns None when the item or picture named in the handoff no longer exists.
    """
    user_id = claims.get('user_id', '')
    item_id = claims.get('item_id', '')
    picture_id = claims.get('picture_id', '')
    item, picture = _find_item_and_picture(user_id, item_id, picture_id)
    if not item or not picture:
        return None

    filename = picture.get('filename') or ''
    _, ext = os.path.splitext(filename)
    content_type = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }.get(ext.lower(), 'application/octet-stream')

    return {
        'object': {
            'item_id': item_id,
            'name': item.get('name', ''),
            'type': item.get('type', ''),
            'catalogue': item.get('catalogue', ''),
            'constellation': item.get('constellation', ''),
        },
        'picture': {
            'source_picture_id': picture_id,
            'date': picture.get('date', ''),
            'exposition_time': picture.get('exposition_time'),
            'frames': picture.get('frames'),
            'integration_minutes': picture.get('integration_minutes'),
            'iso': picture.get('iso', ''),
            'device': picture.get('device', ''),
            'filters': picture.get('filters', ''),
            'combination_id': picture.get('combination_id'),
            'combination_used_components': picture.get('combination_used_components'),
            'location_id': picture.get('location_id'),
            'location_name': picture.get('location_name'),
            'latitude': picture.get('latitude'),
            'longitude': picture.get('longitude'),
            'elevation': picture.get('elevation'),
            'rating': picture.get('rating'),
            'notes': picture.get('notes', ''),
        },
        'image': {
            'url': (
                f"/api/astrodex/integration/source/image?handoff={token}"
                if token
                else '/api/astrodex/integration/source/image'
            ),
            'filename': filename,
            'content_type': content_type,
        },
    }


def resolve_source_image_path(claims: Dict[str, Any]) -> Optional[str]:
    """Resolve the source picture's image to an absolute path inside the images dir.

    Returns None when the picture is gone or the stored filename escapes the
    images directory (defensive - same containment check the upload path uses).
    """
    _, picture = _find_item_and_picture(
        claims.get('user_id', ''), claims.get('item_id', ''), claims.get('picture_id', '')
    )
    if not picture:
        return None
    filename = picture.get('filename') or ''
    if not filename:
        return None
    base_dir = os.path.realpath(astrodex.ASTRODEX_IMAGES_DIR)
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not file_path.startswith(base_dir + os.sep) or not os.path.isfile(file_path):
        return None
    return file_path


# ---------------------------------------------------------------------------
# Enhanced duplicate (MyAstroShine -> board)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_enhanced_image(user_id: str, image_bytes: bytes) -> Optional[str]:
    """Write the enhanced JPEG under data/astrodex/images/ and return its filename.

    Mirrors upload_astrodex_image()'s ``<user_id>_<uuid>.<ext>`` naming and
    realpath containment barrier. MyAstroShine renders JPEG.
    """
    if not _is_handoff_id(user_id):
        return None
    astrodex.ensure_astrodex_directories()
    filename = f"{user_id}_{uuid.uuid4()}.jpg"
    base_dir = os.path.realpath(astrodex.ASTRODEX_IMAGES_DIR)
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not file_path.startswith(base_dir + os.sep):  # pragma: no cover - uuid name can't traverse
        logger.warning("MyAstroShine enhanced image path escaped images dir")
        return None
    with open(file_path, 'wb') as handle:
        handle.write(image_bytes)
    return filename


class EnhancedDuplicateError(Exception):
    """Raised when the enhanced duplicate cannot be created. ``status`` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def create_enhanced_duplicate(claims: Dict[str, Any], image_bytes: bytes, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a duplicated AstroDex picture on the same item, carrying the enhanced image.

    Never replaces the source: a new picture is appended. Copies the source
    picture's frozen metadata snapshot, stamps the ``enhanced_*`` provenance
    fields, and marks the handoff jti spent.

    Raises :class:`EnhancedDuplicateError` (with an HTTP ``status``) on any
    failure; returns ``{"status": "created", "item_id", "picture_id"}`` on success.
    """
    jti = claims.get('jti', '')
    if not jti or is_handoff_consumed(jti):
        raise EnhancedDuplicateError(409, 'handoff already consumed')

    user_id = claims.get('user_id', '')
    item_id = claims.get('item_id', '')
    source_picture_id = claims.get('picture_id', '')

    # Re-validate the ids that build Astrodex file paths (user_id / item_id),
    # right before they are handed to observation.astrodex, independent of
    # verify_handoff() - see _HANDOFF_ID_RE.
    if not (_is_handoff_id(user_id) and _is_handoff_id(item_id) and _is_handoff_id(source_picture_id)):
        raise EnhancedDuplicateError(401, 'malformed handoff identifiers')

    item, source = _find_item_and_picture(user_id, item_id, source_picture_id)
    if not item or not source:
        raise EnhancedDuplicateError(404, 'source item or picture no longer exists')

    cfg = get_integration_config()
    parameters = payload.get('parameters') if isinstance(payload.get('parameters'), dict) else {}

    new_picture_data: Dict[str, Any] = {field: source.get(field) for field in _COPIED_PICTURE_FIELDS}
    new_picture_data['rating'] = source.get('rating') if cfg.get('copy_rating') else None
    new_picture_data['enhanced_by'] = 'myastroshine'
    new_picture_data['enhanced_at'] = _now_iso()
    new_picture_data['enhanced_from_picture_id'] = source_picture_id
    new_picture_data['enhanced_parameters'] = parameters
    new_picture_data['enhanced_source_version'] = payload.get('myastroshine_version')

    note = payload.get('note')
    if isinstance(note, str) and note.strip():
        base_notes = new_picture_data.get('notes') or ''
        new_picture_data['notes'] = f"{base_notes}\n{note.strip()}".strip() if base_notes else note.strip()

    filename = _save_enhanced_image(user_id, image_bytes)
    if not filename:
        raise EnhancedDuplicateError(500, 'could not store enhanced image')
    new_picture_data['filename'] = filename

    new_picture = astrodex.add_picture_to_item(user_id, item_id, new_picture_data)
    if not new_picture:
        raise EnhancedDuplicateError(404, 'item disappeared while saving')

    mark_handoff_consumed(jti, claims.get('exp'))
    logger.info(
        "MyAstroShine: created enhanced duplicate picture %s on item %s for user %s",
        new_picture.get('id'),
        item_id,
        user_id,
    )
    return {'status': 'created', 'item_id': item_id, 'picture_id': new_picture.get('id')}
