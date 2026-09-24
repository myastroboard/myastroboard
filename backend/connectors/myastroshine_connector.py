"""
MyAstroShine connector — send an Astrodex photo out for re-processing and bring
the enhanced result back as a new picture on the same object.

A connector like any other: it talks to an optional external service over HTTP,
it is switched on or off from Parameters -> Connectors, and it declares the app
tab its data lands in. What sets it apart from AllSky is only *what* it carries:
the exchange is bidirectional (the browser hands a photo to MyAstroShine, the
MyAstroShine container posts the enhanced result back), so it authenticates with
a token and an HMAC signing secret, and it has no browser-fetched resources or
live sensor readings — hence no modules, and the two BaseConnector hooks for
those keep their empty defaults.

Its routes live in ``blueprints/connectors_myastroshine.py``, the same way
AllSky's live in ``blueprints/connectors_allsky.py``. See docs/MYASTROSHINE.md.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import requests

from connectors.base_connector import BaseConnector
from utils.logging_config import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT = 5


class MyAstroShineConnector(BaseConnector):
    name = "myastroshine"
    label = "MyAstroShine"
    description = "Send an Astrodex photo to MyAstroShine for re-processing, then bring the result back"
    # Oldest release implementing the pull + webhook round-trip. Informational: MyAstroShine
    # reports its own version only once a handoff completes, where it is stored per picture
    # as enhanced_source_version.
    min_version = "v0.4.0"
    homepage = "https://github.com/myastroboard/myastroshine"
    target_modules = ["astrodex"]

    # No independently-toggleable features: the round-trip is the whole connector.
    MODULES: list[dict] = []

    SECRET_FIELDS = ("token", "signing_secret")

    URL_FIELDS = ("callback_url_override",)

    # How long a signed handoff stays valid. The single-use ``jti`` is the real anti-replay
    # guard; this TTL just bounds how long a leaked handoff URL could pull the source image.
    HANDOFF_TTL_SECONDS = 12 * 60 * 60
    # Cap on the enhanced JPEG MyAstroShine uploads back.
    MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB
    # Sliding-window rate limit for the cookieless endpoints the container calls.
    ENHANCED_RATE_LIMIT = 30  # max calls per client per window
    ENHANCED_RATE_WINDOW_SECONDS = 60

    CONFIG_FIELDS = {
        "token": "",
        "signing_secret": "",
        # Only needed when the MyAstroShine container cannot reach this board's public URL.
        "callback_url_override": "",
        "copy_rating": False,
    }

    def is_configured(self) -> bool:
        """A URL alone is not enough — without both credentials no handoff can be signed."""
        return bool(self.base_url and self.config.get("token") and self.config.get("signing_secret"))

    def health_check(self) -> dict:
        """Probe ``<url>/api/health``.

        MyAstroShine is LAN-only: "unreachable" is expected and normal when the board runs on
        a different network. Resolves the host and refuses loopback / link-local / unspecified
        / multicast targets, then hits the resolved IP directly rather than the original
        hostname, to break the user-controlled data flow (SSRF / DNS-rebinding hardening) —
        same pattern as the AllSky connector.
        """
        if not self.base_url:
            return {"reachable": False, "modules": {}, "error": "url required"}

        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return {"reachable": False, "modules": {}, "error": "url must be a valid http(s) URL"}

        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addrinfo = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            resolved_ip = str(addrinfo[0][4][0])
            ip_obj = ipaddress.ip_address(resolved_ip)
            if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_multicast:
                return {"reachable": False, "modules": {}, "error": "url host is not allowed"}
        except (socket.gaierror, ValueError):
            return {"reachable": False, "modules": {}, "error": "unable to resolve host"}

        safe_scheme = "https" if parsed.scheme == "https" else "http"
        netloc = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        probe_url = f"{safe_scheme}://{netloc}/api/health"
        headers = {"Host": parsed.netloc} if parsed.netloc else {}

        try:
            resp = requests.get(probe_url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=False)
            reachable = resp.status_code < 500
        except requests.exceptions.RequestException:
            reachable = False
        return {"reachable": reachable, "modules": {}}
