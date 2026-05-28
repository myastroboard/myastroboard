"""Tests for SkyTonight comet ingestion."""

import math

from skytonight_comets import (
    _coerce_coordinates,
    _curated_fallback_rows,
    _parse_comets_txt_line,
    _safe_float,
    _solve_kepler_elliptic,
    _solve_kepler_hyperbolic,
    _target_id_from_name,
    _to_comet_target,
    build_comet_targets,
    enrich_with_jpl_fallback,
    fetch_mpc_comets,
)


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------

def test_build_comet_targets_uses_curated_fallback_when_network_unavailable(monkeypatch):
    monkeypatch.setattr('skytonight_comets.fetch_mpc_comets', lambda timeout_seconds=12: [])

    targets = build_comet_targets('mpc+jpl')

    assert targets
    assert all(target.category == 'comets' for target in targets)
    assert any(target.metadata.get('source') == 'curated-fallback' for target in targets)


def test_enrich_with_jpl_fallback_fills_missing_fields(monkeypatch):
    row = {
        'name': '13P/Olbers',
        'designation': '',
        'absolute_magnitude': None,
    }

    monkeypatch.setattr(
        'skytonight_comets._fetch_jpl_comet_snapshot',
        lambda name, timeout_seconds=8: {
            'name': '13P/Olbers',
            'designation': '13P',
            'absolute_magnitude': 9.1,
            'orbit_class': 'Periodic Comet',
        },
    )

    enriched = enrich_with_jpl_fallback([row])

    assert len(enriched) == 1
    assert enriched[0]['designation'] == '13P'
    assert enriched[0]['absolute_magnitude'] == 9.1


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

def test_safe_float_returns_none_for_none():
    assert _safe_float(None) is None


def test_safe_float_converts_numeric_string():
    assert _safe_float('3.14') == pytest.approx(3.14)


def test_safe_float_returns_none_for_invalid_string():
    assert _safe_float('not-a-number') is None


def test_safe_float_passes_through_int():
    assert _safe_float(42) == 42.0


import pytest  # noqa: E402  (placed after fixtures that use it)


# ---------------------------------------------------------------------------
# _target_id_from_name
# ---------------------------------------------------------------------------

def test_target_id_from_name_produces_comet_prefix():
    tid = _target_id_from_name('13P/Olbers')
    assert tid.startswith('comet-')


def test_target_id_from_name_is_lowercase_normalized():
    tid = _target_id_from_name('C/2023 A3')
    # Must not contain uppercase after prefix
    assert tid == tid.lower()


# ---------------------------------------------------------------------------
# _coerce_coordinates
# ---------------------------------------------------------------------------

def test_coerce_coordinates_returns_object_when_both_present():
    coords = _coerce_coordinates({'ra_hours': 5.5, 'dec_degrees': 10.0})
    assert coords is not None
    assert coords.ra_hours == pytest.approx(5.5)
    assert coords.dec_degrees == pytest.approx(10.0)


def test_coerce_coordinates_returns_none_when_ra_missing():
    assert _coerce_coordinates({'ra_hours': None, 'dec_degrees': 10.0}) is None


def test_coerce_coordinates_returns_none_when_dec_missing():
    assert _coerce_coordinates({'ra_hours': 5.5, 'dec_degrees': None}) is None


def test_coerce_coordinates_returns_none_when_both_absent():
    assert _coerce_coordinates({}) is None


# ---------------------------------------------------------------------------
# _to_comet_target
# ---------------------------------------------------------------------------

def test_to_comet_target_builds_target_from_complete_row():
    row = {
        'name': '13P/Olbers',
        'designation': '13P',
        'magnitude': 7.0,
        'perihelion_date': '2026-10-20',
        'ra_hours': 5.5,
        'dec_degrees': 10.0,
        'orbit_class': 'P',
    }
    target = _to_comet_target(row, source='mpc')
    assert target is not None
    assert target.preferred_name == '13P/Olbers'
    assert target.category == 'comets'
    assert target.object_type == 'Comet'
    assert '13P' in target.aliases
    assert target.metadata['source'] == 'mpc'
    assert target.coordinates is not None


def test_to_comet_target_returns_none_for_empty_name():
    assert _to_comet_target({'name': '', 'designation': ''}, source='mpc') is None


def test_to_comet_target_omits_alias_when_same_as_name():
    row = {'name': '13P/Olbers', 'designation': '13P/Olbers'}
    target = _to_comet_target(row, source='mpc')
    assert target is not None
    assert '13P/Olbers' not in target.aliases


def test_to_comet_target_uses_designation_as_name_fallback():
    row = {'name': '', 'designation': '13P'}
    target = _to_comet_target(row, source='mpc')
    assert target is not None
    assert target.preferred_name == '13P'


# ---------------------------------------------------------------------------
# _parse_comets_txt_line
# ---------------------------------------------------------------------------

def _make_mpc_line(
    name='13P/Olbers',
    orbit_type='P',
    year=2026,
    month=10,
    day=20.1234,
    q=1.234567,
    e=0.876543,
    omega=123.456,
    cap_omega=234.567,
    incl=45.678,
    epoch='20260101',
    abs_mag=10.1,
    designation='0013P  ',
):
    """Construct a minimal valid MPC CometEls.txt line."""
    return (
        '    '                    # [0:4]
        + orbit_type              # [4]
        + f'{designation:<7}'     # [5:12]
        + '  '                    # [12:14]
        + f'{year:4d}'            # [14:18]
        + ' '                     # [18]
        + f'{month:02d}'          # [19:21]
        + ' '                     # [21]
        + f'{day:7.4f}'           # [22:29]
        + ' '                     # [29]
        + f'{q:9.7f}'             # [30:39]
        + ' '                     # [39]
        + f'{e:9.7f}'             # [40:49]
        + ' '                     # [49]
        + f'{omega:9.5f}'         # [50:59]
        + ' '                     # [59]
        + f'{cap_omega:9.5f}'     # [60:69]
        + ' '                     # [69]
        + f'{incl:9.5f}'          # [70:79]
        + '  '                    # [79:81]
        + f'{epoch:8s}'           # [81:89]
        + '  '                    # [89:91]
        + f'{abs_mag:5.1f}'       # [91:96]
        + '      '                # [96:102]
        + name                    # [102:]
    )


def test_parse_comets_txt_line_parses_valid_line():
    line = _make_mpc_line()
    result = _parse_comets_txt_line(line)
    assert result is not None
    assert result['name'] == '13P/Olbers'
    assert result['orbit_type'] == 'P'
    assert result['perihelion_year'] == 2026
    assert result['perihelion_month'] == 10
    assert result['q'] == pytest.approx(1.234567, rel=1e-5)
    assert result['absolute_magnitude'] == pytest.approx(10.1, rel=1e-4)


def test_parse_comets_txt_line_returns_none_for_short_line():
    assert _parse_comets_txt_line('short') is None


def test_parse_comets_txt_line_returns_none_for_invalid_orbit_type():
    line = _make_mpc_line(orbit_type='Z')
    assert _parse_comets_txt_line(line) is None


def test_parse_comets_txt_line_accepts_all_valid_orbit_types():
    for otype in ('P', 'C', 'X', 'D', 'I', 'A'):
        line = _make_mpc_line(orbit_type=otype)
        result = _parse_comets_txt_line(line)
        assert result is not None, f'orbit_type {otype!r} should be accepted'
        assert result['orbit_type'] == otype


def test_parse_comets_txt_line_falls_back_to_designation_when_name_empty():
    line = _make_mpc_line(name='  ')  # empty name area → use designation
    result = _parse_comets_txt_line(line)
    assert result is not None
    assert result['name'] == result['designation']


# ---------------------------------------------------------------------------
# _solve_kepler_elliptic
# ---------------------------------------------------------------------------

def test_solve_kepler_elliptic_circular_orbit_returns_m():
    # For e=0, E = M trivially
    for M in (0.0, 1.0, 2.5):
        E = _solve_kepler_elliptic(M, 0.0)
        assert E == pytest.approx(M, abs=1e-10)


def test_solve_kepler_elliptic_satisfies_kepler_equation():
    # E - e*sin(E) = M must hold to high precision
    M, e = 1.0, 0.5
    E = _solve_kepler_elliptic(M, e)
    residual = E - e * math.sin(E) - M
    assert abs(residual) < 1e-10


def test_solve_kepler_elliptic_zero_mean_anomaly():
    assert _solve_kepler_elliptic(0.0, 0.5) == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# _solve_kepler_hyperbolic
# ---------------------------------------------------------------------------

def test_solve_kepler_hyperbolic_zero_returns_zero():
    # For N=0, F=0 is the trivial solution regardless of e
    for e in (1.5, 2.0, 3.0):
        F = _solve_kepler_hyperbolic(0.0, e)
        assert F == pytest.approx(0.0, abs=1e-10)


def test_solve_kepler_hyperbolic_satisfies_equation():
    # e*sinh(F) - F = N must hold to high precision
    N, e = 1.0, 2.0
    F = _solve_kepler_hyperbolic(N, e)
    residual = e * math.sinh(F) - F - N
    assert abs(residual) < 1e-10


# ---------------------------------------------------------------------------
# _curated_fallback_rows
# ---------------------------------------------------------------------------

def test_curated_fallback_rows_returns_known_comets():
    rows = _curated_fallback_rows()
    assert rows
    names = {r['name'] for r in rows}
    assert '13P/Olbers' in names


def test_curated_fallback_rows_include_perihelion_date():
    rows = _curated_fallback_rows()
    for row in rows:
        assert 'perihelion_date' in row
        assert row['perihelion_date']


# ---------------------------------------------------------------------------
# enrich_with_jpl_fallback — additional edge cases
# ---------------------------------------------------------------------------

def test_enrich_with_jpl_fallback_skips_when_all_fields_present(monkeypatch):
    calls = []

    def _fake_jpl(name, timeout_seconds=8):
        calls.append(name)
        return {}

    monkeypatch.setattr('skytonight_comets._fetch_jpl_comet_snapshot', _fake_jpl)
    rows = [{'name': 'Halley', 'absolute_magnitude': 5.5, 'orbit_class': 'HTC'}]
    result = enrich_with_jpl_fallback(rows)
    assert len(calls) == 0
    assert result[0]['absolute_magnitude'] == 5.5


def test_enrich_with_jpl_fallback_caps_at_50_requests(monkeypatch):
    calls = []

    def _fake_jpl(name, timeout_seconds=8):
        calls.append(name)
        return {}

    monkeypatch.setattr('skytonight_comets._fetch_jpl_comet_snapshot', _fake_jpl)
    rows = [
        {'name': f'Comet{i}', 'absolute_magnitude': None, 'orbit_class': None}
        for i in range(60)
    ]
    enrich_with_jpl_fallback(rows)
    assert len(calls) == 50


def test_enrich_with_jpl_fallback_skips_non_dict_rows(monkeypatch):
    monkeypatch.setattr('skytonight_comets._fetch_jpl_comet_snapshot', lambda *a, **kw: {})
    result = enrich_with_jpl_fallback(['not-a-dict', None])  # type: ignore[list-item]
    assert result == []


# ---------------------------------------------------------------------------
# build_comet_targets — deduplication and source modes
# ---------------------------------------------------------------------------

def test_build_comet_targets_deduplicates_by_target_id(monkeypatch):
    monkeypatch.setattr('skytonight_comets.fetch_mpc_comets', lambda **kw: [])
    monkeypatch.setattr('skytonight_comets._curated_fallback_rows', lambda: [
        {'name': '13P/Olbers', 'magnitude': 7.0},
        {'name': '13P/Olbers', 'magnitude': 8.0},
    ])
    targets = build_comet_targets('mpc+jpl')
    olbers = [t for t in targets if '13P' in t.preferred_name]
    assert len(olbers) == 1
    assert olbers[0].magnitude == 7.0  # first row wins


def test_build_comet_targets_mpc_only_skips_jpl(monkeypatch):
    jpl_calls = []
    monkeypatch.setattr(
        'skytonight_comets.fetch_mpc_comets',
        lambda **kw: [{'name': 'TestComet', 'absolute_magnitude': 8.0, 'orbit_class': 'P'}],
    )
    monkeypatch.setattr(
        'skytonight_comets.enrich_with_jpl_fallback',
        lambda rows: jpl_calls.append(rows) or rows,
    )
    build_comet_targets('mpc')
    assert len(jpl_calls) == 0  # JPL enrichment not called when mode is 'mpc' only


def test_build_comet_targets_all_are_comets(monkeypatch):
    monkeypatch.setattr('skytonight_comets.fetch_mpc_comets', lambda **kw: [])
    targets = build_comet_targets('mpc+jpl')
    assert all(t.category == 'comets' for t in targets)


# ---------------------------------------------------------------------------
# fetch_mpc_comets — network layer
# ---------------------------------------------------------------------------

def test_fetch_mpc_comets_returns_empty_on_network_error(monkeypatch):
    import requests as _requests

    def _raise(*args, **kwargs):
        raise _requests.RequestException('connection timeout')

    monkeypatch.setattr('skytonight_comets.requests.get', _raise)
    result = fetch_mpc_comets()
    assert result == []


def test_fetch_mpc_comets_parses_valid_response(monkeypatch):
    valid_line = _make_mpc_line()

    class _FakeResponse:
        status_code = 200
        text = valid_line + '\n'

        def raise_for_status(self):
            pass

    monkeypatch.setattr('skytonight_comets.requests.get', lambda *a, **kw: _FakeResponse())
    monkeypatch.setattr(
        'skytonight_comets._get_earth_heliocentric',
        lambda obs_time: (1.0, 0.0, 0.0),
    )
    monkeypatch.setattr(
        'skytonight_comets._comet_ra_dec',
        lambda *a, **kw: (5.5, 10.0, 1.2, 0.8),
    )

    result = fetch_mpc_comets()
    assert len(result) == 1
    assert result[0]['name'] == '13P/Olbers'
    assert result[0]['ra_hours'] == pytest.approx(5.5)
    assert result[0]['perihelion_date'] == '2026-10-20'
