"""Catalogue Collection - the Astrodex "Pokedex" browsing view.

Pairs every object of a SkyTonight catalogue with the current user's Astrodex so a
catalogue can be browsed as a grid of caught / not-yet-caught cards.

The dataset side is read-only: objects come from the already-built SkyTonight dataset
(``data/skytonight/catalogues/targets.json``, memoized in ``skytonight_targets``), and
nothing here writes to the Astrodex. Filtering, sorting and pagination all happen
server-side because the largest catalogues (OpenNGC ~13k, OpenIC ~5.5k, Abell clusters
~2.7k) are far too big to hand to the browser in one payload.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from observation import object_info
from observation.astrodex import _extract_name_candidates

# The abbreviation -> full name map (including PyOngc's Se1/Se2 Serpens halves) already
# exists next door; imported rather than copied a third time, since neither module
# imports the other.
from observation.beginner_catalog import _CONSTELLATION_ABBR_MAP
from skytonight import skytonight_targets
from skytonight.skytonight_calculator import compute_difficulty_score
from skytonight.skytonight_models import SkyTonightTarget
from utils import normalize_catalogue_key as _normalize_key
from utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PAGE_SIZE = 60
MAX_PAGE_SIZE = 120

# Solar-system bodies are exposed as their own pseudo-catalogue. They are the one group
# whose thumbnail cannot come from DSS2: they have no fixed coordinates, so bundled
# artwork stands in until the user catches them.
BODIES_CATALOGUE = 'Bodies'

# Comets are deliberately absent: they are transient visitors rather than a fixed set to
# complete, and the catalogue picker mirrors /api/catalogues, which is deep-sky only.
_INCLUDED_CATEGORIES = ('deep_sky',)

# Display order of the catalogue picker: the small, completable sets first, the reference
# mega-catalogues last. Anything not listed is appended alphabetically.
_CATALOGUE_DISPLAY_ORDER: Tuple[str, ...] = (
    BODIES_CATALOGUE,
    'Messier',
    'Caldwell',
    'CommonName',
    'Herschel400',
    'Pensack500',
    'GaryImm',
    'Arp',
    'LBN',
    'Sharpless',
    'Barnard',
    'vdB',
    'AbellPNe',
    'AbellClusters',
    'OpenNGC',
    'OpenIC',
)

_SORT_FIELDS = ('catalogue_id', 'name', 'caught', 'magnitude', 'constellation', 'type', 'difficulty')
_CAUGHT_FILTERS = ('all', 'yes', 'no')
_DIFFICULTY_FILTERS = ('beginner', 'intermediate', 'advanced')

# Ranks the difficulty labels for sorting; unrated objects (solar-system bodies) sort last.
_DIFFICULTY_ORDER = {'beginner': 0, 'intermediate': 1, 'advanced': 2}

# Splits a catalogue identifier into its text/number runs so "M 9" sorts before "M 10"
# instead of after it (plain string ordering would compare "1" against "9").
_NATURAL_CHUNKS = re.compile(r'(\d+)')

# The Sun is not part of the built dataset (SkyTonight tracks it as the source of
# twilight, never as a target), but it is very much something an astrophotographer
# catches, so the Bodies collection carries it as a synthetic entry.
_SUN_ENTRY: Dict[str, Any] = {
    'target_id': 'body-sun',
    'catalogue_id': 'Sun',
    'preferred_name': 'Sun',
    'object_type': 'Sun',
    'constellation': '',
    'magnitude': None,
    'size_arcmin': None,
    'difficulty': None,
    'ra_hours': None,
    'dec_degrees': None,
    'aliases': ['Sun', 'Sol', 'Soleil'],
}


def _natural_sort_key(value: str) -> Tuple:
    """Return a tuple that orders identifiers the way a human reads them ("M 9" < "M 10")."""
    parts = _NATURAL_CHUNKS.split(str(value or '').strip().casefold())
    # Digit runs become ints; the (0, int) / (1, str) prefix keeps the tuple comparable.
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def _body_slug(target_id: str) -> str:
    """Return the artwork slug for a solar-system target id ("body-mars" -> "mars")."""
    slug = str(target_id or '').strip().casefold()
    return slug[len('body-') :] if slug.startswith('body-') else slug


def _body_image_url(target_id: str) -> Optional[str]:
    """Return the bundled illustration for a solar-system body, or None if there is none."""
    slug = _body_slug(target_id)
    return f'/static/img/bodies/{slug}.svg' if re.fullmatch(r'[a-z]+', slug) else None


def _target_key_candidates(entry: Dict[str, Any]) -> set:
    """Return the normalized names an Astrodex item may have been saved under for this object."""
    candidates = {entry.get('catalogue_id'), entry.get('preferred_name')}
    candidates.update(entry.get('aliases') or [])
    return {key for key in (_normalize_key(value) for value in candidates) if key}


def _target_all_keys(target: Any) -> set:
    """Same as :func:`_target_key_candidates` but straight off a dataset target.

    Used by the counting pass, which needs every identifier of an object at once rather
    than the single-catalogue view a card carries.
    """
    if isinstance(target, dict):
        catalogue_names = target.get('catalogue_names') or {}
        preferred_name = target.get('preferred_name')
        aliases = target.get('aliases') or []
    else:
        catalogue_names = getattr(target, 'catalogue_names', {}) or {}
        preferred_name = getattr(target, 'preferred_name', '')
        aliases = getattr(target, 'aliases', []) or []

    candidates = set(catalogue_names.values()) | set(aliases) | {preferred_name}
    return {key for key in (_normalize_key(value) for value in candidates) if key}


def build_astrodex_index(items: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map every normalized name an Astrodex item is known by to that item.

    Built once per request so annotating a 13k-object catalogue stays a set lookup per
    object rather than a repeated scan of the user's collection.
    """
    index: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        # Astrodex items are stored under their display label ("M31 - Andromeda Galaxy"),
        # so the identifier has to be pulled back out of it. Reusing the same extractor
        # is_item_in_astrodex() uses keeps "caught" here in step with the "in Astrodex"
        # badges shown elsewhere in the app.
        for candidate in _extract_name_candidates(str(item.get('name', '') or '')):
            key = _normalize_key(candidate)
            # First writer wins: an item's full label is a better match than the bare
            # identifier the extractor derives from it.
            if key and key not in index:
                index[key] = item
    return index


def _main_picture_filename(item: Dict[str, Any]) -> Optional[str]:
    """Return the cover picture filename of an Astrodex item, or None when it has no picture."""
    pictures = item.get('pictures') if isinstance(item, dict) else None
    if not isinstance(pictures, list) or not pictures:
        return None
    main = next((pic for pic in pictures if isinstance(pic, dict) and pic.get('is_main')), None)
    if main is None:
        main = next((pic for pic in pictures if isinstance(pic, dict)), None)
    filename = str((main or {}).get('filename', '') or '').strip()
    return filename or None


def _full_constellation_name(abbreviation: Any) -> str:
    """Expand an IAU constellation abbreviation ("And") to its full name ("Andromeda").

    Unknown values are passed through unchanged, so an already-expanded name survives.
    """
    value = str(abbreviation or '').strip()
    return _CONSTELLATION_ABBR_MAP.get(value, value)


def _difficulty_for(magnitude: Optional[float], size_arcmin: Optional[float]) -> Optional[str]:
    """Return the beginner/intermediate/advanced label for an object, or None if not rateable.

    Reuses SkyTonight's own scorer, which derives the label from magnitude and apparent size
    alone - it is explicitly independent of location and sky quality, so it can be computed
    straight off the catalogue instead of only for the targets a given night's run happened
    to evaluate. Objects with neither figure (every solar-system body) get no label rather
    than the scorer's neutral "intermediate" default, which would be a guess.
    """
    if magnitude is None and size_arcmin is None:
        return None
    probe = SkyTonightTarget(
        target_id='',
        category='',
        object_type='',
        preferred_name='',
        magnitude=magnitude,
        size_arcmin=size_arcmin,
    )
    return compute_difficulty_score(probe)[1]


def _normalize_target(target: Any, catalogue: str) -> Optional[Dict[str, Any]]:
    """Flatten a SkyTonightTarget (or its dict form) into the fields a collection card needs."""
    is_dict = isinstance(target, dict)

    def field(key: str, default: Any = None) -> Any:
        """Read one attribute whether the dataset handed us a dataclass or a plain dict."""
        return target.get(key, default) if is_dict else getattr(target, key, default)

    if is_dict:
        coordinates = target.get('coordinates') or {}
        ra_hours = coordinates.get('ra_hours') if isinstance(coordinates, dict) else None
        dec_degrees = coordinates.get('dec_degrees') if isinstance(coordinates, dict) else None
    else:
        coordinates = getattr(target, 'coordinates', None)
        ra_hours = getattr(coordinates, 'ra_hours', None)
        dec_degrees = getattr(coordinates, 'dec_degrees', None)

    catalogue_names = field('catalogue_names', {}) or {}
    catalogue_id = str(catalogue_names.get(catalogue, '') or '').strip()
    if not catalogue_id:
        return None

    magnitude = field('magnitude')
    size_arcmin = field('size_arcmin')

    return {
        'target_id': str(field('target_id', '') or ''),
        'catalogue_id': catalogue_id,
        'preferred_name': str(field('preferred_name', '') or ''),
        'object_type': str(field('object_type', '') or ''),
        # The dataset stores IAU abbreviations ("And"); the frontend's constellation
        # translations are keyed on the full name, so expand it here.
        'constellation': _full_constellation_name(field('constellation', '')),
        'magnitude': magnitude,
        'size_arcmin': size_arcmin,
        'difficulty': _difficulty_for(magnitude, size_arcmin),
        'ra_hours': ra_hours,
        'dec_degrees': dec_degrees,
        'aliases': list(field('aliases', []) or []),
    }


def _catalogue_entries(catalogue: str) -> List[Dict[str, Any]]:
    """Return every dataset object carrying an identifier in ``catalogue``."""
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []

    entries: List[Dict[str, Any]] = []
    for target in targets:
        category = target.get('category') if isinstance(target, dict) else getattr(target, 'category', '')
        if catalogue == BODIES_CATALOGUE:
            if str(category or '') != 'bodies':
                continue
        elif str(category or '') not in _INCLUDED_CATEGORIES:
            continue
        entry = _normalize_target(target, catalogue)
        if entry is not None:
            entries.append(entry)

    if catalogue == BODIES_CATALOGUE:
        entries.append(dict(_SUN_ENTRY))
    return entries


def _annotate(entry: Dict[str, Any], astrodex_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Attach caught state and the card image to a normalized catalogue entry."""
    matched: Optional[Dict[str, Any]] = None
    for key in _target_key_candidates(entry):
        matched = astrodex_index.get(key)
        if matched is not None:
            break

    caught = matched is not None
    picture_count = 0
    image_url: Optional[str] = None
    image_source: Optional[str] = None

    if matched is not None:
        pictures = matched.get('pictures')
        picture_count = len(pictures) if isinstance(pictures, list) else 0
        filename = _main_picture_filename(matched)
        if filename:
            image_url = f'/api/astrodex/images/{filename}'
            image_source = 'astrodex'

    if image_url is None:
        if str(entry.get('target_id', '')).startswith('body-'):
            image_url = _body_image_url(entry['target_id'])
            image_source = 'body' if image_url else None
        elif entry.get('ra_hours') is not None and entry.get('dec_degrees') is not None:
            image_url = object_info.get_object_image_proxy_url(entry['ra_hours'] * 15.0, entry['dec_degrees'])
            image_source = 'dss2'

    return {
        'target_id': entry['target_id'],
        'catalogue_id': entry['catalogue_id'],
        'preferred_name': entry['preferred_name'],
        'object_type': entry['object_type'],
        'constellation': entry['constellation'],
        'magnitude': entry['magnitude'],
        'size_arcmin': entry['size_arcmin'],
        'difficulty': entry['difficulty'],
        'caught': caught,
        'picture_count': picture_count,
        'image_url': image_url,
        'image_source': image_source,
    }


def list_catalogues(astrodex_items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return every selectable catalogue with its object count and how many are caught.

    Counted in a single pass over the dataset: an object belongs to as many catalogues as
    it has identifiers, so scanning per catalogue would re-walk all ~18k targets 16 times.
    """
    astrodex_index = build_astrodex_index(astrodex_items)
    known_keys = astrodex_index.keys()
    dataset = skytonight_targets.load_targets_dataset()
    targets = dataset.get('targets', []) if isinstance(dataset, dict) else []

    totals: Dict[str, int] = {}
    caught_counts: Dict[str, int] = {}

    for target in targets:
        is_dict = isinstance(target, dict)
        category = str((target.get('category') if is_dict else getattr(target, 'category', '')) or '')
        if category != 'bodies' and category not in _INCLUDED_CATEGORIES:
            continue

        catalogue_names = (target.get('catalogue_names') if is_dict else getattr(target, 'catalogue_names', {})) or {}
        names = [str(name).strip() for name in catalogue_names if str(name).strip()]
        if not names:
            continue

        is_caught = bool(_target_all_keys(target) & known_keys)
        for name in names:
            totals[name] = totals.get(name, 0) + 1
            if is_caught:
                caught_counts[name] = caught_counts.get(name, 0) + 1

    # The synthetic Sun entry is not in the dataset, so it is counted separately.
    totals[BODIES_CATALOGUE] = totals.get(BODIES_CATALOGUE, 0) + 1
    if _target_key_candidates(_SUN_ENTRY) & known_keys:
        caught_counts[BODIES_CATALOGUE] = caught_counts.get(BODIES_CATALOGUE, 0) + 1

    ordered = [name for name in _CATALOGUE_DISPLAY_ORDER if name in totals]
    ordered += sorted(name for name in totals if name not in _CATALOGUE_DISPLAY_ORDER)

    return [{'id': name, 'total': totals[name], 'caught': caught_counts.get(name, 0)} for name in ordered]


def _matches_filters(
    card: Dict[str, Any],
    search: str,
    object_type: str,
    constellation: str,
    caught: str,
    difficulty: str,
) -> bool:
    """Return True when a card survives every requested filter."""
    if object_type and card['object_type'] != object_type:
        return False
    if constellation and card['constellation'] != constellation:
        return False
    if difficulty and card['difficulty'] != difficulty:
        return False
    if caught == 'yes' and not card['caught']:
        return False
    if caught == 'no' and card['caught']:
        return False
    if search:
        haystack = f"{card['catalogue_id']} {card['preferred_name']}".casefold()
        if search not in haystack:
            return False
    return True


def _sort_cards(cards: List[Dict[str, Any]], sort: str, descending: bool) -> List[Dict[str, Any]]:
    """Order cards by the requested field, always tie-breaking on the catalogue identifier."""

    def tiebreak(card: Dict[str, Any]) -> Tuple:
        return _natural_sort_key(card['catalogue_id'])

    # Objects carrying no value for the sorted field have no rank, so they stay grouped at
    # the end in both directions instead of flipping to the top when the order reverses.
    if sort in ('magnitude', 'difficulty'):
        rank = (
            (lambda card: card['magnitude'])
            if sort == 'magnitude'
            else (lambda card: _DIFFICULTY_ORDER[card['difficulty']])
        )
        rated = [card for card in cards if card[sort] is not None]
        unrated = [card for card in cards if card[sort] is None]
        rated.sort(key=lambda card: (rank(card), tiebreak(card)), reverse=descending)
        unrated.sort(key=tiebreak)
        return rated + unrated

    key_builders = {
        'catalogue_id': tiebreak,
        'name': lambda card: (card['preferred_name'].casefold(), tiebreak(card)),
        'caught': lambda card: (card['caught'], tiebreak(card)),
        'constellation': lambda card: (card['constellation'].casefold(), tiebreak(card)),
        'type': lambda card: (card['object_type'].casefold(), tiebreak(card)),
    }
    ordered = sorted(cards, key=key_builders.get(sort, tiebreak), reverse=descending)
    return ordered


def get_collection_page(
    catalogue: str,
    astrodex_items: Sequence[Dict[str, Any]],
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = 'catalogue_id',
    order: str = 'asc',
    search: str = '',
    object_type: str = '',
    constellation: str = '',
    caught: str = 'all',
    difficulty: str = '',
) -> Dict[str, Any]:
    """Return one page of a catalogue's cards plus the counters and filter options around it.

    ``types`` and ``constellations`` are computed over the whole catalogue, not the current
    page, so the filter dropdowns do not shrink as the user pages through.
    """
    sort = sort if sort in _SORT_FIELDS else 'catalogue_id'
    caught = caught if caught in _CAUGHT_FILTERS else 'all'
    difficulty = difficulty if difficulty in _DIFFICULTY_FILTERS else ''
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    descending = str(order or 'asc').casefold() == 'desc'
    search = str(search or '').strip().casefold()

    astrodex_index = build_astrodex_index(astrodex_items)
    cards = [_annotate(entry, astrodex_index) for entry in _catalogue_entries(catalogue)]

    total = len(cards)
    caught_total = sum(1 for card in cards if card['caught'])
    types = sorted({card['object_type'] for card in cards if card['object_type']})
    constellations = sorted({card['constellation'] for card in cards if card['constellation']})

    filtered = [
        card for card in cards if _matches_filters(card, search, object_type, constellation, caught, difficulty)
    ]
    filtered = _sort_cards(filtered, sort, descending)

    total_pages = max(1, -(-len(filtered) // page_size))  # ceil division
    page = max(0, min(int(page), total_pages - 1))
    start = page * page_size

    return {
        'catalogue': catalogue,
        'total': total,
        'caught': caught_total,
        'filtered_total': len(filtered),
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'items': filtered[start : start + page_size],
        'types': types,
        'constellations': constellations,
    }
