"""
ISS pass prediction service.

Computes upcoming International Space Station passages for the configured observer
location using current TLE data and returns local-time windows with a visibility
score and day/night visibility classification.
"""

from datetime import datetime, timedelta, timezone
from math import acos, asin, cos, degrees, radians, sin
from typing import Optional, Dict, Any, List, Tuple, cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import os
import threading
import time

import json
import numpy as np
import requests
import astropy.units as u
from astropy.time import Time as AstroTime
from astropy.coordinates import Angle, EarthLocation, AltAz, get_sun
from skyfield.api import Loader, EarthSatellite, wgs84

from utils.constants import CACHE_TTL, DATA_DIR_CACHE
from utils.logging_config import get_logger
from utils import load_json_file, save_json_file

logger = get_logger(__name__)

SKYFIELD_CACHE_DIR = os.path.join(DATA_DIR_CACHE, 'skyfield')
os.makedirs(SKYFIELD_CACHE_DIR, exist_ok=True)
SKYFIELD_LOADER = Loader(SKYFIELD_CACHE_DIR)
logger.debug(f"Skyfield cache directory: {SKYFIELD_CACHE_DIR}")

# Process-wide memoised JPL ephemeris. The live-position endpoint is polled far
# more often than the (cached) pass report, so re-opening the ~16 MB de421.bsp on
# every request wastes CPU/IO and file handles; load it once and reuse it.
_EPHEMERIS = None
_EPHEMERIS_ATTEMPTED = False
_EPHEMERIS_LOCK = threading.Lock()


def _get_ephemeris():
    """Return the shared de421 ephemeris, loading it once (None if unavailable)."""
    global _EPHEMERIS, _EPHEMERIS_ATTEMPTED
    if _EPHEMERIS is None and not _EPHEMERIS_ATTEMPTED:
        with _EPHEMERIS_LOCK:
            if _EPHEMERIS is None and not _EPHEMERIS_ATTEMPTED:
                _EPHEMERIS_ATTEMPTED = True
                try:
                    _EPHEMERIS = SKYFIELD_LOADER('de421.bsp')
                except Exception as exc:
                    logger.warning(f"Could not load ephemeris file de421.bsp: {exc}")
                    _EPHEMERIS = None
    return _EPHEMERIS


# TLE sources in priority order.  Celestrak is authoritative but sources 2-3 are
# independent aggregators that remain reachable when a Celestrak IP-block occurs.
# They are placed early so a Celestrak timeout does not cost 30 extra seconds.
ISS_TLE_URLS = [
    # Primary: Celestrak GP catalog (most specific, JSON-capable via FORMAT=TLE)
    "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE",
    # Alternative 1: independent aggregator - returns JSON {line1, line2}
    "https://tle.ivanstanojevic.me/api/tle/25544",
    # Alternative 2: wheretheiss.at - returns JSON {line1, line2}
    "https://api.wheretheiss.at/v1/satellites/25544/tles",
]
REQUEST_TIMEOUT_SECONDS = 10
CELESTRAK_TIMEOUT_BLOCK_THRESHOLD = 3
DEFAULT_FORECAST_DAYS = 20
MAX_FORECAST_DAYS = 30
MIN_EVENT_ALTITUDE_DEG = 10.0
MAX_VISIBLE_SKY_SUN_ALTITUDE_DEG = -4.0
VISIBILITY_SAMPLE_SECONDS = 5
GEOMETRIC_PASS_MIN_ALTITUDE_DEG = 0.0
# Transit detection samples the ISS/Sun (or ISS/Moon) geometry over each geometric
# pass. To avoid propagating every pass at 1 s (the ISS moves ~1°/s, so most passes
# never bring it anywhere near the disk), each pass is first scanned coarsely and
# vectorised; a pass whose closest approach stays beyond MAX_APPROACH_DEG is
# skipped, and only a promising pass is refined at fine resolution. The coarse step
# must stay well under the fine window so the true minimum is always bracketed.
SOLAR_TRANSIT_COARSE_SECONDS = 10.0
SOLAR_TRANSIT_MAX_APPROACH_DEG = 6.0
SOLAR_TRANSIT_REFINE_SAMPLE_SECONDS = 0.1
SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG = 0.0
SOLAR_ANGULAR_RADIUS_FALLBACK_DEG = 0.2666
SOLAR_RADIUS_KM = 695700.0
LUNAR_TRANSIT_COARSE_SECONDS = 10.0
LUNAR_TRANSIT_MAX_APPROACH_DEG = 6.0
LUNAR_TRANSIT_REFINE_SAMPLE_SECONDS = 0.1
LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG = 5.0
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = 0.2615
LUNAR_RADIUS_KM = 1737.4
ISS_TLE_CACHE_FILE = os.path.join(DATA_DIR_CACHE, 'iss_tle_cache.json')
ISS_TLE_MAX_AGE_SECONDS = 6 * 60 * 60
ISS_TLE_FAILURE_COOLDOWN_SECONDS = 3 * 60 * 60
CELESTRAK_USAGE_POLICY_URL = "https://celestrak.org/usage-policy.php"
CELESTRAK_ADDENDUM_URL = "https://celestrak.org/NORAD/documentation/gp-data-formats.php#addendum"
CELESTRAK_ISS_QUERY_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"

# Server-side ground-track cache: recompute the ±50-min orbit path at most once per 5 min.
# The current ISS position is always computed fresh (1 propagation per request).
_TRACK_CACHE: Dict[str, Any] = {}
_TRACK_CACHE_LOCK = threading.Lock()
_TRACK_CACHE_TTL_SECONDS = 300  # 5 minutes


def _utc_timestamp() -> int:
    return int(time.time())


def _read_tle_cache() -> Dict[str, Any]:
    payload = load_json_file(ISS_TLE_CACHE_FILE, default={})
    return payload if isinstance(payload, dict) else {}


def _write_tle_cache(payload: Dict[str, Any]) -> None:
    save_json_file(ISS_TLE_CACHE_FILE, payload)


# Serialises the read-modify-write TLE cache updates below. In a multi-location
# install the ISS pass job runs once per location in parallel threads, so without
# this lock two writers could interleave and lose each other's updates (e.g. clobber
# a freshly-set celestrak_blocked flag). Network fetches stay outside the lock.
_TLE_CACHE_LOCK = threading.Lock()


def _update_tle_cache(mutator) -> None:
    """Apply ``mutator(payload)`` to the on-disk TLE cache atomically."""
    with _TLE_CACHE_LOCK:
        payload = _read_tle_cache()
        mutator(payload)
        _write_tle_cache(payload)


def _get_cached_tle(max_age_seconds: Optional[int] = None) -> Optional[Tuple[str, str, int]]:
    cache = _read_tle_cache()
    line1 = str(cache.get('line1') or '').strip()
    line2 = str(cache.get('line2') or '').strip()
    fetched_at = int(cache.get('fetched_at') or 0)
    if not line1 or not line2 or fetched_at <= 0:
        return None

    age = _utc_timestamp() - fetched_at
    if max_age_seconds is not None and age > max_age_seconds:
        return None

    return line1, line2, fetched_at


def _set_cached_tle(line1: str, line2: str) -> None:
    def _mutate(payload: Dict[str, Any]) -> None:
        payload['line1'] = line1
        payload['line2'] = line2
        payload['fetched_at'] = _utc_timestamp()
        payload['last_error_at'] = None

    _update_tle_cache(_mutate)


def _source_name_from_url(source_url: str) -> str:
    hostname = (urlparse(source_url or "").hostname or "").lower()
    if hostname == "celestrak.org" or hostname.endswith(".celestrak.org"):
        return "Celestrak"
    if hostname == "tle.ivanstanojevic.me":
        return "TLE API (ivanstanojevic.me)"
    if hostname == "api.wheretheiss.at" or hostname == "wheretheiss.at":
        return "WhereTheISS"
    return "Unknown"


def _is_celestrak_url(candidate_url: str) -> bool:
    hostname = (urlparse(candidate_url or "").hostname or "").lower()
    return hostname == "celestrak.org" or hostname.endswith(".celestrak.org")


def _set_cached_tle_with_source(line1: str, line2: str, source_url: str) -> None:
    def _mutate(payload: Dict[str, Any]) -> None:
        payload['line1'] = line1
        payload['line2'] = line2
        payload['fetched_at'] = _utc_timestamp()
        payload['last_error_at'] = None
        payload['last_source_url'] = source_url
        payload['last_source_name'] = _source_name_from_url(source_url)

    _update_tle_cache(_mutate)


def get_iss_tle_source_info() -> Dict[str, Any]:
    payload = _read_tle_cache()
    return {
        "name": str(payload.get("last_source_name") or "").strip(),
        "url": str(payload.get("last_source_url") or "").strip(),
        "fetched_at": int(payload.get("fetched_at") or 0),
    }


def _set_tle_error_timestamp() -> None:
    _update_tle_cache(lambda payload: payload.update({'last_error_at': _utc_timestamp()}))


def _in_tle_failure_cooldown() -> bool:
    payload = _read_tle_cache()
    last_error_at = int(payload.get('last_error_at') or 0)
    if last_error_at <= 0:
        return False
    return (_utc_timestamp() - last_error_at) < ISS_TLE_FAILURE_COOLDOWN_SECONDS


def _set_celestrak_block(status_code: int, reason: str, source_url: str) -> None:
    def _mutate(payload: Dict[str, Any]) -> None:
        payload['celestrak_blocked'] = True
        payload['celestrak_blocked_at'] = _utc_timestamp()
        payload['celestrak_blocked_status_code'] = int(status_code)
        payload['celestrak_blocked_reason'] = reason
        payload['celestrak_blocked_source_url'] = source_url

    _update_tle_cache(_mutate)


def _reset_celestrak_timeout_streak() -> None:
    def _mutate(payload: Dict[str, Any]) -> None:
        payload['celestrak_timeout_streak'] = 0
        payload['celestrak_last_timeout_at'] = None
        payload['celestrak_last_timeout_reason'] = None
        payload['celestrak_last_timeout_source_url'] = None

    _update_tle_cache(_mutate)


def _increment_celestrak_timeout_streak(reason: str, source_url: str) -> int:
    captured: Dict[str, int] = {}

    def _mutate(payload: Dict[str, Any]) -> None:
        streak = int(payload.get('celestrak_timeout_streak') or 0) + 1
        payload['celestrak_timeout_streak'] = streak
        payload['celestrak_last_timeout_at'] = _utc_timestamp()
        payload['celestrak_last_timeout_reason'] = reason
        payload['celestrak_last_timeout_source_url'] = source_url
        captured['streak'] = streak

    _update_tle_cache(_mutate)
    return captured.get('streak', 0)


def _is_celestrak_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    message = str(exc).lower()
    return "timed out" in message or "connect timeout" in message


def _clear_celestrak_block(reset_failure_cooldown: bool = True) -> None:
    def _mutate(payload: Dict[str, Any]) -> None:
        payload['celestrak_blocked'] = False
        payload['celestrak_blocked_at'] = None
        payload['celestrak_blocked_status_code'] = None
        payload['celestrak_blocked_reason'] = None
        payload['celestrak_blocked_source_url'] = None
        payload['celestrak_timeout_streak'] = 0
        payload['celestrak_last_timeout_at'] = None
        payload['celestrak_last_timeout_reason'] = None
        payload['celestrak_last_timeout_source_url'] = None
        if reset_failure_cooldown:
            payload['last_error_at'] = None

    _update_tle_cache(_mutate)


def get_celestrak_status() -> Dict[str, Any]:
    payload = _read_tle_cache()
    return {
        "blocked": bool(payload.get("celestrak_blocked") is True),
        "blocked_at": int(payload.get("celestrak_blocked_at") or 0),
        "blocked_status_code": int(payload.get("celestrak_blocked_status_code") or 0),
        "blocked_reason": str(payload.get("celestrak_blocked_reason") or "").strip(),
        "blocked_source_url": str(payload.get("celestrak_blocked_source_url") or "").strip(),
        "timeout_streak": int(payload.get("celestrak_timeout_streak") or 0),
        "timeout_block_threshold": CELESTRAK_TIMEOUT_BLOCK_THRESHOLD,
        "last_timeout_at": int(payload.get("celestrak_last_timeout_at") or 0),
        "last_timeout_reason": str(payload.get("celestrak_last_timeout_reason") or "").strip(),
        "last_timeout_source_url": str(payload.get("celestrak_last_timeout_source_url") or "").strip(),
        "policy_url": CELESTRAK_USAGE_POLICY_URL,
        "addendum_url": CELESTRAK_ADDENDUM_URL,
        "manual_check_url": CELESTRAK_ISS_QUERY_URL,
    }


def clear_celestrak_block_flag() -> Dict[str, Any]:
    """Clear persisted Celestrak block flag after manual operator confirmation."""
    _clear_celestrak_block(reset_failure_cooldown=True)
    return get_celestrak_status()


class ISSPassService:
    """Service that computes ISS visible passes for an observer location."""

    def __init__(self, latitude: float, longitude: float, elevation_m: float, timezone_str: str):
        self.latitude = latitude
        self.longitude = longitude
        self.elevation_m = elevation_m
        self.timezone = ZoneInfo(timezone_str)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation_m * u.m)

    def get_report(self, days: int = DEFAULT_FORECAST_DAYS) -> Dict[str, Any]:
        """Generate ISS pass report for the requested window."""
        forecast_days = max(1, min(int(days), MAX_FORECAST_DAYS))

        line1, line2 = self._fetch_iss_tle()

        ts = SKYFIELD_LOADER.timescale()
        satellite = EarthSatellite(line1, line2, "ISS (ZARYA)", ts)
        observer = wgs84.latlon(self.latitude, self.longitude, elevation_m=self.elevation_m)
        eph = self._load_ephemeris()

        now_utc = datetime.now(timezone.utc)
        end_utc = now_utc + timedelta(days=forecast_days)

        event_times, event_types = satellite.find_events(
            observer,
            ts.from_datetime(now_utc),
            ts.from_datetime(end_utc),
            altitude_degrees=MIN_EVENT_ALTITUDE_DEG,
        )

        all_passes = self._build_passes(event_times, event_types, satellite, observer, ts, eph)
        passes = [entry for entry in all_passes if entry.get("is_visible")]
        next_visible = passes[0] if passes else None

        # Geometric passes (altitude >= 0) are computed once and shared by the solar
        # and lunar transit scans, which both need the full above-horizon window.
        geo_times, geo_types = satellite.find_events(
            observer,
            ts.from_datetime(now_utc),
            ts.from_datetime(end_utc),
            altitude_degrees=GEOMETRIC_PASS_MIN_ALTITUDE_DEG,
        )
        solar_transits = self._find_solar_transits(now_utc, end_utc, satellite, observer, ts, eph, geo_times, geo_types)
        next_solar_transit = solar_transits[0] if solar_transits else None
        lunar_transits = self._find_lunar_transits(now_utc, end_utc, satellite, observer, ts, eph, geo_times, geo_types)
        next_lunar_transit = lunar_transits[0] if lunar_transits else None

        return {
            "timestamp": datetime.now(self.timezone).isoformat(),
            "location": {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "elevation": self.elevation_m,
                "timezone": str(self.timezone),
            },
            "window_days": forecast_days,
            "next_visible_passage": next_visible,
            "next_solar_transit": next_solar_transit,
            "next_lunar_transit": next_lunar_transit,
            "passes": passes,
            "solar_transits": solar_transits,
            "lunar_transits": lunar_transits,
            "total_passes": len(passes),
            "total_solar_transits": len(solar_transits),
            "total_lunar_transits": len(lunar_transits),
            "cache_ttl": CACHE_TTL,
            "celestrak_status": get_celestrak_status(),
            "tle_source": get_iss_tle_source_info(),
            "units": {
                "times": "ISO format local timezone",
                "duration_minutes": "minutes",
                "duration_seconds": "seconds",
                "peak_altitude": "degrees",
                "azimuth": "degrees",
                "visibility_score": "0-100",
                "angular_separation": "arcminutes",
            },
        }

    def _load_ephemeris(self):
        """Load JPL ephemeris for solar illumination checks."""
        try:
            return SKYFIELD_LOADER('de421.bsp')
        except Exception as exc:
            logger.warning(f"Could not load ephemeris file de421.bsp: {exc}")
            return None

    def _fetch_iss_tle(self) -> Tuple[str, str]:
        """Fetch latest ISS TLE with strict handling for Celestrak policy errors."""
        # Fast path: prefer recent cached TLE to avoid unnecessary upstream requests.
        cached_recent = _get_cached_tle(max_age_seconds=ISS_TLE_MAX_AGE_SECONDS)
        if cached_recent is not None:
            line1, line2, _ = cached_recent
            return line1, line2

        # Circuit breaker: if a recent failure happened, avoid hammering providers.
        if _in_tle_failure_cooldown():
            cached_any = _get_cached_tle(max_age_seconds=None)
            if cached_any is not None:
                line1, line2, fetched_at = cached_any
                age_hours = (_utc_timestamp() - fetched_at) / 3600.0
                logger.warning(f"ISS TLE fetch is in cooldown; reusing stale cached TLE ({age_hours:.1f}h old)")
                return line1, line2
            raise RuntimeError('ISS TLE fetch is in cooldown and no cached TLE is available')

        last_error: Optional[Exception] = None
        celestrak_status = get_celestrak_status()

        for tle_url in ISS_TLE_URLS:
            if celestrak_status.get("blocked") and _is_celestrak_url(tle_url):
                logger.warning("Celestrak is flagged as blocked; skipping Celestrak query until manually reset")
                continue

            try:
                response = requests.get(tle_url, timeout=REQUEST_TIMEOUT_SECONDS)
                status_code = int(getattr(response, "status_code", 200) or 0)

                # Celestrak policy compliance: any non-200 response must stop
                # further upstream querying and be escalated to human review.
                if _is_celestrak_url(tle_url) and status_code != 200:
                    _reset_celestrak_timeout_streak()
                    _set_tle_error_timestamp()
                    _set_celestrak_block(
                        status_code=status_code,
                        reason=f"HTTP {status_code}",
                        source_url=tle_url,
                    )
                    raise RuntimeError(
                        f"Celestrak returned HTTP {status_code};"
                        " stopping TLE queries and requiring manual investigation"
                    )

                response.raise_for_status()
                line1, line2 = self._parse_iss_tle_from_response(response.text)
                _set_cached_tle_with_source(line1, line2, tle_url)
                if _is_celestrak_url(tle_url):
                    _reset_celestrak_timeout_streak()
                    _clear_celestrak_block(reset_failure_cooldown=True)
                return line1, line2
            except Exception as exc:
                if _is_celestrak_url(tle_url):
                    status_message = str(exc).upper()
                    if (isinstance(exc, RuntimeError) and "CELESTRAK RETURNED HTTP" in status_message) or (
                        "403" in status_message
                    ):
                        _set_tle_error_timestamp()
                        _set_celestrak_block(
                            status_code=403 if "403" in status_message else 0,
                            reason=str(exc),
                            source_url=tle_url,
                        )
                        logger.error(
                            "Celestrak rejected a TLE request with a non-200 response. "
                            "Automatic queries have been stopped and human intervention is required. "
                            f"See {CELESTRAK_USAGE_POLICY_URL} and "
                            f"{CELESTRAK_ADDENDUM_URL}"
                        )
                        cached_any = _get_cached_tle(max_age_seconds=None)
                        if cached_any is not None:
                            line1, line2, fetched_at = cached_any
                            age_hours = (_utc_timestamp() - fetched_at) / 3600.0
                            logger.warning(
                                f"Celestrak policy block detected; reusing stale cached TLE ({age_hours:.1f}h old)"
                            )
                            return line1, line2
                        raise RuntimeError(
                            "Celestrak returned a non-200 response and no cached TLE is available; "
                            "manual intervention required"
                        ) from exc

                    if _is_celestrak_timeout_error(exc):
                        timeout_streak = _increment_celestrak_timeout_streak(str(exc), tle_url)
                        logger.warning(
                            "Celestrak timeout detected (%s/%s consecutive): %s",
                            timeout_streak,
                            CELESTRAK_TIMEOUT_BLOCK_THRESHOLD,
                            exc,
                        )
                        if timeout_streak >= CELESTRAK_TIMEOUT_BLOCK_THRESHOLD:
                            _set_tle_error_timestamp()
                            _set_celestrak_block(
                                status_code=0,
                                reason=(
                                    "Consecutive Celestrak timeout threshold reached "
                                    f"({CELESTRAK_TIMEOUT_BLOCK_THRESHOLD})"
                                ),
                                source_url=tle_url,
                            )
                            logger.error(
                                "Celestrak was auto-flagged as blocked after %s consecutive timeouts. "
                                "Automatic Celestrak queries are paused until manual reset.",
                                CELESTRAK_TIMEOUT_BLOCK_THRESHOLD,
                            )
                    else:
                        _reset_celestrak_timeout_streak()

                last_error = exc
                logger.debug(f"ISS TLE fetch failed for {tle_url}: {exc}")

        _set_tle_error_timestamp()
        cached_any = _get_cached_tle(max_age_seconds=None)
        if cached_any is not None:
            line1, line2, fetched_at = cached_any
            age_hours = (_utc_timestamp() - fetched_at) / 3600.0
            logger.warning(f"All ISS TLE sources failed; using stale cached TLE ({age_hours:.1f}h old)")
            return line1, line2

        logger.warning("All ISS TLE sources failed and no cached TLE is available")
        raise RuntimeError(f"Failed to fetch ISS TLE from all sources: {last_error}")

    def _parse_iss_tle_from_response(self, response_text: str) -> Tuple[str, str]:
        """Extract ISS TLE pair from a response payload (JSON or plain-text)."""
        # Attempt JSON first - tle.ivanstanojevic.me and wheretheiss.at return
        # {"line1": "1 25544...", "line2": "2 25544..."}
        try:
            data = json.loads(response_text)
            line1 = str(data.get("line1") or "").strip()
            line2 = str(data.get("line2") or "").strip()
            if line1.startswith("1 ") and line2.startswith("2 "):
                return line1, line2
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass  # response is not JSON — fall through to plain-text TLE parse below

        # Fall back to plain-text TLE format (Celestrak)
        lines = [line.strip() for line in response_text.splitlines() if line.strip()]
        first_tle_pair: Optional[Tuple[str, str]] = None

        for index in range(len(lines) - 1):
            line = lines[index]
            next_line = lines[index + 1]
            if line.startswith("1 ") and next_line.startswith("2 "):
                pair = (line, next_line)
                if first_tle_pair is None:
                    first_tle_pair = pair

                previous_name = lines[index - 1].upper() if index > 0 else ""
                if "ISS" in previous_name or "ZARYA" in previous_name:
                    return pair

        if first_tle_pair is not None:
            return first_tle_pair

        raise ValueError("Could not parse ISS TLE from response payload")

    def _build_passes(
        self, event_times, event_types, satellite: EarthSatellite, observer, ts, eph
    ) -> List[Dict[str, Any]]:
        """Build normalized pass objects from Skyfield rise/culminate/set events."""
        passes: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}

        for event_time, event_type in zip(event_times, event_types):
            dt_utc = event_time.utc_datetime().replace(tzinfo=timezone.utc)

            if event_type == 0:
                current = {"start": dt_utc}
                continue

            if event_type == 1:
                if not current:
                    continue
                current["peak"] = dt_utc
                current["peak_altitude_deg"] = self._satellite_altitude_deg(satellite, observer, event_time)
                continue

            if event_type == 2:
                if not current or "peak" not in current:
                    current = {}
                    continue

                current["end"] = dt_utc
                pass_entry = self._extract_visible_segment(
                    start_utc=current["start"],
                    end_utc=current["end"],
                    satellite=satellite,
                    observer=observer,
                    ts=ts,
                    eph=eph,
                )

                if pass_entry:
                    passes.append(pass_entry)

                current = {}

        return passes

    def _extract_visible_segment(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
    ) -> Optional[Dict[str, Any]]:
        """Extract the visible segment of a geometric pass using time sampling."""
        if end_utc <= start_utc:
            return None

        samples = []
        sample_time = start_utc
        while sample_time <= end_utc:
            samples.append(self._sample_observation(sample_time, satellite, observer, ts, eph))
            sample_time += timedelta(seconds=VISIBILITY_SAMPLE_SECONDS)

        if not samples or samples[-1]["time_utc"] != end_utc:
            samples.append(self._sample_observation(end_utc, satellite, observer, ts, eph))

        visible_indices = [idx for idx, sample in enumerate(samples) if sample["is_visible"]]
        if not visible_indices:
            return None

        segments = self._group_consecutive_indices(visible_indices)
        best_segment = max(
            segments,
            key=lambda segment: max(samples[idx]["altitude_deg"] for idx in segment),
        )

        segment_samples = [samples[idx] for idx in best_segment]
        start_sample = segment_samples[0]
        end_sample = segment_samples[-1]
        peak_sample = max(segment_samples, key=lambda sample: sample["altitude_deg"])

        start_time = start_sample["time_utc"]
        peak_time = peak_sample["time_utc"]
        end_time = end_sample["time_utc"]
        duration_minutes = max(0.0, (end_time - start_time).total_seconds() / 60.0)
        peak_altitude = float(peak_sample["altitude_deg"])
        sun_altitude_deg = float(peak_sample["sun_altitude_deg"])
        day_night_visibility = self._classify_day_night(sun_altitude_deg)
        visibility_score = self._compute_visibility_score(
            peak_altitude_deg=peak_altitude,
            duration_minutes=duration_minutes,
            sun_altitude_deg=sun_altitude_deg,
        )

        return {
            "start_time": start_time.astimezone(self.timezone).isoformat(),
            "peak_time": peak_time.astimezone(self.timezone).isoformat(),
            "end_time": end_time.astimezone(self.timezone).isoformat(),
            "start_altitude_deg": round(float(start_sample["altitude_deg"]), 1),
            "peak_altitude_deg": round(peak_altitude, 1),
            "end_altitude_deg": round(float(end_sample["altitude_deg"]), 1),
            "start_azimuth_deg": round(float(start_sample["azimuth_deg"]), 1),
            "peak_azimuth_deg": round(float(peak_sample["azimuth_deg"]), 1),
            "end_azimuth_deg": round(float(end_sample["azimuth_deg"]), 1),
            "start_azimuth_cardinal": self._azimuth_to_cardinal(float(start_sample["azimuth_deg"])),
            "peak_azimuth_cardinal": self._azimuth_to_cardinal(float(peak_sample["azimuth_deg"])),
            "end_azimuth_cardinal": self._azimuth_to_cardinal(float(end_sample["azimuth_deg"])),
            "duration_minutes": round(duration_minutes, 1),
            "visibility_score": round(visibility_score, 1),
            "visibility_day_night": day_night_visibility,
            "sun_altitude_deg": round(sun_altitude_deg, 1),
            "pass_type": "visible",
            "is_visible": True,
        }

    # -----------------------------------------------------------------------
    # Vectorised geometry helpers (transit detection). Skyfield propagates an
    # array of times in one call, so a whole pass is evaluated at once instead of
    # one Python-loop propagation per sampled instant.
    # -----------------------------------------------------------------------

    @staticmethod
    def _iter_geometric_passes(event_times, event_types):
        """Yield (start_utc, end_utc) for each rise->set geometric pass from Skyfield events."""
        current_start: Optional[datetime] = None
        for event_time, event_type in zip(event_times, event_types):
            dt_utc = event_time.utc_datetime().replace(tzinfo=timezone.utc)
            if event_type == 0:
                current_start = dt_utc
            elif event_type == 2 and current_start is not None:
                yield current_start, dt_utc
                current_start = None

    @staticmethod
    def _time_grid(start_utc: datetime, end_utc: datetime, step_seconds: float) -> List[datetime]:
        """Inclusive list of UTC datetimes spanning [start, end] at a fixed step.

        Steps never overshoot ``end_utc`` (windows shorter than one step collapse to
        the two endpoints), so the grid is always monotonic within [start, end].
        """
        if end_utc <= start_utc:
            return [start_utc]
        total_seconds = (end_utc - start_utc).total_seconds()
        step_count = max(1, int(total_seconds / step_seconds))
        times = [start_utc + timedelta(seconds=min(idx * step_seconds, total_seconds)) for idx in range(step_count + 1)]
        if times[-1] != end_utc:
            times.append(end_utc)
        return times

    @staticmethod
    def _angular_separation_array(alt1, az1, alt2, az2) -> np.ndarray:
        """Vectorised angular separation (degrees) between two alt/az arrays."""
        a1 = np.radians(alt1)
        a2 = np.radians(alt2)
        delta_az = np.radians((az1 - az2) % 360.0)
        cos_sep = np.sin(a1) * np.sin(a2) + np.cos(a1) * np.cos(a2) * np.cos(delta_az)
        return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))

    def _iss_altaz_arrays(self, times_utc, satellite, observer, ts):
        """Vectorised ISS topocentric altitude/azimuth (degrees) over the given UTC datetimes."""
        t = ts.from_datetimes(times_utc)
        altitude, azimuth, _ = (satellite - observer).at(t).altaz()
        return (
            np.atleast_1d(np.asarray(altitude.degrees, dtype=float)),
            np.atleast_1d(np.asarray(azimuth.degrees, dtype=float)),
        )

    def _sun_altaz_radius_arrays(self, times_utc, observer, ts, eph):
        """Vectorised Sun alt/az (deg) and apparent angular radius (deg) over the given times."""
        if eph is not None:
            t = ts.from_datetimes(times_utc)
            sun_apparent = (eph["earth"] + observer).at(t).observe(eph["sun"]).apparent()
            altitude, azimuth, _ = sun_apparent.altaz()
            distance_km = np.atleast_1d(np.asarray(sun_apparent.distance().km, dtype=float))
            radius = np.degrees(np.arcsin(np.clip(SOLAR_RADIUS_KM / distance_km, -1.0, 1.0)))
            return (
                np.atleast_1d(np.asarray(altitude.degrees, dtype=float)),
                np.atleast_1d(np.asarray(azimuth.degrees, dtype=float)),
                radius,
            )
        sun_alt, sun_az = self._sun_altaz_arrays_astropy(times_utc)
        return sun_alt, sun_az, np.full(len(times_utc), SOLAR_ANGULAR_RADIUS_FALLBACK_DEG)

    def _sun_altaz_arrays_astropy(self, times_utc):
        """Vectorised Sun alt/az (deg) via Astropy - fallback when the ephemeris is unavailable."""
        astro_time = AstroTime([when.astimezone(timezone.utc) for when in times_utc])
        frame = AltAz(obstime=astro_time, location=self.location)
        altaz = get_sun(astro_time).transform_to(frame)
        return (
            np.atleast_1d(np.asarray(cast(Any, altaz.alt).to_value(u.deg), dtype=float)),
            np.atleast_1d(np.asarray(cast(Any, altaz.az).to_value(u.deg), dtype=float)),
        )

    def _moon_altaz_radius_illum_arrays(self, times_utc, observer, ts, eph):
        """Vectorised Moon alt/az (deg), apparent radius (deg) and illumination (%) over the times."""
        t = ts.from_datetimes(times_utc)
        observed = (eph["earth"] + observer).at(t)
        moon_astrometric = observed.observe(eph["moon"])
        moon_apparent = moon_astrometric.apparent()
        altitude, azimuth, _ = moon_apparent.altaz()
        distance_km = np.atleast_1d(np.asarray(moon_apparent.distance().km, dtype=float))
        radius = np.degrees(np.arcsin(np.clip(LUNAR_RADIUS_KM / distance_km, -1.0, 1.0)))

        moon_ra, moon_dec, _ = moon_apparent.radec()
        sun_apparent = observed.observe(eph["sun"]).apparent()
        sun_ra, sun_dec, _ = sun_apparent.radec()
        elongation = self._angular_separation_array(
            np.atleast_1d(np.asarray(moon_dec.degrees, dtype=float)),
            np.atleast_1d(np.asarray(moon_ra.hours, dtype=float)) * 15.0,
            np.atleast_1d(np.asarray(sun_dec.degrees, dtype=float)),
            np.atleast_1d(np.asarray(sun_ra.hours, dtype=float)) * 15.0,
        )
        illumination = np.clip(50.0 * (1.0 - np.cos(np.radians(elongation))), 0.0, 100.0)
        return (
            np.atleast_1d(np.asarray(altitude.degrees, dtype=float)),
            np.atleast_1d(np.asarray(azimuth.degrees, dtype=float)),
            radius,
            illumination,
        )

    def _find_solar_transits(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
        event_times=None,
        event_types=None,
    ) -> List[Dict[str, Any]]:
        """Find ISS solar transits for the observer using per-pass refinement.

        ``event_times``/``event_types`` may be a pre-computed geometric pass event
        list (shared with lunar-transit detection to avoid a second find_events call);
        when omitted they are computed here.
        """
        if event_times is None or event_types is None:
            event_times, event_types = satellite.find_events(
                observer,
                ts.from_datetime(start_utc),
                ts.from_datetime(end_utc),
                altitude_degrees=GEOMETRIC_PASS_MIN_ALTITUDE_DEG,
            )

        transits: List[Dict[str, Any]] = []
        for pass_start, pass_end in self._iter_geometric_passes(event_times, event_types):
            transit = self._extract_solar_transit_segment(
                start_utc=pass_start,
                end_utc=pass_end,
                satellite=satellite,
                observer=observer,
                ts=ts,
                eph=eph,
            )
            if transit is not None:
                transits.append(transit)

        transits.sort(key=lambda event: event.get("peak_time", ""))
        return transits

    def _extract_solar_transit_segment(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
    ) -> Optional[Dict[str, Any]]:
        """Find a refined ISS solar transit within a daylight geometric pass (vectorised)."""
        if end_utc <= start_utc:
            return None

        # Coarse vectorised scan of the whole pass; reject early when the Sun is
        # below the horizon throughout or the ISS never comes near the disk.
        coarse_times = self._time_grid(start_utc, end_utc, SOLAR_TRANSIT_COARSE_SECONDS)
        iss_alt, iss_az = self._iss_altaz_arrays(coarse_times, satellite, observer, ts)
        sun_alt, sun_az, _ = self._sun_altaz_radius_arrays(coarse_times, observer, ts, eph)
        separation = self._angular_separation_array(iss_alt, iss_az, sun_alt, sun_az)

        valid = (sun_alt >= SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG) & (iss_alt >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG)
        if not bool(valid.any()):
            return None
        masked_sep = np.where(valid, separation, np.inf)
        coarse_idx = int(np.argmin(masked_sep))
        if masked_sep[coarse_idx] > SOLAR_TRANSIT_MAX_APPROACH_DEG:
            return None

        # Fine vectorised scan around the coarse minimum (the window brackets the true minimum).
        peak_time = coarse_times[coarse_idx]
        window = timedelta(seconds=SOLAR_TRANSIT_COARSE_SECONDS)
        fine_start = max(start_utc, peak_time - window)
        fine_end = min(end_utc, peak_time + window)
        fine_times = self._time_grid(fine_start, fine_end, SOLAR_TRANSIT_REFINE_SAMPLE_SECONDS)
        f_iss_alt, f_iss_az = self._iss_altaz_arrays(fine_times, satellite, observer, ts)
        f_sun_alt, f_sun_az, f_radius = self._sun_altaz_radius_arrays(fine_times, observer, ts, eph)
        f_sep = self._angular_separation_array(f_iss_alt, f_iss_az, f_sun_alt, f_sun_az)

        on_disk = (
            (f_sun_alt >= SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG)
            & (f_iss_alt >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG)
            & (f_sep <= f_radius)
        )
        if not bool(on_disk.any()):
            return None

        indices = np.nonzero(on_disk)[0]
        start_i = int(indices[0])
        end_i = int(indices[-1])
        peak_i = int(indices[int(np.argmin(f_sep[indices]))])
        duration_seconds = max(0.0, (fine_times[end_i] - fine_times[start_i]).total_seconds())

        return {
            "start_time": fine_times[start_i].astimezone(self.timezone).isoformat(),
            "peak_time": fine_times[peak_i].astimezone(self.timezone).isoformat(),
            "end_time": fine_times[end_i].astimezone(self.timezone).isoformat(),
            "duration_seconds": round(duration_seconds, 1),
            "minimum_separation_arcmin": round(float(f_sep[peak_i]) * 60.0, 2),
            "solar_radius_arcmin": round(float(f_radius[peak_i]) * 60.0, 2),
            "sun_altitude_deg": round(float(f_sun_alt[peak_i]), 1),
            "sun_azimuth_deg": round(float(f_sun_az[peak_i]), 1),
            "iss_altitude_deg": round(float(f_iss_alt[peak_i]), 1),
            "iss_azimuth_deg": round(float(f_iss_az[peak_i]), 1),
            "pass_type": "solar_transit",
            "is_visible": True,
        }

    def _sample_time_range(
        self, start_utc: datetime, end_utc: datetime, step_seconds: float, sampler
    ) -> List[Dict[str, Any]]:
        """Sample a time range inclusively with a fixed step."""
        if end_utc <= start_utc:
            return [sampler(start_utc)]

        total_seconds = max(0.0, (end_utc - start_utc).total_seconds())
        step_count = max(1, int(total_seconds / step_seconds))
        samples = [sampler(start_utc + timedelta(seconds=idx * step_seconds)) for idx in range(step_count + 1)]
        if samples[-1]["time_utc"] != end_utc:
            samples.append(sampler(end_utc))
        return samples

    def _solar_angular_radius_deg(self, sun_apparent) -> float:
        """Estimate solar apparent angular radius from observer distance."""
        try:
            distance_km = float(sun_apparent.distance().km)
            if distance_km > SOLAR_RADIUS_KM:
                return degrees(asin(SOLAR_RADIUS_KM / distance_km))
        except Exception:
            pass  # Skyfield geometry unavailable — caller uses the fallback constant
        return SOLAR_ANGULAR_RADIUS_FALLBACK_DEG

    def _find_lunar_transits(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
        event_times=None,
        event_types=None,
    ) -> List[Dict[str, Any]]:
        """Find ISS lunar transits for the observer using per-pass refinement.

        ``event_times``/``event_types`` may be a pre-computed geometric pass event
        list (shared with solar-transit detection); when omitted they are computed here.
        """
        if eph is None:
            logger.warning("Ephemeris not loaded; lunar transit detection skipped")
            return []

        if event_times is None or event_types is None:
            event_times, event_types = satellite.find_events(
                observer,
                ts.from_datetime(start_utc),
                ts.from_datetime(end_utc),
                altitude_degrees=GEOMETRIC_PASS_MIN_ALTITUDE_DEG,
            )

        transits: List[Dict[str, Any]] = []
        for pass_start, pass_end in self._iter_geometric_passes(event_times, event_types):
            transit = self._extract_lunar_transit_segment(
                start_utc=pass_start,
                end_utc=pass_end,
                satellite=satellite,
                observer=observer,
                ts=ts,
                eph=eph,
            )
            if transit is not None:
                transits.append(transit)

        transits.sort(key=lambda event: event.get("peak_time", ""))
        return transits

    def _extract_lunar_transit_segment(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
    ) -> Optional[Dict[str, Any]]:
        """Find a refined ISS lunar transit within a geometric pass where the Moon is up (vectorised)."""
        if end_utc <= start_utc:
            return None

        coarse_times = self._time_grid(start_utc, end_utc, LUNAR_TRANSIT_COARSE_SECONDS)
        iss_alt, iss_az = self._iss_altaz_arrays(coarse_times, satellite, observer, ts)
        moon_alt, moon_az, _, _ = self._moon_altaz_radius_illum_arrays(coarse_times, observer, ts, eph)
        separation = self._angular_separation_array(iss_alt, iss_az, moon_alt, moon_az)

        valid = (moon_alt >= LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG) & (iss_alt >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG)
        if not bool(valid.any()):
            return None
        masked_sep = np.where(valid, separation, np.inf)
        coarse_idx = int(np.argmin(masked_sep))
        if masked_sep[coarse_idx] > LUNAR_TRANSIT_MAX_APPROACH_DEG:
            return None

        peak_time = coarse_times[coarse_idx]
        window = timedelta(seconds=LUNAR_TRANSIT_COARSE_SECONDS)
        fine_start = max(start_utc, peak_time - window)
        fine_end = min(end_utc, peak_time + window)
        fine_times = self._time_grid(fine_start, fine_end, LUNAR_TRANSIT_REFINE_SAMPLE_SECONDS)
        f_iss_alt, f_iss_az = self._iss_altaz_arrays(fine_times, satellite, observer, ts)
        f_moon_alt, f_moon_az, f_radius, f_illum = self._moon_altaz_radius_illum_arrays(fine_times, observer, ts, eph)
        f_sep = self._angular_separation_array(f_iss_alt, f_iss_az, f_moon_alt, f_moon_az)

        on_disk = (
            (f_moon_alt >= LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG)
            & (f_iss_alt >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG)
            & (f_sep <= f_radius)
        )
        if not bool(on_disk.any()):
            return None

        indices = np.nonzero(on_disk)[0]
        start_i = int(indices[0])
        end_i = int(indices[-1])
        peak_i = int(indices[int(np.argmin(f_sep[indices]))])
        duration_seconds = max(0.0, (fine_times[end_i] - fine_times[start_i]).total_seconds())

        return {
            "start_time": fine_times[start_i].astimezone(self.timezone).isoformat(),
            "peak_time": fine_times[peak_i].astimezone(self.timezone).isoformat(),
            "end_time": fine_times[end_i].astimezone(self.timezone).isoformat(),
            "duration_seconds": round(duration_seconds, 1),
            "minimum_separation_arcmin": round(float(f_sep[peak_i]) * 60.0, 2),
            "lunar_radius_arcmin": round(float(f_radius[peak_i]) * 60.0, 2),
            "moon_altitude_deg": round(float(f_moon_alt[peak_i]), 1),
            "moon_azimuth_deg": round(float(f_moon_az[peak_i]), 1),
            "moon_illumination_pct": round(float(f_illum[peak_i]), 1),
            "iss_altitude_deg": round(float(f_iss_alt[peak_i]), 1),
            "iss_azimuth_deg": round(float(f_iss_az[peak_i]), 1),
            "pass_type": "lunar_transit",
            "is_visible": True,
        }

    def _lunar_angular_radius_deg(self, moon_apparent) -> float:
        """Estimate lunar apparent angular radius from observer distance."""
        try:
            distance_km = float(moon_apparent.distance().km)
            if distance_km > LUNAR_RADIUS_KM:
                return degrees(asin(LUNAR_RADIUS_KM / distance_km))
        except Exception:
            pass  # Skyfield geometry unavailable — caller uses the fallback constant
        return LUNAR_ANGULAR_RADIUS_FALLBACK_DEG

    def _angular_separation_deg(
        self, altitude1_deg: float, azimuth1_deg: float, altitude2_deg: float, azimuth2_deg: float
    ) -> float:
        """Compute angular separation in local alt/az coordinates."""
        alt1 = radians(altitude1_deg)
        alt2 = radians(altitude2_deg)
        delta_az = radians((azimuth1_deg - azimuth2_deg) % 360.0)
        cos_sep = (sin(alt1) * sin(alt2)) + (cos(alt1) * cos(alt2) * cos(delta_az))
        cos_sep = max(-1.0, min(1.0, cos_sep))
        return degrees(acos(cos_sep))

    def _sample_observation(self, when_utc: datetime, satellite: EarthSatellite, observer, ts, eph) -> Dict[str, Any]:
        """Sample observer-relative ISS geometry and visibility at one instant."""
        event_time = ts.from_datetime(when_utc)
        topocentric = (satellite - observer).at(event_time)
        altitude, azimuth, _ = topocentric.altaz()
        altitude_deg = float(altitude.degrees)
        azimuth_deg = float(azimuth.degrees)

        if eph is not None:
            sun_altitude_deg = self._sun_altitude_deg_skyfield(observer, eph, event_time)
            is_sunlit = bool(topocentric.is_sunlit(eph))
        else:
            sun_altitude_deg = self._sun_altitude_deg(when_utc)
            is_sunlit = True

        is_visible = (
            altitude_deg >= MIN_EVENT_ALTITUDE_DEG
            and sun_altitude_deg <= MAX_VISIBLE_SKY_SUN_ALTITUDE_DEG
            and is_sunlit
        )

        return {
            "time_utc": when_utc,
            "altitude_deg": altitude_deg,
            "azimuth_deg": azimuth_deg,
            "sun_altitude_deg": sun_altitude_deg,
            "is_visible": is_visible,
        }

    def _sun_altitude_deg_skyfield(self, observer, eph, event_time) -> float:
        """Compute Sun altitude with Skyfield at observer location."""
        earth = eph["earth"]
        sun = eph["sun"]
        astrometric = (earth + observer).at(event_time).observe(sun)
        altitude, _, _ = astrometric.apparent().altaz()
        return float(altitude.degrees)

    def _group_consecutive_indices(self, indices: List[int]) -> List[List[int]]:
        """Group sorted indices into consecutive runs."""
        if not indices:
            return []

        groups: List[List[int]] = []
        current_group: List[int] = [indices[0]]

        for index in indices[1:]:
            if index == current_group[-1] + 1:
                current_group.append(index)
            else:
                groups.append(current_group)
                current_group = [index]

        groups.append(current_group)
        return groups

    def _azimuth_to_cardinal(self, azimuth_deg: float) -> str:
        """Convert azimuth in degrees to 16-point compass direction."""
        labels = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
        ]
        normalized = azimuth_deg % 360.0
        index = int((normalized + 11.25) // 22.5) % 16
        return labels[index]

    def _satellite_altitude_deg(self, satellite: EarthSatellite, observer, event_time) -> float:
        """Get ISS altitude (degrees) for a given event time."""
        topocentric = (satellite - observer).at(event_time)
        altitude, _, _ = topocentric.altaz()
        return float(altitude.degrees)

    def _sun_altitude_deg(self, when_utc: datetime) -> float:
        """Compute Sun altitude in degrees for observer at a UTC datetime."""
        astro_time = AstroTime(when_utc)
        frame = AltAz(obstime=astro_time, location=self.location)
        sun_altaz = get_sun(astro_time).transform_to(frame)
        sun_alt = getattr(sun_altaz, "alt", None)
        if sun_alt is None:
            raise ValueError("Could not determine Sun altitude")
        return float(cast(Any, sun_alt.to_value(u.deg)))

    def _sun_alt_az_deg(self, when_utc: datetime) -> Tuple[float, float]:
        """Compute Sun altitude and azimuth in degrees for observer at a UTC datetime."""
        astro_time = AstroTime(when_utc)
        frame = AltAz(obstime=astro_time, location=self.location)
        sun_altaz = get_sun(astro_time).transform_to(frame)
        sun_alt = getattr(sun_altaz, "alt", None)
        sun_az = getattr(sun_altaz, "az", None)
        if sun_alt is None or sun_az is None:
            raise ValueError("Could not determine Sun altitude/azimuth")
        return (
            float(cast(Any, sun_alt.to_value(u.deg))),
            float(cast(Any, sun_az.to_value(u.deg))),
        )

    def _classify_day_night(self, sun_altitude_deg: float) -> str:
        """Classify visibility context based on Sun altitude."""
        if sun_altitude_deg <= -18:
            return "Astronomical Night"
        if sun_altitude_deg <= -12:
            return "Nautical Twilight"
        if sun_altitude_deg <= -6:
            return "Civil Twilight"
        if sun_altitude_deg <= 0:
            return "Twilight"
        return "Daylight"

    def _compute_visibility_score(
        self, peak_altitude_deg: float, duration_minutes: float, sun_altitude_deg: float
    ) -> float:
        """Compute a user-facing visibility score in range 0-100."""
        altitude_component = min(max((peak_altitude_deg - MIN_EVENT_ALTITUDE_DEG) / 70.0, 0.0), 1.0)
        duration_component = min(max(duration_minutes / 10.0, 0.0), 1.0)

        if sun_altitude_deg <= -18:
            lighting_component = 1.0
        elif sun_altitude_deg <= -12:
            lighting_component = 0.8
        elif sun_altitude_deg <= -6:
            lighting_component = 0.55
        elif sun_altitude_deg <= 0:
            lighting_component = 0.35
        else:
            lighting_component = 0.1

        score = (0.65 * altitude_component) + (0.25 * lighting_component) + (0.10 * duration_component)
        return max(0.0, min(100.0, score * 100.0))


def get_iss_passes_report(
    latitude: float,
    longitude: float,
    elevation_m: float,
    timezone_str: str,
    days: int = DEFAULT_FORECAST_DAYS,
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper to generate ISS pass report."""
    try:
        service = ISSPassService(
            latitude=latitude,
            longitude=longitude,
            elevation_m=elevation_m,
            timezone_str=timezone_str,
        )
        return service.get_report(days=days)
    except Exception as e:
        logger.warning(f"Failed to generate ISS passes report: {e}")
        return None


def get_current_position(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    elevation_m: float = 0.0,
) -> Dict[str, Any]:
    """Compute current ISS ground position and ±50-minute ground track from cached TLE.

    Returns a dict with keys:
      latitude, longitude, altitude_km  - current sub-satellite point
      past_track   - list of [lat, lon] for the past 50 minutes (1-min steps)
      future_track - list of [lat, lon] for the next 50 minutes (1-min steps),
                     starting at the current position
      timestamp    - ISO 8601 UTC instant used for the computation
      observer      - (optional) visibility data from the configured location
    """
    cached = _get_cached_tle(max_age_seconds=None)
    if cached is None:
        raise RuntimeError("No ISS TLE available for position computation")

    line1, line2, _ = cached
    ts = SKYFIELD_LOADER.timescale()
    satellite = EarthSatellite(line1, line2, "ISS (ZARYA)", ts)

    now_utc = datetime.now(timezone.utc)
    now_t = ts.from_datetime(now_utc)
    subpoint = wgs84.subpoint(satellite.at(now_t))
    lat = float(subpoint.latitude.degrees)  # type: ignore[arg-type]
    lon = float(subpoint.longitude.degrees)  # type: ignore[arg-type]
    alt_km = float(subpoint.elevation.km)  # type: ignore[arg-type]

    # Ground track: use cached value when fresh, recompute otherwise.
    # This avoids 101 propagations per request and limits track computation to once per 5 min.
    now_ts = _utc_timestamp()
    with _TRACK_CACHE_LOCK:
        cache_age = now_ts - int(_TRACK_CACHE.get("computed_at", 0))
        if cache_age < _TRACK_CACHE_TTL_SECONDS and _TRACK_CACHE.get("past_track") is not None:
            past_track = _TRACK_CACHE["past_track"]
            future_track = _TRACK_CACHE["future_track"]
        else:
            past_track = []
            for delta_min in range(-50, 0):
                t = ts.from_datetime(now_utc + timedelta(minutes=delta_min))
                sp = wgs84.subpoint(satellite.at(t))
                past_track.append([float(sp.latitude.degrees), float(sp.longitude.degrees)])  # type: ignore[arg-type]

            # Future track starts at the current position so the two polylines connect
            future_track = [[lat, lon]]
            for delta_min in range(1, 51):
                t = ts.from_datetime(now_utc + timedelta(minutes=delta_min))
                sp = wgs84.subpoint(satellite.at(t))
                future_track.append([float(sp.latitude.degrees), float(sp.longitude.degrees)])  # type: ignore[arg-type]

            _TRACK_CACHE["past_track"] = past_track
            _TRACK_CACHE["future_track"] = future_track
            _TRACK_CACHE["computed_at"] = now_ts

    result: Dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "altitude_km": round(alt_km, 1),
        "past_track": past_track,
        "future_track": future_track,
        "timestamp": now_utc.isoformat(),
    }

    # Observer-relative geometry and current visibility (only when location is configured)
    if latitude is not None and longitude is not None:
        observer = wgs84.latlon(latitude, longitude, elevation_m=elevation_m)
        topocentric = (satellite - observer).at(now_t)
        _obs_alt, _obs_az, _ = topocentric.altaz()
        obs_altitude_deg = float(_obs_alt.degrees)  # type: ignore[arg-type]
        obs_azimuth_deg = float(_obs_az.degrees)  # type: ignore[arg-type]

        eph = _get_ephemeris()

        if eph is not None:
            earth = eph["earth"]
            sun_obj = eph["sun"]
            obs_loc_skyfield = wgs84.latlon(latitude, longitude, elevation_m=elevation_m)
            sun_astrometric = (earth + obs_loc_skyfield).at(now_t).observe(sun_obj)
            sun_altitude_deg = float(sun_astrometric.apparent().altaz()[0].degrees)
            is_sunlit = bool(topocentric.is_sunlit(eph))
        else:
            obs_earth_loc = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation_m * u.m)
            astro_time = AstroTime(now_utc)
            frame = AltAz(obstime=astro_time, location=obs_earth_loc)
            sun_alt = get_sun(astro_time).transform_to(frame).alt
            sun_altitude_deg = float(cast(Angle, sun_alt).deg)  # type: ignore[arg-type]
            is_sunlit = True

        is_visible = (
            obs_altitude_deg >= MIN_EVENT_ALTITUDE_DEG
            and sun_altitude_deg <= MAX_VISIBLE_SKY_SUN_ALTITUDE_DEG
            and is_sunlit
        )

        result["observer"] = {
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": elevation_m,
            "iss_altitude_deg": round(obs_altitude_deg, 1),
            "iss_azimuth_deg": round(obs_azimuth_deg, 1),
            "sun_altitude_deg": round(sun_altitude_deg, 1),
            "is_visible": is_visible,
        }

    return result
