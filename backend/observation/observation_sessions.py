"""Observation Log storage and business logic (v1.3).

A *session* is the private, chronological record of what actually happened on one
observing night: when it started/ended, from where, with which equipment, under which
sky, and - through its *entries* - which targets were captured with how many frames.

Deliberate divergences from the Astrodex module this file's storage mechanics are
copied from:

- Sessions are **permanently private**. There is no ``private_mode`` toggle and no
  cross-user merged view: this is a personal logbook, not a shared gallery.
- An entry is **its own record**, the source of truth for "what happened this session"
  (planned vs. actual frames/integration/rating/notes). It is never kept in sync with
  the Astrodex item/picture it points at - both links are one-shot, frozen references,
  exactly like Plan My Night's existing add-to-astrodex action.

This module never imports ``astrodex`` or ``plan_my_night`` at module scope. Resolving
an entry to an Astrodex item is the blueprint layer's job (see
``blueprints/observation_sessions.py``); this module only stores the resulting ids via
``link_entry_to_astrodex()``.
"""

import io
import json
import os
import shutil
import textwrap
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.constants import DATA_DIR
from utils.file_lock import interprocess_lock
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Per-user write locks to prevent race conditions on concurrent saves
_user_save_locks: Dict[str, threading.Lock] = {}
_user_save_locks_mutex = threading.Lock()


def _get_user_save_lock(user_id: str) -> threading.Lock:
    """Get or create a per-user lock for serializing session file writes."""
    with _user_save_locks_mutex:
        if user_id not in _user_save_locks:
            _user_save_locks[user_id] = threading.Lock()
        return _user_save_locks[user_id]


# Observation Log data directory (top-level, mirrors data/astrodex/)
OBSERVATION_SESSIONS_DIR = os.path.join(DATA_DIR, 'observation_sessions')

SESSIONS_FILE_SUFFIX = '_sessions.json'

# Session ("trip") level fields a PUT may change. A session can span several nights
# (see NIGHT_UPDATABLE_FIELDS below) - date/start_time/end_time/sqm/seeing/transparency
# live on each night, not here. Location/equipment are fixed for the whole trip by
# product decision (not per-night). Every id/timestamp is deliberately absent: frozen
# at creation time.
SESSION_UPDATABLE_FIELDS = (
    'location_id',
    'location_name',
    'location_latitude',
    'location_longitude',
    'location_elevation',
    'combination_id',
    'combination_name',
    'notes',
)

# Night-level fields a PUT may change. moon_illumination_percent is nominally
# server-computed (the blueprint layer recomputes it whenever date/start_time change
# and includes it in the payload it passes down here - see
# blueprints/observation_sessions.py), but is coerced the same way as any other
# optional float for a client payload that happens to include it directly (tests, curl).
NIGHT_UPDATABLE_FIELDS = (
    'date',
    'start_time',
    'end_time',
    'sqm',
    'seeing',
    'transparency',
    'moon_illumination_percent',
    'notes',
)

# Entry-level fields a PUT may change - the "what actually happened" numbers, plus
# which night this entry belongs to. The target identity snapshot
# (name/catalogue/ra/dec/...) is frozen at add time, matching Plan My Night entries, and
# the two astrodex_* pointers are set through link_entry_to_astrodex() rather than by a
# client payload. combination_id/combination_name are an optional per-entry override of
# the session's own equipment (null means "same as the session") - mirrors Astrodex's
# per-picture combination_id, one level up.
ENTRY_UPDATABLE_FIELDS = (
    'night_id',
    'frame_count',
    'sub_exposure_seconds',
    'integration_minutes',
    'rating',
    'notes',
    'combination_id',
    'combination_name',
    'combination_used_components',
)

# 7Timer's ASTRO scales, reused verbatim for unit consistency with the rest of the app
# (astroweather/seeing_forecast_7timer.py): seeing 1=best..8=worst, transparency
# 1=worst..8=best.
SKY_SCALE_MIN = 1
SKY_SCALE_MAX = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_sessions_path(path: str) -> str:
    """Resolve *path* and verify it lives inside OBSERVATION_SESSIONS_DIR.

    This is the canonical sanitizer for path expressions in this module. The
    containment check uses realpath + startswith (rather than os.path.commonpath)
    because that is the pattern CodeQL's py/path-injection query recognises as a
    sanitizer barrier, and callers must use the *returned* resolved path.

    OBSERVATION_SESSIONS_DIR is read at call time (not cached) so test fixtures that
    monkeypatch it are honoured.

    Raises ValueError if the path would escape the directory (which also excludes the
    directory itself, never a valid file path).
    """
    base_real = os.path.realpath(OBSERVATION_SESSIONS_DIR)
    resolved = os.path.realpath(path)
    if not resolved.startswith(base_real + os.sep):
        raise ValueError(f'Path outside observation sessions directory: {path!r}')
    return resolved


def _coerce_optional_float(value: Any, minimum: Optional[float] = None, maximum: Optional[float] = None):
    """Best-effort float parse for a loosely-typed numeric field.

    Anything empty, unparseable or out of range becomes None rather than an error -
    same trust level Astrodex applies to its own free-text picture fields.
    """
    if value is None or value == '':
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _coerce_optional_int(value: Any, minimum: Optional[int] = None, maximum: Optional[int] = None):
    """Best-effort int parse for a loosely-typed numeric field (see _coerce_optional_float)."""
    if value is None or value == '':
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _coerce_sky_scale(value: Any):
    """Coerce a seeing/transparency value onto 7Timer's shared 1-8 integer scale."""
    return _coerce_optional_int(value, SKY_SCALE_MIN, SKY_SCALE_MAX)


def _clean_text(value: Any, max_length: int = 5000) -> str:
    """Normalize a free-text field to a bounded string."""
    if value is None:
        return ''
    return str(value).strip()[:max_length]


def _optional_text(value: Any, max_length: int = 200):
    """Normalize an optional short label, mapping empty to None."""
    text = _clean_text(value, max_length)
    return text or None


def attachments_dir() -> str:
    """Attachment files live in a subdirectory of OBSERVATION_SESSIONS_DIR - a function,
    not a module-level constant, so it's read at call time (like _safe_sessions_path())
    and honours test fixtures that monkeypatch OBSERVATION_SESSIONS_DIR. Already covered
    by the admin backup ZIP's existing recursive `observation_sessions` entry - no new
    backup/restore wiring needed."""
    return os.path.join(OBSERVATION_SESSIONS_DIR, 'attachments')


def ensure_observation_sessions_directories() -> None:
    """Ensure the Observation Log data directory (and its attachments subdirectory) exist."""
    os.makedirs(OBSERVATION_SESSIONS_DIR, exist_ok=True)
    os.makedirs(attachments_dir(), exist_ok=True)


def get_user_sessions_file(user_id: str) -> str:
    """Get the path to a user's observation sessions file using their UUID."""
    ensure_observation_sessions_directories()
    return _safe_sessions_path(os.path.join(OBSERVATION_SESSIONS_DIR, f'{user_id}{SESSIONS_FILE_SUFFIX}'))


def _default_payload(user_id: str, username: Optional[str] = None) -> Dict:
    return {
        'user_id': user_id,
        'username': username or 'unknown',
        'created_at': _now_iso(),
        'updated_at': _now_iso(),
        'sessions': [],
    }


def _migrate_session_to_nights(session: Dict) -> bool:
    """Transparent read-time upgrade for a pre-v1.3.1 session.

    Folds the old scalar date/start_time/end_time/sqm/seeing/transparency into a
    single-element ``nights`` list, and stamps every entry that has no ``night_id`` yet
    with that night's id. A no-op (returns False) once a session already has a non-empty
    ``nights`` list. Lazy and one-time in effect: this runs on every load, but nothing
    is written to disk until the next actual save (mirroring how a corrupted-file
    recovery is only persisted on the caller's next write, not forced here).
    """
    if isinstance(session.get('nights'), list) and session['nights']:
        return False

    now = _now_iso()
    night = {
        'id': str(uuid.uuid4()),
        'date': session.get('date') or '',
        'start_time': session.get('start_time'),
        'end_time': session.get('end_time'),
        'sqm': session.get('sqm'),
        'seeing': session.get('seeing'),
        'transparency': session.get('transparency'),
        'moon_illumination_percent': None,
        'notes': '',
        'created_at': session.get('created_at') or now,
        'updated_at': now,
    }
    session['nights'] = [night]

    for entry in session.get('entries', []) or []:
        if isinstance(entry, dict) and not entry.get('night_id'):
            entry['night_id'] = night['id']

    # Retired as session-level fields (see SESSION_UPDATABLE_FIELDS/NIGHT_UPDATABLE_FIELDS).
    for stale_field in ('date', 'start_time', 'end_time', 'sqm', 'seeing', 'transparency'):
        session.pop(stale_field, None)

    return True


def load_user_sessions(user_id: str, username: Optional[str] = None) -> Dict:
    """Load a user's observation sessions.

    Never raises to the caller: a corrupted file is backed up to
    ``.corrupted.<timestamp>`` and an empty payload is returned (the file is overwritten
    on the next save), mirroring ``astrodex.load_user_astrodex``.
    """
    try:
        file_path = get_user_sessions_file(user_id)
    except (ValueError, OSError) as error:
        logger.error(f'Cannot resolve sessions file for user {user_id}: {error}')
        return _default_payload(user_id, username)

    if not os.path.exists(file_path):
        return _default_payload(user_id, username)

    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)
    except json.JSONDecodeError as error:
        logger.error(f'Error loading observation sessions for user {user_id}: {error}')
        logger.error('Corrupted file will be backed up and reset')
        backup_path = file_path + '.corrupted.' + datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            shutil.copy2(file_path, backup_path)
            logger.info(f'Backed up corrupted file to {backup_path}')
        except Exception as backup_error:
            logger.error(f'Failed to backup corrupted file: {backup_error}')
        return _default_payload(user_id, username)
    except Exception as error:
        logger.error(f'Error loading observation sessions for user {user_id}: {error}')
        return _default_payload(user_id, username)

    if not isinstance(data, dict):
        return _default_payload(user_id, username)

    data.setdefault('user_id', user_id)
    data.setdefault('created_at', _now_iso())
    data.setdefault('updated_at', _now_iso())
    if not isinstance(data.get('sessions'), list):
        data['sessions'] = []
    if username and data.get('username') != username:
        data['username'] = username
        data['user_id'] = user_id
        save_user_sessions(user_id, data, username=username)
    data.setdefault('username', username or 'unknown')

    for session in data['sessions']:
        if isinstance(session, dict):
            _migrate_session_to_nights(session)

    return data


def validate_sessions_json(file_path: str) -> Tuple[bool, str]:
    """Validate that a file contains a well-formed observation sessions payload.

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        safe_path = _safe_sessions_path(file_path)
        with open(safe_path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)

        if not isinstance(data, dict):
            return False, 'JSON root is not a dictionary'

        if 'username' not in data:
            return False, "Missing 'username' field"

        if 'sessions' not in data or not isinstance(data['sessions'], list):
            return False, "Missing or invalid 'sessions' field"

        for index, session in enumerate(data['sessions']):
            if not isinstance(session, dict):
                return False, f'Session {index} must be an object'
            if not session.get('id'):
                return False, f"Session {index} missing 'id' field"
            nights = session.get('nights')
            if not isinstance(nights, list) or not nights:
                return False, f"Session {index} missing 'nights' field"
            night_ids = set()
            for night in nights:
                if not isinstance(night, dict) or not night.get('id') or not night.get('date'):
                    return False, f'Session {index} has an invalid night entry'
                night_ids.add(night['id'])
            if not isinstance(session.get('entries', []), list):
                return False, f"Session {index} has an invalid 'entries' field"
            for entry in session.get('entries', []):
                if isinstance(entry, dict) and entry.get('night_id') and entry['night_id'] not in night_ids:
                    return False, f'Session {index} has an entry referencing an unknown night'
            if 'attachments' in session and not isinstance(session['attachments'], list):
                return False, f"Session {index} has an invalid 'attachments' field"

        return True, ''
    except json.JSONDecodeError as error:
        return False, f'Invalid JSON: {error}'
    except Exception as error:
        return False, f'Validation error: {error}'


def save_user_sessions(user_id: str, sessions_data: Dict, username: Optional[str] = None) -> bool:
    """Save a user's observation sessions with the full atomic backup/recovery sequence.

    Process (identical to astrodex.save_user_astrodex):
      1. Back up the existing file
      2. Write to a temporary file
      3. Validate the temporary file
      4. Atomically replace the original
      5. Drop the backup on success, restore from it on failure
    """
    try:
        file_path = get_user_sessions_file(user_id)
    except (ValueError, OSError) as error:
        logger.error(f'Cannot resolve sessions file for user {user_id}: {error}')
        return False

    temp_path = file_path + '.tmp'
    backup_path = file_path + '.backup'

    # The thread lock serializes this worker; the file lock serializes every gunicorn worker
    with _get_user_save_lock(user_id), interprocess_lock(file_path + '.lock'):
        return _save_user_sessions_locked(user_id, username, sessions_data, file_path, temp_path, backup_path)


def _save_user_sessions_locked(
    user_id: str,
    username: Optional[str],
    sessions_data: Dict,
    file_path: str,
    temp_path: str,
    backup_path: str,
) -> bool:
    backup_created = False

    try:
        sessions_data['updated_at'] = _now_iso()
        sessions_data['user_id'] = user_id
        if username:
            sessions_data['username'] = username
        sessions_data.setdefault('username', username or 'unknown')
        sessions_data.setdefault('created_at', _now_iso())

        if os.path.exists(file_path):
            try:
                shutil.copy2(file_path, backup_path)
                backup_created = True
                logger.debug(f'Created backup: {backup_path}')
            except Exception as backup_error:
                logger.error(f'Failed to create backup for user {user_id}: {backup_error}')
                # Continue anyway - the atomic replace still provides some safety

        with open(temp_path, 'w', encoding='utf-8') as file_obj:
            json.dump(sessions_data, file_obj, indent=2, ensure_ascii=False)

        is_valid, error_message = validate_sessions_json(temp_path)
        if not is_valid:
            raise ValueError(f'JSON validation failed: {error_message}')

        os.replace(temp_path, file_path)
        logger.info(f'Successfully saved observation sessions for user {user_id}')

        if backup_created and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception as cleanup_error:  # pragma: no cover
                logger.warning(f'Failed to remove backup: {cleanup_error}')

        return True

    except Exception as error:
        logger.error(f'Error saving observation sessions for user {user_id}: {error}')

        if backup_created and os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, file_path)
                logger.info(f'Restored observation sessions from backup for user {user_id}')
            except Exception as restore_error:  # pragma: no cover
                logger.error(f'Failed to restore from backup: {restore_error}')

        for cleanup_path in (temp_path, backup_path):
            if os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                except Exception as cleanup_error:  # pragma: no cover
                    logger.warning(f'Failed to remove {cleanup_path}: {cleanup_error}')

        return False


def _iter_session_files() -> List[str]:
    """Return every observation sessions file path (all users), safely resolved."""
    if not os.path.isdir(OBSERVATION_SESSIONS_DIR):
        return []
    paths: List[str] = []
    for filename in os.listdir(OBSERVATION_SESSIONS_DIR):
        if not filename.endswith(SESSIONS_FILE_SUFFIX):
            continue
        try:
            paths.append(_safe_sessions_path(os.path.join(OBSERVATION_SESSIONS_DIR, filename)))
        except ValueError:  # pragma: no cover
            continue  # failed containment check — skip
    return paths


def load_all_users_sessions(usernames_by_id: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Load every user's sessions.

    Used by the delete-guard scans below, not by any UI route - sessions are private and
    never shown across users.
    """
    ensure_observation_sessions_directories()
    usernames_by_id = usernames_by_id or {}

    collections: List[Dict] = []
    for filename in sorted(os.listdir(OBSERVATION_SESSIONS_DIR)):
        if not filename.endswith(SESSIONS_FILE_SUFFIX):
            continue
        user_id = filename[: -len(SESSIONS_FILE_SUFFIX)]
        data = load_user_sessions(user_id, usernames_by_id.get(user_id))
        collections.append(
            {
                'user_id': user_id,
                'username': data.get('username') or usernames_by_id.get(user_id) or 'unknown',
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
                'sessions': data.get('sessions', []),
            }
        )
    return collections


def _session_sort_key(session: Dict) -> Tuple[str, str]:
    """Sort key placing the most recent observation date (then creation) first.

    A session's "date" for sorting purposes is the earliest of its nights - a
    multi-night trip sorts by when it started.
    """
    nights = [night for night in session.get('nights', []) or [] if isinstance(night, dict)]
    dates = [str(night.get('date') or '') for night in nights]
    primary_date = min(dates) if dates else ''
    return (primary_date, str(session.get('created_at') or ''))


def get_user_sessions(user_id: str) -> List[Dict]:
    """Return the user's own sessions, newest observation date first."""
    data = load_user_sessions(user_id)
    sessions = [session for session in data.get('sessions', []) if isinstance(session, dict)]
    return sorted(sessions, key=_session_sort_key, reverse=True)


def get_session(user_id: str, session_id: str) -> Optional[Dict]:
    """Return one of the user's own sessions, or None when it doesn't exist."""
    for session in load_user_sessions(user_id).get('sessions', []):
        if isinstance(session, dict) and session.get('id') == session_id:
            return session
    return None


def build_astrodex_session_backlink_index(user_id: str) -> Tuple[Dict[str, List[Dict]], Dict[str, Dict]]:
    """One-pass reverse index: Astrodex item/picture id -> the session entries pointing at it.

    Sessions are private, so this only ever scans the caller's own file (unlike the
    combination/location guards, which scan every user). Built once per request by the
    Astrodex blueprint and used to enrich every item/picture in a collection response,
    rather than re-scanning the user's sessions per item.

    Returns ``(matches_by_item_id, first_match_by_picture_id)`` where each match is
    ``{session_id, session_date, entry_id}``. An item can accumulate several matching
    entries over multiple nights, so it gets a list; a picture is one specific photo, so
    it only ever needs its single (first-found) match.
    """
    matches_by_item: Dict[str, List[Dict]] = {}
    first_match_by_picture: Dict[str, Dict] = {}

    for session in get_user_sessions(user_id):
        nights_by_id = {night['id']: night for night in session.get('nights', []) or [] if isinstance(night, dict)}
        for entry in session.get('entries', []) or []:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get('astrodex_item_id')
            picture_id = entry.get('astrodex_picture_id')
            if not item_id and not picture_id:
                continue
            # The date of *this entry's own* night, not just the session's primary one -
            # a multi-night trip can have the same target logged (and linked) on
            # several different nights.
            entry_night = nights_by_id.get(entry.get('night_id'))
            session_date = entry_night['date'] if entry_night else _primary_night(session).get('date')
            match = {
                'session_id': session.get('id'),
                'session_date': session_date,
                'entry_id': entry.get('id'),
            }
            if item_id:
                matches_by_item.setdefault(item_id, []).append(match)
            if picture_id and picture_id not in first_match_by_picture:
                first_match_by_picture[picture_id] = match

    return matches_by_item, first_match_by_picture


def _apply_session_fields(session: Dict, source: Dict, fields=SESSION_UPDATABLE_FIELDS) -> None:
    """Copy/normalize the session ("trip") level fields present in *source* onto *session*."""
    for field in fields:
        if field not in source:
            continue
        value = source[field]
        if field in ('location_id', 'location_name', 'combination_id', 'combination_name'):
            session[field] = _optional_text(value)
        elif field == 'location_latitude':
            session[field] = _coerce_optional_float(value, -90, 90)
        elif field == 'location_longitude':
            session[field] = _coerce_optional_float(value, -180, 180)
        elif field == 'location_elevation':
            session[field] = _coerce_optional_float(value)
        else:
            session[field] = _clean_text(value)


def _build_night_payload(night_data: Dict) -> Dict:
    """Build one night sub-object of a session (mirrors the scalar fields a session
    used to carry directly, pre-v1.3.1 - see NIGHT_UPDATABLE_FIELDS)."""
    now = _now_iso()
    return {
        'id': str(uuid.uuid4()),
        'date': _clean_text(night_data.get('date'), 32),
        'start_time': _optional_text(night_data.get('start_time'), 64),
        'end_time': _optional_text(night_data.get('end_time'), 64),
        'sqm': _coerce_optional_float(night_data.get('sqm'), 0, 30),
        'seeing': _coerce_sky_scale(night_data.get('seeing')),
        'transparency': _coerce_sky_scale(night_data.get('transparency')),
        'moon_illumination_percent': _coerce_optional_float(night_data.get('moon_illumination_percent'), 0, 100),
        'notes': _clean_text(night_data.get('notes')),
        'created_at': now,
        'updated_at': now,
    }


def _apply_night_fields(night: Dict, source: Dict) -> None:
    """Copy/normalize the night-level fields present in *source* onto *night*."""
    for field in NIGHT_UPDATABLE_FIELDS:
        if field not in source:
            continue
        value = source[field]
        if field == 'date':
            night['date'] = _clean_text(value, 32)
        elif field in ('start_time', 'end_time'):
            night[field] = _optional_text(value, 64)
        elif field == 'sqm':
            night[field] = _coerce_optional_float(value, 0, 30)
        elif field in ('seeing', 'transparency'):
            night[field] = _coerce_sky_scale(value)
        elif field == 'moon_illumination_percent':
            night[field] = _coerce_optional_float(value, 0, 100)
        else:
            night[field] = _clean_text(value)


def get_night(session: Dict, night_id: Optional[str]) -> Optional[Dict]:
    """Look up one of *session*'s nights by id, or None if it doesn't resolve.

    Public (unlike _sorted_nights()/_primary_night()) because the blueprint layer needs
    it to resolve an entry's own night when attaching an Astrodex picture.
    """
    if not night_id:
        return None
    for night in session.get('nights', []) or []:
        if isinstance(night, dict) and night.get('id') == night_id:
            return night
    return None


def _sorted_nights(session: Dict) -> List[Dict]:
    """A session's nights, chronologically - the storage order isn't guaranteed to be
    (add_night() always appends, and import-from-plan can insert an earlier date after
    a later one already exists)."""
    nights = [night for night in session.get('nights', []) or [] if isinstance(night, dict)]
    return sorted(nights, key=lambda night: str(night.get('date') or ''))


def _primary_night(session: Dict) -> Dict:
    """The session's earliest night. Used wherever code still needs exactly one night's
    conditions (the PDF info panel pending its dedicated per-night breakdown - see
    docs/OBSERVATION_LOG.md). Always non-empty for a session that went through
    load_user_sessions()'s migration; ``{}`` only for a hand-built dict in a test."""
    nights = _sorted_nights(session)
    return nights[0] if nights else {}


def session_date_range(session: Dict) -> Tuple[str, str]:
    """(earliest, latest) night date, for display - identical values for a single-night
    session, which is still the overwhelmingly common case."""
    nights = _sorted_nights(session)
    if not nights:
        return '', ''
    dates = [str(night.get('date') or '') for night in nights]
    return dates[0], dates[-1]


def create_session(user_id: str, username: str, session_data: Dict) -> Optional[Dict]:
    """Create a new observation session, seeded with one night.

    ``date`` is required (an undated night is not a log entry) and seeds that first
    night's date; ``start_time``/``end_time``/``sqm``/``seeing``/``transparency`` seed
    its other fields the same way they used to seed the session itself. Everything else
    (location/equipment/notes, all session/"trip" level) is optional and may be filled
    in later through update_session(); additional nights are added through add_night().
    """
    data = load_user_sessions(user_id, username)

    session_date = _clean_text(session_data.get('date'), 32)
    if not session_date:
        logger.error('Session date is required')
        return None

    now = _now_iso()
    first_night = _build_night_payload(
        {
            'date': session_date,
            'start_time': session_data.get('start_time'),
            'end_time': session_data.get('end_time'),
            'sqm': session_data.get('sqm'),
            'seeing': session_data.get('seeing'),
            'transparency': session_data.get('transparency'),
            'moon_illumination_percent': session_data.get('moon_illumination_percent'),
        }
    )
    session: Dict[str, Any] = {
        'id': str(uuid.uuid4()),
        'location_id': None,
        'location_name': None,
        'location_latitude': None,
        'location_longitude': None,
        'location_elevation': None,
        'combination_id': None,
        'combination_name': None,
        'notes': '',
        'nights': [first_night],
        'entries': [],
        'attachments': [],
        'imported_from_plan_combination_id': _optional_text(session_data.get('imported_from_plan_combination_id')),
        'created_at': now,
        'updated_at': now,
    }
    _apply_session_fields(session, session_data)

    data.setdefault('sessions', []).append(session)

    if save_user_sessions(user_id, data, username=username):
        return session
    return None


def update_session(user_id: str, session_id: str, updates: Dict) -> Optional[Dict]:
    """Update session ("trip") level fields - location, equipment, notes. Nights and
    entries are edited through their own dedicated functions (add_night()/
    update_night()/delete_night(), add_entry()/update_entry()/delete_entry())."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        _apply_session_fields(session, updates)
        session['updated_at'] = _now_iso()

        if save_user_sessions(user_id, data):
            return session
        return None

    return None


def add_night(user_id: str, session_id: str, night_data: Dict) -> Optional[Dict]:
    """Add one more night to a multi-night session. ``date`` is required."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        night_date = _clean_text(night_data.get('date'), 32)
        if not night_date:
            logger.error('Night date is required')
            return None

        night = _build_night_payload(night_data)
        session.setdefault('nights', []).append(night)
        session['updated_at'] = _now_iso()

        if save_user_sessions(user_id, data):
            return night
        return None

    return None


def update_night(user_id: str, session_id: str, night_id: str, updates: Dict) -> Optional[Dict]:
    """Update one night's conditions/notes. A blank date keeps the previous value - a
    night, like a session before it, can never become undated."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        for night in session.get('nights', []):
            if not isinstance(night, dict) or night.get('id') != night_id:
                continue

            previous_date = night.get('date')
            _apply_night_fields(night, updates)
            if not night.get('date'):
                night['date'] = previous_date
            night['updated_at'] = _now_iso()
            session['updated_at'] = night['updated_at']

            if save_user_sessions(user_id, data):
                return night
            return None

    return None


def delete_night(user_id: str, session_id: str, night_id: str) -> bool:
    """Remove one night.

    Refuses when it's the session's last remaining night (a session must always have
    at least one - delete the whole session instead), or when any entry still points at
    it: matches this app's established delete-guard convention elsewhere (blocked while
    referenced, never silently orphaning) rather than leaving a dangling ``night_id``
    behind. Move or delete those entries first.
    """
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        nights = session.get('nights', [])
        if len(nights) <= 1:
            return False
        if not any(isinstance(night, dict) and night.get('id') == night_id for night in nights):
            return False
        if any(isinstance(entry, dict) and entry.get('night_id') == night_id for entry in session.get('entries', [])):
            return False

        session['nights'] = [night for night in nights if not (isinstance(night, dict) and night.get('id') == night_id)]
        session['updated_at'] = _now_iso()
        return save_user_sessions(user_id, data)

    return False


def delete_session(user_id: str, session_id: str) -> bool:
    """Delete a session, all of its entries, and its own attachment files.

    Any Astrodex item/picture an entry pointed at is deliberately left untouched - that
    link is a soft, one-way reference into a *different* feature's data (see the module
    docstring). Attachments are different: they belong to this session alone (the only
    place their files are ever uploaded), so they are deleted along with it.
    """
    data = load_user_sessions(user_id)
    sessions = data.get('sessions', [])
    target = next(
        (session for session in sessions if isinstance(session, dict) and session.get('id') == session_id), None
    )
    if target is None:
        return False

    for attachment in target.get('attachments', []) or []:
        if not isinstance(attachment, dict):
            continue
        file_path = _resolve_attachment_file_path(attachment.get('filename'))
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except (OSError, IOError) as error:
                logger.error(f"Error deleting attachment file {attachment.get('filename')}: {error}")

    data['sessions'] = [session for session in sessions if session is not target]
    return save_user_sessions(user_id, data)


def _resolve_attachment_file_path(filename: Optional[str]) -> Optional[str]:
    """Resolve a stored attachment filename to an absolute path inside the attachments
    directory, or None if it escapes that directory (same containment check as
    astrodex.py's own _resolve_image_file_path)."""
    if not filename:
        return None
    base_dir = os.path.realpath(attachments_dir())
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not file_path.startswith(base_dir + os.sep):
        return None
    return file_path


def _build_attachment_payload(filename: str, original_name: str, content_type: str) -> Dict:
    now = _now_iso()
    return {
        'id': str(uuid.uuid4()),
        'filename': filename,
        'original_name': _clean_text(original_name, 200),
        'content_type': _clean_text(content_type, 100),
        'display_name': None,
        'uploaded_at': now,
    }


def add_attachment(
    user_id: str, session_id: str, filename: str, original_name: str, content_type: str
) -> Optional[Dict]:
    """Record one already-uploaded attachment against a session. The file itself is
    saved to disk by the blueprint layer first, mirroring how astrodex.py's own image
    upload is split from the record that references it."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        attachment = _build_attachment_payload(filename, original_name, content_type)
        session.setdefault('attachments', []).append(attachment)
        session['updated_at'] = _now_iso()

        if save_user_sessions(user_id, data):
            return attachment
        return None

    return None


def delete_attachment(user_id: str, session_id: str, attachment_id: str) -> bool:
    """Remove one attachment's metadata and delete its file from disk."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        attachments = session.get('attachments', []) or []
        target = next(
            (item for item in attachments if isinstance(item, dict) and item.get('id') == attachment_id), None
        )
        if target is None:
            return False

        file_path = _resolve_attachment_file_path(target.get('filename'))
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except (OSError, IOError) as error:
                logger.error(f"Error deleting attachment file {target.get('filename')}: {error}")

        session['attachments'] = [
            item for item in attachments if not (isinstance(item, dict) and item.get('id') == attachment_id)
        ]
        session['updated_at'] = _now_iso()
        return save_user_sessions(user_id, data)

    return False


def rename_attachment(user_id: str, session_id: str, attachment_id: str, display_name: Optional[str]) -> Optional[Dict]:
    """Set (or, given a blank/None name, clear) an attachment's custom display name.

    ``filename``/``original_name`` are left untouched - this only changes what the UI
    shows and what a download is saved as, never the file on disk or its storage key.
    """
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        attachments = session.get('attachments', []) or []
        target = next(
            (item for item in attachments if isinstance(item, dict) and item.get('id') == attachment_id), None
        )
        if target is None:
            return None

        target['display_name'] = _clean_text(display_name, 200) or None
        session['updated_at'] = _now_iso()

        if save_user_sessions(user_id, data):
            return target
        return None

    return None


def _build_entry_payload(entry_data: Dict) -> Dict:
    """Build a new session entry from a client payload.

    The target identity fields mirror plan_my_night._build_target_payload() and are a
    frozen snapshot: they are never re-resolved against SkyTonight afterwards.
    """
    now = _now_iso()
    catalogue_aliases = entry_data.get('catalogue_aliases')
    used_components = entry_data.get('combination_used_components')

    return {
        'id': str(uuid.uuid4()),
        'night_id': _optional_text(entry_data.get('night_id'), 80),
        'name': _clean_text(entry_data.get('name'), 200),
        'catalogue': _clean_text(entry_data.get('catalogue'), 80),
        'type': _clean_text(entry_data.get('type'), 80),
        'constellation': _clean_text(entry_data.get('constellation'), 80),
        'ra': entry_data.get('ra'),
        'dec': entry_data.get('dec'),
        'mag': entry_data.get('mag'),
        'size': entry_data.get('size'),
        'catalogue_group_id': _clean_text(entry_data.get('catalogue_group_id'), 80),
        'catalogue_aliases': catalogue_aliases if isinstance(catalogue_aliases, dict) else {},
        'alttime_file': _optional_text(entry_data.get('alttime_file'), 120),
        'source_plan_entry_id': _optional_text(entry_data.get('source_plan_entry_id'), 80),
        'planned_minutes': _coerce_optional_float(entry_data.get('planned_minutes'), 0),
        'frame_count': _coerce_optional_int(entry_data.get('frame_count'), 0),
        'sub_exposure_seconds': _coerce_optional_float(entry_data.get('sub_exposure_seconds'), 0),
        'integration_minutes': _coerce_optional_float(entry_data.get('integration_minutes'), 0),
        'rating': _coerce_optional_float(entry_data.get('rating'), 0, 5),
        'notes': _clean_text(entry_data.get('notes')),
        'combination_id': _optional_text(entry_data.get('combination_id')),
        'combination_name': _optional_text(entry_data.get('combination_name')),
        'combination_used_components': used_components if isinstance(used_components, dict) else None,
        'astrodex_item_id': None,
        'astrodex_picture_id': None,
        'created_at': now,
        'updated_at': now,
    }


def add_entry(user_id: str, session_id: str, entry_data: Dict) -> Optional[Dict]:
    """Add one target entry to a session.

    Does **not** resolve Astrodex itself - the blueprint layer calls
    ``_ensure_astrodex_item_for_entry()`` + ``link_entry_to_astrodex()`` afterwards
    whenever the resulting entry has ``frame_count > 0`` and no ``astrodex_item_id`` yet.
    """
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        entry_name = _clean_text(entry_data.get('name'), 200)
        if not entry_name:
            logger.error('Entry name is required')
            return None

        entry = _build_entry_payload(entry_data)
        session.setdefault('entries', []).append(entry)
        session['updated_at'] = _now_iso()

        if save_user_sessions(user_id, data):
            return entry
        return None

    return None


def update_entry(user_id: str, session_id: str, entry_id: str, updates: Dict) -> Optional[Dict]:
    """Update the "what actually happened" fields of one entry.

    Like add_entry(), this never resolves Astrodex - see that function's docstring.
    """
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        for entry in session.get('entries', []):
            if not isinstance(entry, dict) or entry.get('id') != entry_id:
                continue

            for field in ENTRY_UPDATABLE_FIELDS:
                if field not in updates:
                    continue
                value = updates[field]
                if field == 'frame_count':
                    entry[field] = _coerce_optional_int(value, 0)
                elif field == 'sub_exposure_seconds':
                    entry[field] = _coerce_optional_float(value, 0)
                elif field == 'integration_minutes':
                    entry[field] = _coerce_optional_float(value, 0)
                elif field == 'rating':
                    entry[field] = _coerce_optional_float(value, 0, 5)
                elif field == 'combination_used_components':
                    entry[field] = value if isinstance(value, dict) else None
                elif field in ('combination_id', 'combination_name'):
                    entry[field] = _optional_text(value)
                elif field == 'night_id':
                    entry[field] = _optional_text(value, 80)
                else:
                    entry[field] = _clean_text(value)

            entry['updated_at'] = _now_iso()
            session['updated_at'] = entry['updated_at']

            if save_user_sessions(user_id, data):
                return entry
            return None

    return None


def delete_entry(user_id: str, session_id: str, entry_id: str) -> bool:
    """Remove one entry from a session (never touches its linked Astrodex item/picture)."""
    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        entries = session.get('entries', [])
        original_count = len(entries)
        session['entries'] = [
            entry for entry in entries if not (isinstance(entry, dict) and entry.get('id') == entry_id)
        ]

        if len(session['entries']) < original_count:
            session['updated_at'] = _now_iso()
            return save_user_sessions(user_id, data)
        return False

    return False


def _entry_from_plan_entry(plan_entry: Dict, night_id: str) -> Dict:
    """Map one Plan My Night entry onto a fresh session entry payload for *night_id*."""
    entry = _build_entry_payload(
        {
            'night_id': night_id,
            'name': plan_entry.get('name'),
            'catalogue': plan_entry.get('catalogue'),
            'type': plan_entry.get('type'),
            'constellation': plan_entry.get('constellation'),
            'ra': plan_entry.get('ra'),
            'dec': plan_entry.get('dec'),
            'mag': plan_entry.get('mag'),
            'size': plan_entry.get('size'),
            'catalogue_group_id': plan_entry.get('catalogue_group_id'),
            'catalogue_aliases': plan_entry.get('catalogue_aliases'),
            'alttime_file': plan_entry.get('alttime_file'),
            'source_plan_entry_id': plan_entry.get('id'),
            'planned_minutes': plan_entry.get('planned_minutes'),
        }
    )
    return entry


def _find_or_create_night_for_date(
    session: Dict, date: str, start_time: Optional[str], end_time: Optional[str]
) -> Dict:
    """Find-or-create the night matching *date* within *session*.

    The storage-layer half of "day 2, import the new plan": re-importing the same
    calendar date reuses (and refreshes the start/end of) that existing night rather
    than creating a duplicate; a new date appends a new night.
    """
    for night in session.setdefault('nights', []):
        if isinstance(night, dict) and night.get('date') == date:
            if start_time:
                night['start_time'] = _optional_text(start_time, 64)
            if end_time:
                night['end_time'] = _optional_text(end_time, 64)
            night['updated_at'] = _now_iso()
            return night

    night = _build_night_payload({'date': date, 'start_time': start_time, 'end_time': end_time})
    session['nights'].append(night)
    return night


def create_session_from_plan(
    user_id: str,
    username: str,
    plan_payload: Dict,
    existing_session_id: Optional[str] = None,
) -> Optional[Dict]:
    """Seed a new session from a Plan My Night plan, or merge into an existing one.

    ``plan_payload`` is the ``plan`` dict from ``plan_my_night.get_plan_with_timeline()``
    - the caller (blueprint) is responsible for loading it. This module never imports
    plan_my_night: sessions know about plans, plans have no reason to know about sessions.

    Re-importing is idempotent at two levels: any plan entry whose id already appears as
    an entry's ``source_plan_entry_id`` in the target session is skipped, and the plan's
    date reuses an existing night of that date rather than duplicating it (see
    _find_or_create_night_for_date()).
    """
    if not isinstance(plan_payload, dict):
        return None

    plan_entries = [entry for entry in plan_payload.get('entries', []) if isinstance(entry, dict)]
    plan_date = _clean_text(plan_payload.get('plan_date'), 32) or datetime.now().strftime('%Y-%m-%d')
    plan_start = plan_payload.get('night_start')
    plan_end = plan_payload.get('night_end')

    if existing_session_id:
        data = load_user_sessions(user_id, username)
        session = next(
            (
                item
                for item in data.get('sessions', [])
                if isinstance(item, dict) and item.get('id') == existing_session_id
            ),
            None,
        )
        if session is None:
            return None

        night = _find_or_create_night_for_date(session, plan_date, plan_start, plan_end)

        already_imported = {
            str(entry.get('source_plan_entry_id'))
            for entry in session.get('entries', [])
            if isinstance(entry, dict) and entry.get('source_plan_entry_id')
        }
        entries = session.setdefault('entries', [])
        for plan_entry in plan_entries:
            if str(plan_entry.get('id')) in already_imported:
                continue
            entries.append(_entry_from_plan_entry(plan_entry, night['id']))

        session['updated_at'] = _now_iso()
        if save_user_sessions(user_id, data, username=username):
            return session
        return None

    session = create_session(
        user_id,
        username,
        {
            'date': plan_date,
            'location_id': plan_payload.get('location_id'),
            'location_name': plan_payload.get('location_name'),
            'combination_id': plan_payload.get('combination_id'),
            'combination_name': plan_payload.get('combination_name'),
            'imported_from_plan_combination_id': plan_payload.get('combination_id') or 'default',
            # The plan already knows the night's nautical-twilight window - carry it
            # over so the user isn't left retyping times they already computed.
            'start_time': plan_start,
            'end_time': plan_end,
        },
    )
    if session is None:
        return None

    data = load_user_sessions(user_id, username)
    stored = next(
        (item for item in data.get('sessions', []) if isinstance(item, dict) and item.get('id') == session['id']),
        None,
    )
    if stored is None:  # pragma: no cover - the session was just written
        return None

    first_night_id = stored['nights'][0]['id']
    stored['entries'] = [_entry_from_plan_entry(plan_entry, first_night_id) for plan_entry in plan_entries]
    stored['updated_at'] = _now_iso()

    if save_user_sessions(user_id, data, username=username):
        return stored
    return None


def link_entry_to_astrodex(
    user_id: str,
    session_id: str,
    entry_id: str,
    astrodex_item_id: str,
    astrodex_picture_id: Optional[str] = None,
) -> Optional[Dict]:
    """Store the Astrodex item (and optionally picture) an entry resolved to.

    Pure storage-layer setter with no cross-module import: the blueprint calls it for
    two different triggers - automatically after an entry gains real capture evidence
    (item id only), and explicitly when the user attaches a picture (both ids).
    Idempotent: passing the same item id again is a harmless no-op.

    ``astrodex_picture_id`` is only ever *set*, never cleared by an item-only call, so a
    later frame-count edit cannot orphan an already-attached picture.
    """
    if not astrodex_item_id:
        return None

    data = load_user_sessions(user_id)

    for session in data.get('sessions', []):
        if not isinstance(session, dict) or session.get('id') != session_id:
            continue

        for entry in session.get('entries', []):
            if not isinstance(entry, dict) or entry.get('id') != entry_id:
                continue

            entry['astrodex_item_id'] = astrodex_item_id
            if astrodex_picture_id:
                entry['astrodex_picture_id'] = astrodex_picture_id
            entry['updated_at'] = _now_iso()
            session['updated_at'] = entry['updated_at']

            if save_user_sessions(user_id, data):
                return entry
            return None

    return None


def get_session_stats(user_id: str) -> Dict:
    """Aggregate the user's own sessions into the Observation Log's header counters.

    Deliberately minimal - full analytics (per month, per equipment, sky coverage) is
    v1.5 Session Analytics' job, not this module's.
    """
    sessions = load_user_sessions(user_id).get('sessions', [])

    total_entries = 0
    total_integration_minutes = 0.0
    rating_sum = 0.0
    rating_count = 0

    for session in sessions:
        if not isinstance(session, dict):
            continue
        for entry in session.get('entries', []):
            if not isinstance(entry, dict):
                continue
            total_entries += 1
            integration = _coerce_optional_float(entry.get('integration_minutes'), 0)
            if integration:
                total_integration_minutes += integration
            rating = _coerce_optional_float(entry.get('rating'), 0, 5)
            if rating is not None:
                rating_sum += rating
                rating_count += 1

    return {
        'total_sessions': len([session for session in sessions if isinstance(session, dict)]),
        'total_entries': total_entries,
        'total_integration_minutes': round(total_integration_minutes, 2),
        'average_rating': round(rating_sum / rating_count, 1) if rating_count else None,
    }


def _count_sessions_matching(field: str, value: str) -> int:
    """Count sessions (all users) whose session-level *field* equals *value*.

    Fail-open on unreadable files (skipped), matching
    astrodex.count_pictures_for_combination / plan_my_night.count_plans_for_combination.
    """
    if not value:
        return 0
    count = 0
    for file_path in _iter_session_files():
        try:
            with open(file_path, 'r', encoding='utf-8') as file_obj:
                data = json.load(file_obj)
            for session in data.get('sessions', []):
                if isinstance(session, dict) and session.get(field) == value:
                    count += 1
        except Exception:
            continue  # unreadable file — skip, this is a best-effort count
    return count


def count_sessions_for_combination(combination_id: str) -> int:
    """Count sessions (all users) referencing an equipment combination - pre-delete check.

    A session counts once whether it's the session-level ``combination_id`` that
    matches, any of its entries' own optional per-entry override, or both - an entry's
    override (null by default, meaning "same as the session") lets a single session
    reference more than one combination across its different targets.

    Combinations are never cascade-deleted; deletion is blocked while any session
    references one (see equipment_profiles.delete_combination).
    """
    if not combination_id:
        return 0
    count = 0
    for file_path in _iter_session_files():
        try:
            with open(file_path, 'r', encoding='utf-8') as file_obj:
                data = json.load(file_obj)
            for session in data.get('sessions', []):
                if not isinstance(session, dict):
                    continue
                if session.get('combination_id') == combination_id or any(
                    isinstance(entry, dict) and entry.get('combination_id') == combination_id
                    for entry in session.get('entries', []) or []
                ):
                    count += 1
        except Exception:
            continue  # unreadable file — skip, this is a best-effort count
    return count


def count_sessions_for_location(location_id: str) -> int:
    """Count sessions (all users) referencing a location preset.

    Informational only: like Astrodex pictures, sessions are never cascade-deleted or
    orphan-flagged when a preset is removed - a session is a historical record, and its
    frozen ``location_name`` snapshot stays valid as display-only history.
    """
    return _count_sessions_matching('location_id', location_id)


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
#
# Visual style (colours, header/footer bar, margins) intentionally mirrors
# plan_my_night.generate_plan_pdf() so the two exports feel like one product. Kept as a
# separate implementation rather than a shared helper module: this file never imports
# plan_my_night (see the module docstring), and the per-entry photo layout has no
# equivalent on the Plan My Night side.
#
# This module never imports astrodex, so it cannot resolve an entry's attached photo to a
# file path itself. The blueprint layer pre-resolves every entry's picture into
# ``image_paths`` (entry id -> absolute file path, or absent/None when there is no photo
# or the file no longer exists) before calling these functions.

_PDF_PAGE_W_IN = 8.27
_PDF_PAGE_H_IN = 11.69
_PDF_C_HDR_BG = '#1a1f35'
_PDF_C_WHITE = '#ffffff'
_PDF_C_TXT_DRK = '#212121'
_PDF_C_TXT_MID = '#616161'
_PDF_C_GRID = '#e0e0e0'
_PDF_C_BRAND = '#4e9af1'
_PDF_C_PANEL_BG = '#f4f6fb'
_PDF_C_PLACEHOLDER_BG = '#f0f0f0'
_PDF_C_PLACEHOLDER_BORDER = '#d0d0d0'

_PDF_MARGIN_L = 0.10
_PDF_MARGIN_R = 0.90
_PDF_HEADER_TOP = 0.985
_PDF_HEADER_H = 0.045
# Longest centered header title (title + subtitle) that still clears the brand mark
# (left) and myastroboard.org (right) at the header's bold 10pt - past this it must be
# truncated, or a long session date + section name can visually overlap them. Calibrated
# against measured glyph widths across all locales, not just character count.
_PDF_HEADER_TITLE_MAX_CHARS = 48
_PDF_FOOTER_H = 0.025
_PDF_CONTENT_TOP = _PDF_HEADER_TOP - _PDF_HEADER_H - 0.015
_PDF_CONTENT_BOTTOM = _PDF_FOOTER_H + 0.02

_PDF_INFO_PANEL_H = 0.36
_PDF_INFO_PANEL_H_COMPACT = 0.20  # multi-night session panel: no per-night fields, so a shorter card
_PDF_NIGHT_HEADER_H = 0.11
_PDF_ENTRY_ROW_H = 0.19
_PDF_ENTRY_IMG_W = 0.20
_PDF_SUMMARY_ROW_H = 0.028
_PDF_SUMMARY_ROWS_PER_PAGE = 28


def _pdf_fmt_hm_utc(value: Any) -> str:
    """HH:MM out of an ISO timestamp.

    Session start/end times carry no timezone of their own (see the data model docs), so
    this reads the stored value - UTC, since the frontend converts the browser's local
    input to UTC before saving - rather than guessing a viewer timezone server-side.
    """
    if not value:
        return '--:--'
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%H:%M')
    except ValueError:
        return '--:--'


def _pdf_fmt_integration(minutes: Any) -> str:
    """Compact '1h30' / '45 min' label, or '-' when there is nothing to show."""
    value = _coerce_optional_float(minutes, 0)
    if not value:
        return '-'
    hours, rest = divmod(int(round(value)), 60)
    return f'{hours}h{rest:02d}' if hours else f'{rest} min'


def _pdf_session_totals(entries: List[Dict]) -> Tuple[float, Optional[float]]:
    """(total integration minutes, average rating or None) across one session's entries."""
    total_integration = 0.0
    rating_sum = 0.0
    rating_count = 0
    for entry in entries:
        integration = _coerce_optional_float(entry.get('integration_minutes'), 0)
        if integration:
            total_integration += integration
        rating = _coerce_optional_float(entry.get('rating'), 0, 5)
        if rating is not None:
            rating_sum += rating
            rating_count += 1
    average_rating = rating_sum / rating_count if rating_count else None
    return total_integration, average_rating


def _pdf_text(target, *args, **kwargs):
    """``ax.text()`` / ``fig.text()`` wrapper that never treats the string as mathtext.

    Session/entry notes, location names, etc. are free text a user typed, not markup - an
    unbalanced ``$`` in a note must not raise inside PdfPages and turn an export into a 500.
    """
    kwargs.setdefault('parse_math', False)
    return target.text(*args, **kwargs)


def _pdf_hide_chrome(ax) -> None:
    """Strip ticks, tick labels and spines without ``ax.axis('off')``, which also drops
    the axes' facecolor patch from rendering - every coloured bar/panel below needs that
    patch to actually paint its background."""
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _pdf_header(ax, title: str, subtitle: str = '') -> None:
    ax.set_facecolor(_PDF_C_HDR_BG)
    _pdf_hide_chrome(ax)
    _pdf_text(
        ax,
        0.015,
        0.5,
        'myastroboard',
        va='center',
        ha='left',
        fontsize=10,
        color=_PDF_C_BRAND,
        fontweight='bold',
        transform=ax.transAxes,
    )
    full_title = f'{title}  -  {subtitle}' if subtitle else title
    if len(full_title) > _PDF_HEADER_TITLE_MAX_CHARS:
        full_title = full_title[: _PDF_HEADER_TITLE_MAX_CHARS - 1].rstrip() + '…'
    _pdf_text(
        ax,
        0.5,
        0.5,
        full_title,
        va='center',
        ha='center',
        fontsize=10,
        color=_PDF_C_WHITE,
        fontweight='bold',
        transform=ax.transAxes,
    )
    _pdf_text(
        ax,
        0.985,
        0.5,
        'myastroboard.org',
        va='center',
        ha='right',
        fontsize=8,
        color='#8898cc',
        transform=ax.transAxes,
    )


def _pdf_footer(ax, label: str) -> None:
    ax.set_facecolor(_PDF_C_HDR_BG)
    _pdf_hide_chrome(ax)
    _pdf_text(ax, 0.5, 0.5, label, va='center', ha='center', fontsize=7.5, color='#6a7a99', transform=ax.transAxes)


def _pdf_new_page(title: str, subtitle: str = ''):
    """A blank A4 page with the shared header/footer bars already drawn."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(_PDF_PAGE_W_IN, _PDF_PAGE_H_IN))
    fig.patch.set_facecolor(_PDF_C_WHITE)
    _pdf_header(
        fig.add_axes((_PDF_MARGIN_L, _PDF_HEADER_TOP - _PDF_HEADER_H, _PDF_MARGIN_R - _PDF_MARGIN_L, _PDF_HEADER_H)),
        title,
        subtitle,
    )
    _pdf_footer(fig.add_axes((_PDF_MARGIN_L, 0.01, _PDF_MARGIN_R - _PDF_MARGIN_L, _PDF_FOOTER_H)), 'myastroboard.org')
    return fig


def _pdf_draw_thumbnail(ax_img, image_path: Optional[str], t) -> None:
    """Draw an entry's attached photo, or a neutral placeholder box when there is none."""
    ax_img.axis('off')
    if image_path:
        try:
            from PIL import Image, ImageOps

            with Image.open(image_path) as raw:
                img = ImageOps.exif_transpose(raw)
                img = img.convert('RGB')
                img.thumbnail((900, 900))
                ax_img.imshow(img)
            return
        except Exception as error:
            logger.warning(f'Observation Log PDF: failed to load image {image_path}: {error}')

    from matplotlib.patches import Rectangle

    ax_img.set_facecolor(_PDF_C_PLACEHOLDER_BG)
    ax_img.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=ax_img.transAxes,
            facecolor=_PDF_C_PLACEHOLDER_BG,
            edgecolor=_PDF_C_PLACEHOLDER_BORDER,
            linewidth=0.8,
        )
    )
    _pdf_text(
        ax_img,
        0.5,
        0.5,
        t('observation_log.export_pdf_no_photo') or 'No photo',
        ha='center',
        va='center',
        fontsize=7.5,
        color='#9e9e9e',
        transform=ax_img.transAxes,
    )


def _pdf_render_entry_row(fig, entry: Dict, image_path: Optional[str], row_top: float, row_h: float, t) -> None:
    """One target: photo (or placeholder) on the left, identity/capture/notes text on the right."""
    from matplotlib.lines import Line2D

    pad = row_h * 0.08
    img_h = min(_PDF_ENTRY_IMG_W * _PDF_PAGE_W_IN / _PDF_PAGE_H_IN, row_h - 2 * pad)
    img_bottom = row_top - row_h + (row_h - img_h) / 2
    _pdf_draw_thumbnail(fig.add_axes((_PDF_MARGIN_L, img_bottom, _PDF_ENTRY_IMG_W, img_h)), image_path, t)

    text_left = _PDF_MARGIN_L + _PDF_ENTRY_IMG_W + 0.02
    ax_text = fig.add_axes((text_left, row_top - row_h, _PDF_MARGIN_R - text_left, row_h))
    ax_text.axis('off')
    ax_text.set_xlim(0, 1)
    ax_text.set_ylim(0, 1)

    y = 0.90
    _pdf_text(
        ax_text,
        0.0,
        y,
        entry.get('name') or '?',
        va='top',
        ha='left',
        fontsize=11,
        color=_PDF_C_TXT_DRK,
        fontweight='bold',
        transform=ax_text.transAxes,
    )

    subtitle_parts = [part for part in (entry.get('type'), entry.get('constellation'), entry.get('catalogue')) if part]
    if subtitle_parts:
        y -= 0.16
        _pdf_text(
            ax_text,
            0.0,
            y,
            ' · '.join(subtitle_parts),
            va='top',
            ha='left',
            fontsize=8,
            color=_PDF_C_TXT_MID,
            fontstyle='italic',
            transform=ax_text.transAxes,
        )

    stats = []
    if entry.get('frame_count'):
        stats.append(f"{t('observation_log.frame_count') or 'Frames'}: {entry['frame_count']}")
    if entry.get('sub_exposure_seconds'):
        stats.append(f"{t('observation_log.sub_exposure') or 'Sub-exposure'}: {entry['sub_exposure_seconds']:g}s")
    integration_label = _pdf_fmt_integration(entry.get('integration_minutes'))
    if integration_label != '-':
        stats.append(f"{t('observation_log.integration_minutes') or 'Integration'}: {integration_label}")
    if entry.get('planned_minutes'):
        stats.append(
            f"{t('observation_log.planned_minutes') or 'Planned'}: {_pdf_fmt_integration(entry['planned_minutes'])}"
        )
    if entry.get('rating') is not None:
        stats.append(f"{t('observation_log.rating') or 'Rating'}: {entry['rating']:.1f}/5")

    y -= 0.18
    if stats:
        _pdf_text(
            ax_text,
            0.0,
            y,
            '   '.join(stats),
            va='top',
            ha='left',
            fontsize=8.5,
            color=_PDF_C_TXT_DRK,
            transform=ax_text.transAxes,
        )

    notes = (entry.get('notes') or '').strip()
    if notes:
        y -= 0.16
        wrapped = textwrap.wrap(notes, width=88)
        shown = wrapped[:3]
        if len(wrapped) > 3:
            shown[-1] = shown[-1].rstrip() + '…'
        _pdf_text(
            ax_text,
            0.0,
            y,
            '\n'.join(shown),
            va='top',
            ha='left',
            fontsize=7.5,
            color=_PDF_C_TXT_MID,
            linespacing=1.4,
            transform=ax_text.transAxes,
        )

    fig.add_artist(
        Line2D(
            [_PDF_MARGIN_L, _PDF_MARGIN_R],
            [row_top - row_h, row_top - row_h],
            color=_PDF_C_GRID,
            linewidth=0.7,
            transform=fig.transFigure,
        )
    )


def _pdf_render_info_panel(fig, session: Dict, entries: List[Dict], t) -> float:
    """Session ('trip') level 'common information' card. Returns the y (figure-fraction)
    below which the night/target breakdown should start.

    A single-night session (still the overwhelmingly common case) keeps the original
    8-field layout, showing that one night's own conditions inline - unchanged output
    from before per-night conditions existed. A multi-night session gets a shorter,
    location/equipment/totals-only card instead: each night's own conditions are shown
    by _pdf_render_night_header() ahead of that night's own entries.
    """
    nights = session.get('nights') or []
    is_multi_night = len(nights) > 1
    panel_h = _PDF_INFO_PANEL_H_COMPACT if is_multi_night else _PDF_INFO_PANEL_H
    panel_top = _PDF_CONTENT_TOP
    panel_bottom = panel_top - panel_h
    ax = fig.add_axes((_PDF_MARGIN_L, panel_bottom, _PDF_MARGIN_R - _PDF_MARGIN_L, panel_h))
    ax.set_facecolor(_PDF_C_PANEL_BG)
    _pdf_hide_chrome(ax)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    total_integration, average_rating = _pdf_session_totals(entries)
    location_field = (
        t('observation_log.location') or 'Location',
        session.get('location_name') or (t('observation_log.no_location') or 'No location'),
    )
    equipment_field = (
        t('observation_log.equipment') or 'Equipment',
        session.get('combination_name') or (t('observation_log.no_equipment') or 'No equipment'),
    )
    integration_field = (
        t('observation_log.total_integration') or 'Total integration',
        _pdf_fmt_integration(total_integration),
    )

    if is_multi_night:
        fields = [
            location_field,
            equipment_field,
            integration_field,
            (t('observation_log.nights_section') or 'Nights', str(len(nights))),
        ]
        col_x = [0.02, 0.52]
        row_y = [0.90, 0.50]
        value_offset = 0.18
        for idx, (label, value) in enumerate(fields):
            x = col_x[idx % 2]
            y = row_y[idx // 2]
            _pdf_text(ax, x, y, label, va='top', ha='left', fontsize=8, color=_PDF_C_TXT_MID, transform=ax.transAxes)
            _pdf_text(
                ax,
                x,
                y - value_offset,
                value,
                va='top',
                ha='left',
                fontsize=10,
                color=_PDF_C_TXT_DRK,
                fontweight='bold',
                transform=ax.transAxes,
            )
        stats_y = row_y[-1] - value_offset - 0.14
    else:
        night = _primary_night(session)
        seeing = night.get('seeing')
        transparency = night.get('transparency')
        not_recorded = t('observation_log.not_recorded') or 'Not recorded'

        fields = [
            location_field,
            equipment_field,
            (t('observation_log.start_time') or 'Start', _pdf_fmt_hm_utc(night.get('start_time'))),
            (t('observation_log.end_time') or 'End', _pdf_fmt_hm_utc(night.get('end_time'))),
            (t('observation_log.sqm') or 'SQM', f"{night['sqm']:g}" if night.get('sqm') is not None else '-'),
            (
                t('observation_log.seeing') or 'Seeing',
                t('observation_log.seeing_value', value=seeing) if seeing is not None else not_recorded,
            ),
            (
                t('observation_log.transparency') or 'Transparency',
                (
                    t('observation_log.transparency_value', value=transparency)
                    if transparency is not None
                    else not_recorded
                ),
            ),
            integration_field,
        ]
        col_x = [0.02, 0.52]
        row_y = [0.95, 0.74, 0.53, 0.32]
        for idx, (label, value) in enumerate(fields):
            x = col_x[idx // 4]
            y = row_y[idx % 4]
            _pdf_text(ax, x, y, label, va='top', ha='left', fontsize=8, color=_PDF_C_TXT_MID, transform=ax.transAxes)
            _pdf_text(
                ax,
                x,
                y - 0.08,
                value,
                va='top',
                ha='left',
                fontsize=10,
                color=_PDF_C_TXT_DRK,
                fontweight='bold',
                transform=ax.transAxes,
            )
        stats_y = row_y[3] - 0.08 - 0.06

    stats_line = t('observation_log.target_count', count=len(entries)) or f'{len(entries)} target(s)'
    if average_rating is not None:
        stats_line += f"   -   {t('observation_log.rating') or 'Rating'}: {average_rating:.1f}/5"
    _pdf_text(
        ax,
        0.02,
        stats_y,
        stats_line,
        va='top',
        ha='left',
        fontsize=9,
        color=_PDF_C_TXT_DRK,
        fontweight='bold',
        transform=ax.transAxes,
    )

    notes = (session.get('notes') or '').strip()
    if notes:
        wrapped = textwrap.wrap(notes, width=95)
        shown = wrapped[:4]
        if len(wrapped) > 4:
            shown[-1] = shown[-1].rstrip() + '…'
        _pdf_text(
            ax,
            0.02,
            stats_y - 0.07,
            '\n'.join(shown),
            va='top',
            ha='left',
            fontsize=7.5,
            color=_PDF_C_TXT_MID,
            fontstyle='italic',
            linespacing=1.35,
            transform=ax.transAxes,
        )

    return panel_bottom - 0.02


def _pdf_render_night_header(fig, night: Dict, y_cursor: float, t) -> float:
    """One compact block introducing a night's own date/conditions/notes, drawn ahead of
    that night's own entries in a multi-night session's PDF. Returns the y
    (figure-fraction) below which content continues."""
    from matplotlib.lines import Line2D

    not_recorded = t('observation_log.not_recorded') or 'Not recorded'
    seeing = night.get('seeing')
    transparency = night.get('transparency')
    moon = night.get('moon_illumination_percent')

    seeing_label = (t('observation_log.seeing_value', value=seeing) or f'{seeing}/8') if seeing is not None else None
    transparency_label = (
        (t('observation_log.transparency_value', value=transparency) or f'{transparency}/8')
        if transparency is not None
        else None
    )

    parts = [
        f"{t('observation_log.start_time') or 'Start'} {_pdf_fmt_hm_utc(night.get('start_time'))}",
        f"{t('observation_log.end_time') or 'End'} {_pdf_fmt_hm_utc(night.get('end_time'))}",
    ]
    if night.get('sqm') is not None:
        parts.append(f"{t('observation_log.sqm') or 'SQM'} {night['sqm']:g}")
    parts.append(f"{t('observation_log.seeing') or 'Seeing'} {seeing_label or not_recorded}")
    parts.append(f"{t('observation_log.transparency') or 'Transparency'} {transparency_label or not_recorded}")
    if moon is not None:
        parts.append(f"{t('observation_log.moon_illumination') or 'Moon'} {round(moon)}%")

    _pdf_text(
        fig,
        _PDF_MARGIN_L,
        y_cursor,
        night.get('date') or '',
        fontsize=10,
        fontweight='bold',
        color=_PDF_C_TXT_DRK,
        ha='left',
        va='top',
    )
    y_cursor -= 0.028
    _pdf_text(
        fig,
        _PDF_MARGIN_L,
        y_cursor,
        '   '.join(parts),
        fontsize=8,
        color=_PDF_C_TXT_MID,
        ha='left',
        va='top',
    )
    y_cursor -= 0.024

    notes = (night.get('notes') or '').strip()
    if notes:
        wrapped = textwrap.wrap(notes, width=100)
        shown = wrapped[:2]
        if len(wrapped) > 2:
            shown[-1] = shown[-1].rstrip() + '…'
        _pdf_text(
            fig,
            _PDF_MARGIN_L,
            y_cursor,
            '\n'.join(shown),
            fontsize=7.5,
            color=_PDF_C_TXT_MID,
            fontstyle='italic',
            linespacing=1.35,
            ha='left',
            va='top',
        )
        y_cursor -= 0.02 * len(shown)

    fig.add_artist(
        Line2D(
            [_PDF_MARGIN_L, _PDF_MARGIN_R],
            [y_cursor - 0.006, y_cursor - 0.006],
            color=_PDF_C_GRID,
            linewidth=0.6,
            transform=fig.transFigure,
        )
    )
    return y_cursor - 0.016


def _render_session_section(pdf, session: Dict, image_paths: Dict[str, str], t) -> None:
    """Append one session's pages (info panel, then every entry with its photo) to an
    already-open PdfPages. Shared by generate_session_pdf() and generate_sessions_pdf().

    A single-night session (still the overwhelmingly common case) renders exactly as
    before: one flat 'Logged targets' list under the info panel. A multi-night session
    instead gets one date/conditions sub-header per night, its own entries grouped
    underneath - the day-by-day breakdown a multi-night trip needs.
    """
    import matplotlib.pyplot as plt

    entries = [entry for entry in session.get('entries', []) if isinstance(entry, dict)]
    nights = _sorted_nights(session)
    title = t('observation_log.export_pdf_title') or 'Observation Log'
    date_start, date_end = session_date_range(session)
    session_date_label = date_start if date_start == date_end else f'{date_start} - {date_end}'
    subtitle = t('observation_log.session_of', date=session_date_label) or session_date_label

    fig = _pdf_new_page(title, subtitle)
    y_cursor = _pdf_render_info_panel(fig, session, entries, t)

    if not entries:
        _pdf_text(
            fig,
            _PDF_MARGIN_L,
            y_cursor,
            t('observation_log.no_targets') or 'No target logged in this session yet.',
            fontsize=9.5,
            color=_PDF_C_TXT_MID,
            ha='left',
            va='top',
        )
        pdf.savefig(fig)
        plt.close(fig)
        return

    targets_label = t('observation_log.export_pdf_targets_section') or 'Logged targets'
    continuation_subtitle = f'{subtitle} - {targets_label}'

    def _ensure_room(needed_h: float) -> None:
        nonlocal fig, y_cursor
        if y_cursor - needed_h < _PDF_CONTENT_BOTTOM:
            pdf.savefig(fig)
            plt.close(fig)
            fig = _pdf_new_page(title, continuation_subtitle)
            y_cursor = _PDF_CONTENT_TOP

    if len(nights) <= 1:
        _pdf_text(
            fig,
            _PDF_MARGIN_L,
            y_cursor,
            targets_label,
            fontsize=10,
            fontweight='bold',
            color=_PDF_C_TXT_DRK,
            ha='left',
            va='top',
        )
        y_cursor -= 0.035

        for entry in entries:
            _ensure_room(_PDF_ENTRY_ROW_H)
            _pdf_render_entry_row(fig, entry, image_paths.get(entry.get('id') or ''), y_cursor, _PDF_ENTRY_ROW_H, t)
            y_cursor -= _PDF_ENTRY_ROW_H

        pdf.savefig(fig)
        plt.close(fig)
        return

    entries_by_night: Dict[str, List[Dict]] = {night['id']: [] for night in nights}
    unassigned: List[Dict] = []
    for entry in entries:
        bucket = entries_by_night.get(entry.get('night_id') or '')
        (bucket if bucket is not None else unassigned).append(entry)

    for night in nights:
        night_entries = entries_by_night.get(night['id'], [])
        if not night_entries:
            continue
        _ensure_room(_PDF_NIGHT_HEADER_H)
        y_cursor = _pdf_render_night_header(fig, night, y_cursor, t)
        for entry in night_entries:
            _ensure_room(_PDF_ENTRY_ROW_H)
            _pdf_render_entry_row(fig, entry, image_paths.get(entry.get('id') or ''), y_cursor, _PDF_ENTRY_ROW_H, t)
            y_cursor -= _PDF_ENTRY_ROW_H

    if unassigned:
        _ensure_room(0.035)
        _pdf_text(
            fig,
            _PDF_MARGIN_L,
            y_cursor,
            t('observation_log.other_night_group') or 'Other',
            fontsize=10,
            fontweight='bold',
            color=_PDF_C_TXT_DRK,
            ha='left',
            va='top',
        )
        y_cursor -= 0.035
        for entry in unassigned:
            _ensure_room(_PDF_ENTRY_ROW_H)
            _pdf_render_entry_row(fig, entry, image_paths.get(entry.get('id') or ''), y_cursor, _PDF_ENTRY_ROW_H, t)
            y_cursor -= _PDF_ENTRY_ROW_H

    pdf.savefig(fig)
    plt.close(fig)


def _pdf_render_cover_page(pdf, sessions: List[Dict], from_date: Optional[str], to_date: Optional[str], t) -> None:
    import matplotlib.pyplot as plt

    title = t('observation_log.export_pdf_title') or 'Observation Log'
    fig = _pdf_new_page(title)

    ax = fig.add_axes((_PDF_MARGIN_L, 0.35, _PDF_MARGIN_R - _PDF_MARGIN_L, _PDF_CONTENT_TOP - 0.35))
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    _pdf_text(
        ax,
        0.5,
        0.78,
        t('observation_log.title') or 'Observation Log',
        ha='center',
        va='center',
        fontsize=26,
        fontweight='bold',
        color=_PDF_C_TXT_DRK,
        transform=ax.transAxes,
    )

    if from_date and to_date:
        subtitle = (
            t('observation_log.export_pdf_cover_range', start_date=from_date, end_date=to_date)
            or f'{from_date} - {to_date}'
        )
    else:
        subtitle = t('observation_log.export_pdf_cover_all_sessions') or 'All sessions'
    _pdf_text(
        ax, 0.5, 0.62, subtitle, ha='center', va='center', fontsize=13, color=_PDF_C_TXT_MID, transform=ax.transAxes
    )

    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    _pdf_text(
        ax,
        0.5,
        0.52,
        t('observation_log.export_pdf_generated_on', date=generated_at) or generated_at,
        ha='center',
        va='center',
        fontsize=9,
        color=_PDF_C_TXT_MID,
        transform=ax.transAxes,
    )

    all_entries = [entry for session in sessions for entry in session.get('entries', []) if isinstance(entry, dict)]
    total_integration, average_rating = _pdf_session_totals(all_entries)
    tiles = [
        (str(len(sessions)), t('observation_log.stat_sessions') or 'Sessions'),
        (str(len(all_entries)), t('observation_log.stat_targets') or 'Targets logged'),
        (_pdf_fmt_integration(total_integration), t('observation_log.stat_integration') or 'Total integration'),
        (
            f'{average_rating:.1f}/5' if average_rating is not None else '-',
            t('observation_log.stat_rating') or 'Average rating',
        ),
    ]
    tile_w = 1.0 / len(tiles)
    for idx, (value, label) in enumerate(tiles):
        cx = tile_w * idx + tile_w / 2
        _pdf_text(
            ax,
            cx,
            0.30,
            value,
            ha='center',
            va='center',
            fontsize=17,
            fontweight='bold',
            color=_PDF_C_BRAND,
            transform=ax.transAxes,
        )
        _pdf_text(
            ax, cx, 0.19, label, ha='center', va='center', fontsize=8.5, color=_PDF_C_TXT_MID, transform=ax.transAxes
        )

    pdf.savefig(fig)
    plt.close(fig)


def _pdf_render_summary_pages(pdf, sessions: List[Dict], t) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    title = t('observation_log.export_pdf_title') or 'Observation Log'
    summary_title = t('observation_log.export_pdf_summary_title') or 'Summary'

    col_x = [0.0, 0.16, 0.40, 0.62, 0.74, 0.88]
    col_headers = [
        t('observation_log.export_pdf_col_date') or 'Date',
        t('observation_log.export_pdf_col_location') or 'Location',
        t('observation_log.export_pdf_col_equipment') or 'Equipment',
        t('observation_log.export_pdf_col_targets') or 'Targets',
        t('observation_log.export_pdf_col_integration') or 'Integration',
        t('observation_log.export_pdf_col_rating') or 'Rating',
    ]

    chunks = [
        sessions[i : i + _PDF_SUMMARY_ROWS_PER_PAGE] for i in range(0, len(sessions), _PDF_SUMMARY_ROWS_PER_PAGE)
    ] or [[]]

    for chunk_idx, chunk in enumerate(chunks):
        fig = _pdf_new_page(title, summary_title if chunk_idx == 0 else f'{summary_title} ({chunk_idx + 1})')
        ax = fig.add_axes(
            (_PDF_MARGIN_L, _PDF_CONTENT_BOTTOM, _PDF_MARGIN_R - _PDF_MARGIN_L, _PDF_CONTENT_TOP - _PDF_CONTENT_BOTTOM)
        )
        ax.axis('off')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

        y = 0.99
        for cx, header in zip(col_x, col_headers):
            _pdf_text(
                ax,
                cx,
                y,
                header,
                va='top',
                ha='left',
                fontsize=7.5,
                fontweight='bold',
                color=_PDF_C_TXT_MID,
                transform=ax.transAxes,
            )
        y -= 0.014
        ax.plot([0, 1], [y, y], color=_PDF_C_GRID, lw=0.8, transform=ax.transAxes)
        y -= 0.014

        if not sessions:
            _pdf_text(
                ax,
                0.5,
                0.5,
                t('observation_log.export_pdf_no_sessions') or 'No session to export.',
                ha='center',
                va='center',
                fontsize=10,
                color=_PDF_C_TXT_MID,
                transform=ax.transAxes,
            )

        for idx, session in enumerate(chunk):
            row_bg = '#f5f7fc' if idx % 2 == 0 else _PDF_C_WHITE
            ax.add_patch(
                Rectangle(
                    (0.0, y - _PDF_SUMMARY_ROW_H),
                    1.0,
                    _PDF_SUMMARY_ROW_H,
                    transform=ax.transAxes,
                    facecolor=row_bg,
                    edgecolor='none',
                )
            )
            entries = [entry for entry in session.get('entries', []) if isinstance(entry, dict)]
            total_integration, average_rating = _pdf_session_totals(entries)
            mid_y = y - _PDF_SUMMARY_ROW_H / 2
            date_start, date_end = session_date_range(session)
            date_cell = date_start if date_start == date_end else f'{date_start} - {date_end}'
            cells = [
                (date_cell or '-')[:22],
                (session.get('location_name') or '-')[:22],
                (session.get('combination_name') or '-')[:22],
                str(len(entries)),
                _pdf_fmt_integration(total_integration),
                f'{average_rating:.1f}' if average_rating is not None else '-',
            ]
            for cx, value in zip(col_x, cells):
                _pdf_text(
                    ax,
                    cx,
                    mid_y,
                    value,
                    va='center',
                    ha='left',
                    fontsize=7.5,
                    color=_PDF_C_TXT_DRK,
                    transform=ax.transAxes,
                )
            y -= _PDF_SUMMARY_ROW_H

        pdf.savefig(fig)
        plt.close(fig)


def generate_session_pdf(session: Dict, image_paths: Dict[str, str], i18n_manager) -> io.BytesIO:
    """Render one observation session as a print-friendly A4 PDF: common session info,
    then each logged target with its attached photo (if any).

    ``image_paths`` maps entry id -> absolute image file path, pre-resolved by the
    blueprint layer (see the module docstring above).
    """
    from matplotlib.backends.backend_pdf import PdfPages

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        _render_session_section(pdf, session, image_paths, i18n_manager.t)
    buffer.seek(0)
    return buffer


def generate_sessions_pdf(
    sessions: List[Dict],
    image_paths: Dict[str, str],
    i18n_manager,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    order: str = 'asc',
) -> io.BytesIO:
    """Render every session in *sessions* (already date-filtered by the caller) as one
    PDF: a cover page, an aggregate summary table, then each session's own pages in full
    (identical layout to generate_session_pdf), ordered oldest-to-newest by default.
    """
    from matplotlib.backends.backend_pdf import PdfPages

    t = i18n_manager.t
    ordered = sorted(
        (session for session in sessions if isinstance(session, dict)),
        key=_session_sort_key,
        reverse=(order == 'desc'),
    )

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        _pdf_render_cover_page(pdf, ordered, from_date, to_date, t)
        _pdf_render_summary_pages(pdf, ordered, t)
        for session in ordered:
            _render_session_section(pdf, session, image_paths, t)
    buffer.seek(0)
    return buffer
