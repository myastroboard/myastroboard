"""
Common utilities and helper functions for MyAstroBoard backend
Provides reusable functionality to avoid code duplication
"""

import os
import re
import json
import math
import sys
import unicodedata
import yaml
from typing import Dict, Tuple, Optional
from constants import CONFIG_FILE, DATA_DIR
from logging_config import get_logger

logger = get_logger(__name__)

# Optional numpy dependency - imported once at module level
try:
    import numpy as _np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


class _NumpySafeEncoder(json.JSONEncoder):
    """JSON encoder that converts numpy scalar types to native Python types.

    This avoids ``TypeError: Object of type int64 is not JSON serializable``
    when the payload contains values derived from numpy/astropy calculations.
    NaN and Inf values are replaced with None so the output remains valid JSON.
    """

    def default(self, obj: object) -> object:  # type: ignore[override]
        if _HAS_NUMPY:  # pragma: no branch
            if isinstance(obj, _np.integer):  # type: ignore[union-attr]
                return int(obj)
            if isinstance(obj, _np.floating):  # type: ignore[union-attr]
                v = float(obj)
                return None if (math.isnan(v) or math.isinf(v)) else v
            if isinstance(obj, _np.ndarray):  # type: ignore[union-attr]
                return obj.tolist()
            if isinstance(obj, _np.bool_):  # type: ignore[union-attr]
                return bool(obj)
        return super().default(obj)


def _sanitize_for_json(obj: object) -> object:
    """Recursively convert numpy types and replace NaN/Inf with None."""
    if _HAS_NUMPY:  # pragma: no branch
        if isinstance(obj, _np.integer):  # type: ignore[union-attr]
            return int(obj)
        if isinstance(obj, _np.floating):  # type: ignore[union-attr]
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, _np.bool_):  # type: ignore[union-attr]
            return bool(obj)
        if isinstance(obj, _np.ndarray):  # type: ignore[union-attr]
            return [_sanitize_for_json(x) for x in obj.tolist()]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(x) for x in obj]
    return obj


# Custom YAML Dumper for proper indentation
class IndentDumper(yaml.Dumper):
    """Custom YAML dumper that ensures proper indentation for lists"""

    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


def ensure_directory_exists(path: str) -> None:
    """
    Ensure a directory exists, creating it if necessary

    Args:
        path: Directory path to create
    """
    os.makedirs(path, exist_ok=True)


def slugify_location_name(value: str, fallback: str = 'default-location') -> str:
    """Convert a human location label into a stable ASCII filesystem slug."""
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    ascii_value = normalized.encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', ascii_value.lower()).strip('-')
    return slug or fallback


def safe_file_exists(file_path: str) -> bool:
    """
    Safely check if a file exists

    Args:
        file_path: Path to check

    Returns:
        True if file exists, False otherwise
    """
    try:
        return os.path.exists(file_path) and os.path.isfile(file_path)
    except (OSError, TypeError):
        return False


def load_json_file(file_path: str, default: Optional[dict] = None) -> dict:
    """
    Safely load a JSON file with fallback to default value

    Args:
        file_path: Path to JSON file
        default: Default value if file doesn't exist or is invalid

    Returns:
        Loaded JSON data or default value
    """
    if default is None:
        default = {}

    try:
        if safe_file_exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        pass  # corrupt or unreadable file — return the caller-supplied default

    return default


def save_json_file(file_path: str, data: dict) -> bool:
    """
    Safely save data to a JSON file

    Args:
        file_path: Path to save to
        data: Data to save

    Returns:
        True if successful, False otherwise
    """
    try:
        ensure_directory_exists(os.path.dirname(file_path))
        # Write to a sibling temp file then atomically rename so concurrent
        # readers never see a truncated/empty file mid-write.
        tmp_path = file_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(_sanitize_for_json(data), f, indent=2, ensure_ascii=False, cls=_NumpySafeEncoder)
        os.replace(tmp_path, file_path)
        return True
    except Exception as exc:
        logger.error(f'save_json_file failed for {file_path}: {type(exc).__name__}: {exc}')
        return False


# Coordinate conversion utilities
DMS_PATTERN = re.compile(r"([+-]?\d+)[d°]\s*(\d+)[m']\s*([\d.]+)[s\"]?")


def dms_to_decimal(dms_string: str) -> Optional[float]:
    """
    Convert DMS (Degrees Minutes Seconds) string to decimal degrees

    Args:
        dms_string: DMS string like "48d38m36.16s" or "48°38'36.16\""

    Returns:
        Decimal degrees or None if conversion fails
    """
    try:
        match = DMS_PATTERN.match(dms_string.strip())
        if not match:
            return None

        degrees = float(match.group(1))
        minutes = float(match.group(2))
        seconds = float(match.group(3))

        # Handle negative degrees
        if degrees < 0:
            return degrees - (minutes / 60.0) - (seconds / 3600.0)
        else:
            return degrees + (minutes / 60.0) + (seconds / 3600.0)
    except (ValueError, AttributeError, TypeError):
        return None


def decimal_to_dms(decimal_degrees: float) -> Tuple[int, int, float]:
    """
    Convert decimal degrees to DMS components

    Args:
        decimal_degrees: Decimal degrees value

    Returns:
        Tuple of (degrees, minutes, seconds)
    """
    degrees = int(decimal_degrees)
    minutes_float = (abs(decimal_degrees) - abs(degrees)) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60

    return degrees, minutes, seconds


def validate_coordinates(lat: float, lon: float) -> bool:
    """
    Validate latitude and longitude values

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees

    Returns:
        True if coordinates are valid, False otherwise
    """
    try:
        return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
    except (ValueError, TypeError):
        return False


def format_file_size(size_bytes: float) -> str:
    """
    Format file size in human-readable format

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string like "1.5 MB"
    """
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_environment_info() -> Dict[str, str]:
    """
    Get useful environment information for debugging

    Returns:
        Dictionary with environment details
    """
    return {
        'data_dir': DATA_DIR,
        'config_file_exists': str(safe_file_exists(CONFIG_FILE)),
        'python_version': sys.version,
        'platform': os.name,
        'working_directory': os.getcwd(),
        'docker_env': str(os.path.exists('/.dockerenv')),
    }


def normalize_catalogue_key(value: Optional[str]) -> str:
    """Normalize a catalogue/target name for loose cross-referencing (uppercase, no separators)."""
    return re.sub(r'[^A-Za-z0-9]', '', str(value or '')).upper()


# astropy's bundled constellation_names.dat (Roman 1987) carries a few historical
# misspellings that don't match the modern IAU-sanctioned names used by our i18n
# files. Correct astropy.coordinates.get_constellation()'s output before it's used
# as a display name or translation key.
_ASTROPY_CONSTELLATION_FIXES: Dict[str, str] = {
    'Ophiucus': 'Ophiuchus',
    'Chamaleon': 'Chamaeleon',
    'Pisces Austrinus': 'Piscis Austrinus',
}


def fix_astropy_constellation_name(name: str) -> str:
    """Correct known misspellings in astropy's get_constellation() output."""
    return _ASTROPY_CONSTELLATION_FIXES.get(name, name)
