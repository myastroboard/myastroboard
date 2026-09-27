"""Per-user files on disk: where they live, erasing them, exporting them.

Every feature stores a user's data in files named ``<user_id>_...`` inside its own
directory. This module is the single list of those directories, used both for the
right to erasure (account deletion) and for the right to data portability (the
"Download my data" ZIP).

Feature modules are imported lazily, inside the functions, so utils stays importable
without them (and without import cycles).
"""

import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import IO, Dict, List, Tuple

from utils.logging_config import get_logger

logger = get_logger(__name__)

_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
# Working files that are not user data
_SKIPPED_SUFFIXES = ('.lock', '.tmp')
# Already-compressed formats are stored as is in the ZIP
_STORED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.pdf', '.docx', '.zip'}

_EXPORT_README = """MyAstroBoard - personal data export

Exported on: {exported_at}
Account: {username} ({user_id})

account.json                     your account (password and two-factor secrets excluded)
locations.json                   the observing locations available to you
astrodex/                        your Astrodex (objects, notes, picture metadata)
astrodex/images/                 your Astrodex pictures
equipment/                       your equipment profiles
observation_sessions/            your observation log
observation_sessions/attachments/  files attached to your sessions
plans/                           your Plan My Night plans
wishlist/                        your wishlist

Data files are JSON (UTF-8), readable by any text editor or program.
"""


def user_data_dirs() -> List[Tuple[str, str]]:
    """``(archive folder, directory)`` for every directory holding ``<user_id>_...`` files.

    Resolved on each call (not at import) so tests that repoint a module's directory
    constant are honoured.
    """
    from equipment import equipment_profiles
    from observation import astrodex, observation_sessions, plan_my_night, wishlist

    return [
        ('astrodex', astrodex.ASTRODEX_DIR),
        ('astrodex/images', astrodex.ASTRODEX_IMAGES_DIR),
        ('equipment', equipment_profiles.EQUIPMENT_DIR),
        ('observation_sessions', observation_sessions.OBSERVATION_SESSIONS_DIR),
        ('observation_sessions/attachments', observation_sessions.attachments_dir()),
        ('plans', plan_my_night.PLAN_DIR),
        ('wishlist', wishlist.WISHLIST_DIR),
    ]


def _is_valid_user_id(user_id: str) -> bool:
    return bool(_USER_ID_PATTERN.match(user_id))


def _iter_user_files(user_id: str, include_working_files: bool):
    """Yield ``(archive folder, filename, absolute path)`` for each ``<user_id>_*`` file."""
    prefix = f"{user_id}_"
    for folder, directory in user_data_dirs():
        base_dir = os.path.realpath(directory)
        if not os.path.isdir(base_dir):
            continue
        for filename in sorted(os.listdir(base_dir)):
            if not filename.startswith(prefix):
                continue
            if not include_working_files and filename.endswith(_SKIPPED_SUFFIXES):
                continue
            file_path = os.path.realpath(os.path.join(base_dir, filename))
            if file_path.startswith(base_dir + os.sep) and os.path.isfile(file_path):
                yield folder, filename, file_path


def purge_user_files(user_id) -> int:
    """Delete every per-user file of ``user_id`` (``<user_id>_*``) and return how many were removed.

    Best effort: a file that cannot be removed is logged and skipped so one failure
    never leaves the rest of the user's data behind.
    """
    user_id = str(user_id)
    if not _is_valid_user_id(user_id):
        logger.warning(f"Refusing to purge files for malformed user id {user_id!r}")
        return 0

    removed = 0
    for _folder, filename, file_path in list(_iter_user_files(user_id, include_working_files=True)):
        try:
            os.remove(file_path)
            removed += 1
        except OSError as remove_error:
            logger.warning(f"Failed to delete user data file {filename}: {remove_error}")
    return removed


def _legacy_astrodex_pictures(user_id: str) -> List[Tuple[str, str]]:
    """Pictures the user's Astrodex references without the ``<user_id>_`` prefix (older uploads)."""
    from observation import astrodex

    pictures: List[Tuple[str, str]] = []
    try:
        data = astrodex.load_user_astrodex(user_id)
    except Exception as error:
        logger.warning(f"Export: could not read astrodex of {user_id}: {error}")
        return pictures
    base_dir = os.path.realpath(astrodex.ASTRODEX_IMAGES_DIR)
    for item in data.get('items', []):
        for picture in item.get('pictures', []):
            filename = picture.get('filename') or ''
            if filename.startswith(f"{user_id}_") or not _SAFE_FILENAME_PATTERN.match(filename):
                continue
            file_path = os.path.realpath(os.path.join(base_dir, filename))
            if file_path.startswith(base_dir + os.sep) and os.path.isfile(file_path):
                pictures.append((filename, file_path))
    return pictures


def _account_record(user) -> Dict:
    return {
        'user_id': user.user_id,
        'username': user.username,
        'role': user.role,
        'account_scope': user.account_scope,
        'created_at': user.created_at,
        'last_login': user.last_login,
        'two_factor_enabled': bool(user.totp_enabled),
        'push_subscriptions': len(user.push_subscriptions or []),
        'preferences': user.preferences,
    }


def _locations_record(user) -> List[Dict]:
    from utils.repo_config import get_locations_for_user, load_config

    try:
        return get_locations_for_user(load_config(), user)
    except Exception as error:
        logger.warning(f"Export: could not list locations of {user.username}: {error}")
        return []


def _write_json(archive: zipfile.ZipFile, name: str, payload) -> None:
    archive.writestr(name, json.dumps(payload, indent=2, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)


def _compression_for(filename: str) -> int:
    return zipfile.ZIP_STORED if os.path.splitext(filename)[1].lower() in _STORED_EXTENSIONS else zipfile.ZIP_DEFLATED


def build_user_export(user) -> Tuple[IO[bytes], str]:
    """Write a ZIP of everything stored about ``user``; return ``(file object at offset 0, download name)``.

    The archive goes to a temporary file rather than memory, since pictures can be
    large; the caller streams it and closing it deletes it.
    """
    if not _is_valid_user_id(str(user.user_id)):
        raise ValueError('Invalid user id')

    exported_at = datetime.now(timezone.utc)
    archive_file = tempfile.TemporaryFile()
    with zipfile.ZipFile(archive_file, mode='w') as archive:
        archive.writestr(
            'README.txt',
            _EXPORT_README.format(
                exported_at=exported_at.isoformat(timespec='seconds'), username=user.username, user_id=user.user_id
            ),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        _write_json(archive, 'account.json', _account_record(user))
        _write_json(archive, 'locations.json', _locations_record(user))
        for folder, filename, file_path in _iter_user_files(str(user.user_id), include_working_files=False):
            archive.write(file_path, f"{folder}/{filename}", compress_type=_compression_for(filename))
        for filename, file_path in _legacy_astrodex_pictures(str(user.user_id)):
            archive.write(file_path, f"astrodex/images/{filename}", compress_type=_compression_for(filename))

    archive_file.seek(0)
    safe_username = re.sub(r'[^A-Za-z0-9_.-]+', '_', user.username) or 'user'
    return archive_file, f"myastroboard_{safe_username}_data_{exported_at.strftime('%Y%m%d')}.zip"
