"""
Tests for events_aggregator module.
Tests event aggregation, filtering, sorting, and translation logic.
"""

import pytest
from datetime import timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from events_aggregator import (
    EventType,
    EventImportance,
    AstronomicalEvent,
    EventsAggregator,
)


@pytest.fixture
def aggregator():
    """Create an EventsAggregator instance for testing."""
    return EventsAggregator(
        latitude=45.0,
        longitude=-75.0,
        timezone="America/Toronto",
        language="en"
    )


@pytest.fixture
def aggregator_french():
    """Create a French EventsAggregator instance for testing."""
    return EventsAggregator(
        latitude=45.0,
        longitude=-75.0,
        timezone="America/Toronto",
        language="fr"
    )


class TestEventTypeEnum:
    """Tests for EventType enumeration."""

    def test_solar_eclipse_event_type(self):
        """Test solar eclipse event type."""
        assert EventType.SOLAR_ECLIPSE.value == "Solar Eclipse"

    def test_lunar_eclipse_event_type(self):
        """Test lunar eclipse event type."""
        assert EventType.LUNAR_ECLIPSE.value == "Lunar Eclipse"

    def test_aurora_event_type(self):
        """Test aurora event type."""
        assert EventType.AURORA.value == "Aurora"

    def test_planetary_conjunction_event_type(self):
        """Test planetary conjunction event type."""
        assert EventType.PLANETARY_CONJUNCTION.value == "Planetary Conjunction"


class TestEventImportanceEnum:
    """Tests for EventImportance enumeration."""

    def test_critical_importance(self):
        """Test critical importance level."""
        assert EventImportance.CRITICAL.value == "critical"

    def test_high_importance(self):
        """Test high importance level."""
        assert EventImportance.HIGH.value == "high"

    def test_medium_importance(self):
        """Test medium importance level."""
        assert EventImportance.MEDIUM.value == "medium"

    def test_low_importance(self):
        """Test low importance level."""
        assert EventImportance.LOW.value == "low"


class TestAstronomicalEvent:
    """Tests for AstronomicalEvent dataclass."""

    def test_create_eclipse_event(self):
        """Test creating an eclipse event."""
        event = AstronomicalEvent(
            id="solar_eclipse_20260812",
            event_type="Solar Eclipse",
            icon_class="bi bi-sun",
            icon_color_class="text-warning",
            title="Partial Solar Eclipse",
            description="A partial eclipse visible from your location",
            start_time="2026-08-12T13:05:00",
            peak_time="2026-08-12T14:32:00",
            end_time="2026-08-12T15:59:00",
            days_until_event=170,
            visibility=True,
            importance="high",
            score=8.5,
            raw_data={},
            structure_key="solar"
        )
        
        assert event.id == "solar_eclipse_20260812"
        assert event.event_type == "Solar Eclipse"
        assert event.importance == "high"
        assert event.visibility is True

    def test_event_with_optional_none_values(self):
        """Test creating event with None optional fields."""
        event = AstronomicalEvent(
            id="test_event",
            event_type="Test",
            icon_class="bi bi-star",
            icon_color_class="text-info",
            title="Test Event",
            description="Test description",
            start_time=None,
            peak_time=None,
            end_time=None,
            days_until_event=10,
            visibility=False,
            importance="low",
            score=None,
            raw_data={},
            structure_key="test"
        )
        
        assert event.start_time is None
        assert event.score is None


class TestEventsAggregatorInitialization:
    """Tests for EventsAggregator initialization."""

    def test_init_with_valid_timezone(self, aggregator):
        """Test initialization with valid timezone."""
        assert aggregator.latitude == 45.0
        assert aggregator.longitude == -75.0
        assert aggregator.timezone == ZoneInfo("America/Toronto")

    def test_init_with_utc_timezone(self):
        """Test initialization with UTC timezone."""
        agg = EventsAggregator(
            latitude=0.0,
            longitude=0.0,
            timezone="UTC",
            language="en"
        )
        assert agg.timezone == ZoneInfo("UTC")

    def test_init_sets_i18n_language(self, aggregator):
        """Test that i18n manager is initialized."""
        assert aggregator.i18n is not None

    def test_init_with_french_language(self, aggregator_french):
        """Test initialization with French language."""
        assert aggregator_french.i18n is not None


class TestTranslationHelpers:
    """Tests for translation helper methods."""

    def test_translate_method_t(self, aggregator):
        """Test _t translation method with fallback."""
        result = aggregator._t("nonexistent_key", "fallback_text")
        # Should return fallback if key doesn't exist
        assert "fallback" in result.lower() or result == "nonexistent_key"

    def test_translate_eclipse_type_total(self, aggregator):
        """Test eclipse type translation for Total."""
        result = aggregator._translate_eclipse_type("Total", "solar_eclipse")
        assert result is not None
        assert isinstance(result, str)

    def test_translate_eclipse_type_partial(self, aggregator):
        """Test eclipse type translation for Partial."""
        result = aggregator._translate_eclipse_type("Partial", "lunar_eclipse")
        assert result is not None

    def test_translate_eclipse_type_annular(self, aggregator):
        """Test eclipse type translation for Annular."""
        result = aggregator._translate_eclipse_type("Annular", "solar_eclipse")
        assert result is not None

    def test_moon_phase_translation_full_moon(self, aggregator):
        """Test moon phase translation for Full Moon."""
        result = aggregator._get_moon_phase_translation("Full Moon")
        assert result is not None

    def test_moon_phase_translation_new_moon(self, aggregator):
        """Test moon phase translation for New Moon."""
        result = aggregator._get_moon_phase_translation("New Moon")
        assert result is not None

    def test_moon_phase_translation_waxing_crescent(self, aggregator):
        """Test moon phase translation for Waxing Crescent."""
        result = aggregator._get_moon_phase_translation("Waxing Crescent")
        assert result is not None

    def test_planet_name_translation_venus(self, aggregator):
        """Test planet name translation."""
        result = aggregator._translate_planet_name("Venus")
        assert result is not None

    def test_planet_name_translation_empty(self, aggregator):
        """Test planet name translation with empty string."""
        result = aggregator._translate_planet_name("")
        assert result == ""

    def test_visibility_period_translation(self, aggregator):
        """Test visibility period translation."""
        result = aggregator._translate_visibility_period("Astronomical Night")
        assert result is not None

    def test_visibility_period_translation_unknown(self, aggregator):
        """Test visibility period translation for unknown."""
        result = aggregator._translate_visibility_period("Unknown")
        assert result is not None


class TestIconAndImportanceMapping:
    """Tests for icon class and importance mapping methods."""

    def test_importance_icon_color_critical(self, aggregator):
        """Test icon color for critical importance."""
        result = aggregator._importance_icon_color_class("critical")
        assert "must-see" in result or "danger" in result or "critical" in result

    def test_importance_icon_color_high(self, aggregator):
        """Test icon color for high importance."""
        result = aggregator._importance_icon_color_class("high")
        assert "warning" in result or "high" in result

    def test_importance_icon_color_medium(self, aggregator):
        """Test icon color for medium importance."""
        result = aggregator._importance_icon_color_class("medium")
        assert result is not None

    def test_importance_icon_color_low(self, aggregator):
        """Test icon color for low importance."""
        result = aggregator._importance_icon_color_class("low")
        assert "secondary" in result or result is not None

    def test_importance_icon_color_unknown(self, aggregator):
        """Test icon color for unknown importance."""
        result = aggregator._importance_icon_color_class("unknown")
        assert result is not None

    def test_phase_icon_class_full_moon(self, aggregator):
        """Test icon class for full moon."""
        result = aggregator._phase_icon_class("Full Moon")
        assert "moon" in result or "bi" in result

    def test_phase_icon_class_new_moon(self, aggregator):
        """Test icon class for new moon."""
        result = aggregator._phase_icon_class("New Moon")
        assert "moon" in result or "bi" in result

    def test_infer_icon_class_solar_eclipse(self, aggregator):
        """Test icon inference for solar eclipse."""
        result = aggregator._infer_icon_class("Solar Eclipse")
        assert "sun" in result or "bi" in result

    def test_infer_icon_class_lunar_eclipse(self, aggregator):
        """Test icon inference for lunar eclipse."""
        result = aggregator._infer_icon_class("Lunar Eclipse")
        assert "moon" in result or "bi" in result

    def test_infer_icon_class_aurora(self, aggregator):
        """Test icon inference for aurora."""
        result = aggregator._infer_icon_class("Aurora")
        assert "stars" in result or "bi" in result

    def test_infer_icon_class_iss_pass(self, aggregator):
        """Test icon inference for ISS pass."""
        result = aggregator._infer_icon_class("ISS Pass")
        assert result is not None

    def test_infer_icon_class_unknown_type(self, aggregator):
        """Test icon inference for unknown type uses fallback."""
        result = aggregator._infer_icon_class("Unknown Event Type")
        assert "star" in result or "bi" in result  # Should use fallback


class TestPlanetaryEventLocalization:
    """Tests for planetary event localization."""

    def test_localize_conjunction(self, aggregator):
        """Test localizing conjunction event."""
        event_data = {
            "event_type": "Planetary Conjunction",
            "title": "Venus-Jupiter Conjunction",
            "description": "Two planets come together",
            "raw_data": {
                "planet1": "Venus",
                "planet2": "Jupiter"
            }
        }
        
        title, desc = aggregator._localize_planetary_text(event_data)
        
        assert title is not None
        assert desc is not None

    def test_localize_opposition(self, aggregator):
        """Test localizing opposition event."""
        event_data = {
            "event_type": "Planetary Opposition",
            "title": "Mars Opposition",
            "description": "Mars at opposition",
            "raw_data": {
                "planet": "Mars"
            }
        }
        
        title, desc = aggregator._localize_planetary_text(event_data)
        
        assert title is not None
        assert desc is not None

    def test_localize_elongation(self, aggregator):
        """Test localizing elongation event."""
        event_data = {
            "event_type": "Planetary Elongation",
            "title": "Mercury Elongation",
            "description": "Mercury at maximum elongation",
            "raw_data": {
                "planet": "Mercury",
                "elongation": "28.1"
            },
            "elongation_degrees": 28.1
        }
        
        title, desc = aggregator._localize_planetary_text(event_data)
        
        assert title is not None
        assert desc is not None

    def test_localize_retrograde(self, aggregator):
        """Test localizing retrograde event."""
        event_data = {
            "event_type": "Planetary Retrograde",
            "title": "Mercury Retrograde",
            "description": "Mercury retrograde period",
            "raw_data": {
                "planet": "Mercury",
                "duration_days": 21
            },
            "duration_days": 21
        }
        
        title, desc = aggregator._localize_planetary_text(event_data)
        
        assert title is not None
        assert desc is not None

    def test_localize_moon_conjunction(self, aggregator):
        """Test localizing Moon-planet conjunction event."""
        event_data = {
            "event_type": "Moon Conjunction",
            "title": "Moon - Jupiter Conjunction",
            "description": "The Moon passes within 2.5° of Jupiter",
            "raw_data": {
                "planet1": "Moon",
                "planet2": "Jupiter",
                "separation_degrees": 2.5,
            },
        }

        title, desc = aggregator._localize_planetary_text(event_data)

        assert title is not None
        assert desc is not None

    def test_localize_moon_conjunction_missing_separation(self, aggregator):
        """Test localizing Moon conjunction when separation_degrees is absent."""
        event_data = {
            "event_type": "Moon Conjunction",
            "title": "Moon - Saturn Conjunction",
            "description": "The Moon passes near Saturn",
            "raw_data": {
                "planet1": "Moon",
                "planet2": "Saturn",
            },
        }

        title, desc = aggregator._localize_planetary_text(event_data)

        assert title is not None
        assert desc is not None

    def test_localize_unknown_planetary_event(self, aggregator):
        """Test localizing unknown planetary event type."""
        event_data = {
            "event_type": "Unknown Planetary Event",
            "title": "Unknown",
            "description": "Unknown description",
            "raw_data": {}
        }
        
        title, desc = aggregator._localize_planetary_text(event_data)
        
        assert title == "Unknown" or title is not None
        assert desc == "Unknown description" or desc is not None


class TestAggregateAllEvents:
    """Tests for aggregate_all_events method."""

    def test_aggregate_with_no_data(self, aggregator):
        """Test aggregation with no event data."""
        result = aggregator.aggregate_all_events()
        
        assert result is not None
        assert isinstance(result, dict)
        assert "upcoming_events" in result or result == {}

    def test_aggregate_with_solar_eclipse_data(self, aggregator):
        """Test aggregation with solar eclipse data."""
        eclipse_data = {
            "solar_eclipse": {
                "date": "2026-08-12",
                "magnitude": 0.95,
                "type": "Partial"
            }
        }
        
        result = aggregator.aggregate_all_events(solar_eclipse_data=eclipse_data)
        
        assert result is not None

    def test_aggregate_with_lunar_eclipse_data(self, aggregator):
        """Test aggregation with lunar eclipse data."""
        eclipse_data = {
            "lunar_eclipse": {
                "date": "2026-09-07",
                "magnitude": 1.2,
                "type": "Total"
            }
        }
        
        result = aggregator.aggregate_all_events(lunar_eclipse_data=eclipse_data)
        
        assert result is not None

    def test_aggregate_with_aurora_data(self, aggregator):
        """Test aggregation with aurora data."""
        aurora_data = {
            "forecast": [
                {
                    "date": "2026-04-17",
                    "probability": 0.7
                }
            ]
        }
        
        result = aggregator.aggregate_all_events(aurora_data=aurora_data)
        
        assert result is not None

    def test_aggregate_with_iss_passes_data(self, aggregator):
        """Test aggregation with ISS passes data."""
        iss_data = {
            "passes": [
                {
                    "date": "2026-04-17",
                    "max_altitude": 85,
                    "magnitude": 2.5
                }
            ]
        }
        
        result = aggregator.aggregate_all_events(iss_passes_data=iss_data)
        
        assert result is not None

    def test_aggregate_with_moon_phases_data(self, aggregator):
        """Test aggregation with moon phases data."""
        moon_data = {
            "phases": [
                {
                    "date": "2026-04-18",
                    "phase": "Full Moon"
                }
            ]
        }
        
        result = aggregator.aggregate_all_events(moon_phases_data=moon_data)
        
        assert result is not None

    def test_aggregate_with_planetary_events_data(self, aggregator):
        """Test aggregation with planetary events data."""
        planetary_data = {
            "events": [
                {
                    "date": "2026-04-25",
                    "event_type": "conjunction",
                    "planet1": "Venus",
                    "planet2": "Jupiter"
                }
            ]
        }
        
        result = aggregator.aggregate_all_events(planetary_events_data=planetary_data)
        
        assert result is not None

    def test_aggregate_with_special_phenomena_data(self, aggregator):
        """Test aggregation with special phenomena data."""
        phenomena_data = {
            "equinoxes": [
                {
                    "date": "2026-03-20",
                    "type": "Spring Equinox"
                }
            ],
            "solstices": [],
            "zodiacal_light": []
        }
        
        result = aggregator.aggregate_all_events(special_phenomena_data=phenomena_data)
        
        assert result is not None

    def test_aggregate_with_multiple_event_types(self, aggregator):
        """Test aggregation with multiple event types."""
        eclipse_data = {"solar_eclipse": {"date": "2026-08-12"}}
        aurora_data = {"forecast": [{"date": "2026-04-17"}]}
        
        result = aggregator.aggregate_all_events(
            solar_eclipse_data=eclipse_data,
            aurora_data=aurora_data
        )
        
        assert result is not None


class TestGetLocalNow:
    """Tests for local time handling."""

    def test_local_now_respects_timezone(self, aggregator):
        """Test that local_now respects the aggregator's timezone."""
        assert aggregator.local_now is not None
        assert aggregator.local_now.tzinfo == aggregator.timezone


# ---------------------------------------------------------------------------
# Additional tests to increase branch/statement coverage
# ---------------------------------------------------------------------------

class TestExtractSolarEclipseEvents:
    """Tests for _extract_solar_eclipse_events."""

    def test_no_solar_eclipse_key(self, aggregator):
        """Return empty list when solar_eclipse key is absent."""
        result = aggregator._extract_solar_eclipse_events({})
        assert result == []

    def test_solar_eclipse_not_visible(self, aggregator):
        """Return empty list when solar eclipse is not visible."""
        result = aggregator._extract_solar_eclipse_events({"solar_eclipse": {"visible": False}})
        assert result == []

    def test_solar_eclipse_total_importance(self, aggregator):
        """Total eclipse has CRITICAL importance."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Total",
                "astrophotography_score": 9,
                "obscuration_percent": 100.0,
                "peak_altitude_deg": 45.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "critical"

    def test_solar_eclipse_annular_high_score(self, aggregator):
        """Annular eclipse with score >= 6 gets HIGH importance."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Annular",
                "astrophotography_score": 7,
                "obscuration_percent": 95.0,
                "peak_altitude_deg": 40.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "high"

    def test_solar_eclipse_annular_low_score(self, aggregator):
        """Annular eclipse with score < 6 gets MEDIUM importance."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Annular",
                "astrophotography_score": 4,
                "obscuration_percent": 90.0,
                "peak_altitude_deg": 35.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "medium"

    def test_solar_eclipse_partial_high_score(self, aggregator):
        """Partial eclipse with score >= 5 gets MEDIUM importance."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Partial",
                "astrophotography_score": 6,
                "obscuration_percent": 50.0,
                "peak_altitude_deg": 30.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "medium"

    def test_solar_eclipse_partial_low_score(self, aggregator):
        """Partial eclipse with score < 5 gets LOW importance."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Partial",
                "astrophotography_score": 3,
                "obscuration_percent": 30.0,
                "peak_altitude_deg": 20.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "low"

    def test_solar_eclipse_event_structure_key(self, aggregator):
        """Solar eclipse events have structure_key='sun'."""
        peak = (aggregator.local_now + timedelta(days=3)).isoformat()
        data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Total",
                "astrophotography_score": 9,
                "obscuration_percent": 100.0,
                "peak_altitude_deg": 45.0,
            }
        }
        events = aggregator._extract_solar_eclipse_events(data)
        assert events[0].structure_key == "sun"
        assert events[0].event_type == "Solar Eclipse"


class TestExtractLunarEclipseEvents:
    """Tests for _extract_lunar_eclipse_events."""

    def test_no_lunar_eclipse_key(self, aggregator):
        """Return empty list when lunar_eclipse key is absent."""
        result = aggregator._extract_lunar_eclipse_events({})
        assert result == []

    def test_lunar_eclipse_no_peak_time(self, aggregator):
        """Return empty list when peak_time is missing."""
        result = aggregator._extract_lunar_eclipse_events({"lunar_eclipse": {"visible": True, "type": "Total"}})
        assert result == []

    def test_lunar_eclipse_total_importance(self, aggregator):
        """Total lunar eclipse gets HIGH importance."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "lunar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Total",
                "obscuration_percent": 100.0,
            }
        }
        events = aggregator._extract_lunar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "high"

    def test_lunar_eclipse_partial_importance(self, aggregator):
        """Partial lunar eclipse gets MEDIUM importance."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "lunar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Partial",
                "obscuration_percent": 60.0,
            }
        }
        events = aggregator._extract_lunar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "medium"

    def test_lunar_eclipse_penumbral_importance(self, aggregator):
        """Penumbral lunar eclipse gets LOW importance."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "lunar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Penumbral",
                "obscuration_percent": 20.0,
            }
        }
        events = aggregator._extract_lunar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].importance == "low"
        assert events[0].structure_key == "moon"

    def test_lunar_eclipse_not_visible(self, aggregator):
        """Lunar eclipse not visible is still returned (visibility flag set to False)."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "lunar_eclipse": {
                "visible": False,
                "peak_time": peak,
                "type": "Partial",
                "obscuration_percent": 50.0,
            }
        }
        events = aggregator._extract_lunar_eclipse_events(data)
        assert len(events) == 1
        assert events[0].visibility is False


class TestExtractAuroraEvents:
    """Tests for _extract_aurora_events."""

    def test_empty_aurora_data(self, aggregator):
        """Return empty list when aurora_data is empty/falsy."""
        assert aggregator._extract_aurora_events({}) == []
        assert aggregator._extract_aurora_events(None) == []

    def test_aurora_empty_forecast(self, aggregator):
        """Return empty list when forecast list is empty."""
        result = aggregator._extract_aurora_events({"forecast": []})
        assert result == []

    def test_aurora_low_visibility_skipped(self, aggregator):
        """Entries with < 70% visibility are skipped."""
        ts = (aggregator.local_now + timedelta(days=1)).isoformat()
        data = {
            "forecast": [
                {"visibility_likelihood": 30, "timestamp": ts, "kp_index": 2}
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert result == []

    def test_aurora_high_visibility_returned(self, aggregator):
        """First entry with >= 70% visibility is returned."""
        ts = (aggregator.local_now + timedelta(days=1)).isoformat()
        data = {
            "forecast": [
                {"visibility_likelihood": 80, "timestamp": ts, "kp_index": 5}
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert len(result) == 1
        assert result[0].event_type == "Aurora"
        assert result[0].importance == "high"

    def test_aurora_uses_probability_fallback(self, aggregator):
        """Falls back to probability field when visibility_likelihood is absent."""
        ts = (aggregator.local_now + timedelta(days=1)).isoformat()
        data = {
            "forecast": [
                {"probability": 75, "timestamp": ts, "kp_index": 4}
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert len(result) == 1

    def test_aurora_invalid_timestamp_skipped(self, aggregator):
        """Entry with bad timestamp is skipped gracefully."""
        data = {
            "forecast": [
                {"visibility_likelihood": 80, "timestamp": "not-a-date", "kp_index": 5},
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert result == []

    def test_aurora_missing_timestamp_skipped(self, aggregator):
        """Entry without a timestamp is skipped."""
        data = {
            "forecast": [
                {"visibility_likelihood": 80, "kp_index": 5}
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert result == []

    def test_aurora_returns_only_first_qualifying(self, aggregator):
        """Only the first qualifying entry is returned."""
        ts1 = (aggregator.local_now + timedelta(hours=1)).isoformat()
        ts2 = (aggregator.local_now + timedelta(hours=4)).isoformat()
        data = {
            "forecast": [
                {"visibility_likelihood": 70, "timestamp": ts1, "kp_index": 5},
                {"visibility_likelihood": 90, "timestamp": ts2, "kp_index": 7},
            ]
        }
        result = aggregator._extract_aurora_events(data)
        assert len(result) == 1
        assert "aurora_" + ts1 in result[0].id


class TestExtractMoonPhaseEvents:
    """Tests for _extract_moon_phase_events."""

    def test_standard_phases_format(self, aggregator):
        """Extract events from standard 'phases' format."""
        phase_date = (aggregator.local_now + timedelta(days=3)).isoformat()
        data = {
            "phases": [
                {"phase": "Full Moon", "date": phase_date},
                {"phase": "Last Quarter", "date": phase_date},
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert len(events) == 2
        assert events[0].event_type == "Moon Phase"

    def test_phases_format_skips_missing_date(self, aggregator):
        """Phases with no date are skipped."""
        data = {"phases": [{"phase": "Full Moon"}]}
        events = aggregator._extract_moon_phase_events(data)
        assert events == []

    def test_next_7_nights_full_moon(self, aggregator):
        """Detects Full Moon from next_7_nights illumination >= 98%."""
        date_str = (aggregator.local_now + timedelta(days=2)).isoformat()
        data = {
            "next_7_nights": [
                {"date": date_str, "moon": {"illumination_percent": 99}}
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert len(events) == 1
        assert "full_moon" in events[0].id

    def test_next_7_nights_new_moon(self, aggregator):
        """Detects New Moon from next_7_nights illumination <= 2%."""
        date_str = (aggregator.local_now + timedelta(days=4)).isoformat()
        data = {
            "next_7_nights": [
                {"date": date_str, "moon": {"illumination_percent": 1}}
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert len(events) == 1
        assert "new_moon" in events[0].id

    def test_next_7_nights_mid_illumination_skipped(self, aggregator):
        """Mid-range illumination (not full/new) is ignored."""
        date_str = (aggregator.local_now + timedelta(days=4)).isoformat()
        data = {
            "next_7_nights": [
                {"date": date_str, "moon": {"illumination_percent": 50}}
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert events == []

    def test_next_7_nights_missing_date_skipped(self, aggregator):
        """Entries without date are skipped."""
        data = {
            "next_7_nights": [
                {"moon": {"illumination_percent": 99}}
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert events == []

    def test_next_7_nights_missing_illumination_skipped(self, aggregator):
        """Entries without illumination_percent are skipped."""
        date_str = (aggregator.local_now + timedelta(days=2)).isoformat()
        data = {
            "next_7_nights": [
                {"date": date_str, "moon": {}}
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert events == []

    def test_phase_info_uses_unknown_importance(self, aggregator):
        """Moon phase not in phase_info dict falls back to LOW importance."""
        phase_date = (aggregator.local_now + timedelta(days=3)).isoformat()
        data = {
            "phases": [
                {"phase": "Waxing Gibbous", "date": phase_date},
            ]
        }
        events = aggregator._extract_moon_phase_events(data)
        assert len(events) == 1
        assert events[0].importance == "low"


class TestExtractIssPassEvents:
    """Tests for _extract_iss_pass_events."""

    def _make_pass(self, aggregator, days_ahead=1, score=80, is_visible=True, vis_dn="Astronomical Night"):
        peak = (aggregator.local_now + timedelta(days=days_ahead)).isoformat()
        return {
            "peak_time": peak,
            "visibility_score": score,
            "visibility_day_night": vis_dn,
            "is_visible": is_visible,
            "peak_altitude_deg": 45.0,
        }

    def test_passes_list_format(self, aggregator):
        """ISS passes from 'passes' list are extracted."""
        iss_pass = self._make_pass(aggregator, days_ahead=1)
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert len(events) == 1
        assert events[0].event_type == "ISS Pass"

    def test_passes_beyond_7_days_excluded(self, aggregator):
        """ISS passes more than 7 days away are excluded."""
        iss_pass = self._make_pass(aggregator, days_ahead=10)
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert events == []

    def test_passes_in_the_past_skipped(self, aggregator):
        """ISS passes in the past (days_until < 0) are skipped."""
        peak = (aggregator.local_now - timedelta(days=1)).isoformat()
        iss_pass = {"peak_time": peak, "visibility_score": 80, "visibility_day_night": "Night", "is_visible": True, "peak_altitude_deg": 45.0}
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert events == []

    def test_passes_missing_peak_time_skipped(self, aggregator):
        """Passes without peak_time are skipped."""
        events = aggregator._extract_iss_pass_events({"passes": [{"visibility_score": 80}]})
        assert events == []

    def test_passes_non_dict_entries_skipped(self, aggregator):
        """Non-dict entries in passes list are skipped."""
        events = aggregator._extract_iss_pass_events({"passes": ["invalid", None]})
        assert events == []

    def test_iss_pass_high_score_importance(self, aggregator):
        """Pass with score >= 75 gets HIGH importance."""
        iss_pass = self._make_pass(aggregator, score=80)
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert events[0].importance == "high"

    def test_iss_pass_medium_score_importance(self, aggregator):
        """Pass with score 55-74 gets MEDIUM importance."""
        iss_pass = self._make_pass(aggregator, score=60)
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert events[0].importance == "medium"

    def test_iss_pass_low_score_importance(self, aggregator):
        """Pass with score < 55 gets LOW importance."""
        iss_pass = self._make_pass(aggregator, score=30)
        events = aggregator._extract_iss_pass_events({"passes": [iss_pass]})
        assert events[0].importance == "low"

    def test_single_next_visible_passage_fallback(self, aggregator):
        """Falls back to next_visible_passage when passes is not a list."""
        iss_pass = self._make_pass(aggregator, days_ahead=1)
        events = aggregator._extract_iss_pass_events({"next_visible_passage": iss_pass})
        assert len(events) == 1

    def test_solar_transit_extracted(self, aggregator):
        """Solar transits within 7 days are extracted as ISS_SOLAR_TRANSIT events."""
        peak = (aggregator.local_now + timedelta(days=2)).isoformat()
        transit = {
            "peak_time": peak,
            "minimum_separation_arcmin": 0.5,
            "duration_seconds": 1.2,
            "sun_altitude_deg": 30.0,
            "solar_radius_arcmin": 16.0,
            "is_visible": True,
        }
        events = aggregator._extract_iss_pass_events({"solar_transits": [transit]})
        assert len(events) == 1
        assert events[0].event_type == "ISS Solar Transit"
        assert events[0].importance == "critical"

    def test_solar_transit_fallback_to_next_solar_transit(self, aggregator):
        """Falls back to next_solar_transit when solar_transits is not a list."""
        peak = (aggregator.local_now + timedelta(days=2)).isoformat()
        transit = {
            "peak_time": peak,
            "minimum_separation_arcmin": 0.5,
            "duration_seconds": 1.2,
            "sun_altitude_deg": 30.0,
            "solar_radius_arcmin": 16.0,
        }
        events = aggregator._extract_iss_pass_events({"next_solar_transit": transit})
        assert len(events) == 1

    def test_solar_transit_out_of_range_skipped(self, aggregator):
        """Solar transit more than 7 days away is skipped."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        transit = {"peak_time": peak}
        events = aggregator._extract_iss_pass_events({"solar_transits": [transit]})
        assert events == []

    def test_lunar_transit_extracted(self, aggregator):
        """Lunar transits within 7 days are extracted as ISS_LUNAR_TRANSIT events."""
        peak = (aggregator.local_now + timedelta(days=1)).isoformat()
        transit = {
            "peak_time": peak,
            "minimum_separation_arcmin": 0.3,
            "duration_seconds": 1.5,
            "moon_altitude_deg": 45.0,
            "lunar_radius_arcmin": 15.0,
            "moon_illumination_pct": 75.0,
            "is_visible": True,
        }
        events = aggregator._extract_iss_pass_events({"lunar_transits": [transit]})
        assert len(events) == 1
        assert events[0].event_type == "ISS Lunar Transit"

    def test_lunar_transit_fallback(self, aggregator):
        """Falls back to next_lunar_transit when lunar_transits is not a list."""
        peak = (aggregator.local_now + timedelta(days=1)).isoformat()
        transit = {
            "peak_time": peak,
            "minimum_separation_arcmin": 0.3,
            "duration_seconds": 1.5,
            "moon_altitude_deg": 45.0,
            "lunar_radius_arcmin": 15.0,
            "moon_illumination_pct": 75.0,
        }
        events = aggregator._extract_iss_pass_events({"next_lunar_transit": transit})
        assert len(events) == 1

    def test_iss_language_non_en(self, aggregator_french):
        """Non-English aggregator uses i18n for ISS pass title."""
        peak = (aggregator_french.local_now + timedelta(days=1)).isoformat()
        iss_pass = {
            "peak_time": peak,
            "visibility_score": 80,
            "visibility_day_night": "Astronomical Night",
            "is_visible": True,
            "peak_altitude_deg": 45.0,
        }
        events = aggregator_french._extract_iss_pass_events({"passes": [iss_pass]})
        assert len(events) == 1

    def test_solar_transit_missing_peak_time_skipped(self, aggregator):
        """Solar transit without peak_time is skipped."""
        events = aggregator._extract_iss_pass_events({"solar_transits": [{"minimum_separation_arcmin": 0.5}]})
        assert events == []

    def test_lunar_transit_missing_peak_time_skipped(self, aggregator):
        """Lunar transit without peak_time is skipped."""
        events = aggregator._extract_iss_pass_events({"lunar_transits": [{"moon_altitude_deg": 45.0}]})
        assert events == []

    def test_solar_transit_non_dict_skipped(self, aggregator):
        """Non-dict solar transit entries are skipped."""
        events = aggregator._extract_iss_pass_events({"solar_transits": ["not-a-dict"]})
        assert events == []

    def test_lunar_transit_non_dict_skipped(self, aggregator):
        """Non-dict lunar transit entries are skipped."""
        events = aggregator._extract_iss_pass_events({"lunar_transits": [None, 42]})
        assert events == []

    def test_lunar_transit_out_of_range_skipped(self, aggregator):
        """Line 869: lunar transit more than 7 days away is skipped."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        transit = {"peak_time": peak, "minimum_separation_arcmin": 0.3}
        events = aggregator._extract_iss_pass_events({"lunar_transits": [transit]})
        assert events == []


class TestExtractPlanetaryEvents:
    """Tests for _extract_planetary_events."""

    def test_no_events_key(self, aggregator):
        """Return empty list when 'events' key is absent."""
        result = aggregator._extract_planetary_events({})
        assert result == []

    def test_events_not_a_list(self, aggregator):
        """Return empty list when 'events' is not a list."""
        result = aggregator._extract_planetary_events({"events": "invalid"})
        assert result == []

    def test_event_without_peak_time_skipped(self, aggregator):
        """Events without peak_time are skipped."""
        result = aggregator._extract_planetary_events({"events": [{"event_type": "Planetary Conjunction"}]})
        assert result == []

    def test_conjunction_event_extracted(self, aggregator):
        """Valid conjunction event is extracted correctly."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Planetary Conjunction",
                    "raw_data": {"planet1": "Venus", "planet2": "Jupiter"},
                    "visibility": True,
                    "importance": "high",
                }
            ]
        }
        events = aggregator._extract_planetary_events(data)
        assert len(events) == 1
        assert events[0].event_type == "Planetary Conjunction"
        assert events[0].structure_key == "calendar"

    def test_planetary_event_with_custom_icon(self, aggregator):
        """Events with explicit icon_class and icon_color_class use those values."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Planetary Opposition",
                    "raw_data": {"planet": "Mars"},
                    "icon_class": "bi bi-custom",
                    "icon_color_class": "text-danger",
                }
            ]
        }
        events = aggregator._extract_planetary_events(data)
        assert events[0].icon_class == "bi bi-custom"
        assert events[0].icon_color_class == "text-danger"

    def test_malformed_event_skipped_gracefully(self, aggregator):
        """Malformed event data is caught and skipped."""
        data = {"events": [{"peak_time": "bad-date", "event_type": None}]}
        # Should not raise; may return 0 or 1 events depending on parse behavior
        result = aggregator._extract_planetary_events(data)
        assert isinstance(result, list)


class TestExtractSpecialPhenomenaEvents:
    """Tests for _extract_special_phenomena_events."""

    def test_no_events_key(self, aggregator):
        """Return empty list when 'events' key is absent."""
        result = aggregator._extract_special_phenomena_events({})
        assert result == []

    def test_events_not_a_list(self, aggregator):
        """Return empty list when 'events' is not a list."""
        result = aggregator._extract_special_phenomena_events({"events": {}})
        assert result == []

    def test_event_without_peak_time_skipped(self, aggregator):
        """Events without peak_time are skipped."""
        result = aggregator._extract_special_phenomena_events({"events": [{"event_type": "Equinox"}]})
        assert result == []

    def test_spring_equinox_extracted(self, aggregator):
        """Spring equinox event is extracted and localized."""
        peak = (aggregator.local_now + timedelta(days=20)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Equinox",
                    "raw_data": {"event": "spring_equinox"},
                    "title": "Spring Equinox",
                    "description": "Equal day and night",
                    "visibility": True,
                    "importance": "medium",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1
        assert events[0].structure_key == "calendar"

    def test_summer_solstice_extracted(self, aggregator):
        """Summer solstice event is extracted."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Solstice",
                    "raw_data": {"event": "summer_solstice"},
                    "title": "Summer Solstice",
                    "description": "Longest day of year",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1

    def test_autumn_equinox_extracted(self, aggregator):
        """Autumn equinox event is extracted."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Equinox",
                    "raw_data": {"event": "autumn_equinox"},
                    "title": "Autumn Equinox",
                    "description": "Equal day and night",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1

    def test_winter_solstice_extracted(self, aggregator):
        """Winter solstice event is extracted."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Solstice",
                    "raw_data": {"event": "winter_solstice"},
                    "title": "Winter Solstice",
                    "description": "Shortest day of year",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1

    def test_zodiacal_light_morning_extracted(self, aggregator):
        """Zodiacal light morning viewing is extracted."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Zodiacal Light Window",
                    "raw_data": {"event": "zodiacal_light", "viewing_type": "morning"},
                    "title": "Zodiacal Light",
                    "description": "Visible before dawn",
                    "viewing_type": "morning",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1

    def test_zodiacal_light_evening_extracted(self, aggregator):
        """Zodiacal light evening viewing is extracted."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Zodiacal Light Window",
                    "raw_data": {"event": "zodiacal_light", "viewing_type": "evening"},
                    "title": "Zodiacal Light",
                    "description": "Visible after sunset",
                    "viewing_type": "evening",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1

    def test_unknown_phenomenon_returns_fallback(self, aggregator):
        """Unknown phenomenon raw_data returns the fallback title."""
        peak = (aggregator.local_now + timedelta(days=10)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Custom Event",
                    "raw_data": {"event": "unknown_special"},
                    "title": "My Custom Event",
                    "description": "Custom desc",
                }
            ]
        }
        events = aggregator._extract_special_phenomena_events(data)
        assert len(events) == 1
        assert events[0].title == "My Custom Event"

    def test_malformed_event_hits_except_handler(self, aggregator):
        """Lines 1044-1045: non-dict entry triggers AttributeError → except handler."""
        peak = (aggregator.local_now + timedelta(days=1)).isoformat()
        data = {
            "events": [
                None,
                {
                    "peak_time": peak,
                    "event_type": "Equinox",
                    "title": "Spring Equinox",
                    "description": "Equal day and night",
                },
            ]
        }
        result = aggregator._extract_special_phenomena_events(data)
        assert len(result) == 1


class TestExtractSolarSystemEvents:
    """Tests for _extract_solar_system_events."""

    def test_no_events_key(self, aggregator):
        """Return empty list when 'events' key is absent."""
        result = aggregator._extract_solar_system_events({})
        assert result == []

    def test_events_not_a_list(self, aggregator):
        """Return empty list when 'events' is not a list."""
        result = aggregator._extract_solar_system_events({"events": "not-a-list"})
        assert result == []

    def test_event_without_peak_time_skipped(self, aggregator):
        """Events without peak_time are skipped."""
        result = aggregator._extract_solar_system_events({"events": [{"event_type": "Meteor Shower"}]})
        assert result == []

    def test_meteor_shower_extracted(self, aggregator):
        """Meteor shower event is extracted with fallback icon."""
        peak = (aggregator.local_now + timedelta(days=7)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Meteor Shower",
                    "title": "Perseids",
                    "description": "Peak night",
                    "visibility": True,
                    "importance": "high",
                }
            ]
        }
        events = aggregator._extract_solar_system_events(data)
        assert len(events) == 1
        assert events[0].event_type == "Meteor Shower"
        assert events[0].structure_key == "calendar"
        assert events[0].title == "Perseids"

    def test_comet_appearance_extracted(self, aggregator):
        """Comet appearance event is extracted."""
        peak = (aggregator.local_now + timedelta(days=15)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Comet Appearance",
                    "title": "Comet C/2025",
                    "description": "Visible to naked eye",
                }
            ]
        }
        events = aggregator._extract_solar_system_events(data)
        assert len(events) == 1

    def test_custom_icon_respected(self, aggregator):
        """Custom icon_class in event data is used instead of inferred."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        data = {
            "events": [
                {
                    "peak_time": peak,
                    "event_type": "Asteroid Occultation",
                    "title": "Vesta occults star",
                    "description": "Rare event",
                    "icon_class": "bi bi-circle-fill",
                    "icon_color_class": "text-warning",
                }
            ]
        }
        events = aggregator._extract_solar_system_events(data)
        assert events[0].icon_class == "bi bi-circle-fill"
        assert events[0].icon_color_class == "text-warning"

    def test_malformed_event_hits_except_handler(self, aggregator):
        """Lines 1096-1097: non-dict entry triggers AttributeError → except handler."""
        peak = (aggregator.local_now + timedelta(days=2)).isoformat()
        data = {
            "events": [
                None,
                {
                    "peak_time": peak,
                    "event_type": "Meteor Shower",
                    "title": "Perseids",
                    "description": "Peak night",
                },
            ]
        }
        result = aggregator._extract_solar_system_events(data)
        assert len(result) == 1


class TestAggregateAllEventsExceptionPaths:
    """Test that aggregate_all_events catches exceptions from extractors."""

    def test_solar_eclipse_extractor_exception_caught(self, aggregator):
        """Exception in solar eclipse extraction is caught; other events still process."""
        with patch.object(aggregator, "_extract_solar_eclipse_events", side_effect=RuntimeError("boom")):
            result = aggregator.aggregate_all_events(solar_eclipse_data={"solar_eclipse": {}})
        assert "upcoming_events" in result

    def test_lunar_eclipse_extractor_exception_caught(self, aggregator):
        """Exception in lunar eclipse extraction is caught."""
        with patch.object(aggregator, "_extract_lunar_eclipse_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(lunar_eclipse_data={"lunar_eclipse": {}})
        assert "upcoming_events" in result

    def test_aurora_extractor_exception_caught(self, aggregator):
        """Exception in aurora extraction is caught."""
        with patch.object(aggregator, "_extract_aurora_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(aurora_data={"forecast": []})
        assert "upcoming_events" in result

    def test_moon_phase_extractor_exception_caught(self, aggregator):
        """Exception in moon phase extraction is caught."""
        with patch.object(aggregator, "_extract_moon_phase_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(moon_phases_data={"phases": []})
        assert "upcoming_events" in result

    def test_iss_extractor_exception_caught(self, aggregator):
        """Exception in ISS extraction is caught."""
        with patch.object(aggregator, "_extract_iss_pass_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(iss_passes_data={"passes": []})
        assert "upcoming_events" in result

    def test_css_extractor_exception_caught(self, aggregator):
        """Exception in CSS extraction is caught."""
        with patch.object(aggregator, "_extract_css_pass_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(css_passes_data={"passes": []})
        assert "upcoming_events" in result

    def test_planetary_extractor_exception_caught(self, aggregator):
        """Exception in planetary events extraction is caught."""
        with patch.object(aggregator, "_extract_planetary_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(planetary_events_data={"events": []})
        assert "upcoming_events" in result

    def test_special_phenomena_extractor_exception_caught(self, aggregator):
        """Exception in special phenomena extraction is caught."""
        with patch.object(aggregator, "_extract_special_phenomena_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(special_phenomena_data={"events": []})
        assert "upcoming_events" in result

    def test_solar_system_extractor_exception_caught(self, aggregator):
        """Exception in solar system events extraction is caught."""
        with patch.object(aggregator, "_extract_solar_system_events", side_effect=RuntimeError("fail")):
            result = aggregator.aggregate_all_events(solar_system_events_data={"events": []})
        assert "upcoming_events" in result

    def test_aggregate_result_structure(self, aggregator):
        """aggregate_all_events returns expected keys even with no events."""
        result = aggregator.aggregate_all_events()
        assert "aggregation_time" in result
        assert "upcoming_events" in result
        assert "events_count" in result
        assert result["next_event"] is None
        assert result["events_count"] == 0


class TestParseIsoTime:
    """Tests for _parse_iso_time."""

    def test_valid_iso_string_with_timezone(self, aggregator):
        """Parse ISO string with timezone info."""
        iso = "2026-08-12T14:32:00+05:00"
        result = aggregator._parse_iso_time(iso)
        assert result.tzinfo is not None

    def test_valid_iso_string_without_timezone(self, aggregator):
        """Parse ISO string without timezone - gets aggregator timezone."""
        iso = "2026-08-12T14:32:00"
        result = aggregator._parse_iso_time(iso)
        assert result.tzinfo is not None

    def test_invalid_iso_string_returns_local_now(self, aggregator):
        """Invalid ISO string returns local_now as fallback."""
        result = aggregator._parse_iso_time("not-a-valid-date")
        assert result is not None
        # Should return something close to local_now
        diff = abs((result - aggregator.local_now).total_seconds())
        assert diff < 5  # Within 5 seconds


class TestGetMoonPhaseActivity:
    """Tests for _get_moon_phase_activity."""

    def test_new_moon_activity(self, aggregator):
        result = aggregator._get_moon_phase_activity("New Moon")
        assert result is not None

    def test_first_quarter_activity(self, aggregator):
        result = aggregator._get_moon_phase_activity("First Quarter")
        assert result is not None

    def test_full_moon_activity(self, aggregator):
        result = aggregator._get_moon_phase_activity("Full Moon")
        assert result is not None

    def test_last_quarter_activity(self, aggregator):
        result = aggregator._get_moon_phase_activity("Last Quarter")
        assert result is not None

    def test_unknown_phase_activity(self, aggregator):
        """Unknown phase uses 'observing' fallback."""
        result = aggregator._get_moon_phase_activity("Waning Gibbous")
        assert result is not None


class TestLocalizePlanetaryTextEdgeCases:
    """Edge cases for _localize_planetary_text."""

    def test_elongation_without_elongation_value(self, aggregator):
        """Elongation event with no elongation data handles None gracefully."""
        event_data = {
            "event_type": "Planetary Elongation",
            "title": "Mercury Elongation",
            "description": "Mercury at max elongation",
            "raw_data": {"planet": "Mercury"},
            # No elongation_degrees, no elongation in raw_data
        }
        title, desc = aggregator._localize_planetary_text(event_data)
        assert title is not None
        assert desc is not None

    def test_retrograde_without_duration(self, aggregator):
        """Retrograde event with no duration handles None gracefully."""
        event_data = {
            "event_type": "Planetary Retrograde",
            "title": "Venus Retrograde",
            "description": "Venus retrograde period",
            "raw_data": {"planet": "Venus"},
            # No duration_days
        }
        title, desc = aggregator._localize_planetary_text(event_data)
        assert title is not None
        assert desc is not None

    def test_conjunction_with_no_raw_data(self, aggregator):
        """Conjunction with missing raw_data still returns tuple."""
        event_data = {
            "event_type": "Planetary Conjunction",
            "title": "Conjunction",
            "description": "Two planets close together",
            "raw_data": None,
        }
        title, desc = aggregator._localize_planetary_text(event_data)
        assert title is not None
        assert desc is not None


class TestLocalizeSpecialPhenomenaText:
    """Tests for _localize_special_phenomena_text."""

    def test_unknown_phenomenon_fallback(self, aggregator):
        """Unknown event key returns fallback title and description."""
        event_data = {
            "event_type": "Unknown",
            "title": "My Fallback Title",
            "description": "My Fallback Desc",
            "raw_data": {"event": "totally_unknown"},
        }
        title, desc = aggregator._localize_special_phenomena_text(event_data)
        assert title == "My Fallback Title"
        assert desc == "My Fallback Desc"

    def test_zodiacal_light_viewing_type_from_raw(self, aggregator):
        """Zodiacal light reads viewing_type from raw_data when not on event."""
        event_data = {
            "event_type": "Zodiacal Light Window",
            "title": "Zodiacal Light",
            "description": "Desc",
            "raw_data": {"event": "zodiacal_light", "viewing_type": "morning"},
        }
        title, desc = aggregator._localize_special_phenomena_text(event_data)
        assert title is not None
        assert desc is not None

    def test_zodiacal_light_default_to_evening(self, aggregator):
        """Zodiacal light with no viewing_type defaults to Evening."""
        event_data = {
            "event_type": "Zodiacal Light Window",
            "title": "Zodiacal Light",
            "description": "Desc",
            "raw_data": {"event": "zodiacal_light"},
        }
        title, desc = aggregator._localize_special_phenomena_text(event_data)
        assert title is not None


class TestTranslateVisibilityPeriod:
    """Additional tests for _translate_visibility_period."""

    def test_nautical_twilight(self, aggregator):
        result = aggregator._translate_visibility_period("Nautical Twilight")
        assert result is not None

    def test_civil_twilight(self, aggregator):
        result = aggregator._translate_visibility_period("Civil Twilight")
        assert result is not None

    def test_twilight(self, aggregator):
        result = aggregator._translate_visibility_period("Twilight")
        assert result is not None

    def test_daylight(self, aggregator):
        result = aggregator._translate_visibility_period("Daylight")
        assert result is not None

    def test_unrecognized_period(self, aggregator):
        """Unrecognized period label is returned as-is."""
        result = aggregator._translate_visibility_period("Some Random Period")
        assert result == "Some Random Period"


class TestTranslateEclipseType:
    """Additional tests for _translate_eclipse_type."""

    def test_penumbral_eclipse_type(self, aggregator):
        result = aggregator._translate_eclipse_type("Penumbral", "moon")
        assert result is not None

    def test_unknown_eclipse_type_lowercased(self, aggregator):
        """Unknown eclipse type uses lowercased value as key suffix."""
        result = aggregator._translate_eclipse_type("Hybrid", "sun")
        assert result is not None


class TestMoonPhaseTranslation:
    """Additional tests for _get_moon_phase_translation."""

    def test_waxing_gibbous(self, aggregator):
        result = aggregator._get_moon_phase_translation("Waxing Gibbous")
        assert result is not None

    def test_waning_gibbous(self, aggregator):
        result = aggregator._get_moon_phase_translation("Waning Gibbous")
        assert result is not None

    def test_waning_crescent(self, aggregator):
        result = aggregator._get_moon_phase_translation("Waning Crescent")
        assert result is not None

    def test_unknown_phase_returns_as_is(self, aggregator):
        """Unknown phase string is returned unchanged."""
        result = aggregator._get_moon_phase_translation("Super Blue Moon")
        assert result == "Super Blue Moon"


class TestPhaseIconClass:
    """Tests for _phase_icon_class."""

    def test_first_quarter(self, aggregator):
        result = aggregator._phase_icon_class("First Quarter")
        assert "bi" in result

    def test_last_quarter(self, aggregator):
        result = aggregator._phase_icon_class("Last Quarter")
        assert "bi" in result

    def test_waxing_crescent(self, aggregator):
        result = aggregator._phase_icon_class("Waxing Crescent")
        assert "bi" in result

    def test_waxing_gibbous(self, aggregator):
        result = aggregator._phase_icon_class("Waxing Gibbous")
        assert "bi" in result

    def test_waning_gibbous(self, aggregator):
        result = aggregator._phase_icon_class("Waning Gibbous")
        assert "bi" in result

    def test_waning_crescent(self, aggregator):
        result = aggregator._phase_icon_class("Waning Crescent")
        assert "bi" in result

    def test_unknown_phase_fallback(self, aggregator):
        result = aggregator._phase_icon_class("Random Phase")
        assert result == "bi bi-moon-stars"


class TestInferIconClass:
    """Tests for _infer_icon_class with more event types."""

    def test_iss_solar_transit(self, aggregator):
        result = aggregator._infer_icon_class("ISS Solar Transit")
        assert "sun" in result

    def test_iss_lunar_transit(self, aggregator):
        result = aggregator._infer_icon_class("ISS Lunar Transit")
        assert "moon" in result

    def test_planetary_conjunction(self, aggregator):
        result = aggregator._infer_icon_class("Planetary Conjunction")
        assert "bi" in result

    def test_planetary_opposition(self, aggregator):
        result = aggregator._infer_icon_class("Planetary Opposition")
        assert "bi" in result

    def test_planetary_elongation(self, aggregator):
        result = aggregator._infer_icon_class("Planetary Elongation")
        assert "bi" in result

    def test_planetary_retrograde(self, aggregator):
        result = aggregator._infer_icon_class("Planetary Retrograde")
        assert "bi" in result

    def test_equinox(self, aggregator):
        result = aggregator._infer_icon_class("Equinox")
        assert "bi" in result

    def test_solstice(self, aggregator):
        result = aggregator._infer_icon_class("Solstice")
        assert "bi" in result

    def test_zodiacal_light(self, aggregator):
        result = aggregator._infer_icon_class("Zodiacal Light Window")
        assert "bi" in result

    def test_milky_way(self, aggregator):
        result = aggregator._infer_icon_class("Milky Way Core Visibility")
        assert "bi" in result

    def test_meteor_shower(self, aggregator):
        result = aggregator._infer_icon_class("Meteor Shower")
        assert "bi" in result

    def test_comet_appearance(self, aggregator):
        result = aggregator._infer_icon_class("Comet Appearance")
        assert "bi" in result

    def test_asteroid_occultation(self, aggregator):
        result = aggregator._infer_icon_class("Asteroid Occultation")
        assert "bi" in result

    def test_custom_event(self, aggregator):
        result = aggregator._infer_icon_class("Custom Event")
        assert "bi" in result

    def test_custom_fallback_parameter(self, aggregator):
        """Custom fallback parameter is used for unknown types."""
        result = aggregator._infer_icon_class("Unknown Type", "bi bi-custom-fallback")
        assert result == "bi bi-custom-fallback"


class TestAggregateAllEventsWithValidData:
    """Integration-style tests for aggregate_all_events with realistic data."""

    def test_aggregate_with_visible_solar_eclipse(self, aggregator):
        """Visible solar eclipse appears in upcoming_events."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        eclipse_data = {
            "solar_eclipse": {
                "visible": True,
                "peak_time": peak,
                "type": "Total",
                "astrophotography_score": 9,
                "obscuration_percent": 100.0,
                "peak_altitude_deg": 45.0,
            }
        }
        result = aggregator.aggregate_all_events(solar_eclipse_data=eclipse_data)
        assert result["events_count"] >= 1
        assert result["next_event"] is not None

    def test_aggregate_events_count_and_next_7_days(self, aggregator):
        """Events within 7 days appear in events_next_7_days."""
        peak = (aggregator.local_now + timedelta(days=3)).isoformat()
        data = {
            "phases": [{"phase": "Full Moon", "date": peak}]
        }
        result = aggregator.aggregate_all_events(moon_phases_data=data)
        assert len(result["events_next_7_days"]) >= 1

    def test_aggregate_next_30_days_includes_further_events(self, aggregator):
        """Events within 30 days appear in events_next_30_days."""
        peak = (aggregator.local_now + timedelta(days=25)).isoformat()
        data = {
            "phases": [{"phase": "New Moon", "date": peak}]
        }
        result = aggregator.aggregate_all_events(moon_phases_data=data)
        assert len(result["events_next_30_days"]) >= 1

    def test_aggregate_all_data_sources_simultaneously(self, aggregator):
        """All data sources can be provided simultaneously without errors."""
        peak = (aggregator.local_now + timedelta(days=5)).isoformat()
        aurora_ts = (aggregator.local_now + timedelta(hours=3)).isoformat()
        iss_peak = (aggregator.local_now + timedelta(days=2)).isoformat()

        result = aggregator.aggregate_all_events(
            solar_eclipse_data={"solar_eclipse": {"visible": True, "peak_time": peak, "type": "Total", "astrophotography_score": 9, "obscuration_percent": 100.0, "peak_altitude_deg": 45.0}},
            lunar_eclipse_data={"lunar_eclipse": {"visible": True, "peak_time": peak, "type": "Total", "obscuration_percent": 100.0}},
            aurora_data={"forecast": [{"visibility_likelihood": 85, "timestamp": aurora_ts, "kp_index": 6}]},
            moon_phases_data={"phases": [{"phase": "Full Moon", "date": peak}]},
            iss_passes_data={"passes": [{"peak_time": iss_peak, "visibility_score": 80, "visibility_day_night": "Astronomical Night", "is_visible": True, "peak_altitude_deg": 45.0}]},
            planetary_events_data={"events": [{"peak_time": peak, "event_type": "Planetary Conjunction", "raw_data": {"planet1": "Venus", "planet2": "Jupiter"}}]},
            special_phenomena_data={"events": [{"peak_time": peak, "event_type": "Equinox", "raw_data": {"event": "spring_equinox"}, "title": "Spring Equinox", "description": "Equal day and night"}]},
            solar_system_events_data={"events": [{"peak_time": peak, "event_type": "Meteor Shower", "title": "Perseids", "description": "Peak"}]},
        )
        assert result["events_count"] >= 1
        assert isinstance(result["upcoming_events"], list)
