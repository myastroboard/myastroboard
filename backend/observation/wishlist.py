"""Wishlist storage and business logic (v1.5).

A wishlist item records **intent**: an object the user wants to capture. It is the only
new persistent state Session Analytics introduces; everything else in v1.5 is derived.

Two deliberate design rules
---------------------------
1. **"Captured" is never stored.** Whether a wishlist object has been captured is
   recomputed on every read from the Observation Log and the Astrodex (see
   :func:`annotate_captured`). A stored boolean would go stale the moment an entry is
   edited or a session deleted, and silently-wrong progress is worse than none.
2. **Coordinates are resolved and frozen at add time.** ``ra_deg``/``dec_deg`` come from
   :func:`observation.target_coordinates.resolve_target`, so the visibility pass is a
   pure numeric loop and never has to re-parse the heterogeneous ``ra`` field that Plan
   My Night and the Observation Log carry (see that module's docstring).

Storage mirrors ``observation_sessions``: one JSON file per user, a per-user write lock,
and the atomic backup / temp-write / validate / replace / restore sequence. Wishlists are
permanently private, like the Observation Log - there is no shared or merged view.
"""

import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from observation import target_coordinates
from utils import normalize_catalogue_key as _normalize_key
from utils.constants import DATA_DIR, MAX_WISHLIST_ITEMS
from utils.file_lock import interprocess_lock
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Per-user write locks, so two concurrent saves cannot interleave.
_user_save_locks: Dict[str, threading.Lock] = {}
_user_save_locks_mutex = threading.Lock()


def _get_user_save_lock(user_id: str) -> threading.Lock:
    """Get or create a per-user lock for serializing wishlist file writes."""
    with _user_save_locks_mutex:
        if user_id not in _user_save_locks:
            _user_save_locks[user_id] = threading.Lock()
        return _user_save_locks[user_id]


# Wishlist data directory (top-level, mirrors data/observation_sessions/). Defined here
# rather than in utils/constants.py so test fixtures can monkeypatch this module
# attribute, exactly like observation_sessions.OBSERVATION_SESSIONS_DIR.
WISHLIST_DIR = os.path.join(DATA_DIR, 'wishlist')

WISHLIST_FILE_SUFFIX = '_wishlist.json'

PRIORITIES = ('high', 'normal', 'low')
DEFAULT_PRIORITY = 'normal'

# Where an item came from - display-only, but it tells the user why something is on the
# list months later, and lets the beginner-catalog seeding be recognised.
SOURCES = ('skytonight', 'catalogue_collection', 'beginner_catalog', 'astrodex', 'manual')
DEFAULT_SOURCE = 'manual'

# Fields a PATCH may change. Everything else - the frozen target identity, the resolved
# coordinates, the ids and timestamps - is set once at add time.
UPDATABLE_FIELDS = ('priority', 'notes')

_MAX_NOTES_LENGTH = 2000

# Categories whose objects move measurably between sessions, so a frozen RA/Dec would be
# wrong within weeks. They are still legitimate wishes ("photograph Jupiter"), they just
# never get a fixed-coordinate visibility window - the same distinction
# ``observation/visibility_calendar.py`` draws with its own _UNSUPPORTED_CATEGORIES.
MOVING_CATEGORIES = ('bodies', 'comets')
_MOVING_TYPE_TOKENS = ('planet', 'comet', 'asteroid', 'moon', 'minor')


def _is_moving_target(category: Any, object_type: Any) -> bool:
    """Whether a resolved target's position changes over the horizon of a wishlist."""
    if str(category or '').strip().lower() in MOVING_CATEGORIES:
        return True
    lowered = str(object_type or '').strip().lower()
    return any(token in lowered for token in _MOVING_TYPE_TOKENS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_wishlist_path(path: str) -> str:
    """Resolve *path* and verify it lives inside WISHLIST_DIR.

    Same realpath + startswith containment check ``observation_sessions`` uses, which is
    the pattern CodeQL's py/path-injection query recognises as a sanitizer barrier;
    callers must use the returned resolved path. WISHLIST_DIR is read at call time so
    test fixtures that monkeypatch it are honoured.
    """
    base_real = os.path.realpath(WISHLIST_DIR)
    resolved = os.path.realpath(path)
    if not resolved.startswith(base_real + os.sep):
        raise ValueError(f'Path outside wishlist directory: {path!r}')
    return resolved


def ensure_wishlist_directories() -> None:
    """Ensure the wishlist data directory exists."""
    os.makedirs(WISHLIST_DIR, exist_ok=True)


def get_user_wishlist_file(user_id: str) -> str:
    """Path to a user's wishlist file, keyed on their UUID."""
    ensure_wishlist_directories()
    return _safe_wishlist_path(os.path.join(WISHLIST_DIR, f'{user_id}{WISHLIST_FILE_SUFFIX}'))


def _clean_text(value: Any, max_length: int = _MAX_NOTES_LENGTH) -> str:
    return str(value or '').strip()[:max_length]


def _optional_text(value: Any, max_length: int = 200) -> Optional[str]:
    cleaned = _clean_text(value, max_length)
    return cleaned or None


def _default_payload(user_id: str, username: Optional[str] = None) -> Dict[str, Any]:
    now = _now_iso()
    return {
        'user_id': user_id,
        'username': username or 'unknown',
        'items': [],
        'created_at': now,
        'updated_at': now,
    }


def load_user_wishlist(user_id: str, username: Optional[str] = None) -> Dict[str, Any]:
    """Load a user's wishlist.

    Never raises: a corrupted file is backed up to ``.corrupted.<timestamp>`` and an
    empty payload returned, mirroring ``observation_sessions.load_user_sessions``.
    """
    try:
        file_path = get_user_wishlist_file(user_id)
    except (ValueError, OSError) as error:
        logger.error(f'Cannot resolve wishlist file for user {user_id}: {error}')
        return _default_payload(user_id, username)

    if not os.path.exists(file_path):
        return _default_payload(user_id, username)

    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)
    except json.JSONDecodeError as error:
        logger.error(f'Error loading wishlist for user {user_id}: {error}')
        backup_path = file_path + '.corrupted.' + datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            shutil.copy2(file_path, backup_path)
            logger.info(f'Backed up corrupted wishlist to {backup_path}')
        except Exception as backup_error:
            logger.error(f'Failed to backup corrupted wishlist: {backup_error}')
        return _default_payload(user_id, username)
    except Exception as error:
        logger.error(f'Error loading wishlist for user {user_id}: {error}')
        return _default_payload(user_id, username)

    if not isinstance(data, dict):
        return _default_payload(user_id, username)

    data.setdefault('user_id', user_id)
    data.setdefault('created_at', _now_iso())
    data.setdefault('updated_at', _now_iso())
    if not isinstance(data.get('items'), list):
        data['items'] = []
    data['items'] = [item for item in data['items'] if isinstance(item, dict)]
    data.setdefault('username', username or 'unknown')
    return data


def validate_wishlist_json(file_path: str) -> Tuple[bool, str]:
    """Validate that a file contains a well-formed wishlist payload."""
    try:
        safe_path = _safe_wishlist_path(file_path)
        with open(safe_path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)

        if not isinstance(data, dict):
            return False, 'JSON root is not a dictionary'
        if 'username' not in data:
            return False, "Missing 'username' field"
        if not isinstance(data.get('items'), list):
            return False, "Missing or invalid 'items' field"

        for index, item in enumerate(data['items']):
            if not isinstance(item, dict):
                return False, f'Item {index} must be an object'
            if not item.get('id'):
                return False, f"Item {index} missing 'id' field"
            if not item.get('name'):
                return False, f"Item {index} missing 'name' field"
            if item.get('priority') not in PRIORITIES:
                return False, f'Item {index} has an invalid priority'

        return True, ''
    except json.JSONDecodeError as error:
        return False, f'Invalid JSON: {error}'
    except Exception as error:
        return False, f'Validation error: {error}'


def save_user_wishlist(user_id: str, wishlist_data: Dict[str, Any], username: Optional[str] = None) -> bool:
    """Save a user's wishlist through the atomic backup/validate/replace sequence."""
    try:
        file_path = get_user_wishlist_file(user_id)
    except (ValueError, OSError) as error:
        logger.error(f'Cannot resolve wishlist file for user {user_id}: {error}')
        return False

    temp_path = file_path + '.tmp'
    backup_path = file_path + '.backup'

    # The thread lock serializes this worker; the file lock serializes every gunicorn worker
    with _get_user_save_lock(user_id), interprocess_lock(file_path + '.lock'):
        return _save_user_wishlist_locked(user_id, username, wishlist_data, file_path, temp_path, backup_path)


def _save_user_wishlist_locked(
    user_id: str,
    username: Optional[str],
    wishlist_data: Dict[str, Any],
    file_path: str,
    temp_path: str,
    backup_path: str,
) -> bool:
    backup_created = False

    try:
        wishlist_data['updated_at'] = _now_iso()
        wishlist_data['user_id'] = user_id
        if username:
            wishlist_data['username'] = username
        wishlist_data.setdefault('username', username or 'unknown')
        wishlist_data.setdefault('created_at', _now_iso())

        if os.path.exists(file_path):
            try:
                shutil.copy2(file_path, backup_path)
                backup_created = True
            except Exception as backup_error:
                logger.error(f'Failed to create wishlist backup for user {user_id}: {backup_error}')
                # Continue anyway - the atomic replace still provides some safety

        with open(temp_path, 'w', encoding='utf-8') as file_obj:
            json.dump(wishlist_data, file_obj, indent=2, ensure_ascii=False)

        is_valid, error_message = validate_wishlist_json(temp_path)
        if not is_valid:
            raise ValueError(f'JSON validation failed: {error_message}')

        os.replace(temp_path, file_path)

        if backup_created and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception as cleanup_error:  # pragma: no cover
                logger.warning(f'Failed to remove wishlist backup: {cleanup_error}')

        return True

    except Exception as error:
        logger.error(f'Error saving wishlist for user {user_id}: {error}')

        if backup_created and os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, file_path)
                logger.info(f'Restored wishlist from backup for user {user_id}')
            except Exception as restore_error:  # pragma: no cover
                logger.error(f'Failed to restore wishlist from backup: {restore_error}')

        for cleanup_path in (temp_path, backup_path):
            if os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                except Exception as cleanup_error:  # pragma: no cover
                    logger.warning(f'Failed to remove {cleanup_path}: {cleanup_error}')

        return False


# ---------------------------------------------------------------------------
# Identity and deduplication
# ---------------------------------------------------------------------------


def item_key(item: Dict[str, Any]) -> str:
    """Cross-catalogue identity of a wishlist item.

    The dataset's ``catalogue_group_id`` when the object resolved, so "M 31" and
    "NGC 224" are one wish, else the normalized name.
    """
    return _clean_text(item.get('catalogue_group_id'), 120) or _normalize_key(item.get('name'))


def _target_keys(name: Any, group_id: Any, aliases: Any) -> set:
    """Every normalized identifier a target is known by, for duplicate detection."""
    keys = {_normalize_key(name)}
    group = _clean_text(group_id, 120)
    if group:
        keys.add(group)
    if isinstance(aliases, dict):
        keys.update(_normalize_key(value) for value in aliases.values())
    return {key for key in keys if key}


def _existing_keys(items: Sequence[Dict[str, Any]]) -> set:
    keys = set()
    for item in items:
        keys.update(_target_keys(item.get('name'), item.get('catalogue_group_id'), item.get('catalogue_aliases')))
    return keys


def build_wishlist_index(items: Sequence[Dict[str, Any]]) -> set:
    """Every identifier the user's wishlist covers, as one flat set.

    Built once per request so annotating a large SkyTonight result set stays a set
    lookup per row rather than a rescan of the wishlist - the same contract
    ``catalogue_collection.build_astrodex_index`` provides for Astrodex.
    """
    return _existing_keys([item for item in items if isinstance(item, dict)])


def is_target_in_index(
    index: set,
    name: Any,
    catalogue_group_id: Any = '',
    aliases: Any = None,
) -> bool:
    """Whether a SkyTonight/catalogue row is already on the wishlist behind *index*."""
    if not index:
        return False
    return bool(_target_keys(name, catalogue_group_id, aliases) & index)


# ---------------------------------------------------------------------------
# Item construction
# ---------------------------------------------------------------------------


def _build_item(target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build one wishlist item from a client target payload, or None when unusable."""
    name = _clean_text(target.get('name'), 200)
    if not name:
        return None

    catalogue = _clean_text(target.get('catalogue'), 80)
    identity = target_coordinates.resolve_target(name, catalogue, target.get('ra'), target.get('dec'))

    priority = str(target.get('priority') or DEFAULT_PRIORITY).strip().lower()
    if priority not in PRIORITIES:
        priority = DEFAULT_PRIORITY

    source = str(target.get('source') or DEFAULT_SOURCE).strip().lower()
    if source not in SOURCES:
        source = DEFAULT_SOURCE

    aliases = target.get('catalogue_aliases')
    now = _now_iso()

    # A moving target keeps its wish but never a frozen position: storing one would make
    # the visibility pass report a window the object has already left.
    moving = _is_moving_target(identity['category'], target.get('type') or identity['object_type'])
    ra_deg = None if moving else identity['ra_deg']
    dec_deg = None if moving else identity['dec_deg']

    return {
        'id': str(uuid.uuid4()),
        'name': name,
        'catalogue': catalogue,
        'type': _clean_text(target.get('type') or identity['object_type'], 80),
        'constellation': _clean_text(target.get('constellation') or identity['constellation'], 80),
        'catalogue_group_id': _clean_text(target.get('catalogue_group_id') or identity['group_id'], 120),
        'catalogue_aliases': aliases if isinstance(aliases, dict) else {},
        'target_id': _optional_text(identity['target_id'], 120),
        'ra_deg': ra_deg,
        'dec_deg': dec_deg,
        'resolved': bool(identity['resolved']),
        'placed': ra_deg is not None and dec_deg is not None,
        'moving': moving,
        'priority': priority,
        'notes': _clean_text(target.get('notes')),
        'source': source,
        'created_at': now,
        'updated_at': now,
    }


def add_targets(
    user_id: str,
    username: str,
    targets: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Add one or more targets, skipping duplicates and respecting the per-user cap.

    Always list-shaped, even for the single "add to wishlist" button, so there is one
    code path (see feature.md, section 5).

    Returns a report: ``added`` items, plus ``skipped_duplicates``, ``skipped_invalid``
    and ``skipped_full`` counts so the UI can say precisely what happened.
    """
    data = load_user_wishlist(user_id, username)
    items: List[Dict[str, Any]] = data['items']
    keys = _existing_keys(items)

    added: List[Dict[str, Any]] = []
    skipped_duplicates = 0
    skipped_invalid = 0
    skipped_full = 0

    for target in targets:
        if not isinstance(target, dict):
            skipped_invalid += 1
            continue
        item = _build_item(target)
        if item is None:
            skipped_invalid += 1
            continue

        item_keys = _target_keys(item.get('name'), item.get('catalogue_group_id'), item.get('catalogue_aliases'))
        if item_keys & keys:
            skipped_duplicates += 1
            continue
        if len(items) >= MAX_WISHLIST_ITEMS:
            skipped_full += 1
            continue

        items.append(item)
        keys |= item_keys
        added.append(item)

    if added and not save_user_wishlist(user_id, data, username=username):
        return {
            'added': [],
            'skipped_duplicates': skipped_duplicates,
            'skipped_invalid': skipped_invalid,
            'skipped_full': skipped_full,
            'saved': False,
        }

    return {
        'added': added,
        'skipped_duplicates': skipped_duplicates,
        'skipped_invalid': skipped_invalid,
        'skipped_full': skipped_full,
        'saved': True,
    }


def update_item(user_id: str, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an item's priority and/or notes. Returns the updated item, or None."""
    data = load_user_wishlist(user_id)

    for item in data['items']:
        if item.get('id') != item_id:
            continue

        for field in UPDATABLE_FIELDS:
            if field not in updates:
                continue
            if field == 'priority':
                priority = str(updates[field] or '').strip().lower()
                if priority not in PRIORITIES:
                    logger.warning(f'Rejected invalid wishlist priority: {updates[field]!r}')
                    return None
                item['priority'] = priority
            else:
                item['notes'] = _clean_text(updates[field])

        item['updated_at'] = _now_iso()
        return item if save_user_wishlist(user_id, data) else None

    return None


def delete_item(user_id: str, item_id: str) -> bool:
    """Remove one item. Returns False when it does not exist or the save fails."""
    data = load_user_wishlist(user_id)
    remaining = [item for item in data['items'] if item.get('id') != item_id]
    if len(remaining) == len(data['items']):
        return False
    data['items'] = remaining
    return save_user_wishlist(user_id, data)


def remove_items(user_id: str, item_ids: Iterable[str]) -> int:
    """Remove every item whose id is in *item_ids*. Returns how many were removed."""
    targets = {str(item_id) for item_id in item_ids if item_id}
    if not targets:
        return 0

    data = load_user_wishlist(user_id)
    remaining = [item for item in data['items'] if item.get('id') not in targets]
    removed = len(data['items']) - len(remaining)
    if not removed:
        return 0

    data['items'] = remaining
    return removed if save_user_wishlist(user_id, data) else 0


# ---------------------------------------------------------------------------
# Derived "captured" state
# ---------------------------------------------------------------------------


def build_captured_index(
    captured_keys: Iterable[str],
    captured_names: Iterable[str] = (),
) -> set:
    """Normalize the identifiers of everything the user has already captured.

    The caller supplies them: the blueprint layer derives the keys from the Observation
    Log entries and the Astrodex items, because this module must not depend on either.
    """
    index = {str(key).strip() for key in captured_keys if str(key or '').strip()}
    index |= {_normalize_key(name) for name in captured_names if _normalize_key(name)}
    return index


def annotate_captured(items: Sequence[Dict[str, Any]], captured_index: set) -> List[Dict[str, Any]]:
    """Return copies of *items* carrying a freshly-derived ``captured`` flag.

    Never persisted - recomputed on every read, so editing an entry or deleting a session
    is reflected immediately instead of leaving a stale boolean on disk.
    """
    annotated: List[Dict[str, Any]] = []
    for item in items:
        keys = _target_keys(item.get('name'), item.get('catalogue_group_id'), item.get('catalogue_aliases'))
        copied = dict(item)
        copied['captured'] = bool(keys & captured_index)
        annotated.append(copied)
    return annotated


def progress(annotated_items: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """The "X of Y captured" counters for the progress bar."""
    captured = sum(1 for item in annotated_items if item.get('captured'))
    return {'captured': captured, 'total': len(annotated_items)}


_PRIORITY_ORDER = {'high': 0, 'normal': 1, 'low': 2}


def sort_items(annotated_items: List[Dict[str, Any]], sort: str = 'visibility') -> List[Dict[str, Any]]:
    """Order the list for display.

    ``visibility`` (the default) puts what is observable soonest first, still-wanted
    before already-captured; ``priority`` and ``name`` are the manual alternatives.
    Items with no computed visibility sort last within their group rather than first,
    since "unknown" is not "now".
    """

    def visibility_key(item: Dict[str, Any]):
        hours = item.get('observable_hours_next')
        rank = -float(hours) if isinstance(hours, (int, float)) else 1.0
        return (bool(item.get('captured')), rank, str(item.get('name') or '').lower())

    def priority_key(item: Dict[str, Any]):
        return (
            bool(item.get('captured')),
            _PRIORITY_ORDER.get(str(item.get('priority') or ''), 1),
            str(item.get('name') or '').lower(),
        )

    def name_key(item: Dict[str, Any]):
        return (str(item.get('name') or '').lower(),)

    keys = {'visibility': visibility_key, 'priority': priority_key, 'name': name_key}
    return sorted(annotated_items, key=keys.get(sort, visibility_key))
