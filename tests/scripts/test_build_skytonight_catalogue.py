"""Tests for scripts/build_skytonight_catalogue.py: the offline SkyTonight dataset builder entry point."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location(
    'build_skytonight_catalogue', ROOT / 'scripts' / 'build_skytonight_catalogue.py'
)
build_skytonight_catalogue = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_skytonight_catalogue)


@pytest.mark.unit
def test_main_builds_the_dataset_and_prints_its_counts(monkeypatch, capsys):
    """main() builds and saves the dataset once, then prints its generation time and counts."""
    calls = []

    def fake_build():
        calls.append(True)
        return {
            'metadata': {
                'generated_at': '2026-11-17T12:00:00Z',
                'counts': {'deep_sky': 12000, 'bodies': 9, 'comets': 42},
            }
        }

    monkeypatch.setattr(build_skytonight_catalogue, 'build_and_save_default_dataset', fake_build)
    assert build_skytonight_catalogue.main() == 0
    assert calls == [True]
    out = capsys.readouterr().out
    assert 'Generated at: 2026-11-17T12:00:00Z' in out
    assert 'Deep sky targets: 12000' in out
    assert 'Bodies: 9' in out
    assert 'Comets: 42' in out


@pytest.mark.unit
def test_main_tolerates_missing_metadata_fields(monkeypatch, capsys):
    """Missing generation time or counts print 'unknown' and zeros instead of failing."""
    monkeypatch.setattr(build_skytonight_catalogue, 'build_and_save_default_dataset', lambda: {'metadata': {}})
    assert build_skytonight_catalogue.main() == 0
    out = capsys.readouterr().out
    assert 'Generated at: unknown' in out
    assert 'Deep sky targets: 0' in out
    assert 'Comets: 0' in out
