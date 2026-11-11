"""
Demo data that keeps living (DEMO_MODE=true only).

A demo with an empty Astrodex and no plan shows nothing. This module gives the shared
demo account the life of a real observer, built from the application's own data:

- **Seed** (once, when the demo account holds no equipment and no Astrodex item): the
  demo location when the install has none, two equipment combinations (a smart telescope
  and a small refractor), a few classic targets in the Astrodex, each with a picture, and
  a wishlist.
- **Every night**: for each combination, the previous plan becomes an Observation Log
  session (its entries filled with frames and integration), its best target joins the
  Astrodex with a picture, and a new Plan My Night is built for tonight from tonight's
  SkyTonight results (the best-scoring targets that fit the combination's field), then
  ordered by the plan optimizer.

Every picture is a DSS2 colour survey cut-out (CDS / STScI) framed to the combination's
field, and says so in its notes: no amateur photo is ever passed off as a real capture.
Acquisition figures are illustrative demo values, derived deterministically from the plan.

Imported only by app.py, so the feature imports below cannot close a cycle.
"""

import hashlib
import json
import os
import threading
import uuid
from datetime import UTC, date, datetime, timedelta

from cache import cache_store
from equipment import equipment_profiles
from observation import astrodex, observation_sessions, plan_my_night, wishlist
from observation.object_info import download_dss_image
from skytonight import skytonight_targets
from skytonight.skytonight_storage import drop_location_results, get_dso_results_file
from utils import demo_mode
from utils.auth import user_manager
from utils.constants import DATA_DIR
from utils.file_lock import interprocess_lock
from utils.image_privacy import strip_image_metadata
from utils.logging_config import get_logger
from utils.repo_config import get_install_default_location, load_config, save_config

logger = get_logger(__name__)

# A public, well-known site: never anyone's home.
DEMO_LOCATION = {
    'name': 'Observatoire de Haute-Provence',
    'latitude': 43.9308,
    'longitude': 5.7133,
    'elevation': 650.0,
    'timezone': 'Europe/Paris',
    'bortle': 3,
}

# Two typical setups. 'key' ties a combination to its acquisition habits below.
DEMO_SETUPS = (
    {
        'key': 'smart',
        'telescope': {
            'name': 'Seestar S50',
            'manufacturer': 'ZWO',
            'telescope_type': 'refractor',
            'aperture_mm': 50,
            'focal_length_mm': 250,
        },
        'camera': {
            'name': 'Seestar S50 sensor (IMX462)',
            'manufacturer': 'ZWO',
            'sensor_width_mm': 5.6,
            'sensor_height_mm': 3.2,
            'resolution_width_px': 1920,
            'resolution_height_px': 1080,
            'pixel_size_um': 2.9,
            'sensor_type': 'color',
        },
        'sub_exposure_seconds': 10,
        'planned_minutes': 90,
        'targets_per_night': 3,
    },
    {
        'key': 'refractor',
        'telescope': {
            'name': 'Evostar 80ED',
            'manufacturer': 'Sky-Watcher',
            'telescope_type': 'refractor',
            'aperture_mm': 80,
            'focal_length_mm': 600,
            'reducer_barlow_factor': 0.85,
        },
        'camera': {
            'name': 'ASI533MC Pro',
            'manufacturer': 'ZWO',
            'sensor_width_mm': 11.31,
            'sensor_height_mm': 11.31,
            'resolution_width_px': 3008,
            'resolution_height_px': 3008,
            'pixel_size_um': 3.76,
            'sensor_type': 'color',
            'cooling_supported': True,
        },
        'sub_exposure_seconds': 180,
        'planned_minutes': 120,
        'targets_per_night': 3,
    },
)

# Classic targets seeded into the Astrodex, with the setup that "captured" them.
DEMO_ASTRODEX_SEED = (
    ('M31', 'smart'),
    ('M42', 'smart'),
    ('M45', 'smart'),
    ('NGC 7000', 'smart'),
    ('M13', 'refractor'),
    ('M27', 'refractor'),
    ('M51', 'refractor'),
    ('M8', 'refractor'),
)

DEMO_WISHLIST_SEED = ('M33', 'IC 1805', 'NGC 2237', 'M101')

DEMO_PICTURE_NOTE = 'Demo picture: DSS2 colour survey image (CDS / STScI), not an amateur capture.'
DEMO_SESSION_NOTE = 'Demo night: logged automatically from the plan, acquisition figures are illustrative.'

_PICTURE_SIZE_PX = 1200
_MOVING_TYPES = ('planet', 'comet', 'moon', 'asteroid', 'minor')
_MIN_OBSERVABLE_HOURS = 2.0
# How often the background loop checks whether a new night has come.
CHECK_INTERVAL_SECONDS = 600

_LOCK_PATH = os.path.join(DATA_DIR, 'demo_life.lock')
_state_lock = threading.Lock()
_stop = threading.Event()
_worker: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Entry points (called from app.py)
# ---------------------------------------------------------------------------


def apply_demo_location() -> bool:
    """Give a fresh install the demo location. Returns True when the location changed.

    Runs once at startup, before the schedulers, so the first SkyTonight run is already
    computed for it. An install whose location was set by its admin is left alone.
    """
    config = load_config()
    if config.get('location_configured'):
        return False
    preset = get_install_default_location(config)
    if not preset or not preset.get('id'):
        return False
    preset.update(DEMO_LOCATION)
    preset['updated_at'] = datetime.now(UTC).isoformat()
    config['location_configured'] = True
    save_config(config)
    cache_store.reset_caches_for_location(preset['id'])
    cache_store.update_location_config(preset)
    drop_location_results(preset['id'])
    logger.info(f"Demo mode: install location set to {DEMO_LOCATION['name']}")
    return True


def start() -> None:
    """Start the background loop that seeds, then refreshes, the demo data (idempotent).

    Every worker runs one; the inter-process lock makes them take turns, and a check
    with nothing to do costs a few small reads. The first check runs at once.
    """
    global _worker
    with _state_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_loop, name='demo-life', daemon=True)
        _worker.start()


def _loop() -> None:  # pragma: no cover - endless background loop, run_once() is tested
    while True:
        run_safely()
        _stop.wait(CHECK_INTERVAL_SECONDS)
        if _stop.is_set():
            return


def stop() -> None:
    """Stop the background loop (tests, worker exit)."""
    _stop.set()


def run_safely() -> None:
    """One check under the inter-process lock; a failure is logged, never raised."""
    try:
        with interprocess_lock(_LOCK_PATH):
            run_once()
    except Exception:
        logger.exception("Demo mode: refreshing the demo data failed")


def run_once(today: date | None = None) -> None:
    """Seed the demo account if it is empty, then make sure tonight's plans exist."""
    if skytonight_targets.find_target(DEMO_ASTRODEX_SEED[0][0]) is None:
        # Fresh install: the target dataset is still being built; the next check will seed
        logger.info("Demo mode: waiting for the SkyTonight target dataset")
        return
    user = demo_mode.get_or_create_demo_user(user_manager)
    if not user:
        return
    combinations = _ensure_equipment(user)
    if not combinations:
        return
    if not astrodex.load_user_astrodex(user.user_id, user.username).get('items'):
        _seed_astrodex(user, combinations, today or date.today())
        _seed_wishlist(user)
    refresh_tonight(user, combinations)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def _setup_by_key(key: str) -> dict:
    return next(setup for setup in DEMO_SETUPS if setup['key'] == key)


def _combination_name(setup: dict) -> str:
    return f"{setup['telescope']['name']} + {setup['camera']['name']}"


def _ensure_equipment(user) -> dict[str, dict]:
    """Return the demo combinations by setup key, creating them on an empty account.

    An account that already holds combinations (prepared by hand) is used as it is: its
    combinations are matched to the setups by name, and unmatched ones are ignored.
    """
    existing = equipment_profiles.load_user_combinations(user.user_id).get('items', [])
    by_name = {str(item.get('name')): item for item in existing if isinstance(item, dict)}
    found = {
        setup['key']: by_name[_combination_name(setup)] for setup in DEMO_SETUPS if _combination_name(setup) in by_name
    }
    if found or existing:
        return found

    created = {}
    for setup in DEMO_SETUPS:
        telescope = equipment_profiles.create_telescope(user.user_id, dict(setup['telescope']))
        camera = equipment_profiles.create_camera(user.user_id, dict(setup['camera']))
        if not telescope or not camera:
            logger.warning(f"Demo mode: could not create the {setup['key']} equipment")
            continue
        combination = equipment_profiles.create_combination(
            user.user_id,
            {'name': _combination_name(setup), 'telescope_id': telescope['id'], 'camera_id': camera['id']},
        )
        if combination:
            created[setup['key']] = combination
    logger.info(f"Demo mode: created {len(created)} equipment combinations")
    return created


def field_of_view_deg(setup: dict) -> tuple[float, float]:
    """Field of view (width, height) in degrees of a setup."""
    scope = setup['telescope']
    focal = float(scope['focal_length_mm']) * float(scope.get('reducer_barlow_factor') or 1.0)
    camera = setup['camera']
    return (
        57.2958 * float(camera['sensor_width_mm']) / focal,
        57.2958 * float(camera['sensor_height_mm']) / focal,
    )


def _catalogue_of(names: dict, preferred) -> str:
    """The catalogue whose designation is the preferred name (what the UI sends)."""
    for catalogue, value in (names or {}).items():
        if value == preferred:
            return catalogue
    return next(iter(names), '') if names else ''


def _seed_astrodex(user, combinations: dict[str, dict], today: date) -> None:
    """Add the classic targets, one picture each, dated over the past months."""
    for index, (name, setup_key) in enumerate(DEMO_ASTRODEX_SEED):
        combination = combinations.get(setup_key)
        target = skytonight_targets.find_target(name)
        if target is None or target.coordinates is None or combination is None:
            logger.warning(f"Demo mode: skipping Astrodex seed {name!r} (unknown target or setup)")
            continue
        setup = _setup_by_key(setup_key)
        frames, integration = _acquisition(setup, name, setup['planned_minutes'])
        _add_to_astrodex(
            user,
            {
                'name': target.preferred_name,
                'type': target.object_type,
                'catalogue': _catalogue_of(target.catalogue_names, target.preferred_name),
                'constellation': target.constellation,
            },
            ra_deg=target.coordinates.ra_hours * 15.0,
            dec_deg=target.coordinates.dec_degrees,
            setup=setup,
            combination=combination,
            when=today - timedelta(days=12 + 19 * index),
            frames=frames,
            integration_minutes=integration,
            rating=_rating(name),
        )


def _seed_wishlist(user) -> None:
    targets = []
    for name in DEMO_WISHLIST_SEED:
        target = skytonight_targets.find_target(name)
        if target is not None:
            targets.append(
                {
                    'name': target.preferred_name,
                    'catalogue': _catalogue_of(target.catalogue_names, target.preferred_name),
                    'type': target.object_type,
                }
            )
    if targets:
        wishlist.add_targets(user.user_id, user.username, targets)


# ---------------------------------------------------------------------------
# Every night
# ---------------------------------------------------------------------------


def _load_tonight() -> tuple[dict, list[dict]] | None:
    """Tonight's SkyTonight metadata and deep-sky rows for the install location."""
    location = get_install_default_location(load_config()) or {}
    path = get_dso_results_file(location.get('id'))
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except OSError, ValueError:
        return None
    metadata = data.get('metadata') or {}
    rows = data.get('deep_sky') or []
    if not metadata.get('night_found') or not metadata.get('night_start') or not metadata.get('night_end'):
        return None
    return metadata, [row for row in rows if isinstance(row, dict)]


def refresh_tonight(user, combinations: dict[str, dict]) -> None:
    """Log each finished plan, then build tonight's plan for every demo combination."""
    tonight = _load_tonight()
    if tonight is None:
        logger.info("Demo mode: no SkyTonight results yet, tonight's plans wait for the next check")
        return
    metadata, rows = tonight
    night_date = str(metadata['night_start'])[:10]
    in_astrodex = {
        _normalize(item.get('name'))
        for item in astrodex.load_user_astrodex(user.user_id, user.username).get('items', [])
    }
    taken_tonight: set[str] = set()

    for setup in DEMO_SETUPS:
        combination = combinations.get(setup['key'])
        if not combination:
            continue
        combination_id = combination['id']
        plan = plan_my_night.load_user_plan(user.user_id, user.username, combination_id=combination_id).get('plan')
        if plan and plan.get('plan_date') == night_date:
            taken_tonight.update(_normalize(entry.get('name')) for entry in plan.get('entries', []))
            continue
        if plan:
            if plan.get('entries') and str(plan.get('plan_date')) < night_date:
                _log_plan(user, plan, setup, combination, in_astrodex)
            plan_my_night.clear_plan(user.user_id, user.username, combination_id=combination_id)

        picks = pick_targets(rows, setup, exclude=in_astrodex | taken_tonight)
        if not picks:
            continue
        _build_plan(user, metadata, setup, combination, picks)
        taken_tonight.update(_normalize(row.get('preferred_name')) for row in picks)


def pick_targets(rows: list[dict], setup: dict, exclude: set[str]) -> list[dict]:
    """Tonight's best-scoring deep-sky targets that suit this setup's field of view.

    A target fits when it fills between a tenth and nine tenths of the field's short
    side, stays observable long enough, and is not already captured or planned.
    """
    width_deg, height_deg = field_of_view_deg(setup)
    short_side_arcmin = min(width_deg, height_deg) * 60.0
    candidates = []
    for row in rows:
        name = row.get('preferred_name')
        size = row.get('size_arcmin')
        object_type = str(row.get('object_type') or '').lower()
        observation = row.get('observation') or {}
        if not name or _normalize(name) in exclude or any(token in object_type for token in _MOVING_TYPES):
            continue
        if not isinstance(size, (int, float)) or not 0.1 * short_side_arcmin <= size <= 0.9 * short_side_arcmin:
            continue
        if float(observation.get('observable_hours') or 0) < _MIN_OBSERVABLE_HOURS:
            continue
        candidates.append(row)
    candidates.sort(key=lambda row: float(row.get('astro_score') or 0), reverse=True)
    return candidates[: setup['targets_per_night']]


def _build_plan(user, metadata: dict, setup: dict, combination: dict, picks: list[dict]) -> None:
    start = metadata['night_start']
    end = metadata['night_end']
    hours = float(metadata.get('night_hours') or 0.0)
    for row in picks:
        coordinates = row.get('coordinates') or {}
        catalogue = _catalogue_of(row.get('catalogue_names') or {}, row.get('preferred_name'))
        plan_my_night.create_or_add_target(
            user_id=user.user_id,
            username=user.username,
            item_data={
                'name': row.get('preferred_name'),
                'catalogue': catalogue,
                'type': row.get('object_type'),
                'constellation': row.get('constellation'),
                'ra': coordinates.get('ra_hours'),
                'dec': coordinates.get('dec_degrees'),
                'mag': row.get('magnitude'),
                'size': row.get('size_arcmin'),
                'difficulty': row.get('difficulty'),
                'alttime_file': row.get('target_id'),
                'source_type': 'recommendation',
                'planned_minutes': setup['planned_minutes'],
            },
            catalogue=catalogue,
            night_start=start,
            night_end=end,
            duration_hours=hours,
            combination_id=combination['id'],
            combination_name=combination.get('name'),
            location_id=metadata.get('location_id'),
            location_name=metadata.get('location_name'),
        )
    optimized = plan_my_night.compute_optimized_schedule(user.user_id, user.username, combination['id'])
    if optimized and optimized.get('order'):
        plan_my_night.apply_optimized_schedule(
            user.user_id,
            user.username,
            combination['id'],
            optimized['order'],
            int(optimized.get('start_delay_minutes') or 0),
        )
    logger.info(f"Demo mode: planned {len(picks)} targets for {combination.get('name')!r} on {str(start)[:10]}")


def _log_plan(user, plan: dict, setup: dict, combination: dict, in_astrodex: set[str]) -> None:
    """Turn a finished plan into a logged session; its best target joins the Astrodex."""
    session = observation_sessions.create_session_from_plan(user.user_id, user.username, plan)
    if not session:
        return
    data = observation_sessions.load_user_sessions(user.user_id, user.username)
    stored = next((item for item in data.get('sessions', []) if item.get('id') == session['id']), None)
    if stored is None:  # pragma: no cover - the session was just written
        return
    stored['notes'] = DEMO_SESSION_NOTE
    for entry in stored.get('entries', []):
        frames, integration = _acquisition(setup, entry.get('name'), entry.get('planned_minutes'))
        entry['frame_count'] = frames
        entry['sub_exposure_seconds'] = float(setup['sub_exposure_seconds'])
        entry['integration_minutes'] = integration
        entry['rating'] = _rating(entry.get('name'))
    observation_sessions.save_user_sessions(user.user_id, data, username=user.username)

    best = max(stored.get('entries', []), key=lambda entry: entry.get('rating') or 0, default=None)
    if not best or _normalize(best.get('name')) in in_astrodex:
        return
    try:
        ra_deg = float(best['ra']) * 15.0
        dec_deg = float(best['dec'])
    except KeyError, TypeError, ValueError:
        return
    item_id, picture_id = _add_to_astrodex(
        user,
        {
            'name': best.get('name'),
            'type': best.get('type'),
            'catalogue': best.get('catalogue'),
            'constellation': best.get('constellation'),
        },
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        setup=setup,
        combination=combination,
        when=date.fromisoformat(str(plan.get('plan_date'))[:10]),
        frames=best.get('frame_count'),
        integration_minutes=best.get('integration_minutes'),
        rating=best.get('rating'),
    )
    if item_id:
        in_astrodex.add(_normalize(best.get('name')))
        observation_sessions.link_entry_to_astrodex(user.user_id, stored['id'], best['id'], item_id, picture_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name) -> str:
    return ''.join(str(name or '').lower().split())


def _variation(name, spread: int) -> int:
    """A stable pseudo-random number in [0, spread) for a target name."""
    digest = hashlib.sha256(str(name or '').encode('utf-8')).digest()
    return int.from_bytes(digest[:4], 'big') % spread


def _acquisition(setup: dict, name, planned_minutes) -> tuple[int, float]:
    """Frames and integration minutes for a target: 70 to 95 % of the planned time."""
    try:
        planned = float(planned_minutes or setup['planned_minutes'])
    except TypeError, ValueError:
        planned = float(setup['planned_minutes'])
    kept = planned * (70 + _variation(name, 26)) / 100.0
    frames = max(1, int(kept * 60 // setup['sub_exposure_seconds']))
    return frames, round(frames * setup['sub_exposure_seconds'] / 60.0, 1)


def _rating(name) -> float:
    """3.5 to 5 stars, in half steps."""
    return 3.5 + 0.5 * _variation(f'rating:{name}', 4)


def _add_to_astrodex(
    user,
    item_data: dict,
    *,
    ra_deg: float,
    dec_deg: float,
    setup: dict,
    combination: dict,
    when: date,
    frames,
    integration_minutes,
    rating,
) -> tuple[str | None, str | None]:
    """Create an Astrodex item with one survey picture framed to the setup's field."""
    item = astrodex.create_astrodex_item(user.user_id, item_data, username=user.username)
    if not item:
        return None, None
    filename = _download_picture(user.user_id, ra_deg, dec_deg, max(field_of_view_deg(setup)))
    if not filename:
        return item['id'], None
    location = get_install_default_location(load_config()) or {}
    picture = astrodex.add_picture_to_item(
        user.user_id,
        item['id'],
        {
            'filename': filename,
            'date': when.isoformat(),
            'exposition_time': setup['sub_exposure_seconds'],
            'frames': frames,
            'integration_minutes': integration_minutes,
            'device': combination.get('name', ''),
            'notes': DEMO_PICTURE_NOTE,
            'location_id': location.get('id'),
            'location_name': location.get('name'),
            'latitude': location.get('latitude'),
            'longitude': location.get('longitude'),
            'elevation': location.get('elevation'),
            'combination_id': combination.get('id'),
            'combination_used_components': {'telescope': True, 'camera': True},
            'rating': rating,
        },
    )
    return item['id'], (picture or {}).get('id')


def _download_picture(user_id: str, ra_deg: float, dec_deg: float, fov_deg: float) -> str | None:
    """Fetch a DSS2 cut-out into the Astrodex pictures folder; return its file name."""
    astrodex.ensure_astrodex_directories()
    filename = f"{user_id}_{uuid.uuid4()}.jpg"
    path = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, filename)
    label = f'demo picture ra={ra_deg:.4f}, dec={dec_deg:.4f}'
    if not download_dss_image(ra_deg % 360.0, dec_deg, fov_deg, _PICTURE_SIZE_PX, path, label):
        logger.warning(f"Demo mode: no survey image for {label}")
        return None
    try:
        with open(path, 'rb') as handle:
            cleaned = strip_image_metadata(handle.read())
        with open(path, 'wb') as handle:
            handle.write(cleaned)
    except OSError, ValueError:
        logger.warning(f"Demo mode: unreadable survey image for {label}")
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return filename
