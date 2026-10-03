"""Admin backup ZIP: build it from the database, restore it into the database.

The archive keeps the pre-1.7 layout (see ``db/json_layout.py``), so a backup taken with
1.6 restores on 1.7 and an archive stays readable with any text editor:

    config.json  users.json  app_settings.json
    astrodex/<user_id>_astrodex.json            astrodex/images/...
    equipments/<user_id>_<type>.json
    observation_sessions/<user_id>_sessions.json  observation_sessions/attachments/...
    wishlist/<user_id>_wishlist.json

Deliberately absent, as before: plans (ephemeral), the security settings, the connector
secrets, the secret key and the VAPID keys (host-specific or secret).

Feature modules are imported lazily, inside the functions (utils must stay importable
without them).
"""

import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import IO, Any

from sqlalchemy import select

from db import documents, schema, settings_store, users_store
from db.engine import read, transaction
from db.json_layout import EQUIPMENT_TYPES, document_path, parse_document_path
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Settings shipped in the backup: archive name -> settings key
_SETTING_FILES = {'config.json': 'config', 'app_settings.json': 'app_settings'}
_USERS_FILE = 'users.json'
# Document kinds shipped in the backup, by archive folder (plans are not backed up)
_DOCUMENT_FOLDER_KINDS = {
    'astrodex': ('astrodex',),
    'equipments': tuple(f'equipment.{equipment_type}' for equipment_type in EQUIPMENT_TYPES),
    'observation_sessions': ('observation_sessions',),
    'wishlist': ('wishlist',),
}


def _binary_dirs() -> dict[str, str]:
    """Archive folder -> directory of the binary files shipped in the backup."""
    from observation import astrodex, observation_sessions

    return {
        'astrodex/images': astrodex.ASTRODEX_IMAGES_DIR,
        'observation_sessions/attachments': observation_sessions.attachments_dir(),
    }


# --- Backup ------------------------------------------------------------------------------


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False).encode('utf-8')


def write_backup(target: IO[bytes]) -> int:
    """Write the backup ZIP to ``target``; return the number of archive members."""
    members = 0
    with zipfile.ZipFile(target, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        with read():
            for name, key in _SETTING_FILES.items():
                value = settings_store.get_setting(key)
                if value is not None:
                    archive.writestr(name, _json_bytes(value))
                    members += 1
            users = users_store.get_all_users()
            if users:
                archive.writestr(_USERS_FILE, _json_bytes(users))
                members += 1
            for kinds in _DOCUMENT_FOLDER_KINDS.values():
                for kind in kinds:
                    for user_id, doc_key, data in documents.list_documents(kind):
                        archive.writestr(document_path(kind, user_id, doc_key), _json_bytes(data))
                        members += 1
        for arc_folder, directory in _binary_dirs().items():
            if not os.path.isdir(directory):
                continue
            for root, _dirs, files in os.walk(directory):
                for filename in sorted(files):
                    full_path = os.path.join(root, filename)
                    rel = os.path.relpath(full_path, directory).replace(os.sep, '/')
                    archive.write(full_path, f'{arc_folder}/{rel}')
                    members += 1
    return members


# --- Restore -----------------------------------------------------------------------------


@dataclass
class RestorePlan:
    """What an archive contains, parsed and validated before anything is written."""

    settings: dict[str, Any] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] | None = None
    # folder -> [(kind, user_id, doc_key, data)]
    documents: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = field(default_factory=dict)
    # archive folder -> [(zip member, sanitized relative parts)]
    binaries: dict[str, list[tuple[zipfile.ZipInfo, list[str]]]] = field(default_factory=dict)
    # Why the archive cannot be restored (shown to the admin); nothing is written when set
    error: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.settings or self.users is not None or self.documents or self.binaries)


@dataclass
class RestoreReport:
    restored: int = 0
    skipped: list[str] = field(default_factory=list)


# Returned by _load_json_member for a member that cannot be read or parsed
_UNREADABLE = object()


def _load_json_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> Any:
    try:
        return json.loads(archive.read(info).decode('utf-8-sig'))
    except Exception:
        return _UNREADABLE


def _object_member_error(name: str, value: Any) -> str | None:
    if value is _UNREADABLE:
        return f'{name} is not valid JSON - archive may be corrupt'
    if not isinstance(value, dict):
        return f'{name} is not a JSON object - archive may be corrupt'
    return None


def plan_restore(archive: zipfile.ZipFile) -> RestorePlan:
    """Parse and validate every recognised member (no write). Unknown members are ignored.

    An archive that cannot be restored comes back with ``error`` set (a message written
    here, never an exception's text, as it is shown to the admin).
    """
    from werkzeug.utils import secure_filename

    from utils.auth import UserManager

    plan = RestorePlan()
    binary_folders = list(_binary_dirs())
    for info in archive.infolist():
        name = info.filename.replace('\\', '/').lstrip('/')
        if name.endswith('/'):
            continue
        if name in _SETTING_FILES:
            value = _load_json_member(archive, info)
            plan.error = _object_member_error(name, value)
            if plan.error:
                return plan
            plan.settings[_SETTING_FILES[name]] = value
            continue
        if name == _USERS_FILE:
            users = _load_json_member(archive, info)
            if users is _UNREADABLE:
                plan.error = f'{name} is not valid JSON - archive may be corrupt'
                return plan
            is_valid, error = UserManager.validate_users_json_data(users)
            if not is_valid:
                plan.error = f'users.json is invalid: {error}'
                return plan
            plan.users = users
            continue
        folder = next((f for f in binary_folders if name.startswith(f + '/')), None)
        if folder is not None:
            parts = [secure_filename(part) for part in name[len(folder) + 1 :].split('/') if part]
            if parts and all(parts):
                plan.binaries.setdefault(folder, []).append((info, parts))
            continue
        parsed = parse_document_path(name)
        if parsed is None:
            continue
        kind, user_id, doc_key = parsed
        top = name.split('/', 1)[0]
        if top not in _DOCUMENT_FOLDER_KINDS or kind not in _DOCUMENT_FOLDER_KINDS[top]:
            continue  # e.g. plans: never part of a backup
        data = _load_json_member(archive, info)
        plan.error = _object_member_error(name, data)
        if plan.error:
            return plan
        plan.documents.setdefault(top, []).append((kind, user_id, doc_key, data))
    # A folder seen only through its binary files still replaces its documents (1.6 cleared
    # the whole directory): an archive with astrodex pictures but no astrodex JSON empties it.
    for folder in plan.binaries:
        plan.documents.setdefault(folder.split('/', 1)[0], [])
    return plan


def apply_restore(archive: zipfile.ZipFile, plan: RestorePlan) -> RestoreReport:
    """Write a validated plan: the database in one transaction, then the binary files."""
    report = RestoreReport()
    with transaction() as conn:
        for key, value in plan.settings.items():
            settings_store.put_setting(key, value)
            report.restored += 1
        if plan.users is not None:
            keep = set(plan.users)
            existing = set(conn.execute(select(schema.users.c.user_id)).scalars())
            for user_id in existing - keep:
                users_store.delete_user(user_id)
            users_store.upsert_users(plan.users.values())
            report.restored += 1
        known_users = set(conn.execute(select(schema.users.c.user_id)).scalars())
        for folder, entries in plan.documents.items():
            kinds = _DOCUMENT_FOLDER_KINDS[folder]
            for kind in kinds:
                documents.delete_kind(kind)
            for kind, user_id, doc_key, data in entries:
                if user_id not in known_users:
                    report.skipped.append(document_path(kind, user_id, doc_key))
                    continue
                documents.put_document(user_id, kind, data, doc_key)
                report.restored += 1

        binary_dirs = _binary_dirs()
        for folder, members in plan.binaries.items():
            target_dir = os.path.abspath(binary_dirs[folder])
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            os.makedirs(target_dir, exist_ok=True)
            for info, parts in members:
                destination = os.path.join(target_dir, *parts)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with archive.open(info) as source, open(destination, 'wb') as target:
                    shutil.copyfileobj(source, target)
                report.restored += 1
    if report.skipped:
        logger.warning(f"Restore: skipped {len(report.skipped)} document(s) of unknown users")
    return report
