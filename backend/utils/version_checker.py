"""
Version update checker with caching to avoid GitHub API rate limiting.
Checks for new releases on GitHub and caches results.

When an update is available, the CHANGELOG.md of the latest release is fetched as well and the
sections between the installed and the latest version are returned as structured data, so the
UI can show what changed. The installed image only ships its own (older) changelog, hence the
remote fetch.
"""

import re
import time

import requests
from packaging.version import InvalidVersion
from packaging.version import parse as parse_version

from cache import cache_store
from utils.constants import VERSION_UPDATE_CACHE_TTL
from utils.logging_config import get_logger
from utils.txtconf_loader import get_repo_version

logger = get_logger(__name__)

GITHUB_API_RELEASES_URL = "https://api.github.com/repos/myastroboard/myastroboard/releases/latest"
GITHUB_REPO_URL = "https://github.com/myastroboard/myastroboard"
GITHUB_RAW_CHANGELOG_URL = "https://raw.githubusercontent.com/myastroboard/myastroboard/{tag}/CHANGELOG.md"
REQUEST_TIMEOUT = 10  # seconds
CHANGELOG_MAX_BYTES = 1_000_000  # the whole file is ~60 KB; refuse anything absurd
CHANGELOG_MAX_RELEASES = 30  # an instance that far behind still gets a bounded payload

# "## 1.6.8 (2026-09-30)" - the release workflow writes released sections in this exact shape
_UNRELEASED_HEADING_RE = re.compile(r"^##\s+\[unreleased\]\s*$", re.IGNORECASE)
_RELEASE_HEADING_RE = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\s*(?:\((\d{4}-\d{2}-\d{2})\))?\s*$")
_GROUP_HEADINGS = {
    "features": "features",
    "fixes": "fixes",
    "breaking changes": "breaking",
}
# Markdown link whose target is a repo-relative path (docs/FOO.md), not an absolute URL
_RELATIVE_LINK_RE = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")
_EMPTY_ENTRIES = {"none", "none."}


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


def _absolutize_links(text: str, tag: str) -> str:
    """Point repo-relative markdown links at the file as it was in that release on GitHub."""
    return _RELATIVE_LINK_RE.sub(lambda m: f"]({GITHUB_REPO_URL}/blob/{tag}/{m.group(1)})", text)


def _new_release(version: str, date: str) -> dict:
    return {"version": version, "date": date, "features": [], "fixes": [], "breaking": []}


def parse_changelog(markdown: str, current_version: str, latest_version: str, tag: str, release_date: str = "") -> list:
    """
    Extract the released sections strictly newer than current_version and up to latest_version.

    Returns a list (newest first, as in the file) of
    {"version", "date", "features": [...], "fixes": [...], "breaking": [...]} where every entry is
    the bullet's markdown text on one line. "None." placeholder bullets are dropped and any
    non-semver heading is ignored.

    The release tag is cut before the post-release workflow archives [Unreleased] into a dated
    section, so the file at the tag usually has no "## <latest_version>" heading: its
    [Unreleased] section is then exactly the latest release, and is returned as such (dated
    release_date). When the dated section does exist, [Unreleased] is ignored.
    """
    releases = []
    unreleased = _new_release(latest_version, release_date)
    release: dict | None = None
    group: str | None = None
    bullet: list | None = None

    def _flush_bullet():
        nonlocal bullet
        if release is not None and group is not None and bullet:
            text = " ".join(bullet).strip()
            if text.lower() not in _EMPTY_ENTRIES:
                release[group].append(_absolutize_links(text, tag))
        bullet = None

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            _flush_bullet()
            group = None
            release = None
            if _UNRELEASED_HEADING_RE.match(line):
                release = unreleased
                continue
            match = _RELEASE_HEADING_RE.match(line)
            if match:
                version, date = match.group(1), match.group(2) or ""
                if is_newer_version(current_version, version) and not is_newer_version(latest_version, version):
                    release = _new_release(version, date)
                    releases.append(release)
            continue
        if release is None:
            continue
        if line.startswith("### "):
            _flush_bullet()
            group = _GROUP_HEADINGS.get(line[4:].strip().lower())
            continue
        if line.startswith("- ") or line.startswith("* "):
            _flush_bullet()
            bullet = [line[2:].strip()]
        elif bullet is not None and line.strip():
            # Wrapped continuation line of the current bullet
            bullet.append(line.strip())
        elif not line.strip():
            _flush_bullet()
    _flush_bullet()

    has_latest_section = any(not is_newer_version(r["version"], latest_version) for r in releases)
    has_unreleased_entries = any(unreleased[key] for key in ("features", "fixes", "breaking"))
    if not has_latest_section and has_unreleased_entries and is_newer_version(current_version, latest_version):
        releases.insert(0, unreleased)

    return releases[:CHANGELOG_MAX_RELEASES]


def fetch_release_changes(current_version: str, latest_version: str, tag: str, release_date: str = "") -> list | None:
    """
    Fetch CHANGELOG.md at the latest release tag and return the parsed changes since current_version.
    Returns None when the file cannot be fetched or parsed, so the UI falls back to the release link.
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag or ""):
        logger.warning(f"Refusing to fetch CHANGELOG.md for unexpected tag name {tag!r}")
        return None
    try:
        response = requests.get(GITHUB_RAW_CHANGELOG_URL.format(tag=tag), timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logger.warning(f"Could not fetch CHANGELOG.md for {tag} (HTTP {response.status_code})")
            return None
        text = response.text
        if len(text) > CHANGELOG_MAX_BYTES:
            logger.warning(f"CHANGELOG.md for {tag} is unexpectedly large ({len(text)} chars), ignoring it")
            return None
        return parse_changelog(text, current_version, latest_version, tag, release_date)
    except Exception as e:
        logger.warning(f"Could not load release changes for {tag}: {e}")
        return None


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

        tag_name = str(release_data.get('tag_name', '')).strip()
        latest_version = tag_name.replace('v', '').strip()
        published_at = str(release_data.get('published_at') or '')
        update_available = is_newer_version(current_version, latest_version)

        result = {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "release_url": release_data.get('html_url', ''),
            "release_name": release_data.get('name', ''),
            "published_at": published_at,
            # None = changelog unavailable (UI shows only the release link)
            "changes": (
                fetch_release_changes(current_version, latest_version, tag_name, published_at[:10])
                if update_available
                else None
            ),
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
