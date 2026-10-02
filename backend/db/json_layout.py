"""Where each per-user document lived as a JSON file before 1.7 - and still lives in archives.

The same layout serves three purposes, so it is defined once here:

- the legacy importer reads the pre-1.7 files at these paths (``db/legacy_sources.py``),
- the admin backup ZIP writes the documents back at these paths, so a backup taken with
  1.7 restores exactly like one taken with 1.6 (``blueprints/admin.py``),
- the "Download my data" export uses the same file names (``utils/user_data.py``).

Paths are relative, ``/``-separated, under the data directory (or the archive root).
"""

import re
from typing import Dict, List, Optional, Tuple

EQUIPMENT_TYPES = ('telescopes', 'cameras', 'mounts', 'filters', 'accessories', 'combinations')
# The no-combination plan's document key and its historical file name
DEFAULT_PLAN_KEY = 'default'
_DEFAULT_PLAN_FILE_SUFFIX = 'my_night'

# kind -> (folder, file name suffix after "<user_id>_")
_SIMPLE_KINDS: Dict[str, Tuple[str, str]] = {
    'astrodex': ('astrodex', 'astrodex.json'),
    'observation_sessions': ('observation_sessions', 'sessions.json'),
    'wishlist': ('wishlist', 'wishlist.json'),
}
_EQUIPMENT_FOLDER = 'equipments'
_PLAN_FOLDER = 'projects'

# Every folder holding per-user documents
DOCUMENT_FOLDERS: Tuple[str, ...] = tuple(folder for folder, _suffix in _SIMPLE_KINDS.values()) + (
    _EQUIPMENT_FOLDER,
    _PLAN_FOLDER,
)

# user ids are server-minted uuids; also accept the test/legacy shapes made of the same characters
_USER_ID = r'[A-Za-z0-9-]+'
_DOC_KEY = r'[A-Za-z0-9_-]+'


def document_path(kind: str, user_id: str, doc_key: str = '') -> str:
    """Relative JSON path of a document (raises ValueError for an unknown kind)."""
    if kind in _SIMPLE_KINDS:
        folder, suffix = _SIMPLE_KINDS[kind]
        return f'{folder}/{user_id}_{suffix}'
    if kind.startswith('equipment.') and kind[len('equipment.') :] in EQUIPMENT_TYPES:
        return f'{_EQUIPMENT_FOLDER}/{user_id}_{kind[len("equipment."):]}.json'
    if kind == 'plan':
        name = _DEFAULT_PLAN_FILE_SUFFIX if doc_key in ('', DEFAULT_PLAN_KEY) else doc_key
        return f'{_PLAN_FOLDER}/{user_id}_plan_{name}.json'
    raise ValueError(f'Unknown document kind: {kind!r}')


_PATTERNS: List[Tuple['re.Pattern[str]', str]] = [
    (re.compile(rf'^{folder}/(?P<user>{_USER_ID})_{re.escape(suffix)}$'), kind)
    for kind, (folder, suffix) in _SIMPLE_KINDS.items()
] + [
    (
        re.compile(rf'^{_EQUIPMENT_FOLDER}/(?P<user>{_USER_ID})_(?P<type>{"|".join(EQUIPMENT_TYPES)})\.json$'),
        'equipment',
    ),
    (re.compile(rf'^{_PLAN_FOLDER}/(?P<user>{_USER_ID})_plan_(?P<key>{_DOC_KEY})\.json$'), 'plan'),
]


def parse_document_path(relative_path: str) -> Optional[Tuple[str, str, str]]:
    """``(kind, user_id, doc_key)`` for a document's JSON path, or None when it is not one."""
    path = relative_path.replace('\\', '/')
    for pattern, kind in _PATTERNS:
        match = pattern.match(path)
        if not match:
            continue
        user_id = match.group('user')
        if kind == 'equipment':
            return f'equipment.{match.group("type")}', user_id, ''
        if kind == 'plan':
            key = match.group('key')
            return 'plan', user_id, DEFAULT_PLAN_KEY if key == _DEFAULT_PLAN_FILE_SUFFIX else key
        return kind, user_id, ''
    return None
