"""Tests for the frozen-target coordinate resolver.

The two shapes exercised here are the ones actually written to disk: the SkyTonight
target cards store a decimal-hours float, the SkyTonight result tables store the
formatted ``"21h 31m 48.32s"`` string, and both end up in the same ``ra`` field of a
Plan My Night / Observation Log entry.
"""

import pytest

from observation import target_coordinates
from observation.target_coordinates import (
    parse_dec_to_degrees,
    parse_ra_to_degrees,
    resolve_coordinates,
    resolve_from_dataset,
)


class TestParseRaToDegrees:
    """Right ascension, in every shape a frozen record can carry."""

    def test_decimal_hours_float_becomes_degrees(self):
        """The target-card path stores coordinates.ra_hours."""
        assert parse_ra_to_degrees(21.530088888888887) == pytest.approx(322.95133, abs=1e-4)

    def test_integer_hours(self):
        assert parse_ra_to_degrees(12) == pytest.approx(180.0)

    def test_hms_string_from_the_results_table(self):
        """The table path stores the formatted ra_hms column."""
        assert parse_ra_to_degrees('21h 31m 48.32s') == pytest.approx(322.9513, abs=1e-3)

    def test_hms_string_without_spaces(self):
        assert parse_ra_to_degrees('21h31m48.32s') == pytest.approx(322.9513, abs=1e-3)

    def test_colon_separated_string(self):
        assert parse_ra_to_degrees('21:31:48.32') == pytest.approx(322.9513, abs=1e-3)

    def test_hours_and_minutes_without_seconds(self):
        assert parse_ra_to_degrees('06h 30m') == pytest.approx(97.5)

    def test_bare_decimal_string_is_read_as_hours(self):
        assert parse_ra_to_degrees('12.0') == pytest.approx(180.0)

    def test_value_above_24_is_read_as_degrees(self):
        """Only degrees can exceed 24; reading it as hours would run past the sky."""
        assert parse_ra_to_degrees(314.75) == pytest.approx(314.75)

    def test_24_hours_wraps_to_zero(self):
        assert parse_ra_to_degrees('24h 00m 00s') == pytest.approx(0.0)

    def test_zero_is_valid_not_falsy(self):
        assert parse_ra_to_degrees(0.0) == pytest.approx(0.0)
        assert parse_ra_to_degrees('00h 00m 00s') == pytest.approx(0.0)

    def test_negative_is_rejected(self):
        assert parse_ra_to_degrees(-1.0) is None

    def test_out_of_range_is_rejected(self):
        assert parse_ra_to_degrees(400.0) is None

    def test_impossible_minutes_or_seconds_are_rejected(self):
        assert parse_ra_to_degrees('21h 61m 00s') is None
        assert parse_ra_to_degrees('21h 30m 90s') is None

    def test_missing_and_unparseable_values(self):
        assert parse_ra_to_degrees(None) is None
        assert parse_ra_to_degrees('') is None
        assert parse_ra_to_degrees('   ') is None
        assert parse_ra_to_degrees('not a coordinate') is None

    def test_booleans_are_not_numbers(self):
        assert parse_ra_to_degrees(True) is None


class TestParseDecToDegrees:
    """Declination, including the negative-zero case that trips naive parsers."""

    def test_decimal_degrees_float(self):
        assert parse_dec_to_degrees(48.43816666666666) == pytest.approx(48.43817, abs=1e-5)

    def test_dms_string_from_the_results_table(self):
        assert parse_dec_to_degrees('48° 26\' 17.40"') == pytest.approx(48.43817, abs=1e-4)

    def test_dms_string_with_letter_separators(self):
        assert parse_dec_to_degrees('48d26m17.40s') == pytest.approx(48.43817, abs=1e-4)

    def test_negative_declination(self):
        assert parse_dec_to_degrees('-05:12:33') == pytest.approx(-5.209166, abs=1e-5)

    def test_negative_zero_degrees_keeps_its_sign(self):
        """A target just south of the equator has a '-00' degrees field."""
        assert parse_dec_to_degrees('-00° 30\' 00"') == pytest.approx(-0.5)

    def test_explicit_positive_sign(self):
        assert parse_dec_to_degrees('+48° 26\' 17.40"') == pytest.approx(48.43817, abs=1e-4)

    def test_poles_are_in_range(self):
        assert parse_dec_to_degrees(90.0) == pytest.approx(90.0)
        assert parse_dec_to_degrees(-90.0) == pytest.approx(-90.0)

    def test_out_of_range_is_rejected(self):
        assert parse_dec_to_degrees(91.0) is None
        assert parse_dec_to_degrees(-91.0) is None

    def test_zero_is_valid_not_falsy(self):
        assert parse_dec_to_degrees(0.0) == pytest.approx(0.0)

    def test_missing_and_unparseable_values(self):
        assert parse_dec_to_degrees(None) is None
        assert parse_dec_to_degrees('') is None
        assert parse_dec_to_degrees('somewhere up there') is None


class TestResolveFromDataset:
    """The dataset lookup, which is the canonical source when the object is known."""

    def test_known_target_resolves(self, monkeypatch):
        """A lookup hit wins regardless of what the record itself stored."""
        monkeypatch.setattr(
            target_coordinates.skytonight_targets,
            'get_lookup_entry',
            lambda catalogue, name: {'ra_deg': 10.68, 'dec_deg': 41.27} if 'M 31' in name else {},
        )
        assert resolve_from_dataset('M 31', 'Messier') == (10.68, 41.27)

    def test_display_label_is_reduced_to_its_identifier(self, monkeypatch):
        """Astrodex stores items as 'M31 - Andromeda Galaxy', not as a bare identifier."""
        seen = []

        def fake_lookup(catalogue, name):
            seen.append(name)
            return {'ra_deg': 10.68, 'dec_deg': 41.27} if name == 'M31' else {}

        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', fake_lookup)
        assert resolve_from_dataset('M31 - Andromeda Galaxy') == (10.68, 41.27)
        assert 'M31 - Andromeda Galaxy' in seen

    def test_missing_catalogue_falls_back_to_the_preferred_key(self, monkeypatch):
        """get_lookup_entry returns nothing for an empty catalogue, so one is supplied."""
        seen = []

        def fake_lookup(catalogue, name):
            seen.append(catalogue)
            return {}

        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', fake_lookup)
        resolve_from_dataset('Something', '')
        assert seen and all(catalogue == 'preferred' for catalogue in seen)

    def test_unknown_target_returns_none(self, monkeypatch):
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        assert resolve_from_dataset('Not A Real Object', 'Messier') is None

    def test_entry_without_coordinates_returns_none(self, monkeypatch):
        """Comets and bodies can be in the lookup with no fixed coordinates."""
        monkeypatch.setattr(
            target_coordinates.skytonight_targets,
            'get_lookup_entry',
            lambda *_: {'ra_deg': None, 'dec_deg': None},
        )
        assert resolve_from_dataset('C/2023 A3', 'Comets') is None

    def test_out_of_range_entry_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            target_coordinates.skytonight_targets,
            'get_lookup_entry',
            lambda *_: {'ra_deg': 999.0, 'dec_deg': 41.27},
        )
        assert resolve_from_dataset('Corrupt', 'Messier') is None

    def test_empty_name_returns_none(self):
        assert resolve_from_dataset('') is None
        assert resolve_from_dataset(None) is None


class TestResolveCoordinates:
    """The full resolution order used by the sky coverage map and the wishlist."""

    def test_dataset_wins_over_the_stored_snapshot(self, monkeypatch):
        monkeypatch.setattr(
            target_coordinates.skytonight_targets,
            'get_lookup_entry',
            lambda *_: {'ra_deg': 10.68, 'dec_deg': 41.27},
        )
        assert resolve_coordinates('M 31', 'Messier', ra=0.0, dec=0.0) == (10.68, 41.27)

    def test_falls_back_to_the_stored_snapshot(self, monkeypatch):
        """An object outside the dataset still places if the record carries coordinates."""
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        resolved = resolve_coordinates('Some Star', 'SIMBAD', ra='21h 31m 48.32s', dec='48° 26\' 17.40"')
        assert resolved is not None
        assert resolved[0] == pytest.approx(322.9513, abs=1e-3)
        assert resolved[1] == pytest.approx(48.43817, abs=1e-4)

    def test_half_a_coordinate_is_not_a_coordinate(self, monkeypatch):
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        assert resolve_coordinates('Half', 'SIMBAD', ra='21h 31m 48.32s', dec=None) is None

    def test_unresolvable_returns_none(self, monkeypatch):
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        assert resolve_coordinates('Nothing', 'Nowhere') is None


class TestResolveTarget:
    """The richer resolver used by the sky coverage map and by wishlist creation."""

    def test_known_target_carries_its_dataset_identity(self, monkeypatch):
        monkeypatch.setattr(
            target_coordinates.skytonight_targets,
            'get_lookup_entry',
            lambda *_: {
                'group_id': 'dso-openngc-ngc0224',
                'target_id': 'dso-openngc-ngc0224',
                'preferred_name': 'M 31',
                'object_type': 'Galaxy',
                'constellation': 'And',
                'category': 'deep_sky',
                'ra_deg': 10.68,
                'dec_deg': 41.27,
            },
        )
        resolved = target_coordinates.resolve_target('M 31', 'Messier')
        assert resolved['group_id'] == 'dso-openngc-ngc0224'
        assert resolved['preferred_name'] == 'M 31'
        assert resolved['object_type'] == 'Galaxy'
        assert resolved['ra_deg'] == 10.68
        assert resolved['dec_deg'] == 41.27
        assert resolved['resolved'] is True
        assert resolved['placed'] is True

    def test_unknown_target_still_places_from_its_own_snapshot(self, monkeypatch):
        """A SIMBAD-resolved star is outside the dataset but has coordinates of its own."""
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        resolved = target_coordinates.resolve_target('Some Star', 'SIMBAD', ra=12.0, dec=30.0)
        assert resolved['group_id'] == ''
        assert resolved['resolved'] is False
        assert resolved['placed'] is True
        assert resolved['ra_deg'] == pytest.approx(180.0)

    def test_unplaceable_target_reports_both_flags_false(self, monkeypatch):
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        resolved = target_coordinates.resolve_target('Mystery')
        assert resolved['resolved'] is False
        assert resolved['placed'] is False
        assert resolved['ra_deg'] is None
        assert resolved['dec_deg'] is None

    def test_payload_shape_is_always_complete(self, monkeypatch):
        """Consumers index into this dict unconditionally."""
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        expected = {
            'group_id', 'target_id', 'preferred_name', 'object_type', 'constellation',
            'category', 'ra_deg', 'dec_deg', 'resolved', 'placed',
        }
        assert set(target_coordinates.resolve_target('Anything')) == expected


class TestLookupDatasetEntry:

    def test_returns_the_entry_for_a_known_object(self, monkeypatch):
        monkeypatch.setattr(
            target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {'group_id': 'g1'}
        )
        assert target_coordinates.lookup_dataset_entry('M 31', 'Messier') == {'group_id': 'g1'}

    def test_returns_empty_for_an_unknown_object(self, monkeypatch):
        monkeypatch.setattr(target_coordinates.skytonight_targets, 'get_lookup_entry', lambda *_: {})
        assert target_coordinates.lookup_dataset_entry('Nope', 'Messier') == {}

    def test_empty_name_short_circuits(self):
        assert target_coordinates.lookup_dataset_entry('') == {}
