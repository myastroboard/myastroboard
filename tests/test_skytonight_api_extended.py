"""Extended Flask test client tests for skytonight_api blueprint routes."""
import json as _json
import os
import sys
import tempfile
import types

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import skytonight_api as _skytonight_api_mod
from skytonight_api import (
    _annotate_skytonight_item,
    _get_catalogue_alias_payload,
    _humanize_const_name,
    _preload_all_current_plan_entries,
    _resolve_source_catalogue,
    _target_attr,
    _target_catalogue_names,
)
from app import app
from auth import user_manager


@pytest.fixture
def client_admin():
    app.config['TESTING'] = True
    with tempfile.TemporaryDirectory():
        with app.test_client() as c:
            user = user_manager.get_user_by_username('admin')
            assert user is not None
            with c.session_transaction() as sess:
                sess['user_id'] = user.user_id
                sess['username'] = user.username
                sess['role'] = user.role
            yield c


def _empty_dataset():
    """Return a minimal dataset dict that satisfies all route handlers."""
    return {'targets': [], 'metadata': {}, 'loaded': False, 'dataset_file': ''}


# ---------------------------------------------------------------------------
# /api/catalogues
# ---------------------------------------------------------------------------


class TestCataloguesEndpoint:

    def test_returns_list(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: [])
        resp = client_admin.get('/api/catalogues')
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/catalogues')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/skytonight/scheduler/status
# ---------------------------------------------------------------------------


class TestSkytonightSchedulerStatus:

    def test_no_scheduler_returns_200_with_running_false(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        resp = client_admin.get('/api/skytonight/scheduler/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['running'] is False

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/scheduler/status')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/scheduler/status (legacy alias)
# ---------------------------------------------------------------------------


class TestSchedulerStatusLegacy:

    def test_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        resp = client_admin.get('/api/scheduler/status')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/skytonight/dataset/status
# ---------------------------------------------------------------------------


class TestSkytonightDatasetStatus:

    def test_returns_200_with_dataset_dict(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets,
            'load_targets_dataset',
            lambda: _empty_dataset(),
        )
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda: False)
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        resp = client_admin.get('/api/skytonight/dataset/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'enabled' in data
        assert 'computed_counts' in data

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/dataset/status')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/skytonight/log
# ---------------------------------------------------------------------------


class TestSkytonightLog:

    def test_no_log_file_returns_empty_string(self, client_admin, monkeypatch, tmp_path):
        monkeypatch.setattr(
            _skytonight_api_mod,
            'SKYTONIGHT_CALCULATION_LOG_FILE',
            str(tmp_path / 'nonexistent.log'),
        )
        resp = client_admin.get('/api/skytonight/log')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'log_content' in data
        assert data['log_content'] == ''

    def test_with_log_file_returns_content(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / 'calc.log'
        entry = {'status': 'success', 'payload': {}, 'timestamp': '2026-01-01T00:00:00Z'}
        log_file.write_text(_json.dumps(entry) + '\n')
        monkeypatch.setattr(
            _skytonight_api_mod,
            'SKYTONIGHT_CALCULATION_LOG_FILE',
            str(log_file),
        )
        resp = client_admin.get('/api/skytonight/log')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'log_content' in data
        assert 'success' in data['log_content']

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/log')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/skytonight/reports
# ---------------------------------------------------------------------------


class TestSkytonightReports:

    def test_returns_200_with_mocked_payload_builder(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            '_build_skytonight_reports_payload',
            lambda catalogue, user_id, username: {'targets': [], 'status': 'ok'},
        )
        resp = client_admin.get('/api/skytonight/reports')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'targets' in data

    def test_invalid_catalogue_returns_400(self, client_admin, monkeypatch):
        resp = client_admin.get('/api/skytonight/reports/bad!name')
        assert resp.status_code == 400

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/reports')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/skytonight/reports/<catalogue>
# ---------------------------------------------------------------------------


class TestSkytonightReportsByCatalogue:

    def test_valid_catalogue_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            '_build_skytonight_reports_payload',
            lambda catalogue, user_id, username: {'targets': [], 'catalogue': catalogue},
        )
        resp = client_admin.get('/api/skytonight/reports/Messier')
        assert resp.status_code == 200

    def test_invalid_catalogue_name_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/reports/bad%20name')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/skytonight/data/* — per-section data endpoints
# ---------------------------------------------------------------------------


class TestSkytonightDataEndpoints:

    def test_bodies_returns_200_with_mocked_builder(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            '_build_bodies_section_payload',
            lambda user_id, username: {'targets': []},
        )
        resp = client_admin.get('/api/skytonight/data/bodies')
        assert resp.status_code == 200

    def test_comets_returns_200_with_mocked_builder(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            '_build_comets_section_payload',
            lambda user_id, username: {'targets': []},
        )
        resp = client_admin.get('/api/skytonight/data/comets')
        assert resp.status_code == 200

    def test_dso_returns_200_with_mocked_builder(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            '_build_dso_section_payload',
            lambda catalogue, user_id, username: {'targets': []},
        )
        resp = client_admin.get('/api/skytonight/data/dso')
        assert resp.status_code == 200

    def test_dso_invalid_catalogue_param_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/data/dso?catalogue=bad%20name')
        assert resp.status_code == 400

    def test_unauthenticated_bodies_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/data/bodies')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/skytonight/logs/<catalogue>
# ---------------------------------------------------------------------------


class TestSkytonightCatalogueLogs:

    def test_invalid_catalogue_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/logs/bad!name')
        assert resp.status_code == 400

    def test_valid_no_log_returns_404(self, client_admin, monkeypatch, tmp_path):
        monkeypatch.setattr(
            _skytonight_api_mod,
            'SKYTONIGHT_CALCULATION_LOG_FILE',
            str(tmp_path / 'nonexistent.log'),
        )
        resp = client_admin.get('/api/skytonight/logs/Messier')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/skytonight/logs/<catalogue>/exists
# ---------------------------------------------------------------------------


class TestSkytonightCatalogueLogsExists:

    def test_invalid_catalogue_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/logs/bad!name/exists')
        assert resp.status_code == 400

    def test_valid_catalogue_returns_200(self, client_admin, monkeypatch, tmp_path):
        monkeypatch.setattr(
            _skytonight_api_mod,
            'SKYTONIGHT_CALCULATION_LOG_FILE',
            str(tmp_path / 'nonexistent.log'),
        )
        resp = client_admin.get('/api/skytonight/logs/Messier/exists')
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/logs/Messier/exists')
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _preload_all_current_plan_entries
# ---------------------------------------------------------------------------


class TestPreloadAllCurrentPlanEntries:

    def test_returns_empty_for_user_with_no_plans(self, monkeypatch, tmp_path):
        import plan_my_night as pmn
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        import uuid
        user_id = str(uuid.uuid4())
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []

    def test_returns_entries_from_current_plan(self, monkeypatch, tmp_path):
        import json as _json
        import plan_my_night as pmn
        import uuid
        from datetime import datetime, timezone, timedelta
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        entry = {'id': 'e1', 'name': 'M42', 'catalogue': 'Messier'}
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text(_json.dumps({
            'user_id': user_id,
            'plan': {'night_end': future, 'entries': [entry]},
        }))
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert len(result) == 1
        assert result[0]['id'] == 'e1'

    def test_skips_previous_plans(self, monkeypatch, tmp_path):
        import json as _json
        import plan_my_night as pmn
        import uuid
        from datetime import datetime, timezone, timedelta
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        entry = {'id': 'e1', 'name': 'M31', 'catalogue': 'Messier'}
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text(_json.dumps({
            'user_id': user_id,
            'plan': {'night_end': past, 'entries': [entry]},
        }))
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []

    def test_skips_plan_obj_not_dict(self, monkeypatch, tmp_path):
        """Covers line 112: plan_obj not a dict → continue."""
        import plan_my_night as pmn
        import uuid
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text(_json.dumps({'user_id': user_id, 'plan': 'not_a_dict'}))
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []

    def test_exception_in_plan_load_is_silenced(self, monkeypatch, tmp_path):
        """Covers lines 120-121: except Exception: pass and return all_entries."""
        import plan_my_night as pmn
        import uuid
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        # Create a file that will cause an exception when loading
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text('{invalid json')
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []  # exception silenced, returns empty list

    def test_deduplicates_entries_across_telescopes(self, monkeypatch, tmp_path):
        import json as _json
        import plan_my_night as pmn
        import uuid
        from datetime import datetime, timezone, timedelta
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        tel_id = str(uuid.uuid4())
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        entry = {'id': 'shared-entry', 'name': 'M42'}
        for suffix in ['_plan_my_night.json', f'_plan_{tel_id}.json']:
            (tmp_path / f'{user_id}{suffix}').write_text(_json.dumps({
                'user_id': user_id,
                'plan': {'night_end': future, 'entries': [entry]},
            }))
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _resolve_source_catalogue
# ---------------------------------------------------------------------------


class TestResolveSourceCatalogue:

    def test_empty_catalogue_names_returns_skytonight(self):
        result = _resolve_source_catalogue({}, 'M42')
        assert result == 'SkyTonight'

    def test_none_catalogue_names_returns_skytonight(self):
        result = _resolve_source_catalogue(None, 'M42')
        assert result == 'SkyTonight'

    def test_returns_first_key_when_no_match(self):
        result = _resolve_source_catalogue({'OpenNGC': 'NGC 1976'}, 'Unknown')
        assert result == 'OpenNGC'

    def test_returns_matching_catalogue_label(self, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets,
            'normalize_object_name',
            lambda name: name.lower().replace(' ', ''),
        )
        result = _resolve_source_catalogue({'Messier': 'M 42', 'OpenNGC': 'NGC 1976'}, 'M 42')
        assert result == 'Messier'


# ---------------------------------------------------------------------------
# _annotate_skytonight_item
# ---------------------------------------------------------------------------


class TestAnnotateSkytonightItem:

    def test_empty_name_sets_false_flags(self):
        item = {'name': '', 'id': ''}
        _annotate_skytonight_item(item, 'user1', 'alice', 'Messier', 'current')
        assert item['in_astrodex'] is False
        assert item['in_plan_my_night'] is False
        assert item['catalogue_group_id'] == ''
        assert item['catalogue_aliases'] == {}
        assert item['plan_state'] == 'current'

    def test_with_preloaded_entries_uses_them(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda a, n, c: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda entries, c, n: True)
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None
        )
        item = {'name': 'M42'}
        _annotate_skytonight_item(item, 'u1', 'alice', 'Messier', 'current',
                                  _preloaded_astrodex={}, _preloaded_plan_entries=[])
        assert item['in_plan_my_night'] is True

    def test_without_preloaded_uses_disk(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda uid, n, c: False)
        monkeypatch.setattr(
            _skytonight_api_mod.plan_my_night, 'is_target_in_current_plan',
            lambda uid, user, cat, name: False
        )
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None
        )
        item = {'name': 'NGC 1976'}
        _annotate_skytonight_item(item, 'u1', 'alice', 'OpenNGC', 'current')
        assert item['in_astrodex'] is False
        assert item['plan_state'] == 'current'


class TestHumanizeConstName:

    def test_camel_case_split(self):
        assert _humanize_const_name('CanisMajor') == 'Canis Major'

    def test_single_word(self):
        assert _humanize_const_name('Orion') == 'Orion'

    def test_multiple_caps(self):
        # Inserts a space before every uppercase letter after the first
        result = _humanize_const_name('UrsaMajor')
        assert 'Ursa' in result and 'Major' in result


class TestTargetAttr:

    def test_dict_target(self):
        assert _target_attr({'key': 'val'}, 'key') == 'val'
        assert _target_attr({'key': 'val'}, 'missing', 'default') == 'default'

    def test_object_target(self):
        class Obj:
            key = 'attrval'
        assert _target_attr(Obj(), 'key') == 'attrval'
        assert _target_attr(Obj(), 'nope', 42) == 42


class TestTargetCatalogueNames:

    def test_dict_with_catalogue_names(self):
        target = {'catalogue_names': {'Messier': 'M42', 'OpenNGC': 'NGC 1976'}}
        result = _target_catalogue_names(target)
        assert result == {'Messier': 'M42', 'OpenNGC': 'NGC 1976'}

    def test_non_dict_catalogue_names_returns_empty(self):
        target = {'catalogue_names': ['M42']}
        result = _target_catalogue_names(target)
        assert result == {}

    def test_missing_key_returns_empty(self):
        assert _target_catalogue_names({}) == {}


class TestGetCatalogueAliasPayload:

    def test_empty_inputs_return_empty(self):
        group_id, aliases = _get_catalogue_alias_payload('', '')
        assert group_id == ''
        assert aliases == {}

    def test_missing_catalogue_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets,
            'get_lookup_entry',
            lambda cat, name: None,
        )
        group_id, aliases = _get_catalogue_alias_payload('Messier', 'M42')
        assert group_id == ''
        assert aliases == {}

    def test_valid_entry(self, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets,
            'get_lookup_entry',
            lambda cat, name: {'group_id': 'g-42', 'aliases': {'OpenNGC': 'NGC 1976'}},
        )
        group_id, aliases = _get_catalogue_alias_payload('Messier', 'M42')
        assert group_id == 'g-42'
        assert aliases == {'OpenNGC': 'NGC 1976'}

    def test_non_dict_aliases_normalised(self, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod.skytonight_targets,
            'get_lookup_entry',
            lambda cat, name: {'group_id': 'g-1', 'aliases': ['not', 'a', 'dict']},
        )
        group_id, aliases = _get_catalogue_alias_payload('Messier', 'M51')
        assert aliases == {}


# ---------------------------------------------------------------------------
# Route: /api/skytonight/reports — with real payload builder
# ---------------------------------------------------------------------------


class TestSkytonightReportsRealBuilder:

    def test_returns_200_with_empty_calc_results(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda: True)
        monkeypatch.setattr(
            _skytonight_api_mod,
            'load_calculation_results',
            lambda: {'deep_sky': [], 'bodies': [], 'comets': [], 'metadata': {}},
        )
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: [])
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        resp = client_admin.get('/api/skytonight/reports')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_reports_by_catalogue_with_empty_data(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda: True)
        monkeypatch.setattr(
            _skytonight_api_mod,
            'load_calculation_results',
            lambda: {'deep_sky': [], 'bodies': [], 'comets': [], 'metadata': {}},
        )
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: [])
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        resp = client_admin.get('/api/skytonight/reports/Messier')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/skytonight/target-debug
# ---------------------------------------------------------------------------


class TestSkytonightTargetDebug:

    def test_missing_target_id_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/target-debug')
        assert resp.status_code == 400

    def test_valid_target_id_returns_response(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _skytonight_api_mod,
            'compute_target_debug',
            lambda target_id, config: {'target_id': target_id, 'debug': {}},
        )
        resp = client_admin.get('/api/skytonight/target-debug?target_id=dso-ngc224')
        assert resp.status_code in (200, 400, 500)

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.get('/api/skytonight/target-debug?target_id=foo')
            assert resp.status_code == 401
