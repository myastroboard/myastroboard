"""Schema checks for the equipment presets (static/data/equipment_presets.json).

The presets are fetched by the browser and turned into create payloads by equipment.js,
equipment_bundles.js and first_run.js. A wrong key or enum value is not an error there: the field
is silently left empty or replaced by a default, and a bundle item the API rejects is skipped, which
leaves a smart telescope combination without its camera. These tests catch that at commit time.
The allowed codes and form values are read from the JS sources, so they cannot drift apart.
See docs/EQUIPMENT.md#preset-field-reference.
"""

import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from blueprints.equipment import (
    _validate_accessory_data,
    _validate_camera_data,
    _validate_filter_data,
    _validate_mount_data,
    _validate_telescope_data,
)

_ROOT = Path(__file__).resolve().parents[2]
_PRESETS = json.loads((_ROOT / 'static' / 'data' / 'equipment_presets.json').read_text(encoding='utf-8'))
_EQUIPMENT_JS = (_ROOT / 'static' / 'js' / 'equipment.js').read_text(encoding='utf-8')
_BUNDLES_JS = (_ROOT / 'static' / 'js' / 'equipment_bundles.js').read_text(encoding='utf-8')
_WIZARD_JS = (_ROOT / 'static' / 'js' / 'first_run.js').read_text(encoding='utf-8')

_COMMON_KEYS = {'id', 'label', 'manufacturer', 'source_url', 'suggests_experience'}
_KEYS_BY_KIND = {
    'telescope': {'type', 'aperture_mm', 'focal_length_mm', 'focal_ratio', 'weight_kg', 'auto_combination', 'bundle'},
    'camera': {
        'type',
        'sensor_width_mm',
        'sensor_height_mm',
        'pixel_size_um',
        'resolution_w',
        'resolution_h',
        'weight_kg',
        'cooling_supported',
        'min_temperature_c',
    },
    'mount': {
        'mount_type',
        'payload_capacity_kg',
        'tracking_accuracy_arcsec',
        'guiding_supported',
        'meridian_flip_required',
        'meridian_flip_delay_min',
        'meridian_flip_duration_min',
        'weight_kg',
    },
    'filter': {'filter_type', 'central_wavelength_nm', 'bandwidth_nm', 'intended_use', 'weight_kg'},
    'accessory': {'accessory_type', 'weight_kg'},
}
_REQUIRED_BY_KIND = {
    'telescope': {'type', 'aperture_mm', 'focal_length_mm', 'weight_kg'},
    'camera': {'type', 'sensor_width_mm', 'sensor_height_mm', 'pixel_size_um', 'resolution_w', 'resolution_h'},
    'mount': {'mount_type', 'payload_capacity_kg'},
    'filter': {'filter_type'},
    'accessory': {'accessory_type'},
}
_ARRAY_BY_KIND = {
    'telescope': 'telescopes',
    'camera': 'cameras',
    'mount': 'mounts',
    'filter': 'filters',
    'accessory': 'accessories',
}
_EXPERIENCE_LEVELS = {'beginner', 'intermediate', 'advanced'}
# Makers round published sensor dimensions to 0.1 mm or so; 2 % absorbs that rounding but
# not a swapped axis, a wrong pixel pitch or a sensor taken from another model.
_SENSOR_SIZE_TOLERANCE = 0.02


def _js_map_keys(source: str, name: str) -> set[str]:
    """Keys of a `const NAME = { key: 'Value', ... };` lookup table in a JS source."""
    match = re.search(rf'const {name} = \{{(.*?)\}};', source, re.S)
    assert match, f'{name} not found'
    return set(re.findall(r'^\s*(\w+):', match.group(1), re.M))


def _js_map_values(source: str, name: str) -> set[str]:
    """Values of a `const NAME = { key: 'Value', ... };` lookup table in a JS source."""
    match = re.search(rf'const {name} = \{{(.*?)\}};', source, re.S)
    assert match, f'{name} not found'
    return set(re.findall(r":\s*'([^']+)'", match.group(1)))


def _select_options(select_id: str) -> set[str]:
    """Values a form `<select id=...>` in equipment.js accepts."""
    match = re.search(rf'id="{select_id}"(.*?)</select>', _EQUIPMENT_JS, re.S)
    assert match, f'select #{select_id} not found'
    return set(re.findall(r'<option value="([^"$]+)"', match.group(1)))


_TELESCOPE_CODES = _js_map_keys(_EQUIPMENT_JS, '_TELESCOPE_PRESET_TYPE_MAP')
_CAMERA_CODES = _js_map_keys(_BUNDLES_JS, 'EQUIPMENT_PRESET_SENSOR_TYPE_MAP')


def _entries() -> list[tuple[str, dict[str, Any], bool]]:
    """Every preset as (kind, entry, is_bundle_item), bundle items included."""
    entries: list[tuple[str, dict[str, Any], bool]] = []
    for kind, array in _ARRAY_BY_KIND.items():
        for entry in _PRESETS[array]:
            entries.append((kind, entry, False))
            for item in entry.get('bundle', []):
                entries.append((item.get('kind', '?'), item, True))
    return entries


def _entry_id(param: tuple[str, dict[str, Any], bool]) -> str:
    kind, entry, is_bundle = param
    return f'{"bundle-" if is_bundle else ""}{kind}-{entry.get("id", "?")}'


def _cameras() -> list[tuple[str, dict[str, Any], bool]]:
    return [param for param in _entries() if param[0] == 'camera']


def _payload(kind: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The stored field names a preset entry is turned into (mirrors equipment_bundles.js)."""
    renamed = {'label': 'name', 'resolution_w': 'resolution_width_px', 'resolution_h': 'resolution_height_px'}
    return {renamed.get(key, key): value for key, value in entry.items() if key not in ('kind', 'bundle')}


_VALIDATORS = {
    'telescope': _validate_telescope_data,
    'camera': _validate_camera_data,
    'mount': _validate_mount_data,
    'filter': _validate_filter_data,
    'accessory': _validate_accessory_data,
}


def test_preset_ids_are_unique():
    """Every preset id, bundle items included, is unique across the whole file."""
    ids = [entry['id'] for _, entry, _ in _entries()]
    duplicates = sorted({preset_id for preset_id in ids if ids.count(preset_id) > 1})
    assert not duplicates


def test_js_type_maps_point_at_form_values():
    """The preset type codes translate to values the telescope and camera forms accept."""
    assert _js_map_values(_EQUIPMENT_JS, '_TELESCOPE_PRESET_TYPE_MAP') <= _select_options('telescope-type')
    assert _js_map_values(_BUNDLES_JS, 'EQUIPMENT_PRESET_SENSOR_TYPE_MAP') <= _select_options('camera-sensor-type')


def test_js_type_maps_agree_between_tab_and_wizard():
    """The Equipment tab and the setup wizard accept the same preset type codes."""
    assert _js_map_keys(_WIZARD_JS, '_WIZARD_TELESCOPE_TYPE_MAP') == _TELESCOPE_CODES
    assert _js_map_keys(_EQUIPMENT_JS, '_CAMERA_PRESET_SENSOR_TYPE_MAP') == _CAMERA_CODES


@pytest.mark.parametrize('param', _entries(), ids=_entry_id)
def test_preset_uses_only_known_keys(param: tuple[str, dict[str, Any], bool]):
    """A preset carries only the keys the JS reads, with the preset names (resolution_w, not resolution_width_px)."""
    kind, entry, is_bundle = param
    assert kind in _KEYS_BY_KIND, f'unknown bundle kind {kind!r}'
    allowed = _COMMON_KEYS | _KEYS_BY_KIND[kind] | ({'kind'} if is_bundle else set())
    assert set(entry) - allowed == set()


@pytest.mark.parametrize('param', _entries(), ids=_entry_id)
def test_preset_has_required_keys(param: tuple[str, dict[str, Any], bool]):
    """A preset has an id, a label, a maker and every spec its form or the API needs."""
    kind, entry, is_bundle = param
    required = {'id', 'label', 'manufacturer'} | _REQUIRED_BY_KIND[kind]
    if not is_bundle:
        required |= {'source_url', 'suggests_experience'}
    assert required - set(entry) == set()
    if 'suggests_experience' in entry:
        assert entry['suggests_experience'] in _EXPERIENCE_LEVELS


@pytest.mark.parametrize('param', _entries(), ids=_entry_id)
def test_preset_enum_fields_are_valid(param: tuple[str, dict[str, Any], bool]):
    """`type` is a lowercase preset code; mount_type and filter_type are the exact form values."""
    kind, entry, _ = param
    if kind == 'telescope':
        assert entry['type'] in _TELESCOPE_CODES
    elif kind == 'camera':
        assert entry['type'] in _CAMERA_CODES
    elif kind == 'mount':
        assert entry['mount_type'] in _select_options('mount-type')
    elif kind == 'filter':
        assert entry['filter_type'] in _select_options('filter-type')


@pytest.mark.parametrize('param', _entries(), ids=_entry_id)
def test_preset_values_pass_api_validation(param: tuple[str, dict[str, Any], bool]):
    """The create payload built from a preset is inside the ranges the API accepts."""
    kind, entry, _ = param
    assert _VALIDATORS[kind](_payload(kind, entry)) is None


@pytest.mark.parametrize('param', _cameras(), ids=_entry_id)
def test_camera_sensor_matches_resolution_times_pixel_size(param: tuple[str, dict[str, Any], bool]):
    """Sensor width and height agree with resolution x pixel pitch, in the same orientation."""
    _, camera, _ = param
    for size_key, pixels_key in (('sensor_width_mm', 'resolution_w'), ('sensor_height_mm', 'resolution_h')):
        derived_mm = camera[pixels_key] * camera['pixel_size_um'] / 1000
        assert derived_mm == pytest.approx(camera[size_key], rel=_SENSOR_SIZE_TOLERANCE), size_key


@pytest.mark.parametrize(
    'preset', [preset for preset in _PRESETS['telescopes'] if preset.get('bundle')], ids=lambda preset: preset['id']
)
def test_bundle_items_weigh_nothing_and_mount_carries_the_unit(preset: dict[str, Any]):
    """Bundle items have weight_kg 0, and the built-in mount carries the unit within its recommended load."""
    for item in preset['bundle']:
        assert item.get('weight_kg') == 0, item['id']
    mounts = [item for item in preset['bundle'] if item['kind'] == 'mount']
    assert len(mounts) <= 1
    for mount in mounts:
        assert preset['weight_kg'] <= 0.75 * mount['payload_capacity_kg'] + 1e-9
