"""Tests for backend/beginner_catalog.py and the /api/beginner-catalog endpoint."""

import os
import sys
import tempfile
import types

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import app as app_module  # type: ignore[import-not-found]  # noqa: E402
import beginner_catalog  # type: ignore[import-not-found]  # noqa: E402
from auth import user_manager  # type: ignore[import-not-found]  # noqa: E402

app = app_module.app


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


def _fake_catalog():
    return [
        {
            'id': 'M42', 'preferred_name': 'Orion Nebula', 'catalogue_id': 'M42',
            'ra_hours': 5.588, 'dec_degrees': -5.39, 'i18n_key': 'm42',
            'typical_integration_hours': 2, 'object_type': 'Nebula', 'constellation': 'Ori',
            'difficulty': 'beginner', 'season': ['winter'],
        },
        {
            'id': 'M99', 'preferred_name': 'Unmatched Galaxy', 'catalogue_id': 'M99',
            'ra_hours': 12.0, 'dec_degrees': 14.0, 'i18n_key': 'm99',
            'typical_integration_hours': 4, 'object_type': 'Galaxy', 'constellation': 'Com',
            'difficulty': 'intermediate', 'season': ['spring'],
        },
    ]


class TestLoadBeginnerCatalog:
    def test_loads_expected_entry_count(self):
        catalog = beginner_catalog.load_beginner_catalog()
        assert len(catalog) == 34

    def test_entries_have_required_keys_and_no_english_text(self):
        catalog = beginner_catalog.load_beginner_catalog()
        required_keys = {
            'id', 'preferred_name', 'catalogue_id', 'ra_hours', 'dec_degrees', 'i18n_key',
            'typical_integration_hours', 'object_type', 'constellation', 'difficulty', 'season',
        }
        for entry in catalog:
            assert required_keys.issubset(entry.keys())
            assert 'why_beginner' not in entry
            assert 'suggested_framing' not in entry

    def test_missing_file_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(beginner_catalog, '_BEGINNER_CATALOG_FILE', '/nonexistent/path.json')
        assert beginner_catalog.load_beginner_catalog() == []


class TestTranslateCatalogEntries:
    def test_resolves_known_key(self):
        translated = beginner_catalog.translate_catalog_entries(_fake_catalog(), 'en')
        m42 = next(e for e in translated if e['id'] == 'M42')
        assert m42['why_beginner'] != 'beginner_catalog.objects.m42.why'
        assert m42['suggested_framing'] != 'beginner_catalog.objects.m42.framing'

    def test_unknown_key_returns_key_itself(self):
        translated = beginner_catalog.translate_catalog_entries(_fake_catalog(), 'en')
        m99 = next(e for e in translated if e['id'] == 'M99')
        assert m99['why_beginner'] == 'beginner_catalog.objects.m99.why'

    def test_does_not_mutate_input(self):
        catalog = _fake_catalog()
        beginner_catalog.translate_catalog_entries(catalog, 'en')
        assert 'why_beginner' not in catalog[0]


class TestEnrichWithSkytonight:
    def test_matched_target_marked_visible_with_astro_score(self):
        catalog = _fake_catalog()
        dso_results = {
            'deep_sky': [
                {'catalogue_names': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'}, 'astro_score': 0.82},
            ]
        }
        enriched = beginner_catalog.enrich_with_skytonight(catalog, dso_results, [], [])
        m42 = next(e for e in enriched if e['id'] == 'M42')
        assert m42['visible_tonight'] is True
        assert m42['astro_score'] == 0.82

    def test_unmatched_target_marked_not_visible(self):
        catalog = _fake_catalog()
        dso_results = {'deep_sky': [{'catalogue_names': {'Messier': 'M 42'}, 'astro_score': 0.5}]}
        enriched = beginner_catalog.enrich_with_skytonight(catalog, dso_results, [], [])
        m99 = next(e for e in enriched if e['id'] == 'M99')
        assert m99['visible_tonight'] is False
        assert m99['astro_score'] is None

    def test_in_astrodex_and_in_plan_detected_by_name_or_catalogue(self):
        catalog = _fake_catalog()
        astrodex_items = [{'name': 'Orion Nebula', 'catalogue': 'M42'}]
        plan_entries = [{'name': 'Unmatched Galaxy', 'catalogue': 'M99'}]
        enriched = beginner_catalog.enrich_with_skytonight(catalog, {}, astrodex_items, plan_entries)
        m42 = next(e for e in enriched if e['id'] == 'M42')
        m99 = next(e for e in enriched if e['id'] == 'M99')
        assert m42['in_astrodex'] is True
        assert m42['in_plan'] is False
        assert m99['in_plan'] is True
        assert m99['in_astrodex'] is False


class TestBeginnerCatalogEndpoint:
    def test_requires_authentication(self):
        app.config['TESTING'] = True
        with app.test_client() as anon_client:
            response = anon_client.get('/api/beginner-catalog')
        assert response.status_code == 401

    def test_returns_all_entries_with_visible_only_false(self, client_admin, monkeypatch):
        monkeypatch.setattr(beginner_catalog, 'load_beginner_catalog', lambda: _fake_catalog())
        monkeypatch.setattr(app_module, 'load_json_file', lambda *a, **k: {})
        monkeypatch.setattr(app_module, 'has_dso_results', lambda: False)

        response = client_admin.get('/api/beginner-catalog?lang=en&visible_only=false')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['total'] == 2
        assert len(payload['objects']) == 2

    def test_visible_only_true_filters_when_results_exist(self, client_admin, monkeypatch):
        monkeypatch.setattr(beginner_catalog, 'load_beginner_catalog', lambda: _fake_catalog())
        monkeypatch.setattr(
            app_module, 'load_json_file',
            lambda *a, **k: {'deep_sky': [{'catalogue_names': {'Messier': 'M 42'}, 'astro_score': 0.5}]},
        )
        monkeypatch.setattr(app_module, 'has_dso_results', lambda: True)

        response = client_admin.get('/api/beginner-catalog?lang=en&visible_only=true')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['total'] == 2
        assert len(payload['objects']) == 1
        assert payload['objects'][0]['id'] == 'M42'

    def test_missing_lang_param_does_not_error(self, client_admin, monkeypatch):
        monkeypatch.setattr(beginner_catalog, 'load_beginner_catalog', lambda: _fake_catalog())
        monkeypatch.setattr(app_module, 'load_json_file', lambda *a, **k: {})
        monkeypatch.setattr(app_module, 'has_dso_results', lambda: False)

        response = client_admin.get('/api/beginner-catalog')
        assert response.status_code == 200
