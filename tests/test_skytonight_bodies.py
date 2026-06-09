"""Tests for SkyTonight bodies ingestion."""

import skytonight_bodies

build_body_targets = skytonight_bodies.build_body_targets


def test_build_body_targets_contains_major_bodies():
    targets = build_body_targets()

    names = {target.preferred_name for target in targets}
    assert 'Moon' in names
    assert 'Mars' in names
    assert 'Jupiter' in names
    assert all(target.category == 'bodies' for target in targets)


def test_build_body_targets_metadata_source_is_builtin():
    targets = build_body_targets()
    assert targets
    assert all(target.metadata.get('source') == 'builtin-solar-system' for target in targets)


def _get_aliases(targets, name):
    t = next(t for t in targets if t.preferred_name == name)
    return t.aliases


def test_moon_has_luna_and_lune_aliases():
    targets = build_body_targets()
    aliases = _get_aliases(targets, 'Moon')
    assert 'Luna' in aliases
    assert 'Lune' in aliases


def test_mercury_has_mercure_alias():
    targets = build_body_targets()
    assert 'Mercure' in _get_aliases(targets, 'Mercury')


def test_venus_has_vnus_alias():
    targets = build_body_targets()
    assert 'Vénus' in _get_aliases(targets, 'Venus')


def test_saturn_has_saturne_alias():
    targets = build_body_targets()
    assert 'Saturne' in _get_aliases(targets, 'Saturn')


def test_empty_name_body_is_skipped():
    from unittest.mock import patch

    defs_with_empty = list(skytonight_bodies.BODY_DEFINITIONS) + [
        {'name': '', 'object_type': 'Planet', 'aliases': []}
    ]
    with patch.object(skytonight_bodies, 'BODY_DEFINITIONS', defs_with_empty):
        targets = skytonight_bodies.build_body_targets()

    assert all(t.preferred_name != '' for t in targets)
    assert len(targets) == len(skytonight_bodies.BODY_DEFINITIONS)
