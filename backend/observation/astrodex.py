"""
Astrodex Module - Pokédex-style collection system for astrophotography objects
Manages user collections of celestial objects they have photographed
"""

import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from utils.logging_config import get_logger
from constellation import Constellation
from observation import catalogue_aliases
from skytonight import skytonight_targets

logger = get_logger(__name__)

# Per-user write locks to prevent race conditions on concurrent saves
_user_save_locks: Dict[str, threading.Lock] = {}
_user_save_locks_mutex = threading.Lock()


def _get_user_save_lock(user_id: str) -> threading.Lock:
    """Get or create a per-user lock for serializing file writes."""
    with _user_save_locks_mutex:
        if user_id not in _user_save_locks:
            _user_save_locks[user_id] = threading.Lock()
        return _user_save_locks[user_id]


# Astrodex data directory
ASTRODEX_DIR = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'astrodex')
ASTRODEX_IMAGES_DIR = os.path.join(ASTRODEX_DIR, 'images')

# Default image for items without pictures
DEFAULT_IMAGE = 'default_astro_object.png'

TRANSIENT_ITEM_FIELDS = {'catalogue_aliases', 'catalogue_group_id'}
UNUSED_ITEM_FIELDS = {'ra', 'dec', 'magnitude', 'size'}


def _normalize_name(name: str) -> str:
    """Normalize names for resilient comparisons."""
    return skytonight_targets.normalize_object_name(name)


def _strip_parenthesized_text(value: str) -> str:
    """Remove parenthesized segments using a linear scan."""
    result_chars: List[str] = []
    depth = 0

    for char in value:
        if char == '(':
            depth += 1
            continue
        if char == ')' and depth > 0:
            depth -= 1
            continue
        if depth == 0:
            result_chars.append(char)

    return ''.join(result_chars)


def _normalize_whitespace(value: str) -> str:
    """Collapse whitespace to single spaces without regex."""
    return ' '.join(str(value).split())


def _extract_name_candidates(name: str) -> List[str]:
    """Extract likely catalogue identifier candidates from a raw target label."""
    raw = str(name or '').strip()
    if not raw:
        return []

    candidates: List[str] = [raw]

    no_parentheses = _normalize_whitespace(_strip_parenthesized_text(raw))
    if no_parentheses and no_parentheses not in candidates:
        candidates.append(no_parentheses)

    identifier_patterns = [
        r'\bM\s*\d+\b',
        r'\bNGC\s*\d+[A-Z]?\b',
        r'\bIC\s*\d+[A-Z]?\b',
        r'\bLBN\s*\d+\b',
        r'\bLDN\s*\d+\b',
        r'\bARP\s*\d+\b',
        r'\bABELL\s*\d+\b',
        r'\bBARNARD\s*\d+\b',
        r'\bVDB\s*\d+\b',
        r'\bSH2[-\s]?\d+\b',
    ]

    for pattern in identifier_patterns:
        for match in re.findall(pattern, raw, flags=re.IGNORECASE):
            match_value = _normalize_whitespace(str(match))
            if match_value and match_value not in candidates:
                candidates.append(match_value)

    return candidates


def _get_alias_for_catalogue(aliases: Dict[str, str], catalogue: str) -> str:
    """Return alias name for a catalogue using case-insensitive key lookup."""
    if not catalogue or not isinstance(aliases, dict):
        return ''

    direct = aliases.get(catalogue)
    if direct:
        return str(direct)

    catalogue_normalized = str(catalogue).strip().lower()
    for key, value in aliases.items():
        if str(key).strip().lower() == catalogue_normalized:
            return str(value or '')

    return ''


def _get_alias_metadata(catalogue: str, object_name: str) -> tuple[str, Dict[str, str]]:
    """Get aliases group metadata from the SkyTonight target resolver."""
    if not catalogue or not object_name:
        return '', {}

    entry = skytonight_targets.get_lookup_entry(catalogue, object_name)
    if not entry:
        return '', {}

    group_id = str(entry.get('group_id', '') or '')
    aliases = entry.get('aliases', {})
    if not isinstance(aliases, dict):
        aliases = {}

    return group_id, aliases


def _get_item_alias_metadata(item: Dict) -> tuple[str, Dict[str, str]]:
    """Get item aliases metadata from current aliases table (no persisted cache)."""
    inferred_group_id, inferred_aliases = _get_alias_metadata(item.get('catalogue', ''), item.get('name', ''))
    if inferred_aliases:
        return inferred_group_id, inferred_aliases

    return '', {}


def _sanitize_item_for_persistence(item: Dict) -> None:
    """Remove transient and unused fields from a persisted astrodex item."""
    if not isinstance(item, dict):
        return

    for field_name in TRANSIENT_ITEM_FIELDS | UNUSED_ITEM_FIELDS:
        item.pop(field_name, None)


def _sanitize_astrodex_for_persistence(astrodex_data: Dict) -> None:
    """Normalize astrodex payload before writing to disk."""
    if not isinstance(astrodex_data, dict):
        return

    items = astrodex_data.get('items', [])
    if not isinstance(items, list):
        return

    for item in items:
        _sanitize_item_for_persistence(item)


def _get_item_merge_key(item: Dict) -> str:
    """Build a stable merge key for an astrodex item (aliases group first)."""
    group_id, aliases = _get_item_alias_metadata(item)
    if group_id:
        return f"group:{group_id.lower()}"

    alias_names = {_normalize_name(alias_name) for alias_name in aliases.values() if alias_name}
    alias_names.discard('')
    if alias_names:
        return f"alias:{sorted(alias_names)[0]}"

    normalized_name = _normalize_name(item.get('name', ''))
    if normalized_name:
        return f"name:{normalized_name}"

    return f"id:{item.get('id', '')}"


def _attach_picture_owner_metadata(item: Dict, owner_user_id: str, owner_username: str, current_user_id: str) -> None:
    """Attach ownership metadata to all pictures of an item for UI permissions."""
    pictures = item.get('pictures', [])
    if not isinstance(pictures, list):
        item['pictures'] = []
        return

    for picture in pictures:
        if not isinstance(picture, dict):
            continue
        picture['owner_user_id'] = owner_user_id
        picture['owner_username'] = owner_username
        picture['is_owned_by_current_user'] = owner_user_id == current_user_id


_PRIVATE_PICTURE_FIELDS = ('latitude', 'longitude', 'elevation')


def _strip_private_picture_fields(picture: Dict) -> Dict:
    """Remove a picture's precise coordinates in place, keeping location_name.

    Coordinates are private to the picture's owner (v1.2) - the shared/merged
    astrodex view must never expose another user's exact capture location
    (which, for a "home" preset, is effectively their address). The location
    *name* stays visible either way; that's the whole point of the frozen
    name snapshot on Astrodex items/pictures.
    """
    for field in _PRIVATE_PICTURE_FIELDS:
        picture.pop(field, None)
    return picture


def _build_stats_from_items(items: List[Dict]) -> Dict:
    """Build astrodex stats from an arbitrary visible items list."""
    total_items = len(items)
    items_with_pictures = sum(1 for item in items if item.get('pictures'))
    total_pictures = sum(len(item.get('pictures', [])) for item in items)

    types_count: Dict[str, int] = {}
    for item in items:
        item_type = item.get('type', 'Unknown')
        types_count[item_type] = types_count.get(item_type, 0) + 1

    return {
        'total_items': total_items,
        'items_with_pictures': items_with_pictures,
        'items_without_pictures': total_items - items_with_pictures,
        'total_pictures': total_pictures,
        'types': types_count,
    }


def load_all_users_astrodex(usernames_by_id: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Load astrodex collections for all users that have an astrodex file."""
    ensure_astrodex_directories()
    usernames_by_id = usernames_by_id or {}

    collections: List[Dict] = []
    suffix = '_astrodex.json'

    for filename in os.listdir(ASTRODEX_DIR):
        if not filename.endswith(suffix):
            continue

        user_id = filename[: -len(suffix)]
        username = usernames_by_id.get(user_id)
        data = load_user_astrodex(user_id, username)
        collections.append(
            {
                'user_id': user_id,
                'username': data.get('username') or username or 'unknown',
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
                'items': data.get('items', []),
            }
        )

    return collections


def get_visible_astrodex(
    current_user_id: str,
    current_username: Optional[str] = None,
    private_mode: bool = False,
    usernames_by_id: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Return astrodex payload visible to current user.

    private_mode=True -> only current user's astrodex.
    private_mode=False -> merged view across users, grouped by aliases/name.
    """
    current_user = load_user_astrodex(current_user_id, current_username)
    own_items = current_user.get('items', []) if isinstance(current_user.get('items', []), list) else []

    if private_mode:
        visible_items: List[Dict] = []
        for raw_item in own_items:
            item = copy.deepcopy(raw_item)
            enrich_item_with_catalogue_aliases(item)
            item['owner_user_id'] = current_user_id
            item['owner_username'] = current_user.get('username', current_username or 'unknown')
            item['is_owned_by_current_user'] = True
            _attach_picture_owner_metadata(item, current_user_id, item['owner_username'], current_user_id)
            item['own_pictures'] = copy.deepcopy(item.get('pictures', []))
            item['own_pictures_count'] = len(item['own_pictures'])
            item['total_pictures'] = len(item.get('pictures', []))
            visible_items.append(item)

        return {
            'items': visible_items,
            'stats': _build_stats_from_items(visible_items),
            'created_at': current_user.get('created_at'),
            'updated_at': current_user.get('updated_at'),
            'private_mode': True,
        }

    usernames_by_id = usernames_by_id or {}
    all_collections = load_all_users_astrodex(usernames_by_id)

    grouped: Dict[str, List[Dict]] = {}

    for collection in all_collections:
        owner_user_id = collection.get('user_id', '')
        owner_username = collection.get('username', 'unknown')
        for raw_item in collection.get('items', []):
            item = copy.deepcopy(raw_item)
            enrich_item_with_catalogue_aliases(item)
            item['owner_user_id'] = owner_user_id
            item['owner_username'] = owner_username
            item['is_owned_by_current_user'] = owner_user_id == current_user_id
            _attach_picture_owner_metadata(item, owner_user_id, owner_username, current_user_id)

            merge_key = _get_item_merge_key(item)
            grouped.setdefault(merge_key, []).append(item)

    merged_items: List[Dict] = []
    for source_items in grouped.values():
        own_item = next((item for item in source_items if item.get('owner_user_id') == current_user_id), None)
        base_item = own_item or source_items[0]

        merged_item = copy.deepcopy(base_item)
        merged_item['is_owned_by_current_user'] = own_item is not None

        merged_pictures: List[Dict] = []
        seen_picture_keys = set()
        for source_item in source_items:
            for picture in source_item.get('pictures', []):
                picture_key = (
                    str(picture.get('owner_user_id', source_item.get('owner_user_id', ''))),
                    str(picture.get('id', '')),
                    str(picture.get('filename', '')),
                )
                if picture_key in seen_picture_keys:
                    continue  # pragma: no cover
                seen_picture_keys.add(picture_key)
                picture_copy = copy.deepcopy(picture)
                if not picture_copy.get('is_owned_by_current_user'):
                    _strip_private_picture_fields(picture_copy)
                merged_pictures.append(picture_copy)

        own_pictures = copy.deepcopy(own_item.get('pictures', [])) if own_item else []

        merged_item['pictures'] = merged_pictures
        merged_item['own_pictures'] = own_pictures
        merged_item['own_pictures_count'] = len(own_pictures)
        merged_item['total_pictures'] = len(merged_pictures)
        merged_item['shared_owner_usernames'] = sorted(
            {str(item.get('owner_username') or 'unknown') for item in source_items}
        )

        merged_items.append(merged_item)

    merged_items.sort(key=lambda item: _normalize_name(item.get('name', '')) or item.get('name', '').lower())

    return {
        'items': merged_items,
        'stats': _build_stats_from_items(merged_items),
        'created_at': current_user.get('created_at'),
        'updated_at': current_user.get('updated_at'),
        'private_mode': False,
    }


def get_astrodex_map_points(
    current_user_id: str,
    current_username: Optional[str] = None,
    map_private: bool = False,
    usernames_by_id: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Return a flat list of geotagged Astrodex pictures for the Photo Map view.

    map_private=True -> only current user's own geotagged pictures.
    map_private=False -> geotagged pictures from every user, WITH real coordinates.

    This deliberately never calls _strip_private_picture_fields(): coordinate
    exposure on the map is governed entirely by the dedicated `map_private`
    config flag (independent from the general astrodex `private` flag used by
    get_visible_astrodex()), per product decision - this app targets small
    trusted deployments (family/astro-club), not public multi-tenant use.
    Do not "fix" this by reintroducing the strip call.
    """
    if map_private:
        collections = [
            {
                'user_id': current_user_id,
                'username': current_username or 'unknown',
                'items': load_user_astrodex(current_user_id, current_username).get('items', []),
            }
        ]
    else:
        collections = load_all_users_astrodex(usernames_by_id or {})

    points: List[Dict] = []
    total_without_location = 0

    for collection in collections:
        owner_user_id = collection.get('user_id', '')
        owner_username = collection.get('username', 'unknown')
        for item in collection.get('items', []):
            item_name = item.get('name', '')
            item_id = item.get('id', '')
            for picture in item.get('pictures', []):
                latitude = picture.get('latitude')
                longitude = picture.get('longitude')
                if latitude is None or longitude is None:
                    total_without_location += 1
                    continue
                points.append(
                    {
                        'id': picture.get('id', ''),
                        'item_id': item_id,
                        'item_name': item_name,
                        'filename': picture.get('filename', ''),
                        'date': picture.get('date'),
                        'latitude': latitude,
                        'longitude': longitude,
                        'location_name': picture.get('location_name'),
                        'owner_user_id': owner_user_id,
                        'owner_username': owner_username,
                        'is_owned_by_current_user': owner_user_id == current_user_id,
                    }
                )

    return {
        'points': points,
        'total_geotagged': len(points),
        'total_without_location': total_without_location,
        'map_private': map_private,
    }


def can_user_view_image(
    user_id: str, filename: str, private_mode: bool, usernames_by_id: Optional[Dict[str, str]] = None
) -> bool:
    """Check if user can access an astrodex image according to privacy mode."""
    if not filename:
        return False

    if private_mode:
        data = load_user_astrodex(user_id, (usernames_by_id or {}).get(user_id))
        for item in data.get('items', []):
            for picture in item.get('pictures', []):
                if picture.get('filename') == filename:
                    return True
        return False

    collections = load_all_users_astrodex(usernames_by_id)
    for collection in collections:
        for item in collection.get('items', []):
            for picture in item.get('pictures', []):
                if picture.get('filename') == filename:
                    return True

    return False


def ensure_astrodex_directories():
    """Ensure astrodex directories exist"""
    os.makedirs(ASTRODEX_DIR, exist_ok=True)
    os.makedirs(ASTRODEX_IMAGES_DIR, exist_ok=True)


def get_user_astrodex_file(user_id: str) -> str:
    """Get the path to a user's astrodex data file using user UUID"""
    ensure_astrodex_directories()
    return os.path.join(ASTRODEX_DIR, f'{user_id}_astrodex.json')


def load_user_astrodex(user_id: str, username: Optional[str] = None) -> Dict:
    """Load a user's astrodex data using user UUID

    Args:
        user_id: User's UUID
        username: Optional username for metadata
    """
    file_path = get_user_astrodex_file(user_id)

    if not os.path.exists(file_path):
        return {
            'user_id': user_id,
            'username': username or 'unknown',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'items': [],
        }

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        if username and data.get('username') != username:
            data['username'] = username
            data['user_id'] = user_id
            save_user_astrodex(user_id, data, username=username)
        return data
    except json.JSONDecodeError as e:
        # JSON is corrupted - try to recover or reset
        logger.error(f"Error loading astrodex for {username}: {e}")
        logger.error("Corrupted file will be backed up and reset")

        # Create backup of corrupted file
        backup_path = file_path + '.corrupted.' + datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            import shutil

            shutil.copy2(file_path, backup_path)
            logger.info(f"Backed up corrupted file to {backup_path}")
        except Exception as backup_error:
            logger.error(f"Failed to backup corrupted file: {backup_error}")

        # Return fresh astrodex (file will be overwritten on next save)
        return {
            'user_id': user_id,
            'username': username or 'unknown',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'items': [],
        }
    except Exception as e:
        logger.error(f"Error loading astrodex for user {user_id}: {e}")
        return {
            'user_id': user_id,
            'username': username or 'unknown',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'items': [],
        }


def validate_astrodex_json(file_path: str) -> tuple[bool, str]:
    """
    Validate that a file contains valid astrodex JSON

    Args:
        file_path: Path to JSON file to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        # Check required top-level fields
        if not isinstance(data, dict):
            return False, "JSON root is not a dictionary"

        if 'username' not in data:
            return False, "Missing 'username' field"

        if 'items' not in data or not isinstance(data['items'], list):
            return False, "Missing or invalid 'items' field"

        # Validate each item has required fields
        for idx, item in enumerate(data['items']):
            if 'id' not in item:
                return False, f"Item {idx} missing 'id' field"
            if 'name' not in item:
                return False, f"Item {idx} missing 'name' field"

        return True, ""

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"


def save_user_astrodex(user_id: str, astrodex_data: Dict, username: Optional[str] = None) -> bool:
    """
    Save a user's astrodex data with backup and recovery mechanism

    Process:
    1. Create backup of existing file (if exists)
    2. Write new data to temporary file
    3. Validate the temporary file
    4. Atomically replace original with temp file
    5. Delete backup on success, restore on failure

    Args:
        user_id: User's UUID
        astrodex_data: Astrodex data to save

    Returns:
        True on success, False on failure
    """
    file_path = get_user_astrodex_file(user_id)
    temp_path = file_path + '.tmp'
    backup_path = file_path + '.backup'

    with _get_user_save_lock(user_id):
        return _save_user_astrodex_locked(user_id, username, astrodex_data, file_path, temp_path, backup_path)


def _save_user_astrodex_locked(
    user_id: str,
    username: Optional[str],
    astrodex_data: Dict,
    file_path: str,
    temp_path: str,
    backup_path: str,
) -> bool:
    # Track if we created a backup (for cleanup)
    backup_created = False

    try:
        astrodex_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        astrodex_data['user_id'] = user_id
        if username:
            astrodex_data['username'] = username

        _sanitize_astrodex_for_persistence(astrodex_data)

        # Step 1: Create backup of existing file
        if os.path.exists(file_path):
            try:
                import shutil

                shutil.copy2(file_path, backup_path)
                backup_created = True
                logger.debug(f"Created backup: {backup_path}")
            except Exception as backup_error:
                logger.error(f"Failed to create backup for user {user_id}: {backup_error}")
                # Continue anyway - atomic write still provides some safety

        # Step 2: Write to temporary file
        with open(temp_path, 'w') as f:
            json.dump(astrodex_data, f, indent=2)
        logger.debug(f"Wrote temporary file: {temp_path}")

        # Step 3: Validate the temporary file
        is_valid, error_msg = validate_astrodex_json(temp_path)
        if not is_valid:
            raise ValueError(f"JSON validation failed: {error_msg}")
        logger.debug("Validated temporary file successfully")

        # Step 4: Atomic rename (on POSIX systems, this is atomic)
        os.replace(temp_path, file_path)
        logger.info(f"Successfully saved astrodex for user {user_id}")

        # Step 5: Clean up backup on success
        if backup_created and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
                logger.debug(f"Removed backup: {backup_path}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to remove backup: {cleanup_error}")
                # Not critical - backup will be overwritten next time

        return True

    except Exception as e:
        logger.error(f"Error saving astrodex for user {user_id}: {e}")

        # Restore from backup if it exists
        if backup_created and os.path.exists(backup_path):
            try:
                import shutil

                shutil.copy2(backup_path, file_path)
                logger.info(f"Restored astrodex from backup for user {user_id}")
            except Exception as restore_error:
                logger.error(f"Failed to restore from backup: {restore_error}")

        # Clean up temporary file if it exists
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as cleanup_error:  # pragma: no cover
                logger.warning(f"Failed to remove temp file: {cleanup_error}")

        # Clean up backup file
        if backup_created and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception as cleanup_error:  # pragma: no cover
                logger.warning(f"Failed to remove backup file: {cleanup_error}")

        return False


def create_astrodex_item(user_id: str, item_data: Dict, username: Optional[str] = None) -> Optional[Dict]:
    """
    Create a new item in user's astrodex

    Args:
        user_id: User's UUID
        item_data: Dictionary containing item information:
            - name: Object name (required)
            - type: Object type (galaxy, nebula, etc.)
            - catalogue: Source catalogue
            - constellation: Constellation
            - notes: User notes

    Returns:
        Created item with ID, or None on error
    """
    astrodex = load_user_astrodex(user_id, username)

    # Check if item already exists (by name)
    item_name = item_data.get('name', '').strip()
    if not item_name:
        logger.error("Item name is required")
        return None

    source_catalogue = item_data.get('catalogue', '')

    # Check for duplicate (same exact name OR same cross-catalogue object)
    if is_item_in_astrodex(user_id, item_name, source_catalogue):
        logger.warning(f"Item {item_name} already exists in astrodex")
        return None

    # Create new item.
    # No location on the item itself (v1.2 originally stamped one here, but
    # that implies a single object was only ever observed from one place -
    # false in practice, since the same object gets re-photographed across
    # sessions/sites over an item's lifetime). Location lives on each picture
    # instead; the UI derives an "observed at" summary from the item's
    # pictures rather than storing a redundant, potentially-stale item field.
    new_item = {
        'id': str(uuid.uuid4()),
        'name': item_name,
        'type': item_data.get('type', 'Unknown'),
        'catalogue': item_data.get('catalogue', ''),
        'constellation': item_data.get('constellation', ''),
        'notes': item_data.get('notes', ''),
        'pictures': [],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    astrodex['items'].append(new_item)

    if save_user_astrodex(user_id, astrodex, username=username):
        return new_item
    return None


def get_astrodex_item(user_id: str, item_id: str) -> Optional[Dict]:
    """Get a specific item from user's astrodex"""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            return item

    return None


def count_pictures_for_location(location_id: str) -> int:
    """Count Astrodex pictures (all users) referencing a location preset.

    Location lives on pictures, not items (v1.2) - an item itself is never
    tied to one place. Read-only pre-delete check: deleting a preset never
    cascades to Astrodex - pictures keep their frozen location_name snapshot.
    """
    if not location_id or not os.path.isdir(ASTRODEX_DIR):
        return 0
    count = 0
    for fname in os.listdir(ASTRODEX_DIR):
        if not fname.endswith('_astrodex.json'):
            continue
        try:
            with open(os.path.join(ASTRODEX_DIR, fname), 'r', encoding='utf-8') as file_obj:
                data = json.load(file_obj)
            for item in data.get('items', []):
                if not isinstance(item, dict):
                    continue
                for picture in item.get('pictures', []):
                    if isinstance(picture, dict) and picture.get('location_id') == location_id:
                        count += 1
        except Exception:
            continue  # unreadable file — skip, this is a best-effort count
    return count


def count_pictures_for_combination(combination_id: str) -> int:
    """Count Astrodex pictures (all users) referencing an equipment combination.

    Delete-guard pre-check for equipment_profiles.delete_combination(). Mirrors
    count_pictures_for_location(): scans every user's file directly (not
    get_visible_astrodex()'s privacy-aware merge) since a delete-guard must catch
    every reference regardless of what the deleting user can currently see.
    """
    if not combination_id or not os.path.isdir(ASTRODEX_DIR):
        return 0
    count = 0
    for fname in os.listdir(ASTRODEX_DIR):
        if not fname.endswith('_astrodex.json'):
            continue
        try:
            with open(os.path.join(ASTRODEX_DIR, fname), 'r', encoding='utf-8') as file_obj:
                data = json.load(file_obj)
            for item in data.get('items', []):
                if not isinstance(item, dict):
                    continue
                for picture in item.get('pictures', []):
                    if isinstance(picture, dict) and picture.get('combination_id') == combination_id:
                        count += 1
        except Exception:
            continue  # unreadable file — skip, this is a best-effort count
    return count


def build_combination_photo_index(
    current_user_id: str,
    current_username: Optional[str] = None,
    private_mode: bool = False,
    usernames_by_id: Optional[Dict[str, str]] = None,
) -> Dict[str, List[Dict]]:
    """Index every visible Astrodex picture by its combination_id (pictures with none are
    skipped). Reuses get_visible_astrodex()'s privacy rules (own-only vs merged-across-users),
    so combination photo stats never expose more than the rest of Astrodex already does.

    Call once per request and look up per combination via summarize_combination_pictures() -
    computing this fresh for every combination in a list would re-scan all Astrodex data
    once per combination.
    """
    visible = get_visible_astrodex(current_user_id, current_username, private_mode, usernames_by_id)
    index: Dict[str, List[Dict]] = {}
    for item in visible.get('items', []):
        for picture in item.get('pictures', []):
            combination_id = picture.get('combination_id')
            if not combination_id:
                continue
            annotated = dict(picture)
            annotated['item_id'] = item.get('id')
            annotated['item_name'] = item.get('name')
            index.setdefault(combination_id, []).append(annotated)
    return index


def get_pictures_for_combination(
    combination_id: str,
    current_user_id: str,
    current_username: Optional[str] = None,
    private_mode: bool = False,
    usernames_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Like build_combination_photo_index() but for a single combination_id - use this for the
    single-combination endpoint instead of indexing every other combination's pictures too."""
    visible = get_visible_astrodex(current_user_id, current_username, private_mode, usernames_by_id)
    pictures: List[Dict] = []
    for item in visible.get('items', []):
        for picture in item.get('pictures', []):
            if picture.get('combination_id') != combination_id:
                continue
            annotated = dict(picture)
            annotated['item_id'] = item.get('id')
            annotated['item_name'] = item.get('name')
            pictures.append(annotated)
    return pictures


def summarize_combination_pictures(pictures: List[Dict]) -> Dict:
    """Compute {photo_count, average_rating, picture_refs} for one combination's pictures.

    average_rating is the mean of only the *rated* pictures (unrated ones count toward
    photo_count but are excluded from the average, not treated as a zero).

    A rating that isn't a number counts as unrated as well. Ratings are validated on write,
    so a non-numeric one means hand-edited or legacy data on disk - and a single such entry
    must not raise and take down every endpoint that reports combination stats. It is logged
    rather than dropped silently, since nothing else would reveal the bad record.
    """
    ratings = []
    for picture in pictures:
        value = picture.get('rating')
        if value is None:
            continue
        try:
            ratings.append(float(value))
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring non-numeric rating %r on picture %s - counting it as unrated",
                value,
                picture.get('id'),
            )
    return {
        'photo_count': len(pictures),
        'average_rating': round(sum(ratings) / len(ratings), 2) if ratings else None,
        'picture_refs': pictures,
    }


def update_astrodex_item(user_id: str, item_id: str, updates: Dict) -> Optional[Dict]:
    """Update an existing item in user's astrodex"""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            # Update allowed fields
            allowed_fields = ['type', 'constellation', 'notes']
            for field in allowed_fields:
                if field in updates:
                    item[field] = updates[field]

            item['updated_at'] = datetime.now(timezone.utc).isoformat()

            if save_user_astrodex(user_id, astrodex):
                return item
            return None

    return None


def delete_astrodex_item(user_id: str, item_id: str) -> bool:
    """Delete an astrodex item"""
    astrodex = load_user_astrodex(user_id)

    # Find the item to delete and get all picture filenames
    item_to_delete = None
    for item in astrodex['items']:
        if item['id'] == item_id:
            item_to_delete = item
            break

    # Delete all associated image files
    if item_to_delete and 'pictures' in item_to_delete:
        for picture in item_to_delete['pictures']:
            filename = picture.get('filename')
            if filename:
                try:
                    file_path = os.path.join(ASTRODEX_IMAGES_DIR, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Deleted image file: {file_path}")
                except (OSError, IOError) as e:
                    logger.error(f"Error deleting image file {filename}: {e}")
                    # Continue anyway - the metadata will still be removed

    # Remove the item from the list
    original_count = len(astrodex['items'])
    astrodex['items'] = [item for item in astrodex['items'] if item['id'] != item_id]

    if len(astrodex['items']) < original_count:
        return save_user_astrodex(user_id, astrodex)

    return False


def add_picture_to_item(user_id: str, item_id: str, picture_data: Dict) -> Optional[Dict]:
    """
    Add a picture to an astrodex item

    Args:
        user_id: User's UUID
        item_id: Item ID
        picture_data: Dictionary containing:
            - filename: Image filename
            - date: Observation date
            - exposition_time: Exposition time
            - device: Device/telescope used
            - filters: Filters used
            - notes: Picture notes
            - location_id / location_name / latitude / longitude / elevation:
              where this picture was taken (v1.2, resolved server-side from
              the uploader's chosen location - see new_item's location fields
              for the same best-effort-id/frozen-name split). Coordinates are
              private to the picture's owner - get_visible_astrodex() strips
              them from every picture it shows to a different user.
            - combination_id: linked equipment combination (validated server-side
              in blueprints/astrodex.py before this is called), or None for the
              free-text "Other equipment" path.
            - combination_used_components: frozen snapshot of which parts of the
              combination were actually used for this photo (e.g.
              {"telescope": true, "camera": true, "filter_ids": [...]})  - purely
              informational, never recomputed even if the combination is edited
              later.
            - rating: 0.0-5.0 in 0.5 steps, or None if not yet rated (validated
              server-side).

    Returns:
        Created picture with ID, or None on error
    """
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            # Create new picture entry
            # A single item can be re-imaged across multiple sessions/sites over
            # its lifetime, so each picture gets its own location snapshot rather
            # than inheriting the item's (first-logged) location.
            new_picture = {
                'id': str(uuid.uuid4()),
                'filename': picture_data.get('filename', ''),
                'date': picture_data.get('date', ''),
                'exposition_time': picture_data.get('exposition_time', ''),
                'device': picture_data.get('device', ''),
                'filters': picture_data.get('filters', ''),
                'iso': picture_data.get('iso', ''),
                'frames': picture_data.get('frames', ''),
                'notes': picture_data.get('notes', ''),
                'location_id': picture_data.get('location_id') or None,
                'location_name': picture_data.get('location_name') or None,
                'latitude': picture_data.get('latitude'),
                'longitude': picture_data.get('longitude'),
                'elevation': picture_data.get('elevation'),
                'combination_id': picture_data.get('combination_id') or None,
                'combination_used_components': picture_data.get('combination_used_components') or None,
                'rating': picture_data.get('rating'),
                'is_main': False,  # New pictures are not main by default
                'created_at': datetime.now(timezone.utc).isoformat(),
            }

            # If this is the first picture, make it main
            if not item['pictures']:
                new_picture['is_main'] = True

            item['pictures'].append(new_picture)
            item['updated_at'] = datetime.now(timezone.utc).isoformat()

            if save_user_astrodex(user_id, astrodex):
                return new_picture
            return None

    return None


def update_picture(user_id: str, item_id: str, picture_id: str, updates: Dict) -> Optional[Dict]:
    """Update a picture in an astrodex item"""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            for picture in item['pictures']:
                if picture['id'] == picture_id:
                    # Update allowed fields. Unlike Astrodex items (location
                    # frozen at creation), a picture's location is correctable
                    # after the fact - pictures are often uploaded well after
                    # the session (stacking/processing takes time), so the
                    # auto-captured active-location-at-upload-time can be wrong,
                    # and old pictures predating this field have none at all.
                    allowed_fields = [
                        'date',
                        'exposition_time',
                        'device',
                        'filters',
                        'iso',
                        'frames',
                        'notes',
                        'location_id',
                        'location_name',
                        'latitude',
                        'longitude',
                        'elevation',
                        'combination_id',
                        'combination_used_components',
                        'rating',
                    ]
                    for field in allowed_fields:
                        if field in updates:
                            picture[field] = updates[field]

                    item['updated_at'] = datetime.now(timezone.utc).isoformat()

                    if save_user_astrodex(user_id, astrodex):
                        return picture
                    return None

    return None


def delete_picture(user_id: str, item_id: str, picture_id: str) -> bool:
    """Delete a picture from an astrodex item"""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            original_count = len(item['pictures'])
            was_main = False
            deleted_filename = None

            # Check if deleted picture was main and get filename
            for pic in item['pictures']:
                if pic['id'] == picture_id:
                    if pic.get('is_main', False):
                        was_main = True
                    deleted_filename = pic.get('filename')
                    break

            # Remove the picture from the list
            item['pictures'] = [pic for pic in item['pictures'] if pic['id'] != picture_id]

            # If we deleted the main picture and there are other pictures, make the first one main
            if was_main and item['pictures']:
                item['pictures'][0]['is_main'] = True

            if len(item['pictures']) < original_count:
                item['updated_at'] = datetime.now(timezone.utc).isoformat()

                # Delete the physical file if it exists
                if deleted_filename:
                    try:
                        file_path = os.path.join(ASTRODEX_IMAGES_DIR, deleted_filename)
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            logger.info(f"Deleted image file: {file_path}")
                    except (OSError, IOError) as e:
                        logger.error(f"Error deleting image file {deleted_filename}: {e}")
                        # Continue anyway - the metadata is still removed

                return save_user_astrodex(user_id, astrodex)

    return False


def set_main_picture(user_id: str, item_id: str, picture_id: str) -> bool:
    """Set a picture as the main picture for an item"""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] == item_id:
            # First, unset all pictures as main
            for picture in item['pictures']:
                picture['is_main'] = False

            # Then set the specified picture as main
            for picture in item['pictures']:
                if picture['id'] == picture_id:
                    picture['is_main'] = True
                    item['updated_at'] = datetime.now(timezone.utc).isoformat()
                    return save_user_astrodex(user_id, astrodex)

    return False


def get_main_picture(item: Dict) -> Optional[Dict]:
    """Get the main picture for an item, or None if no pictures"""
    if not item.get('pictures'):
        return None

    # Find main picture
    for picture in item['pictures']:
        if picture.get('is_main', False):
            return picture

    # If no main picture is set, return first picture
    return item['pictures'][0] if item['pictures'] else None


def is_item_in_astrodex_with_catalogue(user_id: str, item_name: str, catalogue: str = '') -> bool:
    """Check if an item exists by exact name or cross-catalogue aliases group."""
    astrodex = load_user_astrodex(user_id)

    requested_candidates = _extract_name_candidates(item_name)
    requested_normalized_names = {
        _normalize_name(candidate) for candidate in requested_candidates if _normalize_name(candidate)
    }

    requested_group_ids = set()
    requested_alias_names = set()
    for candidate in requested_candidates or [item_name]:
        group_id, aliases = _get_alias_metadata(catalogue, candidate)
        if group_id:
            requested_group_ids.add(group_id)
        if aliases:
            requested_alias_names.update(_normalize_name(value) for value in aliases.values() if value)

    requested_alias_names.discard('')

    for item in astrodex['items']:
        existing_name_normalized = _normalize_name(item.get('name', ''))
        if existing_name_normalized and existing_name_normalized in requested_normalized_names:
            return True

        existing_group_id, existing_aliases = _get_item_alias_metadata(item)

        if existing_group_id and existing_group_id in requested_group_ids:
            return True

        if requested_alias_names:
            existing_alias_names = {_normalize_name(value) for value in existing_aliases.values() if value}
            if existing_alias_names and (requested_alias_names & existing_alias_names):
                return True
            if existing_name_normalized in requested_alias_names:
                return True

        if catalogue and existing_aliases:
            alias_name = _get_alias_for_catalogue(existing_aliases, catalogue)
            if alias_name and _normalize_name(alias_name) in requested_normalized_names:
                return True

    return False


def is_item_in_astrodex(user_id: str, item_name: str, catalogue: str = '') -> bool:
    """Compatibility wrapper to support optional catalogue context."""
    return is_item_in_astrodex_with_catalogue(user_id, item_name, catalogue)


def find_item_in_astrodex(user_id: str, item_name: str, catalogue: str = '') -> dict | None:
    """Return the matching astrodex item (or None) — same matching rules as is_item_in_astrodex."""
    astrodex = load_user_astrodex(user_id)

    requested_candidates = _extract_name_candidates(item_name)
    requested_normalized_names = {_normalize_name(c) for c in requested_candidates if _normalize_name(c)}

    requested_group_ids: set = set()
    requested_alias_names: set = set()
    for candidate in requested_candidates or [item_name]:
        group_id, aliases = _get_alias_metadata(catalogue, candidate)
        if group_id:
            requested_group_ids.add(group_id)
        if aliases:
            requested_alias_names.update(_normalize_name(v) for v in aliases.values() if v)
    requested_alias_names.discard('')

    for item in astrodex['items']:
        existing_name_normalized = _normalize_name(item.get('name', ''))
        if existing_name_normalized and existing_name_normalized in requested_normalized_names:
            return item

        existing_group_id, existing_aliases = _get_item_alias_metadata(item)

        if existing_group_id and existing_group_id in requested_group_ids:
            return item

        if requested_alias_names:
            existing_alias_names = {_normalize_name(v) for v in existing_aliases.values() if v}
            if existing_alias_names and (requested_alias_names & existing_alias_names):
                return item
            if existing_name_normalized in requested_alias_names:
                return item

        if catalogue and existing_aliases:
            alias_name = _get_alias_for_catalogue(existing_aliases, catalogue)
            if alias_name and _normalize_name(alias_name) in requested_normalized_names:
                return item

    return None


def is_item_in_preloaded_astrodex(astrodex_data: dict, item_name: str, catalogue: str = '') -> bool:
    """Same logic as is_item_in_astrodex_with_catalogue but uses pre-loaded data.

    Avoids repeated disk reads when checking many items against the same
    astrodex (e.g. annotating 1 000 DSO rows in a single API call).
    """
    items = astrodex_data.get('items', []) if isinstance(astrodex_data, dict) else []

    requested_candidates = _extract_name_candidates(item_name)
    requested_normalized_names = {
        _normalize_name(candidate) for candidate in requested_candidates if _normalize_name(candidate)
    }

    requested_group_ids: set = set()
    requested_alias_names: set = set()
    for candidate in requested_candidates or [item_name]:
        group_id, aliases = _get_alias_metadata(catalogue, candidate)
        if group_id:
            requested_group_ids.add(group_id)
        if aliases:
            requested_alias_names.update(_normalize_name(value) for value in aliases.values() if value)

    requested_alias_names.discard('')

    for item in items:
        existing_name_normalized = _normalize_name(item.get('name', ''))
        if existing_name_normalized and existing_name_normalized in requested_normalized_names:
            return True

        existing_group_id, existing_aliases = _get_item_alias_metadata(item)

        if existing_group_id and existing_group_id in requested_group_ids:
            return True

        if requested_alias_names:
            existing_alias_names = {_normalize_name(value) for value in existing_aliases.values() if value}
            if existing_alias_names and (requested_alias_names & existing_alias_names):
                return True
            if existing_name_normalized in requested_alias_names:
                return True

        if catalogue and existing_aliases:
            alias_name = _get_alias_for_catalogue(existing_aliases, catalogue)
            if alias_name and _normalize_name(alias_name) in requested_normalized_names:
                return True

    return False


def enrich_item_with_catalogue_aliases(item: Dict) -> Dict:
    """Attach aliases metadata at runtime (not persisted)."""
    return catalogue_aliases.merge_item_with_alias_entry(item)


def switch_item_catalogue_name(user_id: str, item_id: str, target_catalogue: str) -> Optional[Dict]:
    """Switch displayed object name to one of its catalogue aliases."""
    astrodex = load_user_astrodex(user_id)

    for item in astrodex['items']:
        if item['id'] != item_id:
            continue

        enrich_item_with_catalogue_aliases(item)
        aliases = item.get('catalogue_aliases', {})
        if not isinstance(aliases, dict) or not aliases:
            raise ValueError('No catalogue aliases available for this item')

        if target_catalogue not in aliases:
            raise ValueError('Requested catalogue name is not available for this item')

        target_name = aliases[target_catalogue]
        target_group_id, target_aliases = _get_alias_metadata(target_catalogue, target_name)
        if not target_aliases:
            target_aliases = aliases

        # Prevent duplicates on rename/switch
        for existing_item in astrodex['items']:
            if existing_item['id'] == item_id:
                continue

            existing_group_id, _ = _get_item_alias_metadata(existing_item)

            if target_group_id and existing_group_id and target_group_id == existing_group_id:
                raise ValueError('An equivalent object already exists in your Astrodex')

            if _normalize_name(existing_item.get('name', '')) == _normalize_name(target_name):
                raise ValueError('An item with this name already exists in your Astrodex')

        item['name'] = target_name
        item['catalogue'] = target_catalogue
        if target_aliases:
            item['catalogue_aliases'] = target_aliases
        else:  # pragma: no cover
            item.pop('catalogue_aliases', None)
        item.pop('catalogue_group_id', None)
        item['updated_at'] = datetime.now(timezone.utc).isoformat()

        if save_user_astrodex(user_id, astrodex):
            return item
        return None

    return None


def get_astrodex_stats(user_id: str) -> Dict:
    """Get statistics about user's astrodex"""
    astrodex = load_user_astrodex(user_id)
    return _build_stats_from_items(astrodex['items'])


def get_constellations_list() -> List[str]:
    """Get a human-readable list of constellation names from the Constellation enum"""

    def humanize(name: str) -> str:
        # Add a space before each capital letter (except the first one) to humanize the name
        return re.sub(r'(?<!^)(?=[A-Z])', ' ', name)

    return [humanize(constellation.name) for constellation in Constellation]
