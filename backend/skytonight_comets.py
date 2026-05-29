"""SkyTonight comet ingestion (MPC primary, JPL fallback/enrichment)."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Dict, List, Optional, Tuple, cast

import requests

from logging_config import get_logger
from skytonight_models import SkyTonightCoordinates, SkyTonightTarget
from skytonight_targets import normalize_object_name
from solar_system_events import SolarSystemEventsService


logger = get_logger(__name__)

# MPC CometEls.txt — fixed-width orbital elements for all known comets
COMETS_TXT_URL = 'https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt'
JPL_SBDB_ENDPOINT = 'https://ssd-api.jpl.nasa.gov/sbdb.api'

# Gaussian gravitational constant (AU^1.5 day^-1, solar mass = 1)
_GAUSS_K = 0.01720209895
# J2000.0 mean obliquity of the ecliptic (degrees)
_OBLIQUITY_DEG = 23.439291


def _response_preview(text: str, limit: int = 180) -> str:
    preview = ' '.join(str(text or '').split())
    if len(preview) > limit:
        return f"{preview[:limit]}..."
    return preview


# ---------------------------------------------------------------------------
# Keplerian orbit helpers
# ---------------------------------------------------------------------------

def _solve_kepler_elliptic(M: float, e: float) -> float:
    """Solve Kepler's equation E - e*sin(E) = M for eccentric anomaly E."""
    E = M
    for _ in range(60):
        dE = (M - E + e * math.sin(E)) / (1.0 - e * math.cos(E))
        E += dE
        if abs(dE) < 1e-12:
            break
    return E


def _solve_kepler_hyperbolic(N: float, e: float) -> float:
    """Solve hyperbolic Kepler's equation e*sinh(F) - F = N for F."""
    F = N
    for _ in range(60):
        denom = e * math.cosh(F) - 1.0
        if abs(denom) < 1e-15:
            break
        dF = (N + F - e * math.sinh(F)) / denom
        F += dF
        if abs(dF) < 1e-12:
            break
    return F


def _get_earth_heliocentric(obs_time: datetime) -> Tuple[float, float, float]:
    """Return Earth's heliocentric position in equatorial J2000 (AU).

    Uses Astropy get_body_barycentric; falls back to a simple circular
    approximation when Astropy is unavailable.
    """
    try:
        from astropy.time import Time
        from astropy.coordinates import CartesianRepresentation, get_body_barycentric
        from astropy import units as u
        t = Time(obs_time)
        e_bary = cast(CartesianRepresentation, get_body_barycentric('earth', t))
        s_bary = cast(CartesianRepresentation, get_body_barycentric('sun', t))
        delta_xyz = (e_bary - s_bary).get_xyz().to_value(u.AU)
        return (
            float(delta_xyz[0]),
            float(delta_xyz[1]),
            float(delta_xyz[2]),
        )
    except Exception:
        # Rough circular approximation: 1 AU, ~1 deg/day
        day_of_year = obs_time.timetuple().tm_yday
        angle = math.radians((day_of_year - 3) * 360.0 / 365.25)
        return (math.cos(angle), math.sin(angle), 0.0)


def _comet_ra_dec(
    q: float, e: float, omega_deg: float, Omega_deg: float, i_deg: float,
    peri_year: int, peri_month: int, peri_day: float,
    obs_time: datetime,
    earth_helio: Tuple[float, float, float],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Compute geocentric RA (hours), Dec (degrees), heliocentric distance (AU),
    and geocentric distance (AU) for a comet.

    Uses Keplerian two-body propagation.  Returns (None, None, None, None) on
    any computational failure.
    """
    try:
        omega = math.radians(omega_deg)
        Omega = math.radians(Omega_deg)
        i_rad = math.radians(i_deg)
        eps = math.radians(_OBLIQUITY_DEG)

        # Perihelion JD (days from J2000.0 = 2451545.0)
        day_int = int(peri_day)
        day_frac = peri_day - day_int
        peri_dt = datetime(peri_year, peri_month, max(1, day_int),
                           tzinfo=timezone.utc)
        peri_jd = peri_dt.timestamp() / 86400.0 + 2440587.5 + day_frac
        obs_jd = obs_time.timestamp() / 86400.0 + 2440587.5
        dt = obs_jd - peri_jd  # days since perihelion

        # Solve for true anomaly (f) and heliocentric distance (r)
        if abs(e - 1.0) < 0.005:  # approximately parabolic
            W = (3.0 / math.sqrt(2.0)) * _GAUSS_K * dt / (q ** 1.5)
            Y = math.copysign(
                abs(W + math.sqrt(W * W + 1.0)) ** (1.0 / 3.0),
                W + math.sqrt(W * W + 1.0),
            )
            tan_half_f = Y - 1.0 / Y
            f = 2.0 * math.atan(tan_half_f)
            r = q * (1.0 + tan_half_f ** 2)
        elif e < 1.0:  # elliptic
            a = q / (1.0 - e)
            n = _GAUSS_K / (a ** 1.5)
            M = n * dt
            E = _solve_kepler_elliptic(M, e)
            r = a * (1.0 - e * math.cos(E))
            cos_f = (math.cos(E) - e) / (1.0 - e * math.cos(E))
            sin_f = (math.sqrt(max(0.0, 1.0 - e * e)) * math.sin(E)
                     / (1.0 - e * math.cos(E)))
            f = math.atan2(sin_f, cos_f)
        else:  # hyperbolic
            a = q / (e - 1.0)
            n = _GAUSS_K / (a ** 1.5)
            N_h = n * dt
            F = _solve_kepler_hyperbolic(N_h, e)
            r = a * (e * math.cosh(F) - 1.0)
            if r <= 0:
                return None, None, None, None
            th = math.sqrt((e + 1.0) / (e - 1.0)) * math.tanh(F / 2.0)
            f = 2.0 * math.atan(th)

        # Heliocentric ecliptic rectangular coordinates
        u_arg = omega + f
        cu, su = math.cos(u_arg), math.sin(u_arg)
        cO, sO = math.cos(Omega), math.sin(Omega)
        ci = math.cos(i_rad)
        si = math.sin(i_rad)
        x_ecl = r * (cO * cu - sO * su * ci)
        y_ecl = r * (sO * cu + cO * su * ci)
        z_ecl = r * su * si

        # Rotate ecliptic → equatorial (J2000)
        ce, se = math.cos(eps), math.sin(eps)
        x_h = x_ecl
        y_h = y_ecl * ce - z_ecl * se
        z_h = y_ecl * se + z_ecl * ce

        # Geocentric position
        gx = x_h - earth_helio[0]
        gy = y_h - earth_helio[1]
        gz = z_h - earth_helio[2]
        g_dist = math.sqrt(gx * gx + gy * gy + gz * gz)
        if g_dist < 1e-12:
            return None, None, None, None

        ra_rad = math.atan2(gy, gx)
        if ra_rad < 0:
            ra_rad += 2.0 * math.pi
        dec_rad = math.asin(max(-1.0, min(1.0, gz / g_dist)))

        return math.degrees(ra_rad) / 15.0, math.degrees(dec_rad), round(r, 4), round(g_dist, 4)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None, None, None, None


def _parse_comets_txt_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one line of MPC CometEls.txt (fixed-width).  Returns None on failure."""
    if len(line) < 103:
        return None
    orbit_type = line[4:5].strip()
    if orbit_type not in ('P', 'C', 'X', 'D', 'I', 'A'):
        return None
    try:
        peri_year = int(line[14:18])
        peri_month = int(line[19:21])
        peri_day = float(line[22:29])
        q = float(line[30:39])
        e = float(line[40:49])
        omega = float(line[50:59])
        cap_omega = float(line[60:69])
        incl = float(line[70:79])
        epoch = line[81:89].strip()
        abs_mag = _safe_float(line[91:96].strip() or None)
        name = re.sub(r'\s{2,}', ' ', line[102:]).strip()
        designation = line[5:12].strip()
        if not name:
            name = designation
        return {
            'orbit_type': orbit_type,
            'designation': designation,
            'name': name,
            'perihelion_year': peri_year,
            'perihelion_month': peri_month,
            'perihelion_day': peri_day,
            'q': q,
            'e': e,
            'omega': omega,
            'Omega': cap_omega,
            'inclination': incl,
            'epoch': epoch,
            'absolute_magnitude': abs_mag,
            'magnitude': abs_mag,
        }
    except (ValueError, IndexError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target_id_from_name(name: str) -> str:
    return f"comet-{normalize_object_name(name)}"


def _coerce_coordinates(row: Dict[str, Any]) -> Optional[SkyTonightCoordinates]:
    ra_hours = _safe_float(row.get('ra_hours'))
    dec_degrees = _safe_float(row.get('dec_degrees'))
    if ra_hours is None or dec_degrees is None:
        return None
    return SkyTonightCoordinates(ra_hours=ra_hours, dec_degrees=dec_degrees)


def _to_comet_target(row: Dict[str, Any], source: str) -> Optional[SkyTonightTarget]:
    name = str(row.get('name') or row.get('designation') or '').strip()
    if not name:
        return None

    aliases = []
    designation = str(row.get('designation') or '').strip()
    if designation and designation != name:
        aliases.append(designation)

    metadata: Dict[str, Any] = {
        'source': source,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    for key in ('perihelion_date', 'orbit_class', 'epoch', 'uncertainty',
                 'distance_sun_au', 'distance_earth_au', 'absolute_magnitude'):
        if row.get(key) not in (None, ''):
            metadata[key] = row.get(key)

    return SkyTonightTarget(
        target_id=_target_id_from_name(name),
        category='comets',
        object_type='Comet',
        preferred_name=name,
        catalogue_names={'Comets': name},
        aliases=aliases,
        constellation=str(row.get('constellation') or '').strip(),
        magnitude=_safe_float(row.get('magnitude') or row.get('absolute_magnitude')),
        size_arcmin=None,
        coordinates=_coerce_coordinates(row),
        source_catalogues=['Comets'],
        translation_key='skytonight.type_comet',
        metadata=metadata,
    )


def fetch_mpc_comets(timeout_seconds: int = 20) -> List[Dict[str, Any]]:
    """Fetch comet orbital elements from MPC CometEls.txt and compute RA/Dec.

    Parses the fixed-width MPC CometEls.txt file, propagates each comet's
    orbit to the current time using Keplerian two-body mechanics, and returns
    a list of row dicts with 'ra_hours'/'dec_degrees' populated (or None when
    computation fails).
    """
    try:
        response = requests.get(COMETS_TXT_URL, timeout=timeout_seconds)
        response.raise_for_status()
        text = response.text
    except requests.RequestException as error:
        logger.warning(f'Failed to reach MPC CometEls.txt (provider/network issue): {error}')
        return []
    except Exception as error:
        logger.warning(f'Failed to fetch MPC comet elements: {error}')
        return []

    raw_rows = []
    for line in text.splitlines():
        parsed = _parse_comets_txt_line(line)
        if parsed is not None:
            raw_rows.append(parsed)

    if not raw_rows:
        logger.warning('MPC CometEls.txt returned no parseable comet data; '
                       f'body_preview=\'{_response_preview(text)}\'')
        return []

    logger.debug(f'Parsed {len(raw_rows)} comet orbital elements from MPC CometEls.txt')

    obs_time = datetime.now(timezone.utc)
    earth_helio = _get_earth_heliocentric(obs_time)

    rows: List[Dict[str, Any]] = []
    computed = 0
    for raw in raw_rows:
        ra_h, dec_d, dist_sun, dist_earth = _comet_ra_dec(
            raw['q'], raw['e'], raw['omega'], raw['Omega'], raw['inclination'],
            raw['perihelion_year'], raw['perihelion_month'], raw['perihelion_day'],
            obs_time, earth_helio,
        )
        row = dict(raw)
        row['ra_hours'] = ra_h
        row['dec_degrees'] = dec_d
        row['distance_sun_au'] = dist_sun
        row['distance_earth_au'] = dist_earth
        row['perihelion_date'] = (
            f"{raw['perihelion_year']:04d}-"
            f"{raw['perihelion_month']:02d}-"
            f"{int(raw['perihelion_day']):02d}"
        )
        row['orbit_class'] = raw['orbit_type']
        row['uncertainty'] = None
        rows.append(row)
        if ra_h is not None:
            computed += 1

    logger.debug(f'Computed sky positions for {computed}/{len(rows)} comets')
    return rows


def _fetch_jpl_comet_snapshot(name: str, timeout_seconds: int = 8) -> Dict[str, Any]:
    if not name:
        return {}
    try:
        response = requests.get(JPL_SBDB_ENDPOINT, params={'sstr': name}, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    orbit = payload.get('orbit', {}) if isinstance(payload.get('orbit'), dict) else {}
    phys = payload.get('phys_par', {}) if isinstance(payload.get('phys_par'), dict) else {}
    object_data = payload.get('object', {}) if isinstance(payload.get('object'), dict) else {}

    return {
        'name': str(object_data.get('fullname') or name),
        'designation': str(object_data.get('des') or ''),
        'orbit_class': str(orbit.get('class') or ''),
        'absolute_magnitude': _safe_float(phys.get('H')),
    }


def enrich_with_jpl_fallback(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fill missing fields from JPL when possible, preserving MPC rows as primary."""
    # Only these fields are worth fetching from JPL — and MPC already provides
    # them for virtually all comets.  Skip the HTTP call entirely when all of
    # them are already present so we don't make hundreds of unnecessary requests.
    _JPL_FILLS = ('absolute_magnitude', 'orbit_class')
    # Safety cap: never make more than this many JPL requests per build cycle.
    _MAX_JPL_REQUESTS = 50

    jpl_requests_made = 0
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current = dict(row)
        name = str(current.get('name') or current.get('designation') or '').strip()

        needs_jpl = (
            name
            and jpl_requests_made < _MAX_JPL_REQUESTS
            and any(current.get(key) in (None, '') for key in _JPL_FILLS)
        )

        if needs_jpl:
            snapshot = _fetch_jpl_comet_snapshot(name)
            jpl_requests_made += 1
            if snapshot:
                for key, value in snapshot.items():
                    if current.get(key) in (None, '') and value not in (None, ''):
                        current[key] = value
                current.setdefault('enrichment_source', 'JPL')

        enriched.append(current)

    if jpl_requests_made:
        logger.info(f'JPL enrichment: {jpl_requests_made} requests made for comets with missing fields')
    else:
        logger.debug('JPL enrichment: all comets already had complete MPC data, no requests needed')

    return enriched


def _curated_fallback_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for name, values in SolarSystemEventsService.NOTABLE_COMETS.items():
        rows.append(
            {
                'name': name,
                'magnitude': values.get('magnitude'),
                'perihelion_date': f"{values.get('perihelion_year', ''):04d}-{values.get('perihelion_month', 1):02d}-{values.get('perihelion_day', 1):02d}",
            }
        )
    return rows


def build_comet_targets(source_mode: str = 'mpc+jpl') -> List[SkyTonightTarget]:
    """Build normalized SkyTonight comet targets with MPC primary and JPL fallback/enrichment."""
    mode = str(source_mode or 'mpc+jpl').strip().lower()

    rows: List[Dict[str, Any]] = []
    if 'mpc' in mode:
        rows = fetch_mpc_comets()

    if ('jpl' in mode) and rows:
        rows = enrich_with_jpl_fallback(rows)

    if not rows:
        rows = _curated_fallback_rows()
        row_source = 'curated-fallback'
    else:
        row_source = 'mpc+jpl' if 'jpl' in mode else 'mpc'

    targets: List[SkyTonightTarget] = []
    for row in rows:
        target = _to_comet_target(row, source=row_source)
        if target is not None:
            targets.append(target)

    # Deduplicate by target_id while preserving first row priority.
    deduplicated: Dict[str, SkyTonightTarget] = {}
    for target in targets:
        deduplicated.setdefault(target.target_id, target)

    return sorted(deduplicated.values(), key=lambda item: item.preferred_name.lower())
