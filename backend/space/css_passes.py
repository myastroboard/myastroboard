"""
CSS (China Space Station) pass prediction service.

Computes upcoming Chinese Space Station (Tiangong/CSS, NORAD 48274) passages for the
configured observer location using current TLE data and returns local-time windows
with a visibility score and day/night visibility classification.

Architecture mirrors iss_passes.py exactly — all state is separate so both stations
run as independent parallel cache jobs without any shared mutable data.
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
import requests
import astropy.units as u
from astropy.time import Time as AstroTime
from astropy.coordinates import Angle, EarthLocation, AltAz, get_sun
from skyfield.api import Loader, EarthSatellite, wgs84

from utils.constants import CACHE_TTL, DATA_DIR_CACHE
from utils.logging_config import get_logger
from utils import load_json_file, save_json_file

logger = get_logger(__name__)

# Re-use the same Skyfield loader/cache as the ISS module.
SKYFIELD_CACHE_DIR = os.path.join(DATA_DIR_CACHE, 'skyfield')
os.makedirs(SKYFIELD_CACHE_DIR, exist_ok=True)
SKYFIELD_LOADER = Loader(SKYFIELD_CACHE_DIR)

# TLE sources in priority order for NORAD 48274 (CSS / Tiangong).
CSS_TLE_URLS = [
    "https://celestrak.org/NORAD/elements/gp.php?CATNR=48274&FORMAT=TLE",
    "https://tle.ivanstanojevic.me/api/tle/48274",
]
REQUEST_TIMEOUT_SECONDS = 10
CELESTRAK_TIMEOUT_BLOCK_THRESHOLD = 3
DEFAULT_FORECAST_DAYS = 20
MAX_FORECAST_DAYS = 30
MIN_EVENT_ALTITUDE_DEG = 10.0
MAX_VISIBLE_SKY_SUN_ALTITUDE_DEG = -4.0
VISIBILITY_SAMPLE_SECONDS = 5
GEOMETRIC_PASS_MIN_ALTITUDE_DEG = 0.0
SOLAR_TRANSIT_SAMPLE_SECONDS = 1.0
SOLAR_TRANSIT_REFINE_WINDOW_SECONDS = 1.0
SOLAR_TRANSIT_REFINE_SAMPLE_SECONDS = 0.1
SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG = 0.0
SOLAR_ANGULAR_RADIUS_FALLBACK_DEG = 0.2666
SOLAR_RADIUS_KM = 695700.0
LUNAR_TRANSIT_SAMPLE_SECONDS = 1.0
LUNAR_TRANSIT_REFINE_WINDOW_SECONDS = 1.0
LUNAR_TRANSIT_REFINE_SAMPLE_SECONDS = 0.1
LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG = 5.0
LUNAR_ANGULAR_RADIUS_FALLBACK_DEG = 0.2615
LUNAR_RADIUS_KM = 1737.4
CSS_TLE_CACHE_FILE = os.path.join(DATA_DIR_CACHE, 'css_tle_cache.json')
CSS_TLE_MAX_AGE_SECONDS = 6 * 60 * 60
CSS_TLE_FAILURE_COOLDOWN_SECONDS = 3 * 60 * 60
CELESTRAK_USAGE_POLICY_URL = "https://celestrak.org/usage-policy.php"
CELESTRAK_ADDENDUM_URL = "https://celestrak.org/NORAD/documentation/gp-data-formats.php#addendum"
CELESTRAK_CSS_QUERY_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=48274&FORMAT=TLE"

# Server-side ground-track cache for CSS: recompute the ±50-min orbit path at most once per 5 min.
_CSS_TRACK_CACHE: Dict[str, Any] = {}
_CSS_TRACK_CACHE_LOCK = threading.Lock()
_CSS_TRACK_CACHE_TTL_SECONDS = 300  # 5 minutes


def _utc_timestamp() -> int:
    return int(time.time())


def _read_css_tle_cache() -> Dict[str, Any]:
    payload = load_json_file(CSS_TLE_CACHE_FILE, default={})
    return payload if isinstance(payload, dict) else {}


def _write_css_tle_cache(payload: Dict[str, Any]) -> None:
    save_json_file(CSS_TLE_CACHE_FILE, payload)


def _get_cached_css_tle(max_age_seconds: Optional[int] = None) -> Optional[Tuple[str, str, int]]:
    cache = _read_css_tle_cache()
    line1 = str(cache.get('line1') or '').strip()
    line2 = str(cache.get('line2') or '').strip()
    fetched_at = int(cache.get('fetched_at') or 0)
    if not line1 or not line2 or fetched_at <= 0:
        return None

    age = _utc_timestamp() - fetched_at
    if max_age_seconds is not None and age > max_age_seconds:
        return None

    return line1, line2, fetched_at


def _set_cached_css_tle(line1: str, line2: str) -> None:
    payload = _read_css_tle_cache()
    payload['line1'] = line1
    payload['line2'] = line2
    payload['fetched_at'] = _utc_timestamp()
    payload['last_error_at'] = None
    _write_css_tle_cache(payload)


def _source_name_from_url(source_url: str) -> str:
    hostname = (urlparse(source_url or "").hostname or "").lower()
    if hostname == "celestrak.org" or hostname.endswith(".celestrak.org"):
        return "Celestrak"
    if hostname == "tle.ivanstanojevic.me":
        return "TLE API (ivanstanojevic.me)"
    return "Unknown"


def _is_celestrak_url(candidate_url: str) -> bool:
    hostname = (urlparse(candidate_url or "").hostname or "").lower()
    return hostname == "celestrak.org" or hostname.endswith(".celestrak.org")


def _set_cached_css_tle_with_source(line1: str, line2: str, source_url: str) -> None:
    payload = _read_css_tle_cache()
    payload['line1'] = line1
    payload['line2'] = line2
    payload['fetched_at'] = _utc_timestamp()
    payload['last_error_at'] = None
    payload['last_source_url'] = source_url
    payload['last_source_name'] = _source_name_from_url(source_url)
    _write_css_tle_cache(payload)


def get_css_tle_source_info() -> Dict[str, Any]:
    payload = _read_css_tle_cache()
    return {
        "name": str(payload.get("last_source_name") or "").strip(),
        "url": str(payload.get("last_source_url") or "").strip(),
        "fetched_at": int(payload.get("fetched_at") or 0),
    }


def _set_css_tle_error_timestamp() -> None:
    payload = _read_css_tle_cache()
    payload['last_error_at'] = _utc_timestamp()
    _write_css_tle_cache(payload)


def _in_css_tle_failure_cooldown() -> bool:
    payload = _read_css_tle_cache()
    last_error_at = int(payload.get('last_error_at') or 0)
    if last_error_at <= 0:
        return False
    return (_utc_timestamp() - last_error_at) < CSS_TLE_FAILURE_COOLDOWN_SECONDS


def _set_css_celestrak_block(status_code: int, reason: str, source_url: str) -> None:
    payload = _read_css_tle_cache()
    payload['celestrak_blocked'] = True
    payload['celestrak_blocked_at'] = _utc_timestamp()
    payload['celestrak_blocked_status_code'] = int(status_code)
    payload['celestrak_blocked_reason'] = reason
    payload['celestrak_blocked_source_url'] = source_url
    _write_css_tle_cache(payload)


def _reset_css_celestrak_timeout_streak() -> None:
    payload = _read_css_tle_cache()
    payload['celestrak_timeout_streak'] = 0
    payload['celestrak_last_timeout_at'] = None
    payload['celestrak_last_timeout_reason'] = None
    payload['celestrak_last_timeout_source_url'] = None
    _write_css_tle_cache(payload)


def _increment_css_celestrak_timeout_streak(reason: str, source_url: str) -> int:
    payload = _read_css_tle_cache()
    streak = int(payload.get('celestrak_timeout_streak') or 0) + 1
    payload['celestrak_timeout_streak'] = streak
    payload['celestrak_last_timeout_at'] = _utc_timestamp()
    payload['celestrak_last_timeout_reason'] = reason
    payload['celestrak_last_timeout_source_url'] = source_url
    _write_css_tle_cache(payload)
    return streak


def _is_celestrak_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    message = str(exc).lower()
    return "timed out" in message or "connect timeout" in message


def _clear_css_celestrak_block(reset_failure_cooldown: bool = True) -> None:
    payload = _read_css_tle_cache()
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
    _write_css_tle_cache(payload)


def get_css_celestrak_status() -> Dict[str, Any]:
    payload = _read_css_tle_cache()
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
        "manual_check_url": CELESTRAK_CSS_QUERY_URL,
    }


def clear_css_celestrak_block_flag() -> Dict[str, Any]:
    """Clear persisted Celestrak block flag after manual operator confirmation."""
    _clear_css_celestrak_block(reset_failure_cooldown=True)
    return get_css_celestrak_status()


class CSSPassService:
    """Service that computes CSS (Tiangong) visible passes for an observer location."""

    def __init__(self, latitude: float, longitude: float, elevation_m: float, timezone_str: str):
        self.latitude = latitude
        self.longitude = longitude
        self.elevation_m = elevation_m
        self.timezone = ZoneInfo(timezone_str)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation_m * u.m)

    def get_report(self, days: int = DEFAULT_FORECAST_DAYS) -> Dict[str, Any]:
        """Generate CSS pass report for the requested window."""
        forecast_days = max(1, min(int(days), MAX_FORECAST_DAYS))

        line1, line2 = self._fetch_css_tle()

        ts = SKYFIELD_LOADER.timescale()
        satellite = EarthSatellite(line1, line2, "CSS (TIANHE)", ts)
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
        solar_transits = self._find_solar_transits(now_utc, end_utc, satellite, observer, ts, eph)
        next_solar_transit = solar_transits[0] if solar_transits else None
        lunar_transits = self._find_lunar_transits(now_utc, end_utc, satellite, observer, ts, eph)
        next_lunar_transit = lunar_transits[0] if lunar_transits else None

        return {
            "timestamp": datetime.now(self.timezone).isoformat(),
            "station": "CSS",
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
            "celestrak_status": get_css_celestrak_status(),
            "tle_source": get_css_tle_source_info(),
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
        try:
            return SKYFIELD_LOADER('de421.bsp')
        except Exception as exc:
            logger.warning(f"Could not load ephemeris file de421.bsp: {exc}")
            return None

    def _fetch_css_tle(self) -> Tuple[str, str]:
        """Fetch latest CSS TLE with strict handling for Celestrak policy errors."""
        cached_recent = _get_cached_css_tle(max_age_seconds=CSS_TLE_MAX_AGE_SECONDS)
        if cached_recent is not None:
            line1, line2, _ = cached_recent
            return line1, line2

        if _in_css_tle_failure_cooldown():
            cached_any = _get_cached_css_tle(max_age_seconds=None)
            if cached_any is not None:
                line1, line2, fetched_at = cached_any
                age_hours = (_utc_timestamp() - fetched_at) / 3600.0
                logger.warning(f"CSS TLE fetch is in cooldown; reusing stale cached TLE ({age_hours:.1f}h old)")
                return line1, line2
            raise RuntimeError('CSS TLE fetch is in cooldown and no cached TLE is available')

        last_error: Optional[Exception] = None
        celestrak_status = get_css_celestrak_status()

        for tle_url in CSS_TLE_URLS:
            if celestrak_status.get("blocked") and _is_celestrak_url(tle_url):
                logger.warning("Celestrak is flagged as blocked for CSS; skipping Celestrak query until manually reset")
                continue

            try:
                response = requests.get(tle_url, timeout=REQUEST_TIMEOUT_SECONDS)
                status_code = int(getattr(response, "status_code", 200) or 0)

                if _is_celestrak_url(tle_url) and status_code != 200:
                    _reset_css_celestrak_timeout_streak()
                    _set_css_tle_error_timestamp()
                    _set_css_celestrak_block(
                        status_code=status_code,
                        reason=f"HTTP {status_code}",
                        source_url=tle_url,
                    )
                    raise RuntimeError(
                        f"Celestrak returned HTTP {status_code} for CSS TLE;"
                        " stopping TLE queries and requiring manual investigation"
                    )

                response.raise_for_status()
                line1, line2 = self._parse_css_tle_from_response(response.text)
                _set_cached_css_tle_with_source(line1, line2, tle_url)
                if _is_celestrak_url(tle_url):
                    _reset_css_celestrak_timeout_streak()
                    _clear_css_celestrak_block(reset_failure_cooldown=True)
                return line1, line2
            except Exception as exc:
                if _is_celestrak_url(tle_url):
                    status_message = str(exc).upper()
                    if (isinstance(exc, RuntimeError) and "CELESTRAK RETURNED HTTP" in status_message) or (
                        "403" in status_message
                    ):
                        _set_css_tle_error_timestamp()
                        _set_css_celestrak_block(
                            status_code=403 if "403" in status_message else 0,
                            reason=str(exc),
                            source_url=tle_url,
                        )
                        logger.error(
                            "Celestrak rejected a CSS TLE request with a non-200 response. "
                            "Automatic queries have been stopped and human intervention is required. "
                            f"See {CELESTRAK_USAGE_POLICY_URL} and "
                            f"{CELESTRAK_ADDENDUM_URL}"
                        )
                        cached_any = _get_cached_css_tle(max_age_seconds=None)
                        if cached_any is not None:
                            line1, line2, fetched_at = cached_any
                            age_hours = (_utc_timestamp() - fetched_at) / 3600.0
                            logger.warning(
                                f"Celestrak policy block for CSS; reusing stale cached TLE ({age_hours:.1f}h old)"
                            )
                            return line1, line2
                        raise RuntimeError(
                            "Celestrak returned a non-200 response for CSS TLE and no cached TLE is available; "
                            "manual intervention required"
                        ) from exc

                    if _is_celestrak_timeout_error(exc):
                        timeout_streak = _increment_css_celestrak_timeout_streak(str(exc), tle_url)
                        logger.warning(
                            "Celestrak CSS timeout detected (%s/%s consecutive): %s",
                            timeout_streak,
                            CELESTRAK_TIMEOUT_BLOCK_THRESHOLD,
                            exc,
                        )
                        if timeout_streak >= CELESTRAK_TIMEOUT_BLOCK_THRESHOLD:
                            _set_css_tle_error_timestamp()
                            _set_css_celestrak_block(
                                status_code=0,
                                reason=(
                                    "Consecutive Celestrak timeout threshold reached "
                                    f"({CELESTRAK_TIMEOUT_BLOCK_THRESHOLD})"
                                ),
                                source_url=tle_url,
                            )
                            logger.error(
                                "Celestrak was auto-flagged as blocked for CSS after %s consecutive timeouts. "
                                "Automatic Celestrak CSS queries are paused until manual reset.",
                                CELESTRAK_TIMEOUT_BLOCK_THRESHOLD,
                            )
                    else:
                        _reset_css_celestrak_timeout_streak()

                last_error = exc
                logger.debug(f"CSS TLE fetch failed for {tle_url}: {exc}")

        _set_css_tle_error_timestamp()
        cached_any = _get_cached_css_tle(max_age_seconds=None)
        if cached_any is not None:
            line1, line2, fetched_at = cached_any
            age_hours = (_utc_timestamp() - fetched_at) / 3600.0
            logger.warning(f"All CSS TLE sources failed; using stale cached TLE ({age_hours:.1f}h old)")
            return line1, line2

        logger.warning("All CSS TLE sources failed and no cached TLE is available")
        raise RuntimeError(f"Failed to fetch CSS TLE from all sources: {last_error}")

    def _parse_css_tle_from_response(self, response_text: str) -> Tuple[str, str]:
        """Extract CSS TLE pair from a response payload (JSON or plain-text)."""
        try:
            data = json.loads(response_text)
            line1 = str(data.get("line1") or "").strip()
            line2 = str(data.get("line2") or "").strip()
            if line1.startswith("1 ") and line2.startswith("2 "):
                return line1, line2
        except (json.JSONDecodeError, AttributeError, TypeError):
            # Response is not JSON — expected for plain-text TLE sources; fall through to line-based parsing
            pass

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
                if "CSS" in previous_name or "TIANHE" in previous_name or "TIANGONG" in previous_name:
                    return pair

        if first_tle_pair is not None:
            return first_tle_pair

        raise ValueError("Could not parse CSS TLE from response payload")

    def _build_passes(
        self, event_times, event_types, satellite: EarthSatellite, observer, ts, eph
    ) -> List[Dict[str, Any]]:
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

    def _find_solar_transits(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
    ) -> List[Dict[str, Any]]:
        event_times, event_types = satellite.find_events(
            observer,
            ts.from_datetime(start_utc),
            ts.from_datetime(end_utc),
            altitude_degrees=GEOMETRIC_PASS_MIN_ALTITUDE_DEG,
        )

        transits: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}

        for event_time, event_type in zip(event_times, event_types):
            dt_utc = event_time.utc_datetime().replace(tzinfo=timezone.utc)

            if event_type == 0:
                current = {"start": dt_utc}
                continue

            if event_type == 1:
                if current:
                    current["peak"] = dt_utc
                continue

            if event_type == 2:
                if not current or "start" not in current:
                    current = {}
                    continue

                current["end"] = dt_utc
                transit = self._extract_solar_transit_segment(
                    start_utc=current["start"],
                    end_utc=current["end"],
                    satellite=satellite,
                    observer=observer,
                    ts=ts,
                    eph=eph,
                )
                if transit is not None:
                    transits.append(transit)

                current = {}

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
        if end_utc <= start_utc:
            return None

        samples = self._sample_time_range(
            start_utc=start_utc,
            end_utc=end_utc,
            step_seconds=SOLAR_TRANSIT_SAMPLE_SECONDS,
            sampler=lambda when: self._sample_solar_transit_observation(when, satellite, observer, ts, eph),
        )

        candidate_indices = [
            idx
            for idx, sample in enumerate(samples)
            if sample["sun_altitude_deg"] >= SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG
            and sample["css_altitude_deg"] >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG
            and sample["separation_deg"] <= sample["solar_radius_deg"]
        ]
        if not candidate_indices:
            return None

        segments = self._group_consecutive_indices(candidate_indices)
        best_segment = min(
            segments,
            key=lambda segment: min(samples[idx]["separation_deg"] for idx in segment),
        )
        coarse_peak = min((samples[idx] for idx in best_segment), key=lambda sample: sample["separation_deg"])

        refined_start = max(start_utc, coarse_peak["time_utc"] - timedelta(seconds=SOLAR_TRANSIT_REFINE_WINDOW_SECONDS))
        refined_end = min(end_utc, coarse_peak["time_utc"] + timedelta(seconds=SOLAR_TRANSIT_REFINE_WINDOW_SECONDS))
        refined_samples = self._sample_time_range(
            start_utc=refined_start,
            end_utc=refined_end,
            step_seconds=SOLAR_TRANSIT_REFINE_SAMPLE_SECONDS,
            sampler=lambda when: self._sample_solar_transit_observation(when, satellite, observer, ts, eph),
        )

        refined_candidates = [
            sample
            for sample in refined_samples
            if sample["sun_altitude_deg"] >= SOLAR_TRANSIT_MIN_SUN_ALTITUDE_DEG
            and sample["css_altitude_deg"] >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG
            and sample["separation_deg"] <= sample["solar_radius_deg"]
        ]
        if not refined_candidates:
            refined_candidates = [coarse_peak]

        start_sample = refined_candidates[0]
        end_sample = refined_candidates[-1]
        peak_sample = min(refined_candidates, key=lambda sample: sample["separation_deg"])
        duration_seconds = max(0.0, (end_sample["time_utc"] - start_sample["time_utc"]).total_seconds())

        return {
            "start_time": start_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "peak_time": peak_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "end_time": end_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "duration_seconds": round(duration_seconds, 1),
            "minimum_separation_arcmin": round(float(peak_sample["separation_deg"]) * 60.0, 2),
            "solar_radius_arcmin": round(float(peak_sample["solar_radius_deg"]) * 60.0, 2),
            "sun_altitude_deg": round(float(peak_sample["sun_altitude_deg"]), 1),
            "sun_azimuth_deg": round(float(peak_sample["sun_azimuth_deg"]), 1),
            "css_altitude_deg": round(float(peak_sample["css_altitude_deg"]), 1),
            "css_azimuth_deg": round(float(peak_sample["css_azimuth_deg"]), 1),
            "pass_type": "solar_transit",
            "is_visible": True,
        }

    def _sample_time_range(
        self, start_utc: datetime, end_utc: datetime, step_seconds: float, sampler
    ) -> List[Dict[str, Any]]:
        if end_utc <= start_utc:
            return [sampler(start_utc)]

        total_seconds = max(0.0, (end_utc - start_utc).total_seconds())
        step_count = max(1, int(total_seconds / step_seconds))
        samples = [sampler(start_utc + timedelta(seconds=idx * step_seconds)) for idx in range(step_count + 1)]
        if samples[-1]["time_utc"] != end_utc:
            samples.append(sampler(end_utc))
        return samples

    def _sample_solar_transit_observation(
        self, when_utc: datetime, satellite: EarthSatellite, observer, ts, eph
    ) -> Dict[str, Any]:
        event_time = ts.from_datetime(when_utc)
        topocentric = (satellite - observer).at(event_time)
        css_altitude, css_azimuth, _ = topocentric.altaz()
        css_altitude_deg = float(css_altitude.degrees)
        css_azimuth_deg = float(css_azimuth.degrees)

        if eph is not None:
            earth = eph["earth"]
            sun = eph["sun"]
            sun_apparent = (earth + observer).at(event_time).observe(sun).apparent()
            sun_altitude, sun_azimuth, _ = sun_apparent.altaz()
            sun_altitude_deg = float(sun_altitude.degrees)
            sun_azimuth_deg = float(sun_azimuth.degrees)
            solar_radius_deg = self._solar_angular_radius_deg(sun_apparent)
        else:
            sun_altitude_deg, sun_azimuth_deg = self._sun_alt_az_deg(when_utc)
            solar_radius_deg = SOLAR_ANGULAR_RADIUS_FALLBACK_DEG

        separation_deg = self._angular_separation_deg(
            css_altitude_deg,
            css_azimuth_deg,
            sun_altitude_deg,
            sun_azimuth_deg,
        )

        return {
            "time_utc": when_utc,
            "css_altitude_deg": css_altitude_deg,
            "css_azimuth_deg": css_azimuth_deg,
            "sun_altitude_deg": sun_altitude_deg,
            "sun_azimuth_deg": sun_azimuth_deg,
            "solar_radius_deg": solar_radius_deg,
            "separation_deg": separation_deg,
        }

    def _solar_angular_radius_deg(self, sun_apparent) -> float:
        try:
            distance_km = float(sun_apparent.distance().km)
            if distance_km > SOLAR_RADIUS_KM:
                return degrees(asin(SOLAR_RADIUS_KM / distance_km))
        except Exception as exc:
            logger.debug("Solar angular radius calculation failed, using fallback: %s", exc)
        return SOLAR_ANGULAR_RADIUS_FALLBACK_DEG

    def _find_lunar_transits(
        self,
        start_utc: datetime,
        end_utc: datetime,
        satellite: EarthSatellite,
        observer,
        ts,
        eph,
    ) -> List[Dict[str, Any]]:
        if eph is None:
            logger.warning("Ephemeris not loaded; CSS lunar transit detection skipped")
            return []

        event_times, event_types = satellite.find_events(
            observer,
            ts.from_datetime(start_utc),
            ts.from_datetime(end_utc),
            altitude_degrees=GEOMETRIC_PASS_MIN_ALTITUDE_DEG,
        )

        transits: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}

        for event_time, event_type in zip(event_times, event_types):
            dt_utc = event_time.utc_datetime().replace(tzinfo=timezone.utc)

            if event_type == 0:
                current = {"start": dt_utc}
                continue

            if event_type == 1:
                if current:
                    current["peak"] = dt_utc
                continue

            if event_type == 2:
                if not current or "start" not in current:
                    current = {}
                    continue

                current["end"] = dt_utc
                transit = self._extract_lunar_transit_segment(
                    start_utc=current["start"],
                    end_utc=current["end"],
                    satellite=satellite,
                    observer=observer,
                    ts=ts,
                    eph=eph,
                )
                if transit is not None:
                    transits.append(transit)

                current = {}

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
        if end_utc <= start_utc:
            return None

        samples = self._sample_time_range(
            start_utc=start_utc,
            end_utc=end_utc,
            step_seconds=LUNAR_TRANSIT_SAMPLE_SECONDS,
            sampler=lambda when: self._sample_lunar_transit_observation(when, satellite, observer, ts, eph),
        )

        candidate_indices = [
            idx
            for idx, sample in enumerate(samples)
            if sample["moon_altitude_deg"] >= LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG
            and sample["css_altitude_deg"] >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG
            and sample["separation_deg"] <= sample["lunar_radius_deg"]
        ]
        if not candidate_indices:
            return None

        segments = self._group_consecutive_indices(candidate_indices)
        best_segment = min(
            segments,
            key=lambda segment: min(samples[idx]["separation_deg"] for idx in segment),
        )
        coarse_peak = min((samples[idx] for idx in best_segment), key=lambda sample: sample["separation_deg"])

        refined_start = max(start_utc, coarse_peak["time_utc"] - timedelta(seconds=LUNAR_TRANSIT_REFINE_WINDOW_SECONDS))
        refined_end = min(end_utc, coarse_peak["time_utc"] + timedelta(seconds=LUNAR_TRANSIT_REFINE_WINDOW_SECONDS))
        refined_samples = self._sample_time_range(
            start_utc=refined_start,
            end_utc=refined_end,
            step_seconds=LUNAR_TRANSIT_REFINE_SAMPLE_SECONDS,
            sampler=lambda when: self._sample_lunar_transit_observation(when, satellite, observer, ts, eph),
        )

        refined_candidates = [
            sample
            for sample in refined_samples
            if sample["moon_altitude_deg"] >= LUNAR_TRANSIT_MIN_MOON_ALTITUDE_DEG
            and sample["css_altitude_deg"] >= GEOMETRIC_PASS_MIN_ALTITUDE_DEG
            and sample["separation_deg"] <= sample["lunar_radius_deg"]
        ]
        if not refined_candidates:
            refined_candidates = [coarse_peak]

        start_sample = refined_candidates[0]
        end_sample = refined_candidates[-1]
        peak_sample = min(refined_candidates, key=lambda sample: sample["separation_deg"])
        duration_seconds = max(0.0, (end_sample["time_utc"] - start_sample["time_utc"]).total_seconds())

        return {
            "start_time": start_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "peak_time": peak_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "end_time": end_sample["time_utc"].astimezone(self.timezone).isoformat(),
            "duration_seconds": round(duration_seconds, 1),
            "minimum_separation_arcmin": round(float(peak_sample["separation_deg"]) * 60.0, 2),
            "lunar_radius_arcmin": round(float(peak_sample["lunar_radius_deg"]) * 60.0, 2),
            "moon_altitude_deg": round(float(peak_sample["moon_altitude_deg"]), 1),
            "moon_azimuth_deg": round(float(peak_sample["moon_azimuth_deg"]), 1),
            "moon_illumination_pct": round(float(peak_sample.get("moon_illumination_pct", 0.0)), 1),
            "css_altitude_deg": round(float(peak_sample["css_altitude_deg"]), 1),
            "css_azimuth_deg": round(float(peak_sample["css_azimuth_deg"]), 1),
            "pass_type": "lunar_transit",
            "is_visible": True,
        }

    def _sample_lunar_transit_observation(
        self, when_utc: datetime, satellite: EarthSatellite, observer, ts, eph
    ) -> Dict[str, Any]:
        event_time = ts.from_datetime(when_utc)
        topocentric = (satellite - observer).at(event_time)
        css_altitude, css_azimuth, _ = topocentric.altaz()
        css_altitude_deg = float(css_altitude.degrees)
        css_azimuth_deg = float(css_azimuth.degrees)

        earth = eph["earth"]
        moon = eph["moon"]
        moon_apparent = (earth + observer).at(event_time).observe(moon).apparent()
        moon_altitude, moon_azimuth, _ = moon_apparent.altaz()
        moon_altitude_deg = float(moon_altitude.degrees)
        moon_azimuth_deg = float(moon_azimuth.degrees)
        lunar_radius_deg = self._lunar_angular_radius_deg(moon_apparent)

        try:
            sun = eph["sun"]
            moon_astrometric = (earth + observer).at(event_time).observe(moon)
            sun_astrometric = (earth + observer).at(event_time).observe(sun)
            moon_ra, moon_dec, _ = moon_astrometric.apparent().radec()
            sun_ra, sun_dec, _ = sun_astrometric.apparent().radec()
            elongation_deg = self._angular_separation_deg(
                float(moon_dec.degrees),
                float(moon_ra.hours) * 15.0,
                float(sun_dec.degrees),
                float(sun_ra.hours) * 15.0,
            )
            moon_illumination_pct = 50.0 * (1.0 - cos(radians(elongation_deg))) * 100.0 / 100.0
            moon_illumination_pct = max(0.0, min(100.0, moon_illumination_pct))
        except Exception:
            moon_illumination_pct = 0.0

        separation_deg = self._angular_separation_deg(
            css_altitude_deg,
            css_azimuth_deg,
            moon_altitude_deg,
            moon_azimuth_deg,
        )

        return {
            "time_utc": when_utc,
            "css_altitude_deg": css_altitude_deg,
            "css_azimuth_deg": css_azimuth_deg,
            "moon_altitude_deg": moon_altitude_deg,
            "moon_azimuth_deg": moon_azimuth_deg,
            "lunar_radius_deg": lunar_radius_deg,
            "moon_illumination_pct": moon_illumination_pct,
            "separation_deg": separation_deg,
        }

    def _lunar_angular_radius_deg(self, moon_apparent) -> float:
        try:
            distance_km = float(moon_apparent.distance().km)
            if distance_km > LUNAR_RADIUS_KM:
                return degrees(asin(LUNAR_RADIUS_KM / distance_km))
        except Exception as exc:
            logger.debug("Lunar angular radius calculation failed, using fallback: %s", exc)
        return LUNAR_ANGULAR_RADIUS_FALLBACK_DEG

    def _angular_separation_deg(
        self, altitude1_deg: float, azimuth1_deg: float, altitude2_deg: float, azimuth2_deg: float
    ) -> float:
        alt1 = radians(altitude1_deg)
        alt2 = radians(altitude2_deg)
        delta_az = radians((azimuth1_deg - azimuth2_deg) % 360.0)
        cos_sep = (sin(alt1) * sin(alt2)) + (cos(alt1) * cos(alt2) * cos(delta_az))
        cos_sep = max(-1.0, min(1.0, cos_sep))
        return degrees(acos(cos_sep))

    def _sample_observation(self, when_utc: datetime, satellite: EarthSatellite, observer, ts, eph) -> Dict[str, Any]:
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
        earth = eph["earth"]
        sun = eph["sun"]
        astrometric = (earth + observer).at(event_time).observe(sun)
        altitude, _, _ = astrometric.apparent().altaz()
        return float(altitude.degrees)

    def _group_consecutive_indices(self, indices: List[int]) -> List[List[int]]:
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
        topocentric = (satellite - observer).at(event_time)
        altitude, _, _ = topocentric.altaz()
        return float(altitude.degrees)

    def _sun_altitude_deg(self, when_utc: datetime) -> float:
        astro_time = AstroTime(when_utc)
        frame = AltAz(obstime=astro_time, location=self.location)
        sun_altaz = get_sun(astro_time).transform_to(frame)
        sun_alt = getattr(sun_altaz, "alt", None)
        if sun_alt is None:
            raise ValueError("Could not determine Sun altitude")
        return float(cast(Any, sun_alt.to_value(u.deg)))

    def _sun_alt_az_deg(self, when_utc: datetime) -> Tuple[float, float]:
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


def get_css_passes_report(
    latitude: float,
    longitude: float,
    elevation_m: float,
    timezone_str: str,
    days: int = DEFAULT_FORECAST_DAYS,
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper to generate CSS pass report."""
    try:
        service = CSSPassService(
            latitude=latitude,
            longitude=longitude,
            elevation_m=elevation_m,
            timezone_str=timezone_str,
        )
        return service.get_report(days=days)
    except Exception as e:
        logger.warning(f"Failed to generate CSS passes report: {e}")
        return None


def get_css_current_position(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    elevation_m: float = 0.0,
) -> Dict[str, Any]:
    """Compute current CSS ground position and ±50-minute ground track from cached TLE."""
    cached = _get_cached_css_tle(max_age_seconds=None)
    if cached is None:
        raise RuntimeError("No CSS TLE available for position computation")

    line1, line2, _ = cached
    ts = SKYFIELD_LOADER.timescale()
    satellite = EarthSatellite(line1, line2, "CSS (TIANHE)", ts)

    now_utc = datetime.now(timezone.utc)
    now_t = ts.from_datetime(now_utc)
    subpoint = wgs84.subpoint(satellite.at(now_t))
    lat = float(subpoint.latitude.degrees)  # type: ignore[arg-type]
    lon = float(subpoint.longitude.degrees)  # type: ignore[arg-type]
    alt_km = float(subpoint.elevation.km)  # type: ignore[arg-type]

    now_ts = _utc_timestamp()
    with _CSS_TRACK_CACHE_LOCK:
        cache_age = now_ts - int(_CSS_TRACK_CACHE.get("computed_at", 0))
        if cache_age < _CSS_TRACK_CACHE_TTL_SECONDS and _CSS_TRACK_CACHE.get("past_track") is not None:
            past_track = _CSS_TRACK_CACHE["past_track"]
            future_track = _CSS_TRACK_CACHE["future_track"]
        else:
            past_track = []
            for delta_min in range(-50, 0):
                t = ts.from_datetime(now_utc + timedelta(minutes=delta_min))
                sp = wgs84.subpoint(satellite.at(t))
                past_track.append([float(sp.latitude.degrees), float(sp.longitude.degrees)])  # type: ignore[arg-type]

            future_track = [[lat, lon]]
            for delta_min in range(1, 51):
                t = ts.from_datetime(now_utc + timedelta(minutes=delta_min))
                sp = wgs84.subpoint(satellite.at(t))
                future_track.append([float(sp.latitude.degrees), float(sp.longitude.degrees)])  # type: ignore[arg-type]

            _CSS_TRACK_CACHE["past_track"] = past_track
            _CSS_TRACK_CACHE["future_track"] = future_track
            _CSS_TRACK_CACHE["computed_at"] = now_ts

    result: Dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "altitude_km": round(alt_km, 1),
        "past_track": past_track,
        "future_track": future_track,
        "timestamp": now_utc.isoformat(),
        "station": "CSS",
    }

    if latitude is not None and longitude is not None:
        observer = wgs84.latlon(latitude, longitude, elevation_m=elevation_m)
        topocentric = (satellite - observer).at(now_t)
        _obs_alt, _obs_az, _ = topocentric.altaz()
        obs_altitude_deg = float(_obs_alt.degrees)  # type: ignore[arg-type]
        obs_azimuth_deg = float(_obs_az.degrees)  # type: ignore[arg-type]

        eph = None
        try:
            eph = SKYFIELD_LOADER('de421.bsp')
        except Exception as exc:
            logger.warning("Failed to load ephemeris de421.bsp, solar/lunar data unavailable: %s", exc)

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
            "css_altitude_deg": round(obs_altitude_deg, 1),
            "css_azimuth_deg": round(obs_azimuth_deg, 1),
            "sun_altitude_deg": round(sun_altitude_deg, 1),
            "is_visible": is_visible,
        }

    return result
