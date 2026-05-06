"""Regression tests for newly added event services."""

from datetime import datetime, date
from zoneinfo import ZoneInfo

from astropy.time import Time

from app import _translate_special_phenomena_events
from planetary_events import PlanetaryEventsService
from special_phenomena import SpecialPhenomenaService
from sidereal_time import SiderealTimeService


class TestPlanetaryEventsService:
    """Tests for planetary events service regressions."""

    def test_get_planetary_events_uses_valid_astropy_time_inputs(self, monkeypatch):
        service = PlanetaryEventsService(latitude=48.0, longitude=2.0)
        captured = {}

        def fake_find_conjunctions(self, start_date, end_date):
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            return []

        monkeypatch.setattr(PlanetaryEventsService, "_find_conjunctions", fake_find_conjunctions)
        monkeypatch.setattr(PlanetaryEventsService, "_find_oppositions", lambda self, s, e: [])
        monkeypatch.setattr(PlanetaryEventsService, "_find_elongations", lambda self, s, e: [])
        monkeypatch.setattr(PlanetaryEventsService, "_find_retrograde_periods", lambda self, s, e: [])

        events = service.get_planetary_events(days_ahead=30)

        assert isinstance(events, list)
        assert "start_date" in captured
        assert isinstance(captured["start_date"], Time)
        assert isinstance(captured["end_date"], Time)
        assert captured["end_date"].jd > captured["start_date"].jd


class TestSpecialPhenomenaService:
    """Tests for special phenomena service regressions."""

    def test_get_special_phenomena_uses_valid_astropy_time_inputs(self, monkeypatch):
        service = SpecialPhenomenaService(latitude=48.0, longitude=2.0, timezone="Europe/Paris")
        captured = {}

        def fake_find_seasonal_events(self, start_date, end_date):
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            return []

        monkeypatch.setattr(SpecialPhenomenaService, "_find_seasonal_events", fake_find_seasonal_events)
        monkeypatch.setattr(SpecialPhenomenaService, "_find_zodiacal_light_windows", lambda self, s, e: [])
        monkeypatch.setattr(SpecialPhenomenaService, "_find_milky_way_core_visibility", lambda self, s, e: [])

        events = service.get_special_phenomena(days_ahead=30)

        assert isinstance(events, list)
        assert "start_date" in captured
        assert isinstance(captured["start_date"], Time)
        assert isinstance(captured["end_date"], Time)
        assert captured["end_date"].jd > captured["start_date"].jd

    def test_approximate_seasonal_times_do_not_raise_yday_format_errors(self):
        service = SpecialPhenomenaService(latitude=48.0, longitude=2.0, timezone="Europe/Paris")

        spring = service._approximate_equinox(2026, "spring")
        autumn = service._approximate_equinox(2026, "autumn")
        summer = service._approximate_solstice(2026, "summer")
        winter = service._approximate_solstice(2026, "winter")

        assert isinstance(spring, Time)
        assert isinstance(autumn, Time)
        assert isinstance(summer, Time)
        assert isinstance(winter, Time)

    def test_milky_way_event_translation_uses_requested_language(self):
        phenomena_data = {
            "events": [
                {
                    "event_type": "Milky Way Core Visibility",
                    "title": "Milky Way Core Visible",
                    "description": "Galactic center visible at 5° altitude. Excellent night for wide-field astrophotography.",
                    "galactic_center_altitude": 5,
                }
            ]
        }

        translated = _translate_special_phenomena_events(phenomena_data, "fr")
        translated_event = translated["events"][0]

        assert translated_event["title"] == "Voie Lactée visible"
        assert translated_event["description"] == "Centre galactique visible à 5° d'altitude. Excellente nuit pour l'astrophotographie grand champ."


class TestSiderealTimeService:
    """Tests for sidereal time regressions."""

    def test_calculate_sidereal_info_returns_values_with_longitude_context(self):
        service = SiderealTimeService(latitude=48.0, longitude=2.0, timezone="Europe/Paris")
        time_obj = Time(datetime(2026, 3, 2, 12, 0, 0, tzinfo=ZoneInfo("UTC")))

        result = service._calculate_sidereal_info(time_obj)

        assert isinstance(result, dict)
        assert result.get("greenwich_sidereal_time_hours") is not None
        assert result.get("local_sidereal_time_hours") is not None
        assert result.get("observer_longitude_degrees") == 2.0

    def test_get_hourly_sidereal_times_returns_hourly_entries(self):
        service = SiderealTimeService(latitude=48.0, longitude=2.0, timezone="Europe/Paris")

        results = service.get_hourly_sidereal_times(date(2026, 3, 2), num_hours=6)

        assert isinstance(results, list)
        assert len(results) == 6
        for item in results:
            assert "hour" in item
            assert "local_sidereal_time_hms" in item
            assert "greenwich_sidereal_time_hms" in item
