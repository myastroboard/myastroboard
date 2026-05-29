"""Tests for SkyTonight catalogue dataset building."""

from skytonight_catalogue_builder import (
    PyOngcRow,
    _load_deep_sky_rows,
    build_targets_from_rows,
)
from skytonight_models import SkyTonightTarget


def test_build_targets_from_rows_prefers_openngc_and_deduplicates():
    rows = [
        PyOngcRow(
            name='NGC224',
            object_type='Galaxy',
            constellation='And',
            ra_hours=0.712,
            dec_degrees=41.269,
            magnitude=3.44,
            size_arcmin=189.0,
            messier='M 31',
            ngc_names=['NGC 224'],
            ic_names=[],
            common_names=['Andromeda Galaxy'],
            other_identifiers=['PGC 2557'],
        ),
        PyOngcRow(
            name='M31',
            object_type='Galaxy',
            constellation='And',
            ra_hours=0.712,
            dec_degrees=41.269,
            magnitude=3.44,
            size_arcmin=189.0,
            messier='M 31',
            ngc_names=['NGC 224'],
            ic_names=[],
            common_names=['Great Andromeda Nebula'],
            other_identifiers=[],
        ),
    ]

    targets = build_targets_from_rows(rows)

    assert len(targets) == 1
    target = targets[0]
    assert target.target_id == 'dso-openngc-ngc224'
    # CommonName takes priority in SKYTONIGHT_PREFERRED_NAME_ORDER
    assert target.preferred_name == 'Andromeda Galaxy'
    assert target.catalogue_names['CommonName'] == 'Andromeda Galaxy'
    assert target.catalogue_names['Messier'] == 'M 31'
    assert target.catalogue_names['OpenNGC'] == 'NGC 224'
    assert 'Andromeda Galaxy' in target.aliases
    assert 'Great Andromeda Nebula' in target.aliases


def test_build_targets_from_rows_adds_caldwell_when_mapped():
    rows = [
        PyOngcRow(
            name='NGC7000',
            object_type='Nebula',
            constellation='Cyg',
            ra_hours=20.988,
            dec_degrees=44.528,
            magnitude=4.0,
            size_arcmin=120.0,
            messier=None,
            ngc_names=['NGC 7000'],
            ic_names=[],
            common_names=['North America Nebula'],
            other_identifiers=['LBN 373'],
        ),
    ]

    targets = build_targets_from_rows(rows, caldwell_map={'ngc7000': 'C 20'})

    assert len(targets) == 1
    assert targets[0].catalogue_names['Caldwell'] == 'C 20'


def test_build_targets_from_rows_skips_missing_coordinates_and_duplicates():
    rows = [
        PyOngcRow(
            name='IC1064',
            object_type='Galaxy',
            constellation='Psc',
            ra_hours=None,
            dec_degrees=None,
            magnitude=None,
            size_arcmin=None,
            messier=None,
            ngc_names=[],
            ic_names=['IC 1064'],
            common_names=[],
            other_identifiers=[],
        ),
        PyOngcRow(
            name='IC11',
            object_type='Duplicated record',
            constellation='Cas',
            ra_hours=0.1,
            dec_degrees=60.0,
            magnitude=None,
            size_arcmin=None,
            messier=None,
            ngc_names=[],
            ic_names=['IC 11'],
            common_names=[],
            other_identifiers=[],
        ),
    ]

    targets = build_targets_from_rows(rows)
    assert targets == []


def test_build_and_save_default_dataset_includes_comets(monkeypatch):
    deep_sky_row = PyOngcRow(
        name='NGC224',
        object_type='Galaxy',
        constellation='And',
        ra_hours=0.712,
        dec_degrees=41.269,
        magnitude=3.44,
        size_arcmin=189.0,
        messier='M 31',
        ngc_names=['NGC 224'],
        ic_names=[],
        common_names=['Andromeda Galaxy'],
        other_identifiers=['PGC 2557'],
    )

    comet_target = SkyTonightTarget(
        target_id='comet-13polbers',
        category='comets',
        object_type='Comet',
        preferred_name='13P/Olbers',
        catalogue_names={'Comets': '13P/Olbers'},
        aliases=['13P'],
        source_catalogues=['Comets'],
        translation_key='skytonight.type_comet',
        metadata={'source': 'curated-fallback'},
    )

    body_target = SkyTonightTarget(
        target_id='body-mars',
        category='bodies',
        object_type='Planet',
        preferred_name='Mars',
        catalogue_names={'Bodies': 'Mars'},
        aliases=[],
        source_catalogues=['Bodies'],
        translation_key='skytonight.type_planet',
        metadata={'source': 'builtin-solar-system'},
    )

    monkeypatch.setattr('skytonight_catalogue_builder._load_deep_sky_rows', lambda: ([deep_sky_row], 'targets-yaml'))
    monkeypatch.setattr('skytonight_catalogue_builder.build_body_targets', lambda: [body_target])
    monkeypatch.setattr('skytonight_catalogue_builder.build_comet_targets', lambda source_mode='mpc+jpl': [comet_target])
    monkeypatch.setattr('skytonight_catalogue_builder.save_targets_dataset', lambda targets, metadata=None: True)
    monkeypatch.setattr('skytonight_catalogue_builder._build_standalone_targets_from_json', lambda filename, catalogue_key: [])

    from skytonight_catalogue_builder import build_and_save_default_dataset

    result = build_and_save_default_dataset()
    counts = result['metadata']['counts']

    assert counts['deep_sky'] == 1
    assert counts['bodies'] == 1
    assert counts['comets'] == 1
    assert counts['deep_sky'] + counts['bodies'] + counts['comets'] == 3
    assert 'builtin-solar-system' in result['metadata']['sources']
    assert 'curated-fallback' in result['metadata']['sources']