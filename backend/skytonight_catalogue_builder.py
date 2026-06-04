"""SkyTonight target dataset builder for deep-sky catalogues."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from logging_config import get_logger
from skytonight_bodies import build_body_targets
from skytonight_comets import build_comet_targets
from skytonight_models import SkyTonightCoordinates, SkyTonightTarget
from skytonight_targets import (
    normalize_catalogue_name,
    normalize_object_name,
    save_targets_dataset,
    choose_preferred_catalogue_name,
)

logger = get_logger(__name__)

_CATALOGUES_DIR = os.path.join(os.path.dirname(__file__), 'catalogues')

DEFAULT_CALDWELL_MAP: Dict[str, str] = {}
IDENTIFIER_PATTERN = re.compile(r'\b(M\s*\d+|NGC\s*\d+|IC\s*\d+)\b', re.IGNORECASE)

# ── Herschel 400 - Astronomical League program (NGC objects only) ─────────────
# Source: https://www.astroleague.org/herschel-400-observing-program/
_HERSCHEL400_NGC: frozenset = frozenset(
    {
        40,
        129,
        136,
        157,
        185,
        188,
        205,
        225,
        246,
        247,
        253,
        278,
        288,
        300,
        404,
        436,
        457,
        524,
        559,
        584,
        596,
        598,
        613,
        615,
        628,
        636,
        650,
        651,
        654,
        659,
        663,
        720,
        752,
        772,
        779,
        869,
        884,
        891,
        908,
        936,
        1003,
        1023,
        1027,
        1055,
        1084,
        1245,
        1300,
        1342,
        1444,
        1502,
        1513,
        1528,
        1545,
        1647,
        1664,
        1788,
        1817,
        1857,
        1907,
        1931,
        1961,
        2022,
        2024,
        2126,
        2129,
        2158,
        2169,
        2185,
        2186,
        2194,
        2215,
        2232,
        2244,
        2245,
        2251,
        2261,
        2266,
        2281,
        2286,
        2304,
        2311,
        2324,
        2335,
        2343,
        2353,
        2354,
        2355,
        2360,
        2362,
        2371,
        2372,
        2392,
        2395,
        2403,
        2419,
        2420,
        2421,
        2422,
        2423,
        2438,
        2440,
        2479,
        2489,
        2506,
        2509,
        2527,
        2539,
        2548,
        2571,
        2613,
        2627,
        2655,
        2681,
        2683,
        2742,
        2768,
        2775,
        2782,
        2787,
        2811,
        2841,
        2859,
        2903,
        2950,
        2964,
        2974,
        2976,
        2985,
        3034,
        3077,
        3079,
        3115,
        3147,
        3166,
        3169,
        3184,
        3193,
        3198,
        3227,
        3242,
        3245,
        3277,
        3294,
        3310,
        3344,
        3377,
        3379,
        3384,
        3395,
        3412,
        3414,
        3432,
        3489,
        3504,
        3521,
        3593,
        3607,
        3608,
        3610,
        3613,
        3619,
        3621,
        3626,
        3628,
        3631,
        3640,
        3655,
        3665,
        3675,
        3686,
        3705,
        3726,
        3729,
        3810,
        3813,
        3877,
        3893,
        3898,
        3938,
        3941,
        3945,
        3949,
        3953,
        3962,
        3982,
        3992,
        3998,
        4026,
        4027,
        4030,
        4036,
        4038,
        4039,
        4041,
        4051,
        4085,
        4088,
        4102,
        4111,
        4143,
        4147,
        4150,
        4151,
        4157,
        4179,
        4203,
        4214,
        4216,
        4245,
        4251,
        4258,
        4261,
        4273,
        4274,
        4278,
        4281,
        4293,
        4294,
        4298,
        4302,
        4303,
        4314,
        4346,
        4350,
        4361,
        4365,
        4371,
        4378,
        4380,
        4387,
        4388,
        4394,
        4395,
        4414,
        4419,
        4429,
        4435,
        4436,
        4438,
        4442,
        4448,
        4449,
        4450,
        4460,
        4473,
        4477,
        4478,
        4485,
        4490,
        4494,
        4526,
        4527,
        4531,
        4536,
        4546,
        4550,
        4559,
        4564,
        4565,
        4570,
        4596,
        4618,
        4631,
        4636,
        4643,
        4654,
        4656,
        4660,
        4665,
        4666,
        4689,
        4697,
        4698,
        4699,
        4710,
        4725,
        4747,
        4753,
        4754,
        4762,
        4772,
        4781,
        4800,
        4845,
        4856,
        4866,
        4900,
        4958,
        4995,
        5005,
        5033,
        5054,
        5195,
        5248,
        5273,
        5322,
        5363,
        5364,
        5371,
        5377,
        5389,
        5395,
        5422,
        5448,
        5473,
        5474,
        5557,
        5566,
        5576,
        5631,
        5638,
        5645,
        5676,
        5689,
        5694,
        5746,
        5775,
        5806,
        5813,
        5831,
        5838,
        5846,
        5854,
        5866,
        5907,
        5965,
        6015,
        6118,
        6207,
        6217,
        6229,
        6503,
        6543,
        6654,
        6742,
        6946,
        6951,
        7000,
        7008,
        7009,
        7044,
        7062,
        7086,
        7128,
        7139,
        7142,
        7160,
        7209,
        7217,
        7243,
        7296,
        7331,
        7380,
        7448,
        7479,
        7510,
        7606,
        7619,
        7626,
        7662,
        7686,
        7723,
        7727,
        7789,
        7790,
    }
)


@dataclass(frozen=True)
class PyOngcRow:
    """Intermediate representation used by the dataset builder."""

    name: str
    object_type: str
    constellation: str
    ra_hours: Optional[float]
    dec_degrees: Optional[float]
    magnitude: Optional[float]
    size_arcmin: Optional[float]
    messier: Optional[str]
    ngc_names: List[str]
    ic_names: List[str]
    common_names: List[str]
    other_identifiers: List[str]


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _coerce_identifier_list(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        return [values] if values.strip() else []

    coerced: List[str] = []
    for value in values:
        text = str(value or '').strip()
        if text:
            coerced.append(text)
    return coerced


def _normalize_identifier(identifier: str) -> str:
    text = str(identifier or '').strip()
    if not text:
        return ''
    upper = text.upper().replace('  ', ' ')
    if upper.startswith('M') and upper[1:].isdigit():
        return f'M {int(upper[1:])}'
    if upper.startswith('NGC'):
        suffix = upper[3:].strip()
        return f'NGC {suffix}' if suffix else 'NGC'
    if upper.startswith('IC'):
        suffix = upper[2:].strip()
        return f'IC {suffix}' if suffix else 'IC'
    if upper.startswith('C') and upper[1:].strip().isdigit():
        return f'C {int(upper[1:].strip())}'
    return text


def _collect_catalogue_names(row: PyOngcRow, caldwell_map: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    names: Dict[str, str] = {}

    if row.messier:
        names['Messier'] = _normalize_identifier(row.messier)

    if row.ngc_names:
        names['OpenNGC'] = _normalize_identifier(row.ngc_names[0])

    if row.ic_names:
        if 'OpenNGC' not in names:
            names['OpenNGC'] = _normalize_identifier(row.ic_names[0])
        names['OpenIC'] = _normalize_identifier(row.ic_names[0])

    # PyOngc returns identifiers[1]/[2] as cross-references only - they are None
    # for the primary NGC/IC object itself.  Derive OpenNGC / OpenIC from the
    # canonical row name when the cross-reference columns were empty.
    norm_primary = _normalize_identifier(row.name)
    if norm_primary.startswith('NGC ') and 'OpenNGC' not in names:
        names['OpenNGC'] = norm_primary
    elif norm_primary.startswith('IC ') and 'OpenIC' not in names:
        names['OpenIC'] = norm_primary
        if 'OpenNGC' not in names:
            names['OpenNGC'] = norm_primary

    # Popular / common name (first entry from PyOngc common-names list)
    if row.common_names:
        first_common = str(row.common_names[0]).strip()
        if first_common:
            names['CommonName'] = first_common

    # First: extract Caldwell identifier directly from PyOngc other_identifiers
    # (PyOngc returns entries like "C 1", "C 42" in the other_identifiers field)
    for identifier in row.other_identifiers:
        if re.match(r'^C \d+$', identifier):
            names['Caldwell'] = identifier
            break

    # Fallback: use caldwell_map lookup (for custom maps or testing)
    if 'Caldwell' not in names:
        caldwell_catalogue = caldwell_map or DEFAULT_CALDWELL_MAP
        for alias_name in list(names.values()) + [row.name]:
            caldwell_name = caldwell_catalogue.get(normalize_object_name(alias_name), '')
            if caldwell_name:
                names['Caldwell'] = _normalize_identifier(caldwell_name)
                break

    return names


def _build_aliases(row: PyOngcRow, catalogue_names: Dict[str, str]) -> List[str]:
    aliases = {
        str(row.name or '').strip(),
        *catalogue_names.values(),
        *_coerce_identifier_list(row.common_names),
        *_coerce_identifier_list(row.other_identifiers),
        *_coerce_identifier_list(row.ngc_names),
        *_coerce_identifier_list(row.ic_names),
    }
    aliases.discard('')
    return sorted(aliases)


def _canonical_key(catalogue_names: Dict[str, str], fallback_name: str) -> Tuple[str, str]:
    if 'OpenNGC' in catalogue_names:
        return ('OpenNGC', normalize_object_name(catalogue_names['OpenNGC']))
    if 'Messier' in catalogue_names:
        return ('Messier', normalize_object_name(catalogue_names['Messier']))
    if 'OpenIC' in catalogue_names:
        return ('OpenIC', normalize_object_name(catalogue_names['OpenIC']))
    if 'Caldwell' in catalogue_names:
        return ('Caldwell', normalize_object_name(catalogue_names['Caldwell']))
    return ('Alias', normalize_object_name(fallback_name))


def _target_id_from_key(canonical_catalogue: str, canonical_name: str) -> str:
    return f"dso-{normalize_catalogue_name(canonical_catalogue).lower()}-{canonical_name}"


def _merge_target(existing: SkyTonightTarget, incoming: SkyTonightTarget) -> SkyTonightTarget:
    catalogue_names = dict(existing.catalogue_names)
    # Merge incoming catalogue entries without overwriting keys already present
    # (keeps the first-seen CommonName, Messier, etc. rather than the last).
    for k, v in incoming.catalogue_names.items():
        if k not in catalogue_names or not catalogue_names[k]:
            catalogue_names[k] = v

    aliases = sorted({*existing.aliases, *incoming.aliases})
    source_catalogues = sorted({*existing.source_catalogues, *incoming.source_catalogues})

    magnitude = existing.magnitude if existing.magnitude is not None else incoming.magnitude
    size_arcmin = existing.size_arcmin if existing.size_arcmin is not None else incoming.size_arcmin
    coordinates = existing.coordinates or incoming.coordinates
    constellation = existing.constellation or incoming.constellation
    preferred_name = existing.preferred_name or incoming.preferred_name
    object_type = existing.object_type or incoming.object_type

    metadata = dict(existing.metadata)
    metadata.update(incoming.metadata)

    return SkyTonightTarget(
        target_id=existing.target_id,
        category=existing.category,
        object_type=object_type,
        preferred_name=preferred_name,
        catalogue_names=catalogue_names,
        aliases=aliases,
        constellation=constellation,
        magnitude=magnitude,
        size_arcmin=size_arcmin,
        coordinates=coordinates,
        source_catalogues=source_catalogues,
        translation_key=existing.translation_key or incoming.translation_key,
        metadata=metadata,
    )


def _load_json_catalogue(filename: str) -> Any:
    """Load a catalogue JSON file from backend/catalogues/ and return its decoded content."""
    filepath = os.path.join(_CATALOGUES_DIR, filename)
    if not os.path.exists(filepath):
        logger.warning(f'Catalogue file not found: {filepath}')
        return None
    try:
        with open(filepath, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f'Failed to load catalogue file {filename}: {e}')
        return None


def _ngc_ic_match_key(name: str) -> str:
    """Normalise an NGC/IC name to a key that matches PyOngc's zero-padded output.

    PyOngc stores names as 'NGC0891' internally; _normalize_identifier converts
    that to 'NGC 0891', so normalize_object_name gives 'ngc0891'.  A cross-ref
    JSON entry like 'NGC 891' would produce key 'ngc891', which would never
    match.  This helper pads the number to 4 digits before normalising, so both
    sides of the lookup agree on the key format.
    """
    m = re.match(r'^(NGC|IC)\s*(\d+)\s*$', name.strip(), re.IGNORECASE)
    if m:
        return normalize_object_name(f"{m.group(1).upper()} {int(m.group(2)):04d}")
    return normalize_object_name(name.strip())


def _build_cross_ref_map() -> Dict[str, Dict[str, str]]:
    """Build a unified cross-reference map: _ngc_ic_match_key(ngc_name) → {catalogue: name}.

    Merges Herschel 400 (static), Pensack 500, LBN, GaryImm, and Arp (all JSON).
    The result is passed to _apply_cross_refs() after the main PyOngc build.
    """
    cross_refs: Dict[str, Dict[str, str]] = {}

    # ── Herschel 400 ─────────────────────────────────────────────────────────
    for ngc_num in _HERSCHEL400_NGC:
        ngc_name = f'NGC {ngc_num}'
        key = normalize_object_name(f'NGC {ngc_num:04d}')
        cross_refs.setdefault(key, {})['Herschel400'] = ngc_name

    # ── Pensack 500 ───────────────────────────────────────────────────────────
    pensack_data = _load_json_catalogue('pensack500.json')
    if isinstance(pensack_data, list):
        for raw_name in pensack_data:
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            key = _ngc_ic_match_key(raw_name.strip())
            if key:
                cross_refs.setdefault(key, {})['Pensack500'] = raw_name.strip()
    else:
        logger.warning('pensack500.json missing or invalid - Pensack 500 catalogue not applied')

    # ── LBN cross-refs ────────────────────────────────────────────────────────
    lbn_data = _load_json_catalogue('lbn.json')
    if isinstance(lbn_data, dict):
        for raw_ngc_name, lbn_name in lbn_data.items():
            if not raw_ngc_name or not lbn_name:
                continue
            key = _ngc_ic_match_key(str(raw_ngc_name).strip())
            if key:
                cross_refs.setdefault(key, {})['LBN'] = str(lbn_name).strip()
    else:
        logger.warning('lbn.json missing or invalid - LBN cross-references not applied')

    # ── GaryImm cross-refs ────────────────────────────────────────────────────
    garyimm_data = _load_json_catalogue('garyimm_crossrefs.json')
    if isinstance(garyimm_data, list):
        for raw_name in garyimm_data:
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            key = _ngc_ic_match_key(raw_name.strip())
            if key:
                cross_refs.setdefault(key, {})['GaryImm'] = raw_name.strip()
    else:
        logger.warning('garyimm_crossrefs.json missing or invalid - GaryImm cross-refs not applied')

    # ── Arp cross-refs ────────────────────────────────────────────────────────
    arp_data = _load_json_catalogue('arp.json')
    if isinstance(arp_data, dict):
        for raw_ngc_name, arp_name in arp_data.items():
            if not raw_ngc_name or not arp_name:
                continue
            key = _ngc_ic_match_key(str(raw_ngc_name).strip())
            if key:
                cross_refs.setdefault(key, {})['Arp'] = str(arp_name).strip()
    else:
        logger.warning('arp.json missing or invalid - Arp cross-references not applied')

    total_keys = len(cross_refs)
    catalogues_applied = sorted({cat for refs in cross_refs.values() for cat in refs})
    logger.debug(f'Cross-ref map built: {total_keys} NGC/IC keys, catalogues: {catalogues_applied}')
    return cross_refs


def _apply_cross_refs(
    targets: List[SkyTonightTarget],
    cross_refs: Dict[str, Dict[str, str]],
) -> List[SkyTonightTarget]:
    """Inject cross-catalogue membership (Herschel400, Pensack500, LBN, GaryImm, Arp) into targets."""
    if not cross_refs:
        return targets

    enriched = 0
    result: List[SkyTonightTarget] = []
    for target in targets:
        # Lookup by all NGC/IC names this target carries.
        # Use _ngc_ic_match_key so that PyOngc's zero-padded names (e.g. "NGC 0891")
        # produce the same key as the JSON entries (e.g. "NGC 891" → "ngc0891").
        extra: Dict[str, str] = {}
        for cat_key in ('OpenNGC', 'OpenIC'):
            val = target.catalogue_names.get(cat_key, '')
            if val:
                extra.update(cross_refs.get(_ngc_ic_match_key(val), {}))

        if extra:
            new_catalogue_names = {**target.catalogue_names, **extra}
            new_source_catalogues = sorted({*target.source_catalogues, *extra.keys()})
            new_aliases = sorted({*target.aliases, *extra.values()})
            target = SkyTonightTarget(
                target_id=target.target_id,
                category=target.category,
                object_type=target.object_type,
                preferred_name=target.preferred_name,
                catalogue_names=new_catalogue_names,
                aliases=new_aliases,
                constellation=target.constellation,
                magnitude=target.magnitude,
                size_arcmin=target.size_arcmin,
                coordinates=target.coordinates,
                source_catalogues=new_source_catalogues,
                translation_key=target.translation_key,
                metadata=target.metadata,
            )
            enriched += 1

        result.append(target)

    logger.debug(f'Cross-ref injection: {enriched}/{len(result)} targets enriched')
    return result


def build_targets_from_rows(
    rows: Iterable[PyOngcRow], caldwell_map: Optional[Dict[str, str]] = None
) -> List[SkyTonightTarget]:
    """Normalize PyOngc rows into deduplicated SkyTonight targets."""
    targets_by_key: Dict[Tuple[str, str], SkyTonightTarget] = {}

    for row in rows:
        if row.ra_hours is None or row.dec_degrees is None:
            continue
        if str(row.object_type or '').strip().lower().startswith('duplicated'):
            continue

        catalogue_names = _collect_catalogue_names(row, caldwell_map=caldwell_map)
        aliases = _build_aliases(row, catalogue_names)
        canonical_catalogue, canonical_name = _canonical_key(catalogue_names, row.name)
        if not canonical_name:
            continue

        preferred_name = choose_preferred_catalogue_name(catalogue_names) or row.name
        source_catalogues = sorted({canonical_catalogue, *catalogue_names.keys()})
        target = SkyTonightTarget(
            target_id=_target_id_from_key(canonical_catalogue, canonical_name),
            category='deep_sky',
            object_type=str(row.object_type or '').strip() or 'Unknown',
            preferred_name=preferred_name,
            catalogue_names=catalogue_names,
            aliases=aliases,
            constellation=str(row.constellation or '').strip(),
            magnitude=row.magnitude,
            size_arcmin=row.size_arcmin,
            coordinates=SkyTonightCoordinates(ra_hours=float(row.ra_hours), dec_degrees=float(row.dec_degrees)),
            source_catalogues=source_catalogues,
            translation_key=f"skytonight.type_{normalize_object_name(row.object_type) or 'unknown'}",
            metadata={'source': 'pyongc'},
        )

        key = (canonical_catalogue, canonical_name)
        if key in targets_by_key:
            targets_by_key[key] = _merge_target(targets_by_key[key], target)
        else:
            targets_by_key[key] = target

    return sorted(targets_by_key.values(), key=lambda item: item.preferred_name.lower())


def _load_pyongc_rows() -> List[PyOngcRow]:
    """Load deep-sky objects from PyOngc when available."""
    try:
        from pyongc import ongc  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError('PyOngc is required to build the SkyTonight deep-sky dataset') from error

    rows: List[PyOngcRow] = []
    for dso in ongc.listObjects():
        coords = getattr(dso, 'coords', None)
        if coords is None:
            continue

        try:
            ra_hours = float(coords[0][0] + (coords[0][1] / 60.0) + (coords[0][2] / 3600.0))
            dec_sign = -1.0 if float(coords[1][0]) < 0 else 1.0
            dec_abs = abs(float(coords[1][0])) + (float(coords[1][1]) / 60.0) + (float(coords[1][2]) / 3600.0)
            dec_degrees = dec_sign * dec_abs
        except (TypeError, ValueError, IndexError):
            continue

        dimensions = getattr(dso, 'dimensions', (None, None, None))
        magnitudes = getattr(dso, 'magnitudes', (None, None, None, None, None))
        identifiers = getattr(dso, 'identifiers', (None, None, None, None, None))

        rows.append(
            PyOngcRow(
                name=str(getattr(dso, 'name', '') or '').strip(),
                object_type=str(getattr(dso, 'type', '') or '').strip(),
                constellation=str(getattr(dso, 'constellation', '') or '').strip(),
                ra_hours=ra_hours,
                dec_degrees=dec_degrees,
                magnitude=_safe_float(magnitudes[1] if len(magnitudes) > 1 else None)
                or _safe_float(magnitudes[0] if len(magnitudes) > 0 else None),
                size_arcmin=_safe_float(dimensions[0] if len(dimensions) > 0 else None),
                messier=(
                    _normalize_identifier(str(identifiers[0]))
                    if len(identifiers) > 0 and identifiers[0] is not None
                    else None
                ),
                ngc_names=[
                    _normalize_identifier(value)
                    for value in _coerce_identifier_list(identifiers[1] if len(identifiers) > 1 else [])
                ],
                ic_names=[
                    _normalize_identifier(value)
                    for value in _coerce_identifier_list(identifiers[2] if len(identifiers) > 2 else [])
                ],
                common_names=_coerce_identifier_list(identifiers[3] if len(identifiers) > 3 else []),
                other_identifiers=[
                    _normalize_identifier(value)
                    for value in _coerce_identifier_list(identifiers[4] if len(identifiers) > 4 else [])
                ],
            )
        )

    logger.debug(f'Loaded {len(rows)} PyOngc deep-sky rows for SkyTonight')
    return rows


def _load_deep_sky_rows() -> Tuple[List[PyOngcRow], str]:
    return _load_pyongc_rows(), 'PyOngc'


def build_deep_sky_targets(caldwell_map: Optional[Dict[str, str]] = None) -> List[SkyTonightTarget]:
    """Build normalized SkyTonight deep-sky targets from PyOngc."""
    rows, _source = _load_deep_sky_rows()
    return build_targets_from_rows(rows, caldwell_map=caldwell_map)


def _build_standalone_targets_from_json(filename: str, catalogue_key: str) -> List[SkyTonightTarget]:
    """Create SkyTonightTarget records from a standalone-objects JSON catalogue.

    Each JSON entry must have:
      name, ra_hours, dec_degrees, size_arcmin, type, description, mag, constellation

    Optional field:
      extra_catalogues  - list of additional catalogue keys to tag on this target
                          (e.g. ["GaryImm"] marks an object as part of Gary Imm's list)

    These are objects that have no NGC/IC identifier and therefore cannot be
    expressed as cross-references to existing PyOngc records.
    """
    data = _load_json_catalogue(filename)
    if not isinstance(data, list):
        logger.warning(f'{filename} missing or invalid - {catalogue_key} standalone targets not loaded')
        return []

    # Phase 1 - parse all valid entries into intermediate dicts
    parsed: List[Dict] = []
    skipped = 0
    for entry in data:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        name = str(entry.get('name') or '').strip()
        ra_hours = entry.get('ra_hours')
        dec_degrees = entry.get('dec_degrees')
        if not name or ra_hours is None or dec_degrees is None:
            skipped += 1
            continue
        try:
            ra_h = float(ra_hours)
            dec_d = float(dec_degrees)
        except (TypeError, ValueError):
            skipped += 1
            continue
        canonical_name = normalize_object_name(name)
        if not canonical_name:
            skipped += 1
            continue
        parsed.append(
            {
                'name': name,
                'canonical_name': canonical_name,
                'ra_h': ra_h,
                'dec_d': dec_d,
                'size_arcmin': _safe_float(entry.get('size_arcmin')),
                'mag': _safe_float(entry.get('mag')),
                'object_type': str(entry.get('type') or 'Unknown').strip(),
                'description': str(entry.get('description') or '').strip(),
                'constellation': str(entry.get('constellation') or '').strip(),
                'extra_cats': [str(c) for c in (entry.get('extra_catalogues') or []) if c],
            }
        )

    # Phase 2 - batch-compute constellations for entries that have none
    missing_idx = [i for i, e in enumerate(parsed) if not e['constellation']]
    if missing_idx:
        try:
            import numpy as np
            from astropy.coordinates import SkyCoord, get_constellation

            ras = np.array([parsed[i]['ra_h'] * 15.0 for i in missing_idx])
            decs = np.array([parsed[i]['dec_d'] for i in missing_idx])
            coords = SkyCoord(ra=ras, dec=decs, unit='deg')
            names = get_constellation(coords)
            for i, con in zip(missing_idx, names):
                parsed[i]['constellation'] = str(con)
            logger.info(f'{filename}: resolved constellations for {len(missing_idx)} entries via astropy')
        except Exception as exc:
            logger.warning(f'{filename}: constellation batch lookup failed - {exc}')

    # Phase 3 - build SkyTonightTarget objects
    targets: List[SkyTonightTarget] = []
    for e in parsed:
        catalogue_names: Dict[str, str] = {catalogue_key: e['name']}
        for extra_cat in e['extra_cats']:
            catalogue_names[extra_cat] = e['name']
        # Only promote description to CommonName for GaryImm standalone objects,
        # where Gary Imm's labels are the primary identifiers. For all other
        # catalogues (Sharpless, Barnard, vdB, AbellPNe, AbellClusters…) the
        # catalogue designation (Sh2-N, vdB N, …) is the preferred display name;
        # the description is kept as a searchable alias only.
        use_common_name = catalogue_key == 'GaryImm' and e['description'] and e['description'] != e['name']
        if use_common_name:
            catalogue_names['CommonName'] = e['description']

        preferred_name = e['description'] if use_common_name else e['name']
        all_catalogues = sorted({catalogue_key, *e['extra_cats'], *catalogue_names.keys()})
        targets.append(
            SkyTonightTarget(
                target_id=f"dso-{catalogue_key.lower()}-{e['canonical_name']}",
                category='deep_sky',
                object_type=e['object_type'],
                preferred_name=preferred_name,
                catalogue_names=catalogue_names,
                aliases=sorted({e['name'], e['description']} - {''}),
                constellation=e['constellation'],
                magnitude=e['mag'],
                size_arcmin=e['size_arcmin'],
                coordinates=SkyTonightCoordinates(ra_hours=e['ra_h'], dec_degrees=e['dec_d']),
                source_catalogues=all_catalogues,
                translation_key=f"skytonight.type_{normalize_object_name(e['object_type']) or 'unknown'}",
                metadata={'source': catalogue_key},
            )
        )

    if skipped:
        logger.warning(f'{filename}: skipped {skipped} invalid entries')
    logger.debug(f'Loaded {len(targets)} standalone targets from {filename}')
    return targets


def build_and_save_default_dataset(
    caldwell_map: Optional[Dict[str, str]] = None,
    comet_source_mode: str = 'mpc+jpl',
) -> Dict[str, Any]:
    """Build the first SkyTonight dataset and persist it to the configured dataset file."""
    rows, source_name = _load_deep_sky_rows()
    deep_sky_targets = build_targets_from_rows(rows, caldwell_map=caldwell_map)
    cross_refs = _build_cross_ref_map()
    deep_sky_targets = _apply_cross_refs(deep_sky_targets, cross_refs)

    # Standalone targets: objects with no NGC/IC identifier.
    # Each catalogue has its own JSON; objects selected by Gary Imm are tagged via extra_catalogues.
    standalone_garyimm = _build_standalone_targets_from_json('garyimm_standalone.json', 'GaryImm')
    standalone_sharpless = _build_standalone_targets_from_json('sharpless.json', 'Sharpless')
    standalone_barnard = _build_standalone_targets_from_json('barnard.json', 'Barnard')
    standalone_vdb = _build_standalone_targets_from_json('vdb.json', 'vdB')
    standalone_abell_pne = _build_standalone_targets_from_json('abell_pne.json', 'AbellPNe')
    standalone_abell_clusters = _build_standalone_targets_from_json('abell_clusters.json', 'AbellClusters')
    standalone_targets = [
        *standalone_garyimm,
        *standalone_sharpless,
        *standalone_barnard,
        *standalone_vdb,
        *standalone_abell_pne,
        *standalone_abell_clusters,
    ]

    body_targets = build_body_targets()
    comet_targets = build_comet_targets(source_mode=comet_source_mode)
    all_targets = [*deep_sky_targets, *standalone_targets, *body_targets, *comet_targets]

    comet_sources = sorted(
        {
            str(target.metadata.get('source') or '')
            for target in comet_targets
            if isinstance(target.metadata, dict) and target.metadata.get('source')
        }
    )
    body_sources = sorted(
        {
            str(target.metadata.get('source') or '')
            for target in body_targets
            if isinstance(target.metadata, dict) and target.metadata.get('source')
        }
    )
    all_dso_targets = [*deep_sky_targets, *standalone_targets]
    cross_ref_sources = sorted(
        cat
        for cat in (
            'AbellClusters',
            'AbellPNe',
            'Arp',
            'Barnard',
            'GaryImm',
            'Herschel400',
            'LBN',
            'Pensack500',
            'Sharpless',
            'vdB',
        )
        if any(cat in t.source_catalogues for t in all_dso_targets)
    )
    source_values = [source_name, *body_sources, *comet_sources, *cross_ref_sources]
    deduplicated_sources = [
        value for index, value in enumerate(source_values) if value and value not in source_values[:index]
    ]

    metadata = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': deduplicated_sources,
        'counts': {
            'deep_sky': len(deep_sky_targets) + len(standalone_targets),
            'bodies': len(body_targets),
            'comets': len(comet_targets),
        },
    }

    if not save_targets_dataset(all_targets, metadata=metadata):
        raise RuntimeError('Failed to persist SkyTonight dataset')

    # Do not return the full targets list: the caller only needs metadata and the
    # data is already persisted to disk.  Keeping a reference here would double
    # RAM usage until the caller returns (the scheduler also loads the dataset).
    return {
        'metadata': metadata,
    }
