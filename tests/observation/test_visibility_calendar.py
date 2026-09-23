"""Tests for the target visibility calendar (observation/visibility_calendar.py)."""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from observation import visibility_calendar  # type: ignore[import-not-found]
from skytonight.skytonight_models import SkyTonightTarget, SkyTonightCoordinates  # type: ignore[import-not-found]

_YEAR = 2026
_PARIS = {
    'id': 'loc-paris',
    'name': 'Paris',
    'latitude': 48.8566,
    'longitude': 2.3522,
    'elevation': 35,
    'timezone': 'Europe/Paris',
    'horizon_profile': [],
}


def _target(target_id, ra_hours, dec_degrees, category='deep_sky', object_type='Nebula', name=None):
    return SkyTonightTarget(
        target_id=target_id,
        category=category,
        object_type=object_type,
        preferred_name=name or target_id,
        catalogue_names={'OpenNGC': name or target_id},
        coordinates=SkyTonightCoordinates(ra_hours=ra_hours, dec_degrees=dec_degrees),
    )


@pytest.fixture(autouse=True)
def _default_constraints(monkeypatch):
    """Pin the constraint config so tests do not depend on the on-disk config."""
    monkeypatch.setattr(
        visibility_calendar,
        'load_config',
        lambda: {
            'skytonight': {
                'constraints': {
                    'altitude_constraint_min': 30,
                    'altitude_constraint_max': 90,
                    'airmass_constraint': 0,
                }
            }
        },
    )
    visibility_calendar.clear_cache()
    yield
    visibility_calendar.clear_cache()


def _patch_dataset(monkeypatch, targets):
    monkeypatch.setattr(
        visibility_calendar.skytonight_targets,
        'load_targets_dataset',
        lambda *a, **k: {'loaded': True, 'targets': list(targets), 'metadata': {}},
    )


def test_response_shape_for_supported_target(monkeypatch):
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])
    result = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)

    assert result['supported'] is True
    assert result['year'] == _YEAR
    assert result['location'] == {'id': 'loc-paris', 'name': 'Paris'}
    assert len(result['months']) == 12
    assert len(result['samples']) == 24
    for month in result['months']:
        assert 1 <= month['month'] <= 12
        assert 0.0 <= month['score'] <= 1.0
        assert 0 <= month['bucket'] <= 5
        assert month['dark_hours'] >= month['observable_hours'] >= month['moonless_observable_hours']
    assert set(result['constraints']) == {'altitude_min', 'altitude_max', 'has_horizon_profile'}


def test_circumpolar_target_is_observable_whenever_it_is_dark(monkeypatch):
    # Dec +85 from lat +48.86: minimum altitude ~= 85 - (90 - 48.86) = ~43.7 deg, always up and
    # always inside the [30, 90] window - so it is observable for essentially every dark minute.
    _patch_dataset(monkeypatch, [_target('dso-polar', 12.0, 85.0, name='NGC 0000')])
    result = visibility_calendar.get_visibility_calendar('NGC 0000', _PARIS, _YEAR)

    assert result['supported'] is True
    assert all(sample['max_altitude'] is not None and sample['max_altitude'] > 40.0 for sample in result['samples'])
    for month in result['months']:
        assert abs(month['observable_hours'] - month['dark_hours']) < 0.4
    assert any(month['observable_hours'] > 3.0 for month in result['months'])


def test_never_rises_target_has_no_observable_hours(monkeypatch):
    # Dec -80 from a northern site never clears the horizon.
    _patch_dataset(monkeypatch, [_target('dso-south', 6.0, -80.0, name='NGC 9999')])
    result = visibility_calendar.get_visibility_calendar('NGC 9999', _PARIS, _YEAR)

    assert result['supported'] is True
    assert all(month['observable_hours'] == 0.0 for month in result['months'])
    assert all(month['score'] == 0.0 and month['bucket'] == 0 for month in result['months'])


def test_horizon_profile_reduces_observable_hours(monkeypatch):
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])
    open_sky = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)

    visibility_calendar.clear_cache()
    walled = dict(_PARIS, id='loc-walled', horizon_profile=[{'az': 0, 'alt': 89}, {'az': 359, 'alt': 89}])
    blocked = visibility_calendar.get_visibility_calendar('NGC 224', walled, _YEAR)

    open_total = sum(month['observable_hours'] for month in open_sky['months'])
    blocked_total = sum(month['observable_hours'] for month in blocked['months'])
    assert open_total > 0.0
    assert blocked_total == 0.0


def test_solar_system_body_is_unsupported(monkeypatch):
    _patch_dataset(
        monkeypatch, [_target('body-jupiter', 5.0, 20.0, category='bodies', object_type='Planet', name='Jupiter')]
    )
    result = visibility_calendar.get_visibility_calendar('Jupiter', _PARIS, _YEAR)

    assert result['supported'] is False
    assert result['reason'] == 'moving_target'
    assert result['months'] == [] and result['samples'] == []


def test_comet_is_unsupported(monkeypatch):
    _patch_dataset(
        monkeypatch,
        [_target('comet-13p', 5.0, 20.0, category='comets', object_type='Comet', name='13P/Olbers')],
    )
    result = visibility_calendar.get_visibility_calendar('13P/Olbers', _PARIS, _YEAR)
    assert result['supported'] is False
    assert result['reason'] == 'moving_target'


def test_unknown_target_falls_back_to_simbad_then_not_found(monkeypatch):
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(visibility_calendar.object_info, '_resolve_via_simbad', lambda *_a, **_k: None)
    result = visibility_calendar.get_visibility_calendar('not-a-real-object', _PARIS, _YEAR)
    assert result['supported'] is False
    assert result['reason'] == 'not_found'


def test_future_year_computes_all_months_despite_stale_iers(monkeypatch):
    """A year past the ~1-year IERS horizon must still return all 12 months - the
    calendar mutes the degraded-accuracy error the way the eclipse services do."""
    from datetime import date
    from astropy.utils import iers

    monkeypatch.setattr(iers.conf, 'iers_degraded_accuracy', 'error')
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])
    future_year = date.today().year + 2
    result = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, future_year)
    assert result['supported'] is True
    assert len(result['months']) == 12
    assert len(result['samples']) == 24


def test_current_year_does_not_mute_iers_process_wide(monkeypatch):
    """The IERS degraded-accuracy mute is process-wide, so it must not be entered for
    the common current/previous-year request - only for years past the IERS horizon."""
    from datetime import date
    from astropy.utils import iers

    entered = {'muted': False}
    real_ctx = visibility_calendar.distant_epoch_precision_warnings_muted

    def _tracking_ctx():
        entered['muted'] = True
        return real_ctx()

    monkeypatch.setattr(visibility_calendar, 'distant_epoch_precision_warnings_muted', _tracking_ctx)
    monkeypatch.setattr(iers.conf, 'iers_degraded_accuracy', 'ignore')
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])

    visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, date.today().year)
    assert entered['muted'] is False


def test_simbad_fallback_resolves_astrodex_only_target(monkeypatch):
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(
        visibility_calendar.object_info,
        '_resolve_via_simbad',
        lambda *_a, **_k: {'id': 'LBN 552', 'name': 'LBN 552', 'type': 'Nebula', 'ra': 10.68, 'dec': 41.27},
    )
    result = visibility_calendar.get_visibility_calendar('LBN 552', _PARIS, _YEAR)
    assert result['supported'] is True
    assert len(result['months']) == 12


def test_blank_identifier_is_not_found(monkeypatch):
    _patch_dataset(monkeypatch, [])
    result = visibility_calendar.get_visibility_calendar('   ', _PARIS, _YEAR)
    assert result['supported'] is False
    assert result['reason'] == 'not_found'


def test_resolve_by_exact_target_id(monkeypatch):
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])
    result = visibility_calendar.get_visibility_calendar('dso-m31', _PARIS, _YEAR)
    assert result['supported'] is True
    assert result['target']['id'] == 'dso-m31'


def test_resolve_scans_past_non_matching_target_without_preferred_name(monkeypatch):
    no_name = SkyTonightTarget(
        target_id='dso-noname',
        category='deep_sky',
        object_type='Nebula',
        preferred_name='',
        catalogue_names={'OpenNGC': 'NGC 7000'},
        coordinates=SkyTonightCoordinates(ra_hours=20.98, dec_degrees=44.5),
    )
    _patch_dataset(monkeypatch, [_target('dso-other', 5.0, 10.0, name='NGC 111'), no_name])
    result = visibility_calendar.get_visibility_calendar('NGC 7000', _PARIS, _YEAR)
    assert result['supported'] is True
    assert result['target']['id'] == 'dso-noname'


def test_dataset_target_without_coordinates_is_not_found(monkeypatch):
    no_coords = SkyTonightTarget(
        target_id='dso-nocoord',
        category='deep_sky',
        object_type='Nebula',
        preferred_name='Ghost',
        catalogue_names={'OpenNGC': 'NGC 0001'},
        coordinates=None,
    )
    _patch_dataset(monkeypatch, [no_coords])
    result = visibility_calendar.get_visibility_calendar('NGC 0001', _PARIS, _YEAR)
    assert result['supported'] is False
    assert result['reason'] == 'not_found'


def test_simbad_fallback_moving_target_is_unsupported(monkeypatch):
    _patch_dataset(monkeypatch, [])
    monkeypatch.setattr(
        visibility_calendar.object_info,
        '_resolve_via_simbad',
        lambda *_a, **_k: {'id': 'mars', 'name': 'Mars', 'type': 'Planet', 'ra': 1.0, 'dec': 1.0},
    )
    result = visibility_calendar.get_visibility_calendar('Mars', _PARIS, _YEAR)
    assert result['supported'] is False
    assert result['reason'] == 'moving_target'


def test_airmass_constraint_tightens_altitude_floor(monkeypatch):
    monkeypatch.setattr(
        visibility_calendar,
        'load_config',
        lambda: {
            'skytonight': {
                'constraints': {
                    'altitude_constraint_min': 10,
                    'altitude_constraint_max': 90,
                    'airmass_constraint': 2.0,
                }
            }
        },
    )
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])
    result = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)
    # asin(1/2) = 30 deg, which beats the configured 10 deg floor.
    assert result['constraints']['altitude_min'] == pytest.approx(30.0, abs=0.1)


def test_sample_failure_is_swallowed_and_logged(monkeypatch):
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])

    def _boom(*_a, **_k):
        raise RuntimeError("ephemeris blew up")

    monkeypatch.setattr(visibility_calendar, '_sample_night', _boom)
    result = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)
    assert result['supported'] is True
    assert result['samples'] == []
    assert result['months'] == []


def test_aggregate_months_skips_months_without_samples():
    samples = [
        {
            'date': '2026-03-01',
            'dark_hours': 8.0,
            'observable_hours': 4.0,
            'moonless_observable_hours': 2.0,
            'max_altitude': 60.0,
            'moon_illumination_pct': 20.0,
        },
        {
            'date': '2026-03-15',
            'dark_hours': 7.0,
            'observable_hours': 3.0,
            'moonless_observable_hours': 0.0,
            'max_altitude': None,
            'moon_illumination_pct': 80.0,
        },
    ]
    months = visibility_calendar._aggregate_months(samples)
    assert [m['month'] for m in months] == [3]
    assert months[0]['score'] == 1.0


def test_result_is_cached_and_lru_evicts(monkeypatch):
    _patch_dataset(monkeypatch, [_target('dso-m31', 0.712, 41.27, name='NGC 224')])

    first = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)
    second = visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR)
    assert first is second  # served from the LRU, not recomputed

    monkeypatch.setattr(visibility_calendar, '_MAX_CACHE_ENTRIES', 2)
    visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR + 1)
    visibility_calendar.get_visibility_calendar('NGC 224', _PARIS, _YEAR + 2)
    assert ('ngc 224', 'loc-paris', _YEAR) not in visibility_calendar._calendar_cache


class TestNightContextSplit:
    """The shared-context refactor must not change what the v1.4 calendar computes."""

    def _location(self):
        return {'id': 'loc-test', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}

    def test_context_fold_matches_the_single_night_sample(self):
        """One shared grid must give the same answer as the per-target path."""
        from datetime import date as _date

        night = _date(2026, 9, 15)
        direct = visibility_calendar._sample_night(10.68, 41.27, 48.0, 2.0, 'Europe/Paris', night, 30.0, 80.0, [])

        context = visibility_calendar.build_night_context(48.0, 2.0, 'Europe/Paris', night)
        folded = visibility_calendar.sample_target_in_context(context, 10.68, 41.27, 30.0, 80.0, [])

        assert folded == direct

    def test_one_context_serves_several_targets(self):
        from datetime import date as _date

        context = visibility_calendar.build_night_context(48.0, 2.0, 'Europe/Paris', _date(2026, 9, 15))
        andromeda = visibility_calendar.sample_target_in_context(context, 10.68, 41.27, 30.0, 80.0, [])
        orion = visibility_calendar.sample_target_in_context(context, 83.82, -5.39, 30.0, 80.0, [])

        assert andromeda['date'] == orion['date']
        assert andromeda['dark_hours'] == orion['dark_hours']
        # Different declinations from 48 N cannot produce the same peak altitude.
        assert andromeda['max_altitude'] != orion['max_altitude']

    def test_context_dark_hours_is_target_independent(self):
        from datetime import date as _date

        context = visibility_calendar.build_night_context(48.0, 2.0, 'Europe/Paris', _date(2026, 12, 21))
        dark_hours, moonless_dark_hours = visibility_calendar.context_dark_hours(context)
        assert dark_hours > 0
        assert 0 <= moonless_dark_hours <= dark_hours


class TestDarkHoursByMonth:

    def _location(self):
        return {'id': 'loc-dark', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}

    def test_returns_twelve_months(self):
        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        assert [row['month'] for row in rows] == list(range(1, 13))

    def test_winter_has_more_darkness_than_summer_in_the_north(self):
        """A sanity check that the figures are real rather than placeholders."""
        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        december = next(row for row in rows if row['month'] == 12)
        june = next(row for row in rows if row['month'] == 6)
        assert december['dark_hours'] > june['dark_hours']

    def test_moonless_darkness_never_exceeds_total_darkness(self):
        visibility_calendar.clear_batch_caches()
        for row in visibility_calendar.dark_hours_by_month(self._location(), 2026):
            assert row['moonless_dark_hours'] <= row['dark_hours'] + 1e-9

    def test_result_is_cached_per_location_and_year(self):
        visibility_calendar.clear_batch_caches()
        first = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        second = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        assert first is second

    def test_clearing_the_cache_recomputes(self):
        first = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        visibility_calendar.clear_batch_caches()
        assert visibility_calendar.dark_hours_by_month(self._location(), 2026) is not first

    def test_a_failed_sample_falls_back_to_a_null_month(self, monkeypatch):
        """A transient ephemeris failure must not crash the whole month grid - it just
        leaves the affected month(s) with no usable samples."""

        def _raise(*args, **kwargs):
            raise RuntimeError('ephemeris boom')

        monkeypatch.setattr(visibility_calendar, 'build_night_context', _raise)
        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.dark_hours_by_month(self._location(), 2026)
        assert all(row['dark_hours'] == 0.0 for row in rows)
        assert all(row['moon_illumination_pct'] is None for row in rows)

    def test_dark_hours_cache_evicts_the_oldest_entry(self, monkeypatch):
        monkeypatch.setattr(visibility_calendar, '_MAX_CACHE_ENTRIES', 1)
        visibility_calendar.clear_batch_caches()
        visibility_calendar.dark_hours_by_month(
            {'id': 'loc-a', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}, 2026
        )
        visibility_calendar.dark_hours_by_month(
            {'id': 'loc-b', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}, 2026
        )
        assert ('loc-a', 2026) not in visibility_calendar._dark_hours_cache


class TestNextVisibilityBatch:

    def _location(self):
        return {'id': 'loc-batch', 'latitude': 48.0, 'longitude': 2.0, 'timezone': 'Europe/Paris'}

    def test_returns_one_row_per_target_in_order(self):
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        targets = [
            {'ra_deg': 10.68, 'dec_deg': 41.27},
            {'ra_deg': 83.82, 'dec_deg': -5.39},
        ]
        rows = visibility_calendar.next_visibility_batch(targets, self._location(), _date(2026, 9, 15))
        assert len(rows) == 2
        assert all('observable_hours_next' in row for row in rows)

    def test_targets_without_coordinates_get_null_figures_not_dropped(self):
        """An unresolved wish still needs a row so the UI can say why."""
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        targets = [{'ra_deg': None, 'dec_deg': None}, {'ra_deg': 10.68, 'dec_deg': 41.27}]
        rows = visibility_calendar.next_visibility_batch(targets, self._location(), _date(2026, 9, 15))
        assert len(rows) == 2
        assert rows[0]['observable_hours_next'] is None
        assert rows[1]['observable_hours_next'] is not None

    def test_no_placed_target_short_circuits(self):
        from datetime import date as _date

        rows = visibility_calendar.next_visibility_batch(
            [{'ra_deg': None, 'dec_deg': None}], self._location(), _date(2026, 9, 15)
        )
        assert rows[0]['best_month'] is None

    def test_empty_input(self):
        assert visibility_calendar.next_visibility_batch([], self._location()) == []

    def test_first_sample_is_the_reference_date(self):
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.next_visibility_batch(
            [{'ra_deg': 10.68, 'dec_deg': 41.27}], self._location(), _date(2026, 9, 15)
        )
        assert rows[0]['sampled_dates'][0] == '2026-09-15'

    def test_month_rollover_is_handled(self):
        """November plus three months has to land in the next year, not month 14."""
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.next_visibility_batch(
            [{'ra_deg': 10.68, 'dec_deg': 41.27}], self._location(), _date(2026, 11, 20), months_ahead=3
        )
        assert rows[0]['sampled_dates'] == ['2026-11-20', '2026-12-15', '2027-01-15']

    def test_batch_matches_the_single_target_computation(self):
        """The shared grid must not change the numbers it produces."""
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        night = _date(2026, 9, 15)
        rows = visibility_calendar.next_visibility_batch(
            [{'ra_deg': 10.68, 'dec_deg': 41.27}], self._location(), night, months_ahead=1
        )
        alt_min, alt_max = visibility_calendar._resolve_constraints()
        direct = visibility_calendar._sample_night(10.68, 41.27, 48.0, 2.0, 'Europe/Paris', night, alt_min, alt_max, [])
        assert rows[0]['observable_hours_next'] == direct['observable_hours']
        assert rows[0]['max_altitude_next'] == direct['max_altitude']

    def test_contexts_are_reused_across_calls(self):
        """Repeated wishlist loads on the same day must do no fresh ephemeris work."""
        from datetime import date as _date

        visibility_calendar.clear_batch_caches()
        calls = []
        original = visibility_calendar.build_night_context

        def counting_context(*args, **kwargs):
            calls.append(args[3])
            return original(*args, **kwargs)

        visibility_calendar.build_night_context = counting_context
        try:
            targets = [{'ra_deg': 10.68, 'dec_deg': 41.27}]
            visibility_calendar.next_visibility_batch(targets, self._location(), _date(2026, 9, 15))
            first_pass = len(calls)
            visibility_calendar.next_visibility_batch(targets, self._location(), _date(2026, 9, 15))
            assert len(calls) == first_pass
        finally:
            visibility_calendar.build_night_context = original

    def test_a_failed_context_sample_is_skipped_not_raised(self, monkeypatch):
        """A transient ephemeris failure for one sampled night must not crash the batch -
        the row just keeps its null defaults for that sample."""
        from datetime import date as _date

        def _raise(*args, **kwargs):
            raise RuntimeError('ephemeris boom')

        monkeypatch.setattr(visibility_calendar, '_cached_night_context', _raise)
        visibility_calendar.clear_batch_caches()
        rows = visibility_calendar.next_visibility_batch(
            [{'ra_deg': 10.68, 'dec_deg': 41.27}], self._location(), _date(2026, 9, 15)
        )
        assert rows[0]['observable_hours_next'] is None
        assert rows[0]['best_month'] is None

    def test_context_cache_evicts_the_oldest_entry(self, monkeypatch):
        from datetime import date as _date

        monkeypatch.setattr(visibility_calendar, '_MAX_CONTEXT_ENTRIES', 1)
        visibility_calendar.clear_batch_caches()
        location_id = self._location()['id']
        visibility_calendar._cached_night_context(location_id, 48.0, 2.0, 'Europe/Paris', _date(2026, 1, 1))
        visibility_calendar._cached_night_context(location_id, 48.0, 2.0, 'Europe/Paris', _date(2026, 2, 1))
        assert (location_id, '2026-01-01') not in visibility_calendar._context_cache


# ---------------------------------------------------------------------------
# Cache keys follow location edits (made in any gunicorn worker)
# ---------------------------------------------------------------------------


def _counting_compute(monkeypatch):
    calls = []

    def _compute(identifier, location, year):
        calls.append((location.get('latitude'), year))
        return {'computed': len(calls)}

    monkeypatch.setattr(visibility_calendar, '_compute_visibility_calendar', _compute)
    monkeypatch.setattr(visibility_calendar, '_resolve_constraints', lambda: (30.0, 80.0))
    return calls


def test_calendar_cache_hit_for_unchanged_location(monkeypatch):
    calls = _counting_compute(monkeypatch)
    location = {'id': 'loc-1', 'latitude': 45.0, 'longitude': 5.0, 'timezone': 'UTC'}

    visibility_calendar.get_visibility_calendar('M31', location, 2026)
    visibility_calendar.get_visibility_calendar('m31', dict(location), 2026)

    assert len(calls) == 1


def test_calendar_cache_misses_after_location_coordinates_edit(monkeypatch):
    calls = _counting_compute(monkeypatch)
    location = {'id': 'loc-1', 'latitude': 45.0, 'longitude': 5.0, 'timezone': 'UTC'}

    visibility_calendar.get_visibility_calendar('M31', location, 2026)
    edited = dict(location, latitude=-33.0)
    result = visibility_calendar.get_visibility_calendar('M31', edited, 2026)

    assert calls == [(45.0, 2026), (-33.0, 2026)]
    assert result == {'computed': 2}


def test_calendar_cache_misses_after_horizon_or_constraint_change(monkeypatch):
    calls = _counting_compute(monkeypatch)
    location = {'id': 'loc-1', 'latitude': 45.0, 'longitude': 5.0, 'timezone': 'UTC'}

    visibility_calendar.get_visibility_calendar('M31', location, 2026)
    visibility_calendar.get_visibility_calendar('M31', dict(location, horizon_profile=[{'az': 0, 'alt': 20}]), 2026)
    monkeypatch.setattr(visibility_calendar, '_resolve_constraints', lambda: (40.0, 80.0))
    visibility_calendar.get_visibility_calendar('M31', location, 2026)

    assert len(calls) == 3
