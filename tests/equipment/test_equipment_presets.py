"""The equipment presets against the real frontend and API (static/data/equipment_presets.json).

Every rule is checked by scripts/build_equipment_presets.py, which reads the allowed codes from the
JS sources and the API ranges from backend/blueprints/equipment.py without importing anything, so
its CI job needs no dependency. These tests prove that the repository passes it, and that what the
script reads from those sources matches what the code really does. See docs/EQUIPMENT.md#presets.
"""

import importlib.util
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
_SPEC = importlib.util.spec_from_file_location(
    'build_equipment_presets', _ROOT / 'scripts' / 'build_equipment_presets.py'
)
build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build)

_RULES = build.load_rules(_ROOT)
_EQUIPMENT_JS = (_ROOT / 'static' / 'js' / 'equipment.js').read_text(encoding='utf-8')
_BUNDLES_JS = (_ROOT / 'static' / 'js' / 'equipment_bundles.js').read_text(encoding='utf-8')
_WIZARD_JS = (_ROOT / 'static' / 'js' / 'first_run.js').read_text(encoding='utf-8')

_VALIDATORS = {
    'telescope': _validate_telescope_data,
    'camera': _validate_camera_data,
    'mount': _validate_mount_data,
    'filter': _validate_filter_data,
    'accessory': _validate_accessory_data,
}


def _js_map_values(source: str, name: str) -> set[str]:
    """Values of a `const NAME = { key: 'Value', ... };` lookup table in a JS source."""
    match = re.search(rf'const {name} = \{{(.*?)\}};', source, re.S)
    assert match, f'{name} not found'
    return set(re.findall(r":\s*'([^']+)'", match.group(1)))


def test_repository_presets_pass_the_build_check():
    """The sources are valid and formatted, and the generated file and schemas are up to date."""
    assert build.run(_ROOT, check_only=True) == []


@pytest.mark.parametrize(
    'kind, field, bound',
    [(kind, field, bound) for kind, fields in _RULES['ranges'].items() for field, bound in fields.items()],
    ids=lambda value: str(value),
)
def test_ranges_read_by_the_script_match_the_api(kind: str, field: str, bound: tuple[float, float]):
    """Each range the script reads from the route source is the one the API enforces."""
    low, high = bound
    validator: Any = _VALIDATORS[kind]

    assert validator({field: low}) is None
    assert validator({field: high}) is None
    assert validator({field: low - 1}) is not None
    assert validator({field: high + 1}) is not None


def test_js_type_maps_point_at_form_values():
    """The preset type codes translate to values the telescope and camera forms accept."""
    telescope_options = build._select_options(_EQUIPMENT_JS, 'telescope-type')
    camera_options = build._select_options(_EQUIPMENT_JS, 'camera-sensor-type')

    assert _js_map_values(_EQUIPMENT_JS, '_TELESCOPE_PRESET_TYPE_MAP') <= telescope_options
    assert _js_map_values(_BUNDLES_JS, 'EQUIPMENT_PRESET_SENSOR_TYPE_MAP') <= camera_options


def test_js_type_maps_agree_between_tab_and_wizard():
    """The Equipment tab and the setup wizard accept the same preset type codes."""
    assert build._js_map_keys(_WIZARD_JS, '_WIZARD_TELESCOPE_TYPE_MAP') == _RULES['telescope_codes']
    assert build._js_map_keys(_EQUIPMENT_JS, '_CAMERA_PRESET_SENSOR_TYPE_MAP') == _RULES['camera_codes']
