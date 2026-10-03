"""The pre-1.7 JSON files the legacy importer knows how to bring into the database.

Each source only parses and lightly checks its files: the documents go into the
database exactly as they were on disk, and the feature modules keep applying their
usual load-time normalization when they read them back. Feature modules are NOT
imported here - importing ``utils.auth`` for instance would build the user manager
(and its default admin) in the middle of the import.
"""

import os
from collections.abc import Callable
from typing import Any

from db.json_layout import DOCUMENT_FOLDERS, parse_document_path
from db.legacy_import import (
    DocumentRecord,
    LegacySource,
    Record,
    SettingRecord,
    UnreadableDocument,
    UserRecord,
    read_json_file,
)

USERS_FILENAME = 'users.json'
_REQUIRED_USER_FIELDS = ('user_id', 'username', 'password_hash', 'role')


def _existing(*paths: str) -> list[str]:
    """``paths`` that exist, or whose ``.backup`` does (a 1.6 save interrupted mid-way)."""
    return [path for path in paths if os.path.isfile(path) or os.path.isfile(path + '.backup')]


# --- users.json ------------------------------------------------------------------------


def _discover_users(root: str) -> list[str]:
    return _existing(os.path.join(root, USERS_FILENAME))


def _convert_users(path: str) -> list[Record]:
    data = read_json_file(path)
    if not isinstance(data, dict):
        raise UnreadableDocument('the root is not an object')
    records: list[Record] = []
    usernames = set()
    for user_id, user in data.items():
        if not isinstance(user, dict):
            raise UnreadableDocument(f'user {user_id} is not an object')
        missing = [name for name in _REQUIRED_USER_FIELDS if not user.get(name)]
        if missing:
            raise UnreadableDocument(f"user {user_id} lacks {', '.join(missing)}")
        if user['user_id'] != user_id:
            raise UnreadableDocument(f'user {user_id} has a mismatched user_id')
        if user['username'] in usernames:
            raise UnreadableDocument(f"username {user['username']!r} appears twice")
        usernames.add(user['username'])
        records.append(UserRecord(user=user))
    return records


# --- Install-wide settings (one file -> one key of the settings table) -----------------


def _is_object(value: Any) -> str | None:
    return None if isinstance(value, dict) else 'the root is not an object'


def _setting_source(
    name: str,
    relative_path: str,
    key: str,
    critical: bool = False,
    check: Callable[[Any], str | None] = _is_object,
) -> LegacySource:
    """A source for one JSON file that becomes the value of one setting."""

    def discover(root: str) -> list[str]:
        return _existing(os.path.join(root, *relative_path.split('/')))

    def convert(path: str) -> list[Record]:
        value = read_json_file(path)
        problem = check(value)
        if problem:
            raise UnreadableDocument(problem)
        return [SettingRecord(key=key, value=value)]

    return LegacySource(name, discover, convert, critical=critical)


def _discover_secret_key(root: str) -> list[str]:
    return _existing(os.path.join(root, 'secret_key.txt'))


def _convert_secret_key(path: str) -> list[Record]:
    with open(path, encoding='utf-8') as handle:
        key = handle.read().strip()
    if not key:
        raise UnreadableDocument('the file is empty')
    return [SettingRecord(key='secret_key', value=key)]


# --- Per-user documents (astrodex, sessions, wishlist, equipment, plans) ----------------


def _discover_documents(root: str) -> list[str]:
    found: list[str] = []
    for folder in DOCUMENT_FOLDERS:
        directory = os.path.join(root, folder)
        if not os.path.isdir(directory):
            continue
        names = set(os.listdir(directory))
        for name in sorted(names):
            # A lone ".backup" stands for its file when a 1.6 save crashed mid-way
            base = name[: -len('.backup')] if name.endswith('.backup') else name
            if base != name and base in names:
                continue
            if parse_document_path(f'{folder}/{base}') is not None:
                found.append(os.path.join(directory, base))
    return sorted(set(found))


def _convert_document(path: str) -> list[Record]:
    original = path[: -len('.backup')] if path.endswith('.backup') else path
    folder = os.path.basename(os.path.dirname(original))
    parsed = parse_document_path(f'{folder}/{os.path.basename(original)}')
    if parsed is None:  # pragma: no cover - discovery only returns parseable names
        raise UnreadableDocument('not a per-user document')
    kind, user_id, doc_key = parsed
    data = read_json_file(path)
    if not isinstance(data, dict):
        raise UnreadableDocument('the root is not an object')
    return [DocumentRecord(user_id=user_id, kind=kind, data=data, doc_key=doc_key)]


SOURCES: list[LegacySource] = [
    LegacySource('users', _discover_users, _convert_users, critical=True),
    _setting_source('config', 'config.json', 'config', critical=True),
    _setting_source('app settings', 'app_settings.json', 'app_settings'),
    _setting_source('security settings', 'security_settings.json', 'security_settings'),
    _setting_source('connector secrets', 'connectors_secrets.json', 'connectors_secrets'),
    _setting_source('VAPID keys', 'vapid.json', 'vapid'),
    _setting_source(
        'MyAstroShine handoffs', 'astrodex/myastroshine_consumed_handoffs.json', 'myastroshine_consumed_handoffs'
    ),
    LegacySource('secret key', _discover_secret_key, _convert_secret_key),
    LegacySource('per-user documents', _discover_documents, _convert_document),
]


def legacy_users_file_pending(root: str) -> bool:
    """True while a users.json is still waiting to be imported (never create a default admin then)."""
    return bool(_discover_users(root))
