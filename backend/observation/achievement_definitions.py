"""Badge definitions (v1.9) - declarative data, no logic.

Each badge is one row: an identifier, the family it belongs to (the tiers of one
milestone share a family, so "next within reach" can show only the lowest one not yet
earned), the rule that evaluates it and the rule's parameters. The rules themselves live in
``observation/achievements.py``; the texts live in the i18n files under
``achievements.badges.<id>`` (one-off badges) or ``achievements.rules.<rule>`` (tiered
badges, which take a ``{count}`` / ``{catalogue}`` placeholder).

Adding a badge is one row here, its texts in the six language files, and a test.

Rules
-----
``first_class``          first capture of an object class (``object_class``)
``catalogue_count``      captured objects of ``catalogue``; ``threshold`` None = the whole catalogue
``integration_hours``    total integration time, in hours
``single_target_hours``  integration time on one object, in hours
``multi_night_session``  one session spanning at least ``threshold`` nights
``seasons``              captures in ``threshold`` different seasons of the year
``constellations``       captures in ``threshold`` different constellations
``hemispheres``          captures on both sides of the celestial equator
``dark_site``            a night under a Bortle 3 sky or darker
``new_moon_night``       a night with the Moon at most 5 % illuminated
"""

from typing import Any

GROUP_FIRSTS = 'firsts'
GROUP_CATALOGUES = 'catalogues'
GROUP_ENDURANCE = 'endurance'
GROUP_SKY = 'sky'
GROUP_CONDITIONS = 'conditions'

# Display order of the groups on the Progress page.
GROUP_ORDER: tuple[str, ...] = (GROUP_FIRSTS, GROUP_CATALOGUES, GROUP_ENDURANCE, GROUP_SKY, GROUP_CONDITIONS)

# Darkest-sky and new-moon thresholds. Bortle 3 starts at an SQM of about 21.3 mag/arcsec2
# (Bortle's own table), so a measured night reading at least that counts even when the
# location preset carries no Bortle class.
DARK_SITE_MAX_BORTLE = 3
DARK_SITE_MIN_SQM = 21.3
NEW_MOON_MAX_ILLUMINATION = 5.0


def _first(badge_id: str, object_class: str, icon: str) -> dict[str, Any]:
    return {
        'id': badge_id,
        'family': badge_id,
        'group': GROUP_FIRSTS,
        'rule': 'first_class',
        'object_class': object_class,
        'threshold': 1,
        'icon': icon,
    }


def _catalogue(catalogue: str, thresholds: tuple[int | None, ...], icon: str) -> list[dict[str, Any]]:
    family = f'catalogue_{catalogue.casefold()}'
    return [
        {
            'id': f'{family}_{threshold if threshold is not None else "all"}',
            'family': family,
            'group': GROUP_CATALOGUES,
            'rule': 'catalogue_count',
            'catalogue': catalogue,
            'threshold': threshold,
            'icon': icon,
        }
        for threshold in thresholds
    ]


def _tiered(family: str, group: str, rule: str, thresholds: tuple[int, ...], icon: str) -> list[dict[str, Any]]:
    return [
        {
            'id': f'{family}_{threshold}',
            'family': family,
            'group': group,
            'rule': rule,
            'threshold': threshold,
            'icon': icon,
        }
        for threshold in thresholds
    ]


BADGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    _first('first_galaxy', 'galaxy', 'bi-hurricane'),
    _first('first_nebula', 'nebula', 'bi-cloud-haze2-fill'),
    _first('first_cluster', 'cluster', 'bi-stars'),
    _first('first_comet', 'comet', 'bi-magic'),
    _first('first_planet', 'planet', 'bi-globe2'),
    *_catalogue('Messier', (10, 25, 50, None), 'bi-grid-3x3-gap-fill'),
    *_catalogue('Caldwell', (10, 25, 50, None), 'bi-grid-3x3-gap'),
    *_catalogue('Herschel400', (25, 100, 200, None), 'bi-binoculars-fill'),
    *_catalogue('Sharpless', (10, 50), 'bi-cloud-fog2-fill'),
    *_catalogue('Arp', (10, 50), 'bi-intersect'),
    *_catalogue('Barnard', (10, 50), 'bi-circle-half'),
    *_tiered('hours', GROUP_ENDURANCE, 'integration_hours', (10, 50, 100), 'bi-hourglass-split'),
    *_tiered('target_hours', GROUP_ENDURANCE, 'single_target_hours', (10,), 'bi-bullseye'),
    *_tiered('multi_night', GROUP_ENDURANCE, 'multi_night_session', (2,), 'bi-calendar-range'),
    *_tiered('seasons', GROUP_SKY, 'seasons', (4,), 'bi-arrow-repeat'),
    *_tiered('constellations', GROUP_SKY, 'constellations', (10, 20, 40), 'bi-diagram-3-fill'),
    *_tiered('hemispheres', GROUP_SKY, 'hemispheres', (2,), 'bi-globe-americas'),
    {
        'id': 'dark_site',
        'family': 'dark_site',
        'group': GROUP_CONDITIONS,
        'rule': 'dark_site',
        'threshold': 1,
        'icon': 'bi-moon-stars-fill',
    },
    {
        'id': 'new_moon_night',
        'family': 'new_moon_night',
        'group': GROUP_CONDITIONS,
        'rule': 'new_moon_night',
        'threshold': 1,
        'icon': 'bi-circle',
    },
)

BADGE_IDS: frozenset[str] = frozenset(badge['id'] for badge in BADGE_DEFINITIONS)

# Catalogues a badge counts, in the order the Progress page lists them.
BADGE_CATALOGUES: tuple[str, ...] = tuple(
    dict.fromkeys(badge['catalogue'] for badge in BADGE_DEFINITIONS if badge['rule'] == 'catalogue_count')
)
