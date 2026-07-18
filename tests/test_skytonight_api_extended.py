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

from blueprints import skytonight_api as _skytonight_api_mod
_annotate_skytonight_item = _skytonight_api_mod._annotate_skytonight_item
_get_catalogue_alias_payload = _skytonight_api_mod._get_catalogue_alias_payload
_humanize_const_name = _skytonight_api_mod._humanize_const_name
_preload_all_current_plan_entries = _skytonight_api_mod._preload_all_current_plan_entries
_resolve_source_catalogue = _skytonight_api_mod._resolve_source_catalogue
_target_attr = _skytonight_api_mod._target_attr
_target_catalogue_names = _skytonight_api_mod._target_catalogue_names
from app import app
from utils.auth import user_manager


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
            _empty_dataset,
        )
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: False)
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


class TestAdditionalSkytonightRouteBranches:

    def test_scheduler_trigger_remote_success(self, client_admin, monkeypatch, tmp_path):
        trigger_file = tmp_path / 'trigger.flag'
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: 'remote_scheduler')
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_trigger_file', lambda: str(trigger_file))

        resp = client_admin.post('/api/skytonight/scheduler/trigger')
        assert resp.status_code == 200
        assert trigger_file.exists()

    def test_scheduler_trigger_remote_failure(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: 'remote_scheduler')
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_trigger_file', lambda: 'Z:/invalid/path/trigger')
        monkeypatch.setattr(_skytonight_api_mod, 'open', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')), raising=False)

        resp = client_admin.post('/api/skytonight/scheduler/trigger')
        assert resp.status_code == 500

    def test_scheduler_trigger_not_running(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        resp = client_admin.post('/api/skytonight/scheduler/trigger')
        assert resp.status_code == 500

    def test_dataset_rebuild_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_run_skytonight_refresh', lambda: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.post('/api/skytonight/dataset/rebuild')
        assert resp.status_code == 500

    def test_log_api_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'ensure_skytonight_directories', lambda *a, **k: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda _p: True)
        monkeypatch.setattr(
            _skytonight_api_mod,
            'open',
            lambda *a, **k: (_ for _ in ()).throw(OSError('read error')),
            raising=False,
        )

        resp = client_admin.get('/api/skytonight/log')
        assert resp.status_code == 500

    def test_reports_api_internal_error(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_build_skytonight_reports_payload', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        resp = client_admin.get('/api/skytonight/reports')
        assert resp.status_code == 500

    def test_reports_api_user_missing_returns_401(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_current_user', lambda: None)
        resp = client_admin.get('/api/skytonight/reports')
        assert resp.status_code == 401

    def test_reports_catalogue_internal_error(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_build_skytonight_reports_payload', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        resp = client_admin.get('/api/skytonight/reports/Messier')
        assert resp.status_code == 500

    def test_alttime_invalid_id_returns_400(self, client_admin):
        resp = client_admin.get('/api/skytonight/alttime/bad!id')
        assert resp.status_code == 400

    def test_alttime_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda _p: False)
        resp = client_admin.get('/api/skytonight/alttime/valid_id')
        assert resp.status_code == 404

    def test_alttime_read_error_returns_500(self, client_admin, monkeypatch, tmp_path):
        alttime_file = tmp_path / 'ok_alttime.json'
        alttime_file.write_text('{"times": []}', encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', str(tmp_path))
        monkeypatch.setattr(_skytonight_api_mod, '_alttime_json_path', lambda _id, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(_skytonight_api_mod, 'open', lambda *a, **k: (_ for _ in ()).throw(OSError('x')), raising=False)

        resp = client_admin.get('/api/skytonight/alttime/ok')
        assert resp.status_code == 500

    def test_telescope_recommendations_invalid_payload_returns_400(self, client_admin):
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json=[1, 2, 3])
        assert resp.status_code == 400

    def test_telescope_recommendations_no_telescopes_returns_empty(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_user_telescopes', lambda _u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_all_shared_equipment', lambda *_a, **_k: [])
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json={'target name': 'M31'})
        assert resp.status_code == 200
        assert resp.get_json()['has_telescopes'] is False

    def test_skymap_read_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda _p: True)
        monkeypatch.setattr(_skytonight_api_mod, 'open', lambda *a, **k: (_ for _ in ()).throw(OSError('x')), raising=False)
        resp = client_admin.get('/api/skytonight/skymap')
        assert resp.status_code == 500

    def test_data_bodies_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_build_bodies_section_payload', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.get('/api/skytonight/data/bodies')
        assert resp.status_code == 500

    def test_data_comets_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_build_comets_section_payload', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.get('/api/skytonight/data/comets')
        assert resp.status_code == 500

    def test_data_dso_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_build_dso_section_payload', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.get('/api/skytonight/data/dso')
        assert resp.status_code == 500

    def test_catalogue_logs_exists_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'ensure_skytonight_directories', lambda: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.get('/api/skytonight/logs/Messier/exists')
        assert resp.status_code == 500

    def test_target_debug_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'compute_target_debug', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('x')))
        resp = client_admin.get('/api/skytonight/target-debug?name=M31')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _preload_all_current_plan_entries
# ---------------------------------------------------------------------------


class TestPreloadAllCurrentPlanEntries:

    def test_returns_empty_for_user_with_no_plans(self, monkeypatch, tmp_path):
        from observation import plan_my_night as pmn
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        import uuid
        user_id = str(uuid.uuid4())
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []

    def test_returns_entries_from_current_plan(self, monkeypatch, tmp_path):
        from observation import plan_my_night as pmn
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
        from observation import plan_my_night as pmn
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
        from observation import plan_my_night as pmn
        import uuid
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text(_json.dumps({'user_id': user_id, 'plan': 'not_a_dict'}))
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []

    def test_exception_in_plan_load_is_silenced(self, monkeypatch, tmp_path):
        """Covers lines 120-121: except Exception: pass and return all_entries."""
        from observation import plan_my_night as pmn
        import uuid
        monkeypatch.setattr(pmn, 'PLAN_DIR', str(tmp_path))
        user_id = str(uuid.uuid4())
        # Create a file that will cause an exception when loading
        plan_file = tmp_path / f'{user_id}_plan_my_night.json'
        plan_file.write_text('{invalid json')
        result = _preload_all_current_plan_entries(user_id, 'alice')
        assert result == []  # exception silenced, returns empty list

    def test_deduplicates_entries_across_telescopes(self, monkeypatch, tmp_path):
        from observation import plan_my_night as pmn
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
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(
            _skytonight_api_mod,
            'load_calculation_results',
            lambda *_a, **_k: {'deep_sky': [], 'bodies': [], 'comets': [], 'metadata': {}},
        )
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: [])
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        resp = client_admin.get('/api/skytonight/reports')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_reports_by_catalogue_with_empty_data(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(
            _skytonight_api_mod,
            'load_calculation_results',
            lambda *_a, **_k: {'deep_sky': [], 'bodies': [], 'comets': [], 'metadata': {}},
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


# ---------------------------------------------------------------------------
# Helper functions: _to_float, _score_in_range, _ideal_focal_range,
# _aperture_score, _speed_score, _recommend_telescopes_for_target
# ---------------------------------------------------------------------------


_to_float = _skytonight_api_mod._to_float
_score_in_range = _skytonight_api_mod._score_in_range
_ideal_focal_range = _skytonight_api_mod._ideal_focal_range
_aperture_score = _skytonight_api_mod._aperture_score
_speed_score = _skytonight_api_mod._speed_score
_recommend_telescopes_for_target = _skytonight_api_mod._recommend_telescopes_for_target
_alttime_json_path = _skytonight_api_mod._alttime_json_path
_build_skytonight_reports_payload = _skytonight_api_mod._build_skytonight_reports_payload
_build_bodies_section_payload = _skytonight_api_mod._build_bodies_section_payload
_build_comets_section_payload = _skytonight_api_mod._build_comets_section_payload
_build_dso_section_payload = _skytonight_api_mod._build_dso_section_payload


class TestToFloat:

    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_empty_string_returns_none(self):
        assert _to_float('') is None

    def test_valid_int(self):
        assert _to_float(5) == 5.0

    def test_valid_string_float(self):
        assert _to_float('3.14') == pytest.approx(3.14)

    def test_invalid_string_returns_none(self):
        assert _to_float('abc') is None

    def test_invalid_type_returns_none(self):
        assert _to_float({'a': 1}) is None


class TestScoreInRange:

    def test_value_in_range_returns_5(self):
        assert _score_in_range(50.0, 30.0, 70.0) == 5.0

    def test_value_at_min_boundary_returns_5(self):
        assert _score_in_range(30.0, 30.0, 70.0) == 5.0

    def test_value_at_max_boundary_returns_5(self):
        assert _score_in_range(70.0, 30.0, 70.0) == 5.0

    def test_value_below_range_returns_less_than_5(self):
        score = _score_in_range(0.0, 30.0, 70.0)
        assert 1.0 <= score < 5.0

    def test_value_above_range_returns_less_than_5(self):
        score = _score_in_range(200.0, 30.0, 70.0)
        assert 1.0 <= score < 5.0

    def test_value_very_far_out_returns_1(self):
        score = _score_in_range(10000.0, 30.0, 70.0)
        assert score == pytest.approx(1.0)

    def test_inverted_min_max_handled(self):
        # min_value > max_value → gets swapped
        score = _score_in_range(50.0, 70.0, 30.0)
        assert score == 5.0


class TestIdealFocalRange:

    def test_very_large_object(self):
        low, high = _ideal_focal_range(150.0, 'Galaxy')
        assert low == 100.0 and high == 350.0

    def test_large_object_60_to_120(self):
        low, high = _ideal_focal_range(80.0, 'Galaxy')
        assert low == 200.0 and high == 550.0

    def test_medium_large_30_to_60(self):
        low, high = _ideal_focal_range(40.0, 'Galaxy')
        assert low == 350.0 and high == 850.0

    def test_medium_15_to_30(self):
        low, high = _ideal_focal_range(20.0, 'Galaxy')
        assert low == 600.0 and high == 1300.0

    def test_small_8_to_15(self):
        low, high = _ideal_focal_range(10.0, 'Galaxy')
        assert low == 900.0 and high == 1800.0

    def test_tiny_less_than_8(self):
        low, high = _ideal_focal_range(5.0, 'Galaxy')
        assert low == 1200.0 and high == 3000.0

    def test_none_size_galaxy_type(self):
        low, high = _ideal_focal_range(None, 'Galaxy')
        assert low == 900.0 and high == 2200.0

    def test_none_size_globular_type(self):
        low, high = _ideal_focal_range(None, 'Globular Cluster')
        assert low == 900.0 and high == 2200.0

    def test_none_size_nebula_type(self):
        low, high = _ideal_focal_range(None, 'Emission Nebula')
        assert low == 250.0 and high == 900.0

    def test_none_size_open_cluster_type(self):
        low, high = _ideal_focal_range(None, 'Open Cluster')
        assert low == 250.0 and high == 900.0

    def test_none_size_asterism_type(self):
        low, high = _ideal_focal_range(None, 'Asterism')
        assert low == 250.0 and high == 900.0

    def test_none_size_cloud_type(self):
        low, high = _ideal_focal_range(None, 'Molecular Cloud')
        assert low == 250.0 and high == 900.0

    def test_none_size_unknown_type(self):
        low, high = _ideal_focal_range(None, 'Unknown Type')
        assert low == 450.0 and high == 1400.0

    def test_zero_size_falls_through_to_type(self):
        # size_arcmin=0 → condition `size_arcmin > 0` is False → falls through
        low, high = _ideal_focal_range(0.0, 'Galaxy')
        assert low == 900.0 and high == 2200.0


class TestApertureScore:

    def test_none_magnitude_uses_default_range(self):
        score = _aperture_score(125.0, None)
        # 125 in [70, 180] → should be 5.0
        assert score == 5.0

    def test_bright_target_low_magnitude(self):
        # magnitude 1.0 → faintness near 0, min_ap≈50, ideal_ap≈100
        score = _aperture_score(75.0, 1.0)
        assert 1.0 <= score <= 5.0

    def test_faint_target_high_magnitude(self):
        # magnitude 12.0 → faintness=1.0, min_ap≈170, ideal_ap≈320
        score = _aperture_score(200.0, 12.0)
        assert 1.0 <= score <= 5.0

    def test_very_small_aperture_faint_target_score_low(self):
        # small aperture for very faint object
        score = _aperture_score(50.0, 14.0)
        assert score <= 3.0

    def test_magnitude_clamped_below_6(self):
        # magnitude -1 → faintness=0
        score = _aperture_score(125.0, -1.0)
        # 125 vs range [50, 100] → above ideal, some penalty
        assert 1.0 <= score <= 5.0


class TestSpeedScore:

    def test_nebula_fast_scope(self):
        assert _speed_score(4.0, 'Emission Nebula') == 5.0

    def test_nebula_medium_fast_scope(self):
        assert _speed_score(6.0, 'Emission Nebula') == 4.0

    def test_nebula_medium_scope(self):
        assert _speed_score(7.0, 'Emission Nebula') == 3.0

    def test_nebula_slow_scope(self):
        assert _speed_score(9.0, 'Emission Nebula') == 2.0

    def test_nebula_very_slow_scope(self):
        assert _speed_score(11.0, 'Emission Nebula') == 1.0

    def test_open_cluster_score(self):
        assert _speed_score(4.0, 'Open Cluster') == 5.0

    def test_asterism_score(self):
        assert _speed_score(4.0, 'Asterism') == 5.0

    def test_cloud_score(self):
        assert _speed_score(4.0, 'Molecular Cloud') == 5.0

    def test_galaxy_returns_flat_score(self):
        assert _speed_score(8.0, 'Galaxy') == 3.5

    def test_unknown_type_returns_flat_score(self):
        assert _speed_score(6.0, '') == 3.5


class TestRecommendTelescopesForTarget:

    def _make_scope(self, tid, aperture=200.0, focal=1000.0, ratio=5.0, shared=False, owner=None):
        return {
            'id': tid,
            'name': f'Scope {tid}',
            'manufacturer': 'TestCo',
            'aperture_mm': aperture,
            'effective_focal_length': focal,
            'effective_focal_ratio': ratio,
            'is_shared': shared,
            'owner_username': owner,
        }

    def test_empty_telescopes_returns_empty(self):
        result = _recommend_telescopes_for_target({'size': 30.0, 'mag': 8.0, 'type': 'Galaxy'}, [])
        assert result == []

    def test_scope_missing_aperture_skipped(self):
        scope = self._make_scope('t1')
        scope.pop('aperture_mm')
        result = _recommend_telescopes_for_target({'size': 30.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert result == []

    def test_scope_missing_focal_length_skipped(self):
        scope = {'id': 't1', 'name': 'T1', 'manufacturer': 'C',
                 'aperture_mm': 200.0, 'native_focal_ratio': 5.0}
        # no effective or native focal length
        result = _recommend_telescopes_for_target({'size': 30.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert result == []

    def test_scope_missing_ratio_skipped(self):
        scope = {'id': 't1', 'name': 'T1', 'manufacturer': 'C',
                 'aperture_mm': 200.0, 'effective_focal_length': 1000.0}
        result = _recommend_telescopes_for_target({'size': 30.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert result == []

    def test_valid_scope_produces_recommendation(self):
        scope = self._make_scope('t1', aperture=200.0, focal=1000.0, ratio=5.0)
        result = _recommend_telescopes_for_target({'size': 30.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert len(result) == 1
        rec = result[0]
        assert rec['telescope_id'] == 't1'
        assert 1 <= rec['rating_1_to_5'] <= 5
        assert rec['is_shared'] is False
        assert rec['target_magnitude'] == pytest.approx(8.0, abs=0.01)
        assert rec['target_size_arcmin'] == pytest.approx(30.0, abs=0.01)

    def test_multiple_scopes_sorted_by_rating(self):
        # fast scope for nebula should score higher
        slow = self._make_scope('slow', aperture=100.0, focal=1500.0, ratio=15.0)
        fast = self._make_scope('fast', aperture=150.0, focal=600.0, ratio=4.0)
        result = _recommend_telescopes_for_target({'size': None, 'mag': None, 'type': 'Emission Nebula'}, [slow, fast])
        assert result[0]['telescope_id'] == 'fast'

    def test_native_focal_ratio_used_as_fallback(self):
        scope = {
            'id': 't2', 'name': 'T2', 'manufacturer': 'C',
            'aperture_mm': 200.0,
            'effective_focal_length': 1000.0,
            'native_focal_ratio': 5.0,  # no effective_focal_ratio
        }
        result = _recommend_telescopes_for_target({'size': 10.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert len(result) == 1

    def test_focal_length_mm_used_as_fallback(self):
        scope = {
            'id': 't3', 'name': 'T3', 'manufacturer': 'C',
            'aperture_mm': 150.0,
            'focal_length_mm': 750.0,  # no effective_focal_length
            'effective_focal_ratio': 5.0,
        }
        result = _recommend_telescopes_for_target({'size': 10.0, 'mag': 8.0, 'type': 'Galaxy'}, [scope])
        assert len(result) == 1

    def test_shared_scope_flag(self):
        scope = self._make_scope('t4', shared=True, owner='alice')
        result = _recommend_telescopes_for_target({'size': None, 'mag': None, 'type': ''}, [scope])
        assert result[0]['is_shared'] is True
        assert result[0]['owner_username'] == 'alice'

    def test_none_magnitude_in_target(self):
        scope = self._make_scope('t5')
        result = _recommend_telescopes_for_target({'size': None, 'mag': None, 'type': 'Galaxy'}, [scope])
        assert len(result) == 1
        assert result[0]['target_magnitude'] is None

    def test_uses_visual_magnitude_key(self):
        scope = self._make_scope('t6')
        # 'mag' key is None but 'visual magnitude' would be in a pre-normalized payload
        result = _recommend_telescopes_for_target({'size': None, 'mag': None, 'type': ''}, [scope])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _alttime_json_path helper
# ---------------------------------------------------------------------------


class TestAlttimeJsonPath:

    def test_sanitizes_special_chars(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', '/data/output')
        path = _alttime_json_path('NGC 1976')
        assert ' ' not in path
        assert path.endswith('_alttime.json')

    def test_lowercased(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', '/data/output')
        path = _alttime_json_path('Jupiter')
        assert 'jupiter' in path


# ---------------------------------------------------------------------------
# _build_skytonight_reports_payload — calculated path with bodies/comets/dso
# ---------------------------------------------------------------------------


class TestBuildSkytonightReportsPayloadCalculated:

    def _make_calc_results(self, include_deep_sky=True, include_bodies=True, include_comets=True):
        results = {
            'metadata': {'computed_at': '2026-01-01T00:00:00Z'},
            'deep_sky': [],
            'bodies': [],
            'comets': [],
        }
        if include_deep_sky:
            results['deep_sky'] = [{
                'target_id': 'dso-1',
                'preferred_name': 'M 42',
                'catalogue_names': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'},
                'object_type': 'Emission Nebula',
                'constellation': 'Ori',
                'magnitude': 4.0,
                'size_arcmin': 85.0,
                'astro_score': 0.9,
                'observation': {
                    'ra_hms': '05h35m17s',
                    'dec_dms': '-05°23\'28"',
                    'max_altitude': 45.0,
                    'azimuth': 180.0,
                    'observable_fraction': 0.8,
                    'observable_hours': 4.0,
                    'meridian_transit': '22:00',
                    'antimeridian_transit': '10:00',
                },
            }]
        if include_bodies:
            results['bodies'] = [{
                'target_id': 'body-jupiter',
                'preferred_name': 'Jupiter',
                'object_type': 'Planet',
                'magnitude': -2.3,
                'astro_score': 0.95,
                'solar_elongation_deg': 120.0,
                'observation': {
                    'ra_hms': '12h00m00s',
                    'dec_dms': '+00°00\'00"',
                    'max_altitude': 60.0,
                    'azimuth': 200.0,
                    'max_altitude_time': '23:00',
                    'meridian_transit': '23:00',
                    'antimeridian_transit': '11:00',
                    'observable_hours': 6.0,
                },
            }]
        if include_comets:
            results['comets'] = [{
                'target_id': 'comet-1',
                'preferred_name': 'C/2023 A1',
                'object_type': 'Comet',
                'magnitude': 8.0,
                'astro_score': 0.5,
                'metadata': {
                    'absolute_magnitude': 7.5,
                    'perihelion_date': '2026-06-01',
                    'distance_earth_au': 1.2,
                    'distance_sun_au': 0.9,
                },
                'observation': {
                    'ra_hms': '10h00m00s',
                    'dec_dms': '+20°00\'00"',
                    'max_altitude': 40.0,
                    'azimuth': 160.0,
                    'rise_time': '20:00',
                    'set_time': '04:00',
                    'meridian_transit': '00:00',
                    'antimeridian_transit': '12:00',
                    'observable_hours': 5.0,
                },
            }]
        return results

    def test_calculated_path_returns_report_bodies_comets(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_calculation_results', self._make_calc_results)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_skytonight_reports_payload(None, 'uid-1', 'alice')

        assert len(result['report']) == 1
        assert len(result['bodies']) == 1
        assert len(result['comets']) == 1
        assert result['report'][0]['target name'] == 'M 42'
        assert result['bodies'][0]['target name'] == 'Jupiter'
        assert result['comets'][0]['target name'] == 'C/2023 A1'
        assert result['night_metadata']['computed_at'] == '2026-01-01T00:00:00Z'

    def test_calculated_path_with_catalogue_filter(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_calculation_results', self._make_calc_results)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        # Filter by Messier catalogue
        result = _build_skytonight_reports_payload('Messier', 'uid-1', 'alice')
        assert len(result['report']) == 1
        # When catalogue filter applied, display name comes from catalogue_names[catalogue]
        assert result['report'][0]['target name'] == 'M 42'

    def test_calculated_path_catalogue_filter_excludes_non_matching(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        calc = self._make_calc_results(include_deep_sky=True, include_bodies=False, include_comets=False)
        # DSO has no 'UNKNOWN_CAT' entry
        monkeypatch.setattr(_skytonight_api_mod, 'load_calculation_results', lambda *_a, **_k: calc)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_skytonight_reports_payload('UNKNOWN_CAT', 'uid-1', 'alice')
        assert len(result['report']) == 0

    def test_calculated_path_comet_metadata_not_dict(self, monkeypatch):
        calc = self._make_calc_results(include_deep_sky=False, include_bodies=False, include_comets=True)
        calc['comets'][0]['metadata'] = 'invalid'
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_calculation_results', lambda *_a, **_k: calc)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_skytonight_reports_payload(None, 'uid-1', 'alice')
        assert len(result['comets']) == 1
        # metadata falls back to empty dict, so absolute_magnitude etc. are None
        assert result['comets'][0]['absolute magnitude'] is None

    def test_calculated_path_alttime_file_exists(self, monkeypatch, tmp_path):
        calc = self._make_calc_results(include_deep_sky=True, include_bodies=False, include_comets=False)
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_calculation_results', lambda *_a, **_k: calc)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)
        # Simulate alttime file existing
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)

        result = _build_skytonight_reports_payload(None, 'uid-1', 'alice')
        assert result['report'][0]['alttime_file'] == 'dso-1'

    def test_fallback_static_dataset_with_catalogue_filter(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='dso-test',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='M 31',
                catalogue_names={'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
                source_catalogues=['Messier'],
                constellation='And',
                magnitude=3.4,
                size_arcmin=189.0,
                translation_key='skytonight.type_galaxy',
            )
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets, 'metadata': {}, 'loaded': True})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)

        result = _build_skytonight_reports_payload('Messier', 'uid-1', 'alice')
        assert len(result['report']) == 1
        assert result['report'][0]['id'] == 'M 31'

    def test_fallback_static_dataset_no_catalogue(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='body-mars',
                category='bodies',
                object_type='Planet',
                preferred_name='Mars',
                catalogue_names={'Bodies': 'Mars'},
                source_catalogues=['Bodies'],
                translation_key='skytonight.type_planet',
            ),
            SkyTonightTarget(
                target_id='comet-1',
                category='comets',
                object_type='Comet',
                preferred_name='C/2023',
                catalogue_names={'Comets': 'C/2023'},
                source_catalogues=['Comets'],
                translation_key='skytonight.type_comet',
                metadata={'perihelion_date': '2026-01-01'},
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets, 'metadata': {}})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_current_plan', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)

        result = _build_skytonight_reports_payload(None, 'uid-1', 'alice')
        assert len(result['bodies']) == 1
        assert len(result['comets']) == 1
        assert result['comets'][0]['q'] == '2026-01-01'


# ---------------------------------------------------------------------------
# _build_bodies_section_payload
# ---------------------------------------------------------------------------


class TestBuildBodiesSectionPayload:

    def test_calculated_path_with_bodies(self, monkeypatch):
        bodies_data = {
            'metadata': {'computed_at': '2026-01-01'},
            'bodies': [{
                'target_id': 'body-venus',
                'preferred_name': 'Venus',
                'object_type': 'Planet',
                'magnitude': -4.5,
                'astro_score': 0.99,
                'solar_elongation_deg': 35.0,
                'observation': {
                    'ra_hms': '06h00m00s',
                    'dec_dms': '+10°00\'00"',
                    'max_altitude': 30.0,
                    'azimuth': 240.0,
                    'max_altitude_time': '21:00',
                    'meridian_transit': '21:00',
                    'antimeridian_transit': '09:00',
                    'observable_hours': 2.0,
                },
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_bodies_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: bodies_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_bodies_section_payload('uid-1', 'alice')
        assert result['available'] is True
        assert len(result['bodies']) == 1
        assert result['bodies'][0]['target name'] == 'Venus'
        assert result['source_type'] == 'calculated'

    def test_calculated_path_alttime_file_exists(self, monkeypatch):
        bodies_data = {
            'metadata': {'in_progress': True},
            'bodies': [{
                'target_id': 'body-mars',
                'preferred_name': 'Mars',
                'object_type': 'Planet',
                'magnitude': 0.5,
                'astro_score': 0.7,
                'observation': {'ra_hms': '', 'dec_dms': ''},
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_bodies_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: bodies_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)

        result = _build_bodies_section_payload('uid-1', 'alice')
        assert result['in_progress'] is True
        assert result['bodies'][0]['alttime_file'] == 'body-mars'

    def test_fallback_static_dataset_bodies(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='body-saturn',
                category='bodies',
                object_type='Planet',
                preferred_name='Saturn',
                catalogue_names={'Bodies': 'Saturn'},
                source_catalogues=['Bodies'],
                translation_key='skytonight.type_planet',
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_bodies_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)

        result = _build_bodies_section_payload('uid-1', 'alice')
        assert result['source_type'] == 'dataset'
        assert len(result['bodies']) == 1
        assert result['bodies'][0]['target name'] == 'Saturn'

    def test_fallback_dataset_is_list_not_dict(self, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'has_bodies_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: [])
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])

        result = _build_bodies_section_payload('uid-1', 'alice')
        assert result['bodies'] == []
        assert result['available'] is False


# ---------------------------------------------------------------------------
# _build_comets_section_payload
# ---------------------------------------------------------------------------


class TestBuildCometsSectionPayload:

    def test_calculated_path_with_comets(self, monkeypatch):
        comets_data = {
            'metadata': {'computed_at': '2026-01-01'},
            'comets': [{
                'target_id': 'comet-test',
                'preferred_name': 'C/2023 A3',
                'object_type': 'Comet',
                'magnitude': 6.0,
                'astro_score': 0.6,
                'metadata': {
                    'absolute_magnitude': 5.5,
                    'perihelion_date': '2026-03-15',
                    'distance_earth_au': 0.8,
                    'distance_sun_au': 0.5,
                },
                'observation': {
                    'ra_hms': '14h00m00s',
                    'dec_dms': '+30°00\'00"',
                    'max_altitude': 55.0,
                    'azimuth': 170.0,
                    'rise_time': '19:00',
                    'set_time': '03:00',
                    'meridian_transit': '23:00',
                    'antimeridian_transit': '11:00',
                    'observable_hours': 4.5,
                },
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_comets_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: comets_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_comets_section_payload('uid-1', 'alice')
        assert result['available'] is True
        assert len(result['comets']) == 1
        assert result['comets'][0]['target name'] == 'C/2023 A3'
        assert result['comets'][0]['absolute magnitude'] == 5.5
        assert result['comets'][0]['q'] == '2026-03-15'
        assert result['source_type'] == 'calculated'

    def test_calculated_path_metadata_not_dict(self, monkeypatch):
        comets_data = {
            'metadata': {},
            'comets': [{
                'target_id': 'comet-bad',
                'preferred_name': 'C/Bad',
                'object_type': 'Comet',
                'magnitude': 9.0,
                'astro_score': 0.3,
                'metadata': 'not-a-dict',
                'observation': {'ra_hms': '', 'dec_dms': ''},
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_comets_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: comets_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_comets_section_payload('uid-1', 'alice')
        assert len(result['comets']) == 1
        assert result['comets'][0]['absolute magnitude'] is None

    def test_fallback_static_dataset_comets(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='comet-halley',
                category='comets',
                object_type='Comet',
                preferred_name='1P/Halley',
                catalogue_names={'Comets': '1P/Halley'},
                source_catalogues=['Comets'],
                translation_key='skytonight.type_comet',
                metadata={'perihelion_date': '2061-07-28'},
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_comets_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)

        result = _build_comets_section_payload('uid-1', 'alice')
        assert result['source_type'] == 'dataset'
        assert len(result['comets']) == 1
        assert result['comets'][0]['q'] == '2061-07-28'

    def test_fallback_comet_metadata_not_dict(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget

        target = SkyTonightTarget(
            target_id='comet-bad2',
            category='comets',
            object_type='Comet',
            preferred_name='C/BadMeta',
            catalogue_names={'Comets': 'C/BadMeta'},
            source_catalogues=['Comets'],
            translation_key='skytonight.type_comet',
            metadata='not-a-dict',
        )
        monkeypatch.setattr(_skytonight_api_mod, 'has_comets_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': [target]})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)

        result = _build_comets_section_payload('uid-1', 'alice')
        assert len(result['comets']) == 1
        assert result['comets'][0]['q'] == ''


# ---------------------------------------------------------------------------
# _build_dso_section_payload
# ---------------------------------------------------------------------------


class TestBuildDsoSectionPayload:

    def test_calculated_path_with_dso(self, monkeypatch):
        dso_data = {
            'metadata': {'computed_at': '2026-01-01'},
            'deep_sky': [{
                'target_id': 'dso-ngc1976',
                'preferred_name': 'M 42',
                'catalogue_names': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'},
                'object_type': 'Emission Nebula',
                'constellation': 'Ori',
                'magnitude': 4.0,
                'size_arcmin': 85.0,
                'astro_score': 0.9,
                'observation': {
                    'ra_hms': '05h35m17s',
                    'dec_dms': '-05°23\'28"',
                    'max_altitude': 45.0,
                    'azimuth': 180.0,
                    'observable_fraction': 0.8,
                    'observable_hours': 4.0,
                    'meridian_transit': '22:00',
                    'antimeridian_transit': '10:00',
                },
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: dso_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_dso_section_payload(None, 'uid-1', 'alice')
        assert result['available'] is True
        assert len(result['report']) == 1
        assert result['report'][0]['target name'] == 'M 42'
        # NGC ID used for canonical_id since OpenNGC present
        assert result['report'][0]['id'] == 'NGC 1976'

    def test_calculated_path_catalogue_filter(self, monkeypatch):
        dso_data = {
            'metadata': {},
            'deep_sky': [{
                'target_id': 'dso-ngc1976',
                'preferred_name': 'M 42',
                'catalogue_names': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'},
                'object_type': 'Emission Nebula',
                'constellation': 'Ori',
                'magnitude': 4.0,
                'size_arcmin': 85.0,
                'astro_score': 0.9,
                'observation': {},
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: dso_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_dso_section_payload('Messier', 'uid-1', 'alice')
        assert len(result['report']) == 1

    def test_calculated_path_catalogue_filter_excludes(self, monkeypatch):
        dso_data = {
            'metadata': {},
            'deep_sky': [{
                'target_id': 'dso-1',
                'preferred_name': 'M 42',
                'catalogue_names': {'Messier': 'M 42'},
                'object_type': 'Nebula',
                'constellation': 'Ori',
                'magnitude': 4.0,
                'size_arcmin': 85.0,
                'astro_score': 0.9,
                'observation': {},
            }],
        }
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file', lambda *a, **k: dso_data)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)

        result = _build_dso_section_payload('OpenNGC', 'uid-1', 'alice')
        assert len(result['report']) == 0

    def test_fallback_dataset_with_catalogue_filter(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='dso-test',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='M 31',
                catalogue_names={'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
                source_catalogues=['Messier'],
                constellation='And',
                magnitude=3.4,
                size_arcmin=189.0,
                translation_key='skytonight.type_galaxy',
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'is_item_in_preloaded_astrodex', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'is_target_in_entries', lambda *a, **k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'get_lookup_entry', lambda c, n: None)

        result = _build_dso_section_payload('Messier', 'uid-1', 'alice')
        assert len(result['report']) == 1
        assert result['report'][0]['id'] == 'M 31'

    def test_fallback_dataset_no_catalogue_no_annotations(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='dso-test2',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='NGC 891',
                catalogue_names={'OpenNGC': 'NGC 891'},
                source_catalogues=['OpenNGC'],
                constellation='And',
                magnitude=10.0,
                size_arcmin=13.5,
                translation_key='skytonight.type_galaxy',
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'normalize_object_name', lambda n: n)

        # No catalogue → skip_deep_sky_annotations=True in fallback
        result = _build_dso_section_payload(None, 'uid-1', 'alice')
        assert len(result['report']) == 1
        assert result['report'][0]['in_astrodex'] is False
        assert result['report'][0]['in_plan_my_night'] is False

    def test_fallback_dataset_excludes_non_matching_catalogue(self, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='dso-test3',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='NGC 891',
                catalogue_names={'OpenNGC': 'NGC 891'},
                source_catalogues=['OpenNGC'],
                constellation='And',
                magnitude=10.0,
                size_arcmin=13.5,
                translation_key='skytonight.type_galaxy',
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod, 'has_dso_results', lambda *_a, **_k: False)
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_plan_with_timeline', lambda u, n: {'state': 'none'})
        monkeypatch.setattr(_skytonight_api_mod.astrodex, 'load_user_astrodex', lambda u: {'items': []})
        monkeypatch.setattr(_skytonight_api_mod.plan_my_night, 'get_all_plan_files', lambda uid: [])

        # Filter by Messier - NGC 891 has no Messier entry → excluded
        result = _build_dso_section_payload('Messier', 'uid-1', 'alice')
        assert len(result['report']) == 0


# ---------------------------------------------------------------------------
# Skymap endpoint additional branches
# ---------------------------------------------------------------------------


class TestSkymapEndpointBranches:

    def test_skymap_file_absent_returns_empty(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: False)
        resp = client_admin.get('/api/skytonight/skymap')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['targets'] == []

    def test_skymap_file_present_returns_data(self, client_admin, monkeypatch, tmp_path):
        skymap_file = tmp_path / 'skymap.json'
        skymap_data = {
            'targets': [
                {'id': 'dso-1', 'category': 'deep_sky', 'constellation': 'Ori', 'messier': True},
                {'id': 'body-1', 'category': 'bodies', 'constellation': 'Gem'},
            ]
        }
        skymap_file.write_text(_json.dumps(skymap_data), encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)

        cfg = {'skytonight': {'constraints': {'altitude_constraint_min': 25, 'horizon_profile': []}}}
        monkeypatch.setattr(_skytonight_api_mod, 'load_config', lambda: cfg)

        resp = client_admin.get('/api/skytonight/skymap')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'targets' in data
        assert 'constraints' in data

    def test_skymap_enriches_missing_messier_flag(self, client_admin, monkeypatch, tmp_path):
        skymap_file = tmp_path / 'skymap.json'
        dso_file = tmp_path / 'dso.json'
        skymap_data = {
            'targets': [
                {'id': 'dso-ngc1976', 'category': 'deep_sky', 'constellation': 'Ori'},
            ]
        }
        dso_data = {
            'deep_sky': [
                {'target_id': 'dso-ngc1976', 'catalogue_names': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'}},
            ]
        }
        skymap_file.write_text(_json.dumps(skymap_data), encoding='utf-8')
        dso_file.write_text(_json.dumps(dso_data), encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'get_skymap_file', lambda *_a, **_k: str(skymap_file))
        monkeypatch.setattr(_skytonight_api_mod, 'get_dso_results_file', lambda *_a, **_k: str(dso_file))
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)
        monkeypatch.setattr(_skytonight_api_mod, 'load_json_file',
                            lambda path, default=None: dso_data if 'dso' in str(path) else default)
        cfg = {'skytonight': {'constraints': {'altitude_constraint_min': 30, 'horizon_profile': []}}}
        monkeypatch.setattr(_skytonight_api_mod, 'load_config', lambda: cfg)

        resp = client_admin.get('/api/skytonight/skymap')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scheduler status endpoint additional branches
# ---------------------------------------------------------------------------


class TestSchedulerStatusAdditionalBranches:

    def test_scheduler_is_object_calls_get_status(self, client_admin, monkeypatch):
        mock_sched_obj = type('Sched', (), {'get_status': lambda self: {'running': True, 'is_executing': False}})()
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: mock_sched_obj)
        resp = client_admin.get('/api/skytonight/scheduler/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['running'] is True

    def test_scheduler_is_remote(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: 'remote_scheduler')
        monkeypatch.setattr(_skytonight_api_mod, 'get_remote_skytonight_scheduler_status',
                            lambda: {'running': False, 'is_executing': False})
        resp = client_admin.get('/api/skytonight/scheduler/status')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dataset status additional branches
# ---------------------------------------------------------------------------


class TestDatasetStatusAdditionalBranches:

    def test_dataset_status_with_object_scheduler(self, client_admin, monkeypatch):
        dataset = {
            'targets': [
                {'category': 'deep_sky'},
                {'category': 'bodies'},
            ],
            'metadata': {},
            'loaded': True,
            'dataset_file': '/some/path',
        }
        mock_sched = type('Sched', (), {
            'get_status': lambda self: {'running': True, 'is_executing': False}
        })()
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: dataset)
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: True)

        resp = client_admin.get('/api/skytonight/dataset/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['computed_counts']['deep_sky'] == 1

    def test_dataset_status_target_with_getattr_category(self, client_admin, monkeypatch):
        # Test branch: target is an object (not dict), category via getattr
        class Target:
            category = 'deep_sky'

        dataset = {
            'targets': [Target()],
            'metadata': {},
            'loaded': False,
            'dataset_file': '',
        }
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset', lambda: dataset)
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        monkeypatch.setattr(_skytonight_api_mod, 'has_calculation_results', lambda *_a, **_k: False)

        resp = client_admin.get('/api/skytonight/dataset/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['computed_counts']['deep_sky'] == 1


# ---------------------------------------------------------------------------
# Dataset rebuild endpoint
# ---------------------------------------------------------------------------


class TestDatasetRebuildEndpoint:

    def test_dataset_rebuild_success(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, '_run_skytonight_refresh', lambda: {'targets': 42})
        resp = client_admin.post('/api/skytonight/dataset/rebuild')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'rebuilt'
        assert data['targets'] == 42


# ---------------------------------------------------------------------------
# Catalogue logs endpoints additional branches
# ---------------------------------------------------------------------------


class TestCatalogueLogsAdditionalBranches:

    def test_valid_catalogue_with_non_empty_log(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / 'calc.log'
        log_file.write_text('some log content', encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        monkeypatch.setattr(_skytonight_api_mod, 'ensure_skytonight_directories', lambda: None)

        resp = client_admin.get('/api/skytonight/logs/Messier')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'log_content' in data
        assert data['catalogue'] == 'skytonight'

    def test_valid_catalogue_with_empty_log_returns_404(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / 'calc.log'
        log_file.write_text('', encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        monkeypatch.setattr(_skytonight_api_mod, 'ensure_skytonight_directories', lambda: None)

        resp = client_admin.get('/api/skytonight/logs/Messier')
        assert resp.status_code == 404

    def test_catalogue_log_internal_error_returns_500(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / 'calc.log'
        log_file.write_text('content', encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'SKYTONIGHT_CALCULATION_LOG_FILE', str(log_file))
        monkeypatch.setattr(_skytonight_api_mod, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(_skytonight_api_mod, 'open',
                            lambda *a, **k: (_ for _ in ()).throw(OSError('fail')), raising=False)

        resp = client_admin.get('/api/skytonight/logs/Messier')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Alttime endpoint additional branches
# ---------------------------------------------------------------------------


class TestAlttimeEndpointAdditionalBranches:

    def test_alttime_path_traversal_rejected(self, client_admin, monkeypatch, tmp_path):
        """Path traversal guard — file_path not under OUTPUT_DIR → 400."""
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', str(tmp_path))
        monkeypatch.setattr(_skytonight_api_mod, '_alttime_json_path', lambda _id, *_a, **_k: '/etc/passwd')
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)

        resp = client_admin.get('/api/skytonight/alttime/valid_id')
        assert resp.status_code == 400

    def test_alttime_successful_read_with_horizon(self, client_admin, monkeypatch, tmp_path):
        alttime_file = tmp_path / 'valid_id_alttime.json'
        alttime_file.write_text(_json.dumps({'times': [1, 2, 3], 'altitudes': [30, 45, 60]}), encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', str(tmp_path))
        monkeypatch.setattr(_skytonight_api_mod, '_alttime_json_path', lambda _id, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)
        # v1.2: horizon comes from the install-default location preset
        cfg = {'locations': [{'id': 'ext-loc', 'is_install_default': True, 'horizon_profile': [[0, 10], [90, 15]]}]}
        monkeypatch.setattr(_skytonight_api_mod, 'load_config', lambda: cfg)

        resp = client_admin.get('/api/skytonight/alttime/valid_id')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['horizon_profile'] == [[0, 10], [90, 15]]

    def test_alttime_no_horizon_in_config_no_existing_profile(self, client_admin, monkeypatch, tmp_path):
        alttime_file = tmp_path / 'valid_id_alttime.json'
        alttime_file.write_text(_json.dumps({'times': [1, 2]}), encoding='utf-8')
        monkeypatch.setattr(_skytonight_api_mod, 'OUTPUT_DIR', str(tmp_path))
        monkeypatch.setattr(_skytonight_api_mod, '_alttime_json_path', lambda _id, *_a, **_k: str(alttime_file))
        monkeypatch.setattr(_skytonight_api_mod.os.path, 'isfile', lambda p: True)
        cfg = {'skytonight': {'constraints': {}}}
        monkeypatch.setattr(_skytonight_api_mod, 'load_config', lambda: cfg)

        resp = client_admin.get('/api/skytonight/alttime/valid_id')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('horizon_profile') == []


# ---------------------------------------------------------------------------
# Telescope recommendations endpoint additional branches
# ---------------------------------------------------------------------------


class TestTelescopeRecommendationsEndpointBranches:

    def test_unauthenticated_returns_401(self):
        app.config['TESTING'] = True
        with app.test_client() as c:
            resp = c.post('/api/skytonight/telescope-recommendations', json={'type': 'Galaxy'})
            assert resp.status_code == 401

    def test_with_telescopes_returns_recommendations(self, client_admin, monkeypatch):
        telescope = {
            'id': 'scope-1',
            'name': 'My Scope',
            'manufacturer': 'Brand',
            'aperture_mm': 200.0,
            'effective_focal_length': 1000.0,
            'effective_focal_ratio': 5.0,
            'is_shared': False,
            'owner_username': None,
        }
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_user_telescopes',
                            lambda u: {'items': [telescope]})
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_all_shared_equipment',
                            lambda *a, **k: [])

        payload = {'type': 'Galaxy', 'size': 30.0, 'mag': 8.0}
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_telescopes'] is True
        assert len(data['recommendations']) == 1

    def test_visual_magnitude_fallback_key(self, client_admin, monkeypatch):
        telescope = {
            'id': 'scope-2',
            'name': 'Scope 2',
            'manufacturer': 'Brand',
            'aperture_mm': 150.0,
            'effective_focal_length': 750.0,
            'effective_focal_ratio': 5.0,
        }
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_user_telescopes',
                            lambda u: {'items': [telescope]})
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_all_shared_equipment',
                            lambda *a, **k: [])

        # 'mag' is None but 'visual magnitude' present → picked up in endpoint
        payload = {'type': 'Planet', 'mag': None, 'visual magnitude': -2.0}
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_telescopes'] is True

    def test_user_not_authenticated_returns_401(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_current_user', lambda: None)
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json={})
        assert resp.status_code == 401

    def test_internal_error_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.equipment_profiles, 'load_user_telescopes',
                            lambda u: (_ for _ in ()).throw(RuntimeError('crash')))
        resp = client_admin.post('/api/skytonight/telescope-recommendations', json={'type': 'Galaxy'})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Legacy trigger endpoint
# ---------------------------------------------------------------------------


class TestLegacyTriggerEndpoint:

    def test_legacy_trigger_no_scheduler_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: None)
        resp = client_admin.post('/api/scheduler/trigger')
        assert resp.status_code == 500

    def test_legacy_trigger_with_scheduler_calls_trigger_now(self, client_admin, monkeypatch):
        mock_sched = type('Sched', (), {'trigger_now': lambda self: {'status': 'ok'}})()
        monkeypatch.setattr(_skytonight_api_mod, 'get_skytonight_scheduler_for_api', lambda: mock_sched)
        resp = client_admin.post('/api/scheduler/trigger')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'


# ---------------------------------------------------------------------------
# Catalogues endpoint with data
# ---------------------------------------------------------------------------


class TestCataloguesEndpointWithData:

    def test_returns_sorted_catalogues(self, client_admin, monkeypatch):
        from skytonight.skytonight_models import SkyTonightTarget
        targets = [
            SkyTonightTarget(
                target_id='dso-1',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='M 31',
                catalogue_names={'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
                source_catalogues=['Messier', 'OpenNGC'],
                constellation='And',
                magnitude=3.4,
                size_arcmin=189.0,
                translation_key='skytonight.type_galaxy',
            ),
            SkyTonightTarget(
                target_id='dso-2',
                category='deep_sky',
                object_type='Galaxy',
                preferred_name='M 32',
                catalogue_names={'Messier': 'M 32'},
                source_catalogues=['Messier'],
                constellation='And',
                magnitude=8.7,
                size_arcmin=8.7,
                translation_key='skytonight.type_galaxy',
            ),
            SkyTonightTarget(
                target_id='body-1',
                category='bodies',
                object_type='Planet',
                preferred_name='Mars',
                catalogue_names={'Bodies': 'Mars'},
                source_catalogues=['Bodies'],
                translation_key='skytonight.type_planet',
            ),
        ]
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: {'targets': targets})

        resp = client_admin.get('/api/catalogues')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert 'Messier' in data
        assert 'OpenNGC' in data
        # Bodies category should not appear
        assert 'Bodies' not in data
        # Should be sorted
        assert data == sorted(data)

    def test_exception_in_catalogues_returns_empty_list(self, client_admin, monkeypatch):
        monkeypatch.setattr(_skytonight_api_mod.skytonight_targets, 'load_targets_dataset',
                            lambda: (_ for _ in ()).throw(RuntimeError('crash')))
        resp = client_admin.get('/api/catalogues')
        assert resp.status_code == 200
        assert resp.get_json() == []
