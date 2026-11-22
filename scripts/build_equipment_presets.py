"""Build and validate the equipment presets (static/data/equipment_presets.json).

The presets are edited as one small file per gear type and manufacturer:

    presets/equipment/<type>/<manufacturer>.json

where <type> is telescopes, cameras, mounts, filters or accessories, and <manufacturer> is the
manufacturer name in lowercase with every run of other characters replaced by a hyphen
("Sky-Watcher" -> sky-watcher.json, "William Optics" -> william-optics.json). Each file is
`{"$schema": "../<type>.schema.json", "presets": [...]}`: the JSON Schema gives completion and
inline errors in the editor.

A telescope's `bundle` lists the ids of the equipment that comes with it (smart telescopes): any
camera, mount, filter or accessory preset. An item marked `"built_in": true` (a smart telescope's
own camera or mount) is not sold on its own: it is left out of the standalone lists and only reaches
the app through the bundles that reference it. An item without it (a tripod also sold separately)
stays in its list as well.

This script merges the files into static/data/equipment_presets.json, the file the browser fetches,
with every bundle reference replaced by the item itself, and generates the schemas from the same
rules it checks. Never edit the generated files by hand.

Usage:
    python scripts/build_equipment_presets.py           # format the sources, rebuild, validate
    python scripts/build_equipment_presets.py --check   # validate only, write nothing (CI)

Checks (all are hard failures, every problem is listed at once):
  1. Every source file is valid JSON, `{"$schema": ..., "presets": [...]}`, with no duplicate keys.
  2. Every source file is in a known type folder, named after its manufacturer, and formatted
     the canonical way (2-space indent, presets sorted by id, ASCII text only).
  3. Every id is unique across all files and in snake_case.
  4. Every preset has the keys the frontend needs and no key it ignores, with the preset key
     names (resolution_w, not resolution_width_px).
  5. Enum values are the ones the frontend accepts: telescope and camera `type` codes from the
     lookup tables in static/js/equipment.js and equipment_bundles.js, mount_type and
     filter_type from the form selects in static/js/equipment.js.
  6. Numbers are inside the ranges the API accepts (read from backend/blueprints/equipment.py).
  7. A camera's sensor size matches resolution x pixel size within 2 %.
  8. Bundles reference existing, non-telescope presets: one camera, at most one mount, no repeat,
     and a mount that carries the telescope, camera and accessories within its recommended load
     (75 % of its capacity). A built-in item weighs 0 and is referenced by at least one bundle.
  9. static/data/equipment_presets.json matches the sources, and every <type>.schema.json matches
     the rules above.

The rules are documented in docs/EQUIPMENT.md#presets. Needs only the standard library, so the
CI job runs it without installing anything.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUBDIR = Path('presets') / 'equipment'
OUTPUT_FILE = Path('static') / 'data' / 'equipment_presets.json'
EQUIPMENT_JS = Path('static') / 'js' / 'equipment.js'
BUNDLES_JS = Path('static') / 'js' / 'equipment_bundles.js'
ROUTES_PY = Path('backend') / 'blueprints' / 'equipment.py'
REBUILD_HINT = 'run python scripts/build_equipment_presets.py'

# Output order of the arrays, and the gear kind each folder holds.
TYPE_DIRS = {
    'telescopes': 'telescope',
    'cameras': 'camera',
    'mounts': 'mount',
    'filters': 'filter',
    'accessories': 'accessory',
}
BUNDLE_KINDS = ('camera', 'mount', 'filter', 'accessory')
SCHEMA_FILES = {f'{type_dir}.schema.json' for type_dir in TYPE_DIRS}
COMMON_KEYS = {'id', 'label', 'manufacturer', 'source_url', 'suggests_experience'}
KEYS_BY_KIND = {
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
        'built_in',
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
        'built_in',
    },
    'filter': {'filter_type', 'central_wavelength_nm', 'bandwidth_nm', 'intended_use', 'weight_kg', 'built_in'},
    'accessory': {'accessory_type', 'weight_kg', 'built_in'},
}
REQUIRED_BY_KIND = {
    'telescope': {'type', 'aperture_mm', 'focal_length_mm', 'weight_kg'},
    'camera': {'type', 'sensor_width_mm', 'sensor_height_mm', 'pixel_size_um', 'resolution_w', 'resolution_h'},
    'mount': {'mount_type', 'payload_capacity_kg'},
    'filter': {'filter_type'},
    'accessory': {'accessory_type'},
}
# Required on every preset sold on its own; optional on a built-in item.
STANDALONE_KEYS = {'source_url', 'suggests_experience'}
# Preset key -> stored field name, where they differ (static/js/equipment_bundles.js).
STORED_NAMES = {'label': 'name', 'resolution_w': 'resolution_width_px', 'resolution_h': 'resolution_height_px'}
EXPERIENCE_LEVELS = {'beginner', 'intermediate', 'advanced'}
STRING_KEYS = {'id', 'label', 'manufacturer', 'source_url', 'intended_use', 'accessory_type'}
BOOLEAN_KEYS = {'auto_combination', 'cooling_supported', 'guiding_supported', 'meridian_flip_required', 'built_in'}
INTEGER_KEYS = {'resolution_w', 'resolution_h'}
ID_RE = re.compile(r'^[a-z0-9]+(?:_[a-z0-9]+)*$')
# Makers round published sensor dimensions to 0.1 mm or so; 2 % absorbs that rounding but
# not a swapped axis, a wrong pixel pitch or a sensor taken from another model.
SENSOR_SIZE_TOLERANCE = 0.02
RECOMMENDED_LOAD = 0.75

DESCRIPTIONS = {
    'id': 'Unique snake_case id across every preset file.',
    'label': 'Display name; becomes the item name.',
    'manufacturer': 'Brand, exactly as the file is named after it.',
    'source_url': "The maker's official spec page every value comes from.",
    'suggests_experience': 'Sorts the presets matching the user experience level first.',
    'focal_ratio': 'Informational; the app recalculates it from focal length / aperture.',
    'weight_kg': 'For a smart telescope: the whole unit. A built-in item weighs 0.',
    'resolution_w': 'Pixels across, in the orientation the device delivers its images (not resolution_width_px).',
    'resolution_h': 'Pixels down, in the orientation the device delivers its images (not resolution_height_px).',
    'sensor_width_mm': 'Must equal resolution_w x pixel_size_um / 1000 within 2 %.',
    'sensor_height_mm': 'Must equal resolution_h x pixel_size_um / 1000 within 2 %.',
    'payload_capacity_kg': 'A smart telescope mount: at least the unit weight / 0.75.',
    'auto_combination': 'Create the bundle items and a combination when this preset is picked.',
    'bundle': (
        'Ids of the camera, mount, filters and accessories that come with this telescope: '
        'one camera, at most one mount.'
    ),
    'built_in': (
        'Part of a smart telescope, not sold on its own: hidden from the preset pickers, weighs 0, '
        "reached through the telescope's bundle."
    ),
}
TYPE_DESCRIPTIONS = {
    'telescope': 'A preset code, not the form label.',
    'camera': 'A preset code, not the form label (dslr_color and mirrorless_color are stored as CMOS Color).',
}


class DuplicateKeyError(ValueError):
    """A JSON object repeats a key (json.load would silently keep the last value)."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise DuplicateKeyError(f'duplicate key(s) {", ".join(duplicates)}')
    return dict(pairs)


def manufacturer_slug(name: str) -> str:
    """File name stem for a manufacturer: lowercase, other characters collapsed to one hyphen."""
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def dump_json(data: Any) -> str:
    """The canonical text of a generated or source file."""
    return json.dumps(data, indent=2, ensure_ascii=True) + '\n'


def canonical(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A source file's presets in their canonical order (by id)."""
    return sorted(entries, key=lambda entry: str(entry.get('id', '')))


def source_text(rel: Path, entries: list[dict[str, Any]]) -> str:
    """The canonical text of a source file."""
    return dump_json({'$schema': f'../{rel.parent.name}.schema.json', 'presets': canonical(entries)})


# ---------------------------------------------------------------------------
# What the frontend and the API accept, read from their sources
# ---------------------------------------------------------------------------


def _js_map_keys(source: str, name: str) -> set[str]:
    """Keys of a `const NAME = { key: 'Value', ... };` lookup table."""
    match = re.search(rf'const {name} = \{{(.*?)\}};', source, re.S)
    if not match:
        raise LookupError(f'{name} not found')
    return set(re.findall(r'^\s*(\w+):', match.group(1), re.M))


def _select_options(source: str, select_id: str) -> set[str]:
    """Values of a form `<select id=...>`."""
    match = re.search(rf'id="{select_id}"(.*?)</select>', source, re.S)
    if not match:
        raise LookupError(f'select #{select_id} not found')
    return set(re.findall(r'<option value="([^"$]+)"', match.group(1)))


def api_ranges(source: str) -> dict[str, dict[str, tuple[float, float]]]:
    """The (field, low, high) ranges each `_validate_<kind>_data` route helper checks."""
    ranges: dict[str, dict[str, tuple[float, float]]] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        match = re.fullmatch(r'_validate_(\w+)_data', node.name)
        if not match or match.group(1) not in KEYS_BY_KIND:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and len(call.args) == 2 and isinstance(call.args[1], ast.List):
                specs = ast.literal_eval(call.args[1])
                ranges[match.group(1)] = {field: (low, high) for field, low, high, _ in specs}
    missing = set(KEYS_BY_KIND) - set(ranges)
    if missing:
        raise LookupError(f'range checks not found for {", ".join(sorted(missing))}')
    return ranges


def load_rules(root: Path) -> dict[str, Any]:
    """Everything the checks compare against, read from the frontend and backend sources."""
    equipment_js = (root / EQUIPMENT_JS).read_text(encoding='utf-8')
    bundles_js = (root / BUNDLES_JS).read_text(encoding='utf-8')
    return {
        'telescope_codes': _js_map_keys(equipment_js, '_TELESCOPE_PRESET_TYPE_MAP'),
        'camera_codes': _js_map_keys(bundles_js, 'EQUIPMENT_PRESET_SENSOR_TYPE_MAP'),
        'mount_types': _select_options(equipment_js, 'mount-type'),
        'filter_types': _select_options(equipment_js, 'filter-type'),
        'ranges': api_ranges((root / ROUTES_PY).read_text(encoding='utf-8')),
    }


# ---------------------------------------------------------------------------
# Loading the sources, building the outputs
# ---------------------------------------------------------------------------


def load_sources(root: Path, errors: list[str]) -> dict[Path, list[dict[str, Any]]]:
    """The presets of every readable source file, keyed by path relative to root."""
    source_dir = root / SOURCE_SUBDIR
    sources: dict[Path, list[dict[str, Any]]] = {}
    if not source_dir.is_dir():
        errors.append(f'{SOURCE_SUBDIR.as_posix()}: folder not found')
        return sources
    for path in sorted(source_dir.rglob('*')):
        rel = path.relative_to(root)
        name = rel.as_posix()
        if path.is_dir() or (path.parent == source_dir and path.name in SCHEMA_FILES | {'README.md'}):
            continue
        if path.parent.parent != source_dir or path.parent.name not in TYPE_DIRS:
            errors.append(f'{name}: unexpected file; presets go in {SOURCE_SUBDIR.as_posix()}/<type>/')
            continue
        if path.suffix != '.json':
            errors.append(f'{name}: not a .json file')
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
        except DuplicateKeyError as exc:
            errors.append(f'{name}: {exc}')
            continue
        except json.JSONDecodeError as exc:
            errors.append(f'{name}: invalid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})')
            continue
        expected_schema = f'../{path.parent.name}.schema.json'
        presets = data.get('presets') if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or set(data) != {'$schema', 'presets'}
            or not isinstance(presets, list)
            or not all(isinstance(entry, dict) for entry in presets)
        ):
            errors.append(f'{name}: must be {{"$schema": "{expected_schema}", "presets": [...]}}')
            continue
        if data['$schema'] != expected_schema:
            errors.append(f'{name}: $schema must be "{expected_schema}"')
        sources[rel] = presets
    return sources


def index_by_id(sources: dict[Path, list[dict[str, Any]]]) -> dict[str, tuple[str, dict[str, Any], Path]]:
    """Every preset by id, with its kind and file (the first one wins when an id repeats)."""
    index: dict[str, tuple[str, dict[str, Any], Path]] = {}
    for rel, entries in sources.items():
        for entry in entries:
            if isinstance(entry.get('id'), str):
                index.setdefault(entry['id'], (TYPE_DIRS[rel.parent.name], entry, rel))
    return index


def _resolved_bundle(telescope: dict[str, Any], index: dict[str, tuple[str, dict[str, Any], Path]]) -> list[Any]:
    """A telescope's bundle with each reference replaced by `{"kind": ..., **item}` (built_in dropped)."""
    resolved: list[Any] = []
    for ref in telescope['bundle']:
        kind, item, _ = index[ref]
        resolved.append({'kind': kind, **{key: value for key, value in item.items() if key != 'built_in'}})
    return resolved


def build_output(sources: dict[Path, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """The generated file: one array per type (built-in items left out), bundles resolved."""
    index = index_by_id(sources)
    output: dict[str, list[dict[str, Any]]] = {type_dir: [] for type_dir in TYPE_DIRS}
    for rel in sorted(sources, key=lambda path: (list(TYPE_DIRS).index(path.parent.name), path.name)):
        for entry in canonical(sources[rel]):
            if entry.get('built_in'):
                continue
            if isinstance(entry.get('bundle'), list):
                entry = {**entry, 'bundle': _resolved_bundle(entry, index)}
            output[rel.parent.name].append(entry)
    return output


def _property(kind: str, key: str, rules: dict[str, Any], *, required: bool) -> dict[str, Any]:
    """The JSON Schema of one preset key."""
    enums: dict[str, set[str]] = {
        'suggests_experience': EXPERIENCE_LEVELS,
        'mount_type': rules['mount_types'],
        'filter_type': rules['filter_types'],
    }
    if kind in ('telescope', 'camera'):
        enums['type'] = rules[f'{kind}_codes']
    prop: dict[str, Any]
    if key == 'bundle':
        prop = {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string', 'pattern': ID_RE.pattern}}
    elif key in enums:
        prop = {'type': 'string', 'enum': sorted(enums[key])}
    elif key == 'id':
        prop = {'type': 'string', 'pattern': ID_RE.pattern}
    elif key in STRING_KEYS:
        prop = {'type': 'string', 'minLength': 1} if required else {'type': 'string'}
    elif key in BOOLEAN_KEYS:
        prop = {'type': 'boolean'}
    else:
        prop = {'type': 'integer' if key in INTEGER_KEYS else 'number'}
        low_high = rules['ranges'][kind].get(STORED_NAMES.get(key, key))
        if low_high:
            prop['minimum'], prop['maximum'] = low_high
        if not required:
            prop['type'] = [prop['type'], 'null']
    description = TYPE_DESCRIPTIONS.get(kind) if key == 'type' else DESCRIPTIONS.get(key)
    return {'description': description, **prop} if description else prop


def _definition(kind: str, rules: dict[str, Any]) -> dict[str, Any]:
    """The JSON Schema of one preset."""
    keys = COMMON_KEYS | KEYS_BY_KIND[kind]
    required = {'id', 'label', 'manufacturer'} | REQUIRED_BY_KIND[kind]
    definition: dict[str, Any] = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {key: _property(kind, key, rules, required=key in required) for key in sorted(keys)},
    }
    if kind == 'telescope':
        definition['required'] = sorted(required | STANDALONE_KEYS)
    else:
        definition['required'] = sorted(required)
        definition['if'] = {'properties': {'built_in': {'const': True}}, 'required': ['built_in']}
        definition['then'] = {'properties': {'weight_kg': {'const': 0}}, 'required': ['weight_kg']}
        definition['else'] = {'required': sorted(STANDALONE_KEYS)}
    return definition


def build_schemas(rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One JSON Schema per type folder, keyed by file name."""
    schemas: dict[str, dict[str, Any]] = {}
    for type_dir, kind in TYPE_DIRS.items():
        schemas[f'{type_dir}.schema.json'] = {
            '$schema': 'http://json-schema.org/draft-07/schema#',
            'title': f'MyAstroBoard {kind} presets',
            'description': (
                'Generated by scripts/build_equipment_presets.py from the rules it checks - do not edit. '
                'See docs/EQUIPMENT.md#presets.'
            ),
            'type': 'object',
            'additionalProperties': False,
            'required': ['$schema', 'presets'],
            'properties': {
                '$schema': {'const': f'../{type_dir}.schema.json'},
                'presets': {'type': 'array', 'items': {'$ref': f'#/definitions/{kind}'}},
            },
            'definitions': {kind: _definition(kind, rules)},
        }
    return schemas


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _non_ascii(value: Any) -> bool:
    if isinstance(value, str):
        return any(ord(char) > 127 for char in value)
    if isinstance(value, dict):
        return any(_non_ascii(key) or _non_ascii(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_non_ascii(item) for item in value)
    return False


def _number(entry: dict[str, Any], key: str) -> float | None:
    value = entry.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def check_entry(where: str, kind: str, entry: dict[str, Any], rules: dict[str, Any], *, maker: str) -> list[str]:
    """Problems with one preset, on its own (bundles are checked by check_bundle)."""
    errors: list[str] = []
    built_in = entry.get('built_in') is True
    allowed = COMMON_KEYS | KEYS_BY_KIND[kind]
    required = {'id', 'label', 'manufacturer'} | REQUIRED_BY_KIND[kind] | (set() if built_in else STANDALONE_KEYS)
    preset_names = {stored: preset for preset, stored in STORED_NAMES.items()}
    for key in sorted(set(entry) - allowed):
        hint = f' (use {preset_names[key]!r})' if key in preset_names else ''
        errors.append(f'{where}: unknown key {key!r}{hint}')
    for key in sorted(required - set(entry)):
        errors.append(f'{where}: missing key {key!r}')

    if 'id' in entry and not (isinstance(entry['id'], str) and ID_RE.match(entry['id'])):
        errors.append(f'{where}: id {entry["id"]!r} must be snake_case (a-z, 0-9, _)')
    if 'manufacturer' in entry and entry['manufacturer'] != maker:
        errors.append(f'{where}: manufacturer {entry["manufacturer"]!r} does not match the file ({maker!r})')
    if 'suggests_experience' in entry and entry['suggests_experience'] not in EXPERIENCE_LEVELS:
        errors.append(f'{where}: suggests_experience must be one of {", ".join(sorted(EXPERIENCE_LEVELS))}')
    if 'built_in' in entry and entry['built_in'] is not True:
        errors.append(f'{where}: built_in is either true or left out')
    if built_in and entry.get('weight_kg') != 0:
        errors.append(f'{where}: a built-in item has weight_kg 0 (the telescope weight is the whole unit)')

    enum_checks = {
        'telescope': ('type', rules['telescope_codes']),
        'camera': ('type', rules['camera_codes']),
        'mount': ('mount_type', rules['mount_types']),
        'filter': ('filter_type', rules['filter_types']),
    }
    if kind in enum_checks:
        key, accepted = enum_checks[kind]
        if key in entry and entry[key] not in accepted:
            errors.append(f'{where}: {key} {entry[key]!r} is not one of {", ".join(sorted(accepted))}')

    for key, value in entry.items():
        stored = STORED_NAMES.get(key, key)
        if stored in rules['ranges'][kind] and value is not None:
            low, high = rules['ranges'][kind][stored]
            number = _number(entry, key)
            if number is None or not low <= number <= high:
                errors.append(f'{where}: {key} {value!r} must be a number between {low} and {high}')

    if kind == 'camera':
        pitch = _number(entry, 'pixel_size_um')
        for size_key, pixels_key in (('sensor_width_mm', 'resolution_w'), ('sensor_height_mm', 'resolution_h')):
            size, pixels = _number(entry, size_key), _number(entry, pixels_key)
            if size and pixels and pitch:
                derived = pixels * pitch / 1000
                if abs(derived - size) > SENSOR_SIZE_TOLERANCE * size:
                    errors.append(
                        f'{where}: {size_key} {size} does not match {pixels_key} x pixel_size_um '
                        f'({derived:.2f} mm); check the orientation and the spec sheet'
                    )
    return errors


def check_bundle(
    where: str, telescope: dict[str, Any], index: dict[str, tuple[str, dict[str, Any], Path]]
) -> list[str]:
    """Problems with a telescope's bundle references."""
    bundle = telescope['bundle']
    if not isinstance(bundle, list) or not all(isinstance(ref, str) for ref in bundle):
        return [f'{where}: bundle must be a list of preset ids']
    repeated = sorted({ref for ref in bundle if bundle.count(ref) > 1})
    errors = [f'{where}: bundle lists {ref!r} more than once' for ref in repeated]
    items: list[tuple[str, dict[str, Any]]] = []
    for ref in dict.fromkeys(bundle):
        if ref not in index:
            errors.append(f'{where}: bundle references unknown preset {ref!r}')
        elif index[ref][0] == 'telescope':
            errors.append(f'{where}: bundle references a telescope ({ref!r})')
        else:
            items.append((index[ref][0], index[ref][1]))
    kinds = [kind for kind, _ in items]
    if kinds.count('camera') != 1:
        errors.append(f'{where}: a bundle needs exactly one camera (found {kinds.count("camera")})')
    if kinds.count('mount') > 1:
        errors.append(f'{where}: a bundle holds at most one mount')
    # Same sum as the combination card in static/js/equipment.js: telescope + camera + accessories.
    carried = (_number(telescope, 'weight_kg') or 0) + sum(
        _number(item, 'weight_kg') or 0 for kind, item in items if kind in ('camera', 'accessory')
    )
    for kind, mount in items:
        payload = _number(mount, 'payload_capacity_kg')
        if kind == 'mount' and payload and carried > RECOMMENDED_LOAD * payload + 1e-9:
            errors.append(
                f'{where}: mount {mount.get("id")!r} carries {carried:.2f} kg, more than {RECOMMENDED_LOAD:.0%} of its '
                f'payload_capacity_kg; raise it to at least {carried / RECOMMENDED_LOAD:.2f} kg'
            )
    return errors


def source_problems(root: Path, sources: dict[Path, list[dict[str, Any]]], rules: dict[str, Any]) -> list[str]:
    """Every problem in the source files themselves."""
    errors: list[str] = []
    index = index_by_id(sources)
    referenced: set[str] = set()
    for rel, entries in sources.items():
        name = rel.as_posix()
        kind = TYPE_DIRS[rel.parent.name]
        if _non_ascii(entries):
            errors.append(f'{name}: use ASCII text only (straight quotes, hyphen-minus)')
        elif (root / rel).read_text(encoding='utf-8') != source_text(rel, entries):
            errors.append(f'{name}: not formatted; {REBUILD_HINT}')
        makers = {entry.get('manufacturer') for entry in entries}
        maker = next(iter(makers)) if len(makers) == 1 else None
        if not entries:
            errors.append(f'{name}: no presets')
        elif not isinstance(maker, str) or manufacturer_slug(maker) != rel.stem:
            expected = sorted(manufacturer_slug(m) + '.json' for m in makers if isinstance(m, str))
            errors.append(f'{name}: one manufacturer per file, named after it (expected {", ".join(expected)})')
        for entry in entries:
            where = f'{name} > {entry.get("id", "?")}'
            errors.extend(check_entry(where, kind, entry, rules, maker=maker or ''))
            entry_id = entry.get('id')
            if isinstance(entry_id, str) and index[entry_id][1] is not entry:
                errors.append(f'{where}: id {entry_id!r} already used in {index[entry_id][2].as_posix()}')
            if 'bundle' in entry:
                errors.extend(check_bundle(where, entry, index))
                if isinstance(entry['bundle'], list):
                    referenced.update(ref for ref in entry['bundle'] if isinstance(ref, str))
    for entry_id, (_, entry, rel) in index.items():
        if entry.get('built_in') is True and entry_id not in referenced:
            errors.append(f'{rel.as_posix()} > {entry_id}: built-in but no telescope bundle references it')
    return errors


def validate(root: Path, sources: dict[Path, list[dict[str, Any]]], rules: dict[str, Any]) -> list[str]:
    """Every problem in the sources, then (once they hold) in the generated files."""
    errors = source_problems(root, sources, rules)
    if errors:
        return errors
    output = root / OUTPUT_FILE
    if not output.is_file() or output.read_text(encoding='utf-8') != dump_json(build_output(sources)):
        errors.append(f'{OUTPUT_FILE.as_posix()}: out of date; {REBUILD_HINT}')
    for schema_name, schema in build_schemas(rules).items():
        path = root / SOURCE_SUBDIR / schema_name
        if not path.is_file() or path.read_text(encoding='utf-8') != dump_json(schema):
            errors.append(f'{(SOURCE_SUBDIR / schema_name).as_posix()}: out of date; {REBUILD_HINT}')
    return errors


def write(root: Path, sources: dict[Path, list[dict[str, Any]]], rules: dict[str, Any]) -> None:
    """Format every ASCII source file, rebuild the schemas, and the generated file once the sources hold."""
    for rel, entries in sources.items():
        if not _non_ascii(entries):
            (root / rel).write_text(source_text(rel, entries), encoding='utf-8', newline='\n')
    for schema_name, schema in build_schemas(rules).items():
        (root / SOURCE_SUBDIR / schema_name).write_text(dump_json(schema), encoding='utf-8', newline='\n')
    if not source_problems(root, sources, rules):
        (root / OUTPUT_FILE).write_text(dump_json(build_output(sources)), encoding='utf-8', newline='\n')


def run(root: Path, *, check_only: bool) -> list[str]:
    """Load, optionally write, then validate. Returns every problem found."""
    errors: list[str] = []
    sources = load_sources(root, errors)
    if errors:
        return errors
    rules = load_rules(root)
    if not check_only:
        write(root, sources, rules)
    return validate(root, sources, rules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build and validate the equipment presets.')
    parser.add_argument('--check', action='store_true', help='validate only, write nothing (CI)')
    args = parser.parse_args(argv)
    errors = run(ROOT, check_only=args.check)
    if errors:
        sys.stderr.write(f'{len(errors)} problem(s) in the equipment presets:\n')
        sys.stderr.writelines(f'  - {error}\n' for error in errors)
        sys.stderr.write('Rules: docs/EQUIPMENT.md#presets\n')
        return 1
    sys.stdout.write('Equipment presets OK\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
