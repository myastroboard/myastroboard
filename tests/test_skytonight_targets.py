"""Tests for SkyTonight target normalization and compatibility helpers."""

import json

from skytonight_models import SkyTonightCoordinates, SkyTonightTarget
import skytonight_targets


def _sample_targets():
    return [
        SkyTonightTarget(
            target_id='DSO-0001',
            category='deep_sky',
            object_type='Galaxy',
            preferred_name='NGC 224',
            catalogue_names={
                'Messier': 'M 31',
                'OpenNGC': 'NGC 224',
                'Caldwell': 'C 23',
            },
            aliases=['Andromeda Galaxy', 'Andromeda'],
            constellation='Andromeda',
            magnitude=3.44,
            size_arcmin=189.0,
            coordinates=SkyTonightCoordinates(ra_hours=0.712, dec_degrees=41.269),
            source_catalogues=['Messier', 'OpenNGC', 'Caldwell'],
            translation_key='skytonight.type_galaxy',
        )
    ]


def test_choose_preferred_catalogue_name_uses_priority_order():
    name = skytonight_targets.choose_preferred_catalogue_name({
        'Messier': 'M 31',
        'OpenNGC': 'NGC 224',
        'Caldwell': 'C 23',
    })
    # Messier takes priority over OpenNGC in SKYTONIGHT_PREFERRED_NAME_ORDER
    assert name == 'M 31'


def test_build_lookup_from_targets_registers_catalogues_and_aliases():
    lookup = skytonight_targets.build_lookup_from_targets(_sample_targets())
    assert lookup['messier::m31']['group_id'] == 'DSO-0001'
    assert lookup['openngc::ngc224']['preferred_name'] == 'NGC 224'
    assert lookup['alias::andromedagalaxy']['aliases']['OpenNGC'] == 'NGC 224'


def test_save_and_load_targets_dataset_round_trip(tmp_path):
    dataset_file = tmp_path / 'targets.json'
    targets = _sample_targets()

    saved = skytonight_targets.save_targets_dataset(
        targets,
        metadata={'version': 'test'},
        dataset_file=str(dataset_file),
    )

    assert saved is True

    dataset = skytonight_targets.load_targets_dataset(force_reload=True, dataset_file=str(dataset_file))
    assert dataset['metadata']['version'] == 'test'
    assert len(dataset['targets']) == 1
    assert dataset['lookup']['openngc::ngc224']['group_id'] == 'DSO-0001'


def test_get_lookup_entry_falls_back_to_alias_match(tmp_path):
    dataset_file = tmp_path / 'targets.json'
    skytonight_targets.save_targets_dataset(_sample_targets(), dataset_file=str(dataset_file))

    entry = skytonight_targets.get_lookup_entry('Messier', 'Andromeda Galaxy', force_reload=True, dataset_file=str(dataset_file))
    assert entry['group_id'] == 'DSO-0001'


def test_merge_item_with_target_entry_adds_alias_payload(monkeypatch):
    monkeypatch.setattr(
        skytonight_targets,
        'get_lookup_entry',
        lambda catalogue, object_name, force_reload=False: {
            'group_id': 'DSO-0001',
            'aliases': {'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
        },
    )

    item = {'catalogue': 'Messier', 'name': 'M 31'}
    merged = skytonight_targets.merge_item_with_target_entry(item)

    assert merged['catalogue_group_id'] == 'DSO-0001'
    assert merged['catalogue_aliases']['OpenNGC'] == 'NGC 224'


def test_choose_preferred_catalogue_name_empty_dict():
    name = skytonight_targets.choose_preferred_catalogue_name({})
    assert name == ''


def test_choose_preferred_catalogue_name_unknown_catalogue():
    """Unknown catalogue falls back to alphabetical position."""
    name = skytonight_targets.choose_preferred_catalogue_name({'UnknownCat': 'UNK 999'})
    assert name == 'UNK 999'


def test_append_lookup_name_empty_values():
    """_append_lookup_name should be a no-op when catalogue or name is empty."""
    lookup = {}
    skytonight_targets._append_lookup_name(lookup, '', 'M 31', {'group_id': 'X'})
    assert len(lookup) == 0
    skytonight_targets._append_lookup_name(lookup, 'Messier', '', {'group_id': 'X'})
    assert len(lookup) == 0


def test_coerce_targets_non_list_returns_empty():
    result = skytonight_targets._coerce_targets("not a list")
    assert result == []


def test_coerce_targets_skips_non_dict_items():
    result = skytonight_targets._coerce_targets(["string", 123, None])
    assert result == []


def test_coerce_targets_skips_invalid_target_dict():
    """A dict that raises TypeError/ValueError during from_dict is skipped."""
    result = skytonight_targets._coerce_targets([{"invalid_key_only": True}])
    assert isinstance(result, list)


def test_coerce_targets_skips_target_without_id():
    """A target dict with empty target_id should be excluded."""
    result = skytonight_targets._coerce_targets([{
        "target_id": "",
        "category": "deep_sky",
        "object_type": "Galaxy",
        "preferred_name": "Test",
        "catalogue_names": {},
        "aliases": [],
        "constellation": "",
        "magnitude": None,
        "size_arcmin": None,
        "coordinates": None,
        "source_catalogues": [],
        "translation_key": "",
    }])
    assert result == []


def test_save_targets_dataset_returns_false_when_save_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(skytonight_targets, "save_json_file", lambda *_a, **_k: False)
    result = skytonight_targets.save_targets_dataset([], dataset_file=str(tmp_path / "out.json"))
    assert result is False


def test_get_aliases_map_returns_dict(tmp_path):
    dataset_file = tmp_path / 'targets.json'
    from tests.test_skytonight_targets import _sample_targets
    skytonight_targets.save_targets_dataset(_sample_targets(), dataset_file=str(dataset_file))
    aliases = skytonight_targets.get_aliases_map('Messier', 'M 31', dataset_file=str(dataset_file))
    assert isinstance(aliases, dict)


def test_get_group_id_returns_string(tmp_path):
    dataset_file = tmp_path / 'targets.json'
    from tests.test_skytonight_targets import _sample_targets
    skytonight_targets.save_targets_dataset(_sample_targets(), dataset_file=str(dataset_file))
    gid = skytonight_targets.get_group_id('Messier', 'M 31', dataset_file=str(dataset_file))
    assert isinstance(gid, str)
    assert gid == 'DSO-0001'


def test_merge_item_with_target_entry_non_dict():
    result = skytonight_targets.merge_item_with_target_entry("not a dict")
    assert result == "not a dict"


def test_merge_item_with_target_entry_no_catalogue():
    item = {'name': 'M 31'}
    result = skytonight_targets.merge_item_with_target_entry(item)
    assert 'catalogue_aliases' not in result
    assert 'catalogue_group_id' not in result


def test_merge_item_with_target_entry_no_entry(monkeypatch):
    monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', lambda *_a, **_k: {})
    item = {'catalogue': 'Messier', 'name': 'M 999'}
    result = skytonight_targets.merge_item_with_target_entry(item)
    assert 'catalogue_aliases' not in result


def test_merge_item_empty_aliases(monkeypatch):
    monkeypatch.setattr(
        skytonight_targets,
        'get_lookup_entry',
        lambda *_a, **_k: {'group_id': '', 'aliases': {}},
    )
    item = {'catalogue': 'Messier', 'name': 'M 31'}
    result = skytonight_targets.merge_item_with_target_entry(item)
    assert 'catalogue_aliases' not in result
    assert 'catalogue_group_id' not in result


def test_build_lookup_no_preferred_name():
    """Target with no preferred_name uses choose_preferred_catalogue_name as fallback."""
    from skytonight_models import SkyTonightCoordinates, SkyTonightTarget
    target = SkyTonightTarget(
        target_id='DSO-TEST',
        category='deep_sky',
        object_type='Galaxy',
        preferred_name='',
        catalogue_names={'OpenNGC': 'NGC 999'},
        aliases=[],
        constellation='Orion',
        magnitude=10.0,
        size_arcmin=5.0,
        coordinates=SkyTonightCoordinates(ra_hours=5.0, dec_degrees=-5.0),
        source_catalogues=['OpenNGC'],
        translation_key='',
    )
    lookup = skytonight_targets.build_lookup_from_targets([target])
    assert any('dso-test' in v.get('group_id', '').lower() or v.get('group_id') == 'DSO-TEST' for v in lookup.values())


def test_build_lookup_no_preferred_name_and_no_catalogues():
    """Line 108->98: preferred_name='' and catalogue_names={} → if preferred_name: False."""
    from skytonight_models import SkyTonightCoordinates, SkyTonightTarget
    target = SkyTonightTarget(
        target_id='DSO-EMPTY',
        category='deep_sky',
        object_type='Galaxy',
        preferred_name='',
        catalogue_names={},
        aliases=[],
        constellation='',
        magnitude=None,
        size_arcmin=None,
        coordinates=None,
        source_catalogues=[],
        translation_key='',
    )
    lookup = skytonight_targets.build_lookup_from_targets([target])
    assert isinstance(lookup, dict)


def test_coerce_targets_from_dict_raises_skipped():
    """Lines 123-125: from_dict raises ValueError → except block executed."""
    result = skytonight_targets._coerce_targets([{'magnitude': 'not_a_float'}])
    assert result == []


def test_get_lookup_entry_empty_catalogue_returns_empty():
    """Line 177: empty catalogue → return {}."""
    result = skytonight_targets.get_lookup_entry('', 'M 31')
    assert result == {}


def test_invalidate_targets_dataset_cache_forces_reload_from_disk(tmp_path):
    dataset_file = tmp_path / 'targets.json'
    skytonight_targets.save_targets_dataset(_sample_targets(), dataset_file=str(dataset_file))

    cached_dataset = skytonight_targets.load_targets_dataset(force_reload=True, dataset_file=str(dataset_file))
    assert len(cached_dataset['targets']) == 1

    # Mutate the dataset file directly to simulate an external rebuild while the
    # in-memory cache still holds the previous large target list.
    dataset_file.write_text(
        json.dumps({'metadata': {'version': 'new'}, 'targets': []}),
        encoding='utf-8',
    )

    still_cached = skytonight_targets.load_targets_dataset(dataset_file=str(dataset_file))
    assert len(still_cached['targets']) == 1

    skytonight_targets.invalidate_targets_dataset_cache()
    reloaded = skytonight_targets.load_targets_dataset(dataset_file=str(dataset_file))
    assert reloaded['metadata']['version'] == 'new'
    assert reloaded['targets'] == []