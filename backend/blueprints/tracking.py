"""Object lookup, ISS/CSS tracking, spaceflight and on-demand translation Blueprint.

Routes: /api/object/*, /api/object-image/*, /api/iss/*, /api/css/*,
/api/spaceflight/*, /api/translate/on-demand
"""

import os
import re
from typing import Any, Dict

from flask import Blueprint, request, jsonify, send_from_directory

from cache import cache_store
from space import css_passes
from space import iss_passes
from utils.auth import login_required
from utils.constants import (
    CACHE_TTL_CSS_PASSES,
    CACHE_TTL_ISS_PASSES,
    CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
    CACHE_TTL_SPACEFLIGHT_EVENTS,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES,
    DATA_DIR_CACHE,
)
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger
from utils.on_demand_translate import translate_text_on_demand
from utils.route_helpers import _active_location_cache, _resolve_active_location

logger = get_logger(__name__)

tracking_bp = Blueprint('tracking', __name__)


def _safe_cache_path(base_dir: str, filename: str) -> str:
    """Resolve *filename* under *base_dir* and verify it doesn't escape it.

    CodeQL (CWE-022) requires this check to be re-applied at each file
    operation's call site; reusing a path resolved earlier in the function is
    not recognised as a sanitizer barrier. Raises ValueError if unsafe.
    """
    resolved = os.path.realpath(os.path.join(base_dir, filename))
    try:
        inside_base_dir = os.path.commonpath([base_dir, resolved]) == base_dir
    except ValueError:
        inside_base_dir = False
    if not inside_base_dir:
        raise ValueError(f'Path outside {base_dir!r}: {filename!r}')
    return resolved


@tracking_bp.route('/api/object/<path:identifier>', methods=['GET'])
@login_required
def get_object_info_api(identifier):
    """Return metadata, image URL and localized description for a deep-sky object.

    Query parameters:
      lang  (str, optional) - Wikipedia language code, default 'en'

    Response (200):
    {
      "id": "NGC 2632",
      "name": "Praesepe",
      "aliases": ["M44", "Beehive Cluster", ...],
      "type": "Open Cluster",
      "coordinates": {"ra": 130.1, "dec": 19.67},
      "description": "...",
      "description_title": "Beehive Cluster",
      "image": {"url": "...", "credit": "DSS2 / SkyView (NASA GSFC)"}
    }

    If the object is not found, returns 404 with {"error": "not_found"}.
    If the identifier is invalid, returns 400 with {"error": "invalid_identifier"}.
    """
    from observation.object_info import is_safe_identifier as _oi_safe, get_object_info as _oi_get

    lang = request.args.get('lang', 'en', type=str)
    # Sanitize lang to a safe value
    lang = str(lang).strip()[:8]

    # Validate identifier characters before any processing
    if not _oi_safe(identifier):
        return jsonify({'error': 'invalid_identifier'}), 400

    try:
        data = _oi_get(identifier, lang=lang)
    except Exception as exc:
        logger.error(f'Error fetching object info for {identifier!r}: {exc}')
        return jsonify({'error': 'Internal server error'}), 500

    error = data.get('error')
    if error == 'invalid_identifier':
        return jsonify(data), 400
    # not_found is a normal outcome (Moon, comets, personal objects not in SIMBAD)
    # return 200 so browsers don't log a console error
    return jsonify(data)


@tracking_bp.route('/api/object-image/<filename>', methods=['GET'])
@login_required
def get_object_image_api(filename):
    """Serve a locally cached DSS2 (hips2fits) image, e.g. "10.684000_41.269000.jpg".

    Downloads from CDS hips2fits on first request and caches the JPEG to disk
    (data/cache/object_images/) so subsequent requests - from any user - are
    served locally instead of round-tripping to CDS, which is slow.
    """
    from observation.object_info import OBJECT_IMAGE_CACHE_DIR, parse_object_image_filename, ensure_cached_object_image

    coords = parse_object_image_filename(filename)
    if coords is None:
        return jsonify({'error': 'invalid_filename'}), 400
    ra, dec = coords

    if ensure_cached_object_image(ra, dec) is None:
        return jsonify({'error': 'image_unavailable'}), 502

    return send_from_directory(OBJECT_IMAGE_CACHE_DIR, filename, max_age=2592000)


@tracking_bp.route("/api/iss/passes", methods=["GET"])
@login_required
def get_iss_passes_api():
    """Return ISS passes report, from cache only"""
    try:

        def _with_celestrak_status(payload: Dict[str, Any]) -> Dict[str, Any]:
            merged = dict(payload)
            merged["celestrak_status"] = iss_passes.get_celestrak_status()
            merged["tle_source"] = iss_passes.get_iss_tle_source_info()
            return merged

        days = request.args.get("days", default=20, type=int)
        days = max(1, min(days, 30))

        _, entry = _active_location_cache("iss_passes")
        if cache_store.is_cache_valid(entry, CACHE_TTL_ISS_PASSES):
            cached_data = entry["data"]
            if isinstance(cached_data, dict) and cached_data.get("window_days") == days:
                return jsonify(_with_celestrak_status(cached_data))

        return (
            jsonify({"status": "pending", "message": "ISS passes cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting ISS passes cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/iss/location", methods=["GET"])
@login_required
def get_iss_location_api():
    """Return current ISS ground position and ±50-minute orbit track, computed from cached TLE."""
    try:
        location = _resolve_active_location()
        lat = location.get("latitude")
        lon = location.get("longitude")
        elev = float(location.get("elevation", 0) or 0)
        position = iss_passes.get_current_position(
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            elevation_m=elev,
        )
        return jsonify(position)
    except RuntimeError:
        logger.exception("Runtime error computing ISS location")
        return jsonify({'error': 'Service temporarily unavailable'}), 503
    except Exception as exc:
        logger.error(f"Error computing ISS location: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/iss/celestrak/restart", methods=["POST"])
@login_required
def restart_iss_celestrak_crawl_api():
    """Clear Celestrak block flag after explicit operator confirmation in UI."""
    try:
        status = iss_passes.clear_celestrak_block_flag()
        return jsonify(
            {
                "status": "ok",
                "message": "Celestrak block flag cleared. Next crawl may query Celestrak again.",
                "celestrak_status": status,
            }
        )
    except Exception as exc:
        logger.error(f"Error resetting Celestrak block flag: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/css/passes", methods=["GET"])
@login_required
def get_css_passes_api():
    """Return CSS (Tiangong) passes report, from cache only."""
    try:

        def _with_celestrak_status(payload: Dict[str, Any]) -> Dict[str, Any]:
            merged = dict(payload)
            merged["celestrak_status"] = css_passes.get_css_celestrak_status()
            merged["tle_source"] = css_passes.get_css_tle_source_info()
            return merged

        days = request.args.get("days", default=20, type=int)
        days = max(1, min(days, 30))

        _, entry = _active_location_cache("css_passes")
        if cache_store.is_cache_valid(entry, CACHE_TTL_CSS_PASSES):
            cached_data = entry["data"]
            if isinstance(cached_data, dict) and cached_data.get("window_days") == days:
                return jsonify(_with_celestrak_status(cached_data))

        return (
            jsonify({"status": "pending", "message": "CSS passes cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting CSS passes cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/css/location", methods=["GET"])
@login_required
def get_css_location_api():
    """Return current CSS ground position and ±50-minute orbit track, computed from cached TLE."""
    try:
        location = _resolve_active_location()
        lat = location.get("latitude")
        lon = location.get("longitude")
        elev = float(location.get("elevation", 0) or 0)
        position = css_passes.get_css_current_position(
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            elevation_m=elev,
        )
        return jsonify(position)
    except RuntimeError:
        logger.exception("Runtime error computing CSS location")
        return jsonify({'error': 'Service temporarily unavailable'}), 503
    except Exception as exc:
        logger.error(f"Error computing CSS location: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/css/celestrak/restart", methods=["POST"])
@login_required
def restart_css_celestrak_crawl_api():
    """Clear CSS Celestrak block flag after explicit operator confirmation in UI."""
    try:
        status = css_passes.clear_css_celestrak_block_flag()
        return jsonify(
            {
                "status": "ok",
                "message": "CSS Celestrak block flag cleared. Next crawl may query Celestrak again.",
                "celestrak_status": status,
            }
        )
    except Exception as exc:
        logger.error(f"Error resetting CSS Celestrak block flag: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@tracking_bp.route("/api/spaceflight/launches", methods=["GET"])
@login_required
def get_spaceflight_launches_api():
    """Return upcoming and past launches from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES):
            return jsonify(cache_store._spaceflight_launches_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_launches", cache_store._spaceflight_launches_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES):
            return jsonify(cache_store._spaceflight_launches_cache["data"])

        stale_data = cache_store._spaceflight_launches_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight launches: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@tracking_bp.route("/api/spaceflight/astronauts", methods=["GET"])
@login_required
def get_spaceflight_astronauts_api():
    """Return ISS crew and astronauts in space from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS):
            return jsonify(cache_store._spaceflight_astronauts_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_astronauts", cache_store._spaceflight_astronauts_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS):
            return jsonify(cache_store._spaceflight_astronauts_cache["data"])

        stale_data = cache_store._spaceflight_astronauts_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight astronauts: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@tracking_bp.route("/api/spaceflight/events", methods=["GET"])
@login_required
def get_spaceflight_events_api():
    """Return upcoming space events from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS):
            return jsonify(cache_store._spaceflight_events_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_events", cache_store._spaceflight_events_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS):
            return jsonify(cache_store._spaceflight_events_cache["data"])

        stale_data = cache_store._spaceflight_events_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight events: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@tracking_bp.route("/api/spaceflight/img/<filename>", methods=["GET"])
@login_required
def spaceflight_image(filename):
    """Serve a locally cached spaceflight/astronaut image.
    If the image file is missing but a .url sidecar exists, re-download it
    on the fly so stale cache entries pointing to deleted files self-heal.
    """
    if not re.match(r'^[a-f0-9]{32}\.(jpg|jpeg|png|webp|gif)$', filename):
        return jsonify({"error": "Invalid filename"}), 400
    img_dir = os.path.realpath(os.path.join(DATA_DIR_CACHE, 'spaceflight_images'))
    sidecar_name = filename + '.url'
    try:
        # Prevent path traversal: resolved path must stay inside img_dir.
        # The regex above already guarantees this; each call is re-validated
        # here (rather than reusing a path resolved once) as CodeQL requires
        # the sanitizer at the call site of every file operation.
        if not os.path.exists(_safe_cache_path(img_dir, filename)):
            if os.path.exists(_safe_cache_path(img_dir, sidecar_name)):
                try:
                    with open(_safe_cache_path(img_dir, sidecar_name), 'r', encoding='utf-8') as sf:
                        original_url = sf.read().strip()
                    import requests as _req

                    resp = _req.get(original_url, timeout=15, stream=True)
                    resp.raise_for_status()
                    os.makedirs(img_dir, exist_ok=True)
                    with open(_safe_cache_path(img_dir, filename), 'wb') as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
                            fh.write(chunk)
                    logger.info("Re-downloaded missing spaceflight image: %s", filename)
                except Exception as exc:
                    logger.warning("Could not re-download spaceflight image %s: %s", filename, exc)
                    return jsonify({"error": "Image unavailable"}), 404
            else:
                return jsonify({"error": "Image not found"}), 404
    except ValueError:  # pragma: no cover  # regex above prevents path traversal
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(img_dir, filename, max_age=86400)


@tracking_bp.route("/api/spaceflight/launch/<launch_id>/vidurls", methods=["GET"])
@login_required
def get_spaceflight_launch_vidurls(launch_id):
    """Return live video URLs for a specific launch from the LL2 detail endpoint.
    Results are cached in-process for 5 minutes to protect the free-tier rate limit.
    Only call this for launches where webcast_live=true."""
    if not re.match(r'^[0-9a-f-]{36}$', launch_id):
        return jsonify({"error": "Invalid launch ID"}), 400
    try:
        from space.spaceflight_tracker import get_launch_vidurls

        vidurls = get_launch_vidurls(launch_id)
        return jsonify({"vidURLs": vidurls})
    except Exception as exc:
        logger.error(f"Error fetching vidURLs for launch {launch_id}: {exc}")
        return jsonify({"vidURLs": []}), 200


@tracking_bp.route("/api/translate/on-demand", methods=["POST"])
@login_required
def translate_on_demand_api():
    """Translate dynamic third-party text for non-English users on demand."""
    try:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text") or "").strip()
        target_lang = str(payload.get("target_lang") or "").split(",")[0].split("-")[0].lower().strip()
        source_lang = str(payload.get("source_lang") or "en").split(",")[0].split("-")[0].lower().strip()

        if not text:
            return jsonify({"error": "missing_text"}), 400
        if len(text) > 5000:
            return jsonify({"error": "text_too_long"}), 400

        supported_languages = set(I18nManager.get_supported_languages())
        if target_lang not in supported_languages:
            return jsonify({"error": "unsupported_target_language"}), 400

        result = translate_text_on_demand(
            text=text,
            source_lang=source_lang or "en",
            target_lang=target_lang,
        )
        return jsonify(result), 200

    except Exception as exc:
        logger.error(f"Error translating on demand: {exc}")
        return jsonify({"error": "Internal server error"}), 500
