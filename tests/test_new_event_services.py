"""Regression tests for newly added event services."""

from datetime import datetime, date
import time
from zoneinfo import ZoneInfo

import pytest
from astropy.time import Time

from app import app
from app import _translate_special_phenomena_events
from app import cache_store
from auth import user_manager
from planetary_events import PlanetaryEventsService
from special_phenomena import SpecialPhenomenaService
from sidereal_time import SiderealTimeService


@pytest.fixture
def authenticated_client():
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        user = user_manager.get_user_by_username("admin")
        assert user is not None
        with test_client.session_transaction() as session:
            session["user_id"] = user.user_id
            session["username"] = user.username
            session["role"] = user.role
        yield test_client


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

    def test_seasonal_event_translation_uses_requested_language(self):
        phenomena_data = {
            "events": [
                {
                    "event_type": "Solstice",
                    "title": "Summer Solstice",
                    "description": "First day of summer. Longest day of the year in Northern Hemisphere.",
                    "raw_data": {"event": "summer_solstice"},
                }
            ]
        }

        translated = _translate_special_phenomena_events(phenomena_data, "fr")
        translated_event = translated["events"][0]

        assert translated_event["title"] == "Solstice d'été"
        assert translated_event["description"] == "Premier jour de l'été. Jour le plus long de l'année dans l'hémisphère Nord."

    def test_zodiacal_light_translation_uses_requested_language(self):
        phenomena_data = {
            "events": [
                {
                    "event_type": "Zodiacal Light Window",
                    "title": "Zodiacal Light Visible (Evening)",
                    "description": "Faint cone of light from interplanetary dust visible during twilight. Best viewed in dark skies.",
                    "viewing_type": "Evening",
                    "raw_data": {"event": "zodiacal_light"},
                }
            ]
        }

        translated = _translate_special_phenomena_events(phenomena_data, "fr")
        translated_event = translated["events"][0]

        assert translated_event["title"] == "Lumière zodiacale visible (soir)"
        assert translated_event["description"] == "Faible cône lumineux de poussière interplanétaire visible au crépuscule. Observation optimale sous un ciel sombre."
        assert translated_event["viewing_type"] == "soir"

    def test_special_phenomena_api_translates_cached_event_payload(self, authenticated_client, monkeypatch):
        cache_store._special_phenomena_cache["data"] = {
            "events": [
                {
                    "event_type": "Solstice",
                    "title": "Summer Solstice",
                    "description": "First day of summer. Longest day of the year in Northern Hemisphere.",
                    "raw_data": {"event": "summer_solstice"},
                },
                {
                    "event_type": "Zodiacal Light Window",
                    "title": "Zodiacal Light Visible (Evening)",
                    "description": "Faint cone of light from interplanetary dust visible during twilight. Best viewed in dark skies.",
                    "viewing_type": "Evening",
                    "raw_data": {"event": "zodiacal_light"},
                },
            ]
        }
        cache_store._special_phenomena_cache["timestamp"] = time.time()

        monkeypatch.setattr(
            cache_store,
            "is_cache_valid",
            lambda cache_obj, ttl: cache_obj is cache_store._special_phenomena_cache,
        )

        response = authenticated_client.get("/api/events/phenomena?lang=fr")
        assert response.status_code == 200

        payload = response.get_json()
        assert isinstance(payload, dict)
        assert "events" in payload
        assert len(payload["events"]) == 2
        assert payload["events"][0]["title"] == "Solstice d'été"
        assert payload["events"][0]["description"] == "Premier jour de l'été. Jour le plus long de l'année dans l'hémisphère Nord."
        assert payload["events"][1]["title"] == "Lumière zodiacale visible (soir)"
        assert payload["events"][1]["description"] == "Faible cône lumineux de poussière interplanétaire visible au crépuscule. Observation optimale sous un ciel sombre."
        assert payload["events"][1]["viewing_type"] == "soir"


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
