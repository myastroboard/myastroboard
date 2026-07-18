"""Miscellaneous utility routes Blueprint.

Routes: /api/skyquality, /api/convert-coordinates, /api/timezones,
/api/health, /health, /api/cache, /api/version, /api/version/check-updates
"""

import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones

from flask import Blueprint, request, jsonify

from cache import cache_store
from utils.auth import login_required
from utils.logging_config import get_logger
from utils.repo_config import load_config, get_scheduler_locations, get_install_default_location
from utils.route_helpers import _resolve_active_location
from utils.txtconf_loader import get_repo_version
from utils.version_checker import check_for_updates

logger = get_logger(__name__)

misc_bp = Blueprint('misc', __name__)

# Coordinate conversion regex pattern (module-level constant)
# Matches DMS format: 48d38m36.16s or 48°38'36.16"
# Pattern: optional sign, degrees, minutes, seconds
DMS_PATTERN = re.compile(r"^([+-]?\d{1,3})[d°]\s*(\d{1,2})[m']\s*(\d{1,2}(?:\.\d{1,6})?)[s\"]?$")


@misc_bp.route('/api/skyquality', methods=['GET'])
@login_required
def get_sky_quality_api():
    """
    Return the configured sky quality (Bortle / SQM) for the current location.

    When neither bortle nor sqm is configured, sqm_source is "not_configured"
    and all numeric fields are null - the LP integration is inactive.
    """
    from weather.sky_quality import (
        bortle_to_sqm,
        sqm_to_bortle,
        light_pollution_factor,
        BORTLE_DESCRIPTIONS,
    )

    location = _resolve_active_location()
    raw_sqm = location.get('sqm')
    raw_bortle = location.get('bortle')

    sqm: Optional[float] = None
    bortle: Optional[int] = None
    sqm_source: str = "not_configured"

    if raw_sqm is not None and raw_bortle is not None:
        # Both provided (e.g. read from lightpollutionmap.info): trust as-is.
        # Do not re-derive bortle from sqm - the two values come from the same
        # source and may use different boundary tables.
        try:
            sqm = float(raw_sqm)
            bortle = int(raw_bortle)
            sqm_source = "user_measured"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None, endpoint returns 404
    elif raw_sqm is not None:
        try:
            sqm = float(raw_sqm)
            bortle = sqm_to_bortle(sqm)
            sqm_source = "user_measured"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None
    elif raw_bortle is not None:
        try:
            bortle = int(raw_bortle)
            sqm = bortle_to_sqm(bortle)
            sqm_source = "bortle_midpoint"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None

    if sqm is not None and bortle is not None:
        return jsonify(
            {
                "bortle": bortle,
                "sqm": round(sqm, 2),
                "sqm_source": sqm_source,
                "light_pollution_factor": light_pollution_factor(sqm),
                "description": BORTLE_DESCRIPTIONS.get(bortle, ""),
            }
        )

    return jsonify(
        {
            "bortle": None,
            "sqm": None,
            "sqm_source": "not_configured",
            "light_pollution_factor": None,
            "description": None,
        }
    )


@misc_bp.route('/api/convert-coordinates', methods=['POST'])
@login_required
def convert_coordinates_api():
    """Convert DMS coordinates to decimal"""
    try:
        data = request.json
        dms_str = data.get('dms', '')

        if not isinstance(dms_str, str) or len(dms_str) > 50:
            logger.warning(f"Invalid DMS input: {dms_str}")
            return jsonify({"status": "error", "message": "Invalid input"}), 400

        # Use module-level DMS_PATTERN constant
        match = DMS_PATTERN.match(dms_str.strip())

        if match:
            degrees = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))

            # Convert to decimal
            decimal = abs(degrees) + minutes / 60 + seconds / 3600
            if degrees < 0:
                decimal = -decimal

            # Validate reasonable ranges (lat: -90 to 90, lon: -180 to 180)
            # Note: We don't know if this is lat or lon, so we use wider range
            if decimal < -180 or decimal > 180:
                return jsonify({"status": "error", "message": "Coordinate value out of valid range (-180 to 180)"}), 400

            return jsonify({"status": "success", "decimal": round(decimal, 6), "dms": dms_str})
        else:
            return jsonify({"status": "error", "message": "Invalid DMS format. Use format like: 48d38m36.16s"}), 400

    except Exception as e:  # pragma: no cover
        logger.error(f"Error converting coordinates: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@misc_bp.route('/api/timezones', methods=['GET'])
@login_required
def get_timezones_api():
    now = datetime.now(timezone.utc)
    result = []

    for tz in sorted(available_timezones()):
        if not (tz.startswith("posix/") or tz.startswith("right/") or tz == "localtime"):
            local_time = now.astimezone(ZoneInfo(tz))
            offset = local_time.strftime('%z')

            result.append({"name": tz, "offset": offset})

    return jsonify(result)


@misc_bp.route('/api/health', methods=['GET'])
def health_api():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@misc_bp.route('/health', methods=['GET'])
def health_simple_api():
    """Simple health check endpoint for Docker healthcheck"""
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@misc_bp.route('/api/cache', methods=['GET'])
@login_required
def cache_health_api():
    """
    Cache status endpoint - purely informational.
    Returns whether caches are currently valid based on TTL.
    All cache management is server-side only.
    """
    status = cache_store.get_cache_init_status()

    # Location id -> display name for every location this status covers, so the
    # Metrics UI can label per-location job breakdowns without a second,
    # admin-only /api/locations call (this endpoint is available to any user).
    config = load_config()
    scheduler_locations = get_scheduler_locations(config)
    location_names = {loc["id"]: loc.get("name") or loc["id"] for loc in scheduler_locations if loc.get("id")}
    install_default_id = get_install_default_location(config).get("id")

    return jsonify(
        {
            "cache_status": status["all_ready"],
            "in_progress": status["in_progress"],
            "current_step": status.get("current_step", 0),
            "total_steps": status.get("total_steps", 0),
            "step_name": status.get("step_name", ""),
            "progress_percent": status.get("progress_percent", 0),
            "details": status,
            "location_names": location_names,
            "install_default_location_id": install_default_id,
        }
    )


@misc_bp.route('/api/version', methods=['GET'])
@login_required
def get_version_api():
    """Get application version"""
    version = get_repo_version()
    version = version.strip()
    return jsonify({"version": version})


@misc_bp.route('/api/version/check-updates', methods=['GET'])
@login_required
def check_updates_api():
    """
    Check for available updates from GitHub.
    Uses server-side caching to respect GitHub API rate limits.
    Cache TTL: 4 hours
    """
    try:
        update_info = check_for_updates()
        return jsonify(update_info)
    except Exception:
        logger.error("Error in check updates API")
        return (
            jsonify(
                {
                    "current_version": get_repo_version().strip(),
                    "update_available": False,
                    "error": "Internal server error",
                }
            ),
            500,
        )
