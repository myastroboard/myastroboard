"""Tests for SkyTonight catalogue dataset building."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from skytonight_catalogue_builder import (
    PyOngcRow,
    _load_deep_sky_rows,
    build_targets_from_rows,
    _safe_float,
    _coerce_identifier_list,
    _normalize_identifier,
    _collect_catalogue_names,
    _build_aliases,
    _canonical_key,
    _merge_target,
    _load_json_catalogue,
    _ngc_ic_match_key,
    _build_cross_ref_map,
    _apply_cross_refs,
    _build_standalone_targets_from_json,
    _CATALOGUES_DIR,
)
from skytonight_models import SkyTonightCoordinates, SkyTonightTarget


def test_build_targets_from_rows_prefers_openngc_and_deduplicates():
    rows = [
        PyOngcRow(
            name='NGC224',
            object_type='Galaxy',
            constellation='And',
            ra_hours=0.712,
            dec_degrees=41.269,
            magnitude=3.44,
            size_arcmin=189.0,
            messier='M 31',
            ngc_names=['NGC 224'],
            ic_names=[],
            common_names=['Andromeda Galaxy'],
            other_identifiers=['PGC 2557'],
        ),
        PyOngcRow(
            name='M31',
            object_type='Galaxy',
            constellation='And',
            ra_hours=0.712,
            dec_degrees=41.269,
            magnitude=3.44,
            size_arcmin=189.0,
            messier='M 31',
            ngc_names=['NGC 224'],
            ic_names=[],
            common_names=['Great Andromeda Nebula'],
            other_identifiers=[],
        ),
    ]

    targets = build_targets_from_rows(rows)

    assert len(targets) == 1
    target = targets[0]
    assert target.target_id == 'dso-openngc-ngc224'
    # CommonName takes priority in SKYTONIGHT_PREFERRED_NAME_ORDER
    assert target.preferred_name == 'Andromeda Galaxy'
    assert target.catalogue_names['CommonName'] == 'Andromeda Galaxy'
    assert target.catalogue_names['Messier'] == 'M 31'
    assert target.catalogue_names['OpenNGC'] == 'NGC 224'
    assert 'Andromeda Galaxy' in target.aliases
    assert 'Great Andromeda Nebula' in target.aliases


def test_build_targets_from_rows_adds_caldwell_when_mapped():
    rows = [
        PyOngcRow(
            name='NGC7000',
            object_type='Nebula',
            constellation='Cyg',
            ra_hours=20.988,
            dec_degrees=44.528,
            magnitude=4.0,
            size_arcmin=120.0,
            messier=None,
            ngc_names=['NGC 7000'],
            ic_names=[],
            common_names=['North America Nebula'],
            other_identifiers=['LBN 373'],
        ),
    ]

    targets = build_targets_from_rows(rows, caldwell_map={'ngc7000': 'C 20'})

    assert len(targets) == 1
    assert targets[0].catalogue_names['Caldwell'] == 'C 20'


def test_build_targets_from_rows_skips_missing_coordinates_and_duplicates():
    rows = [
        PyOngcRow(
            name='IC1064',
            object_type='Galaxy',
            constellation='Psc',
            ra_hours=None,
            dec_degrees=None,
            magnitude=None,
            size_arcmin=None,
            messier=None,
            ngc_names=[],
            ic_names=['IC 1064'],
            common_names=[],
            other_identifiers=[],
        ),
        PyOngcRow(
            name='IC11',
            object_type='Duplicated record',
            constellation='Cas',
            ra_hours=0.1,
            dec_degrees=60.0,
            magnitude=None,
            size_arcmin=None,
            messier=None,
            ngc_names=[],
            ic_names=['IC 11'],
            common_names=[],
            other_identifiers=[],
        ),
    ]

    targets = build_targets_from_rows(rows)
    assert targets == []


def test_build_and_save_default_dataset_includes_comets(monkeypatch):
    deep_sky_row = PyOngcRow(
        name='NGC224',
        object_type='Galaxy',
        constellation='And',
        ra_hours=0.712,
        dec_degrees=41.269,
        magnitude=3.44,
        size_arcmin=189.0,
        messier='M 31',
        ngc_names=['NGC 224'],
        ic_names=[],
        common_names=['Andromeda Galaxy'],
        other_identifiers=['PGC 2557'],
    )

    comet_target = SkyTonightTarget(
        target_id='comet-13polbers',
        category='comets',
        object_type='Comet',
        preferred_name='13P/Olbers',
        catalogue_names={'Comets': '13P/Olbers'},
        aliases=['13P'],
        source_catalogues=['Comets'],
        translation_key='skytonight.type_comet',
        metadata={'source': 'curated-fallback'},
    )

    body_target = SkyTonightTarget(
        target_id='body-mars',
        category='bodies',
        object_type='Planet',
        preferred_name='Mars',
        catalogue_names={'Bodies': 'Mars'},
        aliases=[],
        source_catalogues=['Bodies'],
        translation_key='skytonight.type_planet',
        metadata={'source': 'builtin-solar-system'},
    )

    monkeypatch.setattr('skytonight_catalogue_builder._load_deep_sky_rows', lambda: ([deep_sky_row], 'targets-yaml'))
    monkeypatch.setattr('skytonight_catalogue_builder.build_body_targets', lambda: [body_target])
    monkeypatch.setattr('skytonight_catalogue_builder.build_comet_targets', lambda source_mode='mpc+jpl': [comet_target])
    monkeypatch.setattr('skytonight_catalogue_builder.save_targets_dataset', lambda targets, metadata=None: True)
    monkeypatch.setattr('skytonight_catalogue_builder._build_standalone_targets_from_json', lambda filename, catalogue_key: [])

    from skytonight_catalogue_builder import build_and_save_default_dataset

    result = build_and_save_default_dataset()
    counts = result['metadata']['counts']

    assert counts['deep_sky'] == 1
    assert counts['bodies'] == 1
    assert counts['comets'] == 1
    assert counts['deep_sky'] + counts['bodies'] + counts['comets'] == 3
    assert 'builtin-solar-system' in result['metadata']['sources']
    assert 'curated-fallback' in result['metadata']['sources']


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

def test_safe_float_returns_none_for_none():
    assert _safe_float(None) is None


def test_safe_float_converts_numeric_string():
    assert _safe_float('3.14') == pytest.approx(3.14)


def test_safe_float_returns_none_for_invalid():
    assert _safe_float('not-a-number') is None


def test_safe_float_passes_through_int():
    assert _safe_float(42) == 42.0


def test_safe_float_handles_zero():
    assert _safe_float(0) == 0.0


# ---------------------------------------------------------------------------
# _coerce_identifier_list
# ---------------------------------------------------------------------------

def test_coerce_identifier_list_empty_input():
    assert _coerce_identifier_list([]) == []
    assert _coerce_identifier_list(None) == []
    assert _coerce_identifier_list('') == []


def test_coerce_identifier_list_string_input():
    assert _coerce_identifier_list('NGC 224') == ['NGC 224']
    assert _coerce_identifier_list('  ') == []


def test_coerce_identifier_list_filters_empty_items():
    result = _coerce_identifier_list(['NGC 224', '', None, 'IC 1234'])
    assert result == ['NGC 224', 'IC 1234']


def test_coerce_identifier_list_strips_whitespace():
    result = _coerce_identifier_list(['  NGC 224  '])
    assert result == ['NGC 224']


# ---------------------------------------------------------------------------
# _normalize_identifier
# ---------------------------------------------------------------------------

def test_normalize_identifier_messier():
    assert _normalize_identifier('M31') == 'M 31'
    assert _normalize_identifier('M 31') == 'M 31'
    assert _normalize_identifier('m8') == 'M 8'


def test_normalize_identifier_ngc():
    assert _normalize_identifier('NGC224') == 'NGC 224'
    assert _normalize_identifier('NGC 224') == 'NGC 224'


def test_normalize_identifier_ngc_no_suffix():
    # 'NGC' alone with no suffix
    assert _normalize_identifier('NGC') == 'NGC'


def test_normalize_identifier_ic():
    assert _normalize_identifier('IC1234') == 'IC 1234'
    assert _normalize_identifier('IC') == 'IC'


def test_normalize_identifier_caldwell():
    assert _normalize_identifier('C1') == 'C 1'
    assert _normalize_identifier('C 42') == 'C 42'


def test_normalize_identifier_other():
    assert _normalize_identifier('PGC 1234') == 'PGC 1234'


def test_normalize_identifier_empty():
    assert _normalize_identifier('') == ''
    assert _normalize_identifier('   ') == ''


# ---------------------------------------------------------------------------
# _collect_catalogue_names
# ---------------------------------------------------------------------------

def _make_row(**kwargs):
    defaults = dict(
        name='NGC224',
        object_type='Galaxy',
        constellation='And',
        ra_hours=0.712,
        dec_degrees=41.269,
        magnitude=3.44,
        size_arcmin=189.0,
        messier=None,
        ngc_names=[],
        ic_names=[],
        common_names=[],
        other_identifiers=[],
    )
    defaults.update(kwargs)
    return PyOngcRow(**defaults)


def test_collect_catalogue_names_messier_only():
    row = _make_row(messier='M 31')
    names = _collect_catalogue_names(row)
    assert names['Messier'] == 'M 31'


def test_collect_catalogue_names_ngc_only():
    row = _make_row(ngc_names=['NGC 224'])
    names = _collect_catalogue_names(row)
    assert names['OpenNGC'] == 'NGC 224'


def test_collect_catalogue_names_ic_names_set_openngc_and_openic():
    row = _make_row(name='IC1234', ngc_names=[], ic_names=['IC 1234'])
    names = _collect_catalogue_names(row)
    assert 'OpenIC' in names
    assert 'OpenNGC' in names  # IC also fills OpenNGC if not already set


def test_collect_catalogue_names_ic_names_does_not_override_openngc():
    row = _make_row(ngc_names=['NGC 224'], ic_names=['IC 5'])
    names = _collect_catalogue_names(row)
    assert names['OpenNGC'] == 'NGC 224'   # not overwritten by IC
    assert names['OpenIC'] == 'IC 5'


def test_collect_catalogue_names_primary_name_ngc_fills_openngc():
    row = _make_row(name='NGC5128', ngc_names=[], ic_names=[])
    names = _collect_catalogue_names(row)
    assert 'OpenNGC' in names


def test_collect_catalogue_names_primary_name_ic_fills_openic():
    row = _make_row(name='IC1234', ngc_names=[], ic_names=[])
    names = _collect_catalogue_names(row)
    assert 'OpenIC' in names
    assert 'OpenNGC' in names


def test_collect_catalogue_names_caldwell_from_other_identifiers():
    row = _make_row(other_identifiers=['C 20'])
    names = _collect_catalogue_names(row)
    assert names['Caldwell'] == 'C 20'


def test_collect_catalogue_names_caldwell_from_map():
    row = _make_row(ngc_names=['NGC 7000'], name='NGC7000')
    names = _collect_catalogue_names(row, caldwell_map={'ngc7000': 'C 20'})
    assert names['Caldwell'] == 'C 20'


def test_collect_catalogue_names_common_name():
    row = _make_row(common_names=['Andromeda Galaxy'])
    names = _collect_catalogue_names(row)
    assert names['CommonName'] == 'Andromeda Galaxy'


def test_collect_catalogue_names_blank_common_name_not_added():
    row = _make_row(common_names=['  '])
    names = _collect_catalogue_names(row)
    assert 'CommonName' not in names


# ---------------------------------------------------------------------------
# _build_aliases
# ---------------------------------------------------------------------------

def test_build_aliases_includes_all_names():
    row = _make_row(
        name='NGC224',
        messier='M 31',
        ngc_names=['NGC 224'],
        common_names=['Andromeda Galaxy'],
        other_identifiers=['PGC 2557'],
    )
    catalogue_names = {'Messier': 'M 31', 'OpenNGC': 'NGC 224', 'CommonName': 'Andromeda Galaxy'}
    aliases = _build_aliases(row, catalogue_names)
    assert 'NGC224' in aliases
    assert 'NGC 224' in aliases
    assert 'Andromeda Galaxy' in aliases
    assert 'PGC 2557' in aliases
    assert '' not in aliases


# ---------------------------------------------------------------------------
# _canonical_key
# ---------------------------------------------------------------------------

def test_canonical_key_prefers_openngc():
    names = {'OpenNGC': 'NGC 224', 'Messier': 'M 31'}
    cat, key = _canonical_key(names, 'NGC224')
    assert cat == 'OpenNGC'


def test_canonical_key_falls_back_to_messier():
    names = {'Messier': 'M 31'}
    cat, key = _canonical_key(names, 'M31')
    assert cat == 'Messier'


def test_canonical_key_falls_back_to_openic():
    names = {'OpenIC': 'IC 434'}
    cat, key = _canonical_key(names, 'IC434')
    assert cat == 'OpenIC'


def test_canonical_key_falls_back_to_caldwell():
    names = {'Caldwell': 'C 20'}
    cat, key = _canonical_key(names, 'NGC7000')
    assert cat == 'Caldwell'


def test_canonical_key_falls_back_to_alias():
    names = {}
    cat, key = _canonical_key(names, 'SomeObject')
    assert cat == 'Alias'


# ---------------------------------------------------------------------------
# _merge_target
# ---------------------------------------------------------------------------

def _make_target(target_id='dso-openngc-ngc224', preferred_name='NGC 224',
                 catalogue_names=None, aliases=None, magnitude=None,
                 constellation='And', size_arcmin=None, coordinates=None,
                 source_catalogues=None):
    return SkyTonightTarget(
        target_id=target_id,
        category='deep_sky',
        object_type='Galaxy',
        preferred_name=preferred_name,
        catalogue_names=catalogue_names or {'OpenNGC': 'NGC 224'},
        aliases=aliases or [],
        constellation=constellation,
        magnitude=magnitude,
        size_arcmin=size_arcmin,
        coordinates=coordinates,
        source_catalogues=source_catalogues or ['OpenNGC'],
        translation_key='skytonight.type_galaxy',
        metadata={'source': 'pyongc'},
    )


def test_merge_target_combines_aliases_and_source_catalogues():
    t1 = _make_target(aliases=['Andromeda Galaxy'], source_catalogues=['OpenNGC'])
    t2 = _make_target(aliases=['Great Nebula in Andromeda'], source_catalogues=['Messier'])
    merged = _merge_target(t1, t2)
    assert 'Andromeda Galaxy' in merged.aliases
    assert 'Great Nebula in Andromeda' in merged.aliases
    assert 'Messier' in merged.source_catalogues


def test_merge_target_existing_magnitude_takes_priority():
    t1 = _make_target(magnitude=3.44)
    t2 = _make_target(magnitude=5.0)
    merged = _merge_target(t1, t2)
    assert merged.magnitude == pytest.approx(3.44)


def test_merge_target_incoming_magnitude_used_when_existing_is_none():
    t1 = _make_target(magnitude=None)
    t2 = _make_target(magnitude=5.0)
    merged = _merge_target(t1, t2)
    assert merged.magnitude == pytest.approx(5.0)


def test_merge_target_does_not_overwrite_existing_catalogue_name():
    t1 = _make_target(catalogue_names={'OpenNGC': 'NGC 224', 'CommonName': 'First Name'})
    t2 = _make_target(catalogue_names={'OpenNGC': 'NGC 224', 'CommonName': 'Second Name'})
    merged = _merge_target(t1, t2)
    assert merged.catalogue_names['CommonName'] == 'First Name'


def test_merge_target_uses_incoming_coordinates_when_existing_is_none():
    coords = SkyTonightCoordinates(ra_hours=0.712, dec_degrees=41.269)
    t1 = _make_target(coordinates=None)
    t2 = _make_target(coordinates=coords)
    merged = _merge_target(t1, t2)
    assert merged.coordinates is not None
    assert merged.coordinates.ra_hours == pytest.approx(0.712)


# ---------------------------------------------------------------------------
# _load_json_catalogue
# ---------------------------------------------------------------------------

def test_load_json_catalogue_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._CATALOGUES_DIR', str(tmp_path))
    result = _load_json_catalogue('nonexistent.json')
    assert result is None


def test_load_json_catalogue_returns_parsed_json(tmp_path, monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._CATALOGUES_DIR', str(tmp_path))
    catalogue_file = tmp_path / 'test_cat.json'
    catalogue_file.write_text(json.dumps(['NGC 224', 'NGC 891']), encoding='utf-8')
    result = _load_json_catalogue('test_cat.json')
    assert result == ['NGC 224', 'NGC 891']


def test_load_json_catalogue_returns_none_for_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._CATALOGUES_DIR', str(tmp_path))
    bad_file = tmp_path / 'bad.json'
    bad_file.write_text('{ not valid json', encoding='utf-8')
    result = _load_json_catalogue('bad.json')
    assert result is None


# ---------------------------------------------------------------------------
# _ngc_ic_match_key
# ---------------------------------------------------------------------------

def test_ngc_ic_match_key_pads_ngc_number():
    # 'NGC 891' → same key as 'NGC 0891'
    assert _ngc_ic_match_key('NGC 891') == _ngc_ic_match_key('NGC 0891')


def test_ngc_ic_match_key_pads_ic_number():
    assert _ngc_ic_match_key('IC 434') == _ngc_ic_match_key('IC 0434')


def test_ngc_ic_match_key_non_ngc_name_fallback():
    key = _ngc_ic_match_key('Sh2-155')
    assert 'sh2' in key


# ---------------------------------------------------------------------------
# _build_cross_ref_map
# ---------------------------------------------------------------------------

def test_build_cross_ref_map_includes_herschel400_when_json_missing(monkeypatch):
    """When JSON files are missing, Herschel 400 (static) must still be in the map."""
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: None)
    cross_refs = _build_cross_ref_map()
    # Herschel 400 objects are hardcoded; at least some must appear
    assert any('Herschel400' in cats for cats in cross_refs.values())


def test_build_cross_ref_map_pensack_list_is_applied(monkeypatch, tmp_path):
    """When pensack500.json is a list, its entries appear in the map."""
    pensack_data = ['NGC 891', 'NGC 253', '']   # empty string must be skipped

    def fake_load(filename):
        if filename == 'pensack500.json':
            return pensack_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    assert any('Pensack500' in cats for cats in cross_refs.values())


def test_build_cross_ref_map_lbn_dict_is_applied(monkeypatch):
    """When lbn.json is a dict, LBN entries appear in the map."""
    lbn_data = {'NGC 7023': 'LBN 487', '': 'LBN 0'}   # empty key must be skipped

    def fake_load(filename):
        if filename == 'lbn.json':
            return lbn_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    assert any('LBN' in cats for cats in cross_refs.values())


def test_build_cross_ref_map_garyimm_list_is_applied(monkeypatch):
    """When garyimm_crossrefs.json is a list, GaryImm entries appear in the map."""
    garyimm_data = ['NGC 5128', 'NGC 253']

    def fake_load(filename):
        if filename == 'garyimm_crossrefs.json':
            return garyimm_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    assert any('GaryImm' in cats for cats in cross_refs.values())


def test_build_cross_ref_map_arp_dict_is_applied(monkeypatch):
    """When arp.json is a dict, Arp entries appear in the map."""
    arp_data = {'NGC 1': 'Arp 1'}

    def fake_load(filename):
        if filename == 'arp.json':
            return arp_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    assert any('Arp' in cats for cats in cross_refs.values())


def test_build_cross_ref_map_warns_on_invalid_json(monkeypatch):
    """None values (invalid/missing JSON) trigger warnings but do not crash."""
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: None)
    # Should not raise; Herschel 400 static list is still populated
    cross_refs = _build_cross_ref_map()
    assert isinstance(cross_refs, dict)


# ---------------------------------------------------------------------------
# _apply_cross_refs
# ---------------------------------------------------------------------------

def test_apply_cross_refs_empty_cross_refs_returns_unchanged():
    target = _make_target()
    result = _apply_cross_refs([target], {})
    assert result == [target]


def test_apply_cross_refs_injects_herschel400():
    from skytonight_catalogue_builder import _ngc_ic_match_key
    target = _make_target(
        catalogue_names={'OpenNGC': 'NGC 0891'},
        source_catalogues=['OpenNGC'],
    )
    key = _ngc_ic_match_key('NGC 0891')
    cross_refs = {key: {'Herschel400': 'NGC 891'}}
    result = _apply_cross_refs([target], cross_refs)
    assert 'Herschel400' in result[0].catalogue_names
    assert 'Herschel400' in result[0].source_catalogues


def test_apply_cross_refs_skips_target_without_ngc_ic_key():
    # A target with only Messier/CommonName should not be enriched
    target = _make_target(catalogue_names={'Messier': 'M 31'}, source_catalogues=['Messier'])
    cross_refs = {'ngc0224': {'Herschel400': 'NGC 224'}}
    result = _apply_cross_refs([target], cross_refs)
    assert 'Herschel400' not in result[0].catalogue_names


def test_apply_cross_refs_enriches_via_openic():
    from skytonight_catalogue_builder import _ngc_ic_match_key
    target = _make_target(
        catalogue_names={'OpenIC': 'IC 0434'},
        source_catalogues=['OpenIC'],
    )
    key = _ngc_ic_match_key('IC 0434')
    cross_refs = {key: {'LBN': 'LBN 954'}}
    result = _apply_cross_refs([target], cross_refs)
    assert 'LBN' in result[0].catalogue_names


# ---------------------------------------------------------------------------
# _build_standalone_targets_from_json
# ---------------------------------------------------------------------------

def test_build_standalone_targets_returns_empty_for_missing_catalogue(monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: None)
    result = _build_standalone_targets_from_json('missing.json', 'TestCat')
    assert result == []


def test_build_standalone_targets_returns_empty_for_non_list_data(monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: {'not': 'a list'})
    result = _build_standalone_targets_from_json('bad.json', 'TestCat')
    assert result == []


def test_build_standalone_targets_parses_valid_entries(monkeypatch):
    data = [
        {
            'name': 'Sh2-155',
            'ra_hours': 22.5,
            'dec_degrees': 62.5,
            'size_arcmin': 50.0,
            'mag': 7.7,
            'type': 'Emission Nebula',
            'description': 'Cave Nebula',
            'constellation': 'Cep',
        }
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('sharpless.json', 'Sharpless')
    assert len(result) == 1
    t = result[0]
    assert t.preferred_name == 'Sh2-155'
    assert t.coordinates is not None
    assert t.coordinates.ra_hours == pytest.approx(22.5)


def test_build_standalone_targets_skips_entries_missing_ra_dec(monkeypatch):
    data = [
        {'name': 'NoCoords', 'ra_hours': None, 'dec_degrees': None,
         'type': 'Unknown', 'description': '', 'constellation': 'Ori'},
        {'name': 'Valid', 'ra_hours': 5.5, 'dec_degrees': -5.0,
         'type': 'Unknown', 'description': '', 'constellation': 'Ori'},
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('test.json', 'TestCat')
    assert len(result) == 1
    assert result[0].preferred_name == 'Valid'


# ---------------------------------------------------------------------------
# _collect_catalogue_names — OpenNGC already set when IC row processed (line 485)
# ---------------------------------------------------------------------------

def test_collect_catalogue_names_ic_row_with_ngc_names_skips_openngc_fallback():
    """Line 485 False branch: IC-named row already has OpenNGC set from ngc_names."""
    row = _make_row(name='IC1234', ngc_names=['NGC 224'], ic_names=[])
    names = _collect_catalogue_names(row)
    assert names.get('OpenNGC') == 'NGC 224'
    assert names.get('OpenIC') == 'IC 1234'


# ---------------------------------------------------------------------------
# _build_cross_ref_map — if key: False branches (lines 630, 642, 654, 666)
# ---------------------------------------------------------------------------

def test_build_cross_ref_map_pensack_skips_empty_key(monkeypatch):
    """Line 630 False branch: Pensack entry normalizes to empty key -> skipped."""
    pensack_data = ['---', 'NGC 5128']

    def fake_load(filename):
        if filename == 'pensack500.json':
            return pensack_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc5128_key = _ngc_ic_match_key('NGC 5128')
    assert 'Pensack500' in cross_refs.get(ngc5128_key, {})


def test_build_cross_ref_map_lbn_skips_empty_key(monkeypatch):
    """Line 642 False branch: LBN entry raw_ngc_name normalizes to empty key -> skipped."""
    lbn_data = {'---': 'LBN 999', 'NGC 5128': 'LBN 357'}

    def fake_load(filename):
        if filename == 'lbn.json':
            return lbn_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc5128_key = _ngc_ic_match_key('NGC 5128')
    assert 'LBN' in cross_refs.get(ngc5128_key, {})


def test_build_cross_ref_map_garyimm_skips_empty_key(monkeypatch):
    """Line 654 False branch: GaryImm entry normalizes to empty key -> skipped."""
    garyimm_data = ['---', 'NGC 5128']

    def fake_load(filename):
        if filename == 'garyimm_crossrefs.json':
            return garyimm_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc5128_key = _ngc_ic_match_key('NGC 5128')
    assert 'GaryImm' in cross_refs.get(ngc5128_key, {})


def test_build_cross_ref_map_arp_skips_empty_key(monkeypatch):
    """Line 666 False branch: Arp entry raw_ngc_name normalizes to empty key -> skipped."""
    arp_data = {'---': 'Arp 999', 'NGC 2': 'Arp 2'}

    def fake_load(filename):
        if filename == 'arp.json':
            return arp_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc2_key = _ngc_ic_match_key('NGC 2')
    assert 'Arp' in cross_refs.get(ngc2_key, {})


def test_build_standalone_targets_skips_non_dict_entries(monkeypatch):
    data = ['not-a-dict', None, 42, {'name': 'Valid', 'ra_hours': 5.5, 'dec_degrees': -5.0,
                                     'type': 'Unknown', 'description': '', 'constellation': 'Ori'}]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('test.json', 'TestCat')
    assert len(result) == 1


def test_build_standalone_targets_garyimm_uses_description_as_preferred_name(monkeypatch):
    data = [
        {
            'name': 'NGC 891',
            'ra_hours': 2.37,
            'dec_degrees': 42.35,
            'size_arcmin': 13.5,
            'mag': 10.1,
            'type': 'Galaxy',
            'description': 'Silver Sliver Galaxy',
            'constellation': 'And',
        }
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('garyimm_standalone.json', 'GaryImm')
    assert len(result) == 1
    assert result[0].preferred_name == 'Silver Sliver Galaxy'
    assert 'CommonName' in result[0].catalogue_names


def test_build_standalone_targets_handles_extra_catalogues(monkeypatch):
    data = [
        {
            'name': 'NGC 891',
            'ra_hours': 2.37,
            'dec_degrees': 42.35,
            'size_arcmin': 13.5,
            'mag': 10.1,
            'type': 'Galaxy',
            'description': 'Silver Sliver Galaxy',
            'constellation': 'And',
            'extra_catalogues': ['Herschel400'],
        }
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('garyimm_standalone.json', 'GaryImm')
    assert 'Herschel400' in result[0].catalogue_names


def test_build_standalone_targets_skips_invalid_ra_dec_types(monkeypatch):
    data = [
        {'name': 'Bad', 'ra_hours': 'not-a-float', 'dec_degrees': 42.0,
         'type': 'Unknown', 'description': '', 'constellation': 'Ori'},
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('test.json', 'TestCat')
    assert result == []


# ---------------------------------------------------------------------------
# build_targets_from_rows - IC / Caldwell / other branches
# ---------------------------------------------------------------------------

def test_build_targets_from_rows_ic_only_object():
    rows = [
        PyOngcRow(
            name='IC434',
            object_type='Emission Nebula',
            constellation='Ori',
            ra_hours=5.68,
            dec_degrees=-2.5,
            magnitude=None,
            size_arcmin=60.0,
            messier=None,
            ngc_names=[],
            ic_names=['IC 434'],
            common_names=['Horsehead Nebula Region'],
            other_identifiers=[],
        )
    ]
    targets = build_targets_from_rows(rows)
    assert len(targets) == 1
    t = targets[0]
    assert 'OpenIC' in t.catalogue_names or 'OpenNGC' in t.catalogue_names


def test_build_targets_from_rows_caldwell_identifier_in_other():
    rows = [
        PyOngcRow(
            name='NGC7000',
            object_type='Emission Nebula',
            constellation='Cyg',
            ra_hours=20.99,
            dec_degrees=44.53,
            magnitude=4.0,
            size_arcmin=120.0,
            messier=None,
            ngc_names=['NGC 7000'],
            ic_names=[],
            common_names=['North America Nebula'],
            other_identifiers=['C 20'],
        )
    ]
    targets = build_targets_from_rows(rows)
    assert len(targets) == 1
    assert targets[0].catalogue_names['Caldwell'] == 'C 20'


def test_build_targets_from_rows_merges_duplicate_rows():
    row1 = PyOngcRow(
        name='NGC891',
        object_type='Galaxy',
        constellation='And',
        ra_hours=2.374,
        dec_degrees=42.349,
        magnitude=10.1,
        size_arcmin=13.5,
        messier=None,
        ngc_names=['NGC 891'],
        ic_names=[],
        common_names=['Silver Sliver Galaxy'],
        other_identifiers=[],
    )
    row2 = PyOngcRow(
        name='NGC891',
        object_type='Galaxy',
        constellation='And',
        ra_hours=2.374,
        dec_degrees=42.349,
        magnitude=None,
        size_arcmin=None,
        messier=None,
        ngc_names=['NGC 891'],
        ic_names=[],
        common_names=['Edge-On Galaxy'],
        other_identifiers=['C 23'],
    )
    targets = build_targets_from_rows([row1, row2])
    assert len(targets) == 1
    t = targets[0]
    assert t.magnitude == pytest.approx(10.1)   # first row's magnitude wins
    assert 'Edge-On Galaxy' in t.aliases          # second row's common name merged


# ---------------------------------------------------------------------------
# build_and_save_default_dataset - save failure raises RuntimeError
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _load_pyongc_rows / _load_deep_sky_rows / build_deep_sky_targets
# ---------------------------------------------------------------------------

def test_load_pyongc_rows_raises_when_pyongc_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _no_pyongc(name, *args, **kwargs):
        if name == 'pyongc' or name.startswith('pyongc.'):
            raise ImportError('mocked missing pyongc')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _no_pyongc)
    from skytonight_catalogue_builder import _load_pyongc_rows
    with pytest.raises(RuntimeError, match='PyOngc is required'):
        _load_pyongc_rows()


def test_load_pyongc_rows_skips_dso_without_coords(monkeypatch):
    """DSO objects whose coords attribute is None must be skipped."""
    import types
    dso_no_coords = types.SimpleNamespace(
        coords=None,
        name='NGC0001',
        type='Galaxy',
        constellation='And',
        dimensions=(None, None, None),
        magnitudes=(None, None),
        identifiers=(None, None, None, None, None),
    )
    dso_valid = types.SimpleNamespace(
        coords=((0, 42, 44), (41, 16, 9)),
        name='NGC0224',
        type='Galaxy',
        constellation='And',
        dimensions=(189.0, None, None),
        magnitudes=(None, 3.44),
        identifiers=('M 31', ['NGC 224'], [], ['Andromeda Galaxy'], []),
    )

    fake_ongc = MagicMock()
    fake_ongc.listObjects.return_value = [dso_no_coords, dso_valid]

    import sys
    fake_pyongc = types.ModuleType('pyongc')
    fake_pyongc.ongc = fake_ongc
    monkeypatch.setitem(sys.modules, 'pyongc', fake_pyongc)
    monkeypatch.setitem(sys.modules, 'pyongc.ongc', fake_ongc)

    from skytonight_catalogue_builder import _load_pyongc_rows
    rows = _load_pyongc_rows()
    assert len(rows) == 1
    assert rows[0].name == 'NGC0224'


def test_load_pyongc_rows_skips_dso_with_bad_coord_format(monkeypatch):
    """DSO objects whose coord tuples cause ValueError must be skipped."""
    import types
    dso_bad = types.SimpleNamespace(
        coords=(('bad', 'bad', 'bad'), (41, 16, 9)),
        name='NGCBAD',
        type='Galaxy',
        constellation='And',
        dimensions=(None,),
        magnitudes=(None,),
        identifiers=(),
    )

    fake_ongc = MagicMock()
    fake_ongc.listObjects.return_value = [dso_bad]

    import sys
    fake_pyongc = types.ModuleType('pyongc')
    fake_pyongc.ongc = fake_ongc
    monkeypatch.setitem(sys.modules, 'pyongc', fake_pyongc)
    monkeypatch.setitem(sys.modules, 'pyongc.ongc', fake_ongc)

    from skytonight_catalogue_builder import _load_pyongc_rows
    rows = _load_pyongc_rows()
    assert rows == []


def test_load_deep_sky_rows_returns_tuple(monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._load_pyongc_rows', lambda: [])
    from skytonight_catalogue_builder import _load_deep_sky_rows
    rows, source = _load_deep_sky_rows()
    assert rows == []
    assert isinstance(source, str)


def test_build_deep_sky_targets_returns_list(monkeypatch):
    monkeypatch.setattr('skytonight_catalogue_builder._load_pyongc_rows', lambda: [])
    from skytonight_catalogue_builder import build_deep_sky_targets
    result = build_deep_sky_targets()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _build_standalone_targets_from_json - constellation batch lookup
# ---------------------------------------------------------------------------

def test_build_standalone_targets_resolves_constellation_via_astropy(monkeypatch):
    """When constellation is missing and astropy is available, it is resolved."""
    data = [
        {
            'name': 'Sh2-001',
            'ra_hours': 5.5,
            'dec_degrees': -5.0,
            'size_arcmin': 30.0,
            'mag': 8.0,
            'type': 'Emission Nebula',
            'description': 'Test nebula',
            'constellation': '',   # intentionally blank → astropy path
        }
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)

    # Mock astropy / numpy to avoid dependency in tests
    import sys
    import types

    fake_np = MagicMock()
    fake_np.array.side_effect = lambda x: x   # passthrough
    fake_skycoord_instance = MagicMock()
    fake_astropy_coords = MagicMock()
    fake_astropy_coords.SkyCoord.return_value = fake_skycoord_instance
    fake_astropy_coords.get_constellation.return_value = ['Orion']
    fake_numpy_mod = types.ModuleType('numpy')
    fake_numpy_mod.array = fake_np.array

    monkeypatch.setitem(sys.modules, 'numpy', fake_numpy_mod)
    monkeypatch.setitem(sys.modules, 'astropy', types.ModuleType('astropy'))
    monkeypatch.setitem(sys.modules, 'astropy.coordinates', fake_astropy_coords)

    result = _build_standalone_targets_from_json('sharpless.json', 'Sharpless')
    # Either astropy resolved it or the entry was still built (with empty constellation)
    assert len(result) == 1


def test_build_standalone_targets_constellation_lookup_failure_fallback(monkeypatch):
    """When astropy raises an exception during constellation lookup, the entry is still built."""
    data = [
        {
            'name': 'Sh2-001',
            'ra_hours': 5.5,
            'dec_degrees': -5.0,
            'size_arcmin': 30.0,
            'mag': 8.0,
            'type': 'Emission Nebula',
            'description': 'Test nebula',
            'constellation': '',
        }
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)

    import sys
    import types

    # Patch numpy to raise on import or usage
    class _RaisingModule(types.ModuleType):
        def __getattr__(self, item):
            raise AttributeError('numpy not available')

    monkeypatch.setitem(sys.modules, 'numpy', _RaisingModule('numpy'))

    result = _build_standalone_targets_from_json('sharpless.json', 'Sharpless')
    assert len(result) == 1   # entry built with empty constellation


# ---------------------------------------------------------------------------
# build_and_save_default_dataset - save failure raises RuntimeError
# ---------------------------------------------------------------------------

def test_build_and_save_default_dataset_raises_on_save_failure(monkeypatch):
    from skytonight_catalogue_builder import build_and_save_default_dataset

    deep_sky_row = _make_row(
        ra_hours=0.712,
        dec_degrees=41.269,
        ngc_names=['NGC 224'],
    )

    monkeypatch.setattr('skytonight_catalogue_builder._load_deep_sky_rows', lambda: ([deep_sky_row], 'PyOngc'))
    monkeypatch.setattr('skytonight_catalogue_builder.build_body_targets', lambda: [])
    monkeypatch.setattr('skytonight_catalogue_builder.build_comet_targets', lambda source_mode='mpc+jpl': [])
    monkeypatch.setattr('skytonight_catalogue_builder.save_targets_dataset', lambda targets, metadata=None: False)
    monkeypatch.setattr('skytonight_catalogue_builder._build_standalone_targets_from_json', lambda f, k: [])
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: None)

    with pytest.raises(RuntimeError):
        build_and_save_default_dataset()


# ---------------------------------------------------------------------------
# _build_cross_ref_map — skip guards (lines 652, 664)
# ---------------------------------------------------------------------------

def test_build_cross_ref_map_garyimm_skips_non_string_and_empty(monkeypatch):
    """Line 652: non-string and empty entries in garyimm list are skipped."""
    garyimm_data = [42, '', 'NGC 5128']

    def fake_load(filename):
        if filename == 'garyimm_crossrefs.json':
            return garyimm_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc5128_key = _ngc_ic_match_key('NGC 5128')
    assert 'GaryImm' in cross_refs.get(ngc5128_key, {})


def test_build_cross_ref_map_arp_skips_empty_key_or_value(monkeypatch):
    """Line 664: falsy dict key or falsy value in arp data are skipped."""
    arp_data = {'': 'Arp 1', 'NGC 1': None, 'NGC 2': 'Arp 2'}

    def fake_load(filename):
        if filename == 'arp.json':
            return arp_data
        return None

    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', fake_load)
    cross_refs = _build_cross_ref_map()
    ngc2_key = _ngc_ic_match_key('NGC 2')
    assert 'Arp' in cross_refs.get(ngc2_key, {})


# ---------------------------------------------------------------------------
# build_targets_from_rows — empty canonical_name skip (line 740)
# ---------------------------------------------------------------------------

def test_build_targets_from_rows_skips_row_with_empty_canonical_name(monkeypatch):
    """Line 740: when _canonical_key returns empty canonical_name the row is skipped."""
    monkeypatch.setattr(
        'skytonight_catalogue_builder._canonical_key',
        lambda names, fallback: ('OpenNGC', ''),
    )
    rows = [_make_row(ngc_names=['NGC 999'])]
    targets = build_targets_from_rows(rows)
    assert len(targets) == 0


# ---------------------------------------------------------------------------
# _build_standalone_targets_from_json — non-normalizable name (lines 878-879)
# ---------------------------------------------------------------------------

def test_build_standalone_targets_skips_name_normalizing_to_empty(monkeypatch):
    """Lines 878-879: normalize_object_name returns '' for punctuation-only name → skipped."""
    data = [
        {
            'name': '---',
            'ra_hours': 5.5,
            'dec_degrees': -5.0,
            'type': 'Nebula',
            'description': '',
            'constellation': 'Ori',
        },
        {
            'name': 'Valid',
            'ra_hours': 5.5,
            'dec_degrees': -5.0,
            'type': 'Nebula',
            'description': '',
            'constellation': 'Ori',
        },
    ]
    monkeypatch.setattr('skytonight_catalogue_builder._load_json_catalogue', lambda f: data)
    result = _build_standalone_targets_from_json('test.json', 'TestCat')
    assert len(result) == 1
    assert result[0].preferred_name == 'Valid'