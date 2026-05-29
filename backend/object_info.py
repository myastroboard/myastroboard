"""
Deep Sky Object metadata and image integration.

Provides:
  Phase 1 — Object resolution via SIMBAD TAP (identifier → name, type, RA/DEC, aliases)
  Phase 2 — Image URL construction via SkyView/DSS (no download, link only)
  Phase 3 — Localized description via Wikipedia REST API with language fallback chain
"""

import re
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

from logging_config import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REQUEST_TIMEOUT = 10  # seconds

# Whitelist of Wikipedia language codes that the endpoint accepts.
_ALLOWED_LANGS: frozenset = frozenset([
    'en', 'fr', 'de', 'es', 'it', 'pt', 'nl', 'ru', 'ja', 'zh',
    'pl', 'sv', 'uk', 'ar', 'cs', 'ko', 'hu', 'fi', 'no', 'da',
])

# Allowed characters in an astronomical object identifier.
# Permits: letters, digits, space, +, -, ., *, /, '  (e.g. "NGC 2632", "alpha Cen")
_IDENT_RE = re.compile(r"^[A-Za-z0-9 +\-_.*/']+$")

# Pre-built Wikipedia base URLs keyed by lang code — the hostname is never
# constructed from user input, which prevents SSRF (CodeQL CWE-918).
_WIKIPEDIA_BASES: Dict[str, str] = {
    lang: f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/'
    for lang in [
        'en', 'fr', 'de', 'es', 'it', 'pt', 'nl', 'ru', 'ja', 'zh',
        'pl', 'sv', 'uk', 'ar', 'cs', 'ko', 'hu', 'fi', 'no', 'da',
    ]
}
SIMBAD_TAP_URL = 'https://simbad.cds.unistra.fr/simbad/sim-tap/sync'
HIPS2FITS_URL = 'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'


# ──────────────────────────────────────────────
# Input validation
# ──────────────────────────────────────────────

def is_safe_identifier(identifier: str) -> bool:
    """Return True only if *identifier* contains safe characters for an object name."""
    return (
        bool(identifier)
        and len(identifier) <= 64
        and bool(_IDENT_RE.match(identifier))
    )


def _sanitize_lang(lang: str) -> str:
    """Return *lang* if it is in the allowed set, otherwise 'en'."""
    return lang if lang in _ALLOWED_LANGS else 'en'


# ──────────────────────────────────────────────
# Phase 1 — Object resolution (SIMBAD TAP)
# ──────────────────────────────────────────────

def _simbad_query(adql: str) -> Optional[Dict]:
    """Execute an ADQL query against the SIMBAD TAP endpoint and return the JSON payload."""
    try:
        resp = requests.get(
            SIMBAD_TAP_URL,
            params={
                'REQUEST': 'doQuery',
                'LANG': 'ADQL',
                'FORMAT': 'json',
                'QUERY': adql,
            },
            timeout=REQUEST_TIMEOUT,
            headers={'Accept': 'application/json'},
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning(f'SIMBAD TAP request failed: {exc}')
        return None


def _sort_aliases(aliases: List[str]) -> List[str]:
    """
    Return *aliases* sorted so that well-known catalogue names come first
    and noisy survey identifiers (NVSS, TGSS, Gaia, 2MASS, SDSS, …) come last.

    Priority tiers (lower = shown earlier):
      0 - Messier (M \\d)
      1 - NGC / IC
      2 - Caldwell (C \\d), named common names without survey keywords
      3 - Other recognisable catalogue prefixes (UGC, MCG, PGC, LMC, SMC, …)
      4 - Everything else
      5 - Known noisy survey prefixes (NVSS, TGSS, Gaia, 2MASS, SDSS, WISE, …)
    """
    _SURVEY_PREFIXES = (
        '2MASS', '2MASX', 'NVSS', 'TGSS', 'TGSSADR',
        'GAIA', 'SDSS', 'WISE', 'IRAS', 'ROSAT', 'XMM',
        'CHANDRA', 'FIRST', 'WENSS', 'SUMSS', 'GLEAM',
        'LOTSS', 'RACS', 'VLASS',
    )
    _KNOWN_PREFIXES = (
        ('M ',  0), ('NGC ', 1), ('IC ',  1),
        ('C ',  2), ('UGC ', 3), ('MCG ', 3), ('PGC ', 3),
        ('LMC',  3), ('SMC', 3),
    )

    def _priority(alias: str) -> tuple:
        up = alias.upper()
        for prefix, tier in _KNOWN_PREFIXES:
            if up.startswith(prefix.upper()):
                return (tier, alias.lower())
        for survey in _SURVEY_PREFIXES:
            if up.startswith(survey):
                return (5, alias.lower())
        return (4, alias.lower())

    return sorted(aliases, key=_priority)


def _resolve_via_simbad(identifier: str) -> Optional[Dict[str, Any]]:
    """
    Resolve *identifier* through SIMBAD TAP.

    Returns a dict:
    {
        'id': str,           # SIMBAD main identifier
        'name': str,         # same as id
        'type': str,         # human-readable object type
        'ra': float | None,  # degrees J2000
        'dec': float | None, # degrees J2000
        'aliases': list[str] # up to 20 alternative identifiers
    }
    or None if the object is not found.
    """
    # Escape single quotes for ADQL injection safety
    safe_id = identifier.replace("'", "''")

    main_query = (
        "SELECT b.main_id, b.otype_txt, b.ra, b.dec "
        "FROM basic AS b "
        "JOIN ident AS i ON b.oid = i.oidref "
        f"WHERE i.id = '{safe_id}'"
    )
    result = _simbad_query(main_query)
    if not result or not result.get('data'):
        return None

    row = result['data'][0]
    cols = [c['name'] for c in result.get('metadata', [])]
    row_dict = dict(zip(cols, row))

    main_id = str(row_dict.get('main_id') or '').strip()
    obj_type = str(row_dict.get('otype_txt') or '').strip()
    ra_raw = row_dict.get('ra')
    dec_raw = row_dict.get('dec')

    # Fetch all alternative identifiers
    safe_main = main_id.replace("'", "''")
    alias_query = (
        "SELECT i.id "
        "FROM ident AS i "
        "JOIN ident AS ref ON i.oidref = ref.oidref "
        f"WHERE ref.id = '{safe_main}'"
    )
    alias_result = _simbad_query(alias_query)
    raw_aliases: List[str] = []
    if alias_result and alias_result.get('data'):
        for alias_row in alias_result['data']:
            alias_val = str(alias_row[0]).strip()
            # Exclude only the identifier the user searched for — it is already
            # the modal title, so showing it again as an alias is redundant.
            # Keep main_id even if it differs from identifier: it is a valid
            # "also known as" name (e.g. user clicked "M 100", main_id is "NGC 4258").
            if alias_val and alias_val != identifier:
                raw_aliases.append(alias_val)

    return {
        'id': main_id,
        'name': main_id,
        'type': obj_type,
        'ra': float(ra_raw) if ra_raw is not None else None,
        'dec': float(dec_raw) if dec_raw is not None else None,
        'aliases': _sort_aliases(raw_aliases)[:20],
    }


# Recognized catalog patterns for building catalogue_names dicts from SIMBAD aliases.
# Order matters: higher-priority catalogs are matched first.
_CATALOGUE_ALIAS_PATTERNS: List[tuple] = [
    (re.compile(r'^M\s+\d+$', re.I), 'Messier'),
    (re.compile(r'^NGC\s+\w+$', re.I), 'OpenNGC'),
    (re.compile(r'^IC\s+\w+$', re.I), 'OpenIC'),
    (re.compile(r'^C\s+\d+$', re.I), 'Caldwell'),
    (re.compile(r'^HIP\s+\d+$', re.I), 'HIP'),
    (re.compile(r'^HD\s+\d+$', re.I), 'HD'),
    (re.compile(r'^SAO\s+\d+$', re.I), 'SAO'),
    (re.compile(r'^TYC\s+\S+$', re.I), 'TYC'),
    (re.compile(r'^UGC\s+\d+$', re.I), 'UGC'),
    (re.compile(r'^PGC\s+\d+$', re.I), 'PGC'),
    (re.compile(r'^MCG\s+\S+$', re.I), 'MCG'),
]


def build_catalogue_names_from_aliases(identifier: str, aliases: List[str]) -> Dict[str, str]:
    """Build a {catalogue_key: identifier} dict from a SIMBAD alias list.

    The input identifier is always included under its detected catalog key (or 'Simbad').
    """
    result: Dict[str, str] = {}
    for name in [identifier] + aliases:
        for pattern, key in _CATALOGUE_ALIAS_PATTERNS:
            if key not in result and pattern.match(name.strip()):
                result[key] = name.strip()
                break
    if not result:
        result['Simbad'] = identifier
    return result


def resolve_identifier_for_catalogue_lookup(identifier: str) -> Optional[Dict[str, Any]]:
    """Resolve *identifier* via SIMBAD TAP for the Astrodex catalogue-lookup fallback.

    Returns {'object_type', 'constellation', 'aliases'} or None.
    'constellation' is the full lowercase constellation name derived from RA/Dec via astropy
    (e.g. 'cassiopeia', 'ursa major') — ready for the dropdown without further conversion.
    'aliases' is a sorted list (most recognizable first).
    """
    safe_id = identifier.replace("'", "''")
    main_query = (
        "SELECT b.main_id, b.otype_txt, b.ra, b.dec "
        "FROM basic AS b "
        "JOIN ident AS i ON b.oid = i.oidref "
        f"WHERE i.id = '{safe_id}'"
    )
    result = _simbad_query(main_query)
    if not result or not result.get('data'):
        return None

    row = result['data'][0]
    cols = [c['name'] for c in result.get('metadata', [])]
    row_dict = dict(zip(cols, row))

    main_id = str(row_dict.get('main_id') or '').strip()
    obj_type = str(row_dict.get('otype_txt') or '').strip()
    ra_raw = row_dict.get('ra')
    dec_raw = row_dict.get('dec')

    # Derive constellation from coordinates using astropy
    constellation = ''
    if ra_raw is not None and dec_raw is not None:
        try:
            from astropy.coordinates import SkyCoord, get_constellation
            coord = SkyCoord(ra=float(ra_raw), dec=float(dec_raw), unit='deg')
            constellation = str(get_constellation(coord)).lower()
        except Exception:
            pass

    safe_main = main_id.replace("'", "''")
    alias_query = (
        "SELECT i.id FROM ident AS i "
        "JOIN ident AS ref ON i.oidref = ref.oidref "
        f"WHERE ref.id = '{safe_main}'"
    )
    alias_result = _simbad_query(alias_query)
    raw_aliases: List[str] = []
    if alias_result and alias_result.get('data'):
        for alias_row in alias_result['data']:
            alias_val = str(alias_row[0]).strip()
            if alias_val:
                raw_aliases.append(alias_val)

    return {
        'object_type': obj_type,
        'constellation': constellation,
        'aliases': _sort_aliases(raw_aliases),
    }


# ──────────────────────────────────────────────
# Phase 2 — Image URL (SkyView / DSS)
# ──────────────────────────────────────────────

def _get_dss_image_url(ra: float, dec: float, size_deg: float = 0.5) -> str:
    """
    Construct a CDS hips2fits URL for a DSS2 Red image at the given coordinates.

    The URL returns a JPEG image directly (no HTML wrapper).
    """
    params = {
        'hips': 'CDS/P/DSS2/red',
        'width': '400',
        'height': '400',
        'fov': f'{size_deg:.3f}',
        'projection': 'TAN',
        'coordsys': 'icrs',
        'ra': f'{ra:.6f}',
        'dec': f'{dec:.6f}',
        'format': 'jpg',
    }
    return f"{HIPS2FITS_URL}?{urllib.parse.urlencode(params)}"

# ──────────────────────────────────────────────
# Phase 3 — Localized description (Wikipedia)
# ──────────────────────────────────────────────

# Regex matching SIMBAD catalog-style designations that Wikipedia will never have
# e.g. "[LB2005] NGC 3031 X1", "[HB89] 0951+699"
_SIMBAD_CATALOG_RE = re.compile(r'^\[.*?\]')


def _is_wikipedia_candidate(term: str) -> bool:
    """Return False for terms that are SIMBAD catalog designations unlikely to exist on Wikipedia."""
    return not _SIMBAD_CATALOG_RE.match(term.strip())


def _normalize_wikipedia_term(term: str) -> str:
    """Collapse repeated whitespace in a search term before URL-encoding."""
    return ' '.join(term.split())


def _get_wikipedia_summary(search_term: str, lang: str = 'en') -> Optional[Dict[str, str]]:
    """
    Fetch a Wikipedia page summary for *search_term* in the given *lang*.

    Only languages from _ALLOWED_LANGS are accepted; others fall back to 'en'.

    Returns:
    {
        'title': str,
        'description': str,   # short tagline
        'extract': str        # paragraph summary
    }
    or None if not found.
    """
    lang = _sanitize_lang(lang)
    safe_term = urllib.parse.quote(_normalize_wikipedia_term(search_term), safe='')
    # Use the pre-built base URL so the hostname is never derived from user input.
    base = _WIKIPEDIA_BASES[lang]  # lang is guaranteed in _ALLOWED_LANGS after _sanitize_lang
    url = base + safe_term
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                'Accept': 'application/json',
                'User-Agent': 'MyAstroBoard/1.0 (https://github.com/WorldOfGZ/myastroboard)',
            },
        )
        if resp.status_code in (404, 403):
            return None
        resp.raise_for_status()
        data = resp.json()
        # Skip disambiguation pages — they list unrelated topics sharing the same label
        if data.get('type') == 'disambiguation':
            return None
        extract = data.get('extract', '').strip()
        if not extract:
            return None
        return {
            'title': data.get('title', ''),
            'description': data.get('description', ''),
            'extract': extract,
        }
    except requests.RequestException as exc:
        logger.warning(f'Wikipedia request failed ({lang}/{search_term}): {exc}')
        return None


def _wikipedia_with_fallback(aliases: List[str], lang: str) -> Optional[Dict[str, str]]:
    """
    Try each term in *aliases* for the requested *lang*, then fall back to
    English if nothing is found.
    """
    for term in aliases:
        if not _is_wikipedia_candidate(term):
            continue
        result = _get_wikipedia_summary(term, lang)
        if result:
            return result
    if lang != 'en':
        for term in aliases:
            if not _is_wikipedia_candidate(term):
                continue
            result = _get_wikipedia_summary(term, 'en')
            if result:
                return result
    return None


# ──────────────────────────────────────────────
# SIMBAD identifier normalisation
# ──────────────────────────────────────────────

# Mapping from our identifier formats to the formats SIMBAD uses internally.
# SIMBAD identifiers are case-sensitive and use specific spacing conventions.
_VDB_RE      = re.compile(r'^vdB\s+(\d+)$', re.I)
_SH2_RE      = re.compile(r'^Sh2-(\d+)$', re.I)
_BARNARD_RE  = re.compile(r'^Barnard\s+(\d+)$', re.I)
_ABELL_RE    = re.compile(r'^Abell\s+(\d+)$', re.I)


def _simbad_identifier_variants(identifier: str) -> List[str]:
    """Return alternative SIMBAD-compatible identifiers to try when the primary lookup fails.

    SIMBAD uses different capitalization and spacing than our preferred names:
      vdB N    → VdB N       (different capitalisation)
      Sh2-N    → Sh 2-N      (space before "2-")
      Barnard N → B  N       (abbreviated with double space)
      Abell N  → PN A66  N   (planetary nebula catalog)
                 ACO  N      (galaxy cluster catalog)
    """
    m = _VDB_RE.match(identifier)
    if m:
        return [f'VdB {m.group(1)}']

    m = _SH2_RE.match(identifier)
    if m:
        return [f'Sh 2-{m.group(1)}']

    m = _BARNARD_RE.match(identifier)
    if m:
        return [f'B  {m.group(1)}']

    m = _ABELL_RE.match(identifier)
    if m:
        n = m.group(1)
        return [f'PN A66  {n}', f'ACO  {n}']

    return []


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def _translate_object_type(object_type: str, lang: str) -> str:
    """Return a localized object type using the skytonight i18n keys.

    Mirrors the frontend's strToTranslateKey + tSkyTonightType logic:
      "Open Cluster" → skytonight.type_open_cluster → "Amas ouvert" (fr)
    Falls back to the original string when the key is not found.
    """
    if not object_type or lang == 'en':
        return object_type
    from i18n_utils import I18nManager
    key_suffix = re.sub(r'[^a-z0-9]+', '_', object_type.lower()).strip('_')
    i18n_key = f'skytonight.type_{key_suffix}'
    translated = I18nManager(lang).t(i18n_key)
    return object_type if translated == i18n_key else translated


def get_object_info(identifier: str, lang: str = 'en') -> Dict[str, Any]:
    """
    Return full metadata for an astronomical object.

    Steps:
      1. Validate *identifier* (safe characters, max 64 chars).
      2. Resolve via SIMBAD → name, type, RA/DEC, aliases.
      3. Build SkyView image URL from RA/DEC.
      4. Fetch Wikipedia description (requested lang → English fallback).

    Returns a dict matching the feature spec:
    {
        "id": str,
        "name": str,
        "aliases": list[str],
        "type": str | None,
        "coordinates": {"ra": float, "dec": float} | None,
        "description": str | None,
        "description_title": str | None,
        "image": {"url": str, "credit": str} | None
    }
    """
    lang = _sanitize_lang(lang)

    if not is_safe_identifier(identifier):
        logger.warning(f'get_object_info: unsafe identifier rejected: {identifier!r}')
        return {
            'id': '',
            'name': '',
            'aliases': [],
            'type': None,
            'coordinates': None,
            'description': None,
            'description_title': None,
            'image': None,
            'error': 'invalid_identifier',
        }

    # ── Phase 1: object resolution ──────────────────
    from skytonight_targets import get_lookup_entry as _get_local_entry

    resolved = _resolve_via_simbad(identifier)

    # When the primary lookup fails, try alternative SIMBAD identifier formats
    # (e.g. "vdB 146" → "VdB 146", "Sh2-1" → "Sh 2-1", "Barnard 1" → "B  1").
    if not resolved:
        for _variant in _simbad_identifier_variants(identifier):
            resolved = _resolve_via_simbad(_variant)
            if resolved:
                break

    # When SIMBAD has no record at all, fall back to local dataset coordinates
    # so we can still show the DSS image and Wikipedia description.
    if not resolved:
        _local_entry = _get_local_entry('alias', identifier)
        if not _local_entry:
            _local_entry = _get_local_entry('preferred', identifier)
        if _local_entry and _local_entry.get('ra_deg') is not None:
            _ra  = float(_local_entry['ra_deg'])
            _dec = float(_local_entry['dec_deg'])
            _local_type = str(_local_entry.get('object_type') or '').strip()
            _preferred  = str(_local_entry.get('preferred_name') or identifier).strip()
            _image = {'url': _get_dss_image_url(_ra, _dec), 'credit': 'DSS2 Red / CDS HiPS'}
            _seen: set = set()
            _search_terms: List[str] = []
            for _t in [identifier, _preferred]:
                _norm = _normalize_wikipedia_term(_t)
                if _norm not in _seen:
                    _seen.add(_norm)
                    _search_terms.append(_norm)
            _wiki = _wikipedia_with_fallback(_search_terms, lang)
            return {
                'id': _preferred,
                'name': _preferred,
                'aliases': [],
                'type': _translate_object_type(_local_type, lang),
                'coordinates': {'ra': _ra, 'dec': _dec},
                'description': _wiki.get('extract') if _wiki else None,
                'description_title': _wiki.get('title') if _wiki else None,
                'image': _image,
            }
        return {
            'id': identifier,
            'name': identifier,
            'aliases': [],
            'type': None,
            'coordinates': None,
            'description': None,
            'description_title': None,
            'image': None,
            'error': 'not_found',
        }

    ra = resolved.get('ra')
    dec = resolved.get('dec')

    # Replace SIMBAD's raw otype_txt code (e.g. "OpC", "GlCl") with the human-readable
    # object_type from the local dataset when available — the local type matches the
    # i18n keys used by tSkyTonightType() in the frontend (e.g. "Open Cluster" →
    # skytonight.type_open_cluster → "Amas ouvert").
    _local_entry = _get_local_entry('alias', identifier)
    if not _local_entry:
        # Also try via SIMBAD main_id in case identifier was an alias
        _local_entry = _get_local_entry('alias', resolved.get('name', ''))
    local_type = str(_local_entry.get('object_type') or '').strip() if _local_entry else ''
    if local_type:
        resolved = dict(resolved, type=local_type)

    # ── Phase 2: image ──────────────────────────────
    image = None
    if ra is not None and dec is not None:
        image = {
            'url': _get_dss_image_url(ra, dec),
            'credit': 'DSS2 Red / CDS HiPS',
        }

    # ── Phase 3: Wikipedia description ─────────────
    # Build candidate search terms: original identifier first (e.g. 'NGC 3034'
    # resolves to SIMBAD main name 'M  82' which Wikipedia rejects with a space),
    # then SIMBAD main name, then recognisable aliases.
    # Also add compact (no-space) variant for Messier-style names like 'M 82' → 'M82'.
    _seen: set = set()
    search_terms: List[str] = []
    for _t in [identifier, resolved['name']] + resolved.get('aliases', [])[:8]:
        _norm = _normalize_wikipedia_term(_t)
        if _norm not in _seen:
            _seen.add(_norm)
            search_terms.append(_norm)
        # For 'M 82' style names also try 'M82' (no space) — French Wikipedia needs it
        _compact = _norm.replace(' ', '')
        if _compact != _norm and _compact not in _seen:
            _seen.add(_compact)
            search_terms.append(_compact)
    wiki_data = _wikipedia_with_fallback(search_terms, lang)

    return {
        'id': resolved['id'],
        'name': resolved['name'],
        'aliases': resolved.get('aliases', []),
        'type': _translate_object_type(str(resolved.get('type') or ''), lang),
        'coordinates': {'ra': ra, 'dec': dec} if ra is not None else None,
        'description': wiki_data.get('extract') if wiki_data else None,
        'description_title': wiki_data.get('title') if wiki_data else None,
        'image': image,
    }
