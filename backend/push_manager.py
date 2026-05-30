"""
VAPID key management and Web Push delivery.

Keys are generated once on first startup and persisted to DATA_DIR/vapid.json.
Storage format:
  private_key — PEM string (used by pywebpush's webpush())
  public_key  — URL-safe base64url of the uncompressed EC point (65 bytes, no padding)
                sent to the browser as applicationServerKey
"""
import base64
import json
import os
from urllib.parse import urlparse

from logging_config import get_logger

logger = get_logger(__name__)

_VAPID_FILE = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'vapid.json')
_VAPID_CLAIMS_EMAIL = 'mailto:noreply@myastroboard.local'

_vapid_keys: dict = {}


def _generate_keys() -> dict:
    """Generate a new VAPID EC key pair using py_vapid (bundled with pywebpush)."""
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # type: ignore[import]

    vapid = Vapid()
    vapid.generate_keys()
    assert vapid.public_key is not None, "generate_keys() must populate public_key"

    private_pem = vapid.private_pem().decode('utf-8')

    pub_bytes = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public_key_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode('utf-8')

    return {'private_key': private_pem, 'public_key': public_key_b64}


def load_or_generate_vapid_keys() -> dict:
    """Return VAPID key dict, generating and persisting on first call."""
    global _vapid_keys
    if _vapid_keys.get('private_key'):
        return _vapid_keys

    if os.path.exists(_VAPID_FILE):
        try:
            with open(_VAPID_FILE, 'r') as f:
                keys = json.load(f)
            if keys.get('private_key') and keys.get('public_key'):
                _vapid_keys = keys
                logger.debug("VAPID keys loaded from disk")
                return _vapid_keys
        except Exception as e:
            logger.warning(f"Failed to load VAPID keys, regenerating: {e}")

    logger.info("Generating new VAPID key pair")
    keys = _generate_keys()
    try:
        with open(_VAPID_FILE, 'w') as f:
            json.dump(keys, f, indent=2)
        logger.info(f"VAPID keys saved to {_VAPID_FILE}")
    except Exception as e:
        logger.error(f"Failed to persist VAPID keys: {e}")

    _vapid_keys = keys
    return keys


def get_vapid_public_key() -> str:
    return load_or_generate_vapid_keys()['public_key']


def send_push(subscription_info: dict, payload: dict) -> bool:
    """
    Send a single Web Push notification.

    subscription_info: {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}
    Returns True on success, False on any delivery failure (expired/blocked subscription included).
    """
    try:
        from pywebpush import webpush

        keys    = load_or_generate_vapid_keys()
        endpoint = subscription_info.get('endpoint', '')
        parsed   = urlparse(endpoint)
        aud      = f"{parsed.scheme}://{parsed.netloc}"

        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=keys['private_key'],
            vapid_claims={
                'sub': _VAPID_CLAIMS_EMAIL,
                'aud': aud,
            },
        )
        return True

    except Exception as e:
        logger.warning(f"Push delivery failed [{subscription_info.get('endpoint', '?')[:60]}]: {e}")
        return False
