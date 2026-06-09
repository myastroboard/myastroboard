"""Plan My Night storage and business logic."""

import copy
import csv
import json
import os
import re
import shutil
import threading
import uuid
import io
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import skytonight_targets
from constants import DATA_DIR
from logging_config import get_logger

logger = get_logger(__name__)

# Per-user write locks to prevent race conditions on concurrent saves
_user_plan_locks: Dict[str, threading.Lock] = {}
_user_plan_locks_mutex = threading.Lock()


def _get_user_plan_lock(user_id: str) -> threading.Lock:
    """Get or create a per-user lock for serializing plan file writes."""
    with _user_plan_locks_mutex:
        if user_id not in _user_plan_locks:
            _user_plan_locks[user_id] = threading.Lock()
        return _user_plan_locks[user_id]


PLAN_DIR = os.path.join(DATA_DIR, 'projects')


def _safe_plan_path(path: str) -> str:
    """Resolve *path* and verify it lives inside PLAN_DIR.

    This is the canonical sanitizer for path expressions in this module.
    CodeQL (CWE-022) requires the realpath check to occur at the call site of
    each file operation; callers must use the *returned* resolved path.

    PLAN_DIR is read at call time (not cached) so that test fixtures that
    monkeypatch plan_my_night.PLAN_DIR are honoured correctly.

    Raises ValueError if the path would escape the plan directory.
    """
    plan_dir_real = os.path.realpath(PLAN_DIR)
    resolved = os.path.realpath(path)
    if not resolved.startswith(plan_dir_real + os.sep):
        raise ValueError(f'Path outside plan directory: {path!r}')
    return resolved


_TELESCOPE_ID_DEFAULT = 'default'

# All system-generated IDs are UUID v4 strings produced by uuid.uuid4()
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_valid_user_id(user_id: Optional[str]) -> bool:
    """Return True only when user_id matches the UUID v4 format used by auth.py."""
    return bool(user_id) and bool(_UUID_RE.match(str(user_id)))


def _is_valid_telescope_id(telescope_id: Optional[str]) -> bool:
    """Return True for 'default' or a UUID string used as a telescope identifier."""
    if not telescope_id:
        return False
    if telescope_id == _TELESCOPE_ID_DEFAULT:
        return True
    return bool(_UUID_RE.match(str(telescope_id)))


def _now() -> datetime:
    return datetime.now().astimezone()


def _to_iso(value: datetime) -> str:
    return value.astimezone().isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone()

    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text).astimezone()
    except ValueError:
        pass

    # Legacy moon endpoint format: YYYY-MM-DD HH:MM
    try:
        return datetime.strptime(text, '%Y-%m-%d %H:%M').astimezone()
    except ValueError:
        return None


def ensure_plan_directory() -> None:
    os.makedirs(PLAN_DIR, exist_ok=True)


def get_user_plan_file(user_id: str, telescope_id: Optional[str] = None) -> str:
    ensure_plan_directory()
    if not _is_valid_user_id(user_id):
        raise ValueError(f'Invalid user_id format: {user_id!r}')
    tid = telescope_id if _is_valid_telescope_id(telescope_id) else _TELESCOPE_ID_DEFAULT
    if tid == _TELESCOPE_ID_DEFAULT:
        # Legacy / no-telescope filename kept for backwards compat
        path = os.path.join(PLAN_DIR, f'{user_id}_plan_my_night.json')
    else:
        path = os.path.join(PLAN_DIR, f'{user_id}_plan_{tid}.json')
    # _safe_plan_path resolves symlinks and verifies containment; returns the
    # realpath so downstream callers always operate on a canonical, safe path.
    return _safe_plan_path(path)


def get_all_plan_files(user_id: str) -> list:
    """Return all plan file paths that exist for this user."""
    if not _is_valid_user_id(user_id):
        return []
    ensure_plan_directory()
    result = []
    for fname in os.listdir(PLAN_DIR):
        if (
            fname.startswith(f'{user_id}_plan')
            and fname.endswith('.json')
            and '.corrupted.' not in fname
            and '.backup' not in fname
            and fname != f'{user_id}_plan_my_night.json.tmp'
        ):
            try:
                resolved = _safe_plan_path(os.path.join(PLAN_DIR, fname))
                result.append(resolved)
            except ValueError:
                pass  # filename failed path-traversal check — skip it
    return result


def delete_plan_for_telescope(user_id: str, telescope_id: str) -> bool:
    """Delete the plan file for a specific telescope (called when telescope is removed)."""
    if not _is_valid_user_id(user_id) or not _is_valid_telescope_id(telescope_id):
        logger.warning('delete_plan_for_telescope: invalid user_id or telescope_id, aborting')
        return False
    try:
        resolved = get_user_plan_file(user_id, telescope_id)
    except ValueError:
        logger.warning('delete_plan_for_telescope: path traversal detected, aborting')
        return False
    try:
        if os.path.exists(resolved):
            os.remove(resolved)
            logger.info(f'Deleted plan file for user {user_id} telescope {telescope_id}')
        return True
    except Exception as error:
        logger.error(f'Error deleting plan file {resolved}: {error}')
        return False


def _default_payload(user_id: str, username: Optional[str] = None) -> Dict:
    return {
        'user_id': user_id,
        'username': username or 'unknown',
        'created_at': _to_iso(_now()),
        'updated_at': _to_iso(_now()),
        'plan': None,
    }


def load_user_plan(user_id: str, username: Optional[str] = None, telescope_id: Optional[str] = None) -> Dict:
    # get_user_plan_file already calls _safe_plan_path and returns the resolved
    # path.  Re-applying _safe_plan_path here makes the sanitization explicit at
    # the call site, which is required for CodeQL to recognise the barrier.
    file_path = _safe_plan_path(get_user_plan_file(user_id, telescope_id))
    if not os.path.exists(file_path):
        return _default_payload(user_id, username)

    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            payload = json.load(file_obj)
    except json.JSONDecodeError as error:
        logger.error(f'Error loading plan for user {user_id}: {error}')
        backup_path = _safe_plan_path(file_path + '.corrupted.' + datetime.now().strftime('%Y%m%d_%H%M%S'))
        try:
            shutil.copy2(file_path, backup_path)
        except Exception as backup_error:
            logger.error(f'Failed to backup corrupted plan file {file_path}: {backup_error}')
        return _default_payload(user_id, username)
    except Exception as error:
        logger.error(f'Error loading plan for user {user_id}: {error}')
        return _default_payload(user_id, username)

    if not isinstance(payload, dict):
        return _default_payload(user_id, username)

    payload.setdefault('user_id', user_id)
    if username:
        payload['username'] = username
    payload.setdefault('username', username or 'unknown')
    payload.setdefault('created_at', _to_iso(_now()))
    payload.setdefault('updated_at', _to_iso(_now()))

    plan = payload.get('plan')
    if plan is not None and not isinstance(plan, dict):
        payload['plan'] = None

    return payload


def validate_plan_json(file_path: str) -> Tuple[bool, str]:
    try:
        safe_path = _safe_plan_path(file_path)
        with open(safe_path, 'r', encoding='utf-8') as file_obj:
            payload = json.load(file_obj)

        if not isinstance(payload, dict):
            return False, 'JSON root must be an object'

        if 'user_id' not in payload:
            return False, "Missing 'user_id'"

        plan = payload.get('plan')
        if plan is not None:
            if not isinstance(plan, dict):
                return False, "'plan' must be an object or null"
            if not isinstance(plan.get('entries', []), list):
                return False, "'plan.entries' must be a list"

            for index, entry in enumerate(plan.get('entries', [])):
                if not isinstance(entry, dict):
                    return False, f'Entry {index} must be an object'
                if not entry.get('id'):
                    return False, f'Entry {index} missing id'
                if not entry.get('name'):
                    return False, f'Entry {index} missing name'
        return True, ''
    except json.JSONDecodeError as error:
        return False, f'Invalid JSON: {error}'
    except Exception as error:
        return False, f'Validation failed: {error}'


def save_user_plan(
    user_id: str, payload: Dict, username: Optional[str] = None, telescope_id: Optional[str] = None
) -> bool:
    file_path = get_user_plan_file(user_id, telescope_id)
    temp_path = file_path + '.tmp'
    backup_path = file_path + '.backup'

    with _get_user_plan_lock(user_id):
        return _save_user_plan_locked(user_id, payload, username, file_path, temp_path, backup_path)


def _save_user_plan_locked(
    user_id: str,
    payload: Dict,
    username: Optional[str],
    file_path: str,
    temp_path: str,
    backup_path: str,
) -> bool:
    # Validate all three paths at the entry point so every file operation in
    # this function operates on a sanitized, realpath-resolved path.
    try:
        file_path = _safe_plan_path(file_path)
        temp_path = _safe_plan_path(temp_path)
        backup_path = _safe_plan_path(backup_path)
    except ValueError as ve:
        logger.error(f'_save_user_plan_locked: path validation failed for user {user_id}: {ve}')
        return False

    backup_created = False

    try:
        ensure_plan_directory()
        payload['user_id'] = user_id
        if username:
            payload['username'] = username
        payload.setdefault('username', username or 'unknown')
        payload.setdefault('created_at', _to_iso(_now()))
        payload['updated_at'] = _to_iso(_now())

        if os.path.exists(file_path):
            try:
                shutil.copy2(file_path, backup_path)
                backup_created = True
            except Exception as backup_error:
                logger.error(f'Failed to backup plan file for user {user_id}: {backup_error}')

        with open(temp_path, 'w', encoding='utf-8') as file_obj:
            json.dump(payload, file_obj, indent=2, ensure_ascii=False)

        is_valid, error_message = validate_plan_json(temp_path)
        if not is_valid:
            raise ValueError(error_message)

        os.replace(temp_path, file_path)

        if backup_created and os.path.exists(backup_path):
            os.remove(backup_path)

        return True
    except Exception as error:
        logger.error(f'Error saving plan for user {user_id}: {error}')

        if backup_created and os.path.exists(backup_path):
            try:
                os.replace(backup_path, file_path)
            except Exception as restore_error:
                logger.error(f'Failed to restore plan backup for user {user_id}: {restore_error}')

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as cleanup_error:
                logger.warning(f'Failed to clean temp plan file for user {user_id}: {cleanup_error}')

        if backup_created and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass  # best-effort backup cleanup on save failure; non-fatal

        return False


def _normalize_name(name: str) -> str:
    return skytonight_targets.normalize_object_name(name)


def _target_group_id(catalogue: str, name: str) -> str:
    entry = skytonight_targets.get_lookup_entry(catalogue, name)
    return str(entry.get('group_id', '') or '')


def _target_aliases(catalogue: str, name: str) -> Dict[str, str]:
    entry = skytonight_targets.get_lookup_entry(catalogue, name)
    aliases = entry.get('aliases', {}) if isinstance(entry, dict) else {}
    return aliases if isinstance(aliases, dict) else {}


def _entry_matches(entry: Dict, catalogue: str, name: str) -> bool:
    requested_group = _target_group_id(catalogue, name)
    if requested_group and entry.get('catalogue_group_id') == requested_group:
        return True

    requested_normalized = _normalize_name(name)
    if requested_normalized and requested_normalized == _normalize_name(entry.get('name', '')):
        return True

    aliases = entry.get('catalogue_aliases', {})
    if isinstance(aliases, dict):
        for alias_name in aliases.values():
            if requested_normalized and requested_normalized == _normalize_name(alias_name):
                return True

    return False


def is_target_in_entries(plan_entries: list, catalogue: str, name: str) -> bool:
    """Check if a target matches any of the given pre-loaded plan entries.

    Avoids repeated disk reads when checking many items against the same plan
    (e.g. annotating 1 000 DSO rows in a single API call).
    """
    for entry in plan_entries:
        if _entry_matches(entry, catalogue, name):
            return True
    return False


def is_target_in_current_plan(
    user_id: str, username: str, catalogue: str, name: str, telescope_id: Optional[str] = None
) -> bool:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return False
    if get_plan_state(plan) != 'current':
        return False

    for entry in plan.get('entries', []):
        if _entry_matches(entry, catalogue, name):
            return True

    return False


def _parse_hhmm_to_minutes(value: str) -> Optional[int]:
    text = str(value or '').strip()
    if not text:
        return None
    parts = text.split(':')
    if len(parts) != 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None
    if hours < 0 or minutes < 0 or minutes > 59:
        return None
    total = (hours * 60) + minutes
    return max(0, min(total, 24 * 60))


def _minutes_to_hhmm(minutes: int) -> str:
    safe_minutes = max(0, int(minutes))
    hours = safe_minutes // 60
    remainder = safe_minutes % 60
    return f'{hours:02d}:{remainder:02d}'


def get_plan_state(plan: Optional[Dict], now_dt: Optional[datetime] = None) -> str:
    if not plan:
        return 'none'

    now_value = now_dt or _now()
    night_end = _parse_datetime(plan.get('night_end'))
    if night_end and now_value > night_end:
        return 'previous'

    return 'current'


def _build_target_payload(item_data: Dict, catalogue: str) -> Dict:
    item_name = str(item_data.get('name') or item_data.get('id') or item_data.get('target name') or '').strip()
    group_id = _target_group_id(catalogue, item_name)
    aliases = _target_aliases(catalogue, item_name)

    planned_minutes = 60
    planned_minutes_value = item_data.get('planned_minutes')
    if planned_minutes_value is not None:
        try:
            planned_minutes = int(str(planned_minutes_value))
        except (TypeError, ValueError):
            planned_minutes = 60

    return {
        'id': str(uuid.uuid4()),
        'name': item_name,
        'catalogue': catalogue,
        'source_type': str(item_data.get('source_type') or '').strip() or 'report',
        'target_name': str(item_data.get('target name') or '').strip(),
        'type': str(item_data.get('type') or '').strip(),
        'constellation': str(item_data.get('constellation') or '').strip(),
        'ra': item_data.get('ra') or item_data.get('right ascension'),
        'dec': item_data.get('dec') or item_data.get('declination'),
        'mag': item_data.get('mag') or item_data.get('visual magnitude'),
        'size': item_data.get('size'),
        'foto': item_data.get('foto') or item_data.get('fraction of time observable'),
        'alttime_file': str(item_data.get('alttime_file') or '').strip(),
        'catalogue_group_id': group_id,
        'catalogue_aliases': aliases,
        'planned_minutes': max(0, min(planned_minutes, 24 * 60)),
        'planned_duration': _minutes_to_hhmm(planned_minutes),
        'done': bool(item_data.get('done', False)),
        'created_at': _to_iso(_now()),
        'updated_at': _to_iso(_now()),
    }


def create_or_add_target(
    user_id: str,
    username: str,
    item_data: Dict,
    catalogue: str,
    night_start: Any,
    night_end: Any,
    duration_hours: float = 0.0,
    telescope_id: Optional[str] = None,
    telescope_name: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict], Optional[Dict]]:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    now_dt = _now()

    state = get_plan_state(plan, now_dt)
    if state == 'previous':
        return False, 'previous_plan_locked', payload, None

    night_start_dt = _parse_datetime(night_start)
    night_end_dt = _parse_datetime(night_end)
    if not night_start_dt or not night_end_dt or night_end_dt <= night_start_dt:
        return False, 'invalid_night_window', payload, None

    if not plan:
        plan = {
            'plan_date': night_start_dt.date().isoformat(),
            'night_start': _to_iso(night_start_dt),
            'night_end': _to_iso(night_end_dt),
            'duration_hours': float(duration_hours or 0.0),
            'created_at': _to_iso(now_dt),
            'updated_at': _to_iso(now_dt),
            'telescope_id': telescope_id or None,
            'telescope_name': telescope_name or None,
            'entries': [],
        }
        payload['plan'] = plan

    entries = plan.setdefault('entries', [])
    item_name = str(item_data.get('name') or item_data.get('id') or item_data.get('target name') or '').strip()

    for entry in entries:
        if _entry_matches(entry, catalogue, item_name):
            return True, 'already_in_plan', payload, entry

    target = _build_target_payload(item_data, catalogue)
    entries.append(target)
    plan['updated_at'] = _to_iso(now_dt)

    if not save_user_plan(user_id, payload, username=username, telescope_id=telescope_id):
        return False, 'save_failed', payload, None

    return True, 'added', payload, target


def clear_plan(user_id: str, username: str, telescope_id: Optional[str] = None) -> bool:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    payload['plan'] = None
    return save_user_plan(user_id, payload, username=username, telescope_id=telescope_id)


def clear_all_plans(user_id: str) -> int:
    """Delete all plan files for this user. Returns the number of files deleted."""
    deleted = 0
    for file_path in get_all_plan_files(user_id):
        try:
            os.remove(file_path)
            deleted += 1
        except Exception as err:
            logger.error(f'Error deleting plan file {file_path}: {err}')
    return deleted


def remove_target(user_id: str, username: str, entry_id: str, telescope_id: Optional[str] = None) -> bool:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return False

    if get_plan_state(plan) == 'previous':
        return False

    entries = plan.get('entries', [])
    before = len(entries)
    plan['entries'] = [entry for entry in entries if entry.get('id') != entry_id]

    if len(plan['entries']) == before:
        return False

    plan['updated_at'] = _to_iso(_now())
    return save_user_plan(user_id, payload, username=username, telescope_id=telescope_id)


def update_target(
    user_id: str, username: str, entry_id: str, updates: Dict, telescope_id: Optional[str] = None
) -> Optional[Dict]:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return None

    if get_plan_state(plan) == 'previous':
        return None

    entries = plan.get('entries', [])
    target_entry = next((entry for entry in entries if entry.get('id') == entry_id), None)
    if not target_entry:
        return None

    if 'done' in updates:
        target_entry['done'] = bool(updates.get('done'))

    if 'planned_duration' in updates:
        parsed_minutes = _parse_hhmm_to_minutes(str(updates.get('planned_duration')))
        if parsed_minutes is not None:
            target_entry['planned_minutes'] = parsed_minutes
            target_entry['planned_duration'] = _minutes_to_hhmm(parsed_minutes)

    if 'planned_minutes' in updates:
        planned_minutes_value = updates.get('planned_minutes')
        try:
            parsed_minutes = int(str(planned_minutes_value))
            target_entry['planned_minutes'] = max(0, min(parsed_minutes, 24 * 60))
            target_entry['planned_duration'] = _minutes_to_hhmm(target_entry['planned_minutes'])
        except (TypeError, ValueError):
            pass  # non-integer planned_minutes — leave field unchanged

    target_entry['updated_at'] = _to_iso(_now())
    plan['updated_at'] = _to_iso(_now())

    if not save_user_plan(user_id, payload, username=username, telescope_id=telescope_id):
        return None

    return target_entry


def update_plan_meta(user_id: str, username: str, updates: Dict, telescope_id: Optional[str] = None) -> Optional[Dict]:
    """Update plan-level metadata fields (e.g. start_delay_minutes)."""
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return None

    if get_plan_state(plan) == 'previous':
        return None

    if 'start_delay_minutes' in updates:
        try:
            delay = max(0, min(int(updates['start_delay_minutes']), 23 * 60 + 59))
        except (TypeError, ValueError):
            delay = 0
        plan['start_delay_minutes'] = delay

    plan['updated_at'] = _to_iso(_now())
    if not save_user_plan(user_id, payload, username=username, telescope_id=telescope_id):
        return None
    return plan


def reorder_target(
    user_id: str, username: str, entry_id: str, new_index: int, telescope_id: Optional[str] = None
) -> bool:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return False

    if get_plan_state(plan) == 'previous':
        return False

    entries = plan.get('entries', [])
    current_index = next((index for index, entry in enumerate(entries) if entry.get('id') == entry_id), None)
    if current_index is None:
        return False

    bounded_new_index = max(0, min(int(new_index), len(entries) - 1))
    if bounded_new_index == current_index:
        return True

    entry = entries.pop(current_index)
    entries.insert(bounded_new_index, entry)
    plan['updated_at'] = _to_iso(_now())

    return save_user_plan(user_id, payload, username=username, telescope_id=telescope_id)


def get_plan_with_timeline(user_id: str, username: str, telescope_id: Optional[str] = None) -> Dict:
    payload = load_user_plan(user_id, username, telescope_id=telescope_id)
    plan = payload.get('plan')
    if not plan:
        return {
            'state': 'none',
            'plan': None,
            'timeline': {
                'progress_percent': 0.0,
                'is_inside_night': False,
                'current_target_id': None,
            },
            'current_banner': None,
        }

    plan_copy = copy.deepcopy(plan)
    state = get_plan_state(plan_copy)

    entries = plan_copy.get('entries', [])
    night_start = _parse_datetime(plan_copy.get('night_start'))
    night_end = _parse_datetime(plan_copy.get('night_end'))

    now_dt = _now()
    progress_percent = 0.0
    is_inside_night = False
    current_target_id = None

    if night_start and night_end and night_end > night_start:
        total_seconds = (night_end - night_start).total_seconds()
        if total_seconds > 0:
            elapsed_seconds = (now_dt - night_start).total_seconds()
            progress_percent = max(0.0, min(100.0, (elapsed_seconds / total_seconds) * 100.0))
        is_inside_night = night_start <= now_dt <= night_end

        start_delay_minutes = int(plan_copy.get('start_delay_minutes') or 0)
        cursor = night_start + timedelta(minutes=start_delay_minutes)
        for entry in entries:
            planned_minutes = int(entry.get('planned_minutes') or 0)
            start_dt = cursor
            end_dt = cursor
            if planned_minutes > 0:
                end_dt = cursor + timedelta(minutes=planned_minutes)
            if end_dt > night_end:
                end_dt = night_end

            entry['timeline_start'] = _to_iso(start_dt)
            entry['timeline_end'] = _to_iso(end_dt)

            if is_inside_night and not entry.get('done') and start_dt <= now_dt <= end_dt:
                current_target_id = entry.get('id')

            cursor = end_dt

    current_entry = next((entry for entry in entries if entry.get('id') == current_target_id), None)

    return {
        'state': state,
        'plan': plan_copy,
        'timeline': {
            'progress_percent': round(progress_percent, 2),
            'is_inside_night': is_inside_night,
            'current_target_id': current_target_id,
        },
        'current_banner': current_entry,
    }


def _csv_normalize_ra(val) -> str:
    """Normalize RA to HH:MM:SS (J2000 sexagesimal)."""
    if val is None:
        return ''
    s = str(val).strip()
    m = re.match(r'(\d+)\s*h\s*(\d+)\s*m\s*([\d.]+)\s*s?', s, re.IGNORECASE)
    if m:
        h, mn, sec = int(m.group(1)), int(m.group(2)), round(float(m.group(3)))
        if sec == 60:
            sec, mn = 0, mn + 1
        return f'{h:02d}:{mn:02d}:{sec:02d}'
    try:
        total_h = float(s) / 15.0
        h = int(total_h)
        mn = int((total_h % 1) * 60)
        sec = round(((total_h % 1) * 60 % 1) * 60)
        if sec == 60:
            sec, mn = 0, mn + 1
        return f'{h:02d}:{mn:02d}:{sec:02d}'
    except (ValueError, TypeError):
        return s


def _csv_normalize_dec(val) -> str:
    """Normalize Dec to ±DD:MM:SS (J2000 sexagesimal)."""
    if val is None:
        return ''
    s = str(val).strip().replace('Â°', '°').replace('Â', '')
    m = re.match(r'([+-]?\s*\d+)\s*[°d]\s*(\d+)\s*[\'m]\s*([\d.]+)', s)
    if m:
        d = int(m.group(1).replace(' ', ''))
        mn = int(m.group(2))
        sec = round(float(m.group(3)))
        if sec == 60:
            sec, mn = 0, mn + 1
        sign = '-' if d < 0 else '+'
        return f'{sign}{abs(d):02d}:{mn:02d}:{sec:02d}'
    try:
        deg = float(s)
        sign = '-' if deg < 0 else '+'
        adeg = abs(deg)
        d = int(adeg)
        mn = int((adeg % 1) * 60)
        sec = round(((adeg % 1) * 60 % 1) * 60)
        if sec == 60:
            sec, mn = 0, mn + 1
        return f'{sign}{d:02d}:{mn:02d}:{sec:02d}'
    except (ValueError, TypeError):
        return s


def _csv_fmt_local_hm(iso_str) -> str:
    """Format an ISO datetime string as local HH:MM."""
    if not iso_str:
        return ''
    try:
        return datetime.fromisoformat(iso_str).strftime('%H:%M')
    except (ValueError, TypeError):
        return str(iso_str)


def _csv_fmt_observable_pct(val) -> str:
    """Format a 0-1 fraction as an integer percentage string."""
    if val is None or val == '':
        return ''
    try:
        return f'{float(val) * 100:.0f}%'
    except (ValueError, TypeError):
        return str(val)


def serialize_plan_csv(plan_payload: Dict, labels: Optional[Dict[str, str]] = None) -> str:
    labels = labels or {}

    def _label(key: str, fallback: str) -> str:
        return str(labels.get(key) or fallback)

    header = [
        _label('order', 'order'),
        _label('name', 'name'),
        _label('catalogue', 'catalogue'),
        _label('target_name', 'target_name'),
        _label('type', 'type'),
        _label('constellation', 'constellation'),
        _label('ra', 'RA (J2000)'),
        _label('dec', 'Dec (J2000)'),
        _label('mag', 'mag'),
        _label('size', 'size (\'\''),
        _label('observable_pct', 'observable %'),
        _label('planned_minutes', 'duration (min)'),
        _label('timeline_start', 'start'),
        _label('timeline_end', 'end'),
        _label('done', 'done'),
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)

    plan = plan_payload.get('plan')
    if not plan:
        return output.getvalue()

    for index, entry in enumerate(plan.get('entries', []), start=1):
        writer.writerow(
            [
                index,
                str(entry.get('name', '')),
                str(entry.get('catalogue', '')),
                str(entry.get('target_name', '')),
                str(entry.get('type', '')),
                str(entry.get('constellation', '')),
                _csv_normalize_ra(entry.get('ra')),
                _csv_normalize_dec(entry.get('dec')),
                str(entry.get('mag', '')),
                str(entry.get('size', '')),
                _csv_fmt_observable_pct(entry.get('foto')),
                str(entry.get('planned_minutes', '')),
                _csv_fmt_local_hm(entry.get('timeline_start')),
                _csv_fmt_local_hm(entry.get('timeline_end')),
                _label('done_yes', 'yes') if entry.get('done') else _label('done_no', 'no'),
            ]
        )

    return output.getvalue()


def get_all_plan_states(user_id: str, username: str, telescopes: list) -> list:
    """Return a list of plan summaries for each telescope plus the default (no-telescope) plan.

    Each element: {telescope_id, telescope_name, state, entries_count, night_start, night_end}
    """
    result = []
    # Include the default plan (no telescope) only if it exists on disk
    default_file = get_user_plan_file(user_id, None)
    if os.path.exists(default_file):
        payload = load_user_plan(user_id, username, telescope_id=None)
        plan = payload.get('plan')
        state = get_plan_state(plan)
        result.append(
            {
                'telescope_id': None,
                'telescope_name': None,
                'state': state,
                'entries_count': len(plan.get('entries', [])) if plan else 0,
                'night_start': plan.get('night_start') if plan else None,
                'night_end': plan.get('night_end') if plan else None,
            }
        )

    known_ids: set = set()
    for telescope in telescopes:
        tid = telescope.get('id')
        tname = telescope.get('name', '')
        is_own = telescope.get('is_own', True)
        owner_username = telescope.get('owner_username')
        known_ids.add(tid)
        payload = load_user_plan(user_id, username, telescope_id=tid)
        plan = payload.get('plan')
        state = get_plan_state(plan)
        result.append(
            {
                'telescope_id': tid,
                'telescope_name': tname,
                'state': state,
                'entries_count': len(plan.get('entries', [])) if plan else 0,
                'night_start': plan.get('night_start') if plan else None,
                'night_end': plan.get('night_end') if plan else None,
                'is_own': is_own,
                'owner_username': owner_username,
                'is_orphaned': False,
            }
        )

    # Detect orphaned plans: plan files exist but their telescope is no longer accessible
    # (shared telescope was removed or unshared by its owner)
    prefix = f'{user_id}_plan_'
    suffix = '.json'
    for plan_file in get_all_plan_files(user_id):
        fname = os.path.basename(plan_file)
        if not (fname.startswith(prefix) and fname.endswith(suffix)):
            continue
        tid = fname[len(prefix) : -len(suffix)]
        if tid == 'my_night' or tid in known_ids:
            continue
        payload = load_user_plan(user_id, username, telescope_id=tid)
        plan = payload.get('plan')
        orphaned_name = (plan.get('telescope_name') if plan else None) or tid
        state = get_plan_state(plan)
        result.append(
            {
                'telescope_id': tid,
                'telescope_name': orphaned_name,
                'state': state,
                'entries_count': len(plan.get('entries', [])) if plan else 0,
                'night_start': plan.get('night_start') if plan else None,
                'night_end': plan.get('night_end') if plan else None,
                'is_own': True,
                'owner_username': None,
                'is_orphaned': True,
            }
        )

    return result


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


def generate_plan_pdf(payload: Dict, metrics: Dict, i18n_manager) -> io.BytesIO:
    """Render the observation plan as a print-friendly A4 PDF.

    Parameters
    ----------
    payload:      output of :func:`get_plan_with_timeline`
    metrics:      output of ``_compute_plan_fill_metrics`` from app.py
    i18n_manager: :class:`i18n_utils.I18nManager` instance for the request language
    """
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    from datetime import timezone
    import re as _re
    from constants import SKYTONIGHT_OUTPUT_DIR

    plan = payload.get('plan')
    entries = plan.get('entries', []) if plan else []

    t = i18n_manager.t  # shorthand

    # ── colour palette (high-contrast, print-friendly) ──────────────────────
    PALETTE = [
        '#1565c0',
        '#c62828',
        '#2e7d32',
        '#6a1b9a',
        '#e65100',
        '#00838f',
        '#558b2f',
        '#ad1457',
        '#4527a0',
        '#e65100',
        '#0277bd',
        '#6d4c41',
    ]

    # ── print-friendly colours ───────────────────────────────────────────────
    C_HDR_BG = '#1a1f35'
    C_WHITE = '#ffffff'
    C_TXT_DRK = '#212121'
    C_TXT_MID = '#616161'
    C_GRID = '#e0e0e0'
    C_BAR_BG = '#e0e7ff'
    C_BRAND = '#4e9af1'
    C_CHT_TXT = '#424242'
    C_CHT_GRID = '#eeeeee'
    C_CHT_ZONE = '#e8f5e9'
    C_CHT_ZONE_BORDER = '#66bb6a'
    C_NIGHT_LN = '#37474f'

    # ── helpers ──────────────────────────────────────────────────────────────
    _safe_re = _re.compile(r'[^a-z0-9_-]')

    def _load_alttime(alttime_file: str):
        if not alttime_file:
            return None
        safe = _safe_re.sub('_', str(alttime_file).lower())
        path = os.path.normpath(os.path.join(SKYTONIGHT_OUTPUT_DIR, f'{safe}_alttime.json'))
        if not os.path.isfile(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return None

    def _parse_utc(s):
        if not s:
            return None
        try:
            text = str(s).strip()
            if text.endswith('Z'):
                dt = datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            return None

    _local_tz: Any = timezone.utc  # updated after alttime_map is loaded

    def _fmt_hm(iso_str: str | None) -> str:
        dt = _parse_utc(iso_str)
        return dt.astimezone(_local_tz).strftime('%H:%M') if dt else '--:--'

    def _fmt_date(iso_str: str | None) -> str:
        dt = _parse_utc(iso_str)
        return dt.strftime('%B %d, %Y') if dt else '?'

    def _fmt_min(minutes) -> str:
        m = max(0, int(minutes))
        return f"{m // 60}h{m % 60:02d}"

    def _clip_alttime(times_utc, altitudes, start_dt, end_dt):
        """Clip altitude series to [start_dt, end_dt] with boundary interpolation."""
        if not times_utc or not altitudes or not start_dt or not end_dt or start_dt >= end_dt:
            return [], []
        pts = []
        for raw_t, a in zip(times_utc, altitudes):
            dt = _parse_utc(raw_t)
            if dt is not None and a is not None:
                pts.append((dt, float(a)))
        if not pts:
            return [], []

        def _lerp(p0, p1, x):
            span = (p1[0] - p0[0]).total_seconds()
            if span == 0:
                return x, p0[1]
            frac = (x - p0[0]).total_seconds() / span
            return x, p0[1] + frac * (p1[1] - p0[1])

        out = []
        for i, p in enumerate(pts):
            prev = pts[i - 1] if i > 0 else None
            nxt = pts[i + 1] if i < len(pts) - 1 else None
            if prev and prev[0] < start_dt < p[0]:
                out.append(_lerp(prev, p, start_dt))
            if start_dt <= p[0] <= end_dt:
                out.append(p)
            if nxt and p[0] < end_dt < nxt[0]:
                out.append(_lerp(p, nxt, end_dt))
        if not out:
            return [], []
        xs, ys = zip(*out)
        return list(xs), list(ys)

    # ── load altitude-time JSON files ────────────────────────────────────────
    alttime_map: Dict[str, Any] = {}
    for entry in entries:
        af = entry.get('alttime_file')
        if af:
            data = _load_alttime(af)
            if data:
                alttime_map[entry.get('id')] = data

    # ── resolve local timezone from alttime data (matches browser display) ───
    from zoneinfo import ZoneInfo as _ZoneInfo

    _tz_name = (next(iter(alttime_map.values()), None) or {}).get('timezone') or 'UTC'
    try:
        _local_tz = _ZoneInfo(_tz_name)
    except Exception:
        _local_tz = timezone.utc
        _tz_name = 'UTC'

    # ── shared header / footer ───────────────────────────────────────────────
    def _render_header(ax, subtitle: str = '') -> None:
        ax.axis('off')
        ax.set_facecolor(C_HDR_BG)
        ax.text(
            0.015,
            0.5,
            'myastroboard',
            va='center',
            ha='left',
            fontsize=10,
            color=C_BRAND,
            fontweight='bold',
            transform=ax.transAxes,
        )
        title = t('plan_my_night.export_pdf_title') or 'My Observation Plan'
        if subtitle:
            title += f'  -  {subtitle}'
        ax.text(
            0.5,
            0.5,
            title,
            va='center',
            ha='center',
            fontsize=12,
            color=C_WHITE,
            fontweight='bold',
            transform=ax.transAxes,
        )
        ax.text(
            0.985, 0.5, 'myastroboard.org', va='center', ha='right', fontsize=8, color='#8898cc', transform=ax.transAxes
        )

    def _render_footer(ax) -> None:
        ax.axis('off')
        ax.set_facecolor(C_HDR_BG)
        ax.text(
            0.5,
            0.5,
            f"myastroboard.org  -  {t('common.title_html') or 'MyAstroBoard'}",
            va='center',
            ha='center',
            fontsize=7.5,
            color='#6a7a99',
            transform=ax.transAxes,
        )

    # ── column layout ────────────────────────────────────────────────────────
    COL_X = [0.00, 0.38, 0.54, 0.66, 0.80]
    COL_H = [
        t('plan_my_night.export_pdf_col_target') or 'Target',
        t('plan_my_night.export_pdf_slot') or 'Slot',
        t('plan_my_night.export_pdf_duration') or 'Duration',
        t('plan_my_night.export_pdf_type') or 'Type',
        t('plan_my_night.export_pdf_constellation') or 'Constellation',
    ]

    def _render_col_headers(ax, y: float) -> float:
        for cx, cl in zip(COL_X, COL_H):
            ax.text(
                cx, y, cl, va='top', ha='left', fontsize=7, color=C_TXT_MID, fontweight='bold', transform=ax.transAxes
            )
        y -= 0.013
        ax.plot([0.0, 1.0], [y + 0.005, y + 0.005], color=C_GRID, lw=0.7, transform=ax.transAxes)
        return y - 0.004

    ROW_H = 0.030  # compact fixed row height

    def _render_entry_row(ax, abs_idx: int, entry: Dict, y: float) -> None:
        color = PALETTE[abs_idx % len(PALETTE)]
        done = bool(entry.get('done'))
        name = (entry.get('name') or entry.get('target_name') or '?')[:26]
        cat = entry.get('catalogue') or ''
        ts = _fmt_hm(entry.get('timeline_start'))
        te = _fmt_hm(entry.get('timeline_end'))
        dur = entry.get('planned_duration') or '--:--'
        typ = (entry.get('type') or '')[:16]
        const = (entry.get('constellation') or '')[:13]

        row_bg = '#f5f7fc' if abs_idx % 2 == 0 else C_WHITE
        ax.add_patch(
            Rectangle((0.0, y - ROW_H), 1.0, ROW_H, transform=ax.transAxes, facecolor=row_bg, edgecolor='none')
        )
        mid_y = y - ROW_H / 2
        ax.plot(0.007, mid_y, 'o', color=color, markersize=4.5, transform=ax.transAxes, zorder=5)

        check = '✓' if done else '○'
        name_txt = f"{abs_idx + 1}. {check}  {name}"
        if cat:
            name_txt += f' ({cat})'
        ax.text(
            0.018,
            mid_y,
            name_txt,
            va='center',
            ha='left',
            fontsize=7.5,
            color=C_TXT_MID if done else C_TXT_DRK,
            fontstyle='italic' if done else 'normal',
            transform=ax.transAxes,
        )
        ax.text(
            COL_X[1], mid_y, f"{ts}→{te}", va='center', ha='left', fontsize=7.5, color=C_TXT_DRK, transform=ax.transAxes
        )
        ax.text(COL_X[2], mid_y, dur, va='center', ha='left', fontsize=7.5, color=C_TXT_DRK, transform=ax.transAxes)
        ax.text(COL_X[3], mid_y, typ, va='center', ha='left', fontsize=7, color=C_TXT_DRK, transform=ax.transAxes)
        ax.text(COL_X[4], mid_y, const, va='center', ha='left', fontsize=7, color=C_TXT_DRK, transform=ax.transAxes)

    def _setup_list_ax(ax) -> None:
        ax.set_facecolor(C_WHITE)
        ax.axis('off')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    # ── build PDF pages ──────────────────────────────────────────────────────
    buffer = io.BytesIO()
    MAX_P1 = 10
    PER_PAGE = 28

    with PdfPages(buffer) as pdf:

        # ─── PAGE 1 ─────────────────────────────────────────────────────────
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor(C_WHITE)

        # rows: header | info | chart | spacer | list | footer
        gs = gridspec.GridSpec(
            6,
            1,
            figure=fig,
            height_ratios=[0.065, 0.095, 0.355, 0.015, 0.445, 0.025],
            hspace=0.01,
            left=0.10,
            right=0.90,
            top=0.985,
            bottom=0.015,
        )

        _render_header(fig.add_subplot(gs[0]))

        # info panel
        ax_info = fig.add_subplot(gs[1])
        ax_info.set_facecolor('#f4f6fb')
        ax_info.axis('off')
        ax_info.set_xlim(0, 1)
        ax_info.set_ylim(0, 1)

        if not plan:
            ax_info.text(
                0.5,
                0.55,
                t('plan_my_night.export_pdf_no_plan') or 'No plan available.',
                va='center',
                ha='center',
                fontsize=11,
                color=C_TXT_MID,
                transform=ax_info.transAxes,
            )
        else:
            date_str = _fmt_date(plan.get('night_start'))
            ns_str = _fmt_hm(plan.get('night_start'))
            ne_str = _fmt_hm(plan.get('night_end'))
            scope = (plan.get('telescope_name') or '').strip()
            n_tgts = len(entries)
            fill_pct = metrics.get('fill_percent', 0.0)
            planned = _fmt_min(metrics.get('planned_minutes', 0))
            night_d = _fmt_min(metrics.get('night_minutes', 0))
            delay = int(plan.get('start_delay_minutes') or 0)
            delay_s = f'  (+{delay} min)' if delay else ''

            ax_info.text(
                0.01,
                0.88,
                f"{t('plan_my_night.export_pdf_date') or 'Date'}:  {date_str}",
                va='top',
                ha='left',
                fontsize=9.5,
                color=C_TXT_DRK,
                transform=ax_info.transAxes,
            )
            if scope:
                ax_info.text(
                    0.50,
                    0.88,
                    f"{t('plan_my_night.export_pdf_telescope') or 'Telescope'}:" f"  {scope}",
                    va='top',
                    ha='left',
                    fontsize=9.5,
                    color=C_TXT_DRK,
                    transform=ax_info.transAxes,
                )
            ax_info.text(
                0.01,
                0.58,
                f"{t('plan_my_night.export_pdf_night_window') or 'Night window'}:" f"  {ns_str} → {ne_str}{delay_s}",
                va='top',
                ha='left',
                fontsize=9.5,
                color=C_TXT_DRK,
                transform=ax_info.transAxes,
            )
            ax_info.text(
                0.50,
                0.58,
                f"{t('plan_my_night.export_pdf_targets') or 'Targets'}:  {n_tgts}",
                va='top',
                ha='left',
                fontsize=9.5,
                color=C_TXT_DRK,
                transform=ax_info.transAxes,
            )

            bx, by, bw, bh = 0.01, 0.07, 0.98, 0.20
            fill_w = min(1.0, fill_pct / 100.0) * bw
            bar_color = C_BRAND if fill_pct <= 100 else '#e53935'
            ax_info.add_patch(
                Rectangle((bx, by), bw, bh, transform=ax_info.transAxes, facecolor=C_BAR_BG, edgecolor='none')
            )
            if fill_w > 0.01:
                ax_info.add_patch(
                    Rectangle((bx, by), fill_w, bh, transform=ax_info.transAxes, facecolor=bar_color, edgecolor='none')
                )
            overflow = metrics.get('overflow_minutes', 0)
            cov_lbl = (
                f"{t('plan_my_night.export_pdf_planned_coverage') or 'Coverage'}:"
                f"  {fill_pct:.0f}%   ({planned} / {night_d})"
            )
            if overflow > 0:
                cov_lbl += f"   {t('plan_my_night.export_pdf_overflow') or 'Overflow'}:" f" +{_fmt_min(overflow)}"
            ax_info.text(
                bx + bw / 2,
                by + bh / 2,
                cov_lbl,
                va='center',
                ha='center',
                fontsize=8.5,
                color=C_WHITE if fill_pct > 12 else C_TXT_DRK,
                fontweight='bold',
                transform=ax_info.transAxes,
            )

        # altitude-time chart
        ax_chart = fig.add_subplot(gs[2])
        ax_chart.set_facecolor(C_WHITE)
        for spine in ax_chart.spines.values():
            spine.set_edgecolor(C_GRID)
            spine.set_linewidth(0.7)

        chart_ok = False
        if plan and alttime_map:
            ns_dt = _parse_utc(plan.get('night_start'))
            ne_dt = _parse_utc(plan.get('night_end'))

            if ns_dt and ne_dt:
                chart_ok = True
                first_data = next(iter(alttime_map.values()), {})
                alt_min = first_data.get('altitude_constraint_min', 30)
                alt_max = first_data.get('altitude_constraint_max', 80)

                ax_chart.axhspan(alt_min, alt_max, color=C_CHT_ZONE, alpha=0.8, zorder=1)
                ax_chart.axhline(y=alt_min, color=C_CHT_ZONE_BORDER, lw=0.8, ls='--', alpha=0.8, zorder=2)
                ax_chart.axhline(y=alt_max, color=C_CHT_ZONE_BORDER, lw=0.8, ls='--', alpha=0.8, zorder=2)

                for i, entry in enumerate(entries):
                    eid = entry.get('id')
                    adata = alttime_map.get(eid)
                    if not adata:
                        continue
                    color = PALETTE[i % len(PALETTE)]
                    t_start = _parse_utc(entry.get('timeline_start'))
                    t_end = _parse_utc(entry.get('timeline_end'))
                    if not t_start or not t_end:
                        continue
                    t_end = min(t_end, ne_dt)  # cap at night end, mirrors JS Math.min(rawEndMs, nightEndMs)
                    if t_end <= t_start:
                        continue

                    xs, ys = _clip_alttime(
                        adata.get('times_utc', []),
                        adata.get('altitudes', []),
                        t_start,
                        t_end,
                    )
                    if not xs:
                        continue

                    ax_chart.plot(xs, ys, color=color, lw=1.8, zorder=4)
                    ax_chart.fill_between(xs, 0, ys, color=color, alpha=0.07, zorder=3)

                    peak_idx = ys.index(max(ys))
                    label = (entry.get('name') or entry.get('target_name') or '')[:14]
                    ax_chart.annotate(
                        label,
                        xy=(xs[peak_idx], ys[peak_idx]),
                        xytext=(0, 5),
                        textcoords='offset points',
                        fontsize=6.5,
                        color=color,
                        fontweight='bold',
                        ha='center',
                        va='bottom',
                        zorder=6,
                        clip_on=True,
                    )

                ns_num = float(mdates.date2num(ns_dt))
                ne_num = float(mdates.date2num(ne_dt))
                ax_chart.axvline(x=ns_num, color=C_NIGHT_LN, lw=0.8, zorder=5)
                ax_chart.axvline(x=ne_num, color=C_NIGHT_LN, lw=0.8, zorder=5)
                ax_chart.set_xlim(ns_num, ne_num)
                ax_chart.set_ylim(0, 90)
                ax_chart.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=_local_tz))
                ax_chart.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=_local_tz))
                ax_chart.tick_params(colors=C_CHT_TXT, labelsize=7.5)
                ax_chart.tick_params(axis='x', colors=C_CHT_TXT)
                ax_chart.tick_params(axis='y', colors=C_CHT_TXT)
                ax_chart.set_ylabel(
                    t('skytonight.altitude_time_y_axis') or 'Altitude (°)',
                    color=C_CHT_TXT,
                    fontsize=8,
                )
                ax_chart.set_xlabel(
                    f"{t('skytonight.altitude_time_x_axis') or 'Time'} ({_tz_name})",
                    color=C_CHT_TXT,
                    fontsize=8,
                )
                ax_chart.yaxis.label.set_color(C_CHT_TXT)
                ax_chart.xaxis.label.set_color(C_CHT_TXT)
                ax_chart.grid(True, color=C_CHT_GRID, lw=0.5)
                # title inside axes area - no risk of overlapping adjacent panels
                ax_chart.text(
                    0.01,
                    0.97,
                    t('skytonight.altitude_time_title') or 'Altitude vs Time',
                    va='top',
                    ha='left',
                    fontsize=8,
                    color=C_TXT_MID,
                    fontstyle='italic',
                    transform=ax_chart.transAxes,
                    zorder=7,
                )

        if not chart_ok:
            ax_chart.axis('off')
            ax_chart.text(
                0.5,
                0.5,
                (t('skytonight.altitude_time_title') or 'Altitude vs Time')
                + '\n'
                + (t('skytonight.altitude_time_load_error') or 'No data available'),
                va='center',
                ha='center',
                fontsize=9,
                color=C_TXT_MID,
                linespacing=1.7,
                transform=ax_chart.transAxes,
            )

        # explicit spacer between chart and target list
        fig.add_subplot(gs[3]).axis('off')

        # target list
        ax_list = fig.add_subplot(gs[4])
        _setup_list_ax(ax_list)

        if not entries:
            ax_list.text(
                0.5,
                0.55,
                t('plan_my_night.export_pdf_no_plan') or 'No targets.',
                va='center',
                ha='center',
                fontsize=10,
                color=C_TXT_MID,
                transform=ax_list.transAxes,
            )
        else:
            y = 0.975
            ax_list.text(
                0.0,
                y,
                t('plan_my_night.export_pdf_section_targets') or 'Planned targets',
                va='top',
                ha='left',
                fontsize=9,
                color=C_TXT_DRK,
                fontweight='bold',
                transform=ax_list.transAxes,
            )
            y -= 0.032
            y = _render_col_headers(ax_list, y)

            for idx, entry in enumerate(entries[:MAX_P1]):
                _render_entry_row(ax_list, idx, entry, y)
                y -= ROW_H

            if len(entries) > MAX_P1:
                ax_list.text(
                    0.5,
                    0.005,
                    f'+ {len(entries) - MAX_P1} targets continued on next page',
                    va='bottom',
                    ha='center',
                    fontsize=7,
                    color=C_TXT_MID,
                    transform=ax_list.transAxes,
                )

        _render_footer(fig.add_subplot(gs[5]))
        pdf.savefig(fig)
        plt.close(fig)

        # ─── OVERFLOW PAGES ──────────────────────────────────────────────────
        if entries and len(entries) > MAX_P1:
            remaining = entries[MAX_P1:]
            chunks = [remaining[i : i + PER_PAGE] for i in range(0, len(remaining), PER_PAGE)]

            for chunk_idx, chunk in enumerate(chunks):
                fig2 = plt.figure(figsize=(8.27, 11.69))
                fig2.patch.set_facecolor(C_WHITE)
                gs2 = gridspec.GridSpec(
                    3,
                    1,
                    figure=fig2,
                    height_ratios=[0.065, 0.910, 0.025],
                    hspace=0.01,
                    left=0.10,
                    right=0.90,
                    top=0.985,
                    bottom=0.015,
                )
                _render_header(fig2.add_subplot(gs2[0]), subtitle=f'Page {chunk_idx + 2}')

                ax_t = fig2.add_subplot(gs2[1])
                _setup_list_ax(ax_t)
                y = 0.990
                y = _render_col_headers(ax_t, y)
                for i, entry in enumerate(chunk):
                    abs_idx = MAX_P1 + chunk_idx * PER_PAGE + i
                    _render_entry_row(ax_t, abs_idx, entry, y)
                    y -= ROW_H

                _render_footer(fig2.add_subplot(gs2[2]))
                pdf.savefig(fig2)
                plt.close(fig2)

    buffer.seek(0)
    return buffer
