"""SkyTonight observability calculator.

Computes, for each target in the dataset, the visibility metrics and
AstroScore for the upcoming nautical night and writes the results
to a JSON cache file.  The scheduler calls :func:`run_calculations`
once per cycle; the API reads from the cache file rather than
recomputing on every request.
"""

from __future__ import annotations

import gc
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, cast
from zoneinfo import ZoneInfo

import numpy as np
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

from astroplan.moon import moon_illumination

from utils.logging_config import get_logger
from utils.repo_config import load_config
from skytonight.skytonight_models import SkyTonightTarget
from skytonight.skytonight_storage import (
    ensure_skytonight_directories,
    get_alttime_dir,
    get_bodies_results_file,
    get_comets_results_file,
    get_dso_results_file,
    get_results_file,
    get_skymap_file,
)
from skytonight.skytonight_targets import choose_preferred_catalogue_name, load_targets_dataset, normalize_object_name
from astroweather.sun_phases import SunService
from utils import load_json_file, save_json_file

logger = get_logger(__name__)

# How many time-steps to generate over the night window for trajectory sampling
_TIME_RESOLUTION_MINUTES = 15

# Minimum number of time steps required to compute meaningful fractions
_MIN_STEPS = 2

# Log a progress line every N deep-sky targets
_DSO_LOG_INTERVAL = 500

# A DSO passes the observability gate when it meets the fraction threshold
# OR is visible for this many hours or more - prevents spring/fall targets from
# being excluded just because they transit before dusk or set shortly after it.
_MIN_OBSERVABLE_HOURS_DSO = 1.0

# Regex pattern for valid alttime target IDs used in file names
_ALTTIME_ID_SAFE = re.compile(r'[^a-z0-9_-]')


def _alttime_json_path(target_id: str, location_id: Optional[str] = None) -> str:
    """Return the full path for a target's altitude-time JSON file (per location)."""
    safe_id = _ALTTIME_ID_SAFE.sub('_', target_id.lower())
    return os.path.join(get_alttime_dir(location_id), f'{safe_id}_alttime.json')


def _save_alttime_json(
    target_id: str,
    name: str,
    times: Any,
    altitudes: np.ndarray,
    night_start: datetime,
    night_end: datetime,
    constraints: Dict[str, Any],
    timezone_name: str = 'UTC',
    precomputed_times_iso: Optional[List[str]] = None,
    az_degrees: Optional[np.ndarray] = None,
    astro_night_start: Optional[datetime] = None,
    astro_night_end: Optional[datetime] = None,
    location_id: Optional[str] = None,
) -> bool:
    """Persist altitude-time series for one target to the location's outputs directory.

    The JSON is consumed by the frontend Chart.js graph rendered on demand
    when the user opens the altitude-vs-time popup for a specific target.
    Only targets that pass visibility constraints are saved; the presence of
    the file is used by the API to indicate that a graph is available.
    """
    try:
        if precomputed_times_iso is not None:
            times_iso = precomputed_times_iso
        else:
            times_iso = [
                t.strftime('%Y-%m-%dT%H:%M:%S')  # type: ignore[attr-defined]
                for t in times.to_datetime(timezone=timezone.utc)
            ]
        payload: Dict[str, Any] = {
            'target_id': target_id,
            'name': name,
            'timezone': timezone_name,
            'night_start': night_start.isoformat(),
            'night_end': night_end.isoformat(),
            'times_utc': times_iso,
            'altitudes': [round(float(a), 2) for a in altitudes],
            'altitude_constraint_min': float(constraints.get('altitude_constraint_min', 30)),
            'altitude_constraint_max': float(constraints.get('altitude_constraint_max', 80)),
        }
        if astro_night_start is not None:
            payload['night_astro_start'] = astro_night_start.isoformat()
        if astro_night_end is not None:
            payload['night_astro_end'] = astro_night_end.isoformat()
        if az_degrees is not None:
            payload['azimuths'] = [round(float(a), 1) for a in az_degrees]
        horizon_profile_save = constraints.get('horizon_profile', [])
        if horizon_profile_save:
            payload['horizon_profile'] = horizon_profile_save
        path = _alttime_json_path(target_id, location_id)
        return save_json_file(path, payload)
    except Exception as exc:
        logger.debug(f'Failed to save alttime JSON for {target_id}: {exc}')
        return False


def _clear_alttime_files(location_id: Optional[str] = None) -> None:
    """Remove one location's altitude-time JSON files from the previous run."""
    try:
        alttime_dir = get_alttime_dir(location_id)
        for filename in os.listdir(alttime_dir):
            if filename.endswith('_alttime.json'):
                try:
                    os.remove(os.path.join(alttime_dir, filename))
                except Exception:
                    pass  # best-effort stale file cleanup; non-fatal
    except Exception as exc:
        logger.debug(f'Failed to clear alttime files: {exc}')


# ---------------------------------------------------------------------------
# Module-level calculation progress - updated in-place during run_calculations
# so the scheduler can surface live phase info while calculation runs.
# ---------------------------------------------------------------------------
_calculation_progress: Dict[str, Any] = {}


def get_calculation_progress() -> Dict[str, Any]:
    """Return a snapshot of the current calculation phase information."""
    return dict(_calculation_progress)


def _set_progress(phase: str, processed: int = 0, total: int = 0) -> None:
    """Update the module-level progress dict in place (thread-safe via GIL)."""
    _calculation_progress['phase'] = phase
    _calculation_progress['phase_processed'] = processed
    _calculation_progress['phase_total'] = total


# ---------------------------------------------------------------------------


def _parse_localtime(text: str, tz: ZoneInfo) -> Optional[datetime]:
    text = str(text or '').strip()
    if not text or text == 'Not found':
        return None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            pass
    return None


def _normalise(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Return angular separation in degrees between two equatorial positions."""
    ra1_r = math.radians(ra1)
    dec1_r = math.radians(dec1)
    ra2_r = math.radians(ra2)
    dec2_r = math.radians(dec2)

    cos_val = math.sin(dec1_r) * math.sin(dec2_r) + math.cos(dec1_r) * math.cos(dec2_r) * math.cos(ra1_r - ra2_r)
    # Clamp to [-1, 1] to guard against floating-point drift
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.degrees(math.acos(cos_val))


def _horizon_floor_array(az_deg: np.ndarray, profile: List[Dict[str, Any]]) -> np.ndarray:
    """Return the custom horizon minimum altitude at each azimuth sample.

    Linearly interpolates between profile points on the circular azimuth scale.
    ``profile`` is a list of dicts with ``az`` (0-360°) and ``alt`` (0-90°) keys.
    Returns a zero array when the profile is empty or invalid so that the caller's
    flat ``alt_min`` acts as the sole floor.
    """
    if not profile:
        return np.zeros(len(az_deg), dtype=np.float32)
    try:
        sorted_pts = sorted(profile, key=lambda p: float(p['az']))
        p_az = np.array([float(p['az']) for p in sorted_pts], dtype=np.float64)
        p_alt = np.array([float(p['alt']) for p in sorted_pts], dtype=np.float64)
        # Extend with wrap-around copies so np.interp handles the 0°/360° seam
        wrap_az = np.concatenate([p_az[-1:] - 360.0, p_az, p_az[:1] + 360.0])
        wrap_alt = np.concatenate([p_alt[-1:], p_alt, p_alt[:1]])
        return np.interp(az_deg % 360.0, wrap_az, wrap_alt).astype(np.float32)
    except Exception:
        return np.zeros(len(az_deg), dtype=np.float32)


def _surface_brightness(magnitude: Optional[float], size_arcmin: Optional[float]) -> Optional[float]:
    """Approximate surface brightness from integrated magnitude and angular size."""
    if magnitude is None or size_arcmin is None or size_arcmin <= 0:
        return None
    surface_area = math.pi * ((size_arcmin / 2.0) ** 2)
    return magnitude + 2.5 * math.log10(surface_area)


# ---------------------------------------------------------------------------
# Night window detection
# ---------------------------------------------------------------------------


def _get_night_window(
    lat: float,
    lon: float,
    timezone_name: str,
) -> Optional[Tuple[datetime, datetime]]:
    """Return (dusk, dawn) for tonight's nautical night; None if no night."""
    tz = ZoneInfo(timezone_name)
    sun_service = SunService(latitude=lat, longitude=lon, timezone=timezone_name)
    report = sun_service.get_today_report()

    dusk = _parse_localtime(report.nautical_dusk, tz)
    dawn = _parse_localtime(report.nautical_dawn, tz)

    if dusk is None or dawn is None:
        return None
    if dawn <= dusk:
        # Dusk already past - try tomorrow
        report_tomorrow = sun_service.get_tomorrow_report()
        dusk = _parse_localtime(report_tomorrow.nautical_dusk, tz)
        dawn = _parse_localtime(report_tomorrow.nautical_dawn, tz)

    if dusk is None or dawn is None or dawn <= dusk:
        return None

    return dusk, dawn


def _get_astro_night_window(
    lat: float,
    lon: float,
    timezone_name: str,
) -> Optional[Tuple[datetime, datetime]]:
    """Return (astro_dusk, astro_dawn) for tonight's astronomical night (-18° sun); None if unavailable."""
    tz = ZoneInfo(timezone_name)
    sun_service = SunService(latitude=lat, longitude=lon, timezone=timezone_name)
    report = sun_service.get_today_report()

    dusk = _parse_localtime(report.astronomical_dusk, tz)
    dawn = _parse_localtime(report.astronomical_dawn, tz)

    if dusk is None or dawn is None or dawn <= dusk:
        report_tomorrow = sun_service.get_tomorrow_report()
        dusk = _parse_localtime(report_tomorrow.astronomical_dusk, tz)
        dawn = _parse_localtime(report_tomorrow.astronomical_dawn, tz)

    if dusk is None or dawn is None or dawn <= dusk:
        return None

    return dusk, dawn


# ---------------------------------------------------------------------------
# Per-target computation
# ---------------------------------------------------------------------------


def _sample_times(night_start: datetime, night_end: datetime) -> Time:
    """Return an Astropy Time array sampled at fixed intervals over the night."""
    total_minutes = (night_end - night_start).total_seconds() / 60.0
    n_steps = max(_MIN_STEPS, int(total_minutes // _TIME_RESOLUTION_MINUTES) + 1)
    step_minutes = total_minutes / (n_steps - 1)

    times_utc = [night_start + timedelta(minutes=i * step_minutes) for i in range(n_steps)]
    # Astropy isot format requires bare UTC strings without timezone offset (e.g.
    # "2026-04-01T20:00:00.000"), so strip the "+00:00" suffix produced by isoformat().
    iso_strings = [t.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000') for t in times_utc]
    return Time(iso_strings, format='isot', scale='utc')


def _compute_altaz_series(
    ra_hours: float,
    dec_degrees: float,
    times: Any,
    location: EarthLocation,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (alt_deg, az_deg) arrays for the target over 'times'."""
    coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_degrees * u.deg, frame='icrs')
    frame = AltAz(obstime=times, location=location)
    altaz = coord.transform_to(frame)
    return altaz.alt.deg, altaz.az.deg  # type: ignore[return-value]


def _compute_body_altaz_series(
    body_name: str,
    times: Any,
    location: EarthLocation,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """Return (alt_deg, az_deg, ra_hours_mid, dec_degrees_mid) for a solar system body.

    Uses astropy's built-in ephemeris so positions are accurate for the current date.
    The RA/Dec mid-night values are returned for display in the More popup.
    """
    frame = AltAz(obstime=times, location=location)
    body_coord = get_body(body_name.lower(), times, location)
    altaz = body_coord.transform_to(frame)
    alt_deg: np.ndarray = altaz.alt.deg  # type: ignore[assignment]
    az_deg: np.ndarray = altaz.az.deg  # type: ignore[assignment]

    # RA/Dec at night midpoint for display
    mid_idx = len(times) // 2
    mid_coord = get_body(body_name.lower(), times[mid_idx], location)
    ra_hours_mid = float(mid_coord.ra.hour)  # type: ignore[attr-defined]
    dec_degrees_mid = float(mid_coord.dec.deg)  # type: ignore[attr-defined]

    return alt_deg, az_deg, ra_hours_mid, dec_degrees_mid


def _meridian_transit_time(
    ra_hours: float,
    night_start: datetime,
    night_end: datetime,
    lat: float,
    lon: float,
) -> Optional[str]:
    """
    Approximate meridian transit time (local sidereal time equals target RA).

    We use a simple linear search because precision at the minute level is
    sufficient for the display field.
    """
    try:
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg)
        step = timedelta(minutes=_TIME_RESOLUTION_MINUTES)
        current = night_start

        prev_hour_angle: Optional[float] = None

        while current <= night_end:
            utc_moment = current.astimezone(timezone.utc)
            t = Time(utc_moment.strftime('%Y-%m-%dT%H:%M:%S.000'), format='isot', scale='utc')
            lst_hours = float(t.sidereal_time('apparent', longitude=location.lon).hour)  # type: ignore[attr-defined]
            ha = ((lst_hours - ra_hours + 12.0) % 24.0) - 12.0  # [-12, +12]

            if prev_hour_angle is not None and prev_hour_angle < 0.0 <= ha:
                return current.strftime('%H:%M')

            prev_hour_angle = float(ha)
            current += step

        return None
    except Exception as exc:
        logger.debug(f'Meridian transit estimation failed: {exc}')
        return None


def _antimeridian_transit_time(
    ra_hours: float,
    night_start: datetime,
    night_end: datetime,
    lat: float,
    lon: float,
) -> Optional[str]:
    """Approximate antimeridian transit (HA = ±12 h)."""
    try:
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg)
        anti_ra = (ra_hours + 12.0) % 24.0
        step = timedelta(minutes=_TIME_RESOLUTION_MINUTES)
        current = night_start
        prev_hour_angle: Optional[float] = None

        while current <= night_end:
            utc_moment = current.astimezone(timezone.utc)
            t = Time(utc_moment.strftime('%Y-%m-%dT%H:%M:%S.000'), format='isot', scale='utc')
            lst_hours = float(t.sidereal_time('apparent', longitude=location.lon).hour)  # type: ignore[attr-defined]
            ha = ((lst_hours - anti_ra + 12.0) % 24.0) - 12.0

            if prev_hour_angle is not None and prev_hour_angle < 0.0 <= ha:
                return current.strftime('%H:%M')

            prev_hour_angle = float(ha)
            current += step

        return None
    except Exception as exc:
        logger.debug(f'Antimeridian transit estimation failed: {exc}')
        return None


def _meridian_transit_fast(
    ra_hours: float,
    lst_hours: np.ndarray,
    times_local: List[datetime],
) -> Optional[str]:
    """Fast meridian transit using a precomputed LST array (avoids per-step sidereal_time calls)."""
    try:
        ha = ((lst_hours - ra_hours + 12.0) % 24.0) - 12.0
        crossings = np.where((ha[:-1] < 0) & (ha[1:] >= 0))[0]
        if len(crossings) > 0:
            return times_local[int(crossings[0]) + 1].strftime('%H:%M')
        return None
    except Exception as exc:
        logger.debug(f'Fast meridian transit failed: {exc}')
        return None


def _antimeridian_transit_fast(
    ra_hours: float,
    lst_hours: np.ndarray,
    times_local: List[datetime],
) -> Optional[str]:
    """Fast antimeridian transit using a precomputed LST array."""
    try:
        anti_ra = (ra_hours + 12.0) % 24.0
        ha = ((lst_hours - anti_ra + 12.0) % 24.0) - 12.0
        crossings = np.where((ha[:-1] < 0) & (ha[1:] >= 0))[0]
        if len(crossings) > 0:
            return times_local[int(crossings[0]) + 1].strftime('%H:%M')
        return None
    except Exception as exc:
        logger.debug(f'Fast antimeridian transit failed: {exc}')
        return None


class _MoonInfo:
    """Cached moon properties for one night session."""

    def __init__(self, times: Any, location: EarthLocation) -> None:
        self.phase: float = 0.0  # 0 = new, 1 = full
        self.ra_deg: Optional[float] = None
        self.dec_deg: Optional[float] = None
        self._compute(times, location)

    def _compute(self, times: Any, location: EarthLocation) -> None:
        try:
            mid_time = times[len(times) // 2]
            illum = moon_illumination(mid_time)
            self.phase = float(illum)

            moon_coord = get_body('moon', mid_time, location)
            self.ra_deg = float(moon_coord.ra.deg)  # type: ignore[attr-defined]
            self.dec_deg = float(moon_coord.dec.deg)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug(f'Moon info computation failed: {exc}')


# ---------------------------------------------------------------------------
# AstroScore calculation
# ---------------------------------------------------------------------------


def compute_astro_score(
    *,
    max_altitude: float,
    observable_hours: float,
    meridian_altitude: float,
    moon_phase: float,
    angular_distance_moon: Optional[float],
    magnitude: Optional[float],
    size_arcmin: Optional[float],
    observable_hours_in_window: float,
    window_start_hour: int,
    is_messier: bool = False,
    is_planet: bool = False,
    is_opposition: bool = False,
    sqm: Optional[float] = None,
    object_type: Optional[str] = None,
) -> float:
    """
    Compute AstroScore on [0, 1] for astrophotography suitability.

    Score components
    ----------------
    score_visibility  (weight 0.40):
        Combines peak altitude, observable hours, and meridian altitude.

    score_sky  (weight 0.25):
        Moon phase + angular distance from moon.

    score_object  (weight 0.25):
        Surface brightness proxy using magnitude + apparent size.

    score_comfort  (weight 0.10):
        Penalises targets only observable in inconvenient late-night hours.

    Bonuses applied after normalisation:
        +0.20 for planet at opposition, capped at 1.0.
        +0.05 for Messier objects (high visual reward).
    """
    # --- score_visibility ---
    sv = (
        0.5 * _normalise(max_altitude, 20.0, 90.0)
        + 0.3 * _normalise(observable_hours, 0.0, 8.0)
        + 0.2 * _normalise(meridian_altitude, 20.0, 90.0)
    )

    # --- score_sky ---
    moon_distance_used = angular_distance_moon if angular_distance_moon is not None else 180.0
    moon_impact = moon_phase * (1.0 - moon_distance_used / 180.0)
    sky_score = max(0.0, 1.0 - moon_impact)

    # Light pollution penalty: multiply sky score by the per-object-type LP factor.
    # When sqm is None (not configured) the factor is 1.0 → no change.
    if sqm is not None:
        from weather.sky_quality import object_lp_factor

        sky_score *= object_lp_factor(sqm, object_type)

    # --- score_object ---
    sb = _surface_brightness(magnitude, size_arcmin)
    if sb is not None:
        obj_score = _normalise(sb, 12.0, 22.0)
        # Invert: lower surface-brightness number → brighter/easier → higher score
        obj_score = 1.0 - obj_score
    else:
        # No magnitude/size data - neutral contribution
        obj_score = 0.5

    # --- score_comfort ---
    # Reward targets that transit during prime evening hours (21:00-01:00).
    # Use explicit hour buckets to keep logic clear and avoid wraparound comparisons.
    if window_start_hour in (21, 22, 23, 0, 1):
        time_bonus = 1.0
    elif window_start_hour in (2, 3):
        time_bonus = 0.5
    else:
        time_bonus = 0.0

    comfort_score = 0.5 * _normalise(observable_hours_in_window, 0.0, 6.0) + 0.5 * time_bonus

    # --- Weighted sum ---
    score = 0.40 * sv + 0.25 * sky_score + 0.25 * obj_score + 0.10 * comfort_score

    # --- Bonuses ---
    if is_opposition and is_planet:
        score += 0.20
    if is_messier:
        score += 0.05

    return round(min(1.0, max(0.0, score)), 4)


# Fixed literal ranges for difficulty normalisation - intentionally not tied to
# user-configurable observability constraints, since difficulty must be static
# and location/Bortle-independent (Bortle affects AstroScore, not difficulty).
_DIFFICULTY_SB_RANGE = (12.0, 22.0)
_DIFFICULTY_SIZE_ARCMIN_RANGE = (1.0, 120.0)
_DIFFICULTY_MAGNITUDE_RANGE = (0.0, 16.0)

_DIFFICULTY_WEIGHT_SURFACE_BRIGHTNESS = 0.40
_DIFFICULTY_WEIGHT_SIZE = 0.30
_DIFFICULTY_WEIGHT_MAGNITUDE = 0.20
# Minimum-integration-hours weight (0.10) is not applied - see docstring below.


def compute_difficulty_score(target: SkyTonightTarget) -> Tuple[int, str]:
    """
    Compute a static astrophotography difficulty score and label for a target.

    Score components (of the theoretical 100-point weighted total)
    ----------------
    surface_brightness (weight 0.40):
        Derived from magnitude + angular size via ``_surface_brightness()``.
        A higher (dimmer) surface brightness value increases difficulty.

    angular_size (weight 0.30):
        A larger apparent size is easier to frame and reduces difficulty.

    visual_magnitude (weight 0.20):
        A brighter (lower) magnitude is easier and reduces difficulty.

    minimum_integration (weight 0.10):
        No per-target minimum-integration-time data exists in the general
        catalogue (only the curated 30-object beginner catalog has it). This
        factor is a documented simplification: it always contributes 0,
        capping the maximum achievable raw score at ~90 instead of 100. This
        does not materially affect the beginner/intermediate/advanced
        thresholds, which sit well below that ceiling.

    Fallback behaviour
    ------------------
    When magnitude or size_arcmin is missing, surface brightness cannot be
    computed, so the surface_brightness contribution is zeroed (not
    proportionally rescaled) and scoring falls back to whichever single factor
    is actually available: "magnitude-only" scoring if magnitude is present,
    or "size-only" scoring if only size_arcmin is present. If both are
    unavailable, the function returns a neutral default of (50, 'intermediate').

    Difficulty is static (computed once from magnitude/size only) and does
    not depend on Bortle or sky quality - those affect AstroScore, not this
    label.

    Returns
    -------
    Tuple[int, str]
        ``(difficulty_score, difficulty)`` where ``difficulty_score`` is in
        [0, 100] (lower = easier) and ``difficulty`` is one of
        ``'beginner'`` (score <= 35), ``'intermediate'`` (35 < score <= 65),
        or ``'advanced'`` (score > 65).
    """
    magnitude = target.magnitude
    size_arcmin = target.size_arcmin

    if magnitude is None and size_arcmin is None:
        return 50, 'intermediate'

    sb = _surface_brightness(magnitude, size_arcmin)

    if sb is not None:
        # _surface_brightness only returns non-None when both inputs are non-None.
        magnitude_component = _normalise(cast(float, magnitude), *_DIFFICULTY_MAGNITUDE_RANGE)
        sb_component = _normalise(sb, *_DIFFICULTY_SB_RANGE)
        size_norm = _normalise(cast(float, size_arcmin), *_DIFFICULTY_SIZE_ARCMIN_RANGE)
        size_component = 1.0 - size_norm
        raw_score = (
            _DIFFICULTY_WEIGHT_SURFACE_BRIGHTNESS * sb_component
            + _DIFFICULTY_WEIGHT_SIZE * size_component
            + _DIFFICULTY_WEIGHT_MAGNITUDE * magnitude_component
        )
    elif magnitude is not None:
        # Size missing: magnitude-only fallback (surface_brightness/size zeroed).
        magnitude_component = _normalise(magnitude, *_DIFFICULTY_MAGNITUDE_RANGE)
        raw_score = _DIFFICULTY_WEIGHT_MAGNITUDE * magnitude_component
    else:
        # Magnitude missing, size available: size-only fallback (mirrors the
        # magnitude-only branch above) instead of discarding the known size_arcmin.
        # Guaranteed non-None here: line 621 ruled out both being None, and this
        # branch is only reached when magnitude is None.
        size_norm = _normalise(cast(float, size_arcmin), *_DIFFICULTY_SIZE_ARCMIN_RANGE)
        size_component = 1.0 - size_norm
        raw_score = _DIFFICULTY_WEIGHT_SIZE * size_component

    difficulty_score = int(round(min(100.0, max(0.0, raw_score * 100.0))))

    if difficulty_score <= 35:
        difficulty = 'beginner'
    elif difficulty_score <= 65:
        difficulty = 'intermediate'
    else:
        difficulty = 'advanced'

    return difficulty_score, difficulty


# ---------------------------------------------------------------------------
# Per-target result builder
# ---------------------------------------------------------------------------


def _compute_target_result(
    target: SkyTonightTarget,
    times: Any,
    altaz_values: np.ndarray,
    location: EarthLocation,
    moon: _MoonInfo,
    constraints: Dict[str, Any],
    night_start: datetime,
    night_end: datetime,
    lat: float,
    lon: float,
    *,
    az_values: Optional[np.ndarray] = None,
    lst_hours: Optional[np.ndarray] = None,
    times_local: Optional[List[datetime]] = None,
    preferred_name_order: Optional[List[str]] = None,
    sqm: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Return a computed result dict for one target, or None if not visible."""
    if target.coordinates is None:
        return None

    ra_hours = target.coordinates.ra_hours
    dec_degrees = target.coordinates.dec_degrees

    alt_min = float(constraints.get('altitude_constraint_min', 30))
    alt_max = float(constraints.get('altitude_constraint_max', 80))
    moon_sep_min = float(constraints.get('moon_separation_min', 45))
    size_min = float(constraints.get('size_constraint_min', 10))
    size_max = float(constraints.get('size_constraint_max', 300))
    frac_threshold = float(constraints.get('fraction_of_time_observable_threshold', 0.5))
    moon_use_illum = bool(constraints.get('moon_separation_use_illumination', True))
    north_to_east_ccw = bool(constraints.get('north_to_east_ccw', False))

    # Derive the effective altitude floor from the airmass constraint:
    # airmass = 1 / sin(altitude)  =>  altitude = arcsin(1 / airmass)
    # Use the stricter of the two limits.
    airmass_constr = float(constraints.get('airmass_constraint', 2.0))
    if airmass_constr >= 1.0:
        alt_from_airmass = math.degrees(math.asin(min(1.0, 1.0 / airmass_constr)))
        alt_min = max(alt_min, alt_from_airmass)

    # --- Size filter for DSOs ---
    if target.category == 'deep_sky' and target.size_arcmin is not None:
        if target.size_arcmin < size_min or target.size_arcmin > size_max:
            return None

    # --- Moon separation filter ---
    if moon.ra_deg is not None and moon.dec_deg is not None:
        ang_sep = _angular_separation_deg(
            ra_hours * 15.0,  # convert h to degrees
            dec_degrees,
            moon.ra_deg,
            moon.dec_deg,
        )
        # When moon_separation_use_illumination is enabled, the minimum
        # separation (in degrees) equals the moon illumination percentage:
        #   1% illumination = 1° minimum separation (overrides moon_sep_min).
        # At new moon (phase≈0) any target is accepted; at full moon (phase=1)
        # the threshold is 100°, providing a strong natural filter.
        effective_min_sep = moon_sep_min
        if moon_use_illum:
            effective_min_sep = moon.phase * 100.0
        if ang_sep < effective_min_sep:
            return None
        angular_distance_moon: Optional[float] = ang_sep
    else:
        angular_distance_moon = None

    # --- Altitude-based observable fraction ---
    total_steps = len(altaz_values)
    if total_steps < _MIN_STEPS:
        return None

    # Steps where target is within [alt_min, alt_max], respecting custom horizon profile
    horizon_profile: List[Dict[str, Any]] = constraints.get('horizon_profile', [])
    if horizon_profile and az_values is not None:
        horizon_floors = np.maximum(alt_min, _horizon_floor_array(az_values, horizon_profile))
        in_window_mask = (altaz_values >= horizon_floors) & (altaz_values <= alt_max)
    else:
        in_window_mask = (altaz_values >= alt_min) & (altaz_values <= alt_max)
    observable_steps = int(np.sum(in_window_mask))
    observable_fraction = observable_steps / total_steps

    # Compute observable hours early so both conditions can be tested together.
    # A target passes if it satisfies the fraction threshold OR is visible for
    # at least _MIN_OBSERVABLE_HOURS_DSO (e.g. spring objects that already
    # transited before dusk are only up for the first hour of a long night).
    night_hours = (night_end - night_start).total_seconds() / 3600.0
    observable_hours = night_hours * observable_fraction

    if observable_fraction < frac_threshold and observable_hours < _MIN_OBSERVABLE_HOURS_DSO:
        return None

    max_altitude = float(np.max(altaz_values))
    if max_altitude < alt_min:
        return None

    # Altitude at peak (meridian altitude approximation)
    peak_idx = int(np.argmax(altaz_values))
    meridian_altitude = float(altaz_values[peak_idx])

    # At the peak time, also record AZ
    peak_az_deg: Optional[float] = None
    try:
        if az_values is not None:
            az_cw = float(az_values[peak_idx])
        else:
            peak_time = times[peak_idx : peak_idx + 1]
            coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_degrees * u.deg, frame='icrs')
            frame = AltAz(obstime=peak_time, location=location)
            peak_altaz = coord.transform_to(frame)
            az_cw = float(peak_altaz.az.deg[0])  # type: ignore[index]
        peak_az_deg = round((360.0 - az_cw) % 360.0 if north_to_east_ccw else az_cw, 1)
    except Exception:
        pass  # astropy AltAz transform failed — peak_az_deg stays None

    # Find first/last observable indices using NumPy (avoids O(n) Python generator loops)
    obs_indices = np.nonzero(in_window_mask)[0]
    first_obs_idx: Optional[int] = int(obs_indices[0]) if len(obs_indices) > 0 else None
    last_obs_idx: Optional[int] = int(obs_indices[-1]) if len(obs_indices) > 0 else None

    if times_local is not None:
        window_start_hour = times_local[first_obs_idx].hour if first_obs_idx is not None else night_start.hour
        rise_time: Optional[str] = times_local[first_obs_idx].strftime('%H:%M') if first_obs_idx is not None else None
        set_time: Optional[str] = times_local[last_obs_idx].strftime('%H:%M') if last_obs_idx is not None else None
    else:
        if first_obs_idx is not None:
            _fot = night_start + timedelta(minutes=first_obs_idx * _TIME_RESOLUTION_MINUTES)
            window_start_hour = _fot.hour
        else:
            window_start_hour = night_start.hour
        rise_time = (
            (night_start + timedelta(minutes=first_obs_idx * _TIME_RESOLUTION_MINUTES)).strftime('%H:%M')
            if first_obs_idx is not None
            else None
        )
        set_time = (
            (night_start + timedelta(minutes=last_obs_idx * _TIME_RESOLUTION_MINUTES)).strftime('%H:%M')
            if last_obs_idx is not None
            else None
        )

    # Messier check
    is_messier = 'Messier' in (target.catalogue_names or {})

    # Meridian / antimeridian times
    if lst_hours is not None and times_local is not None:
        meridian_time = _meridian_transit_fast(ra_hours, lst_hours, times_local)
        antimeridian_time = _antimeridian_transit_fast(ra_hours, lst_hours, times_local)
    else:
        meridian_time = _meridian_transit_time(ra_hours, night_start, night_end, lat, lon)
        antimeridian_time = _antimeridian_transit_time(ra_hours, night_start, night_end, lat, lon)

    # RA/Dec in HMS/DMS
    ra_hms = _hours_to_hms(ra_hours)
    dec_dms = _degrees_to_dms(dec_degrees)

    astro_score = compute_astro_score(
        max_altitude=max_altitude,
        observable_hours=observable_hours,
        meridian_altitude=meridian_altitude,
        moon_phase=moon.phase,
        angular_distance_moon=angular_distance_moon,
        magnitude=target.magnitude,
        size_arcmin=target.size_arcmin,
        observable_hours_in_window=observable_hours,
        window_start_hour=window_start_hour,
        is_messier=is_messier,
        is_planet=(target.object_type or '').lower() == 'planet',
        is_opposition=False,
        sqm=sqm,
        object_type=target.object_type,
    )

    difficulty_score, difficulty = compute_difficulty_score(target)

    return {
        'target_id': target.target_id,
        'preferred_name': (
            (
                choose_preferred_catalogue_name(target.catalogue_names, order=preferred_name_order)
                or target.preferred_name
            )
            if preferred_name_order and target.catalogue_names
            else target.preferred_name
        ),
        'catalogue_names': target.catalogue_names,
        'category': target.category,
        'object_type': target.object_type,
        'constellation': target.constellation,
        'magnitude': target.magnitude,
        'size_arcmin': target.size_arcmin,
        'coordinates': {
            'ra_hours': ra_hours,
            'dec_degrees': dec_degrees,
        },
        'observation': {
            'max_altitude': round(max_altitude, 1),
            'azimuth': peak_az_deg,
            'observable_fraction': round(observable_fraction, 3),
            'observable_hours': round(observable_hours, 2),
            'meridian_transit': meridian_time,
            'antimeridian_transit': antimeridian_time,
            'rise_time': rise_time,
            'set_time': set_time,
            'ra_hms': ra_hms,
            'dec_dms': dec_dms,
        },
        'astro_score': astro_score,
        'difficulty_score': difficulty_score,
        'difficulty': difficulty,
        'moon_angular_distance': round(angular_distance_moon, 1) if angular_distance_moon is not None else None,
        'source_catalogues': target.source_catalogues,
        'metadata': target.metadata,
    }


def _compute_body_result(
    target: SkyTonightTarget,
    times: Any,
    location: EarthLocation,
    moon: _MoonInfo,
    constraints: Dict[str, Any],
    night_start: datetime,
    night_end: datetime,
    lat: float,
    lon: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[np.ndarray], Optional[np.ndarray]]:
    """Compute visibility for a solar system body using live ephemeris positions.

    Returns a tuple of (result_dict, alt_deg_array, az_deg_array).  All elements are None
    when the body is not observable tonight.  The alt_deg array is used by the
    caller to persist the altitude-time graph JSON for the frontend chart.

    Bodies do not have static coordinates - their positions are calculated from
    astropy's built-in ephemeris at each time step.  Constraints are relaxed
    compared to DSOs: no moon-separation filter (planets can be near the moon)
    and a lower observable-fraction threshold.
    """
    body_name = target.preferred_name
    try:
        alt_deg, az_deg, ra_hours, dec_degrees = _compute_body_altaz_series(body_name, times, location)
    except Exception as exc:
        logger.debug(f'Body AltAz computation failed for {body_name}: {exc}')
        return None, None, None

    alt_min = float(constraints.get('altitude_constraint_min', 30))
    north_to_east_ccw = bool(constraints.get('north_to_east_ccw', False))

    # The Moon is always included regardless of observability: its phase and
    # rise/set window affect every other target, so users need it even when
    # it is below the horizon all night (e.g. a new-moon night where the Moon
    # sets before nautical dusk).
    is_moon = (target.object_type or '').lower() == 'moon'

    # Bodies use their own minimum observable-fraction threshold that is
    # intentionally much lower than the DSO threshold: a planet visible for
    # even a short window during the night is worth showing.
    # We do NOT inherit fraction_of_time_observable_threshold from the DSO
    # constraints - showing e.g. Jupiter only for 2 h out of a 7 h night is
    # perfectly valid and the user explicitly wants to see those bodies.
    _BODIES_MIN_FRACTION = 0.05  # ~22 min for a 7 h night

    # Derive effective altitude floor from airmass constraint (stricter wins).
    airmass_constr = float(constraints.get('airmass_constraint', 2.0))
    if airmass_constr >= 1.0:
        alt_from_airmass = math.degrees(math.asin(min(1.0, 1.0 / airmass_constr)))
        alt_min = max(alt_min, alt_from_airmass)

    # Don't apply alt_max clamp for bodies - planets can reach high altitudes
    night_hours = (night_end - night_start).total_seconds() / 3600.0
    total_steps = len(alt_deg)
    if total_steps < _MIN_STEPS:
        return None, None, None

    horizon_profile_b: List[Dict[str, Any]] = constraints.get('horizon_profile', [])
    if horizon_profile_b:
        horizon_floors_b = np.maximum(alt_min, _horizon_floor_array(az_deg, horizon_profile_b))
        in_window_mask = alt_deg >= horizon_floors_b
    else:
        in_window_mask = alt_deg >= alt_min
    observable_steps = int(np.sum(in_window_mask))
    observable_fraction = observable_steps / total_steps

    if not is_moon and observable_fraction < _BODIES_MIN_FRACTION:
        return None, None, None

    max_altitude = float(np.max(alt_deg))

    peak_idx = int(np.argmax(alt_deg))
    meridian_altitude = float(alt_deg[peak_idx])
    az_cw = float(az_deg[peak_idx])
    peak_az_deg = round((360.0 - az_cw) % 360.0 if north_to_east_ccw else az_cw, 1)

    observable_hours = night_hours * observable_fraction

    obs_indices_b = np.nonzero(in_window_mask)[0]
    first_obs_idx = int(obs_indices_b[0]) if len(obs_indices_b) > 0 else None
    last_obs_idx_b = int(obs_indices_b[-1]) if len(obs_indices_b) > 0 else None

    window_start_hour = (
        (night_start + timedelta(minutes=first_obs_idx * _TIME_RESOLUTION_MINUTES)).hour
        if first_obs_idx is not None
        else night_start.hour
    )

    # Peak time during the night window
    max_altitude_time = (night_start + timedelta(minutes=peak_idx * _TIME_RESOLUTION_MINUTES)).strftime('%H:%M')

    # Rise / set times within the observable window
    rise_time_b = (
        (night_start + timedelta(minutes=first_obs_idx * _TIME_RESOLUTION_MINUTES)).strftime('%H:%M')
        if first_obs_idx is not None
        else None
    )
    set_time_b = (
        (night_start + timedelta(minutes=last_obs_idx_b * _TIME_RESOLUTION_MINUTES)).strftime('%H:%M')
        if last_obs_idx_b is not None
        else None
    )

    # Moon angular separation (informational only for bodies, not a filter)
    angular_distance_moon: Optional[float] = None
    if moon.ra_deg is not None and moon.dec_deg is not None:
        ang_sep = _angular_separation_deg(ra_hours * 15.0, dec_degrees, moon.ra_deg, moon.dec_deg)
        angular_distance_moon = ang_sep

    # Solar elongation - angular separation between this body and the Sun at night midpoint.
    # Used to detect opposition (+0.20 AstroScore bonus) and to flag inner planets in solar glare.
    solar_elongation_deg: Optional[float] = None
    is_opposition = False
    try:
        mid_idx_b = len(times) // 2
        sun_coord = get_body('sun', times[mid_idx_b], location)
        solar_elongation_deg = round(
            _angular_separation_deg(
                ra_hours * 15.0,
                dec_degrees,
                float(sun_coord.ra.deg),  # type: ignore[attr-defined]
                float(sun_coord.dec.deg),  # type: ignore[attr-defined]
            ),
            1,
        )
        is_opposition = (target.object_type or '').lower() == 'planet' and solar_elongation_deg > 160.0
    except Exception as exc:
        logger.debug(f'Solar elongation computation failed for {body_name}: {exc}')

    meridian_time = _meridian_transit_time(ra_hours, night_start, night_end, lat, lon)
    antimeridian_time = _antimeridian_transit_time(ra_hours, night_start, night_end, lat, lon)
    ra_hms = _hours_to_hms(ra_hours)
    dec_dms = _degrees_to_dms(dec_degrees)

    astro_score = compute_astro_score(
        max_altitude=max_altitude,
        observable_hours=observable_hours,
        meridian_altitude=meridian_altitude,
        moon_phase=moon.phase,
        angular_distance_moon=angular_distance_moon,
        magnitude=target.magnitude,
        size_arcmin=None,
        observable_hours_in_window=observable_hours,
        window_start_hour=window_start_hour,
        is_messier=False,
        is_planet=(target.object_type or '').lower() == 'planet',
        is_opposition=is_opposition,
    )

    return (
        {
            'target_id': target.target_id,
            'preferred_name': target.preferred_name,
            'catalogue_names': target.catalogue_names,
            'category': target.category,
            'object_type': target.object_type,
            'constellation': '',
            'magnitude': target.magnitude,
            'size_arcmin': None,
            'coordinates': {'ra_hours': round(ra_hours, 6), 'dec_degrees': round(dec_degrees, 6)},
            'observation': {
                'max_altitude': round(max_altitude, 1),
                'azimuth': peak_az_deg,
                'observable_fraction': round(observable_fraction, 3),
                'observable_hours': round(observable_hours, 2),
                'meridian_transit': meridian_time,
                'antimeridian_transit': antimeridian_time,
                'max_altitude_time': max_altitude_time,
                'rise_time': rise_time_b,
                'set_time': set_time_b,
                'ra_hms': ra_hms,
                'dec_dms': dec_dms,
            },
            'astro_score': astro_score,
            'solar_elongation_deg': solar_elongation_deg,
            'moon_angular_distance': round(angular_distance_moon, 1) if angular_distance_moon is not None else None,
            'lunar_phase': round(moon.phase, 4) if is_moon else None,
            'source_catalogues': target.source_catalogues,
            'metadata': target.metadata,
        },
        alt_deg,
        az_deg,
    )


def _hours_to_hms(hours: float) -> str:
    total_seconds = hours * 3600.0
    h = int(total_seconds // 3600)
    remaining = total_seconds - h * 3600
    m = int(remaining // 60)
    s = remaining - m * 60
    return f'{h:02d}h {m:02d}m {s:05.2f}s'


def _degrees_to_dms(degrees: float) -> str:
    sign = '' if degrees >= 0 else '-'
    d = abs(degrees)
    d_int = int(d)
    remaining = (d - d_int) * 60
    m_int = int(remaining)
    s = (remaining - m_int) * 60
    return f'{sign}{d_int:02d}° {m_int:02d}\' {s:05.2f}"'


def _cleanup_calculation_memory(
    *,
    deep_sky_results: List[Dict[str, Any]],
    bodies_results: List[Dict[str, Any]],
    comets_results: List[Dict[str, Any]],
    skymap_entries: List[Dict[str, Any]],
    all_targets: List[SkyTonightTarget],
    dso_targets_with_coords: List[SkyTonightTarget],
    times_iso_list: Optional[List[str]],
    times_local: Optional[List[datetime]],
) -> None:
    """Release large per-run containers before returning from the calculation cycle."""
    deep_sky_results.clear()
    bodies_results.clear()
    comets_results.clear()
    skymap_entries.clear()
    all_targets.clear()
    dso_targets_with_coords.clear()
    if times_iso_list is not None:
        times_iso_list.clear()
    if times_local is not None:
        times_local.clear()
    gc.collect()


# ---------------------------------------------------------------------------
# Main calculation runner
# ---------------------------------------------------------------------------


def run_calculations(
    config: Optional[Dict[str, Any]] = None,
    location: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute observability and AstroScore for all visible targets.

    Writes the per-location result files (see skytonight_storage helpers).

    Parameters
    ----------
    config:
        Merged application config dict.  If *None*, it is loaded internally.
    location:
        Location preset dict to compute for.  If *None*, the install default
        preset is used (the scheduler calls this once per scheduler location).

    Returns
    -------
    dict
        Summary with metadata and per-category counts.
    """
    ensure_skytonight_directories()

    if config is None:
        config = load_config()

    if not isinstance(location, dict) or not location:
        from utils.repo_config import get_install_default_location

        location = get_install_default_location(config) if isinstance(config, dict) else {}
    location_id = location.get('id')

    # Per-location result files (v1.2): each preset keeps its own night table.
    results_file = get_results_file(location_id)
    dso_results_file = get_dso_results_file(location_id)
    bodies_results_file = get_bodies_results_file(location_id)
    comets_results_file = get_comets_results_file(location_id)
    skymap_file = get_skymap_file(location_id)

    lat = float(location.get('latitude') or 0.0)
    lon = float(location.get('longitude') or 0.0)
    elevation = float(location.get('elevation') or 0.0)
    timezone_name = str(location.get('timezone') or 'UTC')
    location_name = str(location.get('name') or 'default-location')

    # Derive effective SQM for light-pollution weighting.
    # User-measured SQM takes priority; otherwise derive from Bortle midpoint.
    # If neither is configured, sqm stays None and LP weighting is disabled.
    _sqm_for_run: Optional[float] = None
    _raw_sqm = location.get('sqm')
    _raw_bortle = location.get('bortle')
    if _raw_sqm is not None:
        try:
            _sqm_for_run = float(_raw_sqm)
        except (TypeError, ValueError):
            pass  # malformed config value — _sqm_for_run stays None
    elif _raw_bortle is not None:
        try:
            from weather.sky_quality import bortle_to_sqm as _bortle_to_sqm

            _sqm_for_run = _bortle_to_sqm(int(_raw_bortle))
        except (TypeError, ValueError):
            pass  # malformed config value — _sqm_for_run stays None

    skytonight_cfg = config.get('skytonight', {}) if isinstance(config, dict) else {}
    constraints: Dict[str, Any] = dict(skytonight_cfg.get('constraints', {}))
    # horizon_profile lives on the location preset since v1.2 - inject it into
    # the constraints dict so the internal observability helpers stay unchanged.
    constraints['horizon_profile'] = location.get('horizon_profile') or []

    # User-configured catalogue name order: applied at result time to override the
    # dataset's build-time preferred_name so the display matches user preference.
    _raw_name_order = skytonight_cfg.get('preferred_name_order')
    preferred_name_order: Optional[List[str]] = (
        [str(x) for x in _raw_name_order if x] if isinstance(_raw_name_order, list) and _raw_name_order else None
    )

    logger.info(f'SkyTonight calculations starting for location: {location_name}')
    _set_progress('night_window')

    # Mark RESULTS_FILE as in-progress immediately so that:
    # - has_calculation_results() returns False while the run is executing,
    #   preventing the scheduler from treating stale results as complete on
    #   restart;
    # - if this run crashes before the final write, the flag stays True and
    #   the next startup correctly triggers a fresh calculation.
    save_json_file(
        results_file,
        {
            'metadata': {
                'calculated_at': datetime.now(timezone.utc).isoformat(),
                'location_id': location_id,
                'location_name': location_name,
                'in_progress': True,
            }
        },
    )

    # --- Determine nautical and astronomical night windows ---
    night_window = _get_night_window(lat, lon, timezone_name)
    if night_window is None:
        logger.warning('No nautical night found for tonight; SkyTonight calculations skipped.')
        _empty_meta = {
            'calculated_at': datetime.now(timezone.utc).isoformat(),
            'location_id': location_id,
            'location_name': location_name,
            'latitude': lat,
            'longitude': lon,
            'elevation': elevation,
            'timezone': timezone_name,
            'night_basis': 'nautical',
            'night_found': False,
            'night_start': None,
            'night_end': None,
            'night_hours': 0.0,
            'moon_phase': 0.0,
            'counts': {'deep_sky': 0, 'bodies': 0, 'comets': 0},
        }
        save_json_file(bodies_results_file, {'metadata': _empty_meta, 'bodies': []})
        save_json_file(comets_results_file, {'metadata': _empty_meta, 'comets': []})
        save_json_file(dso_results_file, {'metadata': _empty_meta, 'deep_sky': []})
        save_json_file(results_file, {'metadata': _empty_meta})
        return {'counts': {'deep_sky': 0, 'bodies': 0, 'comets': 0}, 'night_found': False}

    night_start, night_end = night_window
    night_hours = (night_end - night_start).total_seconds() / 3600.0

    astro_window = _get_astro_night_window(lat, lon, timezone_name)
    astro_night_start = astro_window[0] if astro_window else None
    astro_night_end = astro_window[1] if astro_window else None

    logger.info(
        f'Night window: {night_start.strftime("%Y-%m-%d %H:%M %Z")} → '
        f'{night_end.strftime("%Y-%m-%d %H:%M %Z")} ({night_hours:.1f}h)'
    )
    _set_progress('loading_dataset')
    # --- Load targets dataset ---
    dataset = load_targets_dataset()
    all_targets: List[SkyTonightTarget] = []
    for raw in dataset.get('targets', []):
        if isinstance(raw, SkyTonightTarget):
            all_targets.append(raw)
        elif isinstance(raw, dict):
            try:
                from skytonight.skytonight_models import SkyTonightTarget as ST

                all_targets.append(ST.from_dict(raw))
            except Exception:
                pass  # malformed target dict — skip this entry

    if not all_targets:
        logger.warning('SkyTonight dataset is empty; no calculations to perform.')

    # Pre-count targets by category for progress reporting
    n_bodies = sum(1 for t in all_targets if t.category == 'bodies')
    n_deep_sky = sum(1 for t in all_targets if t.category == 'deep_sky')
    n_comets = sum(1 for t in all_targets if t.category == 'comets')
    logger.info(f'Targets to process: {n_deep_sky} DSOs, {n_bodies} bodies, {n_comets} comets')
    _set_progress('moon_init')

    # --- Shared resources ---
    location_obj = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elevation * u.m)
    times = _sample_times(night_start, night_end)
    moon = _MoonInfo(times, location_obj)

    logger.info(
        f'Moon phase: {moon.phase:.2f} ' f'(RA={moon.ra_deg:.1f}°, Dec={moon.dec_deg:.1f}°)'
        if moon.ra_deg is not None
        else f'Moon phase: {moon.phase:.2f}'
    )

    # --- Compute per-target results ---
    deep_sky_results: List[Dict[str, Any]] = []
    bodies_results: List[Dict[str, Any]] = []
    comets_results: List[Dict[str, Any]] = []

    processed_deep_sky = 0
    processed_bodies = 0
    processed_comets = 0
    skymap_entries: List[Dict[str, Any]] = []  # accumulates trajectory data for sky map
    # Clear altitude-time JSON files from the previous calculation run so stale
    # files are never served after a recalculation for a different night.
    _clear_alttime_files(location_id)

    # -----------------------------------------------------------------------
    # Phase 1: Bodies (planets, Moon) - live ephemeris, fast, save immediately
    # -----------------------------------------------------------------------
    _set_progress('bodies', 0, n_bodies)
    for target in all_targets:
        if target.category != 'bodies':
            continue
        body_result, body_alt_deg, body_az_deg = _compute_body_result(
            target=target,
            times=times,
            location=location_obj,
            moon=moon,
            constraints=constraints,
            night_start=night_start,
            night_end=night_end,
            lat=lat,
            lon=lon,
        )
        if body_result is not None:
            bodies_results.append(body_result)
            if body_alt_deg is not None and body_az_deg is not None:
                skymap_entries.append(
                    {
                        'id': target.target_id,
                        'name': body_result.get('preferred_name', target.target_id),
                        'type': body_result.get('object_type', 'body'),
                        'category': 'bodies',
                        'score': body_result.get('astro_score', 0),
                        'constellation': body_result.get('constellation', ''),
                        'alt': [round(float(v), 1) for v in body_alt_deg[::2]],
                        'az': [round(float(v), 1) for v in body_az_deg[::2]],
                    }
                )
            if body_alt_deg is not None:
                _save_alttime_json(
                    target_id=target.target_id,
                    name=body_result.get('preferred_name', target.target_id),
                    times=times,
                    altitudes=body_alt_deg,
                    night_start=night_start,
                    night_end=night_end,
                    constraints=constraints,
                    timezone_name=timezone_name,
                    az_degrees=body_az_deg,
                    astro_night_start=astro_night_start,
                    astro_night_end=astro_night_end,
                    location_id=location_id,
                )
        processed_bodies += 1
        _set_progress('bodies', processed_bodies, n_bodies)

    # Immediate partial save: bodies are available in the frontend while comets/DSOs compute
    logger.debug(f'Bodies done: {len(bodies_results)} visible. Writing bodies results...')
    save_json_file(
        bodies_results_file,
        {
            'metadata': {
                'calculated_at': datetime.now(timezone.utc).isoformat(),
                'location_id': location_id,
                'location_name': location_name,
                'latitude': lat,
                'longitude': lon,
                'elevation': elevation,
                'timezone': timezone_name,
                'night_start': night_start.isoformat(),
                'night_end': night_end.isoformat(),
                'night_hours': round(night_hours, 2),
                'moon_phase': round(moon.phase, 4),
                'in_progress': True,
            },
            'bodies': bodies_results,
        },
    )

    # -----------------------------------------------------------------------
    # Phase 2: Comets - individually (typically few targets)
    # -----------------------------------------------------------------------
    _set_progress('comets', 0, n_comets)
    for target in all_targets:
        if target.category != 'comets':
            continue
        if target.coordinates is None:
            continue
        try:
            altaz_values, az_values_comet = _compute_altaz_series(
                ra_hours=target.coordinates.ra_hours,
                dec_degrees=target.coordinates.dec_degrees,
                times=times,
                location=location_obj,
            )
        except Exception as exc:
            logger.debug(f'Comet AltAz computation failed for {target.target_id}: {exc}')
            continue
        result = _compute_target_result(
            target=target,
            times=times,
            altaz_values=altaz_values,
            location=location_obj,
            moon=moon,
            constraints=constraints,
            night_start=night_start,
            night_end=night_end,
            lat=lat,
            lon=lon,
            az_values=az_values_comet,
            preferred_name_order=preferred_name_order,
            sqm=_sqm_for_run,
        )
        if result is not None:
            comets_results.append(result)
            skymap_entries.append(
                {
                    'id': target.target_id,
                    'name': result.get('preferred_name', target.target_id),
                    'type': 'comet',
                    'category': 'comets',
                    'score': result.get('astro_score', 0),
                    'constellation': result.get('constellation', ''),
                    'alt': [round(float(v), 1) for v in altaz_values[::2]],
                    'az': [round(float(v), 1) for v in az_values_comet[::2]],
                }
            )
            _save_alttime_json(
                target_id=target.target_id,
                name=result.get('preferred_name', target.target_id),
                times=times,
                altitudes=altaz_values,
                night_start=night_start,
                night_end=night_end,
                constraints=constraints,
                timezone_name=timezone_name,
                az_degrees=az_values_comet,
                astro_night_start=astro_night_start,
                astro_night_end=astro_night_end,
                location_id=location_id,
            )
        processed_comets += 1
        _set_progress('comets', processed_comets, n_comets)

    # Partial save: comets are now available while DSOs compute
    logger.debug(f'Comets done: {len(comets_results)} visible. Writing comets results...')
    save_json_file(
        comets_results_file,
        {
            'metadata': {
                'calculated_at': datetime.now(timezone.utc).isoformat(),
                'location_id': location_id,
                'location_name': location_name,
                'latitude': lat,
                'longitude': lon,
                'elevation': elevation,
                'timezone': timezone_name,
                'night_start': night_start.isoformat(),
                'night_end': night_end.isoformat(),
                'night_hours': round(night_hours, 2),
                'moon_phase': round(moon.phase, 4),
                'in_progress': True,
            },
            'comets': comets_results,
        },
    )

    # -----------------------------------------------------------------------
    # Phase 3: Deep-sky objects - batched AltAz (vectorized over all targets per time step)
    # -----------------------------------------------------------------------
    dso_targets_with_coords = [t for t in all_targets if t.category == 'deep_sky' and t.coordinates is not None]
    n_dso_batch = len(dso_targets_with_coords)
    _set_progress('deep_sky', 0, n_dso_batch)

    alt_matrix: Optional[np.ndarray] = None
    az_matrix: Optional[np.ndarray] = None
    all_dso_coords: Optional[SkyCoord] = None
    lst_hours_arr: Optional[np.ndarray] = None
    times_iso_list: Optional[List[str]] = None
    times_local: Optional[List[datetime]] = None

    if n_dso_batch > 0:
        n_steps = len(times)
        total_night_min = (night_end - night_start).total_seconds() / 60.0
        step_minutes = total_night_min / (n_steps - 1) if n_steps > 1 else 0.0

        # Local datetime objects for %H:%M display (rise/set/transit times)
        times_local = [night_start + timedelta(minutes=i * step_minutes) for i in range(n_steps)]

        # LST array - computed once for all ~33 steps, replaces 13 000+ × 33 sidereal_time() calls
        lst_hours_arr = np.array(times.sidereal_time('apparent', longitude=location_obj.lon).hour)

        # ISO strings computed once - reused for every alttime JSON write
        times_iso_list = [t.strftime('%Y-%m-%dT%H:%M:%S') for t in times.to_datetime(timezone=timezone.utc)]

        # Build a single SkyCoord array for all DSO targets
        # coordinates is guaranteed non-None by the dso_targets_with_coords filter above
        all_ra_h = np.array([t.coordinates.ra_hours for t in dso_targets_with_coords])  # type: ignore[union-attr]
        all_dec_d = np.array([t.coordinates.dec_degrees for t in dso_targets_with_coords])  # type: ignore[union-attr]
        all_dso_coords = SkyCoord(ra=all_ra_h * u.hourangle, dec=all_dec_d * u.deg, frame='icrs')

        # Batch AltAz: n_steps vectorised calls instead of n_dso_batch individual calls.
        # Each call transforms all DSO targets at once for one time step.
        alt_matrix = np.empty((n_dso_batch, n_steps), dtype=np.float32)
        az_matrix = np.empty((n_dso_batch, n_steps), dtype=np.float32)

        logger.info(f'Computing batch AltAz for {n_dso_batch} DSO targets ' f'over {n_steps} time steps...')
        _set_progress('deep_sky_altaz', 0, n_steps)
        for step_i in range(n_steps):
            frame = AltAz(obstime=times[step_i], location=location_obj)
            altaz_batch: SkyCoord = all_dso_coords.transform_to(frame)  # type: ignore[assignment]
            alt_matrix[:, step_i] = altaz_batch.alt.deg  # type: ignore[index]
            az_matrix[:, step_i] = altaz_batch.az.deg  # type: ignore[index]
            _set_progress('deep_sky_altaz', step_i + 1, n_steps)
        logger.info('Batch AltAz computation complete.')

        # Per-target scoring; alttime files written in background threads
        _set_progress('deep_sky', 0, n_dso_batch)
        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as alttime_pool:
            for idx, target in enumerate(dso_targets_with_coords):
                result = _compute_target_result(
                    target=target,
                    times=times,
                    altaz_values=alt_matrix[idx],
                    location=location_obj,
                    moon=moon,
                    constraints=constraints,
                    night_start=night_start,
                    night_end=night_end,
                    lat=lat,
                    lon=lon,
                    az_values=az_matrix[idx],
                    lst_hours=lst_hours_arr,
                    times_local=times_local,
                    preferred_name_order=preferred_name_order,
                    sqm=_sqm_for_run,
                )
                if result is not None:
                    deep_sky_results.append(result)
                    skymap_entries.append(
                        {
                            'id': target.target_id,
                            'name': result.get('preferred_name', target.target_id),
                            'type': result.get('object_type', 'dso'),
                            'category': 'deep_sky',
                            'score': result.get('astro_score', 0),
                            'constellation': result.get('constellation', ''),
                            'messier': bool('Messier' in (target.catalogue_names or {})),
                            'alt': [round(float(v), 1) for v in alt_matrix[idx][::2]],
                            'az': [round(float(v), 1) for v in az_matrix[idx][::2]],
                        }
                    )
                    alttime_pool.submit(
                        _save_alttime_json,
                        target.target_id,
                        result.get('preferred_name', target.target_id),
                        times,
                        alt_matrix[idx],
                        night_start,
                        night_end,
                        constraints,
                        timezone_name,
                        times_iso_list,
                        az_matrix[idx],
                        astro_night_start,
                        astro_night_end,
                        location_id=location_id,
                    )
                processed_deep_sky += 1
                if processed_deep_sky % _DSO_LOG_INTERVAL == 0:
                    logger.debug(f'SkyTonight progress: DSO {processed_deep_sky}/{n_dso_batch}')
                _set_progress('deep_sky', processed_deep_sky, n_dso_batch)

    # Sort by AstroScore descending
    _set_progress('saving')
    deep_sky_results.sort(key=lambda r: r['astro_score'], reverse=True)
    bodies_results.sort(key=lambda r: r['astro_score'], reverse=True)
    comets_results.sort(key=lambda r: r['astro_score'], reverse=True)

    counts = {
        'deep_sky': len(deep_sky_results),
        'bodies': len(bodies_results),
        'comets': len(comets_results),
    }

    _final_meta = {
        'calculated_at': datetime.now(timezone.utc).isoformat(),
        'location_id': location_id,
        'location_name': location_name,
        'latitude': lat,
        'longitude': lon,
        'elevation': elevation,
        'timezone': timezone_name,
        'night_basis': 'nautical',
        'night_found': True,
        'night_start': night_start.isoformat(),
        'night_end': night_end.isoformat(),
        'night_hours': round(night_hours, 2),
        'moon_phase': round(moon.phase, 4),
        'counts': counts,
        'constraints': constraints,
        'in_progress': False,
    }

    # Write each category to its own file (final, sorted, in_progress=False)
    save_json_file(bodies_results_file, {'metadata': _final_meta, 'bodies': bodies_results})
    save_json_file(comets_results_file, {'metadata': _final_meta, 'comets': comets_results})
    save_json_file(dso_results_file, {'metadata': _final_meta, 'deep_sky': deep_sky_results})
    # Metadata-only summary - signals that all calculations are complete
    save_json_file(results_file, {'metadata': _final_meta})

    # Write skymap trajectory data sorted by AstroScore descending, numbered 1..N
    skymap_entries.sort(key=lambda e: e['score'], reverse=True)
    for rank, entry in enumerate(skymap_entries, start=1):
        entry['n'] = rank
    save_json_file(skymap_file, {'targets': skymap_entries})

    _calculation_progress.clear()

    logger.info(
        f'SkyTonight calculations done for {location_name}: '
        f'{counts["deep_sky"]} DSOs, {counts["bodies"]} bodies, {counts["comets"]} comets.'
    )

    _cleanup_calculation_memory(
        deep_sky_results=deep_sky_results,
        bodies_results=bodies_results,
        comets_results=comets_results,
        skymap_entries=skymap_entries,
        all_targets=all_targets,
        dso_targets_with_coords=dso_targets_with_coords,
        times_iso_list=times_iso_list,
        times_local=times_local,
    )

    return {
        'counts': counts,
        'night_found': True,
        'night_start': night_start.isoformat(),
        'night_end': night_end.isoformat(),
    }


def load_calculation_results(location_id: Optional[str] = None) -> Dict[str, Any]:
    """Load and combine a location's latest SkyTonight calculation results.

    *location_id* of None resolves to the install default preset.
    """
    meta_file = load_json_file(get_results_file(location_id), default={})
    dso_file = load_json_file(get_dso_results_file(location_id), default={})
    bodies_file = load_json_file(get_bodies_results_file(location_id), default={})
    comets_file = load_json_file(get_comets_results_file(location_id), default={})

    # Prefer metadata from the summary file; fall back to whichever data file has it
    metadata = (
        meta_file.get('metadata')
        or dso_file.get('metadata')
        or bodies_file.get('metadata')
        or comets_file.get('metadata')
        or {}
    )
    return {
        'metadata': metadata,
        'deep_sky': dso_file.get('deep_sky', []),
        'bodies': bodies_file.get('bodies', []),
        'comets': comets_file.get('comets', []),
    }


# ---------------------------------------------------------------------------
# Per-target debug diagnostics
# ---------------------------------------------------------------------------

_body_alias_map_cache: Optional[Dict[str, str]] = None


def _build_body_alias_map() -> Dict[str, str]:
    """Build a reverse map: normalized localized body name → canonical English body name.

    Reads the 'planets' i18n namespace from every supported language so that
    any translated name (e.g. 'Lune', 'Saturne') resolves to the English name
    used in the dataset (e.g. 'Moon', 'Saturn').
    """
    from utils.i18n_utils import I18nManager, SUPPORTED_LANGUAGES

    result: Dict[str, str] = {}
    for lang in SUPPORTED_LANGUAGES:
        try:
            ns = I18nManager(lang).get_namespace('planets')
            for key, localized_name in ns.items():
                if not isinstance(localized_name, str) or not localized_name.strip():
                    continue
                # i18n key is lowercase English (e.g. 'moon') → canonical 'Moon'
                canonical = key.capitalize()
                norm = normalize_object_name(localized_name)
                if norm:
                    result[norm] = canonical
        except Exception:
            pass  # i18n translation unavailable for this locale — skip section
    return result


def _find_body_entry_by_localized_name(
    name_norm: str,
    lookup: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return a lookup entry by matching a localized body name via the i18n map."""
    global _body_alias_map_cache
    if _body_alias_map_cache is None:
        _body_alias_map_cache = _build_body_alias_map()
    canonical = _body_alias_map_cache.get(name_norm)
    if not canonical:
        return None
    english_norm = normalize_object_name(canonical)
    return lookup.get(f'alias::{english_norm}') or lookup.get(f'preferred::{english_norm}')


def compute_target_debug(
    name: str,
    config: Optional[Dict[str, Any]] = None,
    location: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute detailed constraint diagnostics for a single target by name.

    Returns a structured dict describing which SkyTonight constraints the target
    passes or fails tonight, plus altitude-time data for the frontend chart.
    This powers the 'DSO not found?' debug tab.

    *location* is the preset to diagnose against (the API passes the requesting
    user's active location so diagnostics match the results they are viewing);
    None falls back to the install default preset.
    """
    if config is None:
        config = load_config()

    location_cfg = location
    if not isinstance(location_cfg, dict) or not location_cfg:
        from utils.repo_config import get_install_default_location

        location_cfg = get_install_default_location(config) if isinstance(config, dict) else {}
    lat = float(location_cfg.get('latitude') or 0.0)
    lon = float(location_cfg.get('longitude') or 0.0)
    elevation = float(location_cfg.get('elevation') or 0.0)
    timezone_name = str(location_cfg.get('timezone') or 'UTC')

    skytonight_cfg = config.get('skytonight', {}) if isinstance(config, dict) else {}
    constraints: Dict[str, Any] = dict(skytonight_cfg.get('constraints', {}))
    constraints['horizon_profile'] = location_cfg.get('horizon_profile') or []
    _raw_name_order = skytonight_cfg.get('preferred_name_order')
    preferred_name_order: Optional[List[str]] = (
        [str(x) for x in _raw_name_order if x] if isinstance(_raw_name_order, list) and _raw_name_order else None
    )

    # --- Look up target by name ---
    dataset = load_targets_dataset()
    lookup: Dict[str, Any] = dataset.get('lookup', {})
    all_targets: List[SkyTonightTarget] = dataset.get('targets', [])

    name_norm = normalize_object_name(name)
    entry: Optional[Dict[str, Any]] = lookup.get(f'alias::{name_norm}') or lookup.get(f'preferred::{name_norm}')
    if not entry:
        for key, val in lookup.items():
            if '::' in key and key.split('::', 1)[1] == name_norm:
                entry = val
                break

    # Fallback: check whether the search term is a localized body name in any
    # supported language.  The 'planets' i18n namespace maps English keys
    # (e.g. 'moon') to translated names (e.g. 'Lune', 'Luna').  We invert that
    # map so that any localized name routes to the canonical English body name.
    if not entry:
        entry = _find_body_entry_by_localized_name(name_norm, lookup)

    if not entry:
        return {'found': False}

    target_id = str(entry.get('target_id') or entry.get('group_id') or '')
    target: Optional[SkyTonightTarget] = next((t for t in all_targets if t.target_id == target_id), None)
    if target is None:
        return {'found': False}

    # --- Constraint values ---
    alt_min = float(constraints.get('altitude_constraint_min', 30))
    alt_max = float(constraints.get('altitude_constraint_max', 80))
    airmass = float(constraints.get('airmass_constraint', 2.0))
    size_min = float(constraints.get('size_constraint_min', 10))
    size_max = float(constraints.get('size_constraint_max', 300))
    moon_sep_min = float(constraints.get('moon_separation_min', 45))
    frac_threshold = float(constraints.get('fraction_of_time_observable_threshold', 0.5))
    moon_use_illum = bool(constraints.get('moon_separation_use_illumination', True))
    horizon_profile: List[Dict[str, Any]] = constraints.get('horizon_profile', [])

    # Effective altitude floor: stricter of alt_min vs airmass-derived
    effective_alt_min = alt_min
    if airmass >= 1.0:
        alt_from_airmass = math.degrees(math.asin(min(1.0, 1.0 / airmass)))
        effective_alt_min = max(alt_min, alt_from_airmass)

    constraints_summary = {
        'altitude_constraint_min': alt_min,
        'altitude_constraint_max': alt_max,
        'airmass_constraint': airmass,
        'effective_alt_min': round(effective_alt_min, 1),
        'size_constraint_min': size_min,
        'size_constraint_max': size_max,
        'moon_separation_min': moon_sep_min,
        'moon_separation_use_illumination': moon_use_illum,
        'fraction_of_time_observable_threshold': frac_threshold,
        'horizon_active': bool(horizon_profile),
    }

    # Resolve preferred display name
    display_name = (
        choose_preferred_catalogue_name(target.catalogue_names, order=preferred_name_order)
        if preferred_name_order and target.catalogue_names
        else target.preferred_name
    )

    target_info = {
        'target_id': target.target_id,
        'preferred_name': display_name or target.preferred_name,
        'catalogue_names': target.catalogue_names,
        'object_type': target.object_type,
        'category': target.category,
        'constellation': target.constellation,
        'magnitude': target.magnitude,
        'size_arcmin': target.size_arcmin,
        'coordinates': (
            {'ra_hours': target.coordinates.ra_hours, 'dec_degrees': target.coordinates.dec_degrees}
            if target.coordinates
            else None
        ),
    }

    # Bodies have no static coordinates (computed live from ephemeris) - skip coordinates check.
    # For non-body targets, missing coordinates means we cannot compute anything.
    is_body = target.category == 'bodies'
    is_moon = is_body and (target.object_type or '').lower() == 'moon'
    if not is_body and target.coordinates is None:
        return {
            'found': True,
            'target': target_info,
            'night_window': None,
            'moon': None,
            'alttime': None,
            'constraints': constraints_summary,
            'checks': [{'name': 'coordinates', 'passed': False, 'note': 'Target has no coordinates'}],
            'overall': 'no_coordinates',
        }

    # Placeholder; will be overwritten by _compute_body_altaz_series for bodies.
    ra_hours: float = target.coordinates.ra_hours if target.coordinates else 0.0
    dec_degrees: float = target.coordinates.dec_degrees if target.coordinates else 0.0

    # --- Night window ---
    night_window = _get_night_window(lat, lon, timezone_name)
    astro_window = _get_astro_night_window(lat, lon, timezone_name)

    if night_window is None:
        return {
            'found': True,
            'target': target_info,
            'night_window': {'available': False},
            'moon': None,
            'alttime': None,
            'constraints': constraints_summary,
            'checks': [{'name': 'night_window', 'passed': False}],
            'overall': 'no_night',
        }

    night_start, night_end = night_window
    night_hours = (night_end - night_start).total_seconds() / 3600.0
    astro_night_start = astro_window[0] if astro_window else None
    astro_night_end = astro_window[1] if astro_window else None

    # --- Compute altaz series ---
    location_obj = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elevation * u.m)
    times = _sample_times(night_start, night_end)
    moon = _MoonInfo(times, location_obj)

    try:
        if is_body:
            alt_deg, az_deg, ra_hours, dec_degrees = _compute_body_altaz_series(
                target.preferred_name, times, location_obj
            )
        else:
            alt_deg, az_deg = _compute_altaz_series(ra_hours, dec_degrees, times, location_obj)
    except Exception as exc:
        logger.debug(f'compute_target_debug: altaz computation failed for {target.target_id}: {exc}')
        return {
            'found': True,
            'target': target_info,
            'night_window': {
                'available': True,
                'night_start': night_start.isoformat(),
                'night_end': night_end.isoformat(),
                'night_hours': round(night_hours, 2),
            },
            'moon': None,
            'alttime': None,
            'constraints': constraints_summary,
            'checks': [{'name': 'altaz_computation', 'passed': False, 'note': 'Failed to compute altitude data'}],
            'overall': 'error',
        }

    times_iso = [t.strftime('%Y-%m-%dT%H:%M:%S') for t in times.to_datetime(timezone=timezone.utc)]

    # --- Run constraint checks ---
    checks: List[Dict[str, Any]] = []
    overall = 'visible'

    # Size filter (DSOs and comets only, skip bodies)
    if target.category == 'deep_sky':
        if target.size_arcmin is not None:
            size_min_ok = target.size_arcmin >= size_min
            size_max_ok = target.size_arcmin <= size_max
            checks.append(
                {
                    'name': 'size_min',
                    'passed': size_min_ok,
                    'value': target.size_arcmin,
                    'threshold': size_min,
                    'unit': 'arcmin',
                }
            )
            checks.append(
                {
                    'name': 'size_max',
                    'passed': size_max_ok,
                    'value': target.size_arcmin,
                    'threshold': size_max,
                    'unit': 'arcmin',
                }
            )
            if not (size_min_ok and size_max_ok):
                overall = 'filtered'
        else:
            checks.append({'name': 'size_min', 'passed': True, 'note': 'No size data, filter skipped'})
            checks.append({'name': 'size_max', 'passed': True, 'note': 'No size data, filter skipped'})

    # Moon separation (DSOs and comets only)
    effective_min_sep = moon_sep_min
    if not is_body and moon.ra_deg is not None and moon.dec_deg is not None:
        ang_sep = _angular_separation_deg(ra_hours * 15.0, dec_degrees, moon.ra_deg, moon.dec_deg)
        if moon_use_illum:
            effective_min_sep = moon.phase * 100.0
        moon_ok = ang_sep >= effective_min_sep
        checks.append(
            {
                'name': 'moon_separation',
                'passed': moon_ok,
                'value': round(ang_sep, 1),
                'threshold': round(effective_min_sep, 1),
                'unit': '°',
                'moon_phase': round(moon.phase, 3),
                'moon_phase_pct': round(moon.phase * 100.0, 1),
            }
        )
        if not moon_ok:
            overall = 'filtered'

    # Altitude / observable fraction
    total_steps = len(alt_deg)
    max_altitude = float(np.max(alt_deg))

    checks.append(
        {
            'name': 'max_altitude',
            'passed': is_moon or max_altitude >= effective_alt_min,
            'value': round(max_altitude, 1),
            'threshold': round(effective_alt_min, 1),
            'unit': '°',
        }
    )
    if not is_moon and max_altitude < effective_alt_min:
        overall = 'filtered'

    if horizon_profile and az_deg is not None:
        horizon_floors = np.maximum(effective_alt_min, _horizon_floor_array(az_deg, horizon_profile))
        in_window_mask = (alt_deg >= horizon_floors) if is_body else (alt_deg >= horizon_floors) & (alt_deg <= alt_max)
    else:
        in_window_mask = (
            (alt_deg >= effective_alt_min) if is_body else (alt_deg >= effective_alt_min) & (alt_deg <= alt_max)
        )

    observable_steps = int(np.sum(in_window_mask))
    observable_fraction = observable_steps / total_steps if total_steps > 0 else 0.0
    observable_hours = night_hours * observable_fraction

    # Bodies use a much lower threshold; Moon is always shown regardless (same logic as _compute_target_result).
    _BODIES_MIN_FRACTION_DEBUG = 0.05
    if is_moon:
        fraction_or_hours_ok = True
    elif is_body:
        fraction_or_hours_ok = observable_fraction >= _BODIES_MIN_FRACTION_DEBUG
    else:
        fraction_or_hours_ok = observable_fraction >= frac_threshold or observable_hours >= _MIN_OBSERVABLE_HOURS_DSO
    checks.append(
        {
            'name': 'observable_fraction',
            'passed': fraction_or_hours_ok,
            'value': round(observable_fraction, 3),
            'threshold': _BODIES_MIN_FRACTION_DEBUG if is_body else frac_threshold,
            'observable_hours': round(observable_hours, 2),
            'min_observable_hours': None if is_body else _MIN_OBSERVABLE_HOURS_DSO,
        }
    )
    if not fraction_or_hours_ok:
        overall = 'filtered'

    # --- Alt-time series for chart ---
    alttime: Dict[str, Any] = {
        'times_utc': times_iso,
        'altitudes': [round(float(a), 2) for a in alt_deg],
        'azimuths': [round(float(a), 1) for a in az_deg],
        'altitude_constraint_min': effective_alt_min,
        'altitude_constraint_max': alt_max,
        'night_start': night_start.isoformat(),
        'night_end': night_end.isoformat(),
        'timezone': timezone_name,
    }
    if astro_night_start is not None:
        alttime['night_astro_start'] = astro_night_start.isoformat()
    if astro_night_end is not None:
        alttime['night_astro_end'] = astro_night_end.isoformat()
    if horizon_profile:
        alttime['horizon_profile'] = horizon_profile

    moon_info = {
        'phase': round(moon.phase, 3),
        'phase_pct': round(moon.phase * 100.0, 1),
        'ra_deg': round(moon.ra_deg, 2) if moon.ra_deg is not None else None,
        'dec_deg': round(moon.dec_deg, 2) if moon.dec_deg is not None else None,
        'effective_min_separation': round(effective_min_sep, 1),
    }

    return {
        'found': True,
        'target': target_info,
        'night_window': {
            'available': True,
            'night_start': night_start.isoformat(),
            'night_end': night_end.isoformat(),
            'night_hours': round(night_hours, 2),
        },
        'moon': moon_info,
        'alttime': alttime,
        'constraints': constraints_summary,
        'checks': checks,
        'overall': overall,
    }
