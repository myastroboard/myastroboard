"""Unit tests for AstrodexStreamConnector."""

from connectors.astrodex_stream_connector import AstrodexStreamConnector


def test_is_configured_is_always_true():
    """Nothing external to install - usable as soon as it's enabled."""
    connector = AstrodexStreamConnector({})
    assert connector.is_configured() is True


def test_health_check_reports_reachable_with_no_modules():
    connector = AstrodexStreamConnector({})
    assert connector.health_check() == {"reachable": True, "modules": {}}
