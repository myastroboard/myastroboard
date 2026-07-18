"""Tests for object_info.py - pure functions and mocked-network paths."""

import os

import pytest

from skytonight import skytonight_targets as _st_module  # needed for patching the locally-imported get_lookup_entry

from observation import object_info as oi

# Captured at import time, before the autouse fixture below mocks these out, so tests
# that need the *real* disk-persistence behaviour can restore them explicitly.
_REAL_LOAD_BACKOFF_STATE = oi._load_backoff_state
_REAL_SAVE_BACKOFF_STATE = oi._save_backoff_state

_get_dss_image_url = oi._get_dss_image_url
_is_wikipedia_candidate = oi._is_wikipedia_candidate
_normalize_wikipedia_term = oi._normalize_wikipedia_term
_sanitize_lang = oi._sanitize_lang
_simbad_identifier_variants = oi._simbad_identifier_variants
_sort_aliases = oi._sort_aliases
_translate_object_type = oi._translate_object_type
build_catalogue_names_from_aliases = oi.build_catalogue_names_from_aliases
get_object_info = oi.get_object_info
is_safe_identifier = oi.is_safe_identifier


@pytest.fixture(autouse=True)
def _reset_object_info_backoff(monkeypatch):
    """Isolate the upstream-backoff state (module-level dict + disk file) between tests.

    Without this, a test that simulates a SIMBAD/Wikipedia/hips2fits failure would
    trip the backoff and silently short-circuit every later test's network call
    for _BACKOFF_TTL seconds.
    """
    oi._backoff_until.clear()
    monkeypatch.setattr(oi, '_load_backoff_state', lambda: {})
    monkeypatch.setattr(oi, '_save_backoff_state', lambda: None)
    yield
    oi._backoff_until.clear()


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
# get_object_image_proxy_url / parse_object_image_filename / ensure_cached_object_image
# ---------------------------------------------------------------------------


def test_get_object_image_proxy_url_format():
    url = oi.get_object_image_proxy_url(ra=10.684, dec=41.269)
    assert url == '/api/object-image/10.684000_41.269000.jpg'


def test_parse_object_image_filename_round_trips():
    assert oi.parse_object_image_filename('10.684000_41.269000.jpg') == (10.684, 41.269)


def test_parse_object_image_filename_rejects_bad_format():
    assert oi.parse_object_image_filename('not-a-filename.jpg') is None
    assert oi.parse_object_image_filename('../../etc/passwd') is None
    assert oi.parse_object_image_filename('10.684000_41.269000.png') is None


def test_parse_object_image_filename_rejects_out_of_range_coordinates():
    assert oi.parse_object_image_filename('400.000000_0.000000.jpg') is None
    assert oi.parse_object_image_filename('0.000000_100.000000.jpg') is None


def test_parse_object_image_filename_wraps_exact_360_boundary():
    """f'{ra:.6f}' can round a value just under 360 up to the literal '360.000000' -
    that exact boundary artifact should wrap to 0.0 rather than being rejected."""
    assert oi.parse_object_image_filename('360.000000_5.000000.jpg') == (0.0, 5.0)


def test_ensure_cached_object_image_returns_none_on_request_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(oi, 'OBJECT_IMAGE_CACHE_DIR', str(tmp_path))
    with patch('observation.object_info.requests.get', side_effect=_req_module.RequestException('timeout')):
        result = oi.ensure_cached_object_image(ra=10.684, dec=41.269)
    assert result is None


def test_ensure_cached_object_image_fetches_and_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(oi, 'OBJECT_IMAGE_CACHE_DIR', str(tmp_path))
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_content.return_value = [b'fake-jpeg-bytes']

    with patch('observation.object_info.requests.get', return_value=mock_resp) as mock_get:
        result = oi.ensure_cached_object_image(ra=10.684, dec=41.269)

    expected_path = os.path.join(str(tmp_path), '10.684000_41.269000.jpg')
    assert result == expected_path
    mock_get.assert_called_once()
    assert os.path.isfile(expected_path)
    with open(expected_path, 'rb') as f:
        assert f.read() == b'fake-jpeg-bytes'


def test_ensure_cached_object_image_serves_from_disk_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(oi, 'OBJECT_IMAGE_CACHE_DIR', str(tmp_path))
    expected_path = os.path.join(str(tmp_path), '10.684000_41.269000.jpg')
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(expected_path, 'wb') as f:
        f.write(b'already-cached-bytes')

    with patch('observation.object_info.requests.get') as mock_get:
        result = oi.ensure_cached_object_image(ra=10.684, dec=41.269)

    assert result == expected_path
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# get_object_info - unsafe identifier
# ---------------------------------------------------------------------------

def test_get_object_info_rejects_unsafe_identifier():
    result = get_object_info('NGC<224>')
    assert result['error'] == 'invalid_identifier'
    assert result['id'] == ''
    assert result['name'] == ''
    assert result['image'] is None


# ---------------------------------------------------------------------------
# get_object_info - not found (mocked SIMBAD returning None)
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
# get_object_info - found with coordinates (mocked full pipeline)
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
# get_object_info - local dataset fallback when SIMBAD has no record
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


# ---------------------------------------------------------------------------
# _simbad_query — covers lines 109-125
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock
import requests as _req_module


class TestSimbadQuery:
    """Direct tests for _simbad_query with mocked HTTP."""

    def test_returns_json_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [["M 31", "Galaxy", 10.68, 41.27]],
            "metadata": [{"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}],
        }
        mock_resp.raise_for_status.return_value = None

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._simbad_query("SELECT * FROM basic")

        assert result is not None
        assert "data" in result

    def test_returns_none_on_request_exception(self):
        with patch("observation.object_info.requests.get", side_effect=_req_module.RequestException("timeout")):
            result = oi._simbad_query("SELECT * FROM basic")

        assert result is None


# ---------------------------------------------------------------------------
# _resolve_via_simbad — covers lines 203-241
# ---------------------------------------------------------------------------


class TestResolveViaSimbad:
    """Direct tests for _resolve_via_simbad with mocked _simbad_query."""

    def test_returns_none_when_simbad_fails(self):
        with patch("observation.object_info._simbad_query", return_value=None):
            assert oi._resolve_via_simbad("M31") is None

    def test_returns_none_when_data_empty(self):
        with patch("observation.object_info._simbad_query", return_value={"data": [], "metadata": []}):
            assert oi._resolve_via_simbad("M31") is None

    def test_returns_resolved_dict(self):
        main_result = {
            "data": [["M 31", "Galaxy", 10.684, 41.269]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        alias_result = {
            "data": [["M 31"], ["NGC 224"], ["Andromeda Galaxy"]],
            "metadata": [{"name": "id"}],
        }

        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else alias_result

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            result = oi._resolve_via_simbad("M31")

        assert result is not None
        assert result["id"] == "M 31"
        assert result["type"] == "Galaxy"
        assert "NGC 224" in result["aliases"] or "M 31" in result["aliases"]

    def test_alias_matching_identifier_is_excluded(self):
        """The alias identical to the user's search identifier is skipped (it's already
        the modal title) - other aliases, including ones equal to main_id, are kept."""
        main_result = {
            "data": [["NGC 224", "Galaxy", 10.684, 41.269]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        alias_result = {
            "data": [["M 100"], [""], ["NGC 224"], ["Andromeda Galaxy"]],
            "metadata": [{"name": "id"}],
        }
        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else alias_result

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            result = oi._resolve_via_simbad("M 100")

        assert "M 100" not in result["aliases"]
        assert "" not in result["aliases"]
        assert "Andromeda Galaxy" in result["aliases"]

    def test_handles_none_alias_result(self):
        main_result = {
            "data": [["Some Star", "Star", None, None]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else None

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            result = oi._resolve_via_simbad("SomeStar")

        assert result is not None
        assert result["ra"] is None
        assert result["dec"] is None


# ---------------------------------------------------------------------------
# resolve_identifier_for_catalogue_lookup — covers lines 292-335
# ---------------------------------------------------------------------------


class TestResolveIdentifierForCatalogueLookup:
    """Tests for resolve_identifier_for_catalogue_lookup."""

    def test_returns_none_when_simbad_returns_none(self):
        with patch("observation.object_info._simbad_query", return_value=None):
            assert oi.resolve_identifier_for_catalogue_lookup("M31") is None

    def test_returns_none_when_data_empty(self):
        with patch("observation.object_info._simbad_query", return_value={"data": [], "metadata": []}):
            assert oi.resolve_identifier_for_catalogue_lookup("M31") is None

    def test_returns_dict_with_required_keys(self):
        main_result = {
            "data": [["M 31", "Galaxy", 10.684, 41.269]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        alias_result = {
            "data": [["M 31"], ["NGC 224"]],
            "metadata": [{"name": "id"}],
        }
        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else alias_result

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            result = oi.resolve_identifier_for_catalogue_lookup("M31")

        assert result is not None
        assert "object_type" in result
        assert "constellation" in result
        assert "aliases" in result
        assert result["object_type"] == "Galaxy"

    def test_blank_alias_rows_are_excluded(self):
        main_result = {
            "data": [["M 31", "Galaxy", 10.684, 41.269]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        alias_result = {
            "data": [[""], ["   "], ["NGC 224"]],
            "metadata": [{"name": "id"}],
        }
        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else alias_result

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            result = oi.resolve_identifier_for_catalogue_lookup("M31")

        assert result["aliases"] == ["NGC 224"]

    def test_handles_none_coordinates(self):
        main_result = {
            "data": [["Some Obj", "Star", None, None]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        with patch("observation.object_info._simbad_query", return_value=main_result):
            result = oi.resolve_identifier_for_catalogue_lookup("SomeStar")

        assert result is not None
        assert result["constellation"] == ''


# ---------------------------------------------------------------------------
# _get_wikipedia_summary — covers lines 400-431
# ---------------------------------------------------------------------------


class TestGetWikipediaSummary:
    """Tests for _get_wikipedia_summary with mocked HTTP."""

    def test_returns_dict_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "type": "standard",
            "title": "Andromeda Galaxy",
            "description": "Galaxy in constellation Andromeda",
            "extract": "The Andromeda Galaxy is a large spiral galaxy.",
        }

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._get_wikipedia_summary("Andromeda Galaxy")

        assert result is not None
        assert result["title"] == "Andromeda Galaxy"
        assert "spiral" in result["extract"]

    def test_returns_none_on_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._get_wikipedia_summary("NonExistentObject99999")

        assert result is None

    def test_returns_none_on_403(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._get_wikipedia_summary("SomeThing")

        assert result is None

    def test_returns_none_for_disambiguation_page(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"type": "disambiguation"}

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._get_wikipedia_summary("Andromeda")

        assert result is None

    def test_returns_none_when_extract_is_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"type": "standard", "extract": "   "}

        with patch("observation.object_info.requests.get", return_value=mock_resp):
            result = oi._get_wikipedia_summary("EmptyPage")

        assert result is None

    def test_returns_none_on_request_exception(self):
        with patch("observation.object_info.requests.get", side_effect=_req_module.RequestException("network err")):
            result = oi._get_wikipedia_summary("M31")

        assert result is None

    def test_uses_requested_language(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "type": "standard",
            "title": "Galaxie d'Andromède",
            "description": "galaxie spirale",
            "extract": "La galaxie d'Andromède est une grande galaxie spirale.",
        }

        with patch("observation.object_info.requests.get", return_value=mock_resp) as mock_get:
            result = oi._get_wikipedia_summary("Andromeda Galaxy", lang="fr")

        assert result is not None
        # Ensure the French Wikipedia URL was called
        call_url = mock_get.call_args[0][0]
        assert "fr.wikipedia" in call_url


# ---------------------------------------------------------------------------
# _wikipedia_with_fallback — covers lines 439-452
# ---------------------------------------------------------------------------


class TestWikipediaWithFallback:
    """Tests for _wikipedia_with_fallback."""

    def test_returns_first_found_result(self):
        found = {"title": "M 31", "description": "Galaxy", "extract": "A galaxy."}
        call_count = [0]

        def mock_summary(term, lang='en'):
            call_count[0] += 1
            if term == "M 31":
                return found
            return None

        with patch("observation.object_info._get_wikipedia_summary", side_effect=mock_summary):
            result = oi._wikipedia_with_fallback(["M 31", "NGC 224"], "en")

        assert result is not None
        assert result["title"] == "M 31"

    def test_falls_back_to_english_when_lang_fails(self):
        en_result = {"title": "M 31", "description": "Galaxy", "extract": "A galaxy."}

        def mock_summary(term, lang='en'):
            if lang == 'fr':
                return None
            return en_result

        with patch("observation.object_info._get_wikipedia_summary", side_effect=mock_summary):
            result = oi._wikipedia_with_fallback(["M 31"], "fr")

        assert result is not None

    def test_returns_none_when_all_fail(self):
        with patch("observation.object_info._get_wikipedia_summary", return_value=None):
            result = oi._wikipedia_with_fallback(["UnknownObj1", "UnknownObj2"], "en")

        assert result is None

    def test_english_fallback_tries_next_term_after_a_miss(self):
        """When the first alias has no English article, the fallback loop moves on to
        the next alias instead of giving up after the first miss."""
        en_result = {"title": "NGC 224", "description": "Galaxy", "extract": "A galaxy."}

        def mock_summary(term, lang='en'):
            if lang == 'fr':
                return None
            if term == "Andromeda I":
                return None  # first English attempt misses
            return en_result  # second English attempt hits

        with patch("observation.object_info._get_wikipedia_summary", side_effect=mock_summary):
            result = oi._wikipedia_with_fallback(["Andromeda I", "NGC 224"], "fr")

        assert result is not None
        assert result["title"] == "NGC 224"


# ---------------------------------------------------------------------------
# _translate_object_type — covers lines 511-516
# ---------------------------------------------------------------------------


def test_translate_object_type_english_passthrough():
    assert _translate_object_type("Galaxy", lang="en") == "Galaxy"


def test_translate_object_type_empty_passthrough():
    assert _translate_object_type("", lang="fr") == ""


def test_translate_object_type_non_english_returns_string():
    result = _translate_object_type("Galaxy", lang="fr")
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# get_object_info — cover branches 620->623, 625 (_local_entry fallback)
# ---------------------------------------------------------------------------


def test_get_object_info_uses_local_type_when_available(monkeypatch):
    """Cover lines 620-625: _local_entry found by SIMBAD main_id."""
    monkeypatch.setattr(oi, '_resolve_via_simbad', lambda identifier: {
        'id': 'NGC 224',
        'name': 'NGC 224',
        'type': 'Sb',  # raw SIMBAD type
        'ra': 10.684,
        'dec': 41.269,
        'aliases': ['M 31'],
    })
    monkeypatch.setattr(oi, '_wikipedia_with_fallback', lambda terms, lang: None)

    def local_lookup(kind, name):
        if name in ('NGC 224', 'M 31'):
            return {'preferred_name': 'NGC 224', 'object_type': 'Galaxy', 'ra_deg': 10.684, 'dec_deg': 41.269}
        return None

    monkeypatch.setattr(_st_module, 'get_lookup_entry', local_lookup)

    result = get_object_info('NGC 224')

    assert 'error' not in result
    assert result['type'] == 'Galaxy'


class TestResolveIdentifierSkyCoordException:
    """Lines 320-321: exception in astropy SkyCoord → constellation stays empty."""

    def test_skycoord_raises_constellation_defaults_to_empty(self):
        main_result = {
            "data": [["M 31", "Galaxy", 10.684, 41.269]],
            "metadata": [
                {"name": "main_id"}, {"name": "otype_txt"}, {"name": "ra"}, {"name": "dec"}
            ],
        }
        alias_result = {"data": [], "metadata": [{"name": "id"}]}
        call_count = [0]

        def mock_query(q):
            call_count[0] += 1
            return main_result if call_count[0] == 1 else alias_result

        with patch("observation.object_info._simbad_query", side_effect=mock_query):
            with patch("astropy.coordinates.SkyCoord", side_effect=RuntimeError("coords failed")):
                result = oi.resolve_identifier_for_catalogue_lookup("M31")

        assert result is not None
        assert result["constellation"] == ""


class TestWikipediaWithFallbackNonCandidates:
    """Lines 441, 448: SIMBAD-style aliases skipped as non-Wikipedia candidates."""

    def test_simbad_style_alias_skipped_in_first_loop(self):
        """Line 441: term starting with '[' fails _is_wikipedia_candidate → continue."""
        with patch("observation.object_info._get_wikipedia_summary") as mock_wiki:
            result = oi._wikipedia_with_fallback(["[HB89] 0951+699"], "en")
        assert result is None
        mock_wiki.assert_not_called()

    def test_simbad_style_alias_skipped_in_second_loop(self):
        """Line 448: term skipped in English fallback loop when lang != 'en'."""
        with patch("observation.object_info._get_wikipedia_summary") as mock_wiki:
            result = oi._wikipedia_with_fallback(["[HB89] 0951+699"], "fr")
        assert result is None


# ---------------------------------------------------------------------------
# Upstream backoff — prevents a burst of N object cards, each hitting a down
# service, from stacking into N x REQUEST_TIMEOUT of stalled requests.
# ---------------------------------------------------------------------------


class TestSimbadBackoff:

    def test_failure_triggers_backoff_for_subsequent_calls(self):
        with patch("observation.object_info.requests.get", side_effect=_req_module.RequestException("down")):
            assert oi._simbad_query("SELECT * FROM basic") is None

        # Second call must not touch the network at all - backoff should short-circuit it.
        with patch("observation.object_info.requests.get") as mock_get:
            assert oi._simbad_query("SELECT * FROM basic") is None
        mock_get.assert_not_called()

    def test_success_clears_backoff(self):
        oi._backoff_until['simbad'] = oi.time.time() - 1  # expired entry present
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": [], "metadata": []}
        with patch("observation.object_info.requests.get", return_value=mock_resp):
            oi._simbad_query("SELECT * FROM basic")
        assert 'simbad' not in oi._backoff_until

    def test_active_backoff_short_circuits_resolve(self):
        oi._backoff_until['simbad'] = oi.time.time() + 300
        with patch("observation.object_info.requests.get") as mock_get:
            assert oi._resolve_via_simbad("M31") is None
        mock_get.assert_not_called()


class TestWikipediaBackoff:

    def test_failure_triggers_backoff_for_subsequent_calls(self):
        with patch("observation.object_info.requests.get", side_effect=_req_module.RequestException("down")):
            assert oi._get_wikipedia_summary("M 31") is None

        with patch("observation.object_info.requests.get") as mock_get:
            assert oi._get_wikipedia_summary("NGC 224") is None
        mock_get.assert_not_called()

    def test_success_clears_backoff(self):
        oi._backoff_until['wikipedia'] = oi.time.time() - 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"type": "standard", "extract": "text"}
        with patch("observation.object_info.requests.get", return_value=mock_resp):
            oi._get_wikipedia_summary("M 31")
        assert 'wikipedia' not in oi._backoff_until


class TestHips2fitsBackoff:

    def test_failure_triggers_backoff_for_subsequent_calls(self, tmp_path):
        with patch.object(oi, 'OBJECT_IMAGE_CACHE_DIR', str(tmp_path)):
            with patch("observation.object_info.requests.get", side_effect=_req_module.RequestException("down")):
                assert oi.ensure_cached_object_image(10.684, 41.269) is None

            with patch("observation.object_info.requests.get") as mock_get:
                assert oi.ensure_cached_object_image(20.0, 30.0) is None
            mock_get.assert_not_called()

    def test_success_clears_backoff(self, tmp_path):
        oi._backoff_until['hips2fits'] = oi.time.time() - 1
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b'jpeg-bytes']
        with patch.object(oi, 'OBJECT_IMAGE_CACHE_DIR', str(tmp_path)):
            with patch("observation.object_info.requests.get", return_value=mock_resp):
                oi.ensure_cached_object_image(10.684, 41.269)
        assert 'hips2fits' not in oi._backoff_until


class TestBackoffStateRealPersistence:
    """Exercises the *real* (unmocked) disk-persistence implementation of the backoff
    state: the cross-worker file lock, the atomic temp-file write, and the mtime-gated
    re-read - all bypassed by the module's autouse mock in every other test here."""

    def _use_real_persistence(self, monkeypatch, tmp_path):
        monkeypatch.setattr(oi, '_load_backoff_state', _REAL_LOAD_BACKOFF_STATE)
        monkeypatch.setattr(oi, '_save_backoff_state', _REAL_SAVE_BACKOFF_STATE)
        monkeypatch.setattr(oi, '_BACKOFF_FILE', str(tmp_path / 'object_info_backoff.json'))
        monkeypatch.setattr(oi, '_BACKOFF_LOCK_FILE', str(tmp_path / 'object_info_backoff.lock'))
        monkeypatch.setattr(oi, '_backoff_state', {'mtime_seen': None})

    def test_load_missing_file_returns_empty_dict(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        assert oi._load_backoff_state() == {}

    def test_load_corrupted_file_returns_empty_dict(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        with open(oi._BACKOFF_FILE, 'w', encoding='utf-8') as fh:
            fh.write('{not valid json')
        assert oi._load_backoff_state() == {}

    def test_load_filters_out_expired_entries(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        import json
        os.makedirs(tmp_path, exist_ok=True)
        with open(oi._BACKOFF_FILE, 'w', encoding='utf-8') as fh:
            json.dump({'simbad': oi.time.time() - 10, 'wikipedia': oi.time.time() + 300}, fh)
        state = oi._load_backoff_state()
        assert 'simbad' not in state
        assert 'wikipedia' in state

    def test_save_then_load_round_trips_through_real_lock_and_atomic_write(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        oi._backoff_until['hips2fits'] = oi.time.time() + 300
        oi._save_backoff_state()
        assert os.path.exists(oi._BACKOFF_FILE)
        reloaded = oi._load_backoff_state()
        assert 'hips2fits' in reloaded

    def test_save_prunes_expired_entries_from_disk(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        oi._backoff_until['simbad'] = oi.time.time() - 10  # already expired
        oi._save_backoff_state()
        import json
        with open(oi._BACKOFF_FILE, encoding='utf-8') as fh:
            on_disk = json.load(fh)
        assert on_disk == {}

    def test_refresh_rereads_only_when_mtime_changes(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        oi._backoff_until['simbad'] = oi.time.time() + 300
        oi._save_backoff_state()

        # First refresh picks up the on-disk state written by another "worker".
        oi._backoff_until.clear()
        oi._refresh_backoff_state_if_changed()
        assert 'simbad' in oi._backoff_until

        # File untouched since -> a second refresh must not wipe in-memory state
        # (it would, if it always re-read rather than checking mtime first).
        oi._backoff_until['local_only'] = oi.time.time() + 300
        oi._refresh_backoff_state_if_changed()
        assert 'local_only' in oi._backoff_until

    def test_is_backed_off_and_trigger_and_clear_round_trip_via_disk(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        assert oi._is_backed_off('simbad') is False

        oi._trigger_backoff('simbad')
        assert oi._is_backed_off('simbad') is True

        oi._clear_backoff('simbad')
        assert oi._is_backed_off('simbad') is False

    def test_is_backed_off_clears_expired_entry_and_persists(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        oi._backoff_until['simbad'] = oi.time.time() - 1  # already expired, still in memory
        assert oi._is_backed_off('simbad') is False
        assert 'simbad' not in oi._backoff_until

    def test_save_failure_is_caught_and_logged(self, monkeypatch, tmp_path):
        self._use_real_persistence(monkeypatch, tmp_path)
        # Lock file's parent directory doesn't exist -> opening it raises, exercising the
        # outer try/except that keeps a persistence failure from ever propagating.
        monkeypatch.setattr(oi, '_BACKOFF_LOCK_FILE', str(tmp_path / 'missing_dir' / 'backoff.lock'))
        oi._backoff_until['simbad'] = oi.time.time() + 300
        oi._save_backoff_state()  # should not raise
        assert not os.path.exists(oi._BACKOFF_FILE)
