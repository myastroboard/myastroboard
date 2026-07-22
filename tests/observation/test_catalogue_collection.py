"""
Tests for the Catalogue Collection module (Astrodex "Pokedex" browsing view)
"""

import pytest

from observation import catalogue_collection
from skytonight.skytonight_models import SkyTonightTarget


def _target(
    target_id,
    catalogue_names,
    preferred_name,
    object_type='Galaxy',
    constellation='And',
    magnitude=8.0,
    size_arcmin=20.0,
    ra_hours=1.0,
    dec_degrees=41.0,
    aliases=None,
    category='deep_sky',
):
    """Build one dataset target in the dataclass form load_targets_dataset() returns."""
    return SkyTonightTarget.from_dict(
        {
            'target_id': target_id,
            'category': category,
            'object_type': object_type,
            'preferred_name': preferred_name,
            'catalogue_names': catalogue_names,
            'aliases': aliases or list(catalogue_names.values()),
            'constellation': constellation,
            'magnitude': magnitude,
            'size_arcmin': size_arcmin,
            'coordinates': (
                None if ra_hours is None else {'ra_hours': ra_hours, 'dec_degrees': dec_degrees}
            ),
        }
    )


FAKE_TARGETS = [
    _target('dso-m31', {'Messier': 'M 31', 'OpenNGC': 'NGC 0224'}, 'Andromeda Galaxy'),
    _target('dso-m2', {'Messier': 'M 2'}, 'M 2', object_type='Globular Cluster', constellation='Aqr', magnitude=6.5),
    _target('dso-m10', {'Messier': 'M 10'}, 'M 10', object_type='Globular Cluster', constellation='Oph', magnitude=6.6),
    # No published magnitude - exercises the "unrated objects stay last" sort rule.
    _target('dso-m45', {'Messier': 'M 45'}, 'Pleiades', object_type='Open Cluster', constellation='Tau', magnitude=None),
    _target('dso-ic434', {'OpenIC': 'IC 434'}, 'Horsehead Nebula', object_type='Nebula', constellation='Ori'),
    # Real bodies carry neither magnitude nor size - they are computed per night, not catalogued.
    _target('body-mars', {'Bodies': 'Mars'}, 'Mars', object_type='Planet', constellation='',
            magnitude=None, size_arcmin=None, ra_hours=None, category='bodies'),
    _target('comet-x', {'Comets': 'C/2024 X1'}, 'C/2024 X1', object_type='Comet', category='comets'),
]


@pytest.fixture(autouse=True)
def fake_dataset(monkeypatch):
    """Serve a small, predictable target dataset instead of the built targets.json."""
    monkeypatch.setattr(
        catalogue_collection.skytonight_targets,
        'load_targets_dataset',
        lambda *args, **kwargs: {'targets': FAKE_TARGETS},
    )


def _item(name, pictures=None):
    return {'name': name, 'pictures': pictures or []}


class TestCatalogueListing:
    """Test the catalogue picker payload"""

    def test_lists_deep_sky_catalogues_and_bodies(self):
        catalogues = {entry['id']: entry for entry in catalogue_collection.list_catalogues([])}
        assert set(catalogues) == {'Bodies', 'Messier', 'OpenNGC', 'OpenIC'}
        assert catalogues['Messier']['total'] == 4
        assert catalogues['OpenNGC']['total'] == 1

    def test_comets_are_excluded(self):
        catalogues = {entry['id'] for entry in catalogue_collection.list_catalogues([])}
        assert 'Comets' not in catalogues

    def test_bodies_include_the_synthetic_sun(self):
        catalogues = {entry['id']: entry for entry in catalogue_collection.list_catalogues([])}
        # One dataset body (Mars) plus the Sun, which the dataset does not carry.
        assert catalogues['Bodies']['total'] == 2

    def test_small_catalogues_are_offered_before_the_reference_ones(self):
        order = [entry['id'] for entry in catalogue_collection.list_catalogues([])]
        assert order.index('Messier') < order.index('OpenNGC')

    def test_caught_object_counts_in_every_catalogue_it_belongs_to(self):
        catalogues = {entry['id']: entry for entry in catalogue_collection.list_catalogues([_item('M 31')])}
        # M 31 and NGC 224 are the same object, so it counts once in each catalogue.
        assert catalogues['Messier']['caught'] == 1
        assert catalogues['OpenNGC']['caught'] == 1
        assert catalogues['OpenIC']['caught'] == 0


class TestCaughtDetection:
    """Test how Astrodex items are matched back onto catalogue objects"""

    def test_matches_an_item_saved_under_its_display_label(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('M31 - Andromeda Galaxy')])
        caught = {card['catalogue_id'] for card in page['items'] if card['caught']}
        assert caught == {'M 31'}

    def test_matches_across_catalogues(self):
        """An object caught under one identifier is caught under all of them."""
        page = catalogue_collection.get_collection_page('OpenNGC', [_item('M 31')])
        assert page['items'][0]['catalogue_id'] == 'NGC 0224'
        assert page['items'][0]['caught'] is True

    def test_unrelated_item_leaves_everything_uncaught(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('NGC 7000')])
        assert page['caught'] == 0
        assert all(card['caught'] is False for card in page['items'])


class TestCardImages:
    """Test which picture a card ends up showing"""

    def test_caught_object_uses_its_main_picture(self):
        pictures = [
            {'filename': 'first.jpg', 'is_main': False},
            {'filename': 'cover.jpg', 'is_main': True},
        ]
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31', pictures)], caught='yes')
        card = page['items'][0]
        assert card['image_url'] == '/api/astrodex/images/cover.jpg'
        assert card['image_source'] == 'astrodex'
        assert card['picture_count'] == 2

    def test_caught_object_without_a_main_flag_falls_back_to_the_first_picture(self):
        pictures = [{'filename': 'only.jpg', 'is_main': False}]
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31', pictures)], caught='yes')
        assert page['items'][0]['image_url'] == '/api/astrodex/images/only.jpg'

    def test_caught_object_without_pictures_still_shows_the_sky_survey_preview(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31')], caught='yes')
        card = page['items'][0]
        assert card['caught'] is True
        assert card['image_source'] == 'dss2'
        assert card['image_url'].startswith('/api/object-image/')

    def test_uncaught_deep_sky_object_uses_the_sky_survey_preview(self):
        page = catalogue_collection.get_collection_page('Messier', [])
        assert all(card['image_source'] == 'dss2' for card in page['items'])

    def test_bodies_use_bundled_artwork(self):
        page = catalogue_collection.get_collection_page('Bodies', [])
        images = {card['catalogue_id']: card['image_url'] for card in page['items']}
        assert images['Mars'] == '/static/img/bodies/mars.svg'
        assert images['Sun'] == '/static/img/bodies/sun.svg'

    def test_a_caught_body_shows_the_user_photo_instead_of_the_artwork(self):
        pictures = [{'filename': 'mars.jpg', 'is_main': True}]
        page = catalogue_collection.get_collection_page('Bodies', [_item('Mars', pictures)], caught='yes')
        assert page['items'][0]['image_url'] == '/api/astrodex/images/mars.jpg'


class TestConstellationNames:
    """The dataset stores IAU abbreviations; cards must carry the full name"""

    def test_abbreviations_are_expanded(self):
        page = catalogue_collection.get_collection_page('Messier', [])
        constellations = {card['constellation'] for card in page['items']}
        assert constellations == {'Andromeda', 'Aquarius', 'Ophiuchus', 'Taurus'}

    def test_pyongc_serpens_halves_are_expanded(self):
        """Se1/Se2 are PyOngc-only codes absent from the IAU enum."""
        assert catalogue_collection._full_constellation_name('Se1') == 'Serpens Caput'
        assert catalogue_collection._full_constellation_name('Se2') == 'Serpens Cauda'

    def test_unknown_values_pass_through(self):
        assert catalogue_collection._full_constellation_name('Nonsense') == 'Nonsense'
        assert catalogue_collection._full_constellation_name(None) == ''

    def test_filter_uses_the_expanded_name(self):
        page = catalogue_collection.get_collection_page('Messier', [], constellation='Taurus')
        assert [card['catalogue_id'] for card in page['items']] == ['M 45']


class TestDifficulty:
    """Difficulty is derived from the catalogue itself, not from a night's results"""

    def test_every_rateable_object_gets_a_label(self):
        page = catalogue_collection.get_collection_page('Messier', [])
        labels = {card['catalogue_id']: card['difficulty'] for card in page['items']}
        # M 45 has a size but no magnitude, so it is still rateable via the size fallback.
        assert all(label in ('beginner', 'intermediate', 'advanced') for label in labels.values())

    def test_solar_system_bodies_are_not_rated(self):
        """Bodies have neither magnitude nor size, so a label would be a guess."""
        page = catalogue_collection.get_collection_page('Bodies', [])
        assert all(card['difficulty'] is None for card in page['items'])

    def test_a_bright_large_object_is_easier_than_a_faint_one(self):
        easy = catalogue_collection._difficulty_for(magnitude=3.0, size_arcmin=180.0)
        hard = catalogue_collection._difficulty_for(magnitude=15.0, size_arcmin=0.5)
        assert catalogue_collection._DIFFICULTY_ORDER[easy] < catalogue_collection._DIFFICULTY_ORDER[hard]

    def test_filter_by_difficulty(self):
        page = catalogue_collection.get_collection_page('Messier', [], difficulty='beginner')
        assert page['filtered_total'] >= 1
        assert all(card['difficulty'] == 'beginner' for card in page['items'])

    def test_an_unknown_difficulty_filter_is_ignored(self):
        page = catalogue_collection.get_collection_page('Messier', [], difficulty='impossible')
        assert page['filtered_total'] == 4

    def test_unrated_objects_stay_last_in_both_directions(self):
        for order in ('asc', 'desc'):
            page = catalogue_collection.get_collection_page('Bodies', [], sort='difficulty', order=order)
            assert page['items'][-1]['difficulty'] is None, order


class TestSorting:
    """Test the sort options offered by the collection filters"""

    def test_catalogue_ids_sort_numerically(self):
        page = catalogue_collection.get_collection_page('Messier', [])
        assert [card['catalogue_id'] for card in page['items']] == ['M 2', 'M 10', 'M 31', 'M 45']

    def test_descending_order_reverses_catalogue_ids(self):
        page = catalogue_collection.get_collection_page('Messier', [], order='desc')
        assert [card['catalogue_id'] for card in page['items']] == ['M 45', 'M 31', 'M 10', 'M 2']

    def test_sort_by_name(self):
        page = catalogue_collection.get_collection_page('Messier', [], sort='name')
        assert page['items'][0]['preferred_name'] == 'Andromeda Galaxy'

    def test_sort_by_caught_puts_captured_objects_last_ascending(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31')], sort='caught')
        assert page['items'][-1]['catalogue_id'] == 'M 31'

    def test_objects_without_a_magnitude_stay_last_in_both_directions(self):
        for order in ('asc', 'desc'):
            page = catalogue_collection.get_collection_page('Messier', [], sort='magnitude', order=order)
            assert page['items'][-1]['catalogue_id'] == 'M 45', order

    def test_an_unknown_sort_field_falls_back_to_the_catalogue_id(self):
        page = catalogue_collection.get_collection_page('Messier', [], sort='not-a-field')
        assert [card['catalogue_id'] for card in page['items']] == ['M 2', 'M 10', 'M 31', 'M 45']


class TestFilters:
    """Test the search, type, constellation and captured filters"""

    def test_filter_by_type(self):
        page = catalogue_collection.get_collection_page('Messier', [], object_type='Globular Cluster')
        assert {card['catalogue_id'] for card in page['items']} == {'M 2', 'M 10'}

    def test_filter_by_constellation(self):
        page = catalogue_collection.get_collection_page('Messier', [], constellation='Taurus')
        assert [card['catalogue_id'] for card in page['items']] == ['M 45']

    def test_search_matches_identifier_and_name_case_insensitively(self):
        page = catalogue_collection.get_collection_page('Messier', [], search='andromeda')
        assert [card['catalogue_id'] for card in page['items']] == ['M 31']

    def test_filter_uncaught_only(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31')], caught='no')
        assert 'M 31' not in {card['catalogue_id'] for card in page['items']}
        assert page['filtered_total'] == 3

    def test_counters_describe_the_whole_catalogue_not_the_filtered_view(self):
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31')], caught='yes')
        assert page['total'] == 4
        assert page['caught'] == 1
        assert page['filtered_total'] == 1

    def test_filter_options_cover_the_whole_catalogue(self):
        """The type/constellation dropdowns must not shrink to whatever the filter left."""
        page = catalogue_collection.get_collection_page('Messier', [], object_type='Open Cluster')
        assert 'Globular Cluster' in page['types']
        assert 'Aquarius' in page['constellations']


class TestPagination:
    """Test page slicing and its bounds"""

    def test_page_size_slices_the_result(self):
        page = catalogue_collection.get_collection_page('Messier', [], page_size=2)
        assert len(page['items']) == 2
        assert page['total_pages'] == 2

    def test_a_page_past_the_end_clamps_to_the_last_page(self):
        page = catalogue_collection.get_collection_page('Messier', [], page=99, page_size=2)
        assert page['page'] == 1
        assert [card['catalogue_id'] for card in page['items']] == ['M 31', 'M 45']

    def test_page_size_is_capped(self):
        page = catalogue_collection.get_collection_page('Messier', [], page_size=99999)
        assert page['page_size'] == catalogue_collection.MAX_PAGE_SIZE

    def test_an_empty_result_still_reports_one_page(self):
        page = catalogue_collection.get_collection_page('Messier', [], search='no-such-object')
        assert page['items'] == []
        assert page['total_pages'] == 1


class TestDictTargets:
    """The dataset is normally loaded as dataclasses, but plain dicts must work too"""

    def test_dict_shaped_targets_are_supported(self, monkeypatch):
        monkeypatch.setattr(
            catalogue_collection.skytonight_targets,
            'load_targets_dataset',
            lambda *args, **kwargs: {'targets': [target.to_dict() for target in FAKE_TARGETS]},
        )
        page = catalogue_collection.get_collection_page('Messier', [_item('M 31')])
        assert page['total'] == 4
        assert page['caught'] == 1
        assert page['items'][0]['catalogue_id'] == 'M 2'
