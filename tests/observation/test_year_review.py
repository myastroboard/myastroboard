"""Tests for the v1.9 year in review.

Built from the same facts as the badges, with the dataset lookup injected, so every screen
can be asserted from hand-made sessions and Astrodex items.
"""

import pytest

from observation.achievements import collect_progress
from observation.year_review import available_years, build_year_review

from .test_achievements import fake_resolve, make_entry, make_night, make_session

TOTALS = {'Messier': 110, 'Caldwell': 109}


def review(sessions, items=(), year=2026):
    facts = collect_progress(sessions, items, resolve=fake_resolve)
    return build_year_review(sessions, list(items), year, facts, TOTALS)


@pytest.fixture
def busy_year():
    """Two sessions in 2026 and one in 2025, with equipment, ratings and conditions."""
    first = make_session(
        's1',
        [make_night('n1', '2026-01-10', sqm=21.1, seeing=2, transparency=7, moon_illumination_percent=3)],
        [
            make_entry('M 31', 'n1', integration_minutes=240.0, rating=4.0),
            make_entry('M 45', 'n1', integration_minutes=60.0, rating=5.0),
        ],
        combination_name='Refractor 80 + ASI533',
    )
    second = make_session(
        's2',
        [make_night('n2', '2026-03-02')],
        [make_entry('M 31', 'n2', integration_minutes=120.0, astrodex_item_id='a1', rating=3.0)],
        combination_name='Seestar S50',
    )
    older = make_session('s0', [make_night('n0', '2025-11-20')], [make_entry('M 42', 'n0', integration_minutes=90.0)])
    items = [
        {
            'id': 'a1',
            'name': 'M 31',
            'pictures': [
                {'id': 'p1', 'filename': 'm31-a.jpg', 'date': '2026-01-10', 'rating': 3, 'is_main': True},
                {'id': 'p2', 'filename': 'm31-b.jpg', 'date': '2026-03-02', 'rating': 5},
                {'id': 'p3', 'filename': 'm31-old.jpg', 'date': '2024-09-01', 'rating': 5},
            ],
        },
        {'id': 'a2', 'name': 'M 42', 'pictures': [{'id': 'p4', 'filename': 'm42.jpg', 'date': '2025-11-20'}]},
    ]
    return [first, second, older], items


class TestEmptyAndSparse:
    def test_empty_account_has_no_screen(self):
        payload = review([])
        assert payload['has_data'] is False
        assert payload['totals'] is None
        assert payload['target_of_year'] is None
        assert payload['best_night'] is None
        assert payload['equipment'] is None
        assert payload['catalogues'] == []
        assert payload['mosaic'] == []
        assert payload['available_years'] == []

    def test_a_year_without_data_hides_every_screen(self, busy_year):
        sessions, items = busy_year
        payload = review(sessions, items, year=2023)
        assert payload['has_data'] is False
        assert payload['available_years'] == [2026, 2025, 2024]

    def test_placeholder_entries_do_not_make_a_year(self):
        """A planned-but-clouded-out entry is logged, not captured."""
        sessions = [make_session('s1', [make_night('n1', '2026-02-02')], [make_entry('M 31', 'n1')])]
        payload = review(sessions)
        assert payload['has_data'] is False
        assert payload['best_night'] is None


class TestScreens:
    def test_totals(self, busy_year):
        sessions, items = busy_year
        totals = review(sessions, items)['totals']
        assert totals['integration_minutes'] == pytest.approx(420.0)
        assert totals['nights'] == 2
        assert totals['sessions'] == 2
        assert totals['targets'] == 2
        # M 31 was already in Astrodex in 2024, so only M 45 is new this year.
        assert totals['new_targets'] == 1

    def test_target_of_the_year_has_the_most_hours_and_its_best_picture(self, busy_year):
        sessions, items = busy_year
        target = review(sessions, items)['target_of_year']
        assert target['key'] == 'dso-m31'
        assert target['integration_minutes'] == pytest.approx(360.0)
        assert target['nights'] == 2
        # The best rated picture taken that year, not an older one or the cover.
        assert target['picture']['filename'] == 'm31-b.jpg'

    def test_best_night_is_the_longest(self, busy_year):
        sessions, items = busy_year
        night = review(sessions, items)['best_night']
        assert night['date'] == '2026-01-10'
        assert night['integration_minutes'] == pytest.approx(300.0)
        assert night['average_rating'] == pytest.approx(4.5)
        assert night['targets'] == ['M 31', 'M 45']
        assert night['sqm'] == pytest.approx(21.1)
        assert night['moon_illumination_percent'] == pytest.approx(3.0)
        assert night['combination_name'] == 'Refractor 80 + ASI533'

    def test_equipment_that_collected_the_most_light(self, busy_year):
        sessions, items = busy_year
        equipment = review(sessions, items)['equipment']
        assert equipment['combination_name'] == 'Refractor 80 + ASI533'
        assert equipment['share_percent'] == 71
        assert equipment['combinations_used'] == 2

    def test_favourite_class_by_hours(self, busy_year):
        sessions, items = busy_year
        favourite = review(sessions, items)['favourite_class']
        assert favourite['object_class'] == 'galaxy'
        assert favourite['classes'] == 2

    def test_catalogue_progress_counts_only_this_years_new_objects(self, busy_year):
        sessions, items = busy_year
        rows = review(sessions, items)['catalogues']
        assert rows == [{'catalogue': 'Messier', 'captured': 3, 'gained': 1, 'total': 110}]

    def test_previous_year_comparison_only_when_it_exists(self, busy_year):
        sessions, items = busy_year
        assert review(sessions, items)['previous_year'] == {
            'year': 2025,
            'integration_minutes': 90.0,
            'targets': 1,
        }
        only_this_year = [sessions[0]]
        assert review(only_this_year)['previous_year'] is None

    def test_mosaic_holds_one_picture_per_object_taken_that_year(self, busy_year):
        sessions, items = busy_year
        mosaic = review(sessions, items)['mosaic']
        assert [picture['filename'] for picture in mosaic] == ['m31-b.jpg']

    def test_gallery_only_year_uses_picture_integration(self):
        items = [
            {
                'id': 'a1',
                'name': 'M 42',
                'pictures': [{'id': 'p1', 'filename': 'm42.jpg', 'date': '2026-02-01', 'integration_minutes': 80}],
            }
        ]
        payload = review([], items)
        assert payload['source'] == 'astrodex'
        assert payload['totals']['integration_minutes'] == pytest.approx(80.0)
        assert payload['totals']['nights'] == 1
        assert payload['best_night'] is None
        assert payload['equipment'] is None

    def test_available_years_are_most_recent_first(self, busy_year):
        sessions, items = busy_year
        facts = collect_progress(sessions, items, resolve=fake_resolve)
        assert available_years(facts) == [2026, 2025, 2024]
