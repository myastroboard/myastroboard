"""Tests for the Session Analytics (v1.5) aggregation engine.

Every function under test is pure - it takes already-loaded sessions and returns a
payload - so these build session dicts in the shape ``observation_sessions`` writes them
and assert on the aggregates, with no filesystem involved.
"""

from datetime import date

import pytest

from observation import session_analytics
from observation.session_analytics import (
    build_conditions,
    build_logged_months,
    build_summary,
    effective_combination,
    entry_integration_minutes,
    entry_is_captured,
    entry_rating,
    iter_entries,
    object_key,
)

TODAY = date(2026, 9, 16)


def make_night(night_id, day, **fields):
    """One night sub-object, with the scalar condition fields defaulted to absent."""
    night = {
        'id': night_id,
        'date': day,
        'start_time': None,
        'end_time': None,
        'sqm': None,
        'seeing': None,
        'transparency': None,
        'moon_illumination_percent': None,
        'notes': '',
    }
    night.update(fields)
    return night


def make_entry(name, **fields):
    """One target entry, with the frozen identity and capture fields defaulted."""
    entry = {
        'id': f'entry-{name}',
        'night_id': None,
        'name': name,
        'catalogue': 'Messier',
        'type': 'Galaxy',
        'constellation': 'And',
        'catalogue_group_id': '',
        'frame_count': None,
        'sub_exposure_seconds': None,
        'integration_minutes': None,
        'rating': None,
        'combination_id': None,
        'combination_name': None,
    }
    entry.update(fields)
    return entry


def make_session(session_id, nights, entries, **fields):
    session = {
        'id': session_id,
        'location_id': 'loc-1',
        'location_name': 'Backyard',
        'combination_id': 'combo-1',
        'combination_name': 'Newton 200 + ASI294',
        'notes': '',
        'nights': nights,
        'entries': entries,
        'attachments': [],
    }
    session.update(fields)
    return session


@pytest.fixture
def one_session():
    """A single-night session with two captured targets."""
    night = make_night('night-1', '2026-09-10', seeing=2, transparency=7, sqm=21.0, moon_illumination_percent=5.0)
    return [
        make_session(
            'session-1',
            [night],
            [
                make_entry('M 31', night_id='night-1', integration_minutes=120.0, frame_count=40, rating=4.5),
                make_entry('M 33', night_id='night-1', integration_minutes=60.0, frame_count=20, rating=3.0,
                           type='Galaxy', constellation='Tri'),
            ],
        )
    ]


class TestEntryHelpers:
    """The per-entry primitives every aggregate is built from."""

    def test_integration_prefers_the_recorded_total(self):
        entry = make_entry('M 31', integration_minutes=90.0, frame_count=10, sub_exposure_seconds=300)
        assert entry_integration_minutes(entry) == pytest.approx(90.0)

    def test_integration_falls_back_to_frames_times_sub_exposure(self):
        """Older entries recorded frames and sub length without the computed total."""
        entry = make_entry('M 31', integration_minutes=None, frame_count=12, sub_exposure_seconds=300)
        assert entry_integration_minutes(entry) == pytest.approx(60.0)

    def test_integration_is_zero_when_nothing_was_recorded(self):
        assert entry_integration_minutes(make_entry('M 31')) == 0.0

    def test_captured_requires_real_evidence(self):
        assert entry_is_captured(make_entry('M 31', frame_count=5)) is True
        assert entry_is_captured(make_entry('M 31', integration_minutes=30.0)) is True
        assert entry_is_captured(make_entry('M 31')) is False
        assert entry_is_captured(make_entry('M 31', frame_count=0, integration_minutes=0)) is False

    def test_rating_zero_is_a_rating_not_an_absence(self):
        assert entry_rating(make_entry('M 31', rating=0)) == 0.0
        assert entry_rating(make_entry('M 31')) is None

    def test_out_of_range_rating_is_discarded(self):
        assert entry_rating(make_entry('M 31', rating=9)) is None
        assert entry_rating(make_entry('M 31', rating=-1)) is None

    def test_object_key_prefers_the_cross_catalogue_group(self):
        """M 31 and NGC 224 are one object, so they must collapse to one key."""
        messier = make_entry('M 31', catalogue_group_id='dso-openngc-ngc0224')
        ngc = make_entry('NGC 224', catalogue='OpenNGC', catalogue_group_id='dso-openngc-ngc0224')
        assert object_key(messier) == object_key(ngc)

    def test_object_key_falls_back_to_the_normalized_name(self):
        assert object_key(make_entry('M 31')) == object_key(make_entry('m31'))


class TestNightResolution:
    """Which night an entry is attributed to - the basis of every date bucket."""

    def test_entry_resolves_to_its_own_night(self):
        nights = [make_night('night-1', '2026-09-10'), make_night('night-2', '2026-09-11')]
        sessions = [make_session('s1', nights, [make_entry('M 31', night_id='night-2')])]
        _session, night, _entry = next(iter_entries(sessions))
        assert night['date'] == '2026-09-11'

    def test_null_night_id_falls_back_to_the_earliest_night(self):
        """Entries added through the API without a night still have to land somewhere."""
        nights = [make_night('night-2', '2026-09-11'), make_night('night-1', '2026-09-10')]
        sessions = [make_session('s1', nights, [make_entry('M 31', night_id=None)])]
        _session, night, _entry = next(iter_entries(sessions))
        assert night['date'] == '2026-09-10'

    def test_dangling_night_id_falls_back_rather_than_vanishing(self):
        nights = [make_night('night-1', '2026-09-10')]
        sessions = [make_session('s1', nights, [make_entry('M 31', night_id='deleted-night')])]
        _session, night, _entry = next(iter_entries(sessions))
        assert night['date'] == '2026-09-10'

    def test_session_with_no_nights_yields_an_empty_night(self):
        sessions = [make_session('s1', [], [make_entry('M 31')])]
        _session, night, _entry = next(iter_entries(sessions))
        assert night == {}


class TestEffectiveCombination:
    """Equipment attribution, read from the frozen snapshots on the records."""

    def test_entry_inherits_the_session_combination(self):
        session = make_session('s1', [make_night('n1', '2026-09-10')], [])
        assert effective_combination(session, make_entry('M 31')) == ('combo-1', 'Newton 200 + ASI294')

    def test_entry_override_wins(self):
        """Someone switched telescopes mid-session."""
        session = make_session('s1', [make_night('n1', '2026-09-10')], [])
        entry = make_entry('M 31', combination_id='combo-2', combination_name='RC8 + ASI2600')
        assert effective_combination(session, entry) == ('combo-2', 'RC8 + ASI2600')

    def test_no_equipment_anywhere_is_an_empty_pair(self):
        session = make_session('s1', [make_night('n1', '2026-09-10')], [], combination_id=None, combination_name=None)
        assert effective_combination(session, make_entry('M 31')) == ('', '')


class TestBuildSummaryEmpty:
    """An account that has logged nothing must render, not explode."""

    def test_empty_log(self):
        summary = build_summary([], TODAY)
        totals = summary['totals']
        assert totals['integration_minutes_lifetime'] == 0.0
        assert totals['sessions'] == 0
        assert totals['objects_captured'] == 0
        assert totals['average_rating'] is None
        assert summary['monthly'] == []
        assert summary['object_types'] == []
        assert summary['equipment'] == []

    def test_session_with_no_entries(self):
        sessions = [make_session('s1', [make_night('n1', '2026-09-10')], [])]
        summary = build_summary(sessions, TODAY)
        assert summary['totals']['sessions'] == 1
        assert summary['totals']['nights'] == 1
        assert summary['totals']['entries'] == 0


class TestBuildSummaryTotals:

    def test_lifetime_year_and_month_buckets(self, one_session):
        summary = build_summary(one_session, TODAY)
        totals = summary['totals']
        assert totals['integration_minutes_lifetime'] == pytest.approx(180.0)
        assert totals['integration_minutes_year'] == pytest.approx(180.0)
        assert totals['integration_minutes_month'] == pytest.approx(180.0)

    def test_a_previous_year_is_excluded_from_the_year_bucket(self):
        sessions = [
            make_session('s1', [make_night('n1', '2025-08-02')], [make_entry('M 31', integration_minutes=100.0)]),
            make_session('s2', [make_night('n2', '2026-09-02')], [make_entry('M 33', integration_minutes=50.0)]),
        ]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['integration_minutes_lifetime'] == pytest.approx(150.0)
        assert totals['integration_minutes_year'] == pytest.approx(50.0)
        assert totals['integration_minutes_month'] == pytest.approx(50.0)

    def test_explicit_year_argument_reselects_the_year_bucket(self):
        sessions = [
            make_session('s1', [make_night('n1', '2025-08-02')], [make_entry('M 31', integration_minutes=100.0)]),
            make_session('s2', [make_night('n2', '2026-09-02')], [make_entry('M 33', integration_minutes=50.0)]),
        ]
        totals = build_summary(sessions, TODAY, year=2025)['totals']
        assert totals['integration_minutes_year'] == pytest.approx(100.0)

    def test_month_bucket_uses_the_night_date_not_the_record_creation(self):
        """A session logged weeks late belongs to the month it happened."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-07-04')],
                [make_entry('M 31', integration_minutes=90.0, created_at='2026-09-16T10:00:00+00:00')],
            )
        ]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['integration_minutes_month'] == 0.0
        assert totals['integration_minutes_year'] == pytest.approx(90.0)

    def test_objects_captured_counts_distinct_objects_not_entries(self):
        """Re-shooting the same target across two nights is still one object."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10'), make_night('n2', '2026-09-11')],
                [
                    make_entry('M 31', night_id='n1', integration_minutes=60.0,
                               catalogue_group_id='dso-openngc-ngc0224'),
                    make_entry('NGC 224', night_id='n2', integration_minutes=60.0, catalogue='OpenNGC',
                               catalogue_group_id='dso-openngc-ngc0224'),
                ],
            )
        ]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['entries'] == 2
        assert totals['objects_captured'] == 1

    def test_uncaptured_entries_do_not_count_as_objects(self):
        """A planned-but-clouded-out target is logged without capture evidence."""
        sessions = [make_session('s1', [make_night('n1', '2026-09-10')], [make_entry('M 31')])]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['entries'] == 1
        assert totals['captured_entries'] == 0
        assert totals['objects_captured'] == 0

    def test_astrodex_size_is_reported_separately(self):
        """Astrodex is the gallery, never mixed into the logged totals."""
        summary = build_summary([], TODAY, astrodex_item_count=42)
        assert summary['totals']['astrodex_items'] == 42
        assert summary['totals']['objects_captured'] == 0

    def test_first_and_last_night_span_the_whole_log(self, one_session):
        totals = build_summary(one_session, TODAY)['totals']
        assert totals['first_night'] == '2026-09-10'
        assert totals['last_night'] == '2026-09-10'

    def test_average_rating_ignores_unrated_entries(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0, rating=4.0),
                    make_entry('M 33', integration_minutes=60.0, rating=2.0),
                    make_entry('M 51', integration_minutes=60.0),
                ],
            )
        ]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['average_rating'] == pytest.approx(3.0)
        assert totals['rated_entries'] == 2


class TestBuildSummaryMonthlySeries:

    def test_months_without_activity_are_filled_in(self):
        """A gap must render as a zero bar, not close up the axis."""
        sessions = [
            make_session('s1', [make_night('n1', '2026-01-10')], [make_entry('M 31', integration_minutes=60.0)]),
            make_session('s2', [make_night('n2', '2026-04-10')], [make_entry('M 33', integration_minutes=30.0)]),
        ]
        months = build_summary(sessions, TODAY)['monthly']
        assert [row['month'] for row in months] == ['2026-01', '2026-02', '2026-03', '2026-04']
        assert [row['integration_minutes'] for row in months] == [60.0, 0.0, 0.0, 30.0]

    def test_every_month_row_has_the_same_shape(self):
        sessions = [
            make_session('s1', [make_night('n1', '2026-01-10')], [make_entry('M 31', integration_minutes=60.0)]),
            make_session('s2', [make_night('n2', '2026-03-10')], [make_entry('M 33', integration_minutes=30.0)]),
        ]
        months = build_summary(sessions, TODAY)['monthly']
        expected = {'month', 'integration_minutes', 'entries', 'nights', 'average_rating', 'rated_entries'}
        assert all(set(row) == expected for row in months)

    def test_distinct_nights_are_counted_per_month(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10'), make_night('n2', '2026-09-11')],
                [
                    make_entry('M 31', night_id='n1', integration_minutes=60.0),
                    make_entry('M 33', night_id='n1', integration_minutes=60.0),
                    make_entry('M 51', night_id='n2', integration_minutes=60.0),
                ],
            )
        ]
        months = build_summary(sessions, TODAY)['monthly']
        assert months[0]['nights'] == 2
        assert months[0]['entries'] == 3


class TestBuildSummaryBreakdowns:

    def test_object_types_are_ranked_by_integration(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0, type='Galaxy'),
                    make_entry('M 42', integration_minutes=180.0, type='Nebula'),
                ],
            )
        ]
        types = build_summary(sessions, TODAY)['object_types']
        assert [row['type'] for row in types] == ['Nebula', 'Galaxy']

    def test_missing_object_type_becomes_an_explicit_bucket(self):
        sessions = [make_session('s1', [make_night('n1', '2026-09-10')], [make_entry('M 31', type='')])]
        types = build_summary(sessions, TODAY)['object_types']
        assert [row['type'] for row in types] == ['Unknown']

    def test_constellation_abbreviations_are_expanded(self):
        """Entries store whichever form their source handed over."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0, constellation='And'),
                    make_entry('NGC 7000', integration_minutes=30.0, constellation='Cygnus'),
                ],
            )
        ]
        names = {row['constellation'] for row in build_summary(sessions, TODAY)['constellations']}
        assert names == {'Andromeda', 'Cygnus'}

    def test_the_same_constellation_in_both_forms_is_one_row(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0, constellation='And'),
                    make_entry('M 32', integration_minutes=30.0, constellation='Andromeda'),
                ],
            )
        ]
        summary = build_summary(sessions, TODAY)
        assert len(summary['constellations']) == 1
        assert summary['totals']['constellations'] == 1
        assert summary['constellations'][0]['integration_minutes'] == pytest.approx(90.0)

    def test_equipment_hours_follow_the_effective_combination(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0),
                    make_entry('M 42', integration_minutes=120.0, combination_id='combo-2',
                               combination_name='RC8 + ASI2600'),
                ],
            )
        ]
        equipment = build_summary(sessions, TODAY)['equipment']
        by_id = {row['combination_id']: row for row in equipment}
        assert by_id['combo-1']['integration_minutes'] == pytest.approx(60.0)
        assert by_id['combo-2']['integration_minutes'] == pytest.approx(120.0)
        assert by_id['combo-2']['combination_name'] == 'RC8 + ASI2600'

    def test_entries_without_equipment_get_their_own_bucket(self):
        """The hours must still add up to the headline total."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [make_entry('M 31', integration_minutes=60.0)],
                combination_id=None,
                combination_name=None,
            )
        ]
        summary = build_summary(sessions, TODAY)
        assert len(summary['equipment']) == 1
        assert summary['equipment'][0]['combination_id'] is None
        assert summary['equipment'][0]['integration_minutes'] == pytest.approx(60.0)
        assert summary['totals']['integration_minutes_lifetime'] == pytest.approx(60.0)

    def test_equipment_session_count_is_distinct_sessions(self):
        sessions = [
            make_session('s1', [make_night('n1', '2026-09-10')],
                         [make_entry('M 31', integration_minutes=60.0),
                          make_entry('M 33', integration_minutes=60.0)]),
            make_session('s2', [make_night('n2', '2026-09-12')], [make_entry('M 51', integration_minutes=60.0)]),
        ]
        equipment = build_summary(sessions, TODAY)['equipment']
        assert equipment[0]['sessions'] == 2
        assert equipment[0]['entries'] == 3

    def test_top_targets_merge_repeat_visits(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10'), make_night('n2', '2026-09-14')],
                [
                    make_entry('M 31', night_id='n1', integration_minutes=60.0,
                               catalogue_group_id='dso-openngc-ngc0224'),
                    make_entry('M 31', night_id='n2', integration_minutes=90.0,
                               catalogue_group_id='dso-openngc-ngc0224'),
                ],
            )
        ]
        targets = build_summary(sessions, TODAY)['top_targets']
        assert len(targets) == 1
        assert targets[0]['integration_minutes'] == pytest.approx(150.0)
        assert targets[0]['entries'] == 2
        assert targets[0]['last_date'] == '2026-09-14'

    def test_breakdowns_are_capped_with_a_reported_total(self):
        entries = [
            make_entry(f'Target {index}', integration_minutes=float(index), catalogue_group_id=f'group-{index}')
            for index in range(1, session_analytics.TOP_TARGETS_LIMIT + 6)
        ]
        sessions = [make_session('s1', [make_night('n1', '2026-09-10')], entries)]
        summary = build_summary(sessions, TODAY)
        assert len(summary['top_targets']) == session_analytics.TOP_TARGETS_LIMIT
        assert summary['targets_total'] == len(entries)


class TestBuildSummaryRobustness:
    """Everything here comes off disk and may be partial or corrupt."""

    def test_non_dict_members_are_skipped(self):
        sessions = ['not a session', None, make_session('s1', [make_night('n1', '2026-09-10')], ['junk', 42])]
        summary = build_summary(sessions, TODAY)
        assert summary['totals']['entries'] == 0
        assert summary['totals']['sessions'] == 1

    def test_missing_collections_are_tolerated(self):
        sessions = [{'id': 's1'}]
        summary = build_summary(sessions, TODAY)
        assert summary['totals']['entries'] == 0
        assert summary['totals']['nights'] == 0

    def test_unparseable_numbers_are_ignored(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [make_entry('M 31', integration_minutes='not a number', rating='great')],
            )
        ]
        totals = build_summary(sessions, TODAY)['totals']
        assert totals['integration_minutes_lifetime'] == 0.0
        assert totals['average_rating'] is None

    def test_undated_nights_are_left_out_of_the_series(self):
        sessions = [make_session('s1', [make_night('n1', '')], [make_entry('M 31', integration_minutes=60.0)])]
        summary = build_summary(sessions, TODAY)
        assert summary['monthly'] == []
        assert summary['totals']['integration_minutes_lifetime'] == pytest.approx(60.0)


class TestBuildConditions:

    def _rated(self, **night_fields):
        night = make_night('n1', '2026-09-10', **night_fields)
        return [make_session('s1', [night], [make_entry('M 31', integration_minutes=60.0, rating=4.0)])]

    def test_unrated_entries_are_not_samples(self):
        """A correlation needs both halves; an unrated entry has nothing to correlate."""
        sessions = self._rated(seeing=2)
        sessions[0]['entries'][0]['rating'] = None
        assert build_conditions(sessions)['total_rated_entries'] == 0

    def test_entries_with_no_recorded_conditions_are_not_samples(self):
        assert build_conditions(self._rated())['total_rated_entries'] == 0

    def test_a_sample_carries_its_night_conditions(self):
        result = build_conditions(self._rated(seeing=2, transparency=7, sqm=21.2, moon_illumination_percent=4.0))
        sample = result['samples'][0]
        assert sample['rating'] == 4.0
        assert sample['seeing'] == 2
        assert sample['transparency'] == 7
        assert sample['sqm'] == 21.2
        assert sample['moon_illumination_percent'] == 4.0
        assert sample['date'] == '2026-09-10'

    def test_every_metric_declares_its_direction(self):
        """Seeing and transparency run in opposite directions, on purpose."""
        metrics = build_conditions(self._rated(seeing=2))['metrics']
        assert metrics['seeing']['direction'] == 'lower_is_better'
        assert metrics['transparency']['direction'] == 'higher_is_better'
        assert metrics['sqm']['direction'] == 'higher_is_better'
        assert metrics['moon_illumination_percent']['direction'] == 'lower_is_better'

    def test_buckets_are_ordered_best_first_for_every_metric(self):
        metrics = build_conditions(self._rated(seeing=2))['metrics']
        for name, metric in metrics.items():
            qualities = [bucket['quality'] for bucket in metric['buckets']]
            assert qualities == ['best', 'mid', 'worst'], name

    def test_low_seeing_is_the_best_bucket(self):
        """7Timer seeing is 1 = best .. 8 = worst - a reversed axis is a real bug."""
        best = build_conditions(self._rated(seeing=2))['metrics']['seeing']['buckets'][0]
        assert best['samples'] == 1
        assert best['min'] == 1.0 and best['max'] == 3.0

    def test_high_transparency_is_the_best_bucket(self):
        """7Timer transparency is 1 = worst .. 8 = best."""
        best = build_conditions(self._rated(transparency=7))['metrics']['transparency']['buckets'][0]
        assert best['samples'] == 1
        assert best['min'] == 6.0 and best['max'] == 8.0

    def test_dark_sky_is_the_best_sqm_bucket(self):
        best = build_conditions(self._rated(sqm=21.4))['metrics']['sqm']['buckets'][0]
        assert best['samples'] == 1

    def test_new_moon_is_the_best_moon_bucket(self):
        best = build_conditions(self._rated(moon_illumination_percent=3.0))['metrics']
        assert best['moon_illumination_percent']['buckets'][0]['samples'] == 1

    def test_thin_buckets_are_flagged_rather_than_plotted(self):
        result = build_conditions(self._rated(seeing=2))
        best = result['metrics']['seeing']['buckets'][0]
        assert best['samples'] == 1
        assert best['insufficient_data'] is True
        assert result['minimum_samples'] == session_analytics.MINIMUM_BUCKET_SAMPLES

    def test_a_bucket_over_the_threshold_is_not_flagged(self):
        entries = [
            make_entry(f'Target {index}', integration_minutes=30.0, rating=4.0)
            for index in range(session_analytics.MINIMUM_BUCKET_SAMPLES)
        ]
        sessions = [make_session('s1', [make_night('n1', '2026-09-10', seeing=2)], entries)]
        best = build_conditions(sessions)['metrics']['seeing']['buckets'][0]
        assert best['insufficient_data'] is False
        assert best['average_rating'] == pytest.approx(4.0)

    def test_averages_separate_good_from_bad_nights(self):
        sessions = [
            make_session('s1', [make_night('n1', '2026-09-10', seeing=2)],
                         [make_entry('M 31', integration_minutes=60.0, rating=5.0)]),
            make_session('s2', [make_night('n2', '2026-09-11', seeing=7)],
                         [make_entry('M 33', integration_minutes=60.0, rating=1.0)]),
        ]
        buckets = build_conditions(sessions)['metrics']['seeing']['buckets']
        assert buckets[0]['average_rating'] == pytest.approx(5.0)
        assert buckets[2]['average_rating'] == pytest.approx(1.0)
        assert buckets[1]['average_rating'] is None

    def test_measured_samples_counts_nights_that_recorded_the_metric(self):
        sessions = [
            make_session('s1', [make_night('n1', '2026-09-10', seeing=2)],
                         [make_entry('M 31', integration_minutes=60.0, rating=5.0)]),
            make_session('s2', [make_night('n2', '2026-09-11', sqm=21.0)],
                         [make_entry('M 33', integration_minutes=60.0, rating=1.0)]),
        ]
        metrics = build_conditions(sessions)['metrics']
        assert metrics['seeing']['measured_samples'] == 1
        assert metrics['sqm']['measured_samples'] == 1

    def test_empty_log(self):
        result = build_conditions([])
        assert result['samples'] == []
        assert result['total_rated_entries'] == 0
        assert all(metric['measured_samples'] == 0 for metric in result['metrics'].values())


class TestBuildLoggedMonths:

    def test_always_returns_all_twelve_months(self):
        rows = build_logged_months([])
        assert [row['month'] for row in rows] == list(range(1, 13))
        assert all(row['integration_hours'] == 0.0 for row in rows)

    def test_folds_every_year_into_the_same_calendar_month(self):
        """"Which months do I actually get out" is a question about seasons, not years."""
        sessions = [
            make_session('s1', [make_night('n1', '2024-08-10')], [make_entry('M 31', integration_minutes=60.0)]),
            make_session('s2', [make_night('n2', '2026-08-12')], [make_entry('M 33', integration_minutes=120.0)]),
        ]
        august = build_logged_months(sessions)[7]
        assert august['month'] == 8
        assert august['integration_hours'] == pytest.approx(3.0)
        assert august['entries'] == 2
        assert august['nights_logged'] == 2

    def test_the_same_night_is_counted_once(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-08-10')],
                [
                    make_entry('M 31', integration_minutes=60.0),
                    make_entry('M 33', integration_minutes=60.0),
                ],
            )
        ]
        august = build_logged_months(sessions)[7]
        assert august['nights_logged'] == 1
        assert august['entries'] == 2

    def test_average_rating_per_month(self):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-08-10')],
                [
                    make_entry('M 31', integration_minutes=60.0, rating=5.0),
                    make_entry('M 33', integration_minutes=60.0, rating=3.0),
                ],
            )
        ]
        assert build_logged_months(sessions)[7]['average_rating'] == pytest.approx(4.0)

    def test_undated_entries_are_skipped(self):
        sessions = [make_session('s1', [make_night('n1', '')], [make_entry('M 31', integration_minutes=60.0)])]
        assert all(row['integration_hours'] == 0.0 for row in build_logged_months(sessions))


class TestNeverVisibleDeclination:
    """The band of sky the observer's latitude puts permanently out of reach."""

    def test_northern_hemisphere(self):
        """From 48 N nothing below -42 ever clears the horizon."""
        assert session_analytics.never_visible_declination(48.0) == pytest.approx(-42.0)

    def test_southern_hemisphere_mirrors_it(self):
        assert session_analytics.never_visible_declination(-40.0) == pytest.approx(50.0)

    def test_equator_leaves_only_the_poles_out(self):
        assert session_analytics.never_visible_declination(0.0) == pytest.approx(-90.0)

    def test_unknown_latitude_draws_no_band(self):
        assert session_analytics.never_visible_declination(None) is None
        assert session_analytics.never_visible_declination('north') is None
        assert session_analytics.never_visible_declination(120.0) is None


@pytest.fixture
def stub_resolver(monkeypatch):
    """Replace the dataset lookup with a small in-test catalogue.

    Keyed on the bare identifier so a display label and an entry name both resolve to the
    same object, which is exactly what the coverage map has to collapse.
    """
    catalogue = {
        'M 31': ('dso-ngc0224', 10.68, 41.27, 'Galaxy', 'And'),
        'M31': ('dso-ngc0224', 10.68, 41.27, 'Galaxy', 'And'),
        'NGC 224': ('dso-ngc0224', 10.68, 41.27, 'Galaxy', 'And'),
        'M 42': ('dso-ngc1976', 83.82, -5.39, 'Nebula', 'Ori'),
        'M42': ('dso-ngc1976', 83.82, -5.39, 'Nebula', 'Ori'),
    }

    def fake_resolve_target(name, catalogue_name='', ra=None, dec=None):
        for candidate in (str(name or '').strip(), str(name or '').split(' - ')[0].strip()):
            hit = catalogue.get(candidate)
            if hit:
                group_id, ra_deg, dec_deg, object_type, constellation = hit
                return {
                    'group_id': group_id,
                    'target_id': group_id,
                    'preferred_name': candidate,
                    'object_type': object_type,
                    'constellation': constellation,
                    'category': 'deep_sky',
                    'ra_deg': ra_deg,
                    'dec_deg': dec_deg,
                    'resolved': True,
                    'placed': True,
                }
        ra_deg = session_analytics.target_coordinates.parse_ra_to_degrees(ra)
        dec_deg = session_analytics.target_coordinates.parse_dec_to_degrees(dec)
        placed = ra_deg is not None and dec_deg is not None
        return {
            'group_id': '',
            'target_id': '',
            'preferred_name': '',
            'object_type': '',
            'constellation': '',
            'category': '',
            'ra_deg': ra_deg if placed else None,
            'dec_deg': dec_deg if placed else None,
            'resolved': False,
            'placed': placed,
        }

    monkeypatch.setattr(session_analytics.target_coordinates, 'resolve_target', fake_resolve_target)
    return catalogue


class TestBuildSkyCoverage:

    def test_empty_inputs(self, stub_resolver):
        coverage = session_analytics.build_sky_coverage([], [])
        assert coverage['points'] == []
        assert coverage['total_objects'] == 0
        assert coverage['unplaced_count'] == 0

    def test_a_logged_entry_becomes_a_point(self, stub_resolver):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [make_entry('M 31', integration_minutes=120.0, frame_count=40)],
            )
        ]
        point = session_analytics.build_sky_coverage(sessions)['points'][0]
        assert point['ra_deg'] == pytest.approx(10.68)
        assert point['dec_deg'] == pytest.approx(41.27)
        assert point['ra_hours'] == pytest.approx(0.712, abs=1e-3)
        assert point['integration_minutes'] == pytest.approx(120.0)
        assert point['source'] == 'log'
        assert point['first_date'] == '2026-09-10'

    def test_uncaptured_entries_are_not_plotted(self, stub_resolver):
        """A planned target that never got frames is not coverage."""
        sessions = [make_session('s1', [make_night('n1', '2026-09-10')], [make_entry('M 31')])]
        assert session_analytics.build_sky_coverage(sessions)['points'] == []

    def test_the_same_object_across_catalogues_is_one_dot(self, stub_resolver):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10'), make_night('n2', '2026-09-14')],
                [
                    make_entry('M 31', night_id='n1', integration_minutes=60.0),
                    make_entry('NGC 224', night_id='n2', catalogue='OpenNGC', integration_minutes=90.0),
                ],
            )
        ]
        points = session_analytics.build_sky_coverage(sessions)['points']
        assert len(points) == 1
        assert points[0]['integration_minutes'] == pytest.approx(150.0)
        assert points[0]['entries'] == 2
        assert points[0]['first_date'] == '2026-09-10'
        assert points[0]['last_date'] == '2026-09-14'

    def test_astrodex_only_objects_are_included(self, stub_resolver):
        """Objects added straight to the gallery were never a session entry."""
        items = [{'id': 'item-1', 'name': 'M 42', 'type': 'Nebula', 'constellation': 'Ori', 'pictures': []}]
        coverage = session_analytics.build_sky_coverage([], items)
        assert len(coverage['points']) == 1
        assert coverage['points'][0]['source'] == 'astrodex'
        assert coverage['points'][0]['astrodex_item_id'] == 'item-1'

    def test_an_object_in_both_sources_is_marked_as_such(self, stub_resolver):
        """Astrodex stores a display label; the log stores the bare identifier."""
        sessions = [
            make_session('s1', [make_night('n1', '2026-09-10')], [make_entry('M 31', integration_minutes=60.0)])
        ]
        items = [{'id': 'item-1', 'name': 'M31 - Andromeda Galaxy', 'type': 'Galaxy', 'pictures': []}]
        coverage = session_analytics.build_sky_coverage(sessions, items)
        assert len(coverage['points']) == 1
        assert coverage['points'][0]['source'] == 'both'
        assert coverage['points'][0]['astrodex_item_id'] == 'item-1'

    def test_astrodex_dates_come_from_its_pictures(self, stub_resolver):
        items = [
            {
                'id': 'item-1',
                'name': 'M 42',
                'created_at': '2026-01-01T00:00:00+00:00',
                'pictures': [{'date': '2025-02-03'}, {'date': '2025-11-20'}],
            }
        ]
        point = session_analytics.build_sky_coverage([], items)['points'][0]
        assert point['first_date'] == '2025-02-03'
        assert point['last_date'] == '2025-11-20'

    def test_astrodex_item_without_pictures_falls_back_to_its_creation_day(self, stub_resolver):
        items = [{'id': 'item-1', 'name': 'M 42', 'created_at': '2026-01-05T22:14:00+00:00', 'pictures': []}]
        point = session_analytics.build_sky_coverage([], items)['points'][0]
        assert point['first_date'] == '2026-01-05'

    def test_unplaceable_objects_are_counted_not_dropped(self, stub_resolver):
        """The UI reports how many objects could not be placed instead of losing them."""
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [
                    make_entry('M 31', integration_minutes=60.0),
                    make_entry('My Backyard Panorama', catalogue='', integration_minutes=30.0, ra=None, dec=None),
                ],
            )
        ]
        coverage = session_analytics.build_sky_coverage(sessions)
        assert len(coverage['points']) == 1
        assert coverage['unplaced_count'] == 1
        assert coverage['total_objects'] == 2
        assert 'My Backyard Panorama' in coverage['unplaced_names']

    def test_an_object_outside_the_dataset_places_from_its_own_snapshot(self, stub_resolver):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [make_entry('Some Star', catalogue='SIMBAD', integration_minutes=30.0, ra=6.0, dec=20.0)],
            )
        ]
        coverage = session_analytics.build_sky_coverage(sessions)
        assert coverage['unplaced_count'] == 0
        assert coverage['points'][0]['ra_deg'] == pytest.approx(90.0)
        assert coverage['points'][0]['resolved'] is False

    def test_latitude_drives_the_never_visible_band(self, stub_resolver):
        coverage = session_analytics.build_sky_coverage([], [], latitude=48.0)
        assert coverage['never_visible_dec_below'] == pytest.approx(-42.0)
        assert coverage['latitude'] == pytest.approx(48.0)

    def test_missing_type_becomes_an_explicit_bucket(self, stub_resolver):
        sessions = [
            make_session(
                's1',
                [make_night('n1', '2026-09-10')],
                [make_entry('Some Star', catalogue='SIMBAD', type='', integration_minutes=30.0, ra=6.0, dec=20.0)],
            )
        ]
        assert session_analytics.build_sky_coverage(sessions)['points'][0]['type'] == 'Unknown'

    def test_unnamed_records_are_skipped(self, stub_resolver):
        sessions = [
            make_session('s1', [make_night('n1', '2026-09-10')], [make_entry('', integration_minutes=60.0)])
        ]
        coverage = session_analytics.build_sky_coverage(sessions, [{'id': 'x', 'name': ''}])
        assert coverage['points'] == []
        assert coverage['unplaced_count'] == 0
