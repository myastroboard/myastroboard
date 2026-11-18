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


def _one_night(**entry_fields):
    return [make_session('s1', [make_night('n1', '2026-01-10')], [make_entry('M 31', 'n1', **entry_fields)])]


class TestDefensiveInputs:
    def test_target_without_a_usable_picture_has_no_picture(self):
        items = [{'id': 'a1', 'name': 'M 31', 'pictures': [{'id': 'p1', 'filename': ''}]}]
        payload = review(_one_night(integration_minutes=60.0, astrodex_item_id='a1'), items)
        assert payload['target_of_year']['picture'] is None

    def test_cover_picture_when_none_was_taken_that_year(self):
        items = [
            {
                'id': 'a1',
                'name': 'M 31',
                'pictures': [
                    {'id': 'p1', 'filename': 'old.jpg', 'date': '2020-01-01', 'rating': 'x'},
                    {'id': 'p2', 'filename': 'cover.jpg', 'date': '2021-01-01', 'is_main': True},
                ],
            }
        ]
        payload = review(_one_night(integration_minutes=60.0, astrodex_item_id='a1'), items)
        assert payload['target_of_year']['picture']['filename'] == 'cover.jpg'

    def test_captures_without_integration_have_no_target_of_the_year(self):
        payload = review(_one_night(frame_count=3))
        assert payload['has_data'] is True
        assert payload['target_of_year'] is None
        assert payload['best_night'] is None

    def test_unnamed_entries_and_junk_items_are_ignored(self):
        night = make_night('n1', '2026-01-10')
        entries = [make_entry('M 31', 'n1', integration_minutes=30.0), make_entry('', 'n1', integration_minutes=10.0)]
        items = [
            'junk',
            {'id': 'a2', 'name': 'M 42', 'pictures': [{'id': 'p', 'filename': 'x.jpg', 'date': '2019-01-01'}]},
        ]
        payload = review([make_session('s1', [night], entries)], items)
        assert payload['best_night']['targets'] == ['M 31']
        assert payload['mosaic'] == []

    def test_an_unreadable_rating_ranks_below_any_rated_picture(self):
        """Among the pictures of the year, one whose rating is not a number is not preferred."""
        items = [
            {
                'id': 'a1',
                'name': 'M 31',
                'pictures': [
                    {'id': 'p1', 'filename': 'unrated.jpg', 'date': '2026-01-10', 'rating': 'great'},
                    {'id': 'p2', 'filename': 'rated.jpg', 'date': '2026-01-11', 'rating': 2},
                ],
            }
        ]
        payload = review(_one_night(integration_minutes=60.0, astrodex_item_id='a1'), items)
        assert payload['target_of_year']['picture']['filename'] == 'rated.jpg'

    def test_undated_hours_add_no_year(self):
        """Hours logged on a night without a date do not invent a year to review."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', ''), make_night('n2', '2026-01-10')],
                [
                    make_entry('M 31', 'n1', integration_minutes=30.0),
                    make_entry('M 45', 'n2', integration_minutes=30.0),
                ],
            )
        ]
        facts = collect_progress(sessions, [], resolve=fake_resolve)
        assert available_years(facts) == [2026]

    def test_a_catalogue_without_new_objects_this_year_is_left_out(self):
        """Caldwell objects all captured in earlier years make no Caldwell row; Messier always has one."""

        def resolve(name, catalogue):
            if name == 'C 14':
                return {
                    'group_id': 'dso-c14',
                    'object_type': 'Open Cluster',
                    'category': 'deep_sky',
                    'aliases': {'Caldwell': 'C 14'},
                }
            return fake_resolve(name, catalogue)

        sessions = [
            make_session('s0', [make_night('n0', '2025-10-01')], [make_entry('C 14', 'n0', integration_minutes=60.0)]),
            make_session('s1', [make_night('n1', '2026-01-10')], [make_entry('M 31', 'n1', integration_minutes=60.0)]),
        ]
        facts = collect_progress(sessions, [], resolve=resolve)
        payload = build_year_review(sessions, [], 2026, facts, TOTALS)
        assert [row['catalogue'] for row in payload['catalogues']] == ['Messier']


class TestFigureHelpers:
    """The helpers tolerate figures the public builder never hands them today."""

    def test_best_picture_without_a_year_is_the_cover(self):
        from observation.year_review import _best_picture

        item = {'pictures': [{'filename': 'a.jpg'}, {'filename': 'cover.jpg', 'is_main': True}]}
        assert _best_picture(item, None)['filename'] == 'cover.jpg'

    def test_favourite_class_ignores_unknown_keys(self):
        from observation.year_review import _favourite_class

        figures = {'keys': {'gone'}, 'minutes_by_key': {'gone': 30.0}}
        assert _favourite_class({'captures': {}}, figures) is None

    def test_no_target_of_the_year_without_positive_hours(self):
        from observation.year_review import _target_of_year

        figures = {'keys': {'dso-m31'}, 'minutes_by_key': {'dso-m31': 0.0}}
        assert _target_of_year({'captures': {}}, figures, {}, 2026) is None
