"""Tests for security_settings.py: trusted networks and the instance-wide 2FA switch."""

import json

import pytest


@pytest.fixture(autouse=True)
def reset_security_settings_cache():
    """Clear the module-level cache before and after each test."""
    from utils import security_settings

    security_settings._cache = None
    yield
    security_settings._cache = None


@pytest.fixture
def settings_module(tmp_path, monkeypatch):
    """security_settings pointed at an isolated data directory."""
    from utils import security_settings

    monkeypatch.setattr(security_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(security_settings, '_SECURITY_SETTINGS_FILE', str(tmp_path / 'security_settings.json'))
    return security_settings


# ---------------------------------------------------------------------------
# load / save / defaults
# ---------------------------------------------------------------------------


def test_defaults_when_no_file(settings_module):
    settings = settings_module.load_security_settings()

    assert settings == {'trusted_networks': [], 'two_factor_enabled': False}


def test_save_then_load_round_trip(tmp_path, settings_module):
    settings_module.save_security_settings({'trusted_networks': ['192.168.1.0/24'], 'two_factor_enabled': True})

    on_disk = json.loads((tmp_path / 'security_settings.json').read_text())
    assert on_disk == {'trusted_networks': ['192.168.1.0/24'], 'two_factor_enabled': True}

    settings_module._cache = None
    assert settings_module.load_security_settings() == on_disk


def test_get_settings_uses_cache(tmp_path, settings_module):
    settings_module.save_security_settings({'trusted_networks': ['10.0.0.0/8'], 'two_factor_enabled': True})

    # An external write must not change the answer while the cache is warm; only
    # reload_security_settings() goes back to disk.
    (tmp_path / 'security_settings.json').write_text(
        json.dumps({'trusted_networks': ['172.16.0.0/12'], 'two_factor_enabled': False})
    )

    assert settings_module.get_security_settings()['trusted_networks'] == ['10.0.0.0/8']


def test_reload_picks_up_external_change(tmp_path, settings_module):
    settings_module.save_security_settings({'trusted_networks': ['10.0.0.0/8'], 'two_factor_enabled': False})

    (tmp_path / 'security_settings.json').write_text(
        json.dumps({'trusted_networks': ['172.16.0.0/12'], 'two_factor_enabled': False})
    )

    assert settings_module.reload_security_settings()['trusted_networks'] == ['172.16.0.0/12']


def test_unknown_keys_in_file_are_ignored(tmp_path, settings_module):
    (tmp_path / 'security_settings.json').write_text(
        json.dumps({'trusted_networks': ['10.0.0.0/8'], 'two_factor_enabled': False, 'unexpected': 'value'})
    )

    assert settings_module.load_security_settings() == {
        'trusted_networks': ['10.0.0.0/8'],
        'two_factor_enabled': False,
    }


def test_corrupt_file_falls_back_to_defaults(tmp_path, settings_module):
    (tmp_path / 'security_settings.json').write_text('{not json')

    assert settings_module.load_security_settings() == {'trusted_networks': [], 'two_factor_enabled': False}


def test_hand_edited_non_list_networks_is_coerced(tmp_path, settings_module):
    (tmp_path / 'security_settings.json').write_text(
        json.dumps({'trusted_networks': '192.168.1.0/24', 'two_factor_enabled': False})
    )

    assert settings_module.load_security_settings()['trusted_networks'] == []


def test_two_factor_forced_off_when_file_has_no_network(tmp_path, settings_module):
    """The documented cascade also applies to a hand-edited file, not just to saves."""
    (tmp_path / 'security_settings.json').write_text(
        json.dumps({'trusted_networks': [], 'two_factor_enabled': True})
    )

    assert settings_module.load_security_settings()['two_factor_enabled'] is False


# ---------------------------------------------------------------------------
# normalize_network / normalize_networks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'raw,expected',
    [
        ('192.168.1.0/24', '192.168.1.0/24'),
        # A host address inside a block normalizes to the block, so the same network
        # cannot be stored twice under two different strings.
        ('192.168.1.5/24', '192.168.1.0/24'),
        ('10.0.0.1', '10.0.0.1/32'),
        ('  172.16.0.0/12  ', '172.16.0.0/12'),
        ('2001:db8::/32', '2001:db8::/32'),
        ('::1', '::1/128'),
    ],
)
def test_normalize_network_accepts_ipv4_and_ipv6(settings_module, raw, expected):
    assert settings_module.normalize_network(raw) == expected


@pytest.mark.parametrize('raw', ['', '   ', 'not-a-network', '192.168.1.0/33', '999.1.1.1', None, 42, ['10.0.0.0/8']])
def test_normalize_network_rejects_garbage(settings_module, raw):
    with pytest.raises(ValueError):
        settings_module.normalize_network(raw)


def test_normalize_networks_dedupes_and_keeps_order(settings_module):
    result = settings_module.normalize_networks(['10.0.0.0/8', '192.168.1.5/24', '192.168.1.0/24'])

    assert result == ['10.0.0.0/8', '192.168.1.0/24']


def test_normalize_networks_rejects_non_list(settings_module):
    with pytest.raises(ValueError):
        settings_module.normalize_networks('192.168.1.0/24')


# ---------------------------------------------------------------------------
# client_ip_is_trusted / effective networks
# ---------------------------------------------------------------------------


def test_client_ip_inside_network_is_trusted(settings_module):
    assert settings_module.client_ip_is_trusted('192.168.1.42', ['192.168.1.0/24']) is True


def test_client_ip_outside_network_is_not_trusted(settings_module):
    assert settings_module.client_ip_is_trusted('203.0.113.7', ['192.168.1.0/24']) is False


def test_client_ip_missing_or_unparseable_is_never_trusted(settings_module):
    assert settings_module.client_ip_is_trusted(None, ['0.0.0.0/0']) is False
    assert settings_module.client_ip_is_trusted('', ['0.0.0.0/0']) is False
    assert settings_module.client_ip_is_trusted('not-an-ip', ['0.0.0.0/0']) is False


def test_unparseable_network_entry_is_skipped_not_raised(settings_module):
    """A hand-edited file must not be able to break login with a bad entry."""
    assert settings_module.client_ip_is_trusted('192.168.1.42', ['garbage', '192.168.1.0/24']) is True


def test_ipv4_address_does_not_match_ipv6_network(settings_module):
    assert settings_module.client_ip_is_trusted('192.168.1.42', ['::/0']) is False


def test_ipv6_client_matches_ipv6_network(settings_module):
    assert settings_module.client_ip_is_trusted('2001:db8::1', ['2001:db8::/32']) is True


def test_effective_networks_always_include_loopback(settings_module):
    settings_module.save_security_settings({'trusted_networks': ['192.168.1.0/24'], 'two_factor_enabled': True})

    effective = settings_module.get_effective_trusted_networks()

    assert '127.0.0.0/8' in effective
    assert '::1/128' in effective
    assert '192.168.1.0/24' in effective


def test_loopback_trusted_even_with_empty_configured_list(settings_module):
    settings_module.save_security_settings({'trusted_networks': [], 'two_factor_enabled': False})

    assert settings_module.is_client_ip_trusted('127.0.0.1') is True
    assert settings_module.is_client_ip_trusted('::1') is True
    assert settings_module.is_client_ip_trusted('192.168.1.42') is False


def test_loopback_is_never_written_to_the_file(tmp_path, settings_module):
    """ALWAYS_TRUSTED_NETWORKS is unioned at check time, never persisted."""
    settings_module.save_security_settings({'trusted_networks': ['192.168.1.0/24'], 'two_factor_enabled': True})

    on_disk = json.loads((tmp_path / 'security_settings.json').read_text())
    assert on_disk['trusted_networks'] == ['192.168.1.0/24']
