"""Tests for skytonight_calculator.run_calculations() and load_calculation_results()."""

import json
import os
from datetime import datetime, timezone

import pytest

import skytonight_calculator as calc
from skytonight_calculator import load_calculation_results, run_calculations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_night():
    """Return a (start, end) pair one hour long, anchored in the past."""
    start = datetime(2026, 5, 28, 21, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 28, 22, 0, 0, tzinfo=timezone.utc)
    return start, end


_MINIMAL_CONFIG = {
    'location': {
        'name': 'Test',
        'latitude': 45.5,
        'longitude': -73.5,
        'elevation': 50.0,
        'timezone': 'UTC',
    },
    'skytonight': {'constraints': {}},
}


# ---------------------------------------------------------------------------
# run_calculations — no night window
# ---------------------------------------------------------------------------

def test_run_calculations_no_night_returns_night_found_false(monkeypatch, tmp_path):
    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda lat, lon, tz: None)

    saved = {}

    def _capture_save(path, data):
        saved[os.path.basename(path)] = data

    monkeypatch.setattr(calc, 'save_json_file', _capture_save)

    result = run_calculations(_MINIMAL_CONFIG)

    assert result['night_found'] is False
    assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}


def test_run_calculations_no_night_writes_empty_category_files(monkeypatch):
    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda lat, lon, tz: None)

    saved = {}

    def _capture_save(path, data):
        saved[os.path.basename(path)] = data

    monkeypatch.setattr(calc, 'save_json_file', _capture_save)

    run_calculations(_MINIMAL_CONFIG)

    # All four output files must be written
    assert 'calculation_results.json' in saved
    assert 'bodies_results.json' in saved
    assert 'comets_results.json' in saved
    assert 'dso_results.json' in saved

    assert saved['bodies_results.json']['bodies'] == []
    assert saved['comets_results.json']['comets'] == []
    assert saved['dso_results.json']['deep_sky'] == []

    meta = saved['calculation_results.json']['metadata']
    assert meta['night_start'] is None
    assert meta['night_end'] is None
    assert meta['night_hours'] == 0.0


def test_run_calculations_no_night_counts_all_zero(monkeypatch):
    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda lat, lon, tz: None)
    monkeypatch.setattr(calc, 'save_json_file', lambda *a, **kw: None)

    result = run_calculations(_MINIMAL_CONFIG)
    for key in ('deep_sky', 'bodies', 'comets'):
        assert result['counts'][key] == 0


# ---------------------------------------------------------------------------
# run_calculations — empty dataset with night window
# ---------------------------------------------------------------------------

class _FakeMoon:
    phase = 0.3
    ra_deg = 150.0
    dec_deg = -10.0


class _FakeTimes:
    """Minimal stand-in for an Astropy Time array used only for indexing."""

    def __init__(self):
        self._data = [datetime(2026, 5, 28, 21, 0, tzinfo=timezone.utc),
                      datetime(2026, 5, 28, 22, 0, tzinfo=timezone.utc)]

    def __len__(self):
        return len(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def sidereal_time(self, *a, **kw):
        import types
        obj = types.SimpleNamespace()
        obj.hour = [0.0, 1.0]
        return obj

    def to_datetime(self, **kw):
        return self._data


def test_run_calculations_empty_dataset_returns_night_found_true(monkeypatch):
    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda *a: _fake_night())
    monkeypatch.setattr(calc, '_get_astro_night_window', lambda *a: None)
    monkeypatch.setattr(calc, 'load_targets_dataset', lambda: {'targets': []})
    monkeypatch.setattr(calc, '_sample_times', lambda *a: _FakeTimes())
    monkeypatch.setattr(calc, '_MoonInfo', lambda times, location: _FakeMoon())
    monkeypatch.setattr(calc, '_clear_alttime_files', lambda: None)
    monkeypatch.setattr(calc, 'save_json_file', lambda *a, **kw: None)

    result = run_calculations(_MINIMAL_CONFIG)

    assert result['night_found'] is True
    assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}


def test_run_calculations_empty_dataset_writes_final_files(monkeypatch):
    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda *a: _fake_night())
    monkeypatch.setattr(calc, '_get_astro_night_window', lambda *a: None)
    monkeypatch.setattr(calc, 'load_targets_dataset', lambda: {'targets': []})
    monkeypatch.setattr(calc, '_sample_times', lambda *a: _FakeTimes())
    monkeypatch.setattr(calc, '_MoonInfo', lambda times, location: _FakeMoon())
    monkeypatch.setattr(calc, '_clear_alttime_files', lambda: None)

    saved = {}

    def _capture(path, data):
        saved[os.path.basename(path)] = data

    monkeypatch.setattr(calc, 'save_json_file', _capture)

    run_calculations(_MINIMAL_CONFIG)

    # The final writes must mark in_progress=False
    assert saved['calculation_results.json']['metadata']['in_progress'] is False
    assert saved['bodies_results.json']['metadata']['in_progress'] is False
    assert saved['comets_results.json']['metadata']['in_progress'] is False
    assert saved['dso_results.json']['metadata']['in_progress'] is False


def test_run_calculations_comet_without_coordinates_is_skipped(monkeypatch):
    from skytonight_models import SkyTonightTarget

    comet_no_coords = SkyTonightTarget(
        target_id='comet-nocoords',
        category='comets',
        object_type='Comet',
        preferred_name='TestComet',
        catalogue_names={'Comets': 'TestComet'},
        aliases=[],
        source_catalogues=['Comets'],
        translation_key='skytonight.type_comet',
        coordinates=None,
    )

    monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
    monkeypatch.setattr(calc, '_get_night_window', lambda *a: _fake_night())
    monkeypatch.setattr(calc, '_get_astro_night_window', lambda *a: None)
    monkeypatch.setattr(calc, 'load_targets_dataset', lambda: {'targets': [comet_no_coords]})
    monkeypatch.setattr(calc, '_sample_times', lambda *a: _FakeTimes())
    monkeypatch.setattr(calc, '_MoonInfo', lambda times, location: _FakeMoon())
    monkeypatch.setattr(calc, '_clear_alttime_files', lambda: None)
    monkeypatch.setattr(calc, 'save_json_file', lambda *a, **kw: None)

    result = run_calculations(_MINIMAL_CONFIG)

    assert result['counts']['comets'] == 0


# ---------------------------------------------------------------------------
# load_calculation_results
# ---------------------------------------------------------------------------

def test_load_calculation_results_merges_split_files(monkeypatch):
    fake_meta = {'calculated_at': '2026-05-28T21:00:00+00:00', 'in_progress': False}

    def _fake_load(path, default=None):
        name = os.path.basename(path)
        if name == 'calculation_results.json':
            return {'metadata': fake_meta}
        if name == 'dso_results.json':
            return {'metadata': fake_meta, 'deep_sky': [{'target_id': 'dso-1'}]}
        if name == 'bodies_results.json':
            return {'metadata': fake_meta, 'bodies': [{'target_id': 'body-moon'}]}
        if name == 'comets_results.json':
            return {'metadata': fake_meta, 'comets': [{'target_id': 'comet-1'}]}
        return default or {}

    monkeypatch.setattr(calc, 'load_json_file', _fake_load)

    combined = load_calculation_results()

    assert combined['metadata'] == fake_meta
    assert len(combined['deep_sky']) == 1
    assert len(combined['bodies']) == 1
    assert len(combined['comets']) == 1


def test_load_calculation_results_handles_missing_files(monkeypatch):
    monkeypatch.setattr(calc, 'load_json_file', lambda path, default=None: default or {})

    combined = load_calculation_results()

    assert combined['deep_sky'] == []
    assert combined['bodies'] == []
    assert combined['comets'] == []
    assert combined['metadata'] == {}


def test_load_calculation_results_falls_back_to_data_file_metadata(monkeypatch):
    """When calculation_results.json has no metadata, fall back to a data file's metadata."""
    fallback_meta = {'calculated_at': '2026-05-28T00:00:00+00:00', 'in_progress': False}

    def _fake_load(path, default=None):
        name = os.path.basename(path)
        if name == 'bodies_results.json':
            return {'metadata': fallback_meta, 'bodies': []}
        return default or {}

    monkeypatch.setattr(calc, 'load_json_file', _fake_load)

    combined = load_calculation_results()

    assert combined['metadata'] == fallback_meta
