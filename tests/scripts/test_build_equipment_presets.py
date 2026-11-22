"""Tests for scripts/build_equipment_presets.py: the equipment presets build and CI gate."""

import copy
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location(
    'build_equipment_presets', ROOT / 'scripts' / 'build_equipment_presets.py'
)
build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build)

EQUIPMENT_JS = """
const _TELESCOPE_PRESET_TYPE_MAP = {
    refractor: 'Refractor',
    apo: 'Apochromatic Refractor (APO)',
};
const form = `
<select class="form-select" id="mount-type" name="mount_type">
    <option value="Equatorial">x</option>
    <option value="Alt-Azimuth">x</option>
</select>
<select class="form-select" id="filter-type" name="filter_type">
    <option value="Solar">x</option>
    <option value="Other">x</option>
</select>`;
"""
BUNDLES_JS = """
const EQUIPMENT_PRESET_SENSOR_TYPE_MAP = {
    cmos_color: 'CMOS Color',
    cmos_mono: 'CMOS Mono',
};
"""
ROUTES_PY = """
def _validate_telescope_data(data):
    return _validate_numeric_ranges(data, [('aperture_mm', 10, 5000, 'mm'), ('focal_length_mm', 100, 50000, 'mm')])


def _validate_camera_data(data):
    return _validate_numeric_ranges(data, [('resolution_width_px', 640, 16000, 'px'), ('pixel_size_um', 1, 10, 'um')])


def _validate_mount_data(data):
    return _validate_numeric_ranges(data, [('payload_capacity_kg', 0.1, 100, 'kg')])


def _validate_filter_data(data):
    return _validate_numeric_ranges(data, [('bandwidth_nm', 1, 1000, 'nm')])


def _validate_accessory_data(data):
    return _validate_numeric_ranges(data, [('weight_kg', 0, 50, 'kg')])
"""

MAKER = 'Acme Optics'
SCOPE: dict[str, Any] = {
    'id': 'acme_scope',
    'label': 'Scope',
    'manufacturer': MAKER,
    'aperture_mm': 50,
    'focal_length_mm': 250,
    'type': 'apo',
    'weight_kg': 3.0,
    'suggests_experience': 'beginner',
    'source_url': 'https://example.com/scope',
    'auto_combination': True,
    'bundle': ['acme_scope_camera', 'acme_scope_mount'],
}
CAMERA: dict[str, Any] = {
    'id': 'acme_scope_camera',
    'label': 'Scope camera',
    'manufacturer': MAKER,
    'sensor_width_mm': 5.6,
    'sensor_height_mm': 3.15,
    'pixel_size_um': 2.9,
    'resolution_w': 1920,
    'resolution_h': 1080,
    'type': 'cmos_color',
    'weight_kg': 0,
    'built_in': True,
}
MOUNT: dict[str, Any] = {
    'id': 'acme_scope_mount',
    'label': 'Scope mount',
    'manufacturer': MAKER,
    'mount_type': 'Alt-Azimuth',
    'payload_capacity_kg': 4,
    'weight_kg': 0,
    'built_in': True,
}
TRIPOD: dict[str, Any] = {
    'id': 'acme_tripod',
    'label': 'Tripod',
    'manufacturer': MAKER,
    'accessory_type': 'Tripod',
    'weight_kg': 0.6,
    'suggests_experience': 'beginner',
    'source_url': 'https://example.com/tripod',
}


def _write_source(root: Path, type_dir: str, stem: str, presets: list[dict[str, Any]]) -> Path:
    path = root / 'presets' / 'equipment' / type_dir / f'{stem}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'$schema': f'../{type_dir}.schema.json', 'presets': presets}), encoding='utf-8')
    return path


def _write_smart_scope(
    root: Path, scope: dict[str, Any], camera: dict[str, Any], mount: dict[str, Any], tripod: dict[str, Any]
) -> None:
    _write_source(root, 'telescopes', 'acme-optics', [scope])
    _write_source(root, 'cameras', 'acme-optics', [camera])
    _write_source(root, 'mounts', 'acme-optics', [mount])
    _write_source(root, 'accessories', 'acme-optics', [tripod])


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal project: the frontend and route sources the rules come from, and a valid smart telescope."""
    for rel, text in (
        (build.EQUIPMENT_JS, EQUIPMENT_JS),
        (build.BUNDLES_JS, BUNDLES_JS),
        (build.ROUTES_PY, ROUTES_PY),
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding='utf-8')
    (tmp_path / build.OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    _write_smart_scope(tmp_path, copy.deepcopy(SCOPE), copy.deepcopy(CAMERA), copy.deepcopy(MOUNT), dict(TRIPOD))
    return tmp_path


def _problems_after_build(root: Path) -> list[str]:
    """Format and build, then validate - what a contributor sees after running the script."""
    return build.run(root, check_only=False)


def _output(root: Path) -> dict[str, Any]:
    return json.loads((root / build.OUTPUT_FILE).read_text(encoding='utf-8'))


def test_valid_tree_builds_output_schemas_and_passes_check(tree: Path):
    """A valid source tree is formatted, merged into the output file, given schemas, then passes --check."""
    assert _problems_after_build(tree) == []
    assert build.run(tree, check_only=True) == []

    assert list(_output(tree)) == list(build.TYPE_DIRS)
    for schema_name in build.SCHEMA_FILES:
        assert (tree / build.SOURCE_SUBDIR / schema_name).is_file()


def test_bundle_references_are_resolved_and_built_in_items_hidden(tree: Path):
    """The output inlines each bundled item with its kind, and lists built-in items only inside bundles."""
    _problems_after_build(tree)
    output = _output(tree)

    bundle = output['telescopes'][0]['bundle']
    assert [item['kind'] for item in bundle] == ['camera', 'mount']
    assert bundle[0] == {'kind': 'camera', **{key: value for key, value in CAMERA.items() if key != 'built_in'}}
    assert output['cameras'] == []
    assert output['mounts'] == []
    assert [item['id'] for item in output['accessories']] == ['acme_tripod']


def test_item_sold_separately_can_be_bundled_and_listed(tree: Path):
    """A bundled item without built_in keeps its own list entry and its real weight."""
    scope = copy.deepcopy(SCOPE) | {'bundle': [*SCOPE['bundle'], 'acme_tripod']}
    mount = copy.deepcopy(MOUNT) | {'payload_capacity_kg': 5}
    _write_smart_scope(tree, scope, copy.deepcopy(CAMERA), mount, dict(TRIPOD))

    assert _problems_after_build(tree) == []
    output = _output(tree)
    assert output['telescopes'][0]['bundle'][-1] == {'kind': 'accessory', **TRIPOD}
    assert [item['id'] for item in output['accessories']] == ['acme_tripod']


def test_check_reports_stale_output_and_unformatted_source(tree: Path):
    """--check writes nothing and reports a source edited without rebuilding."""
    assert _problems_after_build(tree) == []
    _write_source(tree, 'telescopes', 'acme-optics', [copy.deepcopy(SCOPE) | {'label': 'Renamed'}])

    problems = build.run(tree, check_only=True)

    assert any('telescopes/acme-optics.json: not formatted' in problem for problem in problems)


def test_check_reports_stale_output(tree: Path):
    """A formatted source whose change was never built leaves the generated file out of date."""
    assert _problems_after_build(tree) == []
    (tree / build.OUTPUT_FILE).write_text('{}\n', encoding='utf-8')

    assert build.run(tree, check_only=True) == [
        'static/data/equipment_presets.json: out of date; run python scripts/build_equipment_presets.py'
    ]


def test_schema_follows_the_rules_read_from_the_frontend(tree: Path):
    """The generated schemas carry the codes, form values and API ranges of the project sources."""
    _problems_after_build(tree)

    def definition(type_dir: str, kind: str) -> dict[str, Any]:
        schema = json.loads((tree / build.SOURCE_SUBDIR / f'{type_dir}.schema.json').read_text(encoding='utf-8'))
        return schema['definitions'][kind]

    telescope, camera = definition('telescopes', 'telescope'), definition('cameras', 'camera')
    assert telescope['properties']['type']['enum'] == ['apo', 'refractor']
    assert telescope['properties']['bundle']['items']['type'] == 'string'
    assert camera['properties']['type']['enum'] == ['cmos_color', 'cmos_mono']
    assert definition('mounts', 'mount')['properties']['mount_type']['enum'] == ['Alt-Azimuth', 'Equatorial']
    assert camera['properties']['resolution_w']['minimum'] == 640
    assert camera['then'] == {'properties': {'weight_kg': {'const': 0}}, 'required': ['weight_kg']}
    assert camera['else'] == {'required': ['source_url', 'suggests_experience']}
    assert telescope['additionalProperties'] is False


@pytest.mark.parametrize(
    'raw, expected',
    [
        ('{"$schema": "../telescopes.schema.json", "presets": [}', 'invalid JSON'),
        ('{"$schema": "../telescopes.schema.json", "presets": [{"id": "a", "id": "b"}]}', 'duplicate key(s) id'),
        ('[{"id": "a"}]', 'must be {"$schema"'),
        ('{"$schema": "../cameras.schema.json", "presets": []}', '$schema must be "../telescopes.schema.json"'),
    ],
    ids=['invalid-json', 'duplicate-key', 'bare-list', 'wrong-schema'],
)
def test_unreadable_source_is_reported(tree: Path, raw: str, expected: str):
    """Broken JSON, a repeated key or the wrong envelope stop the build with the file named."""
    (tree / build.SOURCE_SUBDIR / 'telescopes' / 'broken.json').write_text(raw, encoding='utf-8')

    problems = _problems_after_build(tree)

    assert any(p.startswith('presets/equipment/telescopes/broken.json') and expected in p for p in problems)


def test_file_outside_a_type_folder_is_reported(tree: Path):
    """A preset file must sit in one of the type folders."""
    stray = tree / build.SOURCE_SUBDIR / 'scopes' / 'acme-optics.json'
    stray.parent.mkdir()
    stray.write_text('{}', encoding='utf-8')

    assert any('scopes/acme-optics.json: unexpected file' in problem for problem in _problems_after_build(tree))


def test_file_must_be_named_after_its_manufacturer(tree: Path):
    """The file name is the manufacturer slug, and a file holds one manufacturer."""
    source = tree / build.SOURCE_SUBDIR / 'accessories' / 'acme-optics.json'
    source.rename(source.with_name('acme.json'))

    problems = _problems_after_build(tree)

    assert any(
        'acme.json: one manufacturer per file, named after it (expected acme-optics.json)' in p for p in problems
    )


def test_duplicate_id_across_files_is_reported(tree: Path):
    """Ids are unique across every file."""
    _write_source(tree, 'accessories', 'zed', [dict(TRIPOD) | {'id': 'acme_scope_camera', 'manufacturer': 'Zed'}])

    assert any("id 'acme_scope_camera' already used" in problem for problem in _problems_after_build(tree))


def _broken(tree: Path, change: Callable[[dict[str, dict[str, Any]]], Any]) -> list[str]:
    """Problems reported after applying change() to the valid smart telescope's presets."""
    presets = {
        'scope': copy.deepcopy(SCOPE),
        'camera': copy.deepcopy(CAMERA),
        'mount': copy.deepcopy(MOUNT),
        'tripod': dict(TRIPOD),
    }
    change(presets)
    _write_smart_scope(tree, presets['scope'], presets['camera'], presets['mount'], presets['tripod'])
    return _problems_after_build(tree)


def _rename_resolution(p: dict[str, dict[str, Any]]) -> None:
    p['camera']['resolution_width_px'] = p['camera'].pop('resolution_w')


@pytest.mark.parametrize(
    'change, expected',
    [
        (_rename_resolution, "unknown key 'resolution_width_px' (use 'resolution_w')"),
        (lambda p: p['camera'].pop('resolution_w'), "missing key 'resolution_w'"),
        (lambda p: p['scope'].pop('source_url'), "missing key 'source_url'"),
        (lambda p: p['tripod'].pop('suggests_experience'), "missing key 'suggests_experience'"),
        (lambda p: p['scope'].update(type='Apochromatic Refractor (APO)'), "is not one of apo, refractor"),
        (lambda p: p['camera'].update(type='CMOS Color'), "type 'CMOS Color' is not one of cmos_color, cmos_mono"),
        (lambda p: p['mount'].update(mount_type='AltAz'), "mount_type 'AltAz' is not one of"),
        (lambda p: p['scope'].update(id='Acme-Scope'), 'must be snake_case'),
        (lambda p: p['scope'].update(suggests_experience='expert'), 'suggests_experience must be one of'),
        (lambda p: p['scope'].update(aperture_mm=5), 'aperture_mm 5 must be a number between 10 and 5000'),
        (lambda p: p['camera'].update(resolution_w=320), 'resolution_w 320 must be a number between 640 and 16000'),
        (
            lambda p: p['camera'].update(sensor_width_mm=3.15, sensor_height_mm=5.6),
            'sensor_width_mm 3.15 does not match',
        ),
        (lambda p: p['camera'].update(weight_kg=0.2), 'a built-in item has weight_kg 0'),
        (lambda p: p['tripod'].update(built_in=False), 'built_in is either true or left out'),
        (lambda p: p['tripod'].update(built_in=True, weight_kg=0), 'built-in but no telescope bundle references it'),
        (lambda p: p['scope'].update(bundle=['acme_scope_mount']), 'exactly one camera (found 0)'),
        (lambda p: p['scope']['bundle'].append('acme_lens'), "bundle references unknown preset 'acme_lens'"),
        (lambda p: p['scope']['bundle'].append('acme_scope'), "bundle references a telescope ('acme_scope')"),
        (lambda p: p['scope']['bundle'].append('acme_scope_mount'), "bundle lists 'acme_scope_mount' more than once"),
        (lambda p: p['scope'].update(bundle=[{'kind': 'camera'}]), 'bundle must be a list of preset ids'),
        (lambda p: p['mount'].update(payload_capacity_kg=3), "mount 'acme_scope_mount' carries 3.00 kg"),
        (lambda p: p['scope']['bundle'].append('acme_tripod'), "mount 'acme_scope_mount' carries 3.60 kg"),
        (lambda p: p['scope'].update(label='Scope ’ pro'), 'use ASCII text only'),
    ],
    ids=[
        'stored-field-name',
        'missing-resolution',
        'missing-source-url',
        'standalone-missing-experience',
        'telescope-form-label',
        'camera-form-label',
        'unknown-mount-type',
        'id-not-snake-case',
        'unknown-experience',
        'out-of-api-range',
        'resolution-below-api-range',
        'sensor-axes-swapped',
        'built-in-weight',
        'built-in-false',
        'built-in-unreferenced',
        'bundle-without-camera',
        'bundle-unknown-ref',
        'bundle-telescope-ref',
        'bundle-repeat',
        'bundle-inline-object',
        'mount-too-weak-for-unit',
        'bundled-accessory-weight-counts',
        'non-ascii',
    ],
)
def test_preset_rule_violation_is_reported(
    tree: Path, change: Callable[[dict[str, dict[str, Any]]], Any], expected: str
):
    """Each rule of docs/EQUIPMENT.md#presets is enforced, with a message naming the problem."""
    problems = _broken(tree, change)

    assert any(expected in problem for problem in problems), problems


def test_main_lists_every_problem_and_fails(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The command exits 1 and prints every problem with a pointer to the rules."""
    monkeypatch.setattr(build, 'ROOT', tree)
    _broken(tree, lambda p: p['scope'].update(aperture_mm=5, suggests_experience='expert'))

    assert build.main(['--check']) == 1

    err = capsys.readouterr().err
    assert '2 problem(s) in the equipment presets' in err
    assert 'Rules: docs/EQUIPMENT.md#presets' in err


def test_main_succeeds_on_a_valid_tree(tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """The command exits 0 once the sources are valid and the generated files are up to date."""
    monkeypatch.setattr(build, 'ROOT', tree)

    assert build.main([]) == 0
    assert build.main(['--check']) == 0
    assert 'Equipment presets OK' in capsys.readouterr().out


def test_missing_rule_source_raises(tree: Path):
    """A renamed lookup table or route helper fails loudly instead of accepting anything."""
    (tree / build.BUNDLES_JS).write_text('const OTHER = {};', encoding='utf-8')

    with pytest.raises(LookupError, match='EQUIPMENT_PRESET_SENSOR_TYPE_MAP'):
        build.run(tree, check_only=True)
