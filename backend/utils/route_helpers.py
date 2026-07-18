"""Shared helpers used by multiple route Blueprints."""

from cache import cache_store
from utils.auth import get_current_user
from utils.repo_config import load_config, get_active_location


def _resolve_active_location():
    """Resolve the request's active location preset (per-user, v1.2).

    Outside a request context (background threads, direct helper calls) the
    per-user session is unavailable - fall back to anonymous resolution,
    which yields the install default preset.
    """
    config = load_config()
    try:
        user = get_current_user()
    except RuntimeError:
        user = None
    return get_active_location(config, user)


def _active_location_cache(name):
    """Return (active_location, synced cache entry) for the calling user."""
    location = _resolve_active_location()
    entry = cache_store.load_location_cache(name, location.get("id"))
    return location, entry
