"""Tests for the shared constellation abbreviation -> full name helper.

Covers the behaviour the three former private copies (beginner_catalog,
catalogue_collection, skytonight_api) each relied on, now that they all delegate here.
"""

from utils.constellation_names import ABBREVIATION_TO_NAME, full_constellation_name


class TestFullConstellationName:
    """Expansion of the values the dataset and frozen user records actually carry."""

    def test_abbreviation_is_expanded(self):
        """A plain IAU abbreviation becomes its full name."""
        assert full_constellation_name('And') == 'Andromeda'
        assert full_constellation_name('Cyg') == 'Cygnus'

    def test_camel_case_enum_names_are_split(self):
        """Multi-word constellations come out of the enum concatenated."""
        assert full_constellation_name('CMa') == 'Canis Major'
        assert full_constellation_name('CVn') == 'Canes Venatici'
        assert full_constellation_name('PsA') == 'Piscis Austrinus'

    def test_pyongc_serpens_halves_are_expanded(self):
        """Se1/Se2 are PyOngc-only codes absent from the IAU enum."""
        assert full_constellation_name('Se1') == 'Serpens Caput'
        assert full_constellation_name('Se2') == 'Serpens Cauda'

    def test_already_expanded_name_survives(self):
        """Frozen records may store the full name instead of the abbreviation."""
        assert full_constellation_name('Andromeda') == 'Andromeda'
        assert full_constellation_name('Canes Venatici') == 'Canes Venatici'

    def test_expanded_name_is_normalized_to_canonical_casing(self):
        """The i18n keys are derived from the canonical spelling, so casing must converge."""
        assert full_constellation_name('cygnus') == 'Cygnus'
        assert full_constellation_name('CANES VENATICI') == 'Canes Venatici'

    def test_surrounding_whitespace_is_stripped(self):
        assert full_constellation_name('  Cyg  ') == 'Cygnus'

    def test_unknown_values_pass_through(self):
        """An unrecognized name still displays rather than disappearing."""
        assert full_constellation_name('Nonsense') == 'Nonsense'

    def test_empty_values_return_empty_string(self):
        assert full_constellation_name(None) == ''
        assert full_constellation_name('') == ''
        assert full_constellation_name('   ') == ''

    def test_non_string_values_are_coerced(self):
        """Frozen records occasionally carry a non-string in this field."""
        assert full_constellation_name(0) == ''
        assert full_constellation_name(123) == '123'


class TestAbbreviationTable:
    """The table itself, which callers may iterate to build a filter dropdown."""

    def test_covers_the_88_iau_constellations_plus_both_serpens_halves(self):
        assert len(ABBREVIATION_TO_NAME) == 90

    def test_every_entry_maps_to_a_non_empty_name(self):
        assert all(key and value for key, value in ABBREVIATION_TO_NAME.items())
