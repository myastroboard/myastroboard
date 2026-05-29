"""Tests for object_info.py — pure functions and mocked-network paths."""

import skytonight_targets as _st_module  # needed for patching the locally-imported get_lookup_entry

import object_info as oi
from object_info import (
    _get_dss_image_url,
    _is_wikipedia_candidate,
    _normalize_wikipedia_term,
    _sanitize_lang,
    _simbad_identifier_variants,
    _sort_aliases,
    build_catalogue_names_from_aliases,
    get_object_info,
    is_safe_identifier,
)


# ---------------------------------------------------------------------------
# is_safe_identifier
# ---------------------------------------------------------------------------

def test_is_safe_identifier_accepts_simple_names():
    assert is_safe_identifier('NGC 224') is True
    assert is_safe_identifier('M 31') is True
    assert is_safe_identifier('alpha Cen') is True


def test_is_safe_identifier_accepts_special_chars():
    assert is_safe_identifier('C/2023 A3') is True
    assert is_safe_identifier("alpha Cen A'") is True
    assert is_safe_identifier('HD 209458') is True


def test_is_safe_identifier_rejects_empty_string():
    assert is_safe_identifier('') is False


def test_is_safe_identifier_rejects_too_long():
    assert is_safe_identifier('A' * 65) is False
    assert is_safe_identifier('A' * 64) is True


def test_is_safe_identifier_rejects_disallowed_chars():
    assert is_safe_identifier('NGC<224>') is False
    assert is_safe_identifier('M31;DROP') is False
    assert is_safe_identifier('obj\x00null') is False
    assert is_safe_identifier('name&more') is False


# ---------------------------------------------------------------------------
# _sanitize_lang
# ---------------------------------------------------------------------------

def test_sanitize_lang_passes_known_langs():
    for lang in ('en', 'fr', 'de', 'es', 'it', 'pt'):
        assert _sanitize_lang(lang) == lang


def test_sanitize_lang_falls_back_to_en_for_unknown():
    assert _sanitize_lang('xx') == 'en'
    assert _sanitize_lang('') == 'en'
    assert _sanitize_lang('zz') == 'en'


def test_sanitize_lang_rejects_injection_attempt():
    assert _sanitize_lang('en; rm -rf /') == 'en'


# ---------------------------------------------------------------------------
# _sort_aliases
# ---------------------------------------------------------------------------

def test_sort_aliases_messier_comes_first():
    aliases = ['NGC 224', 'M 31', 'UGC 454']
    sorted_aliases = _sort_aliases(aliases)
    assert sorted_aliases[0] == 'M 31'


def test_sort_aliases_ngc_before_ugc():
    aliases = ['UGC 2837', 'NGC 1068']
    result = _sort_aliases(aliases)
    assert result[0] == 'NGC 1068'


def test_sort_aliases_survey_identifiers_come_last():
    aliases = ['NGC 4258', 'NVSS J1233+4234', '2MASS J1234+5678']
    result = _sort_aliases(aliases)
    assert result[0] == 'NGC 4258'
    for survey_alias in ('NVSS J1233+4234', '2MASS J1234+5678'):
        assert survey_alias in result[-2:]


def test_sort_aliases_empty_list_returns_empty():
    assert _sort_aliases([]) == []


def test_sort_aliases_preserves_all_entries():
    aliases = ['M 31', 'NGC 224', 'Andromeda Galaxy']
    result = _sort_aliases(aliases)
    assert set(result) == set(aliases)


# ---------------------------------------------------------------------------
# build_catalogue_names_from_aliases
# ---------------------------------------------------------------------------

def test_build_catalogue_names_includes_messier():
    result = build_catalogue_names_from_aliases('M 31', ['NGC 224'])
    assert result.get('Messier') == 'M 31'


def test_build_catalogue_names_includes_ngc():
    result = build_catalogue_names_from_aliases('NGC 224', ['M 31'])
    assert result.get('OpenNGC') == 'NGC 224'


def test_build_catalogue_names_includes_multiple_catalogues():
    result = build_catalogue_names_from_aliases('M 31', ['NGC 224', 'UGC 454'])
    assert 'Messier' in result
    assert 'OpenNGC' in result
    assert 'UGC' in result


def test_build_catalogue_names_falls_back_to_simbad_for_unknown():
    result = build_catalogue_names_from_aliases('SomeStar XY', [])
    assert result == {'Simbad': 'SomeStar XY'}


def test_build_catalogue_names_no_duplicate_catalogue_keys():
    result = build_catalogue_names_from_aliases('M 31', ['M 31', 'M 31'])
    assert list(result.keys()).count('Messier') == 1


# ---------------------------------------------------------------------------
# _is_wikipedia_candidate
# ---------------------------------------------------------------------------

def test_is_wikipedia_candidate_accepts_normal_names():
    assert _is_wikipedia_candidate('NGC 224') is True
    assert _is_wikipedia_candidate('Andromeda Galaxy') is True
    assert _is_wikipedia_candidate('M 31') is True


def test_is_wikipedia_candidate_rejects_simbad_catalog_style():
    assert _is_wikipedia_candidate('[LB2005] NGC 3031 X1') is False
    assert _is_wikipedia_candidate('[HB89] 0951+699') is False


# ---------------------------------------------------------------------------
# _normalize_wikipedia_term
# ---------------------------------------------------------------------------

def test_normalize_wikipedia_term_collapses_whitespace():
    assert _normalize_wikipedia_term('M  82') == 'M 82'
    assert _normalize_wikipedia_term('  NGC  224  ') == 'NGC 224'


def test_normalize_wikipedia_term_preserves_single_spaces():
    assert _normalize_wikipedia_term('NGC 224') == 'NGC 224'


# ---------------------------------------------------------------------------
# _get_dss_image_url
# ---------------------------------------------------------------------------

def test_get_dss_image_url_contains_ra_dec():
    url = _get_dss_image_url(ra=10.684, dec=41.269)
    assert '10.684000' in url
    assert '41.269000' in url


def test_get_dss_image_url_contains_hips_identifier():
    url = _get_dss_image_url(ra=0.0, dec=0.0)
    assert 'DSS2' in url


def test_get_dss_image_url_accepts_custom_fov():
    url_small = _get_dss_image_url(ra=0.0, dec=0.0, size_deg=0.25)
    url_large = _get_dss_image_url(ra=0.0, dec=0.0, size_deg=1.0)
    assert '0.250' in url_small
    assert '1.000' in url_large


# ---------------------------------------------------------------------------
# get_object_info — unsafe identifier
# ---------------------------------------------------------------------------

def test_get_object_info_rejects_unsafe_identifier():
    result = get_object_info('NGC<224>')
    assert result['error'] == 'invalid_identifier'
    assert result['id'] == ''
    assert result['name'] == ''
    assert result['image'] is None


# ---------------------------------------------------------------------------
# get_object_info — not found (mocked SIMBAD returning None)
# ---------------------------------------------------------------------------

def test_get_object_info_returns_not_found_when_simbad_empty(monkeypatch):
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: None)
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: {})

    result = get_object_info('NGC 9999999')

    assert result['error'] == 'not_found'
    assert result['id'] == 'NGC 9999999'
    assert result['image'] is None
    assert result['description'] is None


# ---------------------------------------------------------------------------
# get_object_info — found with coordinates (mocked full pipeline)
# ---------------------------------------------------------------------------

def test_get_object_info_builds_image_url_when_coordinates_present(monkeypatch):
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: {
        'id': 'NGC 224',
        'name': 'NGC 224',
        'type': 'Galaxy',
        'ra': 10.684,
        'dec': 41.269,
        'aliases': ['M 31', 'Andromeda Galaxy'],
    })
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: None)
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: None)

    result = get_object_info('NGC 224')

    assert 'error' not in result
    assert result['id'] == 'NGC 224'
    assert result['image'] is not None
    assert '10.684000' in result['image']['url']
    assert result['description'] is None  # Wikipedia mocked to None


def test_get_object_info_includes_wikipedia_when_found(monkeypatch):
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: {
        'id': 'M 31',
        'name': 'M 31',
        'type': 'Galaxy',
        'ra': 10.684,
        'dec': 41.269,
        'aliases': ['NGC 224'],
    })
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: {
        'title': 'Andromeda Galaxy',
        'description': 'spiral galaxy',
        'extract': 'The Andromeda Galaxy is a spiral galaxy.',
    })
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: None)

    result = get_object_info('M 31')

    assert result['description'] == 'The Andromeda Galaxy is a spiral galaxy.'
    assert result['description_title'] == 'Andromeda Galaxy'


# ---------------------------------------------------------------------------
# _simbad_identifier_variants
# ---------------------------------------------------------------------------

def test_simbad_variants_vdb():
    assert _simbad_identifier_variants('vdB 146') == ['VdB 146']
    assert _simbad_identifier_variants('vdB 1') == ['VdB 1']


def test_simbad_variants_sh2():
    assert _simbad_identifier_variants('Sh2-1') == ['Sh 2-1']
    assert _simbad_identifier_variants('Sh2-155') == ['Sh 2-155']


def test_simbad_variants_barnard():
    assert _simbad_identifier_variants('Barnard 33') == ['B  33']
    assert _simbad_identifier_variants('Barnard 1') == ['B  1']


def test_simbad_variants_abell():
    assert _simbad_identifier_variants('Abell 33') == ['PN A66  33', 'ACO  33']
    assert _simbad_identifier_variants('Abell 426') == ['PN A66  426', 'ACO  426']


def test_simbad_variants_unknown_returns_empty():
    assert _simbad_identifier_variants('NGC 224') == []
    assert _simbad_identifier_variants('M 31') == []
    assert _simbad_identifier_variants('IC 1805') == []


# ---------------------------------------------------------------------------
# get_object_info — local dataset fallback when SIMBAD has no record
# ---------------------------------------------------------------------------

def test_get_object_info_local_fallback_when_simbad_fails(monkeypatch):
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: None)
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: {
        'preferred_name': 'vdB 146',
        'object_type': 'Reflection Nebula',
        'ra_deg': 336.06,
        'dec_deg': 68.15,
    })
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: None)

    result = get_object_info('vdB 146')

    assert 'error' not in result
    assert result['name'] == 'vdB 146'
    assert result['type'] == 'Reflection Nebula'
    assert result['coordinates'] == {'ra': 336.06, 'dec': 68.15}
    assert result['image'] is not None
    assert '336.060000' in result['image']['url']


def test_get_object_info_variant_lookup_succeeds(monkeypatch):
    calls = []

    def mock_resolve(identifier):
        calls.append(identifier)
        if identifier == 'VdB 146':
            return {'id': 'VdB 146', 'name': 'VdB 146', 'type': 'RNe', 'ra': 336.06, 'dec': 68.15, 'aliases': []}
        return None

    monkeypatch.setattr(oi, '_resolve_via_simbad', mock_resolve)
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: {})
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: None)

    result = get_object_info('vdB 146')

    assert 'error' not in result
    assert result['coordinates'] == {'ra': 336.06, 'dec': 68.15}
    assert 'vdB 146' in calls
    assert 'VdB 146' in calls


# ---------------------------------------------------------------------------

def test_get_object_info_no_image_when_coordinates_absent(monkeypatch):
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: {
        'id': 'SomeStar',
        'name': 'SomeStar',
        'type': 'Star',
        'ra': None,
        'dec': None,
        'aliases': [],
    })
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: None)
    monkeypatch.setattr(_st_module, 'get_lookup_entry', lambda *a, **kw: None)

    result = get_object_info('SomeStar')

    assert result['image'] is None
    assert result['coordinates'] is None
