"""
Version update checker with caching to avoid GitHub API rate limiting.
Checks for new releases on GitHub and caches results.
"""

import time
import requests
from packaging.version import parse as parse_version, InvalidVersion
from logging_config import get_logger
import cache_store
from constants import VERSION_UPDATE_CACHE_TTL
from txtconf_loader import get_repo_version

logger = get_logger(__name__)

GITHUB_API_RELEASES_URL = "https://api.github.com/repos/myastroboard/myastroboard/releases/latest"
REQUEST_TIMEOUT = 10  # seconds


def is_newer_version(current_version: str, latest_version: str) -> bool:
    """
    Compare two semantic version strings using packaging.version.
    Returns True if latest_version is strictly newer than current_version.
    """
    try:
        current = current_version.replace('v', '').strip()
        latest = latest_version.replace('v', '').strip()
        return parse_version(latest) > parse_version(current)
    except (InvalidVersion, Exception) as e:
        logger.error(f"Error comparing versions '{current_version}' vs '{latest_version}': {e}")
        return False


def _save_version_result(result: dict) -> None:
    """Persist a version-check result to the in-memory and shared cache."""
    cache_entry = cache_store.get_version_update_cache_entry()
    cache_entry["data"] = result
    cache_entry["timestamp"] = time.time()
    cache_store.update_shared_cache_entry(
        "version_update",
        cache_entry["data"],
        cache_entry["timestamp"],
    )


def check_for_updates():
    """
    Check for available updates from GitHub.
    Uses cache to avoid excessive API calls (respects rate limits).
    Returns dict with update information or None if check failed.
    """
    # Sync from shared cache first (for multi-worker support)
    cache_entry = cache_store.get_version_update_cache_entry()
    cache_store.sync_cache_from_shared("version_update", cache_entry)

    current_version = get_repo_version().strip()

    # Check cache first
    if cache_store.is_cache_valid(cache_entry, VERSION_UPDATE_CACHE_TTL):
        cached_data = cache_entry.get("data") or {}
        cached_current = str(cached_data.get("current_version") or "").strip()
        if cached_current == current_version:
            logger.debug("Returning cached version update information")
            return cached_data

        logger.info(
            "Installed version changed (%s -> %s), invalidating version-update cache",
            cached_current or "unknown",
            current_version,
        )

    # Cache expired or empty, fetch from GitHub
    try:
        logger.info("Checking for updates from GitHub...")

        response = requests.get(
            GITHUB_API_RELEASES_URL,
            timeout=REQUEST_TIMEOUT,
            headers={'Accept': 'application/vnd.github.v3+json'},
        )

        if response.status_code == 404:
            logger.warning("GitHub API returned 404 - repository or releases not found")
            result = {"current_version": current_version, "update_available": False, "error": "Repository not found"}
            _save_version_result(result)
            return result

        if response.status_code == 403:
            logger.warning("GitHub API rate limit exceeded")
            result = {"current_version": current_version, "update_available": False, "error": "Rate limit exceeded"}
            _save_version_result(result)
            return result

        response.raise_for_status()
        release_data = response.json()

        latest_version = release_data.get('tag_name', '').replace('v', '').strip()
        update_available = is_newer_version(current_version, latest_version)

        result = {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "release_url": release_data.get('html_url', ''),
            "release_name": release_data.get('name', ''),
            "published_at": release_data.get('published_at', ''),
        }
        _save_version_result(result)

        if update_available:
            logger.info(f"Update available: v{current_version} -> v{latest_version}")
        else:
            logger.info(f"No update available (current: v{current_version}, latest: v{latest_version})")

        return result

    except requests.Timeout:
        logger.warning("GitHub API request timed out")
        result = {
            "current_version": get_repo_version().strip(),
            "update_available": False,
            "error": "Request timed out",
        }
        _save_version_result(result)
        return result
    except requests.RequestException as e:
        logger.error(f"Error checking for updates from GitHub: {e}")
        result = {"current_version": get_repo_version().strip(), "update_available": False, "error": "Request failed"}
        _save_version_result(result)
        return result
    except Exception as e:
        logger.error(f"Unexpected error checking for updates: {e}", exc_info=True)
        result = {"current_version": get_repo_version().strip(), "update_available": False, "error": "Internal error"}
        _save_version_result(result)
        return result
