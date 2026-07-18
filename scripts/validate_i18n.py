"""
Validate i18n consistency across backend, frontend, and webmanifests.

Checks (all are hard failures):
  1. Every language in static/i18n/*.json is declared in _TRANSLATION_FILENAMES
     in backend/utils/i18n_utils.py.
  2. Every non-English language has a static/manifest.<lang>.webmanifest file
     AND the language code appears in the 'supported' array of templates/index.html.
  3. Every language has an <option value="<lang>"> entry in the language selector
     in templates/index.html.
  4. No translation key present in en.json is missing from another language file.
  5. No JSON file contains duplicate object keys.
  6. No JSON file contains inline object values (object opened and closed on one line).
  7. No translated file contains keys not present in en.json (orphan/extra keys).
  8. No translated leaf value has a different type than the corresponding en.json value.
  9. No translation value contains HTML entities (e.g. &amp; &lt; &gt; &quot; &#…;).

Usage:
    python scripts/validate_i18n.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "static" / "i18n"
BACKEND_FILE = ROOT / "backend" / "utils" / "i18n_utils.py"
INDEX_HTML = ROOT / "templates" / "index.html"
STATIC_DIR = ROOT / "static"
REFERENCE_LANG = "en"
MAX_SNIPPET_LENGTH = 100
_ELLIPSIS = "..."
_TRUNCATED_SNIPPET_LENGTH = MAX_SNIPPET_LENGTH - len(_ELLIPSIS)

_HTML_ENTITY_RE = re.compile(r"&(?:[a-zA-Z]{2,10}|#\d{1,7}|#x[0-9a-fA-F]{1,6});")
_LANGUAGE_CODE_PATTERN = r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*"


def flatten_keys(data: Any, parent: str = "") -> set[str]:
    """Return flattened dot-notation keys from a nested JSON structure."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{parent}.{key}" if parent else str(key)
            if isinstance(value, (dict, list)):
                keys.update(flatten_keys(value, path))
            else:
                keys.add(path)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{parent}[{index}]" if parent else f"[{index}]"
            if isinstance(value, (dict, list)):
                keys.update(flatten_keys(value, path))
            else:
                keys.add(path)
    return keys


def get_leaf_types(data: Any, parent: str = "") -> dict[str, str]:
    """Return {dot-notation-path: type_name} for every leaf node."""
    result: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{parent}.{key}" if parent else str(key)
            if isinstance(value, (dict, list)):
                result.update(get_leaf_types(value, path))
            else:
                result[path] = type(value).__name__
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{parent}[{index}]" if parent else f"[{index}]"
            if isinstance(value, (dict, list)):
                result.update(get_leaf_types(value, path))
            else:
                result[path] = type(value).__name__
    return result


def find_duplicate_keys(text: str) -> list[str]:
    """Return keys that appear more than once in any JSON object within the text."""
    duplicates: list[str] = []

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen[key] = value
        return seen

    try:
        json.loads(text, object_pairs_hook=object_pairs_hook)
    except json.JSONDecodeError:
        pass  # parse errors are reported separately
    return duplicates


def find_html_entities(data: Any, parent: str = "") -> list[str]:
    """Return dot-notation paths of leaf strings that contain HTML entities."""
    hits: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{parent}.{key}" if parent else str(key)
            hits.extend(find_html_entities(value, path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{parent}[{index}]" if parent else f"[{index}]"
            hits.extend(find_html_entities(value, path))
    elif isinstance(data, str) and _HTML_ENTITY_RE.search(data):
        hits.append(parent)
    return hits


def find_inline_objects(text: str) -> list[tuple[int, str]]:
    """Return (line_number, stripped_line) for lines that contain inline object values."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        in_string = False
        escape = False
        i = 0
        while i < len(line):
            ch = line[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == '"':
                in_string = True
                i += 1
                continue
            if ch == ":":
                j = i + 1
                while j < len(line) and line[j].isspace():
                    j += 1
                if j < len(line) and line[j] == "{":
                    # Verify the object is also closed on the same line
                    depth = 1
                    k = j + 1
                    in_str = False
                    esc = False
                    while k < len(line) and depth > 0:
                        c = line[k]
                        if in_str:
                            if esc:
                                esc = False
                            elif c == "\\":
                                esc = True
                            elif c == '"':
                                in_str = False
                        elif c == '"':
                            in_str = True
                        elif c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                        k += 1
                    if depth == 0:
                        hits.append((lineno, line.strip()))
                    break
            i += 1
    return hits


def parse_backend_languages(source: str) -> set[str]:
    """Extract declared language codes from _TRANSLATION_FILENAMES dict."""
    match = re.search(
        r"_TRANSLATION_FILENAMES\s*=\s*\{([^}]+)\}", source, re.DOTALL
    )
    if not match:
        return set()
    return set(
        re.findall(rf"['\"]({_LANGUAGE_CODE_PATTERN})['\"]\s*:", match.group(1))
    )


def parse_html_supported_langs(html: str) -> set[str]:
    """Extract language codes from the 'var supported = [...]' array in index.html."""
    match = re.search(r"var\s+supported\s*=\s*\[([^\]]+)\]", html)
    if not match:
        return set()
    return set(re.findall(rf"['\"]({_LANGUAGE_CODE_PATTERN})['\"]", match.group(1)))


def parse_html_selector_langs(html: str) -> set[str]:
    """Extract language <option> values from the language selector in index.html."""
    return set(re.findall(rf"<option[^>]*value=['\"]({_LANGUAGE_CODE_PATTERN})['\"]", html))


def main() -> int:
    errors: list[str] = []

    # --- Collect i18n languages from JSON files ---
    json_languages = {p.stem for p in I18N_DIR.glob("*.json")}
    if not json_languages:
        print("ERROR: No i18n JSON files found in static/i18n/.")
        return 1

    # --- Parse backend/utils/i18n_utils.py ---
    if not BACKEND_FILE.exists():
        errors.append(f"Backend file not found: {BACKEND_FILE}")
        backend_langs: set[str] = set()
    else:
        backend_langs = parse_backend_languages(BACKEND_FILE.read_text(encoding="utf-8"))
        if not backend_langs:
            errors.append(
                f"Could not parse _TRANSLATION_FILENAMES from {BACKEND_FILE.name}"
            )

    # --- Parse templates/index.html ---
    if not INDEX_HTML.exists():
        errors.append(f"Template not found: {INDEX_HTML}")
        html_supported_langs: set[str] = set()
        html_selector_langs: set[str] = set()
    else:
        html_content = INDEX_HTML.read_text(encoding="utf-8")
        html_supported_langs = parse_html_supported_langs(html_content)
        html_selector_langs = parse_html_selector_langs(html_content)
        if not html_supported_langs:
            errors.append(
                "Could not find 'var supported = [...]' for webmanifests in index.html"
            )

    # --- Load reference translation keys and types ---
    ref_path = I18N_DIR / f"{REFERENCE_LANG}.json"
    if not ref_path.exists():
        errors.append(f"Reference translation file not found: {ref_path}")
        ref_keys: set[str] = set()
        ref_types: dict[str, str] = {}
    else:
        try:
            ref_data = json.loads(ref_path.read_text(encoding="utf-8"))
            ref_keys = flatten_keys(ref_data)
            ref_types = get_leaf_types(ref_data)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"[{REFERENCE_LANG}] Could not load reference file: {exc}")
            ref_keys = set()
            ref_types = {}

    # --- Per-language checks ---
    for lang in sorted(json_languages):
        # Check 1: backend declaration
        if backend_langs and lang not in backend_langs:
            errors.append(
                f"[{lang}] Not declared in _TRANSLATION_FILENAMES in {BACKEND_FILE.name}"
            )

        # Check 3: language selector option in index.html
        if html_selector_langs and lang not in html_selector_langs:
            errors.append(
                f"[{lang}] Missing <option value=\"{lang}\"> in language selector in index.html"
            )

        # Check 2 (non-reference languages only): webmanifest file + html supported array
        if lang != REFERENCE_LANG:
            webmanifest = STATIC_DIR / f"manifest.{lang}.webmanifest"
            if not webmanifest.exists():
                errors.append(
                    f"[{lang}] Webmanifest file not found: static/manifest.{lang}.webmanifest"
                )

            if html_supported_langs and lang not in html_supported_langs:
                errors.append(
                    f"[{lang}] Not listed in 'var supported = [...]' for webmanifests in index.html"
                )

        # Load raw text once for checks 5, 6, 9 (and 4/7/8 for non-reference)
        lang_path = I18N_DIR / f"{lang}.json"
        try:
            raw = lang_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"[{lang}] Could not read file: {exc}")
            continue

        # Check 5: duplicate object keys
        for dup in find_duplicate_keys(raw):
            errors.append(f"[{lang}] Duplicate key: '{dup}'")

        # Check 6: inline object values
        for lineno, snippet in find_inline_objects(raw):
            display = snippet if len(snippet) <= MAX_SNIPPET_LENGTH else snippet[:_TRUNCATED_SNIPPET_LENGTH] + _ELLIPSIS
            errors.append(f"[{lang}] Inline object on line {lineno}: {display}")

        # Check 9: HTML entities in string values (applies to all languages)
        try:
            lang_json_for_entities = json.loads(raw)
            for key in find_html_entities(lang_json_for_entities):
                errors.append(f"[{lang}] HTML entity in value at '{key}' (use plain Unicode characters instead)")
        except json.JSONDecodeError:
            pass  # parse errors are reported in checks 4/7/8

        # Checks 4, 7, 8: key completeness, extra keys, type mismatches (skip reference)
        if lang != REFERENCE_LANG and ref_keys:
            try:
                lang_json = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"[{lang}] Could not parse translation file: {exc}")
                continue
            lang_keys = flatten_keys(lang_json)

            # Check 4: missing keys
            for key in sorted(ref_keys - lang_keys):
                errors.append(f"[{lang}] Missing translation key: '{key}'")

            # Check 7: extra/orphan keys
            for key in sorted(lang_keys - ref_keys):
                errors.append(f"[{lang}] Extra key not in reference: '{key}'")

            # Check 8: leaf value type mismatches
            if ref_types:
                lang_types = get_leaf_types(lang_json)
                for key in sorted(set(ref_types) & set(lang_types)):
                    if ref_types[key] != lang_types[key]:
                        errors.append(
                            f"[{lang}] Type mismatch at '{key}':"
                            f" expected {ref_types[key]}, got {lang_types[key]}"
                        )

    # --- Report ---
    if errors:
        print(f"i18n validation FAILED - {len(errors)} error(s) found:\n")
        for err in errors:
            print(f" X {err}")
        print()
        return 1

    print(
        f"i18n validation OK - {len(json_languages)} language(s): "
        f"{sorted(json_languages)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
