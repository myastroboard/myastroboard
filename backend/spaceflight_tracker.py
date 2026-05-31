"""
Spaceflight data service - Launch Library 2 (The Space Devs)
Fetches upcoming/past launches, current astronauts in space, and space events.

Free tier: ~15 requests/hour without auth key; caching keeps live calls minimal.
API base:  https://ll.thespacedevs.com/2.2.0/
Docs:      https://thespacedevs.com/llapi
"""

import hashlib
import os
import time
import urllib.parse
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from constants import DATA_DIR_CACHE
from logging_config import get_logger

logger = get_logger(__name__)

_LL2_BASE = "https://ll.thespacedevs.com/2.2.0"
_REQUEST_TIMEOUT = 15
_SPACEFLIGHT_IMAGES_DIR = os.path.join(DATA_DIR_CACHE, 'spaceflight_images')


def _cache_image(url: Optional[str]) -> Optional[str]:
    """
    Download *url* into the local image cache directory and return the local
    serving path ``/api/spaceflight/img/<hash>.<ext>``.
    Also writes a ``<filename>.url`` sidecar so the serve endpoint can
    re-download the image if the file is later deleted.
    Falls back to the original URL on any error so nothing breaks.
    """
    if not url:
        return url
    try:
        os.makedirs(_SPACEFLIGHT_IMAGES_DIR, exist_ok=True)
        url_hash = hashlib.md5(url.encode()).hexdigest()
        ext = os.path.splitext(url.split('?')[0])[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'
        filename = f"{url_hash}{ext}"
        local_path = os.path.join(_SPACEFLIGHT_IMAGES_DIR, filename)
        sidecar_path = local_path + '.url'
        # Always (re)write the sidecar so we can recover later
        with open(sidecar_path, 'w', encoding='utf-8') as sf:
            sf.write(url)
        if not os.path.exists(local_path):
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT, stream=True)
            resp.raise_for_status()
            with open(local_path, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
        return f"/api/spaceflight/img/{filename}"
    except Exception as exc:
        logger.debug("Failed to cache spaceflight image %s: %s", url, exc)
        return url  # graceful fallback to the original CDN URL


# Per-path 429 backoff - after a rate-limit error, suppress calls to the same
# path for up to _BACKOFF_TTL seconds so the scheduler/API endpoints don't
# hammer the free-tier quota while it recovers.
_BACKOFF_TTL = 3600  # seconds - match the spaceflight launches TTL
_backoff_until: Dict[str, float] = {}


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Execute a GET request against the LL2 API and return the JSON response."""
    # Respect 429 backoff: return None early without making a network call
    backoff_exp = _backoff_until.get(path)
    if backoff_exp:
        remaining = backoff_exp - time.time()
        if remaining > 0:
            logger.debug("LL2 API backoff active for %s - skipping (%.0fs remaining)", path, remaining)
            return None
        else:
            _backoff_until.pop(path, None)

    url = f"{_LL2_BASE}{path}"
    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        _backoff_until.pop(path, None)  # clear any stale backoff on success
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning("LL2 API timeout for %s", url)
    except requests.exceptions.HTTPError as exc:
        sc = exc.response.status_code
        if sc == 429:
            retry_after = int(exc.response.headers.get("Retry-After", _BACKOFF_TTL))
            backoff = min(max(retry_after, 60), _BACKOFF_TTL)
            _backoff_until[path] = time.time() + backoff
            logger.warning("LL2 API 429 for %s - backing off for %ds", url, backoff)
        else:
            logger.warning("LL2 API HTTP error %s for %s", exc.response.status_code, url)
    except Exception as exc:
        logger.warning("LL2 API request failed for %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# Data normalizers - map raw LL2 objects to slim, serialisable dicts
# ---------------------------------------------------------------------------

def _normalise_launch(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Slim representation of a launch object."""
    status = raw.get("status") or {}
    rocket = raw.get("rocket") or {}
    config = rocket.get("configuration") or {}
    mission = raw.get("mission") or {}
    pad = raw.get("pad") or {}
    pad_location = pad.get("location") or {}
    agency = raw.get("launch_service_provider") or {}

    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "slug": raw.get("slug"),
        "net": raw.get("net"),                       # ISO 8601 NET launch date
        "window_start": raw.get("window_start"),
        "window_end": raw.get("window_end"),
        "status_id": status.get("id"),
        "status_abbrev": status.get("abbrev"),       # Go / Hold / TBC / etc.
        "status_name": status.get("name"),
        "status_description": status.get("description"),
        "rocket_name": config.get("full_name") or config.get("name"),
        "rocket_family": config.get("family"),
        "mission_name": mission.get("name"),
        "mission_type": mission.get("type"),
        "mission_description": mission.get("description"),
        "orbit": (mission.get("orbit") or {}).get("abbrev"),
        "pad_name": pad.get("name"),
        "pad_location_name": pad_location.get("name"),
        "pad_location_country": pad_location.get("country_code"),
        "agency_name": agency.get("name"),
        "agency_abbrev": agency.get("abbrev"),
        "agency_type": agency.get("type"),
        "image_url": _cache_image(raw.get("image") if isinstance(raw.get("image"), str) else (raw.get("image") or {}).get("image_url")),
        "webcast_live": raw.get("webcast_live", False),
        "video_url": raw.get("vidURL") or next((v.get("url") for v in (raw.get("vidURLs") or []) if v.get("url")), None),
        "info_url": raw.get("infoURL"),
    }


def _normalise_astronaut(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Slim representation of an astronaut."""
    agency = raw.get("agency") or {}
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "nationality": raw.get("nationality"),
        "agency_name": agency.get("name"),
        "agency_abbrev": agency.get("abbrev"),
        "profile_image": _cache_image(raw.get("profile_image")),
        "status": (raw.get("status") or {}).get("name"),
        "currently_in_space": raw.get("in_space"),
        "time_in_space": raw.get("time_in_space"),
        "bio": raw.get("bio"),
        "wiki_url": raw.get("wiki"),
    }


def _normalise_expedition(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Slim representation of an ISS expedition."""
    crew = []
    for cr in raw.get("crew", []):
        ast = cr.get("astronaut") or {}
        agency = ast.get("agency") or {}
        crew.append({
            "name": ast.get("name"),
            "nationality": ast.get("nationality"),
            "agency_name": agency.get("name"),
            "agency_abbrev": agency.get("abbrev"),
            "role": cr.get("role", {}).get("role") if cr.get("role") else None,
            "profile_image": _cache_image(ast.get("profile_image")),
        })
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "start": raw.get("start"),
        "end": raw.get("end"),
        "crew_count": len(crew),
        "crew": crew,
        "mission_patch": raw.get("mission_patch"),
        "wiki_url": raw.get("wiki"),
    }


def _normalise_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Slim representation of a space event."""
    event_type = raw.get("type") or {}
    programs = [p.get("name") for p in raw.get("programs", []) if p.get("name")]
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "slug": raw.get("slug"),
        "type_name": event_type.get("name"),
        "description": raw.get("description"),
        "date": raw.get("date"),
        "location": raw.get("location"),
        "video_url": raw.get("video_url"),
        "webcast_live": raw.get("webcast_live", False),
        "news_url": raw.get("news_url"),
        "programs": programs,
        "image_url": raw.get("feature_image") if isinstance(raw.get("feature_image"), str) else (raw.get("feature_image") or {}).get("image_url"),
    }


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------

def get_upcoming_launches(limit: int = 12) -> Optional[Dict[str, Any]]:
    """Fetch upcoming launches (NET ≥ now)."""
    raw = _get("/launch/upcoming/", params={"limit": limit, "format": "json"})
    if raw is None:
        return None
    results = [_normalise_launch(r) for r in (raw.get("results") or [])]
    return {
        "count": raw.get("count", len(results)),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_past_launches(limit: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch recent past launches (NET < now), sorted descending."""
    raw = _get("/launch/previous/", params={"limit": limit, "format": "json", "ordering": "-net"})
    if raw is None:
        return None
    results = [_normalise_launch(r) for r in (raw.get("results") or [])]
    return {
        "count": raw.get("count", len(results)),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_iss_crew() -> Optional[Dict[str, Any]]:
    """Fetch current ISS expedition crew via the expeditions endpoint."""
    raw = _get("/expedition/", params={"format": "json", "limit": 1, "ordering": "-start"})
    if raw is None:
        return None
    expeditions = raw.get("results") or []
    if not expeditions:
        return {"expeditions": [], "fetched_at": datetime.now(timezone.utc).isoformat()}
    # The first result is the current expedition (API returns most recent first)
    current = _normalise_expedition(expeditions[0])
    return {
        "current_expedition": current,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_astronauts_in_space() -> Optional[Dict[str, Any]]:
    """Fetch all astronauts currently in space."""
    raw = _get("/astronaut/", params={"in_space": "true", "limit": 30, "format": "json"})
    if raw is None:
        return None
    results = [_normalise_astronaut(r) for r in (raw.get("results") or [])]
    return {
        "count": raw.get("count", len(results)),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_upcoming_space_events(limit: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch upcoming space events (dockings, EVAs, milestones…)."""
    raw = _get("/event/upcoming/", params={"limit": limit, "format": "json"})
    if raw is None:
        return None
    results = [_normalise_event(r) for r in (raw.get("results") or [])]
    return {
        "count": raw.get("count", len(results)),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Live vidURLs - lazy detail-endpoint fetch (free tier: ~15 req/hour)
# Per-launch in-process cache with 5-minute TTL.
# ---------------------------------------------------------------------------
_VIDURLS_TTL = 300  # seconds
_vidurls_cache: Dict[str, Dict[str, Any]] = {}


def get_launch_vidurls(launch_id: str) -> List[Dict[str, Any]]:
    """
    Fetch the vidURLs for a single launch from the LL2 detail endpoint.
    Results are cached in-process for _VIDURLS_TTL seconds to protect the
    free-tier rate limit (this endpoint is only called for live launches when
    a user opens the modal).

    Returns a list sorted best-first: YouTube preferred, then by descending priority.
    """
    entry = _vidurls_cache.get(launch_id)
    if entry and (time.time() - entry["ts"]) < _VIDURLS_TTL:
        return entry["data"]

    raw = _get(f"/launch/{launch_id}/", params={"format": "json"})
    if raw is None:
        return []

    vid_urls = raw.get("vidURLs") or []
    result = [
        {
            "url": v.get("url"),
            "title": v.get("title"),
            "source": v.get("source"),
            "publisher": v.get("publisher"),
            "type": (v.get("type") or {}).get("name"),
            "priority": v.get("priority", 0),
        }
        for v in vid_urls
        if v.get("url")
    ]

    # Sort: YouTube first (embeddable), then by descending priority
    def _is_youtube(url: str) -> bool:
        try:
            host = urllib.parse.urlparse(url).hostname or ""
            return host == "www.youtube.com" or host == "youtube.com"
        except Exception:
            return False

    def _sort_key(v):
        is_yt = 1 if _is_youtube(v.get("url") or "") else 0
        return (-is_yt, -(v.get("priority") or 0))

    result.sort(key=_sort_key)
    _vidurls_cache[launch_id] = {"data": result, "ts": time.time()}
    return result


# ---------------------------------------------------------------------------
# Image cache pruning - remove files no longer referenced by active cache data
# ---------------------------------------------------------------------------

def prune_image_cache(active_data: list) -> None:
    """
    Delete images from the local spaceflight_images directory that are no longer
    referenced in *active_data* (a flat list of all image path strings currently
    in use, e.g. '/api/spaceflight/img/<hash>.jpg').

    Call this after every full spaceflight cache refresh so orphaned images from
    old launches / retired astronauts don't accumulate indefinitely.
    """
    if not os.path.isdir(_SPACEFLIGHT_IMAGES_DIR):
        return

    # Build the set of filenames that are still in use
    in_use: set = set()
    for path in active_data:
        if path and isinstance(path, str) and path.startswith("/api/spaceflight/img/"):
            in_use.add(os.path.basename(path))

    removed = 0
    freed = 0
    for fname in os.listdir(_SPACEFLIGHT_IMAGES_DIR):
        if fname not in in_use:
            fpath = os.path.join(_SPACEFLIGHT_IMAGES_DIR, fname)
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                removed += 1
                freed += size
            except OSError as exc:
                logger.warning("Could not remove stale spaceflight image %s: %s", fpath, exc)

    if removed:
        logger.info(
            "Pruned %d stale spaceflight image(s), freed %.1f KB",
            removed, freed / 1024,
        )


def spaceflight_cache_images_intact(cache_data: dict) -> bool:
    """
    Return True if every ``/api/spaceflight/img/`` path referenced in
    *cache_data* has a corresponding file on disk.

    Returns True when *cache_data* is None/empty (no images to check).
    Returns False as soon as the first missing image is detected, so the
    caller can immediately invalidate the cache and schedule a re-fetch.
    """
    if not cache_data:
        return True

    def _walk(obj):
        if isinstance(obj, str):
            if obj.startswith("/api/spaceflight/img/"):
                fname = os.path.basename(obj)
                fpath = os.path.join(_SPACEFLIGHT_IMAGES_DIR, fname)
                if not os.path.exists(fpath):
                    logger.debug("Spaceflight image missing from disk: %s", fpath)
                    return False
        elif isinstance(obj, dict):
            for v in obj.values():
                if not _walk(v):
                    return False
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                if not _walk(item):
                    return False
        return True

    return _walk(cache_data)
