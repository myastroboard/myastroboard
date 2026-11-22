"""The equipment presets against the real frontend and API (static/data/equipment_presets.json).

Every rule is checked by scripts/build_equipment_presets.py, which reads the allowed codes from the
JS sources and the API ranges from backend/blueprints/equipment.py without importing anything, so
its CI job needs no dependency. These tests prove that the repository passes it, and that what the
script reads from those sources matches what the code really does. See docs/EQUIPMENT.md#presets.
"""

import importlib.util
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


# ---------------------------------------------------------------------------
# Every preset through the real create routes
# ---------------------------------------------------------------------------

_PRESETS = json.loads((_ROOT / 'static' / 'data' / 'equipment_presets.json').read_text(encoding='utf-8'))
_ENDPOINTS = {
    'telescope': '/api/equipment/telescopes',
    'camera': '/api/equipment/cameras',
    'mount': '/api/equipment/mounts',
    'filter': '/api/equipment/filters',
    'accessory': '/api/equipment/accessories',
}
_ARRAYS = {
    'telescope': 'telescopes',
    'camera': 'cameras',
    'mount': 'mounts',
    'filter': 'filters',
    'accessory': 'accessories',
}
# Preset keys the frontend never sends: provenance, sorting and bundle wiring.
_NOT_SENT = {'id', 'source_url', 'suggests_experience', 'focal_ratio', 'auto_combination', 'bundle', 'kind'}


def _js_map(source: str, name: str) -> dict[str, str]:
    """A `const NAME = { key: 'Value', ... };` lookup table of a JS source, as a dict."""
    match = re.search(rf'const {name} = \{{(.*?)\}};', source, re.S)
    assert match, f'{name} not found'
    return dict(re.findall(r"(\w+):\s*'([^']+)'", match.group(1)))


_TELESCOPE_TYPES = _js_map(_EQUIPMENT_JS, '_TELESCOPE_PRESET_TYPE_MAP')
_SENSOR_TYPES = _js_map(_BUNDLES_JS, 'EQUIPMENT_PRESET_SENSOR_TYPE_MAP')


def _form_payload(kind: str, preset: dict[str, Any]) -> dict[str, Any]:
    """What the Equipment form sends once a preset has filled it: stored field names, form type values."""
    payload = {build.STORED_NAMES.get(key, key): value for key, value in preset.items() if key not in _NOT_SENT}
    if kind == 'telescope':
        payload['telescope_type'] = _TELESCOPE_TYPES.get(payload.pop('type', ''), 'Refractor')
    if kind == 'camera':
        payload['sensor_type'] = _SENSOR_TYPES.get(payload.pop('type', ''), 'CMOS Color')
    return payload


def _standalone_presets() -> list[tuple[str, dict[str, Any]]]:
    return [(kind, preset) for kind, key in _ARRAYS.items() for preset in _PRESETS[key]]


@pytest.fixture
def preset_client():
    """A client signed in as a real user account, as the create routes require."""
    from app import app
    from utils.auth import user_manager

    app.config['TESTING'] = True
    user = user_manager.get_user_by_username('preset_tester') or user_manager.create_user(
        'preset_tester', 'preset-tester-pw', 'user'
    )
    assert user is not None
    with app.test_client() as client:
        with client.session_transaction() as session:
            session['user_id'] = user.user_id
            session['username'] = user.username
            session['role'] = user.role
        yield client


@pytest.mark.parametrize(
    'kind, preset', _standalone_presets(), ids=lambda value: value['id'] if isinstance(value, dict) else value
)
def test_every_preset_is_accepted_and_stored_as_given(preset_client: Any, kind: str, preset: dict[str, Any]):
    """Creating an item from each preset, as the form does, succeeds and stores every value unchanged."""
    payload = _form_payload(kind, preset)

    response = preset_client.post(_ENDPOINTS[kind], json=payload)

    assert response.status_code == 201, response.get_json()
    stored = response.get_json()['data']
    for field, value in payload.items():
        assert stored.get(field) == value, f'{field}: sent {value!r}, stored {stored.get(field)!r}'


@pytest.mark.parametrize(
    'telescope',
    [preset for preset in _PRESETS['telescopes'] if preset.get('bundle')],
    ids=lambda preset: preset['id'],
)
def test_every_bundle_creates_its_items_and_combination(preset_client: Any, telescope: dict[str, Any]):
    """A smart telescope preset creates its built-in items and a combination linking all of them."""
    created = preset_client.post(_ENDPOINTS['telescope'], json=_form_payload('telescope', telescope))
    assert created.status_code == 201, created.get_json()
    links: dict[str, Any] = {'camera_id': None, 'mount_id': None, 'filter_ids': [], 'accessory_ids': []}
    for item in telescope['bundle']:
        response = preset_client.post(_ENDPOINTS[item['kind']], json=_form_payload(item['kind'], item))
        assert response.status_code == 201, (item['id'], response.get_json())
        item_id = response.get_json()['data']['id']
        if item['kind'] in ('camera', 'mount'):
            links[f"{item['kind']}_id"] = item_id
        else:
            links[f"{item['kind']}_ids"].append(item_id)

    response = preset_client.post(
        '/api/equipment/combinations',
        json={'name': telescope['label'], 'telescope_id': created.get_json()['data']['id'], **links},
    )

    assert response.status_code == 201, response.get_json()
    assert links['camera_id'] is not None
