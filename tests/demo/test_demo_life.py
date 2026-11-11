"""Tests for demo/demo_life.py: the seeded demo account and its nightly plans and logs."""

import io
import json
import os
import sys
import types
from datetime import UTC, date, datetime, timedelta

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from PIL import Image

import app  # noqa: F401 - loads the backend path and the app factory
from demo import demo_life
from equipment import equipment_profiles
from observation import astrodex, observation_sessions, plan_my_night, wishlist
from skytonight.skytonight_models import SkyTonightCoordinates, SkyTonightTarget
from utils.auth import user_manager
from utils.repo_config import get_install_default_location, load_config, save_config

# name -> (type, constellation, ra_hours, dec_degrees, size_arcmin)
_FAKE_TARGETS = {
    'M31': ('Galaxy', 'And', 0.71, 41.27, 190.0),
    'M42': ('Nebula', 'Ori', 5.59, -5.39, 85.0),
    'M45': ('Open Cluster', 'Tau', 3.79, 24.12, 110.0),
    'NGC 7000': ('Emission Nebula', 'Cyg', 20.98, 44.33, 120.0),
    'M13': ('Globular Cluster', 'Her', 16.69, 36.46, 20.0),
    'M27': ('Planetary Nebula', 'Vul', 19.99, 22.72, 8.0),
    'M51': ('Galaxy', 'CVn', 13.50, 47.20, 11.0),
    'M8': ('Emission Nebula', 'Sgr', 18.06, -24.38, 45.0),
    'M33': ('Galaxy', 'Tri', 1.56, 30.66, 70.0),
    'IC 1805': ('Emission Nebula', 'Cas', 2.55, 61.45, 60.0),
    'NGC 2237': ('Emission Nebula', 'Mon', 6.53, 5.0, 80.0),
    'M101': ('Galaxy', 'UMa', 14.05, 54.35, 28.0),
}


def _fake_find_target(name):
    spec = _FAKE_TARGETS.get(name)
    if spec is None:
        return None
    object_type, constellation, ra, dec, size = spec
    catalogue = 'Messier' if name.startswith('M') else ('OpenIC' if name.startswith('IC') else 'OpenNGC')
    return SkyTonightTarget(
        target_id=f'dso-{name.lower().replace(" ", "")}',
        category='deep_sky',
        object_type=object_type,
        preferred_name=name,
        catalogue_names={catalogue: name},
        constellation=constellation,
        size_arcmin=size,
        coordinates=SkyTonightCoordinates(ra_hours=ra, dec_degrees=dec),
    )


def _fake_download(ra, dec, size_deg, size_px, local_path, label, timeout=None):
    buffer = io.BytesIO()
    Image.new('RGB', (16, 16), (10, 20, 40)).save(buffer, format='JPEG')
    with open(local_path, 'wb') as handle:
        handle.write(buffer.getvalue())
    return True


@pytest.fixture
def demo_env(monkeypatch, tmp_path):
    """Demo mode on, a fake target dataset, survey images written locally, results in tmp."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.delenv('DEMO_USERNAME', raising=False)
    monkeypatch.setattr(demo_life.skytonight_targets, 'find_target', _fake_find_target)
    monkeypatch.setattr(demo_life, 'download_dss_image', _fake_download)
    images = tmp_path / 'images'
    monkeypatch.setattr(astrodex, 'ASTRODEX_IMAGES_DIR', str(images))
    monkeypatch.setattr(astrodex, 'ensure_astrodex_directories', lambda: images.mkdir(exist_ok=True))
    results = tmp_path / 'dso_results.json'
    monkeypatch.setattr(demo_life, 'get_dso_results_file', lambda location_id=None: str(results))
    return results


def _row(name, score, size, hours=6.0, object_type=None):
    spec = _FAKE_TARGETS.get(name, ('Galaxy', 'And', 1.0, 40.0, size))
    return {
        'target_id': f'dso-{name.lower().replace(" ", "")}',
        'preferred_name': name,
        'catalogue_names': {'OpenNGC': name},
        'object_type': object_type or spec[0],
        'constellation': spec[1],
        'magnitude': 8.0,
        'size_arcmin': size,
        'coordinates': {'ra_hours': spec[2], 'dec_degrees': spec[3]},
        'observation': {'observable_hours': hours},
        'astro_score': score,
        'difficulty': 'beginner',
    }


def _write_results(path, night_start, rows):
    night_end = night_start + timedelta(hours=11)
    path.write_text(
        json.dumps(
            {
                'metadata': {
                    'night_found': True,
                    'night_start': night_start.isoformat(),
                    'night_end': night_end.isoformat(),
                    'night_hours': 11.0,
                    'location_id': 'loc-demo',
                    'location_name': 'Observatoire de Haute-Provence',
                },
                'deep_sky': rows,
            }
        ),
        encoding='utf-8',
    )


def _night_rows():
    """Rows that fit each setup: small ones for the refractor, larger ones for the Seestar."""
    return [
        _row('NGC 891', 0.95, 13.0),
        _row('NGC 6946', 0.93, 11.0),
        _row('NGC 2403', 0.90, 21.0),
        _row('NGC 7293', 0.92, 16.0),
        _row('IC 1396', 0.88, 30.0),
        _row('NGC 281', 0.86, 35.0),
        _row('M38', 0.85, 21.0),
        _row('Jupiter', 0.99, 0.6, object_type='Planet'),
    ]


def _demo_user():
    return user_manager.get_user_by_username('demo')


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_apply_demo_location_sets_the_observatory_on_a_fresh_install():
    """A fresh install (no location configured yet) gets the demo observatory."""
    config = load_config()
    config['location_configured'] = False
    save_config(config)

    assert demo_life.apply_demo_location() is True
    config = load_config()
    preset = get_install_default_location(config)
    assert preset['name'] == 'Observatoire de Haute-Provence'
    assert preset['latitude'] == pytest.approx(43.9308)
    assert config['location_configured'] is True


def test_apply_demo_location_leaves_a_configured_install_alone():
    """An admin's own location is never overwritten."""
    config = load_config()
    config['location_configured'] = True
    before = dict(get_install_default_location(config))
    save_config(config)

    assert demo_life.apply_demo_location() is False
    assert get_install_default_location(load_config())['name'] == before['name']


# ---------------------------------------------------------------------------
# Target choice
# ---------------------------------------------------------------------------


def test_field_of_view_accounts_for_the_reducer():
    """The refractor's 0.85x reducer widens its field compared with the bare focal length."""
    smart = demo_life.field_of_view_deg(demo_life._setup_by_key('smart'))
    refractor = demo_life.field_of_view_deg(demo_life._setup_by_key('refractor'))
    assert smart[0] == pytest.approx(57.2958 * 5.6 / 250)
    assert refractor[0] == pytest.approx(57.2958 * 11.31 / (600 * 0.85))


def test_pick_targets_keeps_fitting_observable_unknown_targets_by_score():
    """Too small, too large, too briefly visible, moving or excluded targets are skipped."""
    setup = demo_life._setup_by_key('refractor')  # short side about 76 arcmin
    rows = [
        _row('Tiny', 0.99, 2.0),
        _row('Huge', 0.98, 200.0),
        _row('Brief', 0.97, 20.0, hours=1.0),
        _row('Jupiter', 0.96, 20.0, object_type='Planet'),
        _row('Captured', 0.95, 20.0),
        _row('Third', 0.70, 20.0),
        _row('First', 0.90, 20.0),
        _row('Second', 0.80, 20.0),
        _row('Fourth', 0.60, 20.0),
        {'preferred_name': 'No size', 'astro_score': 0.99},
    ]
    picks = demo_life.pick_targets(rows, setup, exclude={'captured'})
    assert [row['preferred_name'] for row in picks] == ['First', 'Second', 'Third']


def test_acquisition_and_rating_are_stable_and_bounded():
    """The illustrative figures repeat for a target and stay within the planned time."""
    setup = demo_life._setup_by_key('refractor')
    frames, minutes = demo_life._acquisition(setup, 'M51', 120)
    assert (frames, minutes) == demo_life._acquisition(setup, 'M51', 120)
    assert 0.7 * 120 - 3 <= minutes <= 0.96 * 120
    assert frames == int(minutes * 60 // 180)
    assert demo_life._acquisition(setup, 'M51', 'not a number') == demo_life._acquisition(setup, 'M51', None)
    assert demo_life._rating('M51') in (3.5, 4.0, 4.5, 5.0)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def test_run_once_seeds_an_empty_demo_account(demo_env):
    """Equipment, an Astrodex with a picture per target, and a wishlist; no plan without results."""
    demo_life.run_once(today=date(2026, 11, 11))
    user = _demo_user()
    combinations = equipment_profiles.load_user_combinations(user.user_id)['items']
    assert {item['name'] for item in combinations} == {
        demo_life._combination_name(setup) for setup in demo_life.DEMO_SETUPS
    }

    items = astrodex.load_user_astrodex(user.user_id, user.username)['items']
    assert len(items) == len(demo_life.DEMO_ASTRODEX_SEED)
    for item in items:
        assert item['type'] != 'Unknown'
        assert len(item['pictures']) == 1
        picture = item['pictures'][0]
        assert picture['notes'] == demo_life.DEMO_PICTURE_NOTE
        assert picture['frames'] > 0
        assert os.path.isfile(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, picture['filename']))
        assert picture['filename'].startswith(f'{user.user_id}_')

    names = {item['name'] for item in wishlist.load_user_wishlist(user.user_id, user.username)['items']}
    assert names == set(demo_life.DEMO_WISHLIST_SEED)
    assert plan_my_night.load_user_plan(user.user_id, user.username, combinations[0]['id']).get('plan') is None


def test_run_once_does_not_seed_twice(demo_env):
    """A second check leaves an already seeded account as it is."""
    demo_life.run_once()
    demo_life.run_once()
    user = _demo_user()
    assert len(astrodex.load_user_astrodex(user.user_id, user.username)['items']) == len(demo_life.DEMO_ASTRODEX_SEED)
    assert len(equipment_profiles.load_user_combinations(user.user_id)['items']) == len(demo_life.DEMO_SETUPS)


def test_run_once_leaves_a_hand_prepared_account_alone(demo_env):
    """An account with its own equipment (none matching the demo setups) gets no generated data."""
    user = user_manager.create_user('demo', 'prepared', 'user')
    telescope = equipment_profiles.create_telescope(
        user.user_id, {'name': 'Mine', 'telescope_type': 'refractor', 'aperture_mm': 100, 'focal_length_mm': 700}
    )
    equipment_profiles.create_combination(user.user_id, {'name': 'My rig', 'telescope_id': telescope['id']})
    _write_results(demo_env, datetime.now(UTC) + timedelta(hours=2), _night_rows())

    demo_life.run_once()
    assert astrodex.load_user_astrodex(user.user_id, user.username)['items'] == []
    assert len(equipment_profiles.load_user_combinations(user.user_id)['items']) == 1


def test_seed_skips_targets_without_a_survey_image(demo_env, monkeypatch):
    """When no survey server answers, the item is still added, without a picture."""
    monkeypatch.setattr(demo_life, 'download_dss_image', lambda *args, **kwargs: False)
    demo_life.run_once()
    user = _demo_user()
    items = astrodex.load_user_astrodex(user.user_id, user.username)['items']
    assert items and all(item['pictures'] == [] for item in items)


def test_seed_skips_unknown_targets(demo_env, monkeypatch):
    """A seed target missing from the dataset is skipped, the others are added."""
    monkeypatch.setattr(
        demo_life.skytonight_targets, 'find_target', lambda name: None if name == 'M42' else _fake_find_target(name)
    )
    demo_life.run_once()
    user = _demo_user()
    names = {item['name'] for item in astrodex.load_user_astrodex(user.user_id, user.username)['items']}
    assert 'M42' not in names
    assert len(names) == len(demo_life.DEMO_ASTRODEX_SEED) - 1


# ---------------------------------------------------------------------------
# Every night
# ---------------------------------------------------------------------------


def _plans(user):
    combinations = equipment_profiles.load_user_combinations(user.user_id)['items']
    return {
        item['name']: plan_my_night.load_user_plan(user.user_id, user.username, item['id']).get('plan')
        for item in combinations
    }


def test_tonight_gets_one_plan_per_setup_from_the_results(demo_env):
    """Each setup gets a plan for tonight, with fitting targets, and no target twice."""
    night_start = datetime.now(UTC) + timedelta(hours=2)
    _write_results(demo_env, night_start, _night_rows())
    demo_life.run_once()

    plans = _plans(_demo_user())
    assert all(plan is not None for plan in plans.values())
    all_names = []
    for plan in plans.values():
        assert plan['plan_date'] == night_start.isoformat()[:10]
        assert 1 <= len(plan['entries']) <= 3
        assert all(entry['name'] != 'Jupiter' for entry in plan['entries'])
        all_names += [entry['name'] for entry in plan['entries']]
    assert len(all_names) == len(set(all_names))


def test_tonight_plans_are_not_rebuilt_on_the_same_night(demo_env):
    """A second check on the same night keeps the plans untouched."""
    _write_results(demo_env, datetime.now(UTC) + timedelta(hours=2), _night_rows())
    demo_life.run_once()
    first = _plans(_demo_user())
    demo_life.run_once()
    assert _plans(_demo_user()) == first


def test_next_night_logs_the_previous_plan_and_plans_again(demo_env):
    """The finished plan becomes a logged session, its best target joins the Astrodex."""
    first_night = datetime.now(UTC) + timedelta(hours=2)
    _write_results(demo_env, first_night, _night_rows())
    demo_life.run_once()
    user = _demo_user()
    first_plans = _plans(user)
    planned = {entry['name'] for plan in first_plans.values() for entry in plan['entries']}

    _write_results(demo_env, first_night + timedelta(days=1), _night_rows() + [_row('NGC 7331', 0.94, 10.0)])
    demo_life.run_once()

    sessions = observation_sessions.get_user_sessions(user.user_id)
    assert len(sessions) == len(demo_life.DEMO_SETUPS)
    for session in sessions:
        assert session['notes'] == demo_life.DEMO_SESSION_NOTE
        assert session['entries']
        assert all(entry['frame_count'] > 0 and entry['integration_minutes'] > 0 for entry in session['entries'])
        assert any(entry.get('astrodex_item_id') for entry in session['entries'])

    astrodex_names = {item['name'] for item in astrodex.load_user_astrodex(user.user_id, user.username)['items']}
    assert len(astrodex_names & planned) == len(demo_life.DEMO_SETUPS)

    for plan in _plans(user).values():
        assert plan['plan_date'] == (first_night + timedelta(days=1)).isoformat()[:10]
        assert not {entry['name'] for entry in plan['entries']} & astrodex_names


def test_no_results_means_no_plan_yet(demo_env):
    """Without tonight's SkyTonight results, the plans wait for the next check."""
    demo_env.write_text(json.dumps({'metadata': {'night_found': False}, 'deep_sky': []}), encoding='utf-8')
    demo_life.run_once()
    assert all(plan is None for plan in _plans(_demo_user()).values())


def test_run_safely_logs_instead_of_raising(demo_env, monkeypatch):
    """A failure in the background check never escapes the thread."""

    def explode(today=None):
        raise RuntimeError('boom')

    monkeypatch.setattr(demo_life, 'run_once', explode)
    demo_life.run_safely()


def test_run_once_stops_without_a_demo_account(demo_env, monkeypatch):
    """When the demo account cannot be created, there is nothing to do."""
    monkeypatch.setattr(demo_life.demo_mode, 'get_or_create_demo_user', lambda um: None)
    demo_life.run_once()
    assert user_manager.get_user_by_username('demo') is None


def test_start_runs_one_loop_per_process(monkeypatch):
    """Starting twice keeps a single background loop."""
    calls = []
    monkeypatch.setattr(demo_life, '_loop', lambda: calls.append(1) or demo_life._stop.wait(5))
    monkeypatch.setattr(demo_life, '_worker', None)
    demo_life._stop.clear()
    try:
        demo_life.start()
        demo_life.start()
    finally:
        demo_life.stop()
        demo_life._worker.join(timeout=5)
        demo_life._stop.clear()
    assert calls == [1]


def test_run_once_waits_for_the_target_dataset(demo_env, monkeypatch):
    """On a fresh install, nothing is created before the target dataset exists."""
    monkeypatch.setattr(demo_life.skytonight_targets, 'find_target', lambda name: None)
    demo_life.run_once()
    assert user_manager.get_user_by_username('demo') is None
