"""Tests for scripts/build_skytonight_catalogue.py: the offline SkyTonight dataset builder entry point."""

import importlib.util
import runpy
import sys
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


@pytest.mark.unit
@pytest.mark.parametrize('backend_on_path', [True, False])
def test_running_the_script_builds_and_exits_with_success(monkeypatch, capsys, backend_on_path):
    """`python scripts/build_skytonight_catalogue.py` puts backend/ on the import path when
    missing (once only), builds the dataset and exits with status 0."""
    from skytonight import skytonight_catalogue_builder

    backend_dir = str(ROOT / 'backend')
    paths = [path for path in sys.path if path != backend_dir]
    if backend_on_path:
        paths.insert(0, backend_dir)
    monkeypatch.setattr(sys, 'path', paths)
    monkeypatch.setattr(
        skytonight_catalogue_builder, 'build_and_save_default_dataset', lambda: {'metadata': {'counts': {}}}
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(ROOT / 'scripts' / 'build_skytonight_catalogue.py'), run_name='__main__')

    assert exit_info.value.code == 0
    assert sys.path.count(backend_dir) == 1
    assert 'SkyTonight dataset generated successfully' in capsys.readouterr().out
