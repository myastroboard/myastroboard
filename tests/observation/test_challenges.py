"""Tests for the v1.9 challenges: seasons, the Messier marathon and "missing tonight".

The catalogue members and the visibility samples are stubbed for the seasonal lists, so the
ranking rules are tested without the dataset. The marathon runs the real Sun ephemeris on a
few made-up objects, since its whole point is what is reachable from a given latitude.
"""

import datetime

import pytest

from observation import challenges
from observation.challenges import current_season, marathon_nights, marathon_year

PARIS = {'id': 'loc-paris', 'latitude': 48.85, 'longitude': 2.35, 'timezone': 'Europe/Paris', 'horizon_profile': []}


@pytest.fixture(autouse=True)
def fresh_caches():
    challenges.clear_caches()
    yield
    challenges.clear_caches()


def member(target_id, identifier, object_class, magnitude, ra_deg=10.0, dec_deg=40.0, object_type='Galaxy'):
    return {
        'target_id': target_id,
        'identifier': identifier,
        'preferred_name': identifier,
        'object_type': object_type,
        'object_class': object_class,
        'constellation': 'Andromeda',
        'magnitude': magnitude,
        'ra_deg': ra_deg,
        'dec_deg': dec_deg,
    }


class TestSeasons:
    def test_northern_autumn(self):
        season = current_season(datetime.date(2026, 11, 17), 48.0)
        assert season['name'] == 'autumn'
        assert season['nights'] == [
            datetime.date(2026, 9, 15),
            datetime.date(2026, 10, 15),
            datetime.date(2026, 11, 15),
        ]

    def test_the_same_months_are_spring_in_the_south(self):
        assert current_season(datetime.date(2026, 11, 17), -33.0)['name'] == 'spring'

    def test_january_belongs_to_the_winter_that_started_in_december(self):
        season = current_season(datetime.date(2027, 1, 20), 48.0)
        assert season['name'] == 'winter'
        assert season['nights'] == [datetime.date(2026, 12, 15), datetime.date(2027, 1, 15), datetime.date(2027, 2, 15)]


class TestSeasonalChallenges:
    @pytest.fixture
    def stub_visibility(self, monkeypatch):
        """Hours per target id, the same on every sampled night."""
        hours = {'g1': 6.0, 'g2': 5.0, 'g3': 4.0, 'g4': 0.5, 'n1': 7.0}
        candidates = [
            member('g1', 'M 1', 'galaxy', 9.0),
            member('g2', 'M 2', 'galaxy', 6.0),
            member('g3', 'M 3', 'galaxy', None),
            member('g4', 'M 4', 'galaxy', 3.0),
            member('n1', 'M 5', 'nebula', 5.0, object_type='Emission Nebula'),
        ]
        by_position = {}

        def fake_members(catalogue):
            return candidates if catalogue == 'Messier' else []

        def fake_context(location, night):
            return {'date': night}

        def fake_sample(context, ra_deg, dec_deg, alt_min, alt_max, horizon):
            target_id = by_position[(ra_deg, dec_deg)]
            return {'observable_hours': hours[target_id], 'date': context['date'].isoformat()}

        for index, candidate in enumerate(candidates):
            candidate['ra_deg'] = float(index)
            by_position[(candidate['ra_deg'], candidate['dec_deg'])] = candidate['target_id']

        monkeypatch.setattr(challenges.achievements, 'catalogue_members', fake_members)
        monkeypatch.setattr(challenges.visibility_calendar, 'night_context_for', fake_context)
        monkeypatch.setattr(challenges.visibility_calendar, 'sample_target_in_context', fake_sample)
        monkeypatch.setattr(challenges.visibility_calendar, 'observing_constraints', lambda: (30.0, 90.0))

    def test_brightest_observable_targets_with_captured_flags(self, stub_visibility):
        result = challenges.seasonal_challenges(PARIS, datetime.date(2026, 11, 17), {'g2'})
        assert result['season'] == 'autumn'
        galaxies = next(item for item in result['challenges'] if item['object_class'] == 'galaxy')
        # Too short a window (g4) is dropped; brightest first; no magnitude sorts last.
        assert [target['target_id'] for target in galaxies['targets']] == ['g2', 'g1', 'g3']
        assert galaxies['captured'] == 1
        assert galaxies['total'] == 3

    def test_a_class_with_too_few_targets_is_not_offered(self, stub_visibility):
        result = challenges.seasonal_challenges(PARIS, datetime.date(2026, 11, 17), set())
        assert 'nebula' not in [item['object_class'] for item in result['challenges']]


class TestMarathon:
    def test_marathon_year_rolls_over_after_mid_april(self):
        assert marathon_year(datetime.date(2026, 3, 1)) == 2026
        assert marathon_year(datetime.date(2026, 4, 15)) == 2026
        assert marathon_year(datetime.date(2026, 4, 16)) == 2027

    def test_marathon_nights_are_the_new_moons_of_the_window(self):
        nights = marathon_nights(2027, 'Europe/Paris')
        assert nights
        for night, illumination in nights:
            assert datetime.date(2027, 3, 1) <= night <= datetime.date(2027, 4, 15)
            assert illumination < 5.0

    def test_reachable_count_order_and_latitude_limit(self, monkeypatch):
        """From Paris a far-southern object never clears the floor; the rest are ordered."""
        members = [
            # Sets in the west soon after dusk in March (RA ~ 2 h).
            member('west', 'M 1', 'galaxy', 8.0, ra_deg=30.0, dec_deg=15.0),
            # Best in the morning, before dawn (RA ~ 17.5 h).
            member('east', 'M 3', 'cluster', 7.0, ra_deg=262.5, dec_deg=5.0, object_type='Globular Cluster'),
            # Around the meridian near midnight (RA ~ 11 h).
            member('middle', 'M 2', 'galaxy', 9.0, ra_deg=168.0, dec_deg=20.0),
            # Never rises 10 degrees above the Paris horizon.
            member('south', 'M 4', 'cluster', 6.0, ra_deg=265.0, dec_deg=-60.0),
        ]
        monkeypatch.setattr(challenges.achievements, 'catalogue_members', lambda catalogue: members)
        plan = challenges.messier_marathon(PARIS, datetime.date(2026, 11, 17), {'middle'})
        assert plan['year'] == 2027
        assert plan['total'] == 4
        assert plan['reachable'] == 3
        assert [row['target_id'] for row in plan['unreachable']] == ['south']
        assert [row['target_id'] for row in plan['sequence']] == ['west', 'middle', 'east']
        assert plan['captured'] == 1
        assert plan['in_season'] is False
        assert plan['days_until'] > 0
        assert plan['dark_start'] and plan['dark_end']


class TestMissingTonight:
    def test_only_uncaptured_observable_objects_longest_first(self, monkeypatch):
        members = [
            member('a', 'M 1', 'galaxy', 8.0),
            member('b', 'M 2', 'galaxy', 7.0),
            member('c', 'M 3', 'galaxy', 6.0),
            member('d', 'M 4', 'galaxy', 6.0, ra_deg=None),
        ]
        hours = {'b': 2.0, 'c': 5.0}
        monkeypatch.setattr(challenges.achievements, 'catalogue_members', lambda catalogue: members)

        def fake_batch(targets, location, reference_date=None, months_ahead=3):
            assert months_ahead == 1
            return [{'observable_hours_next': hours.get(target['target_id'], 0.0)} for target in targets]

        monkeypatch.setattr(challenges.visibility_calendar, 'next_visibility_batch', fake_batch)
        rows = challenges.missing_tonight('Messier', PARIS, datetime.date(2026, 11, 17), {'a'})
        assert [row['target_id'] for row in rows] == ['c', 'b']

    def test_objects_not_up_tonight_are_left_out(self, monkeypatch):
        """No observable hours (zero, or no figure at all) means not on tonight's list."""
        members = [
            member('a', 'M 1', 'galaxy', 8.0),
            member('b', 'M 2', 'galaxy', 7.0),
            member('c', 'M 3', 'galaxy', 6.0),
        ]
        rows = [{'observable_hours_next': 0.0}, {}, {'observable_hours_next': 1.5}]
        monkeypatch.setattr(challenges.achievements, 'catalogue_members', lambda catalogue: members)
        monkeypatch.setattr(challenges.visibility_calendar, 'next_visibility_batch', lambda *args, **kwargs: rows)

        result = challenges.missing_tonight('Messier', PARIS, datetime.date(2026, 11, 17), set())

        assert [row['target_id'] for row in result] == ['c']


class TestDefensivePaths:
    def test_bounded_cache_drops_the_oldest(self):
        cache = challenges.LruCache(challenges._MAX_CACHE_ENTRIES)
        for key in range(challenges._MAX_CACHE_ENTRIES + 3):
            challenges._remember(cache, key, key)
        assert len(cache) == challenges._MAX_CACHE_ENTRIES
        assert 0 not in cache

    def test_no_sample_night_means_no_challenge(self, monkeypatch):
        def broken(location, night):
            raise RuntimeError('no ephemeris')

        monkeypatch.setattr(challenges.visibility_calendar, 'night_context_for', broken)
        monkeypatch.setattr(challenges.visibility_calendar, 'observing_constraints', lambda: (30.0, 90.0))
        assert challenges.seasonal_challenges(PARIS, datetime.date(2026, 11, 17), set())['challenges'] == []

    def test_unplaced_and_unclassed_candidates_are_skipped_and_lists_are_cached(self, monkeypatch):
        calls = []
        candidates = [
            member('a', 'M 1', 'galaxy', 8.0, ra_deg=None),
            member('b', 'M 2', 'star', 8.0),
            member('c', 'M 3', 'galaxy', 8.0),
        ]
        monkeypatch.setattr(challenges.achievements, 'catalogue_members', lambda catalogue: candidates)
        monkeypatch.setattr(
            challenges.visibility_calendar, 'night_context_for', lambda location, night: {'date': night}
        )
        monkeypatch.setattr(challenges.visibility_calendar, 'observing_constraints', lambda: (30.0, 90.0))

        def sample(context, ra_deg, dec_deg, *_args):
            calls.append(ra_deg)
            return {'observable_hours': 5.0, 'date': context['date'].isoformat()}

        monkeypatch.setattr(challenges.visibility_calendar, 'sample_target_in_context', sample)
        today = datetime.date(2026, 11, 17)
        challenges.seasonal_challenges(PARIS, today, set())
        first = len(calls)
        challenges.seasonal_challenges(PARIS, today, set())
        # Only the placed galaxy is sampled, on the three nights of the season...
        assert first == 3
        # ...and the second call is served from the cache.
        assert len(calls) == first

    def test_unknown_latitude_counts_as_northern(self):
        assert challenges._latitude({'latitude': 'abc'}) is None
        assert challenges.current_season(datetime.date(2026, 7, 1), None)['name'] == 'summer'

    def test_without_a_dark_new_moon_the_darkest_night_is_kept(self, monkeypatch):
        monkeypatch.setattr(challenges, 'phase_at', lambda instant: {'illumination_percent': 40.0 + instant.day / 100})
        nights = challenges.marathon_nights(2027, 'Europe/Paris')
        assert nights == [(datetime.date(2027, 3, 1), pytest.approx(40.01))]

    def test_marathon_plan_is_cached(self, monkeypatch):
        computed = []

        def fake_compute(location, year):
            computed.append(year)
            return {'date': f'{year}-03-08', 'sequence': [], 'unreachable': []}

        monkeypatch.setattr(challenges, '_compute_marathon', fake_compute)
        challenges.messier_marathon(PARIS, datetime.date(2026, 11, 17), set())
        challenges.messier_marathon(PARIS, datetime.date(2026, 11, 18), set())
        assert computed == [2027]

    def test_missing_tonight_with_nothing_left(self, monkeypatch):
        monkeypatch.setattr(
            challenges.achievements, 'catalogue_members', lambda catalogue: [member('a', 'M 1', 'galaxy', 8.0)]
        )
        assert challenges.missing_tonight('Messier', PARIS, datetime.date(2026, 11, 17), {'a'}) == []
