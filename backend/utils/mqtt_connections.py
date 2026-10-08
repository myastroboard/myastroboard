"""
MQTT connections - broker profiles shared by every connector that talks MQTT.

A connection is what a broker needs to be reached: a display name, the ``mqtt(s)://`` URL, a
username, a password and the "accept a self-signed certificate" switch. It lives once, in
``config["mqtt_connections"]``, and a connector picks one through its ``CONNECTION_FIELD``
(``MqttConnector``: ``mqtt_connection_id``). Everything about *what* a connector does on the
broker (topics, discovery, client id, modules) stays in the connector's own block.

The password follows the rule of every other connector credential (utils/connector_secrets.py):
it is kept in the ``connectors_secrets`` setting, under ``mqtt_connection:<id>``, never in the
config. So it stays out of the backup ZIP and ``/api/config/export``, and no API returns it
unmasked.

Two connectors may share a connection (one broker for Home Assistant and AllSky) - each one
then opens its own client, so their client ids must differ (``client_id_conflict``).

Up to 1.7.1 the Home Assistant connector carried its own broker fields. ``normalize_legacy_mqtt``
turns such a block into a connection with a fixed id every time a config is read (an old backup
restored later is converted the same way, and every gunicorn worker converges on the same id);
``migrate_legacy_mqtt`` moves its password into the connection once, at startup.
"""

import uuid
from typing import Any

from utils.connector_secrets import load_secrets, save_secrets
from utils.logging_config import get_logger

logger = get_logger(__name__)

CONNECTIONS_KEY = 'mqtt_connections'

# The connection created from a 1.7.1-or-earlier Home Assistant connector block. Fixed, not random:
# every worker (and every later read of an old backup) must produce the same one.
LEGACY_CONNECTION_ID = 'home-assistant'
LEGACY_CONNECTION_NAME = 'Home Assistant'

# Connector config keys that described the broker before connections existed.
_LEGACY_BROKER_KEYS = ('url', 'username', 'tls_insecure')

NAME_MAX_LENGTH = 64
USERNAME_MAX_LENGTH = 256

_SECRET_PREFIX = 'mqtt_connection:'

# What the browser sees for a stored password: a fixed mask that reveals nothing of it - not
# even its last characters or its length (unlike the token tails of mask_secret()).
PASSWORD_MASK = '********'


def _secret_name(connection_id: str) -> str:
    return f'{_SECRET_PREFIX}{connection_id}'


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _clean_connection(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    connection_id = str(raw.get('id') or '').strip()
    if not connection_id:
        return None
    return {
        'id': connection_id,
        'name': str(raw.get('name') or '').strip() or connection_id,
        'url': str(raw.get('url') or '').strip().rstrip('/'),
        'username': str(raw.get('username') or '').strip(),
        'tls_insecure': bool(raw.get('tls_insecure', False)),
    }


def list_connections(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every saved connection (clean copies, password excluded), in their saved order."""
    raw = config.get(CONNECTIONS_KEY)
    if not isinstance(raw, list):
        return []
    cleaned = (_clean_connection(item) for item in raw)
    return [item for item in cleaned if item is not None]


def get_connection(config: dict[str, Any], connection_id: str | None) -> dict[str, Any] | None:
    """The connection with this id, or None."""
    wanted = str(connection_id or '').strip()
    if not wanted:
        return None
    return next((c for c in list_connections(config) if c['id'] == wanted), None)


def connection_password(connection_id: str | None) -> str:
    """The stored password of a connection (``''`` when none).

    The migrated Home Assistant connection falls back to the password the connector kept before
    connections existed, so a config read before ``migrate_legacy_mqtt`` ran (or an old backup
    restored on an install that still holds that password) keeps working.
    """
    wanted = str(connection_id or '').strip()
    if not wanted:
        return ''
    password = load_secrets(_secret_name(wanted)).get('password', '')
    if not password and wanted == LEGACY_CONNECTION_ID:
        password = load_secrets('mqtt').get('password', '')
    return password


def _connection_connectors() -> dict[str, Any]:
    """Registered connector classes that pick an MQTT connection, by name."""
    # Lazy: utils/ must not depend on the connectors package at import time.
    from connectors import REGISTRY

    return {name: cls for name, cls in REGISTRY.items() if getattr(cls, 'CONNECTION_FIELD', '')}


def used_by(config: dict[str, Any], connection_id: str) -> list[str]:
    """Names of the connectors whose saved block points at this connection (enabled or not)."""
    connectors_cfg = config.get('connectors')
    if not isinstance(connectors_cfg, dict):
        return []
    users = []
    for name, cls in _connection_connectors().items():
        block = connectors_cfg.get(name)
        if isinstance(block, dict) and str(block.get(cls.CONNECTION_FIELD) or '') == connection_id:
            users.append(name)
    return users


def public_connection(config: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    """A connection as the browser may see it: password masked, plus the connectors using it."""
    public = dict(connection)
    password = connection_password(connection['id'])
    public['password'] = PASSWORD_MASK if password else ''
    public['has_password'] = bool(password)
    public['used_by'] = used_by(config, connection['id'])
    return public


def overlay_connection(block: dict[str, Any] | None, config: dict[str, Any], field: str) -> dict[str, Any]:
    """A connector block with the broker fields of its chosen connection laid over it.

    ``url``, ``username`` and ``tls_insecure`` come from the connection, so the connector reads
    them as before. The password is deliberately left out: callers fetch it with
    ``connection_password`` and hand it over explicitly (see connectors/mqtt_publisher.py on
    why it must not share a dict with routine reads). A missing connection leaves ``url``
    blank, which every connector reads as "not configured".
    """
    merged = dict(block or {})
    connection = get_connection(config, merged.get(field))
    merged['url'] = connection['url'] if connection else ''
    merged['username'] = connection['username'] if connection else ''
    merged['tls_insecure'] = connection['tls_insecure'] if connection else False
    return merged


def client_id_conflict(config: dict[str, Any], name: str, connection_id: str, client_id: str) -> str | None:
    """Name of another connector that uses the same connection with the same explicit client id.

    A broker accepts one session per client id: a second client connecting with it pushes the
    first one off, and both then reconnect in turn forever. A blank client id is generated per
    connector, so it never conflicts.
    """
    wanted = str(client_id or '').strip()
    if not wanted or not connection_id:
        return None
    connectors_cfg = config.get('connectors')
    if not isinstance(connectors_cfg, dict):
        return None
    for other, cls in _connection_connectors().items():
        if other == name:
            continue
        block = connectors_cfg.get(other)
        if not isinstance(block, dict) or str(block.get(cls.CONNECTION_FIELD) or '') != connection_id:
            continue
        if str(block.get('client_id') or '').strip() == wanted:
            return other
    return None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _validate(config: dict[str, Any], data: dict[str, Any], current: dict[str, Any] | None) -> tuple[dict, str | None]:
    """The connection fields from *data* (over *current* for an update), or an error string."""
    # Lazy: connectors/ is not imported by utils/ at module level.
    from connectors.mqtt_connector import parse_broker_url

    base = dict(current or {})
    if 'name' in data or current is None:
        base['name'] = str(data.get('name') or '').strip()
    if 'url' in data or current is None:
        base['url'] = str(data.get('url') or '').strip().rstrip('/')
    if 'username' in data or current is None:
        base['username'] = str(data.get('username') or '').strip()
    if 'tls_insecure' in data or current is None:
        base['tls_insecure'] = bool(data.get('tls_insecure', False))

    if not base['name']:
        return base, 'name required'
    if len(base['name']) > NAME_MAX_LENGTH:
        return base, f'name must be at most {NAME_MAX_LENGTH} characters'
    own_id = current['id'] if current else None
    taken = {c['name'].casefold() for c in list_connections(config) if c['id'] != own_id}
    if base['name'].casefold() in taken:
        return base, 'a connection with this name already exists'
    if not base['url']:
        return base, 'url required'
    _host, _port, _tls, error = parse_broker_url(base['url'])
    if error:
        return base, error
    if len(base['username']) > USERNAME_MAX_LENGTH:
        return base, f'username must be at most {USERNAME_MAX_LENGTH} characters'
    return base, None


def _password_update(connection_id: str, data: dict[str, Any], username: str) -> bool:
    """Apply the submitted password; True on success.

    Blank or still masked (``****...`` as handed out by the list) means "keep the stored one".
    A connection without a username has no use for a password, so clearing the username
    drops it.
    """
    if not username:
        return save_secrets(_secret_name(connection_id), {'password': ''})
    incoming = str(data.get('password') or '').strip()
    if not incoming or incoming.startswith('****'):
        return True
    return save_secrets(_secret_name(connection_id), {'password': incoming})


def create_connection(config: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Add a connection to *config* (the caller saves it). Returns ``(connection, error)``."""
    fields, error = _validate(config, data, None)
    if error:
        return None, error
    connection = {'id': uuid.uuid4().hex, **fields}
    if not _password_update(connection['id'], data, connection['username']):
        return None, 'could not store the password'
    raw = config.get(CONNECTIONS_KEY)
    config[CONNECTIONS_KEY] = [*(raw if isinstance(raw, list) else []), connection]
    logger.info(f"MQTT connection '{connection['name']}' created ({connection['id']})")
    return connection, None


def update_connection(
    config: dict[str, Any], connection_id: str, data: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Edit a connection in *config* (the caller saves it). Returns ``(connection, error)``."""
    current = get_connection(config, connection_id)
    if current is None:
        return None, 'not found'
    fields, error = _validate(config, data, current)
    if error:
        return None, error
    if not _password_update(current['id'], data, fields['username']):
        return None, 'could not store the password'
    config[CONNECTIONS_KEY] = [fields if c['id'] == current['id'] else c for c in list_connections(config)]
    logger.info(f"MQTT connection '{fields['name']}' updated ({current['id']})")
    return fields, None


def delete_connection(config: dict[str, Any], connection_id: str) -> tuple[list[str], str | None]:
    """Remove a connection from *config* (the caller saves it). Returns ``(used_by, error)``.

    Refused while a connector still points at it: ``used_by`` then names those connectors.
    """
    current = get_connection(config, connection_id)
    if current is None:
        return [], 'not found'
    users = used_by(config, current['id'])
    if users:
        return users, 'connection in use'
    config[CONNECTIONS_KEY] = [c for c in list_connections(config) if c['id'] != current['id']]
    save_secrets(_secret_name(current['id']), {'password': ''})
    logger.info(f"MQTT connection '{current['name']}' deleted ({current['id']})")
    return [], None


# ---------------------------------------------------------------------------
# Home Assistant connector blocks from 1.7.1 or earlier
# ---------------------------------------------------------------------------


def legacy_mqtt_pending(raw: dict[str, Any] | None) -> bool:
    """True when a stored config still describes the broker inside the MQTT connector block."""
    block = ((raw or {}).get('connectors') or {}).get('mqtt') if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return False
    return any(key in block for key in (*_LEGACY_BROKER_KEYS, 'password'))


def normalize_legacy_mqtt(config: dict[str, Any]) -> None:
    """Turn a 1.7.1-or-earlier MQTT connector block into a connection, in memory (no persistence).

    A block that still carries a broker URL and picks no connection gets the fixed-id
    Home Assistant connection, created with that URL, username and TLS switch; the broker keys
    then leave the block. Its password is not touched here (see ``connection_password``'s
    fallback and ``migrate_legacy_mqtt``).
    """
    connectors_cfg = config.get('connectors')
    if not isinstance(connectors_cfg, dict):
        return
    block = connectors_cfg.get('mqtt')
    if not isinstance(block, dict) or not any(key in block for key in _LEGACY_BROKER_KEYS):
        return
    block = connectors_cfg['mqtt'] = dict(block)  # same reason as the list below

    url = str(block.get('url') or '').strip().rstrip('/')
    if url and not block.get('mqtt_connection_id'):
        if get_connection(config, LEGACY_CONNECTION_ID) is None:
            # A new list, never an append: the merged config can share its lists with the
            # stored payload it was read from.
            raw = config.get(CONNECTIONS_KEY)
            connections = list(raw) if isinstance(raw, list) else []
            connections.append(
                {
                    'id': LEGACY_CONNECTION_ID,
                    'name': LEGACY_CONNECTION_NAME,
                    'url': url,
                    'username': str(block.get('username') or '').strip(),
                    'tls_insecure': bool(block.get('tls_insecure', False)),
                }
            )
            config[CONNECTIONS_KEY] = connections
        block['mqtt_connection_id'] = LEGACY_CONNECTION_ID
    for key in _LEGACY_BROKER_KEYS:
        block.pop(key, None)


def migrate_legacy_mqtt(config: dict[str, Any]) -> bool:
    """Give the migrated Home Assistant connection the password its connector used to hold.

    *config* is a loaded (already normalized) config. The password is taken from the connector
    block (a version that kept it in the config) or from the connector's own credentials, stored
    under the connection, and removed from both old places. Returns True when *config* was
    modified (the caller then saves it). Idempotent, and never drops a password it could not
    store elsewhere.
    """
    connectors_cfg = config.get('connectors')
    block = connectors_cfg.get('mqtt') if isinstance(connectors_cfg, dict) else None
    if not isinstance(block, dict):
        return False

    changed = False
    legacy_password = str(block.get('password') or '').strip() or load_secrets('mqtt').get('password', '')
    if legacy_password and block.get('mqtt_connection_id') == LEGACY_CONNECTION_ID:
        secret = _secret_name(LEGACY_CONNECTION_ID)
        if not load_secrets(secret).get('password') and not save_secrets(secret, {'password': legacy_password}):
            return False
        save_secrets('mqtt', {'password': ''})
        logger.info('MQTT connector password moved to the Home Assistant connection')
    if 'password' in block:
        block.pop('password', None)
        changed = True
    return changed
