"""Tests for utils.request_activity: background calculations giving way to requests."""

import threading
import time

import pytest

from utils import request_activity


@pytest.fixture(autouse=True)
def _no_requests():
    with request_activity._lock:
        request_activity._in_flight.clear()
    yield
    with request_activity._lock:
        request_activity._in_flight.clear()


def _wsgi_app(body=(b'ok',), fail=False):
    def app(environ, start_response):
        if fail:
            raise RuntimeError('boom')
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return list(body)

    return app


class TestMiddleware:
    def test_request_counts_until_its_response_is_closed(self):
        """A response still being sent counts; closing it (the server does) ends the request."""
        seen = []
        app = request_activity.RequestActivityMiddleware(_wsgi_app())
        response = app({}, lambda status, headers: seen.append(status))
        assert request_activity.requests_in_flight() == 1
        assert b''.join(response) == b'ok'
        response.close()
        assert request_activity.requests_in_flight() == 0
        assert seen == ['200 OK']

    def test_failing_request_does_not_stay_counted(self):
        """An exception in the application still ends the request."""
        app = request_activity.RequestActivityMiddleware(_wsgi_app(fail=True))
        with pytest.raises(RuntimeError):
            app({}, lambda *_a: None)
        assert request_activity.requests_in_flight() == 0

    def test_through_the_flask_app(self):
        """The application counts a request until its response is closed, as gunicorn does."""
        import app as app_module

        client = app_module.app.test_client()
        response = client.get('/health')
        assert response.status_code == 200
        assert request_activity.requests_in_flight() == 1
        response.close()
        assert request_activity.requests_in_flight() == 0


class TestYieldToRequests:
    def test_returns_at_once_when_nobody_is_browsing(self):
        started = time.monotonic()
        request_activity.yield_to_requests()
        assert time.monotonic() - started < 0.01

    def test_pause_is_bounded_while_requests_keep_running(self):
        """A calculation keeps moving: one pause lasts MAX_PAUSE_SECONDS at most."""
        request_activity.request_started()
        started = time.monotonic()
        request_activity.yield_to_requests()
        elapsed = time.monotonic() - started
        assert request_activity.MAX_PAUSE_SECONDS * 0.8 <= elapsed < request_activity.MAX_PAUSE_SECONDS + 0.05

    def test_resumes_as_soon_as_the_request_ends(self, monkeypatch):
        """The pause ends when the last request finishes, not at the bound."""
        monkeypatch.setattr(request_activity, 'MAX_PAUSE_SECONDS', 2.0)
        token = request_activity.request_started()
        threading.Timer(0.05, request_activity.request_finished, args=(token,)).start()
        started = time.monotonic()
        request_activity.yield_to_requests()
        assert time.monotonic() - started < 1.0

    def test_long_running_requests_are_not_waited_for(self):
        """A download older than RECENT_SECONDS (a streamed video) does not hold calculations back."""
        token = request_activity.request_started()
        with request_activity._lock:
            request_activity._in_flight[token] = time.monotonic() - request_activity.RECENT_SECONDS - 1
        assert request_activity.requests_in_flight() == 0
        started = time.monotonic()
        request_activity.yield_to_requests()
        assert time.monotonic() - started < 0.01


def test_requests_never_closed_are_eventually_forgotten(monkeypatch):
    """Tokens of responses nobody closed are pruned once very old, bounding the bookkeeping."""
    monkeypatch.setattr(request_activity, '_PRUNE_ABOVE', 3)
    for _ in range(4):
        token = request_activity.request_started()
        with request_activity._lock:
            request_activity._in_flight[token] = time.monotonic() - request_activity._FORGET_SECONDS - 1
    request_activity.request_started()
    assert len(request_activity._in_flight) == 1
