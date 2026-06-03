"""
VAPID key management and Web Push delivery.

Keys are generated once on first startup and persisted to DATA_DIR/vapid.json.
Storage format:
  private_key - raw base64url-encoded 32-byte EC scalar (what py_vapid.from_string expects)
  public_key  - URL-safe base64url of the uncompressed EC point (65 bytes, no padding)
                sent to the browser as applicationServerKey
"""
import base64
import json
import os
from urllib.parse import urlparse

from logging_config import get_logger

logger = get_logger(__name__)

_VAPID_FILE = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'vapid.json')

_raw_contact = os.environ.get('VAPID_CONTACT_EMAIL', '').strip()
if _raw_contact:
    # Accept bare email or full mailto: URI
    _VAPID_CLAIMS_EMAIL = _raw_contact if _raw_contact.startswith(('mailto:', 'https://')) else f'mailto:{_raw_contact}'
else:
    _VAPID_CLAIMS_EMAIL = 'mailto:admin@localhost'

_VAPID_CONTACT_WARNING_EMITTED = False

_vapid_keys: dict = {}


def _pem_to_raw_b64(pem_str: str) -> str:
    """Convert a PEM private key (PKCS#8 or SEC1) to raw base64url scalar.

    py_vapid 1.9.4's from_string() expects the raw 32-byte EC private scalar
    encoded as base64url - it does NOT parse PEM.
    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key  # type: ignore[import]
    key = load_pem_private_key(pem_str.encode('utf-8'), password=None)
    raw_bytes = key.private_numbers().private_value.to_bytes(32, 'big')
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b'=').decode('utf-8')


def _generate_keys() -> dict:
    """Generate a new VAPID EC key pair using py_vapid (bundled with pywebpush)."""
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # type: ignore[import]

    vapid = Vapid()
    vapid.generate_keys()
    assert vapid.public_key is not None, "generate_keys() must populate public_key"

    # Store the raw 32-byte scalar as base64url - the only format py_vapid.from_string accepts.
    raw_bytes = vapid.private_key.private_numbers().private_value.to_bytes(32, 'big')
    private_key_b64 = base64.urlsafe_b64encode(raw_bytes).rstrip(b'=').decode('utf-8')

    pub_bytes = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public_key_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode('utf-8')

    return {'private_key': private_key_b64, 'public_key': public_key_b64}


def load_or_generate_vapid_keys() -> dict:
    """Return VAPID key dict, generating and persisting on first call."""
    global _vapid_keys, _VAPID_CONTACT_WARNING_EMITTED
    if not _raw_contact and not _VAPID_CONTACT_WARNING_EMITTED:
        _VAPID_CONTACT_WARNING_EMITTED = True
        logger.warning(
            "VAPID_CONTACT_EMAIL is not set. Push notifications may be rejected by push services. "
            "Set VAPID_CONTACT_EMAIL to a real email address (e.g. you@example.com)."
        )
    if _vapid_keys.get('private_key'):
        return _vapid_keys

    if os.path.exists(_VAPID_FILE):
        try:
            with open(_VAPID_FILE, 'r') as f:
                keys = json.load(f)
            if keys.get('private_key') and keys.get('public_key'):
                # Migrate PEM format (old storage) to raw base64url scalar.
                if '-----' in keys['private_key']:
                    keys['private_key'] = _pem_to_raw_b64(keys['private_key'])
                    with open(_VAPID_FILE, 'w') as f:
                        json.dump(keys, f, indent=2)
                    logger.info("VAPID private key migrated from PEM to raw base64url format")
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


def get_vapid_contact_status() -> dict:
    """Return whether the VAPID contact email is properly configured for push delivery."""
    raw = os.environ.get('VAPID_CONTACT_EMAIL', '').strip()
    if not raw:
        return {'ok': False, 'reason': 'not_set'}
    email = raw.removeprefix('mailto:')
    domain = email.split('@')[-1].lower() if '@' in email else email.lower()
    _bad_domains = {'.local', 'localhost', 'example.com', 'example.org', 'example.net'}
    if any(domain == d or domain.endswith(d) for d in _bad_domains):
        return {'ok': False, 'reason': 'invalid_domain', 'domain': domain}
    return {'ok': True}


def send_push(subscription_info: dict, payload: dict, ttl: int = 0, urgency: str = 'normal') -> bool:
    """
    Send a single Web Push notification.

    subscription_info: {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}
    ttl:     seconds the push service keeps the message if the device is offline.
             0 = discard immediately; pass the event countdown for time-sensitive alerts.
    urgency: RFC 8030 delivery priority. 'normal' (default) respects device power
             optimisation and never bypasses silent/DND mode. Use 'high' only for
             very short time windows (N3 ISS transit, N7 aurora).
    Returns True on success, False on any delivery failure (expired/blocked subscription included).
    """
    try:
        from pywebpush import webpush

        keys     = load_or_generate_vapid_keys()
        endpoint = subscription_info.get('endpoint', '')
        parsed   = urlparse(endpoint)
        aud      = f"{parsed.scheme}://{parsed.netloc}"

        logger.debug(
            f"Sending push to {endpoint[:60]} | trigger={payload.get('tag','?')} "
            f"ttl={ttl}s urgency={urgency}"
        )

        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=keys['private_key'],
            vapid_claims={
                'sub': _VAPID_CLAIMS_EMAIL,
                'aud': aud,
            },
            ttl=ttl,
            timeout=30,
            headers={'urgency': urgency},
        )
        logger.debug(f"Push delivered OK to {endpoint[:60]}")
        return True

    except Exception as e:
        err = str(e).replace('\n', ' ').replace('\r', '').strip()
        logger.warning(f"Push delivery failed [{subscription_info.get('endpoint', '?')[:60]}]: {err}")
        return False
