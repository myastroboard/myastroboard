"""Translate i18n JSON values while preserving placeholders and astronomy terms.

Usage:
  D:/Code/myastroboard/.venv/Scripts/python.exe scripts/translate_i18n_values.py --lang es
  D:/Code/myastroboard/.venv/Scripts/python.exe scripts/translate_i18n_values.py --lang de
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import translators as ts

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "static" / "i18n"
SOURCE_FILE = I18N_DIR / "en.json"

# Keep domain-specific terms stable across locales.
PROTECTED_TERMS = [
    "MyAstroBoard",
    "Astrodex",
    "SkyTonight",
    "ISS",
    "NOAA",
    "Kp",
    "Pickering",
    "FOV",
    "YAML",
    "JSON",
    "API",
    "CPU",
    "RAM",
    "GHz",
    "hPa",
    "arcsec",
    "HMS/DMS",
    "CMOS",
    "CCD",
    "LRGB",
    "RGB",
    "H-Alpha",
    "OIII",
    "SII",
    "UHC",
    "AU",
]

PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")


def protect_segments(text: str) -> tuple[str, dict[str, str]]:
    """Replace placeholders and protected terms with sentinel tokens."""
    mapping: dict[str, str] = {}
    counter = 0

    def repl_placeholder(match: re.Match[str]) -> str:
        nonlocal counter
        token = f"__PH_{counter}__"
        mapping[token] = match.group(0)
        counter += 1
        return token

    protected = PLACEHOLDER_RE.sub(repl_placeholder, text)

    # Sort longest first to avoid partial replacement collisions.
    for term in sorted(PROTECTED_TERMS, key=len, reverse=True):
        escaped = re.escape(term)
        pattern = re.compile(escaped)

        def repl_term(match: re.Match[str]) -> str:
            nonlocal counter
            token = f"__TM_{counter}__"
            mapping[token] = match.group(0)
            counter += 1
            return token

        protected = pattern.sub(repl_term, protected)

    return protected, mapping


def restore_segments(text: str, mapping: dict[str, str]) -> str:
    restored = text
    for token, original in mapping.items():
        restored = restored.replace(token, original)
    return restored


def needs_translation(value: str, target_lang: str) -> bool:
    """Skip values that are numeric-like, symbols, or intentionally language-neutral."""
    if not value.strip():
        return False
    # Keep cardinal abbreviations and similar short label tokens as-is.
    if re.fullmatch(r"[A-Z0-9+*/'\-_. ]{1,8}", value.strip()):
        return False
    # Keep units and symbol-only values.
    if re.fullmatch(r"[%°µA-Za-z/]+", value.strip()) and value.strip() in {
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
        "d",
        "h",
        "min",
        "s",
        "%",
        "km",
        "m",
        "mm",
        "nm",
        "kg",
        "hPa",
        "GHz",
        "N/A",
        "arcsec/pixel",
        "AU",
    }:
        return False
    # Avoid translating known celestial object names in planets/constellations style values.
    if value in {
        "Mercury",
        "Venus",
        "Earth",
        "Mars",
        "Jupiter",
        "Saturn",
        "Uranus",
        "Neptune",
        "Pluto",
        "Andromeda",
        "Antlia",
        "Apus",
        "Aquarius",
        "Aquila",
        "Ara",
        "Aries",
        "Auriga",
        "Bootes",
        "Caelum",
        "Camelopardalis",
        "Cancer",
        "Canes Venatici",
        "Canis Major",
        "Canis Minor",
        "Capricornus",
        "Carina",
        "Cassiopeia",
        "Centaurus",
        "Cepheus",
        "Cetus",
        "Chamaeleon",
        "Circinus",
        "Columba",
        "Coma Berenices",
        "Corona Australis",
        "Corona Borealis",
        "Corvus",
        "Crater",
        "Crux",
        "Cygnus",
        "Delphinus",
        "Dorado",
        "Draco",
        "Equuleus",
        "Eridanus",
        "Fornax",
        "Gemini",
        "Grus",
        "Hercules",
        "Horologium",
        "Hydra",
        "Hydrus",
        "Indus",
        "Lacerta",
        "Leo",
        "Leo Minor",
        "Lepus",
        "Libra",
        "Lupus",
        "Lynx",
        "Lyra",
        "Mensa",
        "Microscopium",
        "Monoceros",
        "Musca",
        "Norma",
        "Octans",
        "Ophiuchus",
        "Orion",
        "Pavo",
        "Pegasus",
        "Perseus",
        "Phoenix",
        "Pictor",
        "Pisces",
        "Piscis Austrinus",
        "Puppis",
        "Pyxis",
        "Reticulum",
        "Sagitta",
        "Sagittarius",
        "Scorpius",
        "Sculptor",
        "Scutum",
        "Serpens",
        "Serpens Caput",
        "Serpens Cauda",
        "Sextans",
        "Taurus",
        "Telescopium",
        "Triangulum",
        "Triangulum Australe",
        "Tucana",
        "Ursa Major",
        "Ursa Minor",
        "Vela",
        "Virgo",
        "Volans",
        "Vulpecula",
    }:
        return False
    return True


def translate_value(value: str, target_lang: str) -> str:
    if not needs_translation(value, target_lang):
        return value

    protected, mapping = protect_segments(value)
    translated = ts.translate_text(protected, translator="google", from_language="en", to_language=target_lang)
    assert isinstance(translated, str)
    translated = restore_segments(translated, mapping)

    # Cleanup occasional spacing issues around placeholders.
    translated = re.sub(r"\s+([:;,.!?])", r"\1", translated)
    return translated


def translate_node(node: Any, target_lang: str, stats: dict[str, int]) -> Any:
    if isinstance(node, dict):
        return {k: translate_node(v, target_lang, stats) for k, v in node.items()}
    if isinstance(node, list):
        return [translate_node(v, target_lang, stats) for v in node]
    if isinstance(node, str):
        try:
            translated = translate_value(node, target_lang)
            if translated != node:
                stats["translated"] += 1
            else:
                stats["kept"] += 1
            # Gentle throttle for API reliability.
            time.sleep(0.03)
            return translated
        except Exception:
            stats["failed"] += 1
            return node
    return node


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["es", "de", "it", "pt"], required=True)
    args = parser.parse_args()

    with SOURCE_FILE.open("r", encoding="utf-8") as f:
        source = json.load(f)

    stats = {"translated": 0, "kept": 0, "failed": 0}
    translated = translate_node(source, args.lang, stats)

    target_path = I18N_DIR / f"{args.lang}.json"
    with target_path.open("w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {target_path}")
    print(f"stats: translated={stats['translated']} kept={stats['kept']} failed={stats['failed']}")


if __name__ == "__main__":
    main()
