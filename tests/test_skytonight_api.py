"""API tests for SkyTonight report endpoints."""

import os
import sys
import tempfile
import types

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import app as app_module  # type: ignore[import-not-found]
from blueprints import skytonight_api as skytonight_api_module  # type: ignore[import-not-found]
from utils.auth import user_manager  # type: ignore[import-not-found]

app = app_module.app
from skytonight.skytonight_models import SkyTonightTarget  # type: ignore[import-not-found]


@pytest.fixture
def client_admin():
    app.config['TESTING'] = True
    with tempfile.TemporaryDirectory():
        with app.test_client() as test_client:
            user = user_manager.get_user_by_username('admin')
            assert user is not None
            with test_client.session_transaction() as session:
                session['user_id'] = user.user_id
                session['username'] = user.username
                session['role'] = user.role
            yield test_client


def _sample_targets():
    return [
        SkyTonightTarget(
            target_id='dso-openngc-ngc224',
            category='deep_sky',
            object_type='Galaxy',
            preferred_name='NGC 224',
            catalogue_names={'OpenNGC': 'NGC 224', 'Messier': 'M 31'},
            aliases=['Andromeda Galaxy'],
            constellation='Andromeda',
            magnitude=3.4,
            size_arcmin=189.0,
            source_catalogues=['OpenNGC', 'Messier'],
            translation_key='skytonight.type_galaxy',
        ),
        SkyTonightTarget(
            target_id='body-jupiter',
            category='bodies',
            object_type='Planet',
            preferred_name='Jupiter',
            catalogue_names={'Bodies': 'Jupiter'},
            aliases=[],
            source_catalogues=['Bodies'],
            translation_key='skytonight.type_planet',
            metadata={'source': 'builtin-solar-system'},
        ),
        SkyTonightTarget(
            target_id='comet-13polbers',
            category='comets',
            object_type='Comet',
            preferred_name='13P/Olbers',
            catalogue_names={'Comets': '13P/Olbers'},
            aliases=['13P'],
            source_catalogues=['Comets'],
            translation_key='skytonight.type_comet',
            metadata={'source': 'curated-fallback', 'perihelion_date': '2026-10-20'},
        ),
    ]


def test_skytonight_reports_endpoint_returns_compatible_payload(client_admin, monkeypatch):
    monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
    monkeypatch.setattr(
        skytonight_api_module.skytonight_targets,
        'load_targets_dataset',
        lambda *args, **kwargs: {'loaded': True, 'targets': _sample_targets(), 'metadata': {}},
    )
    monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_astrodex', lambda *args, **kwargs: False)
    monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *args, **kwargs: False)
    monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline', lambda *args, **kwargs: {'state': 'current'})
    monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda catalogue, item_name: ('', {}))

    response = client_admin.get('/api/skytonight/reports')
    assert response.status_code == 200

    payload = response.get_json()
    assert isinstance(payload['report'], list)
    assert isinstance(payload['bodies'], list)
    assert isinstance(payload['comets'], list)

    assert payload['report'][0]['id'] == 'NGC 224'
    assert payload['bodies'][0]['target name'] == 'Jupiter'
    assert payload['comets'][0]['target name'] == '13P/Olbers'
    assert payload['comets'][0]['q'] == '2026-10-20'


def test_skytonight_reports_catalogue_filter(client_admin, monkeypatch):
    monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
    monkeypatch.setattr(
        skytonight_api_module.skytonight_targets,
        'load_targets_dataset',
        lambda *args, **kwargs: {'loaded': True, 'targets': _sample_targets(), 'metadata': {}},
    )
    monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_astrodex', lambda *args, **kwargs: False)
    monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *args, **kwargs: False)
    monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline', lambda *args, **kwargs: {'state': 'current'})
    monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda catalogue, item_name: ('', {}))

    response = client_admin.get('/api/skytonight/reports/Messier')
    assert response.status_code == 200
    payload = response.get_json()

    assert len(payload['report']) == 1
    assert payload['report'][0]['id'] == 'M 31'


def test_skytonight_reports_catalogue_filter_rejects_invalid_name(client_admin):
    response = client_admin.get('/api/skytonight/reports/invalid$name')
    assert response.status_code == 400


def test_dso_annotation_uses_display_name_for_astrodex_matching(monkeypatch):
    calls = []

    def _capture_astrodex_call(_astrodex_data, item_name, catalogue=''):
        calls.append((item_name, catalogue))
        return False

    monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: True)
    monkeypatch.setattr(
        skytonight_api_module,
        'load_json_file',
        lambda *_args, **_kwargs: {
            'metadata': {},
            'deep_sky': [
                {
                    'target_id': 'dso-openngc-ngc5457',
                    'preferred_name': 'M 101',
                    'catalogue_names': {
                        'Messier': 'M 101',
                        'OpenNGC': 'NGC 5457',
                        'CommonName': 'Pinwheel Galaxy',
                    },
                    'object_type': 'Galaxy',
                    'constellation': 'UMa',
                    'magnitude': 7.9,
                    'size_arcmin': 28.8,
                    'astro_score': 0.81,
                    'observation': {},
                }
            ],
        },
    )
    monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda *_args, **_kwargs: {'items': []})
    monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', _capture_astrodex_call)
    monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline', lambda *_a, **_k: {'state': 'none'})

    payload = skytonight_api_module._build_dso_section_payload(None, 'uid-1', 'Emeric')

    assert payload['available'] is True
    assert calls == [('M 101', 'Messier')]


def test_skytonight_request_location_falls_back_outside_request_context(monkeypatch):
    """_skytonight_request_location() is also reached by callers with no Flask
    request context (e.g. tooling/background code). `session` access there
    raises RuntimeError, which must fall back to an anonymous lookup rather
    than propagate. Forced via monkeypatch so this doesn't depend on whether
    ambient context happens to be pushed by whatever test runs first."""
    monkeypatch.setattr(
        skytonight_api_module, 'load_config',
        lambda: {'locations': [{'id': 'solo-loc', 'is_install_default': True}]},
    )

    def _raise_outside_request_context():
        raise RuntimeError('Working outside of request context.')

    monkeypatch.setattr(skytonight_api_module, 'get_current_user', _raise_outside_request_context)

    location = skytonight_api_module._skytonight_request_location()

    assert location['id'] == 'solo-loc'


def test_skytonight_request_location_override_falls_back_outside_request_context(monkeypatch):
    """Same outside-request-context fallback as _skytonight_request_location,
    but for the pinned-location variant used by e.g. Plan My Night's alttime lookups."""
    monkeypatch.setattr(
        skytonight_api_module, 'load_config',
        lambda: {'locations': [{'id': 'solo-loc', 'is_install_default': True}]},
    )

    def _raise_outside_request_context():
        raise RuntimeError('Working outside of request context.')

    monkeypatch.setattr(skytonight_api_module, 'get_current_user', _raise_outside_request_context)

    location = skytonight_api_module._skytonight_request_location_override(None)

    assert location['id'] == 'solo-loc'


def test_skytonight_request_location_override_uses_accessible_pinned_location(monkeypatch):
    """A caller-supplied location_id that the viewer can access must override
    their currently-active preset (e.g. reading a plan's pinned location)."""
    monkeypatch.setattr(
        skytonight_api_module, 'load_config',
        lambda: {'locations': [
            {'id': 'loc-a', 'is_install_default': True},
            {'id': 'loc-b', 'is_install_default': False},
        ]},
    )
    monkeypatch.setattr(skytonight_api_module, 'get_current_user', lambda: None)
    monkeypatch.setattr(
        skytonight_api_module, 'get_locations_for_user',
        lambda config, user: config['locations'],
    )

    location = skytonight_api_module._skytonight_request_location_override('loc-b')

    assert location['id'] == 'loc-b'


def test_skytonight_request_location_override_falls_back_when_not_accessible(monkeypatch):
    """A location_id the viewer can't access (foreign/stale id) must fall back
    to their active preset rather than leaking another location's data."""
    monkeypatch.setattr(
        skytonight_api_module, 'load_config',
        lambda: {'locations': [{'id': 'loc-a', 'is_install_default': True}]},
    )
    monkeypatch.setattr(skytonight_api_module, 'get_current_user', lambda: None)
    monkeypatch.setattr(skytonight_api_module, 'get_locations_for_user', lambda config, user: config['locations'])

    location = skytonight_api_module._skytonight_request_location_override('not-accessible-loc')

    assert location['id'] == 'loc-a'


def test_skytonight_log_endpoint_returns_content(client_admin, monkeypatch, tmp_path):
    log_file = tmp_path / 'last_calculation.log'
    log_file.write_text('{"status":"success"}\n', encoding='utf-8')

    monkeypatch.setattr(skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
    monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda *args, **kwargs: {})

    response = client_admin.get('/api/skytonight/log')
    assert response.status_code == 200

    payload = response.get_json()
    assert isinstance(payload, dict)
    assert payload.get('log_content') == '{"status":"success"}\n'


# ---------------------------------------------------------------------------
# /api/skytonight/target-debug endpoint tests
# ---------------------------------------------------------------------------

def test_target_debug_missing_name_returns_400(client_admin):
    response = client_admin.get('/api/skytonight/target-debug')
    assert response.status_code == 400
    assert 'error' in response.get_json()


def test_target_debug_empty_name_returns_400(client_admin):
    response = client_admin.get('/api/skytonight/target-debug?name=')
    assert response.status_code == 400
    assert 'error' in response.get_json()


def test_target_debug_requires_login():
    app.config['TESTING'] = True
    with app.test_client() as unauthenticated:
        response = unauthenticated.get('/api/skytonight/target-debug?name=Jupiter')
    # login_required redirects unauthenticated requests
    assert response.status_code in (302, 401)


def test_target_debug_unknown_name_returns_found_false(client_admin, monkeypatch):
    monkeypatch.setattr(
        skytonight_api_module,
        'compute_target_debug',
        lambda name, config=None, location=None: {'found': False},
    )
    response = client_admin.get('/api/skytonight/target-debug?name=ZZZ_NoSuch')
    assert response.status_code == 200
    assert response.get_json() == {'found': False}


def test_target_debug_known_target_returns_debug_payload(client_admin, monkeypatch):
    fake_result = {
        'found': True,
        'overall': 'visible',
        'target': {'preferred_name': 'M 31', 'object_type': 'Galaxy'},
        'checks': [{'name': 'max_altitude', 'passed': True}],
        'constraints': {'horizon_active': False},
        'night_window': {'available': True},
        'alttime': {},
        'moon': None,
    }
    monkeypatch.setattr(
        skytonight_api_module,
        'compute_target_debug',
        lambda name, config=None, location=None: fake_result,
    )
    response = client_admin.get('/api/skytonight/target-debug?name=M+31')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['found'] is True
    assert payload['overall'] == 'visible'
    assert payload['constraints']['horizon_active'] is False


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestTargetAttr:
    """_target_attr when target is a dict."""

    def test_dict_target_returns_value(self):
        _target_attr = skytonight_api_module._target_attr
        assert _target_attr({'key': 'val'}, 'key') == 'val'

    def test_dict_target_returns_default(self):
        _target_attr = skytonight_api_module._target_attr
        assert _target_attr({}, 'missing', 'default') == 'default'

    def test_object_target_returns_attr(self):
        _target_attr = skytonight_api_module._target_attr
        obj = type('T', (), {'my_attr': 42})()
        assert _target_attr(obj, 'my_attr') == 42


class TestGetCatalogueAliasPayload:
    """_get_catalogue_alias_payload edge cases."""

    def test_empty_catalogue_returns_empty(self):
        _get_catalogue_alias_payload = skytonight_api_module._get_catalogue_alias_payload
        assert _get_catalogue_alias_payload('', 'item') == ('', {})

    def test_empty_item_name_returns_empty(self):
        _get_catalogue_alias_payload = skytonight_api_module._get_catalogue_alias_payload
        assert _get_catalogue_alias_payload('Messier', '') == ('', {})

    def test_entry_not_dict_returns_empty(self, monkeypatch):
        """entry is not a dict → return '', {}."""
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'get_lookup_entry', lambda c, n: 'not_a_dict')
        assert skytonight_api_module._get_catalogue_alias_payload('Messier', 'M 31') == ('', {})

    def test_aliases_not_dict_is_replaced(self, monkeypatch):
        """aliases not dict → replaced with {}."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'get_lookup_entry',
            lambda c, n: {'group_id': 'g1', 'aliases': 'bad_aliases'},
        )
        group_id, aliases = skytonight_api_module._get_catalogue_alias_payload('Messier', 'M 31')
        assert group_id == 'g1'
        assert aliases == {}


class TestResolveSourceCatalogue:
    """_resolve_source_catalogue branches."""

    def test_empty_catalogue_names_returns_skytonight(self):
        """catalogue_names is empty → return 'SkyTonight'."""
        _resolve_source_catalogue = skytonight_api_module._resolve_source_catalogue
        assert _resolve_source_catalogue({}, 'M 31') == 'SkyTonight'

    def test_none_catalogue_names_returns_skytonight(self):
        """catalogue_names is None → return 'SkyTonight'."""
        _resolve_source_catalogue = skytonight_api_module._resolve_source_catalogue
        assert _resolve_source_catalogue(None, 'M 31') == 'SkyTonight'  # type: ignore

    def test_matching_catalogue_is_returned(self, monkeypatch):
        """exact match found → return catalogue label."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'normalize_object_name',
            lambda name: name.lower().replace(' ', ''),
        )
        result = skytonight_api_module._resolve_source_catalogue({'Messier': 'M 31', 'OpenNGC': 'NGC 224'}, 'M 31')
        assert result == 'Messier'

    def test_no_match_returns_first_key(self, monkeypatch):
        """no exact match → return first key."""
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name', lambda name: 'no_match')
        result = skytonight_api_module._resolve_source_catalogue({'Messier': 'M 31'}, 'something_else')
        assert result == 'Messier'


class TestAnnotateSkytonigtItemEmptyName:
    """_annotate_skytonight_item when item_name is empty."""

    def test_empty_item_name_sets_defaults(self, monkeypatch):
        """item without name → in_astrodex=False, plan=False."""
        item = {}
        skytonight_api_module._annotate_skytonight_item(item, 'uid', 'user', 'Messier', 'current')
        assert item['in_astrodex'] is False
        assert item['in_plan_my_night'] is False
        assert item['catalogue_group_id'] == ''
        assert item['catalogue_aliases'] == {}
        assert item['plan_state'] == 'current'


# ---------------------------------------------------------------------------
# Payload builder tests with calc results enabled
# ---------------------------------------------------------------------------


def _make_calc_result():
    """Minimal calculation result to exercise the calc branch of payload builders."""
    return {
        'metadata': {'night_start': '2026-06-07T22:00:00', 'night_end': '2026-06-08T04:00:00'},
        'deep_sky': [
            {
                'target_id': 'dso-openngc-ngc224',
                'preferred_name': 'NGC 224',
                'catalogue_names': {'OpenNGC': 'NGC 224', 'Messier': 'M 31'},
                'object_type': 'Galaxy',
                'constellation': 'And',
                'magnitude': 3.4,
                'size_arcmin': 189.0,
                'astro_score': 0.9,
                'observation': {
                    'ra_hms': '00h 42m 44s',
                    'dec_dms': '+41° 16′ 09″',
                    'max_altitude': 55.0,
                    'observable_fraction': 0.8,
                    'observable_hours': 4.0,
                    'azimuth': 180.0,
                    'meridian_transit': '2026-06-07T23:00:00',
                    'antimeridian_transit': '2026-06-08T11:00:00',
                },
            }
        ],
        'bodies': [
            {
                'target_id': 'body-jupiter',
                'preferred_name': 'Jupiter',
                'object_type': 'Planet',
                'magnitude': -2.0,
                'astro_score': 0.8,
                'observation': {
                    'ra_hms': '03h 00m', 'dec_dms': '+16° 00′',
                    'max_altitude': 40.0, 'azimuth': 170.0,
                    'max_altitude_time': '23:00', 'meridian_transit': '23:00',
                    'antimeridian_transit': '11:00', 'observable_hours': 5.0,
                },
                'solar_elongation_deg': 120.0,
            }
        ],
        'comets': [
            {
                'target_id': 'comet-13P',
                'preferred_name': '13P/Olbers',
                'object_type': 'Comet',
                'magnitude': 7.0,
                'astro_score': 0.5,
                'metadata': {'perihelion_date': '2026-10-20', 'absolute_magnitude': 5.0,
                             'distance_earth_au': 1.2, 'distance_sun_au': 1.5},
                'observation': {
                    'ra_hms': '05h 00m', 'dec_dms': '+20° 00′',
                    'max_altitude': 35.0, 'azimuth': 160.0,
                    'rise_time': '21:00', 'set_time': '03:00',
                    'meridian_transit': '00:00', 'antimeridian_transit': '12:00',
                    'observable_hours': 6.0,
                },
            }
        ],
    }


class TestBuildSkytonigtReportsPayloadWithCalcResults:
    """Cover _build_skytonight_reports_payload with has_calculation_results=True."""

    def test_calc_results_path_returns_expected_structure(self, monkeypatch):
        """all branches in the calc results path."""
        calc = _make_calc_result()
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_calculation_results', lambda *_a, **_k: calc)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'current'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert isinstance(result['report'], list)
        assert len(result['report']) >= 1
        assert result['report'][0]['target name'] == 'NGC 224'

    def test_calc_results_with_catalogue_filter(self, monkeypatch):
        """catalogue filter skips non-matching items."""
        calc = _make_calc_result()
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_calculation_results', lambda *_a, **_k: calc)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

        result = skytonight_api_module._build_skytonight_reports_payload('Messier', 'uid-1', 'user1')
        assert isinstance(result['report'], list)
        # NGC 224 has Messier → should appear; canonical id is OpenNGC name
        assert any(r['id'] == 'NGC 224' for r in result['report'])


class TestBuildBodiesSectionPayloadWithCalcResults:
    """Cover _build_bodies_section_payload with has_bodies_results=True."""

    def test_bodies_calc_path(self, monkeypatch):
        """bodies payload from calc results."""
        calc = _make_calc_result()
        data = {'bodies': calc['bodies'], 'metadata': {}}
        monkeypatch.setattr(skytonight_api_module, 'has_bodies_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

        result = skytonight_api_module._build_bodies_section_payload('uid-1', 'user1')
        assert isinstance(result.get('bodies'), list)
        assert len(result['bodies']) >= 1
        assert result['bodies'][0]['target name'] == 'Jupiter'


class TestBuildCometsSectionPayloadWithCalcResults:
    """Cover _build_comets_section_payload with has_comets_results=True."""

    def test_comets_calc_path(self, monkeypatch):
        """comets payload from calc results."""
        calc = _make_calc_result()
        data = {'comets': calc['comets'], 'metadata': {}}
        monkeypatch.setattr(skytonight_api_module, 'has_comets_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

        result = skytonight_api_module._build_comets_section_payload('uid-1', 'user1')
        assert isinstance(result.get('comets'), list)
        assert len(result['comets']) >= 1
        assert result['comets'][0]['target name'] == '13P/Olbers'

    def test_comets_calc_path_metadata_not_dict(self, monkeypatch):
        """metadata is not dict → replaced with {}."""
        comet = dict(_make_calc_result()['comets'][0])
        comet['metadata'] = 'invalid'
        data = {'comets': [comet], 'metadata': {}}
        monkeypatch.setattr(skytonight_api_module, 'has_comets_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))
        result = skytonight_api_module._build_comets_section_payload('uid-1', 'user1')
        assert result['comets'][0]['absolute magnitude'] is None


class TestBuildDsoSectionPayloadWithCalcResults:
    """Cover _build_dso_section_payload with has_dso_results=True."""

    def test_dso_calc_path(self, monkeypatch):
        """DSO payload from calc results."""
        calc = _make_calc_result()
        data = {'deep_sky': calc['deep_sky'], 'metadata': {}}
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name', lambda n: n.lower())

        result = skytonight_api_module._build_dso_section_payload(None, 'uid-1', 'user1')
        assert isinstance(result.get('report'), list)
        assert len(result['report']) >= 1

    def test_dso_calc_path_with_catalogue_filter(self, monkeypatch):
        """catalogue filter skips non-matching DSO items."""
        calc = _make_calc_result()
        data = {'deep_sky': calc['deep_sky'], 'metadata': {}}
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

        result = skytonight_api_module._build_dso_section_payload('Messier', 'uid-1', 'user1')
        assert isinstance(result.get('report'), list)
        # NGC 224 has 'Messier': 'M 31', so it should appear; canonical id is OpenNGC name
        assert any(r['id'] == 'NGC 224' for r in result['report'])


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


class TestGetCataloguesRoute:
    """Cover /api/catalogues GET."""

    def test_catalogues_returns_list(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'loaded': True, 'targets': _sample_targets(), 'metadata': {}},
        )
        response = client_admin.get('/api/catalogues')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)

    def test_catalogues_returns_empty_on_exception(self, client_admin, monkeypatch):
        """exception → return empty list."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        response = client_admin.get('/api/catalogues')
        assert response.status_code == 200
        assert response.get_json() == []


class TestSchedulerStatusRoutes:
    """Cover /api/scheduler/status and /api/skytonight/scheduler/status."""

    def test_legacy_scheduler_status(self, client_admin, monkeypatch):
        """legacy route delegates to skytonight_scheduler_status_api."""
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': True}, 'location': {'timezone': 'UTC'}})
        response = client_admin.get('/api/scheduler/status')
        assert response.status_code == 200

    def test_skytonight_scheduler_status_no_scheduler(self, client_admin, monkeypatch):
        """when scheduler is None → fallback response."""
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': False}, 'location': {'timezone': 'UTC'}})
        response = client_admin.get('/api/skytonight/scheduler/status')
        assert response.status_code == 200
        data = response.get_json()
        assert 'running' in data

    def test_skytonight_scheduler_status_with_remote(self, client_admin, monkeypatch):
        """remote_scheduler → get_remote status."""
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api',
                            lambda: 'remote_scheduler')
        monkeypatch.setattr(skytonight_api_module, 'get_remote_skytonight_scheduler_status',
                            lambda: {'running': False, 'worker': 'remote'})
        response = client_admin.get('/api/skytonight/scheduler/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['worker'] == 'remote'

    def test_skytonight_scheduler_status_with_live_scheduler(self, client_admin, monkeypatch):
        """scheduler object → call get_status()."""
        mock_sched = type('Sched', (), {'get_status': lambda self: {'running': True, 'mode': 'idle'}})()
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        response = client_admin.get('/api/skytonight/scheduler/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['running'] is True


class TestTriggerSchedulerRoutes:
    """Cover /api/scheduler/trigger and /api/skytonight/scheduler/trigger."""

    def test_legacy_trigger_delegates(self, client_admin, monkeypatch):
        """legacy route delegates to trigger_skytonight_scheduler_api."""
        mock_sched = type('Sched', (), {'trigger_now': lambda self: {'status': 'triggered'}})()
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        response = client_admin.post('/api/scheduler/trigger')
        assert response.status_code == 200

    def test_trigger_with_live_scheduler(self, client_admin, monkeypatch):
        """scheduler.trigger_now()."""
        mock_sched = type('Sched', (), {'trigger_now': lambda self: {'status': 'triggered'}})()
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        response = client_admin.post('/api/skytonight/scheduler/trigger')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'triggered'

    def test_trigger_no_scheduler_returns_500(self, client_admin, monkeypatch):
        """no scheduler → error 500."""
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: None)
        response = client_admin.post('/api/skytonight/scheduler/trigger')
        assert response.status_code == 500

    def test_trigger_remote_scheduler_creates_trigger_file(self, client_admin, monkeypatch, tmp_path):
        """remote_scheduler → create trigger file."""
        trigger_file = tmp_path / 'skytonight.trigger'
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api',
                            lambda: 'remote_scheduler')
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_trigger_file',
                            lambda: str(trigger_file))
        response = client_admin.post('/api/skytonight/scheduler/trigger')
        assert response.status_code == 200
        assert response.get_json()['status'] == 'triggered'


class TestDatasetStatusRoute:
    """Cover /api/skytonight/dataset/status."""

    def test_dataset_status_basic(self, client_admin, monkeypatch):
        """dataset status endpoint."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'loaded': True, 'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': True}, 'location': {'timezone': 'UTC'}})
        response = client_admin.get('/api/skytonight/dataset/status')
        assert response.status_code == 200
        data = response.get_json()
        assert 'enabled' in data
        assert 'computed_counts' in data

    def test_dataset_status_with_remote_scheduler(self, client_admin, monkeypatch):
        """remote_scheduler → get_remote_status."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'loaded': True, 'targets': [], 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api',
                            lambda: 'remote_scheduler')
        monkeypatch.setattr(skytonight_api_module, 'get_remote_skytonight_scheduler_status',
                            lambda: {'running': False, 'is_executing': False})
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': True}, 'location': {}})
        response = client_admin.get('/api/skytonight/dataset/status')
        assert response.status_code == 200

    def test_dataset_status_with_live_scheduler(self, client_admin, monkeypatch):
        """live scheduler → scheduler.get_status()."""
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'loaded': True, 'targets': [], 'metadata': {}},
        )
        mock_sched = type('S', (), {
            'get_status': lambda self: {'running': True, 'is_executing': False}
        })()
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': True}, 'location': {}})
        response = client_admin.get('/api/skytonight/dataset/status')
        assert response.status_code == 200


class TestDatasetRebuildRoute:
    """Cover /api/skytonight/dataset/rebuild."""

    def test_rebuild_returns_status_rebuilt(self, client_admin, monkeypatch):
        """successful rebuild."""
        monkeypatch.setattr(skytonight_api_module, '_run_skytonight_refresh',
                            lambda: {'targets_count': 100, 'calculation_run': True})
        response = client_admin.post('/api/skytonight/dataset/rebuild')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'rebuilt'

    def test_rebuild_exception_returns_500(self, client_admin, monkeypatch):
        """exception during rebuild → 500."""
        monkeypatch.setattr(skytonight_api_module, '_run_skytonight_refresh',
                            lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        response = client_admin.post('/api/skytonight/dataset/rebuild')
        assert response.status_code == 500


class TestAlttimeRoute:
    """Cover /api/skytonight/alttime/<target_id>."""

    def test_invalid_target_id_returns_400(self, client_admin):
        """invalid target_id pattern."""
        response = client_admin.get('/api/skytonight/alttime/bad$id')
        assert response.status_code == 400

    def test_missing_alttime_file_returns_404(self, client_admin, monkeypatch):
        """alttime file doesn't exist."""
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: False)
        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 404

    def test_valid_alttime_file_returns_data(self, client_admin, monkeypatch, tmp_path):
        """read and return alttime JSON."""
        import json
        alttime_data = {'times': [1, 2, 3], 'altitudes': [10, 20, 30]}
        alttime_file = tmp_path / 'dso_ngc224_alttime.json'
        alttime_file.write_text(json.dumps(alttime_data), encoding='utf-8')

        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path',
                            lambda tid, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', str(tmp_path))
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {}}})

        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 200
        data = response.get_json()
        assert 'horizon_profile' in data


class TestCombinationRecommendationsRoute:
    """Cover /api/skytonight/combination-recommendations."""

    def test_no_combinations_returns_empty_recommendations(self, client_admin, monkeypatch):
        """no combinations → empty recommendations."""
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is False
        assert data['recommendations'] == []

    def test_with_combinations_returns_recommendations(self, client_admin, monkeypatch):
        """with an enabled, valid combination → recommendations."""
        mock_combo = {'id': 'combo-1', 'name': 'My Combo', 'telescope_id': 'scope-1', 'is_disabled': False}
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': [mock_combo]})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'compute_combination_validity_status',
                            lambda combo, uid: {'is_valid': True, 'invalid_reasons': [],
                                                 'disabled_component_ids': []})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'index_telescopes_and_cameras',
                            lambda uid: ({}, {}))
        monkeypatch.setattr(skytonight_api_module, '_recommend_combinations_for_target',
                            lambda t, combos, tel, cam: [{'combination_id': 'combo-1', 'rating_1_to_5': 4}])
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is True

    def test_disabled_combination_excluded(self, client_admin, monkeypatch):
        """own combination with is_disabled=True → excluded, no telescopes-recommendations call."""
        mock_combo = {'id': 'combo-1', 'name': 'My Combo', 'telescope_id': 'scope-1', 'is_disabled': True}
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': [mock_combo]})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is False
        assert data['recommendations'] == []

    def test_invalid_combination_excluded(self, client_admin, monkeypatch):
        """own combination failing validity → excluded from recommendations."""
        mock_combo = {'id': 'combo-1', 'name': 'My Combo', 'telescope_id': 'scope-1', 'is_disabled': False}
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': [mock_combo]})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'compute_combination_validity_status',
                            lambda combo, uid: {'is_valid': False, 'invalid_reasons': ['disabled:scope-1'],
                                                 'disabled_component_ids': ['scope-1']})
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is False

    def test_shared_combination_included(self, client_admin, monkeypatch):
        """valid shared combination (from another user) → included in recommendations."""
        shared_combo = {
            'id': 'combo-2', 'name': 'Shared Combo', 'telescope_id': 'scope-2',
            'is_disabled': False, 'is_valid': True, 'owner_username': 'alice',
        }
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [shared_combo])
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'index_telescopes_and_cameras',
                            lambda uid: ({}, {}))
        monkeypatch.setattr(skytonight_api_module, '_recommend_combinations_for_target',
                            lambda t, combos, tel, cam: [{'combination_id': 'combo-2', 'rating_1_to_5': 3}])
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is True


class TestSkymapRoute:
    """Cover /api/skytonight/skymap."""

    def test_skymap_missing_file_returns_empty(self, client_admin, monkeypatch):
        """skymap file doesn't exist → empty targets list."""
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: False)
        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 200
        data = response.get_json()
        assert data['targets'] == []

    def test_skymap_returns_targets(self, client_admin, monkeypatch, tmp_path):
        """read and return skymap data."""
        import json
        skymap_data = {
            'targets': [
                {'id': 'ngc224', 'name': 'NGC 224', 'constellation': 'And',
                 'category': 'deep_sky', 'messier': True},
            ]
        }
        skymap_file = tmp_path / 'skymap.json'
        skymap_file.write_text(json.dumps(skymap_data), encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(skytonight_api_module, 'get_dso_results_file',
                            lambda *_a, **_k: str(tmp_path / 'dso_results.json'))
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'altitude_constraint_min': 30, 'horizon_profile': []}}})
        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data['targets'], list)


class TestDataRoutes:
    """Cover /api/skytonight/data/* endpoints."""

    def test_bodies_route_returns_payload(self, client_admin, monkeypatch):
        """/api/skytonight/data/bodies."""
        monkeypatch.setattr(skytonight_api_module, 'has_bodies_results', lambda *_a, **_k: False)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))
        response = client_admin.get('/api/skytonight/data/bodies')
        assert response.status_code == 200

    def test_comets_route_returns_payload(self, client_admin, monkeypatch):
        """/api/skytonight/data/comets."""
        monkeypatch.setattr(skytonight_api_module, 'has_comets_results', lambda *_a, **_k: False)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))
        response = client_admin.get('/api/skytonight/data/comets')
        assert response.status_code == 200

    def test_dso_route_returns_payload(self, client_admin, monkeypatch):
        """/api/skytonight/data/dso."""
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets,
            'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name',
                            lambda n: n.lower())
        response = client_admin.get('/api/skytonight/data/dso')
        assert response.status_code == 200

    def test_dso_route_invalid_catalogue_returns_400(self, client_admin):
        """invalid catalogue param."""
        response = client_admin.get('/api/skytonight/data/dso?catalogue=bad$name')
        assert response.status_code == 400


class TestCatalogueLogRoutes:
    """Cover /api/skytonight/logs/* endpoints."""

    def test_catalogue_log_invalid_name_returns_400(self, client_admin):
        """invalid catalogue name."""
        response = client_admin.get('/api/skytonight/logs/bad$name')
        assert response.status_code == 400

    def test_catalogue_log_missing_file_returns_404(self, client_admin, monkeypatch):
        """log file doesn't exist."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module.os.path, 'exists', lambda p: False)
        response = client_admin.get('/api/skytonight/logs/Messier')
        assert response.status_code == 404

    def test_catalogue_log_returns_content(self, client_admin, monkeypatch, tmp_path):
        """return log content."""
        log_file = tmp_path / 'calc.log'
        log_file.write_text('{"status":"ok"}\n', encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        response = client_admin.get('/api/skytonight/logs/Messier')
        assert response.status_code == 200
        data = response.get_json()
        assert 'log_content' in data

    def test_catalogue_log_empty_file_returns_404(self, client_admin, monkeypatch, tmp_path):
        """log file exists but empty."""
        log_file = tmp_path / 'empty.log'
        log_file.write_text('', encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        response = client_admin.get('/api/skytonight/logs/Messier')
        assert response.status_code == 404

    def test_log_exists_invalid_name_returns_400(self, client_admin):
        """invalid catalogue name → 400."""
        response = client_admin.get('/api/skytonight/logs/bad$name/exists')
        assert response.status_code == 400

    def test_log_exists_returns_false_when_missing(self, client_admin, monkeypatch):
        """log doesn't exist → log_exists=False."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module.os.path, 'exists', lambda p: False)
        response = client_admin.get('/api/skytonight/logs/Messier/exists')
        assert response.status_code == 200
        data = response.get_json()
        assert data['log_exists'] is False

    def test_log_exists_returns_true_when_present(self, client_admin, monkeypatch, tmp_path):
        """log exists and non-empty → log_exists=True."""
        log_file = tmp_path / 'calc.log'
        log_file.write_text('{"status":"ok"}\n', encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        response = client_admin.get('/api/skytonight/logs/Messier/exists')
        assert response.status_code == 200
        data = response.get_json()
        assert data['log_exists'] is True


# ---------------------------------------------------------------------------
# Route exception handlers (500 responses)
# ---------------------------------------------------------------------------


class TestRouteExceptionHandlers:
    """Cover the except blocks in routes (500-return paths)."""

    def test_skytonight_log_no_file_returns_empty(self, client_admin, monkeypatch, tmp_path):
        """log file doesn't exist → log_content=''."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(
            skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE',
            str(tmp_path / 'nonexistent.log')
        )
        response = client_admin.get('/api/skytonight/log')
        assert response.status_code == 200
        assert response.get_json()['log_content'] == ''

    def test_skytonight_log_file_read_ok(self, client_admin, monkeypatch, tmp_path):
        """read and return log content."""
        log_file = tmp_path / 'calc.log'
        log_file.write_text('line1\nline2\n', encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        response = client_admin.get('/api/skytonight/log')
        assert response.status_code == 200
        assert response.get_json()['log_content'].startswith('line1')

    def test_reports_api_exception_returns_500(self, client_admin, monkeypatch):
        """exception in reports route → 500."""
        monkeypatch.setattr(
            skytonight_api_module, '_build_skytonight_reports_payload',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')),
        )
        response = client_admin.get('/api/skytonight/reports')
        assert response.status_code == 500

    def test_catalogue_reports_api_basic(self, client_admin, monkeypatch):
        """catalogue reports route works."""
        monkeypatch.setattr(
            skytonight_api_module, '_build_skytonight_reports_payload',
            lambda *a, **k: {'report': [], 'bodies': [], 'comets': []},
        )
        response = client_admin.get('/api/skytonight/reports/Messier')
        assert response.status_code == 200

    def test_catalogue_reports_invalid_name_returns_400(self, client_admin):
        """invalid catalogue name → 400."""
        response = client_admin.get('/api/skytonight/reports/bad$name')
        assert response.status_code == 400

    def test_catalogue_reports_exception_returns_500(self, client_admin, monkeypatch):
        """exception in catalogue reports route → 500."""
        monkeypatch.setattr(
            skytonight_api_module, '_build_skytonight_reports_payload',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')),
        )
        response = client_admin.get('/api/skytonight/reports/Messier')
        assert response.status_code == 500

    def test_alttime_horizon_empty_and_not_in_data(self, client_admin, monkeypatch, tmp_path):
        """horizon_profile empty and not in data → set []."""
        import json
        alttime_data = {'times': [1, 2, 3], 'altitudes': [10, 20, 30]}
        alttime_file = tmp_path / 'target_alttime.json'
        alttime_file.write_text(json.dumps(alttime_data), encoding='utf-8')
        output_dir = str(tmp_path)

        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path', lambda tid, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', output_dir)
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'horizon_profile': []}}})

        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 200
        data = response.get_json()
        assert data['horizon_profile'] == []

    def test_alttime_exception_returns_500(self, client_admin, monkeypatch, tmp_path):
        """exception reading alttime file → 500."""
        from unittest.mock import patch as upatch
        output_dir = str(tmp_path)
        target_path = str(tmp_path / 'f.json')

        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path', lambda tid, *_a, **_k: target_path)
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', output_dir)
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)

        import builtins
        real_open = builtins.open

        def bad_open(path, *a, **k):
            if str(path) == target_path:
                raise ValueError('bad json')
            return real_open(path, *a, **k)

        with upatch('builtins.open', side_effect=bad_open):
            response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 500

    def test_combination_recommendations_invalid_payload(self, client_admin, monkeypatch):
        """non-dict JSON payload → 400."""
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            data='"just_a_string"',
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_combination_recommendations_visual_magnitude_fallback(self, client_admin, monkeypatch):
        """mag=None → fallback to 'visual magnitude' key."""
        mock_combo = {'id': 'combo-1', 'name': 'My Combo', 'telescope_id': 'scope-1', 'is_disabled': False}
        mock_telescope = {
            'id': 'scope-1', 'name': 'My Scope',
            'aperture_mm': 200, 'focal_length_mm': 1000,
            'effective_focal_length': 1000, 'effective_focal_ratio': 5.0,
            'native_focal_ratio': 5.0,
        }
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: {'items': [mock_combo]})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_all_shared_combinations',
                            lambda *a, **k: [])
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'compute_combination_validity_status',
                            lambda combo, uid: {'is_valid': True, 'invalid_reasons': [],
                                                 'disabled_component_ids': []})
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'index_telescopes_and_cameras',
                            lambda uid: ({'scope-1': mock_telescope}, {}))
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'visual magnitude': 3.4, 'size': 189.0},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['has_combinations'] is True

    def test_combination_recommendations_exception_returns_500(self, client_admin, monkeypatch):
        """exception → 500."""
        monkeypatch.setattr(skytonight_api_module.equipment_profiles, 'load_user_combinations',
                            lambda uid: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.post(
            '/api/skytonight/combination-recommendations',
            json={'id': 'NGC 224', 'type': 'Galaxy', 'mag': 3.4},
        )
        assert response.status_code == 500

    def test_skymap_exception_returns_500(self, client_admin, monkeypatch, tmp_path):
        """exception reading skymap → 500."""
        bad_file = tmp_path / 'skymap.json'
        bad_file.write_text('not valid json', encoding='utf-8')
        monkeypatch.setattr(skytonight_api_module, 'get_skymap_file', lambda *_a, **_k: str(bad_file))
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 500

    def test_skymap_enrichment_with_dso_file(self, client_admin, monkeypatch, tmp_path):
        """skymap enrichment crosses DSO file when needed."""
        import json
        skymap_data = {
            'targets': [
                {'id': 'dso-ngc224', 'name': 'NGC 224', 'constellation': 'And',
                 'category': 'deep_sky'},
            ]
        }
        dso_data = {
            'deep_sky': [
                {'target_id': 'dso-ngc224', 'catalogue_names': {'Messier': 'M 31', 'OpenNGC': 'NGC 224'}},
            ]
        }
        skymap_file = tmp_path / 'skymap.json'
        dso_file = tmp_path / 'dso_results.json'
        skymap_file.write_text(json.dumps(skymap_data), encoding='utf-8')
        dso_file.write_text(json.dumps(dso_data), encoding='utf-8')

        monkeypatch.setattr(skytonight_api_module, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(skytonight_api_module, 'get_dso_results_file', lambda *_a, **_k: str(dso_file))
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'altitude_constraint_min': 30, 'horizon_profile': []}}})
        monkeypatch.setattr(skytonight_api_module, 'load_json_file',
                            lambda path, default=None: dso_data if 'dso' in str(path) else default)
        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 200
        targets = response.get_json()['targets']
        assert any('messier' in t for t in targets)

    def test_bodies_route_exception_returns_500(self, client_admin, monkeypatch):
        """exception in bodies route → 500."""
        monkeypatch.setattr(skytonight_api_module, '_build_bodies_section_payload',
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/data/bodies')
        assert response.status_code == 500

    def test_comets_route_exception_returns_500(self, client_admin, monkeypatch):
        """exception in comets route → 500."""
        monkeypatch.setattr(skytonight_api_module, '_build_comets_section_payload',
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/data/comets')
        assert response.status_code == 500

    def test_dso_route_exception_returns_500(self, client_admin, monkeypatch):
        """exception in DSO route → 500."""
        monkeypatch.setattr(skytonight_api_module, '_build_dso_section_payload',
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/data/dso')
        assert response.status_code == 500

    def test_catalogue_log_exception_returns_500(self, client_admin, monkeypatch):
        """exception in catalogue log route → 500."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories',
                            lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/logs/Messier')
        assert response.status_code == 500

    def test_log_exists_exception_returns_500(self, client_admin, monkeypatch):
        """exception in log-exists route → 500."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories',
                            lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/logs/Messier/exists')
        assert response.status_code == 500

    def test_target_debug_exception_returns_500(self, client_admin, monkeypatch):
        """exception in target-debug route → 500."""
        monkeypatch.setattr(skytonight_api_module, 'compute_target_debug',
                            lambda name, config=None: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/target-debug?name=M+31')
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Telescope builder helper functions
# ---------------------------------------------------------------------------


class TestCombinationScoringHelpers:
    """Cover _to_float, _score_in_range, _ideal_focal_range, etc."""

    def test_to_float_none_returns_none(self):
        _to_float = skytonight_api_module._to_float
        assert _to_float(None) is None

    def test_to_float_empty_string_returns_none(self):
        _to_float = skytonight_api_module._to_float
        assert _to_float('') is None

    def test_to_float_invalid_string_returns_none(self):
        _to_float = skytonight_api_module._to_float
        assert _to_float('not_a_number') is None

    def test_to_float_valid_value(self):
        _to_float = skytonight_api_module._to_float
        assert _to_float('3.14') == pytest.approx(3.14)

    def test_score_in_range_inside_returns_5(self):
        _score_in_range = skytonight_api_module._score_in_range
        assert _score_in_range(100.0, 80.0, 120.0) == 5.0

    def test_score_in_range_swapped_min_max(self):
        """min_value > max_value → swap."""
        _score_in_range = skytonight_api_module._score_in_range
        assert _score_in_range(100.0, 120.0, 80.0) == 5.0

    def test_score_in_range_outside_below(self):
        """value below min_value → penalty applied."""
        _score_in_range = skytonight_api_module._score_in_range
        score = _score_in_range(10.0, 80.0, 120.0)
        assert 1.0 <= score < 5.0

    def test_score_in_range_outside_above(self):
        _score_in_range = skytonight_api_module._score_in_range
        score = _score_in_range(300.0, 80.0, 120.0)
        assert 1.0 <= score < 5.0

    def test_ideal_focal_range_large_size(self):
        """size_arcmin >= 120 → (100, 350)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(150.0, 'Galaxy') == (100.0, 350.0)

    def test_ideal_focal_range_60_to_120(self):
        """size_arcmin in [60, 120) → (200, 550)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(80.0, 'Galaxy') == (200.0, 550.0)

    def test_ideal_focal_range_30_to_60(self):
        """size_arcmin in [30, 60) → (350, 850)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(45.0, 'Nebula') == (350.0, 850.0)

    def test_ideal_focal_range_15_to_30(self):
        """size_arcmin in [15, 30) → (600, 1300)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(20.0, 'Galaxy') == (600.0, 1300.0)

    def test_ideal_focal_range_8_to_15(self):
        """size_arcmin in [8, 15) → (900, 1800)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(10.0, 'Galaxy') == (900.0, 1800.0)

    def test_ideal_focal_range_small_size(self):
        """size_arcmin < 8 → (1200, 3000)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(5.0, 'Galaxy') == (1200.0, 3000.0)

    def test_ideal_focal_range_none_size_galaxy(self):
        """no size, galaxy type → (900, 2200)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(None, 'Galaxy') == (900.0, 2200.0)

    def test_ideal_focal_range_none_size_open_cluster(self):
        """no size, open cluster → (250, 900)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(None, 'Open Cluster') == (250.0, 900.0)

    def test_ideal_focal_range_none_size_unknown(self):
        """no size, unknown type → (450, 1400)."""
        _ideal_focal_range = skytonight_api_module._ideal_focal_range
        assert _ideal_focal_range(None, 'Unknown') == (450.0, 1400.0)

    def test_aperture_score_no_magnitude(self):
        """magnitude is None → score based on aperture alone."""
        _aperture_score = skytonight_api_module._aperture_score
        score = _aperture_score(100.0, None)
        assert 1.0 <= score <= 5.0

    def test_aperture_score_with_magnitude(self):
        """magnitude provided → faintness-weighted score."""
        _aperture_score = skytonight_api_module._aperture_score
        score = _aperture_score(150.0, 8.0)
        assert 1.0 <= score <= 5.0

    def test_speed_score_nebula_fast(self):
        """nebula with f_ratio <= 5 → 5.0."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(4.5, 'Emission Nebula') == 5.0

    def test_speed_score_nebula_f65(self):
        """f_ratio <= 6.5 → 4.0."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(6.0, 'Open Cluster') == 4.0

    def test_speed_score_nebula_f80(self):
        """f_ratio <= 8 → 3.0."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(7.5, 'Nebula') == 3.0

    def test_speed_score_nebula_f100(self):
        """f_ratio <= 10 → 2.0."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(9.0, 'Nebula') == 2.0

    def test_speed_score_nebula_slow(self):
        """f_ratio > 10 → 1.0."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(12.0, 'Nebula') == 1.0

    def test_speed_score_galaxy_returns_35(self):
        """non-nebula type → 3.5."""
        _speed_score = skytonight_api_module._speed_score
        assert _speed_score(10.0, 'Galaxy') == 3.5

    def test_recommend_skips_combo_with_missing_specs(self):
        """combo without a resolvable telescope or lens specs → skipped."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        result = _recommend_combinations_for_target(
            {'type': 'Galaxy', 'size': 50.0, 'mag': 6.0},
            [{'id': 'bad', 'name': 'No Specs'}],
            {},
            {},
        )
        assert result == []

    def test_recommend_returns_sorted_recommendations(self):
        """two telescope-based combos → recommendations sorted by rating."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        telescopes_by_id = {
            's1': {'id': 's1', 'name': 'Small Scope', 'effective_focal_length': 500.0,
                   'effective_focal_ratio': 7.0, 'aperture_mm': 80.0},
            's2': {'id': 's2', 'name': 'Big Scope', 'effective_focal_length': 1500.0,
                   'effective_focal_ratio': 5.0, 'aperture_mm': 300.0},
        }
        combos = [
            {'id': 'c1', 'name': 'Combo Small', 'telescope_id': 's1'},
            {'id': 'c2', 'name': 'Combo Big', 'telescope_id': 's2'},
        ]
        result = _recommend_combinations_for_target(
            {'type': 'Galaxy', 'size': 50.0, 'mag': 6.0},
            combos,
            telescopes_by_id,
            {},
        )
        assert len(result) == 2
        assert result[0]['rating_1_to_5'] >= result[-1]['rating_1_to_5']
        assert all(rec['telescope_name'] for rec in result)
        assert all(rec['is_camera_only'] is False for rec in result)

    def test_recommend_camera_only_combo_uses_lens_specs(self):
        """no telescope_id, but lens_focal_length_mm/lens_focal_ratio set → still scored."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        combo = {
            'id': 'c1', 'name': 'DSLR + Lens', 'telescope_id': None, 'camera_id': 'cam-1',
            'lens_focal_length_mm': 200.0, 'lens_focal_ratio': 2.8,
        }
        result = _recommend_combinations_for_target(
            {'type': 'Nebula', 'size': 120.0, 'mag': 5.0},
            [combo],
            {},
            {'cam-1': {'id': 'cam-1', 'name': 'My DSLR'}},
        )
        assert len(result) == 1
        rec = result[0]
        assert rec['is_camera_only'] is True
        assert rec['telescope_name'] is None
        assert rec['camera_name'] == 'My DSLR'
        assert rec['effective_focal_length'] == 200.0
        assert rec['effective_focal_ratio'] == 2.8
        assert rec['aperture_mm'] == pytest.approx(200.0 / 2.8, abs=0.1)

    def test_recommend_camera_only_combo_without_lens_specs_skipped(self):
        """no telescope_id and no lens specs → skipped (nothing to score)."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        combo = {'id': 'c1', 'name': 'Mount Only', 'telescope_id': None, 'camera_id': None}
        result = _recommend_combinations_for_target(
            {'type': 'Galaxy', 'size': 50.0, 'mag': 6.0},
            [combo],
            {},
            {},
        )
        assert result == []

    def test_recommend_blends_fov_score_when_camera_resolvable(self):
        """combo with a resolvable camera → fov_diagonal_deg/image_scale/sampling populated."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        telescopes_by_id = {
            's1': {'id': 's1', 'name': 'Scope', 'effective_focal_length': 1000.0,
                   'effective_focal_ratio': 5.0, 'aperture_mm': 200.0},
        }
        cameras_by_id = {
            'cam-1': {'id': 'cam-1', 'name': 'Cam', 'sensor_width_mm': 23.5,
                      'sensor_height_mm': 15.6, 'pixel_size_um': 3.76},
        }
        combo = {'id': 'c1', 'name': 'Scope + Cam', 'telescope_id': 's1', 'camera_id': 'cam-1'}
        result = _recommend_combinations_for_target(
            {'type': 'Galaxy', 'size': 30.0, 'mag': 8.0},
            [combo],
            telescopes_by_id,
            cameras_by_id,
        )
        assert len(result) == 1
        rec = result[0]
        assert rec['fov_diagonal_deg'] is not None
        assert rec['image_scale_arcsec_per_px'] is not None
        assert rec['sampling_classification'] is not None

    def test_recommend_no_fov_score_when_camera_missing_sensor_specs(self):
        """camera resolvable but missing sensor dimensions → FOV fields stay None, no crash."""
        _recommend_combinations_for_target = skytonight_api_module._recommend_combinations_for_target
        telescopes_by_id = {
            's1': {'id': 's1', 'name': 'Scope', 'effective_focal_length': 1000.0,
                   'effective_focal_ratio': 5.0, 'aperture_mm': 200.0},
        }
        cameras_by_id = {'cam-1': {'id': 'cam-1', 'name': 'Cam'}}
        combo = {'id': 'c1', 'name': 'Scope + Cam', 'telescope_id': 's1', 'camera_id': 'cam-1'}
        result = _recommend_combinations_for_target(
            {'type': 'Galaxy', 'size': 30.0, 'mag': 8.0},
            [combo],
            telescopes_by_id,
            cameras_by_id,
        )
        assert len(result) == 1
        assert result[0]['fov_diagonal_deg'] is None


# ---------------------------------------------------------------------------
# Payload builder static path branches
# ---------------------------------------------------------------------------


class TestPayloadBuilderStaticPath:
    """Cover static fallback branches in payload builders."""

    def _common_patches(self, monkeypatch):
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

    def test_empty_targets_logs_info(self, monkeypatch):
        """empty targets list → still returns empty report."""
        self._common_patches(monkeypatch)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [], 'metadata': {}},
        )
        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert result['report'] == []
        assert result['bodies'] == []

    def test_metadata_not_dict_replaced(self, monkeypatch):
        """metadata not dict → replaced with {}."""
        self._common_patches(monkeypatch)
        # Inject metadata as a bad value via a dict-like target
        bad_target = {
            'target_id': 'dso-ngc224', 'category': 'deep_sky', 'object_type': 'Galaxy',
            'preferred_name': 'NGC 224', 'catalogue_names': {'OpenNGC': 'NGC 224'},
            'metadata': 'not_a_dict', 'aliases': [], 'source_catalogues': ['OpenNGC'],
        }
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [bad_target], 'metadata': {}},
        )
        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert isinstance(result['report'], list)

    def test_catalogue_filter_skip_non_matching(self, monkeypatch):
        """catalogue filter skips targets without matching name."""
        self._common_patches(monkeypatch)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        # Filter for 'NGC' catalogue - our sample targets don't have this key
        result = skytonight_api_module._build_skytonight_reports_payload('NGC', 'uid-1', 'user1')
        assert result['report'] == []

    def test_catalogue_filter_with_annotation(self, monkeypatch):
        """annotation path when catalogue filter matches."""
        self._common_patches(monkeypatch)
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        result = skytonight_api_module._build_skytonight_reports_payload('Messier', 'uid-1', 'user1')
        assert any(r.get('in_astrodex') is not None for r in result['report'])

    def test_comet_target_in_static_path(self, monkeypatch):
        """comet category in static path."""
        self._common_patches(monkeypatch)
        comet_target = {
            'target_id': 'comet-13p', 'category': 'comets', 'object_type': 'Comet',
            'preferred_name': '13P/Olbers', 'catalogue_names': {'Comets': '13P/Olbers'},
            'metadata': {'perihelion_date': '2026-10-20'},
        }
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [comet_target], 'metadata': {}},
        )
        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert len(result['comets']) == 1

    def test_comets_section_static_metadata_not_dict(self, monkeypatch):
        """comet metadata not dict → replaced with {} in static path."""
        monkeypatch.setattr(skytonight_api_module, 'has_comets_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        comet_target = {
            'target_id': 'comet-13p', 'category': 'comets', 'object_type': 'Comet',
            'preferred_name': '13P/Olbers', 'catalogue_names': {},
            'metadata': 'bad_metadata',
        }
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [comet_target], 'metadata': {}},
        )
        result = skytonight_api_module._build_comets_section_payload('uid-1', 'user1')
        assert len(result['comets']) == 1
        assert result['comets'][0]['q'] == ''

    def test_dso_section_static_catalogue_filter(self, monkeypatch):
        """DSO static path with catalogue filter."""
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name',
                            lambda n: n.lower())
        # Filter for Messier → should include NGC 224 (has Messier alias)
        result = skytonight_api_module._build_dso_section_payload('Messier', 'uid-1', 'user1')
        assert isinstance(result['report'], list)
        # Should have at least 1 entry (NGC 224 has Messier alias)
        assert len(result['report']) >= 1

    def test_dso_section_static_no_filter_no_annotation(self, monkeypatch):
        """DSO static path without catalogue, no annotation (skip_deep_sky_annotations)."""
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': _sample_targets(), 'metadata': {}},
        )
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name',
                            lambda n: n.lower())
        result = skytonight_api_module._build_dso_section_payload(None, 'uid-1', 'user1')
        assert isinstance(result['report'], list)
        assert len(result['report']) >= 1


class TestPreloadAllCurrentPlanEntries:
    """Cover _preload_all_current_plan_entries."""

    def test_plan_files_with_current_plan(self, monkeypatch):
        """iterate plan files, load plan, add entries."""
        plan_data = {
            'plan': {
                'state': 'current',
                'entries': [{'id': 'target-1', 'name': 'NGC 224'}],
            }
        }
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid1_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state',
                            lambda plan: 'current')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == [{'id': 'target-1', 'name': 'NGC 224'}]

    def test_plan_files_with_non_current_plan_skipped(self, monkeypatch):
        """plan state != 'current' → skip."""
        plan_data = {'plan': {'state': 'none', 'entries': [{'id': 'target-1'}]}}
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid1_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state', lambda plan: 'none')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == []

    def test_plan_files_plan_not_dict_skipped(self, monkeypatch):
        """plan_obj not dict → continue."""
        plan_data = {'plan': 'not_a_dict'}
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid1_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == []

    def test_plan_files_load_exception_swallowed(self, monkeypatch):
        """load_user_plan raises → exception swallowed."""
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid1_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: (_ for _ in ()).throw(RuntimeError('fail')))
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == []

    def test_plan_files_with_combination_id(self, monkeypatch):
        """file with combination-specific name → cid extracted."""
        plan_data = {
            'plan': {
                'state': 'current',
                'entries': [{'id': 'target-2', 'name': 'M 31'}],
            }
        }
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid1_plan_scope-1.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state', lambda plan: 'current')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == [{'id': 'target-2', 'name': 'M 31'}]


class TestCataloguesRouteEdgeCases:
    """Cover empty catalogue name in get_catalogues_api."""

    def test_empty_catalogue_name_not_added(self, client_admin, monkeypatch):
        """catalogue_name empty string → not added to set."""
        from skytonight.skytonight_models import SkyTonightTarget
        target_with_empty_catalogue = SkyTonightTarget(
            target_id='dso-test', category='deep_sky', object_type='Galaxy',
            preferred_name='Test Galaxy', catalogue_names={'': 'Test Galaxy'},
            aliases=[], source_catalogues=[''],
            translation_key='skytonight.type_galaxy',
        )
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [target_with_empty_catalogue], 'metadata': {}},
        )
        response = client_admin.get('/api/catalogues')
        assert response.status_code == 200
        data = response.get_json()
        assert '' not in data


# ---------------------------------------------------------------------------
# Additional targeted tests for remaining missing lines
# ---------------------------------------------------------------------------


class TestResolveCatalogueFixedBranches:
    """Correct _resolve_source_catalogue tests to hit , and 136."""

    def test_empty_display_name_returns_first_key(self, monkeypatch):
        """normalize_object_name returns empty string → skip loop, return first key."""
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name', lambda n: '')
        # normalized_display is '' (falsy) → skip the for loop, go straight to 
        result = skytonight_api_module._resolve_source_catalogue({'OpenNGC': 'NGC 224', 'Messier': 'M 31'}, 'NGC 224')
        assert result == 'OpenNGC'

    def test_second_catalogue_matches(self, monkeypatch):
        """first catalogue value doesn't match, second does."""
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name', lambda n: n.lower())
        # 'OpenNGC': 'NGC 224' normalizes to 'ngc 224', 'Messier': 'M 31' normalizes to 'm 31'
        # display_name='M 31' normalizes to 'm 31' → second entry matches
        result = skytonight_api_module._resolve_source_catalogue({'OpenNGC': 'NGC 224', 'Messier': 'M 31'}, 'M 31')
        assert result == 'Messier'

    def test_no_catalogue_matches_returns_first_key(self, monkeypatch):
        """no catalogue value normalizes to match display_name → return first key."""
        # Make catalogue values normalize to something different from display
        monkeypatch.setattr(skytonight_api_module.skytonight_targets, 'normalize_object_name',
                            lambda n: 'catalogue_val' if n in ('NGC 224', 'M 31') else 'display_val')
        # display_name='Unknown Object' → normalize → 'display_val'
        # catalogue values normalize to 'catalogue_val' ≠ 'display_val'
        result = skytonight_api_module._resolve_source_catalogue({'OpenNGC': 'NGC 224', 'Messier': 'M 31'}, 'Unknown Object')
        assert result == 'OpenNGC'


class TestPreloadPlanEntriesEdgeCases:
    """Covers edge cases in _preload_all_current_plan_entries."""

    def test_default_plan_file_tid_is_none(self, monkeypatch):
        """file matching default name → tid stays None."""
        plan_data = {
            'plan': {
                'state': 'current',
                'entries': [{'id': 'target-1', 'name': 'NGC 224'}],
            }
        }
        # Use the default plan filename format with user_id as a realistic GUID-like string
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: [f'/fake/{uid}_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state', lambda plan: 'current')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-test-123', 'user1')
        assert result == [{'id': 'target-1', 'name': 'NGC 224'}]

    def test_entry_with_no_id_skipped(self, monkeypatch):
        """entry without 'id' → not added to all_entries."""
        plan_data = {
            'plan': {
                'state': 'current',
                'entries': [{'name': 'NGC 224'}],  # no 'id' key
            }
        }
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state', lambda plan: 'current')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert result == []

    def test_duplicate_entry_id_not_added_twice(self, monkeypatch):
        """duplicate entry ID → only added once."""
        plan_data = {
            'plan': {
                'state': 'current',
                'entries': [
                    {'id': 'target-1', 'name': 'NGC 224'},
                    {'id': 'target-1', 'name': 'M 31'},  # duplicate
                ],
            }
        }
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files',
                            lambda uid: ['/fake/uid_plan_my_night.json'])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'load_user_plan',
                            lambda uid, username, combination_id=None: plan_data)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_state', lambda plan: 'current')
        result = skytonight_api_module._preload_all_current_plan_entries('uid-1', 'user1')
        assert len(result) == 1


class TestCalcPathMissingBranches:
    """Covers missing branches in calc paths."""

    def _base_patches(self, monkeypatch):
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

    def test_calc_catalogue_filter_skips_item_without_matching_name(self, monkeypatch):
        """calc DSO item not matching requested catalogue → continue."""
        self._base_patches(monkeypatch)
        # DSO item only has 'OpenNGC', not 'Messier'
        calc = {
            'deep_sky': [
                {
                    'target_id': 'dso-ngc1', 'preferred_name': 'NGC 1',
                    'catalogue_names': {'OpenNGC': 'NGC 1'},
                    'object_type': 'Galaxy', 'constellation': '', 'magnitude': 10.0,
                    'size_arcmin': 5.0, 'astro_score': 0.5,
                    'observation': {'ra_hms': '00h', 'dec_dms': '+00°', 'max_altitude': 40.0,
                                    'observable_fraction': 0.5, 'azimuth': 180.0,
                                    'meridian_transit': '', 'antimeridian_transit': '',
                                    'observable_hours': 3.0},
                }
            ],
            'bodies': [], 'comets': [],
        }
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_calculation_results', lambda *_a, **_k: calc)
        # Request Messier catalogue → NGC 1 doesn't have it → skipped
        result = skytonight_api_module._build_skytonight_reports_payload('Messier', 'uid-1', 'user1')
        assert result['report'] == []

    def test_calc_comet_metadata_not_dict_replaced(self, monkeypatch):
        """comet metadata not dict in calc path → replaced with {}."""
        self._base_patches(monkeypatch)
        calc = {
            'deep_sky': [],
            'bodies': [],
            'comets': [
                {
                    'target_id': 'comet-bad', 'preferred_name': 'Comet Bad',
                    'object_type': 'Comet', 'magnitude': 7.0, 'astro_score': 0.5,
                    'metadata': 'not_a_dict',
                    'observation': {
                        'ra_hms': '05h', 'dec_dms': '+10°',
                        'max_altitude': 35.0, 'azimuth': 170.0,
                        'rise_time': '21:00', 'set_time': '03:00',
                        'meridian_transit': '00:00', 'antimeridian_transit': '12:00',
                        'observable_hours': 6.0,
                    },
                }
            ],
        }
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module, 'load_calculation_results', lambda *_a, **_k: calc)
        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert len(result['comets']) == 1
        assert result['comets'][0]['absolute magnitude'] is None

    def test_dso_calc_catalogue_filter_skips_non_matching(self, monkeypatch):
        """DSO calc item not matching catalogue filter → continue."""
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan',
                            lambda *a, **k: False)
        dso_data = {
            'deep_sky': [
                {
                    'target_id': 'dso-ngc1', 'preferred_name': 'NGC 1',
                    'catalogue_names': {'OpenNGC': 'NGC 1'},
                    'object_type': 'Galaxy', 'constellation': '', 'magnitude': 10.0,
                    'size_arcmin': 5.0, 'astro_score': 0.5,
                    'observation': {'ra_hms': '00h', 'dec_dms': '+00°', 'max_altitude': 40.0,
                                    'observable_fraction': 0.5, 'azimuth': 180.0,
                                    'meridian_transit': '', 'antimeridian_transit': '',
                                    'observable_hours': 3.0},
                }
            ],
            'metadata': {},
        }
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: dso_data)
        # Request Messier → NGC 1 doesn't have it → skipped
        result = skytonight_api_module._build_dso_section_payload('Messier', 'uid-1', 'user1')
        assert result['report'] == []


class TestStaticPathMissingBranches:
    """Covers missing branches in static fallback paths."""

    def _common_patches(self, monkeypatch):
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module, '_get_catalogue_alias_payload', lambda c, n: ('', {}))

    def test_unknown_category_target_skipped(self, monkeypatch):
        """target with unknown category is skipped (not deep_sky/bodies/comets)."""
        self._common_patches(monkeypatch)
        unknown_target = {
            'target_id': 'unknown-1', 'category': 'asteroids', 'object_type': 'Asteroid',
            'preferred_name': 'Asteroid 1', 'catalogue_names': {}, 'metadata': {},
        }
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [unknown_target], 'metadata': {}},
        )
        result = skytonight_api_module._build_skytonight_reports_payload(None, 'uid-1', 'user1')
        assert result['report'] == []
        assert result['bodies'] == []
        assert result['comets'] == []

    def test_dso_static_catalogue_filter_skips_non_matching(self, monkeypatch):
        """DSO static target without matching catalogue → continue."""
        monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_plan_with_timeline',
                            lambda u, n: {'state': 'none'})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'load_user_astrodex', lambda uid: {'items': []})
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_preloaded_astrodex',
                            lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan',
                            lambda *a, **k: False)
        dso_target = {
            'target_id': 'dso-ngc1', 'category': 'deep_sky', 'object_type': 'Galaxy',
            'preferred_name': 'NGC 1', 'catalogue_names': {'OpenNGC': 'NGC 1'}, 'metadata': {},
        }
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': [dso_target], 'metadata': {}},
        )
        # Request Messier → NGC 1 doesn't have it → skipped
        result = skytonight_api_module._build_dso_section_payload('Messier', 'uid-1', 'user1')
        assert result['report'] == []


class TestRemainingRouteGaps:
    """Cover remaining route line gaps."""

    def test_trigger_scheduler_file_creation_exception(self, client_admin, monkeypatch, tmp_path):
        """trigger file creation fails → 500."""
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api',
                            lambda: 'remote_scheduler')
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_trigger_file',
                            lambda: '/invalid/path/that/does/not/exist/trigger')
        response = client_admin.post('/api/skytonight/scheduler/trigger')
        assert response.status_code == 500

    def test_dataset_status_with_dict_targets(self, client_admin, monkeypatch):
        """dict target (not SkyTonightTarget object) → category via .get()."""
        dict_targets = [
            {'target_id': 'dso-1', 'category': 'deep_sky', 'preferred_name': 'NGC 1'},
            {'target_id': 'body-1', 'category': 'bodies', 'preferred_name': 'Jupiter'},
        ]
        monkeypatch.setattr(
            skytonight_api_module.skytonight_targets, 'load_targets_dataset',
            lambda *a, **k: {'targets': dict_targets, 'metadata': {}, 'loaded': True},
        )
        monkeypatch.setattr(skytonight_api_module, 'get_skytonight_scheduler_for_api', lambda: None)
        monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'enabled': True}})
        response = client_admin.get('/api/skytonight/dataset/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['computed_counts']['deep_sky'] == 1

    def test_skytonight_log_exception_returns_500(self, client_admin, monkeypatch):
        """exception in log endpoint → 500."""
        monkeypatch.setattr(skytonight_api_module, 'ensure_skytonight_directories',
                            lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        response = client_admin.get('/api/skytonight/log')
        assert response.status_code == 500

    def test_alttime_path_traversal_rejected(self, client_admin, monkeypatch, tmp_path):
        """path traversal attempt → 400."""
        output_dir = str(tmp_path / 'output')
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', output_dir)
        # _alttime_json_path returns something outside OUTPUT_DIR
        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path',
                            lambda tid, *_a, **_k: '/some/other/path/outside_output/file.json')
        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 400

    def test_alttime_horizon_profile_injection(self, client_admin, monkeypatch, tmp_path):
        """current_horizon is non-empty → inject into data."""
        import json
        alttime_data = {'times': [1, 2, 3], 'altitudes': [10, 20, 30]}
        alttime_file = tmp_path / 'target_alttime.json'
        alttime_file.write_text(json.dumps(alttime_data), encoding='utf-8')
        output_dir = str(tmp_path)

        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path', lambda tid, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', output_dir)
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        # v1.2: the injected horizon comes from the install-default preset
        monkeypatch.setattr(
            skytonight_api_module, 'load_config',
            lambda: {'locations': [{'id': 'alt-loc', 'is_install_default': True, 'horizon_profile': [10, 20, 30]}]},
        )

        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 200
        data = response.get_json()
        assert data['horizon_profile'] == [10, 20, 30]

    def test_alttime_horizon_already_in_data_not_overwritten(self, client_admin, monkeypatch, tmp_path):
        """empty horizon_profile and 'horizon_profile' already in data → keep it."""
        import json
        alttime_data = {'times': [1, 2], 'altitudes': [10, 20], 'horizon_profile': [5, 15, 25]}
        alttime_file = tmp_path / 'target_alttime.json'
        alttime_file.write_text(json.dumps(alttime_data), encoding='utf-8')
        output_dir = str(tmp_path)

        monkeypatch.setattr(skytonight_api_module, '_alttime_json_path', lambda tid, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(skytonight_api_module, 'OUTPUT_DIR', output_dir)
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'horizon_profile': []}}})

        response = client_admin.get('/api/skytonight/alttime/dso-ngc224')
        assert response.status_code == 200
        data = response.get_json()
        assert data['horizon_profile'] == [5, 15, 25]

    def test_skymap_enrichment_dso_file_missing(self, client_admin, monkeypatch, tmp_path):
        """needs_enrichment=True but DSO file doesn't exist → skip enrichment."""
        import json
        skymap_data = {
            'targets': [
                {'id': 'dso-ngc224', 'name': 'NGC 224', 'constellation': '',
                 'category': 'deep_sky'},
            ]
        }
        skymap_file = tmp_path / 'skymap.json'
        skymap_file.write_text(json.dumps(skymap_data), encoding='utf-8')
        dso_file = tmp_path / 'dso_results.json'  # does not exist

        monkeypatch.setattr(skytonight_api_module, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(skytonight_api_module, 'get_dso_results_file', lambda *_a, **_k: str(dso_file))
        # isfile returns True for skymap, False for dso_results
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile',
                            lambda p: p == str(skymap_file))
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'altitude_constraint_min': 30, 'horizon_profile': []}}})

        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 200
        targets = response.get_json()['targets']
        # 'messier' not added when DSO file is missing
        assert len(targets) == 1
        assert 'messier' not in targets[0]

    def test_skymap_mixed_targets_for_inner_loop_false_branch(self, client_admin, monkeypatch, tmp_path):
        """mixed targets - one needing enrichment triggers loop,
        another with 'messier' already set skips the inner enrichment if-body."""
        import json
        skymap_data = {
            'targets': [
                # This one needs enrichment (triggers needs_enrichment=True)
                {'id': 'dso-ngc1', 'name': 'NGC 1', 'constellation': '', 'category': 'deep_sky'},
                # This one already has 'messier' → inner enrichment if-body is skipped
                {'id': 'dso-ngc224', 'name': 'NGC 224', 'constellation': '',
                 'category': 'deep_sky', 'messier': True},
            ]
        }
        dso_data = {
            'deep_sky': [
                {'target_id': 'dso-ngc1', 'catalogue_names': {'OpenNGC': 'NGC 1'}},
            ]
        }
        skymap_file = tmp_path / 'skymap.json'
        dso_file = tmp_path / 'dso_results.json'
        skymap_file.write_text(json.dumps(skymap_data), encoding='utf-8')
        dso_file.write_text(json.dumps(dso_data), encoding='utf-8')

        monkeypatch.setattr(skytonight_api_module, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(skytonight_api_module, 'get_dso_results_file', lambda *_a, **_k: str(dso_file))
        monkeypatch.setattr(skytonight_api_module.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(skytonight_api_module, 'load_config',
                            lambda: {'skytonight': {'constraints': {'altitude_constraint_min': 30, 'horizon_profile': []}}})
        monkeypatch.setattr(skytonight_api_module, 'load_json_file',
                            lambda path, default=None: dso_data)

        response = client_admin.get('/api/skytonight/skymap')
        assert response.status_code == 200
        targets = response.get_json()['targets']
        assert len(targets) == 2
        # 'messier' was already set on second target → stays True
        assert targets[1]['messier'] is True


class TestSkytonightRecommendationsEndpoint:
    """Tests for GET /api/skytonight/recommendations."""

    @staticmethod
    def _dso_results():
        return {
            'deep_sky': [
                {
                    'target_id': 't-beginner', 'preferred_name': 'Beginner Target',
                    'catalogue_names': {'Messier': 'M 42'}, 'object_type': 'Nebula',
                    'magnitude': 4.0, 'size_arcmin': 90.0,
                    'astro_score': 0.5, 'difficulty': 'beginner', 'difficulty_score': 18,
                },
                {
                    'target_id': 't-intermediate', 'preferred_name': 'Intermediate Target',
                    'catalogue_names': {'OpenNGC': 'NGC 1'}, 'object_type': 'Galaxy',
                    'magnitude': 9.0, 'size_arcmin': 10.0,
                    'astro_score': 0.9, 'difficulty': 'intermediate', 'difficulty_score': 50,
                },
                {
                    'target_id': 't-advanced', 'preferred_name': 'Advanced Target',
                    'catalogue_names': {'OpenNGC': 'NGC 2'}, 'object_type': 'Galaxy',
                    'magnitude': 16.0, 'size_arcmin': 0.5,
                    'astro_score': 0.7, 'difficulty': 'advanced', 'difficulty_score': 80,
                },
            ]
        }

    def _mock_common(self, monkeypatch, experience_level='advanced'):
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: self._dso_results())
        monkeypatch.setattr(skytonight_api_module.beginner_catalog, 'load_beginner_catalog', lambda: [])
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(
            skytonight_api_module.user_manager, 'get_user_preferences',
            lambda user_id: {'experience_level': experience_level},
        )

    def test_requires_authentication(self):
        app.config['TESTING'] = True
        with app.test_client() as anon_client:
            response = anon_client.get('/api/skytonight/recommendations')
        assert response.status_code == 401

    def test_beginner_level_returns_only_beginner_targets(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='beginner')
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['experience_level'] == 'beginner'
        assert all(t['difficulty'] == 'beginner' for t in payload['targets'])
        assert len(payload['targets']) == 1

    def test_advanced_level_returns_all_difficulties(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='advanced')
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['count'] == 3

    def test_results_sorted_by_astro_score_descending(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='advanced')
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        scores = [t['astro_score'] for t in response.get_json()['targets']]
        assert scores == sorted(scores, reverse=True)

    def test_limit_clamped_to_maximum_of_ten(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='advanced')
        response = client_admin.get('/api/skytonight/recommendations?lang=en&limit=50')
        assert response.status_code == 200
        assert len(response.get_json()['targets']) <= 10

    def test_estimated_hours_is_estimate_when_no_beginner_catalog_match(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='beginner')
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        targets = response.get_json()['targets']
        assert targets[0]['estimated_integration_hours_is_estimate'] is True
        assert targets[0]['estimated_integration_hours'] == 2.0

    def test_estimated_hours_uses_beginner_catalog_match_when_available(self, client_admin, monkeypatch):
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: self._dso_results())
        monkeypatch.setattr(
            skytonight_api_module.beginner_catalog, 'load_beginner_catalog',
            lambda: [{'catalogue_id': 'M42', 'typical_integration_hours': 3}],
        )
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(
            skytonight_api_module.user_manager, 'get_user_preferences',
            lambda user_id: {'experience_level': 'beginner'},
        )
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        targets = response.get_json()['targets']
        assert targets[0]['estimated_integration_hours'] == 3
        assert targets[0]['estimated_integration_hours_is_estimate'] is False

    def test_non_numeric_limit_falls_back_to_default(self, client_admin, monkeypatch):
        self._mock_common(monkeypatch, experience_level='advanced')
        response = client_admin.get('/api/skytonight/recommendations?lang=en&limit=not-a-number')
        assert response.status_code == 200
        assert len(response.get_json()['targets']) <= 5  # default limit

    def test_thumbnail_url_populated_when_coordinates_present(self, client_admin, monkeypatch):
        dso_results = {
            'deep_sky': [
                {
                    'target_id': 't-coords', 'preferred_name': 'Coord Target',
                    'catalogue_names': {'Messier': 'M 42'}, 'object_type': 'Nebula',
                    'magnitude': 4.0, 'size_arcmin': 90.0, 'astro_score': 0.5,
                    'difficulty': 'beginner', 'difficulty_score': 18,
                    'coordinates': {'ra_hours': 5.5, 'dec_degrees': -5.4},
                },
            ]
        }
        monkeypatch.setattr(skytonight_api_module, 'load_json_file', lambda *a, **k: dso_results)
        monkeypatch.setattr(skytonight_api_module.beginner_catalog, 'load_beginner_catalog', lambda: [])
        monkeypatch.setattr(skytonight_api_module.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(skytonight_api_module.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(
            skytonight_api_module.user_manager, 'get_user_preferences',
            lambda user_id: {'experience_level': 'beginner'},
        )
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        targets = response.get_json()['targets']
        assert targets[0]['thumbnail_url'] is not None
        assert targets[0]['thumbnail_url'].startswith('/api/object-image/')

    def test_beginner_catalog_entry_with_blank_catalogue_id_skipped_in_hours_lookup(
        self, client_admin, monkeypatch
    ):
        self._mock_common(monkeypatch, experience_level='advanced')
        monkeypatch.setattr(
            skytonight_api_module.beginner_catalog, 'load_beginner_catalog',
            lambda: [{'catalogue_id': '', 'typical_integration_hours': 9}],
        )
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        assert response.status_code == 200

    def test_unexpected_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            skytonight_api_module.user_manager, 'get_user_preferences',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')),
        )
        response = client_admin.get('/api/skytonight/recommendations?lang=en')
        assert response.status_code == 500
