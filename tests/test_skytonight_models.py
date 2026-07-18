"""Tests for skytonight_models.py — SkyTonightCoordinates and SkyTonightTarget."""

from skytonight.skytonight_models import SkyTonightCoordinates, SkyTonightTarget


class TestSkyTonightCoordinates:
    def test_to_dict_returns_correct_values(self):
        coords = SkyTonightCoordinates(ra_hours=5.5, dec_degrees=-30.25)
        d = coords.to_dict()
        assert d == {'ra_hours': 5.5, 'dec_degrees': -30.25}

    def test_to_dict_zero_values(self):
        coords = SkyTonightCoordinates(ra_hours=0.0, dec_degrees=0.0)
        d = coords.to_dict()
        assert d['ra_hours'] == 0.0
        assert d['dec_degrees'] == 0.0


class TestSkyTonightTargetToDict:
    def _make_target(self, **kwargs):
        defaults = dict(
            target_id='t-1',
            category='dso',
            object_type='Galaxy',
            preferred_name='M31',
        )
        defaults.update(kwargs)
        return SkyTonightTarget(**defaults)

    def test_to_dict_coordinates_none(self):
        target = self._make_target(coordinates=None)
        d = target.to_dict()
        assert d['coordinates'] is None

    def test_to_dict_with_coordinates(self):
        coords = SkyTonightCoordinates(ra_hours=0.7, dec_degrees=41.3)
        target = self._make_target(coordinates=coords)
        d = target.to_dict()
        assert d['coordinates'] == {'ra_hours': 0.7, 'dec_degrees': 41.3}

    def test_to_dict_contains_expected_keys(self):
        target = self._make_target()
        d = target.to_dict()
        for key in ('target_id', 'category', 'object_type', 'preferred_name'):
            assert key in d


class TestSkyTonightTargetFromDict:
    def test_from_dict_roundtrip(self):
        coords = SkyTonightCoordinates(ra_hours=2.0, dec_degrees=10.0)
        original = SkyTonightTarget(
            target_id='test-1',
            category='dso',
            object_type='Nebula',
            preferred_name='M42',
            coordinates=coords,
            magnitude=4.0,
        )
        restored = SkyTonightTarget.from_dict(original.to_dict())
        assert restored.target_id == original.target_id
        assert restored.preferred_name == original.preferred_name
        assert restored.coordinates is not None
        assert restored.coordinates.ra_hours == coords.ra_hours

    def test_from_dict_no_coordinates(self):
        data = {
            'target_id': 'body-moon',
            'category': 'bodies',
            'object_type': 'Moon',
            'preferred_name': 'Moon',
        }
        target = SkyTonightTarget.from_dict(data)
        assert target.coordinates is None

    def test_from_dict_non_dict_catalogue_names_defaults_to_empty(self):
        data = {
            'target_id': 'x',
            'category': 'dso',
            'object_type': 'Galaxy',
            'preferred_name': 'X',
            'catalogue_names': 'not-a-dict',
        }
        target = SkyTonightTarget.from_dict(data)
        assert target.catalogue_names == {}

    def test_from_dict_non_list_aliases_defaults_to_empty(self):
        data = {
            'target_id': 'x',
            'category': 'dso',
            'object_type': 'Galaxy',
            'preferred_name': 'X',
            'aliases': 'not-a-list',
        }
        target = SkyTonightTarget.from_dict(data)
        assert target.aliases == []
