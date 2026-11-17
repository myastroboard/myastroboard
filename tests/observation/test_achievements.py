"""Tests for the v1.9 achievements engine (badges computed on read).

The engine is pure once the dataset lookup is injected, so these build sessions and
Astrodex items in the shape their stores write them, resolve names through a small fake
dataset, and assert on the facts and the badges.
"""

import pytest

from observation import achievement_definitions, achievements
from observation.achievements import (
    classify_object,
    collect_progress,
    evaluate_badges,
    next_within_reach,
    season_index,
    summarize,
)

# A tiny stand-in for the SkyTonight dataset lookup: name -> lookup entry.
FAKE_DATASET = {
    'M 31': {
        'group_id': 'dso-m31',
        'preferred_name': 'Andromeda Galaxy',
        'object_type': 'Galaxy',
        'category': 'deep_sky',
        'constellation': 'And',
        'dec_deg': 41.3,
        'aliases': {'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
    },
    'M 42': {
        'group_id': 'dso-m42',
        'preferred_name': 'Orion Nebula',
        'object_type': 'Emission Nebula',
        'category': 'deep_sky',
        'constellation': 'Ori',
        'dec_deg': -5.4,
        'aliases': {'Messier': 'M 42', 'OpenNGC': 'NGC 1976'},
    },
    'M 45': {
        'group_id': 'dso-m45',
        'preferred_name': 'Pleiades',
        'object_type': 'Open Cluster',
        'category': 'deep_sky',
        'constellation': 'Tau',
        'dec_deg': 24.1,
        'aliases': {'Messier': 'M 45'},
    },
    'Mars': {
        'group_id': 'body-mars',
        'preferred_name': 'Mars',
        'object_type': 'Planet',
        'category': 'bodies',
        'constellation': '',
        'aliases': {},
    },
}
FAKE_DATASET['NGC 224'] = FAKE_DATASET['M 31']
FAKE_DATASET['M31 - Andromeda Galaxy'] = FAKE_DATASET['M 31']


def fake_resolve(name, _catalogue):
    return FAKE_DATASET.get(name, {})


def make_night(night_id, day, **fields):
    night = {'id': night_id, 'date': day, 'sqm': None, 'moon_illumination_percent': None}
    night.update(fields)
    return night


def make_entry(name, night_id, **fields):
    entry = {
        'id': f'entry-{name}-{night_id}',
        'night_id': night_id,
        'name': name,
        'catalogue': 'Messier',
        'type': '',
        'constellation': '',
        'frame_count': None,
        'sub_exposure_seconds': None,
        'integration_minutes': None,
        'rating': None,
        'astrodex_item_id': None,
        'astrodex_picture_id': None,
    }
    entry.update(fields)
    return entry


def make_session(session_id, nights, entries, **fields):
    session = {'id': session_id, 'location_id': 'loc-1', 'nights': nights, 'entries': entries}
    session.update(fields)
    return session


def facts_for(sessions, items=(), bortle=None):
    return collect_progress(sessions, items, location_bortle=bortle, resolve=fake_resolve)


def badge(badges, badge_id):
    return next(item for item in badges if item['id'] == badge_id)


TOTALS = {'Messier': 3, 'Caldwell': 109}


class TestClassification:
    """Free-form object types fold into the classes a badge can name."""

    @pytest.mark.parametrize(
        ('object_type', 'category', 'expected'),
        [
            ('Galaxy', 'deep_sky', 'galaxy'),
            ('Galaxy Cluster', 'deep_sky', 'galaxy'),
            ('Planetary Nebula', 'deep_sky', 'nebula'),
            ('HII Ionized region', 'deep_sky', 'nebula'),
            ('Star cluster + Nebula', 'deep_sky', 'nebula'),
            ('Open Cluster', 'deep_sky', 'cluster'),
            ('Globular Cluster', 'deep_sky', 'cluster'),
            ('Planet', 'bodies', 'planet'),
            ('Comet', 'comets', 'comet'),
            ('Double star', 'deep_sky', 'star'),
            ('Object of other/unknown type', 'deep_sky', 'other'),
        ],
    )
    def test_object_types(self, object_type, category, expected):
        assert classify_object(object_type, category) == expected

    def test_moon_and_sun_are_recognized_by_name(self):
        assert classify_object('', '', 'Moon') == 'moon'
        assert classify_object('', '', 'Sun') == 'sun'

    def test_seasons_are_meteorological_and_hemisphere_neutral(self):
        assert season_index('2026-12-05') == 0
        assert season_index('2026-01-20') == 0
        assert season_index('2026-04-01') == 1
        assert season_index('2026-07-01') == 2
        assert season_index('2026-10-01') == 3
        assert season_index('') is None


class TestCollectProgress:
    """The facts every badge is built from."""

    def test_two_names_of_one_object_are_one_capture(self):
        """M 31 logged and NGC 224 in Astrodex resolve to the same dataset group."""
        night = make_night('n1', '2026-01-10')
        sessions = [make_session('s1', [night], [make_entry('M 31', 'n1', frame_count=10)])]
        items = [{'id': 'a1', 'name': 'NGC 224', 'pictures': [], 'created_at': '2025-06-01T00:00:00+00:00'}]
        facts = facts_for(sessions, items)
        assert list(facts['captures']) == ['dso-m31']
        # The earliest evidence wins: the Astrodex item predates the logged night.
        assert facts['captures']['dso-m31']['first_date'] == '2025-06-01'
        assert facts['captures']['dso-m31']['astrodex_item_id'] == 'a1'

    def test_placeholder_entries_are_not_captures(self):
        night = make_night('n1', '2026-01-10')
        sessions = [make_session('s1', [night], [make_entry('M 31', 'n1')])]
        assert facts_for(sessions)['captures'] == {}

    def test_unknown_object_falls_back_to_its_own_record(self):
        night = make_night('n1', '2026-01-10')
        entry = make_entry(
            'Sh2-155', 'n1', catalogue='Sharpless', type='Emission Nebula', constellation='Cep', frame_count=3
        )
        facts = facts_for([make_session('s1', [night], [entry])])
        capture = next(iter(facts['captures'].values()))
        assert capture['object_class'] == 'nebula'
        assert capture['constellation'] == 'Cepheus'
        assert capture['catalogues'] == {'Sharpless': 'Sh2-155'}

    def test_linked_astrodex_picture_is_not_counted_twice(self):
        """A picture attached to a log entry carries the same integration as the entry."""
        night = make_night('n1', '2026-01-10')
        entry = make_entry('M 31', 'n1', integration_minutes=120.0, astrodex_item_id='a1', astrodex_picture_id='p1')
        items = [
            {
                'id': 'a1',
                'name': 'M 31',
                'pictures': [
                    {'id': 'p1', 'date': '2026-01-10', 'integration_minutes': 120},
                    {'id': 'p2', 'date': '2026-02-10', 'integration_minutes': 30},
                ],
            }
        ]
        facts = facts_for([make_session('s1', [night], [entry])], items)
        assert sorted(minutes for _day, minutes, _key in facts['integration']) == [30, 120.0]

    def test_gallery_only_user_still_has_hours(self):
        items = [
            {'id': 'a1', 'name': 'M 42', 'pictures': [{'id': 'p1', 'date': '2026-03-01', 'integration_minutes': 90}]}
        ]
        facts = facts_for([], items)
        assert facts['integration'] == [('2026-03-01', 90.0, 'dso-m42')]
        assert facts['activity_dates'] == ['2026-03-01']

    def test_nights_carry_conditions_and_location_bortle(self):
        night = make_night('n1', '2026-01-10', sqm=20.1, moon_illumination_percent=2)
        sessions = [make_session('s1', [night], [make_entry('M 31', 'n1', frame_count=1)])]
        facts = facts_for(sessions, bortle={'loc-1': 2})
        assert facts['nights'] == [{'date': '2026-01-10', 'sqm': 20.1, 'moon_illumination_percent': 2.0, 'bortle': 2.0}]


class TestBadges:
    """Each rule, with the date it was earned read off the history."""

    def test_empty_account_has_no_earned_badge(self):
        badges = evaluate_badges(facts_for([]), TOTALS)
        assert badges
        assert not [item for item in badges if item['earned']]

    def test_first_galaxy_is_dated_by_its_first_capture(self):
        nights = [make_night('n1', '2026-02-01'), make_night('n2', '2026-01-05')]
        entries = [make_entry('M 31', 'n1', frame_count=1), make_entry('M 31', 'n2', frame_count=1)]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS)
        first = badge(badges, 'first_galaxy')
        assert first['earned'] is True
        assert first['earned_on'] == '2026-01-05'
        assert badge(badges, 'first_comet')['earned'] is False

    def test_first_planet(self):
        night = make_night('n1', '2026-02-01')
        badges = evaluate_badges(
            facts_for([make_session('s1', [night], [make_entry('Mars', 'n1', catalogue='', frame_count=5)])]), TOTALS
        )
        assert badge(badges, 'first_planet')['earned'] is True

    def test_catalogue_tier_uses_the_dataset_size(self):
        """The 'whole catalogue' tier needs every object the dataset carries, not 110."""
        nights = [make_night(f'n{i}', f'2026-0{i}-01') for i in (1, 2, 3)]
        entries = [
            make_entry('M 31', 'n1', frame_count=1),
            make_entry('M 42', 'n2', frame_count=1),
            make_entry('M 45', 'n3', frame_count=1),
        ]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS)
        complete = badge(badges, 'catalogue_messier_all')
        assert complete['target'] == 3
        assert complete['earned'] is True
        assert complete['earned_on'] == '2026-03-01'
        assert complete['complete_catalogue'] is True

    def test_catalogue_tiers_larger_than_the_catalogue_are_dropped(self):
        badges = evaluate_badges(facts_for([]), TOTALS)
        ids = {item['id'] for item in badges}
        # Messier holds 3 objects in this fake dataset, so 10 / 25 / 50 cannot exist.
        assert 'catalogue_messier_10' not in ids
        assert 'catalogue_messier_all' in ids
        # A catalogue the dataset does not carry gets no badge at all.
        assert not [item for item in badges if item['catalogue'] == 'Sharpless']

    def test_integration_hours_crossing_date(self):
        nights = [make_night('n1', '2026-01-01'), make_night('n2', '2026-01-02')]
        entries = [
            make_entry('M 31', 'n1', integration_minutes=360.0),
            make_entry('M 42', 'n2', integration_minutes=300.0),
        ]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS)
        hours = badge(badges, 'hours_10')
        assert hours['current'] == 11.0
        assert hours['earned_on'] == '2026-01-02'
        assert badge(badges, 'hours_50')['earned'] is False

    def test_single_target_hours_need_one_object(self):
        nights = [make_night('n1', '2026-01-01'), make_night('n2', '2026-01-02')]
        entries = [
            make_entry('M 31', 'n1', integration_minutes=360.0),
            make_entry('M 42', 'n2', integration_minutes=360.0),
        ]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS)
        assert badge(badges, 'target_hours_10')['earned'] is False
        assert badge(badges, 'target_hours_10')['current'] == 6.0

    def test_multi_night_session(self):
        nights = [make_night('n1', '2026-01-01'), make_night('n2', '2026-01-02')]
        badges = evaluate_badges(
            facts_for([make_session('s1', nights, [make_entry('M 31', 'n1', frame_count=1)])]), TOTALS
        )
        assert badge(badges, 'multi_night_2')['earned_on'] == '2026-01-02'

    def test_four_seasons(self):
        days = ['2026-01-10', '2026-04-10', '2026-07-10', '2026-10-10']
        sessions = [
            make_session(f's{i}', [make_night('n', day)], [make_entry('M 31', 'n', frame_count=1)])
            for i, day in enumerate(days)
        ]
        seasons = badge(evaluate_badges(facts_for(sessions), TOTALS), 'seasons_4')
        assert seasons['earned_on'] == '2026-10-10'

    def test_both_hemispheres(self):
        nights = [make_night('n1', '2026-01-01'), make_night('n2', '2026-02-01')]
        entries = [make_entry('M 31', 'n1', frame_count=1), make_entry('M 42', 'n2', frame_count=1)]
        hemispheres = badge(evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS), 'hemispheres_2')
        assert hemispheres['earned_on'] == '2026-02-01'

    def test_dark_site_from_preset_bortle_or_measured_sqm(self):
        bright = make_night('n1', '2026-01-01', sqm=19.0)
        dark_sqm = make_night('n2', '2026-02-01', sqm=21.4)
        session = make_session('s1', [bright, dark_sqm], [make_entry('M 31', 'n1', frame_count=1)])
        assert badge(evaluate_badges(facts_for([session]), TOTALS), 'dark_site')['earned'] is False

        session['entries'].append(make_entry('M 42', 'n2', frame_count=1))
        assert badge(evaluate_badges(facts_for([session]), TOTALS), 'dark_site')['earned_on'] == '2026-02-01'

        preset = make_session('s2', [make_night('n3', '2025-05-01')], [make_entry('M 45', 'n3', frame_count=1)])
        dark = badge(evaluate_badges(facts_for([preset], bortle={'loc-1': 3}), TOTALS), 'dark_site')
        assert dark['earned_on'] == '2025-05-01'

    def test_new_moon_night(self):
        night = make_night('n1', '2026-01-01', moon_illumination_percent=4)
        session = make_session('s1', [night], [make_entry('M 31', 'n1', frame_count=1)])
        assert badge(evaluate_badges(facts_for([session]), TOTALS), 'new_moon_night')['earned'] is True

    def test_deleting_the_evidence_takes_the_badge_back(self):
        """Badges are computed on read: nothing keeps one once its entries are gone."""
        night = make_night('n1', '2026-01-01')
        session = make_session('s1', [night], [make_entry('M 31', 'n1', frame_count=1)])
        assert badge(evaluate_badges(facts_for([session]), TOTALS), 'first_galaxy')['earned'] is True
        session['entries'] = []
        assert badge(evaluate_badges(facts_for([session]), TOTALS), 'first_galaxy')['earned'] is False

    def test_undated_evidence_earns_without_a_date(self):
        items = [{'id': 'a1', 'name': 'M 31', 'pictures': []}]
        first = badge(evaluate_badges(facts_for([], items), TOTALS), 'first_galaxy')
        assert first['earned'] is True
        assert first['earned_on'] is None

    def test_every_definition_has_a_known_rule_and_unique_id(self):
        ids = [definition['id'] for definition in achievement_definitions.BADGE_DEFINITIONS]
        assert len(ids) == len(set(ids))
        full_totals = {catalogue: 500 for catalogue in achievement_definitions.BADGE_CATALOGUES}
        evaluated = evaluate_badges(facts_for([]), full_totals)
        assert {item['id'] for item in evaluated} == set(ids)


class TestNextWithinReachAndSummary:
    def test_next_within_reach_keeps_the_lowest_open_tier(self):
        nights = [make_night('n1', '2026-01-01')]
        entries = [make_entry('M 31', 'n1', integration_minutes=480.0)]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), {'Messier': 110})
        upcoming = next_within_reach(badges)
        ids = [item['id'] for item in upcoming]
        assert 'hours_10' in ids
        assert 'hours_50' not in ids
        # Families with no progress and the condition badges are not "within reach".
        assert 'first_comet' not in ids
        assert 'dark_site' not in ids
        ratios = [item['current'] / item['target'] for item in upcoming]
        assert ratios == sorted(ratios, reverse=True)

    def test_summary_flags_earned_badges_not_seen_yet(self):
        nights = [make_night('n1', '2026-01-01')]
        entries = [make_entry('M 31', 'n1', frame_count=1), make_entry('M 45', 'n1', frame_count=1)]
        badges = evaluate_badges(facts_for([make_session('s1', nights, entries)]), TOTALS)
        summary = summarize(badges, ['first_galaxy'])
        assert 'first_galaxy' not in summary['new_ids']
        assert 'first_cluster' in summary['new_ids']
        assert summary['earned'] == len([item for item in badges if item['earned']])

    def test_catalogue_progress_skips_catalogues_missing_from_the_dataset(self):
        night = make_night('n1', '2026-01-01')
        facts = facts_for([make_session('s1', [night], [make_entry('M 31', 'n1', frame_count=1)])])
        rows = achievements.catalogue_progress(facts, TOTALS, ('Messier', 'Sharpless'))
        assert rows == [{'catalogue': 'Messier', 'captured': 1, 'total': 3}]


class TestDatasetHelpers:
    """Catalogue sizes and members are read off the built dataset."""

    @pytest.fixture
    def fake_dataset(self, monkeypatch):
        targets = [
            {
                'target_id': 'dso-m31',
                'category': 'deep_sky',
                'object_type': 'Galaxy',
                'preferred_name': 'Andromeda Galaxy',
                'catalogue_names': {'Messier': 'M 31', 'OpenNGC': 'NGC 224'},
                'constellation': 'And',
                'magnitude': 3.4,
                'coordinates': {'ra_hours': 0.712, 'dec_degrees': 41.27},
            },
            {
                'target_id': 'body-mars',
                'category': 'bodies',
                'object_type': 'Planet',
                'preferred_name': 'Mars',
                'catalogue_names': {'Messier': 'not-a-dso'},
            },
        ]
        monkeypatch.setattr(achievements.skytonight_targets, 'load_targets_dataset', lambda: {'targets': targets})
        achievements._catalogue_totals_cache['marker'] = None

    def test_catalogue_totals_count_deep_sky_objects_only(self, fake_dataset):
        assert achievements.catalogue_totals() == {'Messier': 1, 'OpenNGC': 1}

    def test_catalogue_members_carry_coordinates_in_degrees(self, fake_dataset):
        members = achievements.catalogue_members('Messier')
        assert len(members) == 1
        assert members[0]['identifier'] == 'M 31'
        assert members[0]['object_class'] == 'galaxy'
        assert members[0]['ra_deg'] == pytest.approx(0.712 * 15.0)
        assert members[0]['constellation'] == 'Andromeda'


class TestCataloguePictures:
    def test_cover_pictures_of_captured_members_oldest_first(self):
        items = [
            {
                'id': 'a2',
                'name': 'M 42',
                'created_at': '2026-02-01',
                'pictures': [{'id': 'p2', 'filename': 'm42.jpg', 'date': '2026-02-01'}],
            },
            {
                'id': 'a1',
                'name': 'M 31',
                'pictures': [
                    {'id': 'p1', 'filename': 'm31-old.jpg', 'date': '2025-01-01'},
                    {'id': 'p3', 'filename': 'm31-cover.jpg', 'date': '2026-01-01', 'is_main': True},
                ],
            },
            {'id': 'a3', 'name': 'M 45', 'pictures': []},
        ]
        facts = facts_for([], items)
        assert achievements.catalogue_pictures(facts, items, 'Messier') == ['m31-cover.jpg', 'm42.jpg']
        assert achievements.catalogue_pictures(facts, items, 'Messier', limit=1) == ['m31-cover.jpg']


class TestDefensiveInputs:
    """Stored records can be hand-edited or legacy: junk must be skipped, never raise."""

    def test_junk_records_are_skipped(self):
        night = make_night('n1', '2026-01-10')
        entries = [
            make_entry('', 'n1', frame_count=5),
            make_entry('M 31', 'n1', integration_minutes='abc', frame_count=2),
        ]
        sessions = ['not-a-session', make_session('s1', [night], entries)]
        items = ['not-an-item', {'id': 'a9', 'name': '', 'pictures': []}]
        facts = facts_for(sessions, items)
        assert list(facts['captures']) == ['dso-m31']
        assert facts['integration'] == []

    def test_a_failing_dataset_lookup_falls_back_to_the_record(self):
        def broken(_name, _catalogue):
            raise RuntimeError('dataset missing')

        night = make_night('n1', '2026-01-10')
        entry = make_entry('M 31', 'n1', type='Galaxy', frame_count=1)
        facts = collect_progress([make_session('s1', [night], [entry])], resolve=broken)
        assert next(iter(facts['captures'].values()))['object_class'] == 'galaxy'

    def test_malformed_dates_have_no_season(self):
        assert season_index('2026-xx-01') is None
        assert season_index('2026-13-01') is None

    def test_unknown_rule_is_skipped(self):
        odd = [{'id': 'odd', 'family': 'odd', 'group': 'sky', 'rule': 'no-such-rule', 'icon': 'bi-x'}]
        assert evaluate_badges(facts_for([]), TOTALS, odd) == []

    def test_catalogue_members_read_dataclass_targets(self, monkeypatch):
        from types import SimpleNamespace

        target = SimpleNamespace(
            target_id='dso-m42',
            category='deep_sky',
            object_type='Emission Nebula',
            preferred_name='Orion Nebula',
            catalogue_names={'Messier': 'M 42'},
            constellation='Ori',
            magnitude=4.0,
            coordinates=SimpleNamespace(ra_hours=5.59, dec_degrees=-5.39),
        )
        monkeypatch.setattr(achievements.skytonight_targets, 'load_targets_dataset', lambda: {'targets': [target]})
        member = achievements.catalogue_members('Messier')[0]
        assert member['object_class'] == 'nebula'
        assert member['dec_deg'] == pytest.approx(-5.39)
