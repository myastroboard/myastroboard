"""Check translation completeness in static/i18n against en.json reference."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT_DIR / "static" / "i18n"
REFERENCE_FILE = "en.json"


def flatten_keys(data: Any, parent: str = "") -> set[str]:
    """Return flattened dot-notation keys from nested JSON-like data."""
    keys: set[str] = set()

    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{parent}.{key}" if parent else str(key)
            if isinstance(value, (dict, list)):
                keys.update(flatten_keys(value, path))
            else:
                keys.add(path)
        return keys

    if isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{parent}[{index}]" if parent else f"[{index}]"
            if isinstance(value, (dict, list)):
                keys.update(flatten_keys(value, path))
            else:
                keys.add(path)

    return keys


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file and ensure top-level object is a dictionary."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Top-level JSON object must be a dictionary in {path.name}")
    return payload


def iter_language_files(i18n_dir: Path) -> Iterable[Path]:
    """Yield all language JSON files in deterministic order."""
    return sorted(i18n_dir.glob("*.json"))


def main() -> None:
    if not I18N_DIR.exists():
        print(f"Error: i18n folder not found: {I18N_DIR}")
        return

    ref_path = I18N_DIR / REFERENCE_FILE
    if not ref_path.exists():
        print(f"Error: reference file not found: {ref_path}")
        return

    try:
        ref_json = load_json(ref_path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Error while loading reference file {REFERENCE_FILE}: {error}")
        return

    reference_keys = flatten_keys(ref_json)
    total_reference_keys = len(reference_keys)

    if total_reference_keys == 0:
        print(f"Error: reference file {REFERENCE_FILE} has no keys to compare.")
        return

    missing_by_file: dict[str, list[str]] = {}
    completion_by_file: dict[str, tuple[int, int, float]] = {}

    for lang_file in iter_language_files(I18N_DIR):
        try:
            lang_json = load_json(lang_file)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            print(f"Warning: skip {lang_file.name} ({error})")
            continue

        language_keys = flatten_keys(lang_json)
        missing_keys = sorted(reference_keys - language_keys)
        translated_count = total_reference_keys - len(missing_keys)
        completion = (translated_count / total_reference_keys) * 100.0

        missing_by_file[lang_file.name] = missing_keys
        completion_by_file[lang_file.name] = (
            translated_count,
            total_reference_keys,
            completion,
        )

    if not completion_by_file:
        print("No valid translation files found.")
        return

    print("=" * 72)
    print("TRANSLATION COMPLETENESS SUMMARY")
    print("=" * 72)
    print(f"Reference file: {REFERENCE_FILE}")
    print(f"Reference keys: {total_reference_keys}")
    print("\nCompletion by language:")
    for filename in sorted(completion_by_file):
        translated, total, completion = completion_by_file[filename]
        print(f"- {filename:<12} : {completion:6.2f}% ({translated}/{total})")

    print("\n" + "=" * 72)
    print("MISSING KEYS BY FILE")
    print("=" * 72)
    for filename in sorted(missing_by_file):
        missing_keys = missing_by_file[filename]
        print(f"\n[{filename}] Missing keys: {len(missing_keys)}")
        if not missing_keys:
            print("  - None")
            continue
        for key in missing_keys:
            print(f"  - {key}")

    print("\n" + "=" * 72)
    print("MISSING KEYS COUNT BY LANGUAGE")
    print("=" * 72)
    for filename in sorted(missing_by_file):
        print(f"- {filename:<12} : {len(missing_by_file[filename])}")


if __name__ == "__main__":
    main()
