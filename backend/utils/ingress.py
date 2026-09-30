"""Home Assistant Ingress support: serve the app under the per-install ingress prefix.

Under HA Ingress the browser talks to ``https://<ha>/api/hassio_ingress/<token>/...``;
the Supervisor strips that prefix, forwards the request from its own address and says
where it came from in ``X-Ingress-Path`` / ``X-Forwarded-*``. ``IngressMiddleware``
turns that into a normal sub-path deployment (``SCRIPT_NAME`` = the prefix, real client
IP in ``REMOTE_ADDR``), so ``url_for``, redirects, ``request.script_root`` and every
``request.remote_addr``-keyed throttle keep working unchanged.

Trust model: the headers are honored only when the flag ``MYASTROBOARD_HA_INGRESS`` is
set (the HA app sets it, plain Docker installs never do) **and** the TCP peer is the
Supervisor. On the directly published port anyone could send ``X-Ingress-Path``, so a
request from any other address gets the ingress headers stripped and nothing else.
"""

import ipaddress
import os
import re
from typing import Any, Callable, Iterable, Optional

from flask import request
from flask.sessions import SecureCookieSessionInterface

from utils import app_settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

INGRESS_ENV_FLAG = 'MYASTROBOARD_HA_INGRESS'
# Overrides the trusted proxy address, for local testing behind a hand-made proxy only
INGRESS_PROXY_ENV = 'MYASTROBOARD_HA_INGRESS_PROXY_IP'
SUPERVISOR_IP = '172.30.32.2'
# The "hassio" Docker network: HA core (172.30.32.1) and the Supervisor append their own
# hop to X-Forwarded-For, so these addresses are never the real client.
HASSIO_NETWORK = ipaddress.ip_network('172.30.32.0/23')

# Name of the session cookie under ingress: every ingress app shares the HA origin, and
# Flask's default "session" would collide with any other Flask-based app there.
INGRESS_SESSION_COOKIE_NAME = 'myastroboard_session'

# A URL path made of safe characters only: it ends up in HTML, JS and a cookie Path
_PREFIX_RE = re.compile(r'^(/[A-Za-z0-9._~-]+)+$')

_FORWARDED_KEYS = (
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_FORWARDED_PROTO',
    'HTTP_X_FORWARDED_HOST',
    'HTTP_X_FORWARDED_PORT',
    'HTTP_X_FORWARDED_PREFIX',
)


def ingress_enabled() -> bool:
    """True when this install runs as a Home Assistant app with ingress turned on."""
    return os.environ.get(INGRESS_ENV_FLAG, '').strip().lower() in ('1', 'true', 'yes', 'on')


def trusted_proxy_ip() -> str:
    """Address the ingress requests must come from (the Supervisor unless overridden)."""
    return os.environ.get(INGRESS_PROXY_ENV, '').strip() or SUPERVISOR_IP


def _clean_prefix(raw: str) -> Optional[str]:
    """Validated ingress prefix without trailing slash, or None when unusable."""
    prefix = raw.strip().rstrip('/')
    return prefix if _PREFIX_RE.match(prefix) else None


def _client_ip(forwarded_for: str) -> Optional[str]:
    """Rightmost X-Forwarded-For hop outside the hassio network.

    Rightmost, not leftmost: everything left of the hop HA core appended itself comes
    from the browser (or whatever proxy sits in front of HA) and could be spoofed.
    """
    for hop in reversed([h.strip() for h in forwarded_for.split(',') if h.strip()]):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            continue
        if address not in HASSIO_NETWORK:
            return str(address)
    return None


class IngressMiddleware:
    """WSGI middleware applying the HA ingress prefix and client address (see module docstring)."""

    def __init__(self, wsgi_app: Callable[..., Iterable[bytes]], proxy_ip: Optional[str] = None):
        self.wsgi_app = wsgi_app
        self.proxy_ip = proxy_ip or trusted_proxy_ip()

    def __call__(self, environ: dict, start_response: Callable[..., Any]) -> Iterable[bytes]:
        raw_prefix = environ.pop('HTTP_X_INGRESS_PATH', None)
        if raw_prefix is None:
            return self.wsgi_app(environ, start_response)

        if environ.get('REMOTE_ADDR') != self.proxy_ip:
            logger.warning(f"Ignoring X-Ingress-Path from untrusted address {environ.get('REMOTE_ADDR')!r}")
            return self.wsgi_app(environ, start_response)

        prefix = _clean_prefix(raw_prefix)
        if prefix is None:
            logger.warning(f"Ignoring malformed X-Ingress-Path {raw_prefix!r}")
            return self.wsgi_app(environ, start_response)

        environ['SCRIPT_NAME'] = prefix
        path = environ.get('PATH_INFO', '')
        if path.startswith(prefix + '/') or path == prefix:
            # Tolerate a proxy that forwards the prefix instead of stripping it
            environ['PATH_INFO'] = path[len(prefix) :]

        client = _client_ip(environ.get('HTTP_X_FORWARDED_FOR', ''))
        if client:
            environ['REMOTE_ADDR'] = client
        proto = environ.get('HTTP_X_FORWARDED_PROTO', '').split(',')[0].strip().lower()
        if proto in ('http', 'https'):
            environ['wsgi.url_scheme'] = proto
        host = environ.get('HTTP_X_FORWARDED_HOST', '').split(',')[0].strip()
        if host:
            environ['HTTP_HOST'] = host

        # Consumed here: a ProxyFix further in (trust_proxy_headers) must not re-apply them
        # and replace the client address with the HA core hop.
        for key in _FORWARDED_KEYS:
            environ.pop(key, None)
        environ['myastroboard.ingress'] = True
        return self.wsgi_app(environ, start_response)


def is_ingress_request() -> bool:
    """True when the current request came through HA ingress."""
    return bool(request.environ.get('myastroboard.ingress'))


class IngressAwareSessionInterface(SecureCookieSessionInterface):
    """Session cookie scoped to the ingress prefix, with its own name, under ingress.

    Direct-port requests keep Flask's defaults, so existing sessions survive the upgrade.
    """

    def get_cookie_name(self, app) -> str:
        if is_ingress_request():
            return INGRESS_SESSION_COOKIE_NAME
        return super().get_cookie_name(app)

    def get_cookie_path(self, app) -> str:
        if is_ingress_request():
            return request.script_root or '/'
        return super().get_cookie_path(app)


def external_base_url() -> Optional[str]:
    """Base URL other software (HA camera, MyAstroShine) can reach this instance at, no trailing slash.

    The admin setting wins. Otherwise the address of the current request, prefix included -
    except under ingress, whose URL requires a Home Assistant login: None there, so callers
    ask for the setting instead of handing out an address that cannot work.
    """
    configured = app_settings.get_external_base_url()
    if configured:
        return configured
    if is_ingress_request():
        return None
    return request.url_root.rstrip('/')
