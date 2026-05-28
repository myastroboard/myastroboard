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
import skytonight_api as skytonight_api_module  # type: ignore[import-not-found]
from app import app  # type: ignore[import-not-found]
from auth import user_manager  # type: ignore[import-not-found]
from skytonight_models import SkyTonightTarget  # type: ignore[import-not-found]


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
    monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda: False)
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
    monkeypatch.setattr(skytonight_api_module, 'has_calculation_results', lambda: False)
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

    monkeypatch.setattr(skytonight_api_module, 'has_dso_results', lambda: True)
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
        lambda name, config=None: {'found': False},
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
        lambda name, config=None: fake_result,
    )
    response = client_admin.get('/api/skytonight/target-debug?name=M+31')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['found'] is True
    assert payload['overall'] == 'visible'
    assert payload['constraints']['horizon_active'] is False
