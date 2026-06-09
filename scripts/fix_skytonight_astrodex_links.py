"""Repair Astrodex catalogue/name pairs for reliable SkyTonight matching.

This script is intended for production maintenance after upgrading MyAstroBoard.
It scans all ``*_astrodex.json`` files and normalizes each item's catalogue/name
using the current SkyTonight aliases dataset.
Useful for migrating data from versions prior to 0.6.x

Usage examples:
  python scripts/fix_skytonight_astrodex_links.py --data-dir /app/data --dry-run
  python scripts/fix_skytonight_astrodex_links.py --data-dir /app/data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Iterable, Tuple


def _backend_import_path() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.normpath(os.path.join(here, '..', 'backend'))


sys.path.insert(0, _backend_import_path())

import skytonight_targets  # type: ignore  # noqa: E402


KNOWN_CATALOGUES = [
    'Messier',
    'OpenNGC',
    'OpenIC',
    'Caldwell',
    'CommonName',
]


def _iter_astrodex_files(data_dir: str) -> Iterable[str]:
    astrodex_dir = os.path.join(data_dir, 'astrodex')
    if not os.path.isdir(astrodex_dir):
        return []
    return [
        os.path.join(astrodex_dir, filename)
        for filename in os.listdir(astrodex_dir)
        if filename.endswith('_astrodex.json')
    ]


def _load_json(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _save_json(path: str, payload: Dict) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)


def _lookup_entry_any_catalogue(name: str) -> Dict:
    for catalogue in KNOWN_CATALOGUES:
        entry = skytonight_targets.get_lookup_entry(catalogue, name)
        if isinstance(entry, dict) and entry:
            return entry
    return {}


def _select_catalogue_alias(entry: Dict, current_catalogue: str) -> Tuple[str, str]:
    aliases = entry.get('aliases', {}) if isinstance(entry, dict) else {}
    if not isinstance(aliases, dict) or not aliases:
        return '', ''

    current_norm = str(current_catalogue or '').strip().lower()
    if current_norm:
        for alias_catalogue, alias_name in aliases.items():
            if str(alias_catalogue).strip().lower() == current_norm and str(alias_name or '').strip():
                return str(alias_catalogue), str(alias_name).strip()

    for preferred in KNOWN_CATALOGUES:
        for alias_catalogue, alias_name in aliases.items():
            if str(alias_catalogue).strip().lower() == preferred.lower() and str(alias_name or '').strip():
                return str(alias_catalogue), str(alias_name).strip()

    for alias_catalogue, alias_name in aliases.items():
        cleaned_name = str(alias_name or '').strip()
        if cleaned_name:
            return str(alias_catalogue), cleaned_name

    return '', ''


def _repair_item(item: Dict) -> bool:
    if not isinstance(item, dict):
        return False

    name = str(item.get('name', '') or '').strip()
    catalogue = str(item.get('catalogue', '') or '').strip()
    if not name:
        return False

    entry = skytonight_targets.get_lookup_entry(catalogue, name) if catalogue else {}
    if not entry:
        entry = _lookup_entry_any_catalogue(name)
    if not entry:
        return False

    new_catalogue, new_name = _select_catalogue_alias(entry, catalogue)
    if not new_name:
        return False

    changed = False
    if catalogue != new_catalogue:
        item['catalogue'] = new_catalogue
        changed = True
    if name != new_name:
        item['name'] = new_name
        changed = True

    if changed:
        item['updated_at'] = datetime.now().isoformat()

    return changed


def repair_file(path: str, dry_run: bool) -> Tuple[int, int]:
    payload = _load_json(path)
    items = payload.get('items', []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return (0, 0)

    changed_count = 0
    for item in items:
        if _repair_item(item):
            changed_count += 1

    if changed_count > 0 and not dry_run:
        backup_path = f"{path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not os.path.exists(backup_path):
            with open(path, 'r', encoding='utf-8') as source, open(backup_path, 'w', encoding='utf-8') as backup:
                backup.write(source.read())
        payload['updated_at'] = datetime.now().isoformat()
        _save_json(path, payload)

    return (len(items), changed_count)


def main() -> int:
    parser = argparse.ArgumentParser(description='Repair Astrodex catalogue/name links for SkyTonight matching')
    parser.add_argument('--data-dir', default='/app/data', help='Path to MyAstroBoard data directory')
    parser.add_argument('--dry-run', action='store_true', help='Only report changes without writing files')
    args = parser.parse_args()

    files = list(_iter_astrodex_files(args.data_dir))
    if not files:
        print(f'No Astrodex files found under: {os.path.join(args.data_dir, "astrodex")}')
        return 1

    total_items = 0
    total_changes = 0
    for file_path in sorted(files):
        item_count, changed_count = repair_file(file_path, dry_run=args.dry_run)
        total_items += item_count
        total_changes += changed_count
        print(f'{os.path.basename(file_path)}: {changed_count} updated item(s) out of {item_count}')

    mode = 'DRY-RUN' if args.dry_run else 'APPLIED'
    print(f'[{mode}] Processed {len(files)} file(s), {total_items} item(s), {total_changes} repaired item(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
