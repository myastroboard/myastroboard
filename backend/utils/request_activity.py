"""Let background calculations give way to the requests being served.

The web server runs one process: request threads and the background calculations (SkyTonight,
cache jobs) share one Python interpreter and its GIL. While a calculation runs, every request
gets only a share of the CPU, and pages slow down for everyone browsing.

``RequestActivityMiddleware`` counts the requests in flight; a calculation calls
``yield_to_requests()`` between two units of work and pauses briefly while requests are being
served, so they run first. Both bounds keep a calculation moving under any load:

- a pause lasts at most ``MAX_PAUSE_SECONDS``, then the calculation does its next unit of work;
- a request running for more than ``RECENT_SECONDS`` (a video streamed from the AllSky camera)
  no longer counts, so a long download cannot hold a calculation back.
"""

import itertools
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

from werkzeug.wsgi import ClosingIterator

# Requests older than this are not waited for (long downloads and streams).
RECENT_SECONDS = 5.0
# Longest single pause of a calculation, and how often it checks the requests meanwhile.
MAX_PAUSE_SECONDS = 0.025
_POLL_SECONDS = 0.001
# Bookkeeping bounds for requests whose response was never closed.
_PRUNE_ABOVE = 1000
_FORGET_SECONDS = 3600.0

_in_flight: dict[int, float] = {}  # request token -> start time (time.monotonic)
_lock = threading.Lock()
_tokens = itertools.count()


def request_started() -> int:
    """Record a request starting; returns the token to pass to request_finished()."""
    token = next(_tokens)
    now = time.monotonic()
    with _lock:
        if len(_in_flight) > _PRUNE_ABOVE:
            # A response never closed (a test client) must not grow this forever.
            for stale in [key for key, started in _in_flight.items() if now - started > _FORGET_SECONDS]:
                del _in_flight[stale]
        _in_flight[token] = now
    return token


def request_finished(token: int) -> None:
    with _lock:
        _in_flight.pop(token, None)


def requests_in_flight(now: float | None = None) -> int:
    """How many requests started less than RECENT_SECONDS ago are still running."""
    now = time.monotonic() if now is None else now
    with _lock:
        return sum(1 for started in _in_flight.values() if now - started < RECENT_SECONDS)


def yield_to_requests() -> None:
    """Pause the calling background thread while requests are being served (bounded)."""
    if not _in_flight:  # the common case: nobody browsing, no lock taken
        return
    deadline = time.monotonic() + MAX_PAUSE_SECONDS
    while requests_in_flight() and time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)  # sleeping releases the GIL to the request threads


class RequestActivityMiddleware:
    """WSGI middleware counting the requests in flight, until their response is fully sent."""

    def __init__(self, app: Callable[..., Iterable[bytes]]):
        self.app = app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        token = request_started()
        try:
            response = self.app(environ, start_response)
        except BaseException:
            request_finished(token)
            raise
        return ClosingIterator(response, [lambda: request_finished(token)])
