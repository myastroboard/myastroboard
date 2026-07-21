"""
Equipment Profiles Module - Astrophotography Equipment Management
Manages user equipment profiles: telescopes, cameras, mounts, filters, and combinations
"""

import json
import os
import uuid
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from utils.logging_config import get_logger
from utils.constants import DATA_DIR

logger = get_logger(__name__)

# Equipment data directory
EQUIPMENT_DIR = os.path.join(DATA_DIR, 'equipments')


def _get_float_or_none(value, default=None):
    """Convert an optional numeric form field to a float, treating '' and None as unset.

    Checks explicitly for None/'' rather than falsiness so a legitimate 0 (e.g. a lens focal
    ratio) is stored as 0.0 instead of being silently discarded as "not provided".
    """
    if value is None or value == '':
        return default
    return float(value)


class TelescopeType(str, Enum):
    """Telescope types"""

    REFRACTOR = "Refractor"
    APO = "Apochromatic Refractor (APO)"
    REFLECTOR = "Reflector"
    SCT = "Schmidt-Cassegrain (SCT)"
    EDGEHD = "EdgeHD"
    RASA = "Rowe Ackerman Schmidt Astrograph (RASA)"
    RC = "Ritchey-Chrétien (RC)"
    NEWTONIAN = "Newtonian"
    MAKSUTOV = "Maksutov-Cassegrain"
    CASSEGRAIN = "Cassegrain"
    DOBSONIAN = "Dobsonian"


class SamplingClassification(str, Enum):
    """Image sampling classification"""

    UNDERSAMPLED = "Undersampled"
    OPTIMAL = "Optimal"
    OVERSAMPLED = "Oversampled"


# ============================================================
# Data Models
# ============================================================


@dataclass
class Telescope:
    """Telescope profile"""

    id: str
    name: str
    manufacturer: str
    telescope_type: str
    aperture_mm: float  # Aperture in mm
    focal_length_mm: float  # Native focal length in mm
    native_focal_ratio: float  # Auto-calculated: focal_length / aperture
    weight_kg: float = 0.0  # Weight in kg (for payload calculation)
    reducer_barlow_factor: float = 1.0  # Optional reducer/barlow factor
    effective_focal_length: float = 0.0  # Auto-calculated: focal_length * factor
    effective_focal_ratio: float = 0.0  # Auto-calculated: effective_focal_length / aperture
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_shared: bool = False
    is_disabled: bool = False

    def __post_init__(self):
        """Calculate derived values"""
        if self.aperture_mm > 0:
            self.native_focal_ratio = round(self.focal_length_mm / self.aperture_mm, 2)
            self.effective_focal_length = round(self.focal_length_mm * self.reducer_barlow_factor, 1)
            self.effective_focal_ratio = round(self.effective_focal_length / self.aperture_mm, 2)


@dataclass
class Camera:
    """Camera profile"""

    id: str
    name: str
    manufacturer: str
    sensor_width_mm: float  # Sensor width in mm
    sensor_height_mm: float  # Sensor height in mm
    resolution_width_px: int  # Resolution width in pixels
    resolution_height_px: int  # Resolution height in pixels
    pixel_size_um: float  # Pixel size in micrometers
    sensor_type: str  # CMOS/CCD, Mono/Color
    weight_kg: float = 0.0  # Weight in kg (for payload calculation)
    sensor_diagonal_mm: float = 0.0  # Auto-calculated
    cooling_supported: bool = False
    min_temperature_c: Optional[float] = None
    read_noise_e: Optional[float] = None  # Read noise in electrons
    quantum_efficiency: Optional[float] = None  # QE percentage
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_shared: bool = False
    is_disabled: bool = False

    def __post_init__(self):
        """Calculate derived values"""
        import math

        self.sensor_diagonal_mm = round(math.sqrt(self.sensor_width_mm**2 + self.sensor_height_mm**2), 2)


@dataclass
class Mount:
    """Mount profile"""

    id: str
    name: str
    manufacturer: str = ""
    mount_type: str = ""  # Equatorial / Alt-Az
    payload_capacity_kg: float = 0.0  # Maximum payload capacity in kg
    recommended_payload_kg: float = 0.0  # Auto-calculated: 50-70% of max
    tracking_accuracy_arcsec: Optional[float] = None  # Periodic error in arcsec
    guiding_supported: bool = False
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_shared: bool = False
    is_disabled: bool = False

    def __post_init__(self):
        """Calculate recommended payload"""
        if self.payload_capacity_kg > 0:
            # Recommended imaging payload: 75% of max capacity
            self.recommended_payload_kg = round(self.payload_capacity_kg * 0.75, 2)


@dataclass
class Filter:
    """Filter profile"""

    id: str
    name: str
    manufacturer: str = ""
    filter_type: str = ""  # LRGB / narrowband / broadband
    central_wavelength_nm: Optional[float] = None  # Central wavelength in nm
    bandwidth_nm: Optional[float] = None  # Bandwidth in nm
    transmission_curve: Optional[str] = None  # JSON/CSV transmission data
    intended_use: str = ""  # e.g., "emission nebulae", "broadband imaging"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_shared: bool = False
    is_disabled: bool = False


@dataclass
class Accessory:
    """Accessory profile (field flattener, focuser, etc.)"""

    id: str
    name: str
    manufacturer: str
    accessory_type: str  # e.g., "Field Flattener", "Focuser", "Filter Wheel", etc.
    weight_kg: float = 0.0  # Weight in kg (for payload calculation)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_shared: bool = False
    is_disabled: bool = False


@dataclass
class EquipmentCombination:
    """Equipment combination analysis"""

    id: str
    name: str
    telescope_id: Optional[str] = None
    camera_id: Optional[str] = None
    mount_id: Optional[str] = None
    filter_ids: Optional[List[str]] = None  # List of filter IDs
    accessory_ids: Optional[List[str]] = None  # List of accessory IDs
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_disabled: bool = False
    guide_camera_id: Optional[str] = None  # Separate guide camera, purely informational
    lens_focal_length_mm: Optional[float] = None  # Camera-only combos (no telescope): lens on the camera
    lens_focal_ratio: Optional[float] = None  # Camera-only combos: lens f-ratio

    def __post_init__(self):
        if self.filter_ids is None:
            self.filter_ids = []
        if self.accessory_ids is None:
            self.accessory_ids = []


@dataclass
class FOVCalculation:
    """Field of View calculation results"""

    horizontal_fov_deg: float
    vertical_fov_deg: float
    diagonal_fov_deg: float
    image_scale_arcsec_per_px: float
    sampling_classification: str
    telescope_name: str = ""
    camera_name: str = ""


@dataclass
class CombinationAnalysis:
    """Equipment combination analysis results"""

    combination_id: str
    telescope: Optional[Dict] = None
    camera: Optional[Dict] = None
    mount: Optional[Dict] = None
    filters: Optional[List[Dict]] = None
    accessories: Optional[List[Dict]] = None
    fov_calculation: Optional[FOVCalculation] = None
    suitability: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None

    def __post_init__(self):
        if self.filters is None:
            self.filters = []
        if self.accessories is None:
            self.accessories = []
        if self.suitability is None:
            self.suitability = []
        if self.recommendations is None:
            self.recommendations = []


# ============================================================
# Directory & File Management
# ============================================================


def ensure_equipment_directories():
    """Ensure equipment directories exist"""
    os.makedirs(EQUIPMENT_DIR, exist_ok=True)


def get_user_equipment_file(user_id: str, equipment_type: str) -> str:
    """Get the path to a user's equipment file"""
    ensure_equipment_directories()
    return os.path.join(EQUIPMENT_DIR, f'{user_id}_{equipment_type}.json')


def validate_equipment_json(file_path: str) -> Tuple[bool, str]:
    """
    Validate that a file contains valid equipment JSON

    Args:
        file_path: Path to JSON file to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        # Basic structure validation
        if not isinstance(data, dict):
            return False, "JSON root must be an object"

        if 'items' not in data or not isinstance(data['items'], list):
            return False, "Missing or invalid 'items' array"

        return True, ""

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"


def safe_save_equipment(file_path: str, data: Dict) -> bool:
    """
    Safely save equipment data with backup and validation

    Args:
        file_path: Path to equipment file
        data: Equipment data to save

    Returns:
        True if save successful, False otherwise
    """
    backup_path = file_path + '.backup'
    temp_path = file_path + '.tmp'

    try:
        # Step 1: Backup existing file if it exists
        if os.path.exists(file_path):
            shutil.copy2(file_path, backup_path)
            logger.debug(f"Created backup: {backup_path}")

        # Step 2: Write to temporary file
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.debug(f"Wrote temporary file: {temp_path}")

        # Step 3: Validate temporary file
        is_valid, error_msg = validate_equipment_json(temp_path)
        if not is_valid:
            logger.error(f"Validation failed for {temp_path}: {error_msg}")
            # Restore from backup
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, file_path)
                logger.info(f"Restored from backup: {backup_path}")
            os.remove(temp_path)
            return False

        # Step 4: Move temporary file to final location
        shutil.move(temp_path, file_path)
        logger.debug(f"Moved {temp_path} to {file_path}")

        # Step 5: Delete backup on success
        if os.path.exists(backup_path):
            os.remove(backup_path)
            logger.debug(f"Deleted backup: {backup_path}")

        return True

    except Exception as e:
        logger.error(f"Error during safe save: {e}")
        # Attempt to restore from backup
        if os.path.exists(backup_path) and os.path.exists(file_path):
            try:
                shutil.copy2(backup_path, file_path)
                logger.info(f"Restored from backup after error: {backup_path}")
            except Exception as restore_error:
                logger.error(f"Failed to restore from backup: {restore_error}")

        # Clean up temporary file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass  # best-effort temp-file cleanup; failure is non-fatal

        return False


# ============================================================
# Shared Equipment Helpers
# ============================================================


def load_all_shared_equipment(equipment_type: str, exclude_user_id: str) -> List[Dict]:
    """Return items marked is_shared=True from all users except exclude_user_id.

    Each returned item is annotated with owner_id and owner_username.
    """
    from utils.auth import user_manager

    user_map = {u['user_id']: u['username'] for u in user_manager.list_users()}
    ensure_equipment_directories()

    shared_items: List[Dict] = []
    try:
        for fname in os.listdir(EQUIPMENT_DIR):
            if not fname.endswith(f'_{equipment_type}.json'):
                continue
            owner_id = fname[: -(len(equipment_type) + 6)]  # strip _{type}.json
            if owner_id == exclude_user_id:
                continue
            fpath = os.path.join(EQUIPMENT_DIR, fname)
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
            except Exception:
                continue
            for item in data.get('items', []):
                if item.get('is_shared'):
                    annotated = dict(item)
                    annotated['owner_id'] = owner_id
                    annotated['owner_username'] = user_map.get(owner_id, owner_id)
                    shared_items.append(annotated)
    except Exception as e:
        logger.error(f"Error scanning shared equipment ({equipment_type}): {e}")

    return shared_items


_BASIC_EQUIPMENT_TYPES = ('telescopes', 'cameras', 'mounts', 'filters', 'accessories')

# Fields on a combination referencing a single equipment id, keyed by the equipment type
# scanned in EQUIPMENT_DIR (matches the `_{type}.json` file suffix / load_all_shared_equipment
# parameter convention). 'cameras' includes guide_camera_id since either field can reference one.
_COMBINATION_SCALAR_REFERENCE_FIELDS: Dict[str, Tuple[str, ...]] = {
    'telescopes': ('telescope_id',),
    'cameras': ('camera_id', 'guide_camera_id'),
    'mounts': ('mount_id',),
}
# Fields on a combination referencing a list of equipment ids.
_COMBINATION_LIST_REFERENCE_FIELDS: Dict[str, str] = {
    'filters': 'filter_ids',
    'accessories': 'accessory_ids',
}


def index_owned_and_shared_equipment(user_id: str) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """Build (own_by_id, shared_by_id) indexes across all 5 basic equipment types.

    Exposed (not module-private) so a caller that needs the same index for several combinations
    in one request (e.g. the combinations list endpoint) can build it once and pass it into
    compute_combination_share_status/compute_combination_validity_status via their
    `equipment_index` param, instead of each call re-scanning the equipment directory.
    """
    loaders = {
        'telescopes': load_user_telescopes,
        'cameras': load_user_cameras,
        'mounts': load_user_mounts,
        'filters': load_user_filters,
        'accessories': load_user_accessories,
    }
    own_by_id: Dict[str, Dict] = {}
    shared_by_id: Dict[str, Dict] = {}
    for eq_type in _BASIC_EQUIPMENT_TYPES:
        for item in loaders[eq_type](user_id).get('items', []):
            own_by_id[item['id']] = item
        for item in load_all_shared_equipment(eq_type, user_id):
            shared_by_id[item['id']] = item
    return own_by_id, shared_by_id


def index_telescopes_and_cameras(user_id: str) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """Return (telescopes_by_id, cameras_by_id) merging this user's own + all shared items.

    Used by SkyTonight's combination-aware scoring to resolve a combination's
    telescope_id/camera_id into full equipment dicts without re-scanning EQUIPMENT_DIR
    per combination.
    """
    telescopes_by_id: Dict[str, Dict] = {}
    for item in load_user_telescopes(user_id).get('items', []):
        telescopes_by_id[item['id']] = item
    for item in load_all_shared_equipment('telescopes', user_id):
        telescopes_by_id[item['id']] = item

    cameras_by_id: Dict[str, Dict] = {}
    for item in load_user_cameras(user_id).get('items', []):
        cameras_by_id[item['id']] = item
    for item in load_all_shared_equipment('cameras', user_id):
        cameras_by_id[item['id']] = item

    return telescopes_by_id, cameras_by_id


def _combination_reference_ids(combination: Dict) -> List[str]:
    """Flatten every equipment id a combination references into one list."""
    ref_ids: List[str] = []
    for field in ('telescope_id', 'camera_id', 'guide_camera_id', 'mount_id'):
        val = combination.get(field)
        if val:
            ref_ids.append(val)
    ref_ids.extend(combination.get('filter_ids') or [])
    ref_ids.extend(combination.get('accessory_ids') or [])
    return ref_ids


def _find_combinations_referencing(equipment_type: str, equipment_id: str) -> List[Dict]:
    """Return {name, owner_id} for every combination (any user) referencing this equipment id.

    Used as a delete-guard: equipment referenced by a combination cannot be removed while the
    reference exists. Scans every user's combinations file (not just the owner's) because a
    *shared* item can be referenced by another user's combination.

    A combinations file that fails to read/parse (mid-write, corruption, permission hiccup) is
    treated as "unknown, might still reference this equipment" rather than silently skipped - the
    guard fails closed (blocks the delete) instead of failing open, since ignoring an unreadable
    file could let a still-referenced item be deleted out from under that user's combination.
    """
    ensure_equipment_directories()
    scalar_fields = _COMBINATION_SCALAR_REFERENCE_FIELDS.get(equipment_type, ())
    list_field = _COMBINATION_LIST_REFERENCE_FIELDS.get(equipment_type)

    matches: List[Dict] = []
    try:
        for fname in os.listdir(EQUIPMENT_DIR):
            if not fname.endswith('_combinations.json'):
                continue
            owner_id = fname[: -(len('combinations') + 6)]
            fpath = os.path.join(EQUIPMENT_DIR, fname)
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(
                    f"Could not read {fpath} while checking references for "
                    f"{equipment_type}/{equipment_id}; blocking delete to be safe: {e}"
                )
                matches.append({'name': '(unreadable combination - please retry)', 'owner_id': owner_id})
                continue
            for combo in data.get('items', []):
                referenced = any(combo.get(field) == equipment_id for field in scalar_fields)
                if not referenced and list_field:
                    referenced = equipment_id in (combo.get(list_field) or [])
                if referenced:
                    matches.append({'name': combo.get('name', ''), 'owner_id': owner_id})
    except Exception as e:
        logger.error(f"Error scanning combinations referencing {equipment_type}/{equipment_id}: {e}")

    return matches


def compute_combination_validity_status(
    combination: Dict, user_id: str, equipment_index: Optional[Tuple[Dict[str, Dict], Dict[str, Dict]]] = None
) -> Dict:
    """Compute is_valid/invalid_reasons for a combination (feature.md's 'autocheck' requirement).

    Distinct from is_disabled (the combination's own explicit toggle): is_valid is computed
    automatically and turns False as soon as any referenced equipment item is disabled - or,
    defensively, no longer resolvable at all (covers combinations created before delete-guards
    existed, where a referenced item may already be gone).

    `equipment_index` lets a caller that's computing this for several combinations in one request
    (e.g. the combinations list endpoint) pass in a single `index_owned_and_shared_equipment`
    result instead of every combination re-scanning the equipment directory from scratch.
    """
    own_by_id, shared_by_id = equipment_index or index_owned_and_shared_equipment(user_id)

    invalid_reasons: List[str] = []
    disabled_component_ids: List[str] = []

    for eq_id in _combination_reference_ids(combination):
        item = own_by_id.get(eq_id) or shared_by_id.get(eq_id)
        if item is None:
            invalid_reasons.append(f'missing:{eq_id}')
            disabled_component_ids.append(eq_id)
        elif item.get('is_disabled', False):
            invalid_reasons.append(f'disabled:{eq_id}')
            disabled_component_ids.append(eq_id)

    return {
        'is_valid': not invalid_reasons,
        'invalid_reasons': invalid_reasons,
        'disabled_component_ids': disabled_component_ids,
    }


def compute_combination_share_status(
    combination: Dict, user_id: str, equipment_index: Optional[Tuple[Dict[str, Dict], Dict[str, Dict]]] = None
) -> Dict:
    """Compute is_shared, has_broken_share, and broken_items for a combination.

    A combination is 'shared' iff ALL constituent equipment items are accessible
    (own or from others) and have is_shared=True.
    'has_broken_share' is True when a referenced item can no longer be found in
    any user's shared pool (it was previously accessible but is now gone/unshared).

    `equipment_index` - see compute_combination_validity_status.
    """
    own_by_id, shared_by_id = equipment_index or index_owned_and_shared_equipment(user_id)
    ref_ids = _combination_reference_ids(combination)

    is_shared = True
    has_broken_share = False
    broken_items: List[str] = []

    for eq_id in ref_ids:
        if eq_id in own_by_id:
            if not own_by_id[eq_id].get('is_shared', False):
                is_shared = False
        elif eq_id in shared_by_id:
            pass  # still shared by owner, counts as shared
        else:
            # Not found anywhere - previously accessible but now gone/unshared
            is_shared = False
            has_broken_share = True
            broken_items.append(eq_id)

    # Build per-equipment-id metadata for the UI (shared status of each item)
    items_share_info: Dict[str, Dict] = {}
    for eq_id in ref_ids:
        if eq_id in own_by_id:
            item = own_by_id[eq_id]
            items_share_info[eq_id] = {
                'is_shared': bool(item.get('is_shared', False)),
                'owner_id': user_id,
                'owner_username': None,  # own item
            }
        elif eq_id in shared_by_id:
            item = shared_by_id[eq_id]
            items_share_info[eq_id] = {
                'is_shared': True,
                'owner_id': item.get('owner_id'),
                'owner_username': item.get('owner_username'),
            }
        else:
            items_share_info[eq_id] = {'is_shared': False, 'owner_id': None, 'owner_username': None}

    return {
        'is_shared': is_shared and bool(ref_ids),
        'has_broken_share': has_broken_share,
        'broken_items': broken_items,
        'items_share_info': items_share_info,
    }


def load_all_shared_combinations(exclude_user_id: str) -> List[Dict]:
    """Return combinations from other users whose constituent equipment is all shared.

    Computes share status from the owner's perspective for each combination.
    """
    from utils.auth import user_manager

    user_map = {u['user_id']: u['username'] for u in user_manager.list_users()}
    ensure_equipment_directories()

    result: List[Dict] = []
    try:
        for fname in os.listdir(EQUIPMENT_DIR):
            if not fname.endswith('_combinations.json'):
                continue
            owner_id = fname[: -(len('combinations') + 6)]  # strip _combinations.json
            if owner_id == exclude_user_id:
                continue
            fpath = os.path.join(EQUIPMENT_DIR, fname)
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
            except Exception:
                continue
            for combo in data.get('items', []):
                # Compute from the owner's perspective
                status = compute_combination_share_status(combo, owner_id)
                if status['is_shared']:
                    validity = compute_combination_validity_status(combo, owner_id)
                    annotated = {**combo, **status, **validity}
                    annotated['owner_id'] = owner_id
                    annotated['owner_username'] = user_map.get(owner_id, owner_id)
                    result.append(annotated)
    except Exception as e:
        logger.error(f"Error scanning shared combinations: {e}")

    return result


# ============================================================
# CRUD Operations - Telescopes
# ============================================================


def load_user_telescopes(user_id: str) -> Dict:
    """Load user's telescope profiles"""
    file_path = get_user_equipment_file(user_id, 'telescopes')

    if not os.path.exists(file_path):
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}

    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading telescopes for {user_id}: {e}")
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}


def save_user_telescopes(user_id: str, data: Dict) -> bool:
    """Save user's telescope profiles with safety checks"""
    file_path = get_user_equipment_file(user_id, 'telescopes')
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return safe_save_equipment(file_path, data)


def create_telescope(user_id: str, telescope_data: Dict) -> Optional[Dict]:
    """Create a new telescope profile"""
    try:
        # Create telescope object with auto-calculated fields
        telescope = Telescope(
            id=str(uuid.uuid4()),
            name=telescope_data['name'],
            manufacturer=telescope_data.get('manufacturer', ''),
            telescope_type=telescope_data['telescope_type'],
            aperture_mm=float(telescope_data['aperture_mm']),
            focal_length_mm=float(telescope_data['focal_length_mm']),
            weight_kg=_get_float_or_none(telescope_data.get('weight_kg'), 0.0),
            reducer_barlow_factor=_get_float_or_none(telescope_data.get('reducer_barlow_factor'), 1.0),
            native_focal_ratio=0.0,  # Will be calculated
            effective_focal_length=0.0,  # Will be calculated
            effective_focal_ratio=0.0,  # Will be calculated
            notes=telescope_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_shared=bool(telescope_data.get('is_shared', False)),
            is_disabled=bool(telescope_data.get('is_disabled', False)),
        )

        # Load existing data
        data = load_user_telescopes(user_id)

        # Add new telescope
        data['items'].append(asdict(telescope))

        # Save
        if save_user_telescopes(user_id, data):
            return asdict(telescope)
        return None

    except Exception as e:
        logger.error(f"Error creating telescope: {e}")
        return None


def get_telescope(user_id: str, telescope_id: str) -> Optional[Dict]:
    """Get a specific telescope profile"""
    data = load_user_telescopes(user_id)
    for item in data['items']:
        if item['id'] == telescope_id:
            return item
    return None


def update_telescope(user_id: str, telescope_id: str, telescope_data: Dict) -> Optional[Dict]:
    """Update a telescope profile"""
    try:
        data = load_user_telescopes(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == telescope_id:
                # Update with recalculation
                telescope = Telescope(
                    id=telescope_id,
                    name=telescope_data['name'],
                    manufacturer=telescope_data.get('manufacturer', item.get('manufacturer', '')),
                    telescope_type=telescope_data['telescope_type'],
                    aperture_mm=float(telescope_data['aperture_mm']),
                    focal_length_mm=float(telescope_data['focal_length_mm']),
                    weight_kg=_get_float_or_none(telescope_data.get('weight_kg'), item.get('weight_kg', 0.0)),
                    reducer_barlow_factor=_get_float_or_none(telescope_data.get('reducer_barlow_factor'), 1.0),
                    native_focal_ratio=0.0,
                    effective_focal_length=0.0,
                    effective_focal_ratio=0.0,
                    notes=telescope_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    is_shared=bool(telescope_data.get('is_shared', item.get('is_shared', False))),
                    is_disabled=bool(telescope_data.get('is_disabled', item.get('is_disabled', False))),
                )

                data['items'][i] = asdict(telescope)

                if save_user_telescopes(user_id, data):
                    return asdict(telescope)
                return None

        return None

    except Exception as e:
        logger.error(f"Error updating telescope: {e}")
        return None


def delete_telescope(user_id: str, telescope_id: str) -> Tuple[bool, Optional[List[str]]]:
    """Delete a telescope profile.

    Refuses deletion when any combination (owned by this user or another, since a shared
    telescope can be referenced by someone else's combination) still references this
    telescope. Returns (False, [combination names]) in that case so the caller can show a
    specific message, or (False, None) on a generic failure.
    """
    blocking = _find_combinations_referencing('telescopes', telescope_id)
    if blocking:
        return False, [combo['name'] for combo in blocking]
    try:
        data = load_user_telescopes(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != telescope_id]
        return save_user_telescopes(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting telescope: {e}")
        return False, None


# ============================================================
# CRUD Operations - Cameras
# ============================================================


def load_user_cameras(user_id: str) -> Dict:
    """Load user's camera profiles"""
    file_path = get_user_equipment_file(user_id, 'cameras')

    if not os.path.exists(file_path):
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}

    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading cameras for {user_id}: {e}")
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}


def save_user_cameras(user_id: str, data: Dict) -> bool:
    """Save user's camera profiles with safety checks"""
    file_path = get_user_equipment_file(user_id, 'cameras')
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return safe_save_equipment(file_path, data)


def create_camera(user_id: str, camera_data: Dict) -> Optional[Dict]:
    """Create a new camera profile"""
    try:
        camera = Camera(
            id=str(uuid.uuid4()),
            name=camera_data['name'],
            manufacturer=camera_data['manufacturer'],
            sensor_width_mm=float(camera_data['sensor_width_mm']),
            sensor_height_mm=float(camera_data['sensor_height_mm']),
            resolution_width_px=int(camera_data['resolution_width_px']),
            resolution_height_px=int(camera_data['resolution_height_px']),
            pixel_size_um=float(camera_data['pixel_size_um']),
            sensor_type=camera_data['sensor_type'],
            weight_kg=_get_float_or_none(camera_data.get('weight_kg'), 0.0),
            sensor_diagonal_mm=0.0,  # Will be calculated
            cooling_supported=camera_data.get('cooling_supported', False),
            min_temperature_c=_get_float_or_none(camera_data.get('min_temperature_c')),
            read_noise_e=_get_float_or_none(camera_data.get('read_noise_e')),
            quantum_efficiency=_get_float_or_none(camera_data.get('quantum_efficiency')),
            notes=camera_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_shared=bool(camera_data.get('is_shared', False)),
            is_disabled=bool(camera_data.get('is_disabled', False)),
        )

        data = load_user_cameras(user_id)
        data['items'].append(asdict(camera))

        if save_user_cameras(user_id, data):
            return asdict(camera)
        return None

    except Exception as e:
        logger.error(f"Error creating camera: {e}")
        return None


def get_camera(user_id: str, camera_id: str) -> Optional[Dict]:
    """Get a specific camera profile"""
    data = load_user_cameras(user_id)
    for item in data['items']:
        if item['id'] == camera_id:
            return item
    return None


def update_camera(user_id: str, camera_id: str, camera_data: Dict) -> Optional[Dict]:
    """Update a camera profile"""
    try:
        data = load_user_cameras(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == camera_id:
                camera = Camera(
                    id=camera_id,
                    name=camera_data['name'],
                    manufacturer=camera_data['manufacturer'],
                    sensor_width_mm=float(camera_data['sensor_width_mm']),
                    sensor_height_mm=float(camera_data['sensor_height_mm']),
                    resolution_width_px=int(camera_data['resolution_width_px']),
                    resolution_height_px=int(camera_data['resolution_height_px']),
                    pixel_size_um=float(camera_data['pixel_size_um']),
                    sensor_type=camera_data['sensor_type'],
                    weight_kg=_get_float_or_none(camera_data.get('weight_kg'), item.get('weight_kg', 0.0)),
                    sensor_diagonal_mm=0.0,
                    cooling_supported=camera_data.get('cooling_supported', False),
                    min_temperature_c=_get_float_or_none(camera_data.get('min_temperature_c')),
                    read_noise_e=_get_float_or_none(camera_data.get('read_noise_e')),
                    quantum_efficiency=_get_float_or_none(camera_data.get('quantum_efficiency')),
                    notes=camera_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    is_shared=bool(camera_data.get('is_shared', item.get('is_shared', False))),
                    is_disabled=bool(camera_data.get('is_disabled', item.get('is_disabled', False))),
                )

                data['items'][i] = asdict(camera)

                if save_user_cameras(user_id, data):
                    return asdict(camera)
                return None

        return None

    except Exception as e:
        logger.error(f"Error updating camera: {e}")
        return None


def delete_camera(user_id: str, camera_id: str) -> Tuple[bool, Optional[List[str]]]:
    """Delete a camera profile.

    Refuses deletion when any combination references this camera, either as its imaging
    camera or as its guide camera.
    """
    blocking = _find_combinations_referencing('cameras', camera_id)
    if blocking:
        return False, [combo['name'] for combo in blocking]
    try:
        data = load_user_cameras(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != camera_id]
        return save_user_cameras(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting camera: {e}")
        return False, None


# ============================================================
# CRUD Operations - Mounts
# ============================================================


def load_user_mounts(user_id: str) -> Dict:
    """Load user's mount profiles"""
    file_path = get_user_equipment_file(user_id, 'mounts')

    if not os.path.exists(file_path):
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}

    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading mounts for {user_id}: {e}")
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}


def save_user_mounts(user_id: str, data: Dict) -> bool:
    """Save user's mount profiles with safety checks"""
    file_path = get_user_equipment_file(user_id, 'mounts')
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return safe_save_equipment(file_path, data)


def create_mount(user_id: str, mount_data: Dict) -> Optional[Dict]:
    """Create a new mount profile"""
    try:
        mount = Mount(
            id=str(uuid.uuid4()),
            name=mount_data['name'],
            manufacturer=mount_data.get('manufacturer', ''),
            mount_type=mount_data['mount_type'],
            payload_capacity_kg=float(mount_data['payload_capacity_kg']),
            recommended_payload_kg=0.0,  # Will be calculated
            tracking_accuracy_arcsec=(
                float(mount_data['tracking_accuracy_arcsec']) if mount_data.get('tracking_accuracy_arcsec') else None
            ),
            guiding_supported=mount_data.get('guiding_supported', False),
            notes=mount_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_shared=bool(mount_data.get('is_shared', False)),
            is_disabled=bool(mount_data.get('is_disabled', False)),
        )

        data = load_user_mounts(user_id)
        data['items'].append(asdict(mount))

        if save_user_mounts(user_id, data):
            return asdict(mount)
        return None

    except Exception as e:
        logger.error(f"Error creating mount: {e}")
        return None


def get_mount(user_id: str, mount_id: str) -> Optional[Dict]:
    """Get a specific mount profile"""
    data = load_user_mounts(user_id)
    for item in data['items']:
        if item['id'] == mount_id:
            return item
    return None


def update_mount(user_id: str, mount_id: str, mount_data: Dict) -> Optional[Dict]:
    """Update a mount profile"""
    try:
        data = load_user_mounts(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == mount_id:
                mount = Mount(
                    id=mount_id,
                    name=mount_data['name'],
                    manufacturer=mount_data.get('manufacturer', ''),
                    mount_type=mount_data['mount_type'],
                    payload_capacity_kg=float(mount_data['payload_capacity_kg']),
                    recommended_payload_kg=0.0,
                    tracking_accuracy_arcsec=(
                        float(mount_data['tracking_accuracy_arcsec'])
                        if mount_data.get('tracking_accuracy_arcsec')
                        else None
                    ),
                    guiding_supported=mount_data.get('guiding_supported', False),
                    is_shared=bool(mount_data.get('is_shared', item.get('is_shared', False))),
                    is_disabled=bool(mount_data.get('is_disabled', item.get('is_disabled', False))),
                    notes=mount_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )

                data['items'][i] = asdict(mount)

                if save_user_mounts(user_id, data):
                    return asdict(mount)
                return None

        return None

    except Exception as e:
        logger.error(f"Error updating mount: {e}")
        return None


def delete_mount(user_id: str, mount_id: str) -> Tuple[bool, Optional[List[str]]]:
    """Delete a mount profile. Refuses deletion when a combination still references it."""
    blocking = _find_combinations_referencing('mounts', mount_id)
    if blocking:
        return False, [combo['name'] for combo in blocking]
    try:
        data = load_user_mounts(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != mount_id]
        return save_user_mounts(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting mount: {e}")
        return False, None


# ============================================================
# CRUD Operations - Filters
# ============================================================


def load_user_filters(user_id: str) -> Dict:
    """Load user's filter profiles"""
    file_path = get_user_equipment_file(user_id, 'filters')

    if not os.path.exists(file_path):
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}

    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading filters for {user_id}: {e}")
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}


def save_user_filters(user_id: str, data: Dict) -> bool:
    """Save user's filter profiles with safety checks"""
    file_path = get_user_equipment_file(user_id, 'filters')
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return safe_save_equipment(file_path, data)


def create_filter(user_id: str, filter_data: Dict) -> Optional[Dict]:
    """Create a new filter profile"""
    try:
        filter_obj = Filter(
            id=str(uuid.uuid4()),
            name=filter_data['name'],
            manufacturer=filter_data.get('manufacturer', ''),
            filter_type=filter_data['filter_type'],
            central_wavelength_nm=(
                float(filter_data['central_wavelength_nm']) if filter_data.get('central_wavelength_nm') else None
            ),
            bandwidth_nm=float(filter_data['bandwidth_nm']) if filter_data.get('bandwidth_nm') else None,
            transmission_curve=filter_data.get('transmission_curve'),
            intended_use=filter_data.get('intended_use', ''),
            notes=filter_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_shared=bool(filter_data.get('is_shared', False)),
            is_disabled=bool(filter_data.get('is_disabled', False)),
        )

        data = load_user_filters(user_id)
        data['items'].append(asdict(filter_obj))

        if save_user_filters(user_id, data):
            return asdict(filter_obj)
        return None

    except Exception as e:
        logger.error(f"Error creating filter: {e}")
        return None


def get_filter(user_id: str, filter_id: str) -> Optional[Dict]:
    """Get a specific filter profile"""
    data = load_user_filters(user_id)
    for item in data['items']:
        if item['id'] == filter_id:
            return item
    return None


def update_filter(user_id: str, filter_id: str, filter_data: Dict) -> Optional[Dict]:
    """Update a filter profile"""
    try:
        data = load_user_filters(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == filter_id:
                filter_obj = Filter(
                    id=filter_id,
                    name=filter_data['name'],
                    manufacturer=filter_data.get('manufacturer', ''),
                    filter_type=filter_data['filter_type'],
                    central_wavelength_nm=(
                        float(filter_data['central_wavelength_nm'])
                        if filter_data.get('central_wavelength_nm')
                        else None
                    ),
                    bandwidth_nm=float(filter_data['bandwidth_nm']) if filter_data.get('bandwidth_nm') else None,
                    transmission_curve=filter_data.get('transmission_curve'),
                    intended_use=filter_data.get('intended_use', ''),
                    notes=filter_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    is_shared=bool(filter_data.get('is_shared', item.get('is_shared', False))),
                    is_disabled=bool(filter_data.get('is_disabled', item.get('is_disabled', False))),
                )

                data['items'][i] = asdict(filter_obj)

                if save_user_filters(user_id, data):
                    return asdict(filter_obj)
                return None

        return None

    except Exception as e:
        logger.error(f"Error updating filter: {e}")
        return None


def delete_filter(user_id: str, filter_id: str) -> Tuple[bool, Optional[List[str]]]:
    """Delete a filter profile. Refuses deletion when a combination still references it."""
    blocking = _find_combinations_referencing('filters', filter_id)
    if blocking:
        return False, [combo['name'] for combo in blocking]
    try:
        data = load_user_filters(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != filter_id]
        return save_user_filters(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting filter: {e}")
        return False, None


# ============================================================
# CRUD Operations - Accessories
# ============================================================


def load_user_accessories(user_id: str) -> Dict:
    """Load user's accessory profiles"""
    file_path = get_user_equipment_file(user_id, 'accessories')
    if not os.path.exists(file_path):
        return {
            'items': [],
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading accessories: {e}")
        return {
            'items': [],
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }


def save_user_accessories(user_id: str, data: Dict) -> bool:
    """Save user's accessory profiles"""
    file_path = get_user_equipment_file(user_id, 'accessories')
    return safe_save_equipment(file_path, data)


def create_accessory(user_id: str, accessory_data: Dict) -> Optional[Dict]:
    """Create a new accessory profile"""
    try:
        accessory = Accessory(
            id=str(uuid.uuid4()),
            name=accessory_data['name'],
            manufacturer=accessory_data.get('manufacturer', ''),
            accessory_type=accessory_data.get('accessory_type', ''),
            weight_kg=_get_float_or_none(accessory_data.get('weight_kg'), 0.0),
            notes=accessory_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_shared=bool(accessory_data.get('is_shared', False)),
            is_disabled=bool(accessory_data.get('is_disabled', False)),
        )

        data = load_user_accessories(user_id)
        data['items'].append(asdict(accessory))

        if save_user_accessories(user_id, data):
            return asdict(accessory)
        return None
    except Exception as e:
        logger.error(f"Error creating accessory: {e}")
        return None


def get_accessory(user_id: str, accessory_id: str) -> Optional[Dict]:
    """Get a specific accessory profile"""
    data = load_user_accessories(user_id)
    for item in data['items']:
        if item['id'] == accessory_id:
            return item
    return None


def update_accessory(user_id: str, accessory_id: str, accessory_data: Dict) -> Optional[Dict]:
    """Update an accessory profile"""
    try:
        data = load_user_accessories(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == accessory_id:
                accessory = Accessory(
                    id=accessory_id,
                    name=accessory_data['name'],
                    manufacturer=accessory_data.get('manufacturer', item.get('manufacturer', '')),
                    accessory_type=accessory_data.get('accessory_type', item.get('accessory_type', '')),
                    weight_kg=_get_float_or_none(accessory_data.get('weight_kg'), item.get('weight_kg', 0.0)),
                    notes=accessory_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    is_shared=bool(accessory_data.get('is_shared', item.get('is_shared', False))),
                    is_disabled=bool(accessory_data.get('is_disabled', item.get('is_disabled', False))),
                )

                data['items'][i] = asdict(accessory)

                if save_user_accessories(user_id, data):
                    return asdict(accessory)
                return None

        return None
    except Exception as e:
        logger.error(f"Error updating accessory: {e}")
        return None


def delete_accessory(user_id: str, accessory_id: str) -> Tuple[bool, Optional[List[str]]]:
    """Delete an accessory profile. Refuses deletion when a combination still references it."""
    blocking = _find_combinations_referencing('accessories', accessory_id)
    if blocking:
        return False, [combo['name'] for combo in blocking]
    try:
        data = load_user_accessories(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != accessory_id]
        return save_user_accessories(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting accessory: {e}")
        return False, None


# ============================================================
# Field of View Calculator
# ============================================================


def calculate_fov(
    telescope_focal_length_mm: float,
    camera_sensor_width_mm: float,
    camera_sensor_height_mm: float,
    camera_pixel_size_um: float,
    seeing_arcsec: float = 2.0,
) -> FOVCalculation:
    """
    Calculate Field of View and image scale

    Args:
        telescope_focal_length_mm: Effective focal length in mm
        camera_sensor_width_mm: Sensor width in mm
        camera_sensor_height_mm: Sensor height in mm
        camera_pixel_size_um: Pixel size in micrometers
        seeing_arcsec: Seeing conditions in arcseconds (default 2.0)

    Returns:
        FOVCalculation object with all calculated values
    """
    import math

    # FOV (degrees) = 57.3 × sensor dimension / focal length
    horizontal_fov_deg = round(57.3 * camera_sensor_width_mm / telescope_focal_length_mm, 4)
    vertical_fov_deg = round(57.3 * camera_sensor_height_mm / telescope_focal_length_mm, 4)

    # Diagonal FOV
    sensor_diagonal_mm = math.sqrt(camera_sensor_width_mm**2 + camera_sensor_height_mm**2)
    diagonal_fov_deg = round(57.3 * sensor_diagonal_mm / telescope_focal_length_mm, 4)

    # Image scale (arcsec/pixel) = 206.265 × pixel size (µm) / focal length (mm)
    # Note: pixel size stays in micrometers, NOT converted to mm
    image_scale_arcsec_per_px = round(206.265 * camera_pixel_size_um / telescope_focal_length_mm, 4)

    # Sampling classification
    # Optimal: 2-3 pixels per FWHM
    # Nyquist: 2 pixels per FWHM
    optimal_min = seeing_arcsec / 3.0
    optimal_max = seeing_arcsec / 2.0

    if image_scale_arcsec_per_px < optimal_min:
        sampling_classification = SamplingClassification.OVERSAMPLED.value
    elif image_scale_arcsec_per_px > optimal_max:
        sampling_classification = SamplingClassification.UNDERSAMPLED.value
    else:
        sampling_classification = SamplingClassification.OPTIMAL.value

    return FOVCalculation(
        horizontal_fov_deg=horizontal_fov_deg,
        vertical_fov_deg=vertical_fov_deg,
        diagonal_fov_deg=diagonal_fov_deg,
        image_scale_arcsec_per_px=image_scale_arcsec_per_px,
        sampling_classification=sampling_classification,
    )


# ============================================================
# CRUD Operations - Equipment Combinations
# ============================================================


def load_user_combinations(user_id: str) -> Dict:
    """Load user's equipment combinations"""
    file_path = get_user_equipment_file(user_id, 'combinations')

    if not os.path.exists(file_path):
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}

    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading combinations for {user_id}: {e}")
        return {'user_id': user_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': []}


def save_user_combinations(user_id: str, data: Dict) -> bool:
    """Save user's equipment combinations with safety checks"""
    file_path = get_user_equipment_file(user_id, 'combinations')
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return safe_save_equipment(file_path, data)


def create_combination(user_id: str, combination_data: Dict) -> Optional[Dict]:
    """Create a new equipment combination"""
    try:
        # Validate: at minimum telescope or camera must be selected
        if not combination_data.get('telescope_id') and not combination_data.get('camera_id'):
            logger.error("At minimum a telescope or camera must be selected")
            return None

        # lens_focal_length_mm/lens_focal_ratio only make sense for a camera-only combination
        # (a lens mounted directly on the camera) - cleared whenever a telescope is selected so
        # a combination can't end up with both a telescope and stale lens optics on record.
        has_telescope = bool(combination_data.get('telescope_id'))
        combination = EquipmentCombination(
            id=str(uuid.uuid4()),
            name=combination_data['name'],
            telescope_id=combination_data.get('telescope_id'),
            camera_id=combination_data.get('camera_id'),
            mount_id=combination_data.get('mount_id'),
            filter_ids=combination_data.get('filter_ids', []),
            accessory_ids=combination_data.get('accessory_ids', []),
            notes=combination_data.get('notes', ''),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            is_disabled=bool(combination_data.get('is_disabled', False)),
            guide_camera_id=combination_data.get('guide_camera_id') or None,
            lens_focal_length_mm=(
                None if has_telescope else _get_float_or_none(combination_data.get('lens_focal_length_mm'))
            ),
            lens_focal_ratio=None if has_telescope else _get_float_or_none(combination_data.get('lens_focal_ratio')),
        )

        data = load_user_combinations(user_id)
        data['items'].append(asdict(combination))

        if save_user_combinations(user_id, data):
            return asdict(combination)
        return None

    except Exception as e:
        logger.error(f"Error creating combination: {e}")
        return None


def get_combination(user_id: str, combination_id: str) -> Optional[Dict]:
    """Get a specific equipment combination"""
    data = load_user_combinations(user_id)
    for item in data['items']:
        if item['id'] == combination_id:
            return item
    return None


def update_combination(user_id: str, combination_id: str, combination_data: Dict) -> Optional[Dict]:
    """Update an equipment combination"""
    try:
        data = load_user_combinations(user_id)

        for i, item in enumerate(data['items']):
            if item['id'] == combination_id:
                # Validate: at minimum telescope or camera must be selected
                if not combination_data.get('telescope_id') and not combination_data.get('camera_id'):
                    logger.error("At minimum a telescope or camera must be selected")
                    return None

                # See create_combination: lens fields are camera-only optics and are cleared
                # whenever a telescope is selected, even if the submitted payload still carries
                # stale values from before a telescope was added.
                has_telescope = bool(combination_data.get('telescope_id'))
                combination = EquipmentCombination(
                    id=combination_id,
                    name=combination_data['name'],
                    telescope_id=combination_data.get('telescope_id'),
                    camera_id=combination_data.get('camera_id'),
                    mount_id=combination_data.get('mount_id'),
                    filter_ids=combination_data.get('filter_ids', []),
                    accessory_ids=combination_data.get('accessory_ids', []),
                    notes=combination_data.get('notes', ''),
                    created_at=item.get('created_at', datetime.now(timezone.utc).isoformat()),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    is_disabled=bool(combination_data.get('is_disabled', item.get('is_disabled', False))),
                    guide_camera_id=combination_data.get('guide_camera_id') or None,
                    lens_focal_length_mm=(
                        None if has_telescope else _get_float_or_none(combination_data.get('lens_focal_length_mm'))
                    ),
                    lens_focal_ratio=(
                        None if has_telescope else _get_float_or_none(combination_data.get('lens_focal_ratio'))
                    ),
                )

                data['items'][i] = asdict(combination)

                if save_user_combinations(user_id, data):
                    return asdict(combination)
                return None

        return None

    except Exception as e:
        logger.error(f"Error updating combination: {e}")
        return None


def delete_combination(user_id: str, combination_id: str) -> Tuple[bool, Optional[str]]:
    """Delete an equipment combination.

    Refuses deletion while any Astrodex picture (any user) still references this combination
    ('in_use_by_picture'), or any Plan My Night plan (any user) is pinned to it
    ('in_use_by_plan').
    """
    from observation.astrodex import count_pictures_for_combination
    from observation.plan_my_night import count_plans_for_combination

    if count_pictures_for_combination(combination_id) > 0:
        return False, 'in_use_by_picture'
    if count_plans_for_combination(combination_id) > 0:
        return False, 'in_use_by_plan'
    try:
        data = load_user_combinations(user_id)
        data['items'] = [item for item in data['items'] if item['id'] != combination_id]
        return save_user_combinations(user_id, data), None
    except Exception as e:
        logger.error(f"Error deleting combination: {e}")
        return False, None


# ============================================================
# Equipment Combination Analysis
# ============================================================


def analyze_combination(user_id: str, combination_id: str) -> Optional[CombinationAnalysis]:
    """Analyze an equipment combination for imaging suitability"""
    try:
        combination = get_combination(user_id, combination_id)
        if not combination:
            return None

        telescope_id_value = combination.get('telescope_id')
        camera_id_value = combination.get('camera_id')
        mount_id_value = combination.get('mount_id')

        telescope_id: Optional[str] = telescope_id_value if isinstance(telescope_id_value, str) else None
        camera_id: Optional[str] = camera_id_value if isinstance(camera_id_value, str) else None
        mount_id: Optional[str] = mount_id_value if isinstance(mount_id_value, str) else None

        telescope = get_telescope(user_id, telescope_id) if telescope_id else None
        camera = get_camera(user_id, camera_id) if camera_id else None
        mount = get_mount(user_id, mount_id) if mount_id else None

        filter_items: List[Dict] = []
        for filter_id in combination.get('filter_ids', []) or []:
            filter_obj = get_filter(user_id, filter_id)
            if filter_obj:
                filter_items.append(filter_obj)

        accessory_items: List[Dict] = []
        for accessory_id in combination.get('accessory_ids', []) or []:
            accessory_obj = get_accessory(user_id, accessory_id)
            if accessory_obj:
                accessory_items.append(accessory_obj)

        fov_result = None
        suitability: List[str] = []
        recommendations: List[str] = []

        if telescope and camera:
            focal_length = telescope.get('effective_focal_length') or telescope.get('focal_length_mm')
            if (
                focal_length
                and camera.get('sensor_width_mm')
                and camera.get('sensor_height_mm')
                and camera.get('pixel_size_um')
            ):
                fov_result = calculate_fov(
                    telescope_focal_length_mm=float(focal_length),
                    camera_sensor_width_mm=float(camera['sensor_width_mm']),
                    camera_sensor_height_mm=float(camera['sensor_height_mm']),
                    camera_pixel_size_um=float(camera['pixel_size_um']),
                )
                fov_result.telescope_name = telescope.get('name', '')
                fov_result.camera_name = camera.get('name', '')

                if fov_result.sampling_classification == SamplingClassification.OPTIMAL.value:
                    suitability.append("Balanced setup for typical seeing conditions")
                elif fov_result.sampling_classification == SamplingClassification.UNDERSAMPLED.value:
                    suitability.append("Better suited for wide-field targets")
                    recommendations.append("Use a longer focal length or smaller pixel camera for finer details")
                else:
                    suitability.append("Better suited for high-resolution imaging")
                    recommendations.append("Use binning or shorter focal length for easier guiding")

                if fov_result.diagonal_fov_deg >= 2.0:
                    suitability.append("Well suited for large nebulae and wide fields")
                elif fov_result.diagonal_fov_deg <= 0.5:
                    suitability.append("Well suited for compact targets like galaxies and planetary nebulae")
            else:
                recommendations.append("Complete telescope and camera specifications to compute FOV")
        else:
            recommendations.append("Select both a telescope and a camera for full optical analysis")

        if mount and telescope:
            camera_weight = float(camera.get('weight_kg', 0.0) or 0.0) if camera else 0.0
            total_payload = float(telescope.get('weight_kg', 0.0) or 0.0) + camera_weight
            recommended_payload = float(mount.get('recommended_payload_kg', 0.0) or 0.0)
            if total_payload > 0 and recommended_payload > 0:
                if total_payload <= recommended_payload:
                    suitability.append("Payload is within recommended mount limits")
                else:
                    recommendations.append("Payload may be too high for optimal tracking performance")

        if not suitability:
            suitability.append("Basic equipment combination is valid")
        if not recommendations:
            recommendations.append("No critical issues detected")

        return CombinationAnalysis(
            combination_id=combination_id,
            telescope=telescope,
            camera=camera,
            mount=mount,
            filters=filter_items,
            accessories=accessory_items,
            fov_calculation=fov_result,
            suitability=suitability,
            recommendations=recommendations,
        )
    except Exception as e:
        logger.error(f"Error analyzing combination: {e}")
        return None


# ============================================================
# Utility Functions
# ============================================================


def get_all_equipment_summary(user_id: str) -> Dict:
    """Get a summary of all user equipment"""
    return {
        'telescopes_count': len(load_user_telescopes(user_id).get('items', [])),
        'cameras_count': len(load_user_cameras(user_id).get('items', [])),
        'mounts_count': len(load_user_mounts(user_id).get('items', [])),
        'filters_count': len(load_user_filters(user_id).get('items', [])),
        'combinations_count': len(load_user_combinations(user_id).get('items', [])),
    }
