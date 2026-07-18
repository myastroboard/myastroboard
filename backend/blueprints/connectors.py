"""Connectors (AllSky) Blueprint. Routes: /api/connectors/*"""

import time

from flask import Blueprint, request, jsonify, abort, Response, stream_with_context

from cache import cache_store
from utils.auth import login_required
from utils.constants import CACHE_TTL_ALLSKY_HEALTH
from utils.logging_config import get_logger
from utils.repo_config import load_config

logger = get_logger(__name__)

connectors_bp = Blueprint('connectors', __name__)


@connectors_bp.route('/api/connectors', methods=['GET'])
@login_required
def list_connectors_api():
    """List all available connectors with their installed/enabled state."""
    from connectors import REGISTRY

    config = load_config()
    connectors_cfg = config.get("connectors", {})
    result = []
    for name, cls in REGISTRY.items():
        cfg = connectors_cfg.get(name, {})
        result.append(
            {
                "name": name,
                "label": cls.label,
                "description": cls.description,
                "min_version": cls.min_version,
                "homepage": cls.homepage,
                "modules": cls.MODULES,
                "installed": bool(cfg.get("url")),
                "enabled": bool(cfg.get("enabled")) and bool(cfg.get("url")),
                "config": cfg,
            }
        )
    return jsonify(result)


@connectors_bp.route('/api/connectors/allsky/status', methods=['GET'])
@login_required
def allsky_status_api():
    """Return cached AllSky sensor data (allskydata.json)."""
    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return jsonify({"error": "AllSky connector not configured"}), 404
    if not allsky_cfg.get("modules", {}).get("sensor_data", {}).get("enabled"):
        return jsonify({"error": "sensor_data module not enabled"}), 404

    data = cache_store._allsky_sensor_cache.get("data")
    if data is None:
        from connectors.allsky_connector import AllSkyConnector

        data = AllSkyConnector(allsky_cfg).fetch_sensor_data()
        cache_store._allsky_sensor_cache["data"] = data

        cache_store._allsky_sensor_cache["timestamp"] = time.time()
    return jsonify(data)


@connectors_bp.route('/api/connectors/allsky/health', methods=['GET', 'POST'])
@login_required
def allsky_health_api():
    """Run a per-module health check against the AllSky instance.

    POST {"url": "..."} — quick reachability probe against an arbitrary URL
    (used by the test button before saving).
    GET — full module health check using saved config, with 2-minute cache.
    """
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        test_url = (data.get("url") or "").strip().rstrip("/")
        if not test_url:
            return jsonify({"reachable": False, "error": "url required"}), 400
        import ipaddress as _ipaddress
        import socket as _socket
        from urllib.parse import urlparse as _urlparse

        parsed = _urlparse(test_url)
        if parsed.scheme not in ('http', 'https'):
            return jsonify({"reachable": False, "error": "url must use http or https"}), 400
        if not parsed.hostname:
            return jsonify({"reachable": False, "error": "url must include a valid host"}), 400
        # Resolve hostname to IP, validate it is not a dangerous range (loopback, link-local
        # which covers cloud metadata endpoints like 169.254.169.254, unspecified, multicast),
        # then make the request to the resolved IP — not the original URL — to break the
        # user-controlled data flow and prevent DNS rebinding.
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addrinfo = _socket.getaddrinfo(parsed.hostname, port, type=_socket.SOCK_STREAM)
            resolved_ip = addrinfo[0][4][0]
            ip_obj = _ipaddress.ip_address(resolved_ip)
            if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_multicast:
                return jsonify({"reachable": False, "error": "url host is not allowed"}), 400
        except (_socket.gaierror, ValueError):
            return jsonify({"reachable": False, "error": "unable to resolve host"}), 400
        safe_scheme = 'https' if parsed.scheme == 'https' else 'http'
        safe_url = f"{safe_scheme}://{resolved_ip}"
        import requests as _req

        try:
            r = _req.head(safe_url, timeout=5, allow_redirects=True)
            if r.status_code == 405:
                r = _req.get(safe_url, timeout=5, stream=True)
            reachable = r.status_code < 500
        except _req.exceptions.RequestException:
            reachable = False
        return jsonify({"reachable": reachable})

    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("url"):
        return jsonify({"reachable": False, "modules": {}, "error": "AllSky URL not configured"}), 200

    cached = cache_store._allsky_health_cache
    fresh = request.args.get("fresh") == "1"
    if not fresh and cached.get("data") and (time.time() - cached.get("timestamp", 0)) < CACHE_TTL_ALLSKY_HEALTH:
        return jsonify(cached["data"])

    from connectors.allsky_connector import AllSkyConnector

    result = AllSkyConnector(allsky_cfg).health_check()
    cache_store._allsky_health_cache["data"] = result
    cache_store._allsky_health_cache["timestamp"] = time.time()
    return jsonify(result)


@connectors_bp.route('/api/connectors/allsky/urls', methods=['GET'])
@login_required
def allsky_urls_api():
    """Return proxy URLs for all enabled AllSky modules.

    Returns /api/connectors/allsky/proxy?module=<slug> paths so the browser
    never contacts AllSky directly — works behind a reverse proxy / HTTPS.
    """
    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return jsonify({"error": "AllSky connector not configured"}), 404

    date_str = request.args.get("date")
    from connectors.allsky_connector import AllSkyConnector

    direct_urls = AllSkyConnector(allsky_cfg).get_module_urls(date_str=date_str)

    date_suffix = f"&date={date_str}" if date_str else ""
    proxy_urls = {module: f"/api/connectors/allsky/proxy?module={module}{date_suffix}" for module in direct_urls}
    return jsonify(proxy_urls)


@connectors_bp.route('/api/connectors/allsky/proxy', methods=['GET'])
@login_required
def allsky_proxy_api():
    """Proxy an AllSky resource through the backend.

    The browser requests /api/connectors/allsky/proxy?module=<slug>[&date=YYYYMMDD].
    The backend fetches the real AllSky URL and streams it back, so the browser
    only ever talks to MyAstroBoard — no mixed-content or local-network issues.
    Range requests (video seeking) are forwarded transparently.
    """
    module = request.args.get("module")
    if not module:
        return jsonify({"error": "module parameter required"}), 400

    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return abort(503)

    date_str = request.args.get("date")
    from connectors.allsky_connector import AllSkyConnector
    import requests as _req

    direct_urls = AllSkyConnector(allsky_cfg).get_module_urls(date_str=date_str)
    target_url = direct_urls.get(module)
    if not target_url:
        return abort(404)

    # Force IPv4 to avoid ENETUNREACH when the host resolves to an IPv6
    # link-local address (common with .local mDNS names inside Docker).
    import socket
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(target_url)
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ipv4 = infos[0][4][0]
            netloc = f"{ipv4}:{parsed.port}" if parsed.port else ipv4
            target_url = urlunparse(parsed._replace(netloc=netloc))
    except OSError:
        pass  # already an IP or DNS unavailable — proceed with original URL

    upstream_headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        upstream_headers["Range"] = range_header

    try:
        r = _req.get(target_url, timeout=15, stream=True, headers=upstream_headers)
    except _req.exceptions.Timeout:
        logger.warning("AllSky proxy timeout for module %s", module)
        return abort(504)
    except _req.exceptions.RequestException as exc:
        logger.debug("AllSky proxy error for module %s: %s", module, exc)
        return abort(502)

    if r.status_code != 200:
        logger.debug("AllSky proxy: %s → HTTP %s for %s", module, r.status_code, target_url)

    proxy_headers = {"Content-Type": r.headers.get("Content-Type", "application/octet-stream")}
    for hdr in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if hdr in r.headers:
            proxy_headers[hdr] = r.headers[hdr]

    return Response(
        stream_with_context(r.iter_content(chunk_size=16384)),
        status=r.status_code,
        headers=proxy_headers,
    )
