"""Maintenance mode after a failed legacy import: everything answers 503 except the health check."""

import pytest

from db import bootstrap


@pytest.fixture
def maintenance(monkeypatch):
    monkeypatch.setattr(bootstrap, 'is_maintenance', lambda: True)


def test_api_answers_503_with_json(client, maintenance):
    response = client.get('/api/version')
    assert response.status_code == 503
    assert response.get_json()['error'] == 'maintenance'


def test_pages_answer_503_with_text(client, maintenance):
    response = client.get('/login')
    assert response.status_code == 503
    assert response.mimetype == 'text/plain'
    assert 'data/backups/' in response.get_data(as_text=True)


def test_health_check_still_answers(client, maintenance):
    assert client.get('/health').status_code == 200


def test_normal_requests_are_not_blocked(client):
    assert client.get('/health').status_code == 200
    assert client.get('/login').status_code != 503
