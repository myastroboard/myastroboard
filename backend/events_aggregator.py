"""
Events Aggregator Service for MyAstroBoard

Aggregates upcoming astronomical events (eclipses, auroras, etc.) and provides
unified event information for dashboard alerts and sharing.

Collects events from:
- Solar eclipses
- Lunar eclipses
- Aurora predictions
- Moon phases
- Custom events

Example output:
{
    "upcoming_events": [
        {
            "id": "solar_eclipse_20260812",
            "event_type": "Solar Eclipse",
            "title": "Partial Solar Eclipse",
            "description": "Partial eclipse visible from your location",
            "start_time": "2026-08-12T13:05:00",
            "peak_time": "2026-08-12T14:32:15",
            "end_time": "2026-08-12T15:59:00",
            "days_until_event": 170,
            "visibility": true,
            "importance": "high",
            "score": 6.5,
            "raw_data": {...}
        },
        ...
    ],
    "next_event": {...},
    "events_next_7_days": [...]
}
"""

import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo
from enum import Enum
from logging_config import get_logger
from i18n_utils import I18nManager

logger = get_logger(__name__)


class EventType(Enum):
    """Enum for event types"""

    SOLAR_ECLIPSE = "Solar Eclipse"
    LUNAR_ECLIPSE = "Lunar Eclipse"
    AURORA = "Aurora"
    ISS_PASS = "ISS Pass"
    ISS_SOLAR_TRANSIT = "ISS Solar Transit"
    ISS_LUNAR_TRANSIT = "ISS Lunar Transit"
    CSS_PASS = "CSS Pass"
    CSS_SOLAR_TRANSIT = "CSS Solar Transit"
    CSS_LUNAR_TRANSIT = "CSS Lunar Transit"
    MOON_PHASE = "Moon Phase"
    MOON_CONJUNCTION = "Moon Conjunction"
    PLANETARY_CONJUNCTION = "Planetary Conjunction"
    PLANETARY_OPPOSITION = "Planetary Opposition"
    PLANETARY_ELONGATION = "Planetary Elongation"
    PLANETARY_RETROGRADE = "Planetary Retrograde"
    EQUINOX = "Equinox"
    SOLSTICE = "Solstice"
    ZODIACAL_LIGHT = "Zodiacal Light Window"
    MILKY_WAY = "Milky Way Core Visibility"
    METEOR_SHOWER = "Meteor Shower"
    COMET_APPEARANCE = "Comet Appearance"
    ASTEROID_OCCULTATION = "Asteroid Occultation"
    CUSTOM = "Custom Event"


class EventImportance(Enum):
    """Event importance levels for alerting"""

    CRITICAL = "critical"  # Must-see events
    HIGH = "high"  # Highly recommended
    MEDIUM = "medium"  # Worth considering
    LOW = "low"  # Nice to know


@dataclass
class AstronomicalEvent:
    """Standardized astronomical event data"""

    id: str  # Unique identifier
    event_type: str  # Type of event
    icon_class: str  # Bootstrap icon class (e.g. "bi bi-sun")
    icon_color_class: str  # Optional color class (e.g. "text-warning")
    title: str  # Short title
    description: str  # Description
    start_time: Optional[str]  # Start time (ISO format)
    peak_time: Optional[str]  # Peak/best time (ISO format)
    end_time: Optional[str]  # End time (ISO format)
    days_until_event: int  # Days until event happens
    visibility: bool  # Is event visible from location?
    importance: str  # Importance level
    score: Optional[float]  # Importance score (0-10)
    raw_data: Dict[str, Any]  # Original data for detailed view
    structure_key: str  # Stable frontend section key (moon, sun, ...)


class EventsAggregator:
    """
    Aggregates upcoming astronomical events from various sources.
    Provides unified interface for event queries.
    """

    def __init__(self, latitude: float, longitude: float, timezone: str, language: str = "en"):
        """
        Initialize events aggregator

        Args:
            latitude: Observer latitude
            longitude: Observer longitude
            timezone: IANA timezone string
        """
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = ZoneInfo(timezone)
        self.i18n = I18nManager(language)
        self.local_now = self._get_local_now()

    def _t(self, key: str, fallback: str, **params: Any) -> str:
        """Translate a key with fallback when missing."""
        translated = self.i18n.t(key, **params)
        if translated == key:
            return fallback
        return translated

    def _translate_eclipse_type(self, eclipse_type: str, namespace: str) -> str:
        """Translate eclipse type using i18n keys with English fallback."""
        key_map = {
            "Total": "total",
            "Partial": "partial",
            "Annular": "annular",
            "Penumbral": "penumbral",
        }
        key_suffix = key_map.get(eclipse_type, eclipse_type.lower())
        return self._t(f"{namespace}.eclipse_type.{key_suffix}", eclipse_type)

    def _get_moon_phase_translation(self, phase_type: str) -> str:
        """Translate moon phase label with fallback."""
        key_map = {
            "New Moon": "new_moon",
            "First Quarter": "first_quarter",
            "Full Moon": "full_moon",
            "Last Quarter": "last_quarter",
            "Waxing Crescent": "waxing_crescent",
            "Waxing Gibbous": "waxing_gibbous",
            "Waning Gibbous": "waning_gibbous",
            "Waning Crescent": "waning_crescent",
        }
        phase_key = key_map.get(phase_type)
        if not phase_key:
            return phase_type
        return self._t(f"moon.{phase_key}", phase_type)

    def _translate_planet_name(self, planet_name: str) -> str:
        """Translate planet name where available (fallback to source name)."""
        if not planet_name:
            return planet_name
        return self._t(f"planets.{planet_name.lower()}", planet_name)

    def _translate_visibility_period(self, period_label: str) -> str:
        """Translate ISS day/night classification labels."""
        key_map = {
            "Astronomical Night": "astronomical_night",
            "Nautical Twilight": "nautical_twilight",
            "Civil Twilight": "civil_twilight",
            "Twilight": "twilight",
            "Daylight": "daylight",
            "Unknown": "unknown",
        }
        key_suffix = key_map.get(period_label)
        if not key_suffix:
            return period_label
        return self._t(f"events_api.iss_periods.{key_suffix}", period_label)

    def _importance_icon_color_class(self, importance: str) -> str:
        """Map event importance to a Bootstrap text color class."""
        color_map = {
            EventImportance.CRITICAL.value: "text-must-see",
            EventImportance.HIGH.value: "text-warning",
            EventImportance.MEDIUM.value: "text-info",
            EventImportance.LOW.value: "text-secondary",
        }
        return color_map.get(importance, "text-info")

    def _phase_icon_class(self, phase_type: str) -> str:
        """Map moon phase label to a Bootstrap icon class."""
        phase_map = {
            "New Moon": "bi bi-moon-fill",
            "First Quarter": "bi bi-moon",
            "Full Moon": "bi bi-moon-stars-fill",
            "Last Quarter": "bi bi-moon",
            "Waxing Crescent": "bi bi-moon",
            "Waxing Gibbous": "bi bi-moon-stars",
            "Waning Gibbous": "bi bi-moon-stars",
            "Waning Crescent": "bi bi-moon",
        }
        return phase_map.get(phase_type, "bi bi-moon-stars")

    def _infer_icon_class(self, event_type: str, fallback: str = "bi bi-star-fill") -> str:
        """Infer icon class for externally provided events that do not provide one."""
        mapping = {
            EventType.SOLAR_ECLIPSE.value: "bi bi-sun",
            EventType.LUNAR_ECLIPSE.value: "bi bi-moon-stars",
            EventType.AURORA.value: "bi bi-stars",
            EventType.ISS_PASS.value: "bi bi-iss",
            EventType.ISS_SOLAR_TRANSIT.value: "bi bi-sun",
            EventType.ISS_LUNAR_TRANSIT.value: "bi bi-moon-stars",
            EventType.CSS_PASS.value: "bi bi-iss",
            EventType.CSS_SOLAR_TRANSIT.value: "bi bi-sun",
            EventType.CSS_LUNAR_TRANSIT.value: "bi bi-moon-stars",
            EventType.MOON_PHASE.value: "bi bi-moon-stars",
            EventType.MOON_CONJUNCTION.value: "bi bi-moon-stars",
            EventType.PLANETARY_CONJUNCTION.value: "bi bi-conjonction",
            EventType.PLANETARY_OPPOSITION.value: "bi bi-bullseye",
            EventType.PLANETARY_ELONGATION.value: "bi bi-arrows-angle-expand",
            EventType.PLANETARY_RETROGRADE.value: "bi bi-arrow-counterclockwise",
            EventType.EQUINOX.value: "bi bi-sunrise",
            EventType.SOLSTICE.value: "bi bi-sunset",
            EventType.ZODIACAL_LIGHT.value: "bi bi-stars",
            EventType.MILKY_WAY.value: "bi bi-stars",
            EventType.METEOR_SHOWER.value: "bi bi-comet",
            EventType.COMET_APPEARANCE.value: "bi bi-comet",
            EventType.ASTEROID_OCCULTATION.value: "bi bi-circle",
            EventType.CUSTOM.value: "bi bi-star-fill",
        }
        return mapping.get(event_type, fallback)

    def _localize_planetary_text(self, event_data: Dict[str, Any]) -> tuple[str, str]:
        """Localize planetary event title and description using raw_data."""
        event_type = event_data.get("event_type", "")
        raw = event_data.get("raw_data", {}) or {}
        fallback_title = event_data.get("title", "Planetary Event")
        fallback_description = event_data.get("description", "")

        if event_type == EventType.MOON_CONJUNCTION.value:
            planet = self._translate_planet_name(str(raw.get("planet2", "")))
            sep = raw.get("separation_degrees")
            sep_value = f"{float(sep):.1f}" if sep is not None else ""
            return (
                self._t("events_api.planetary.moon_conjunction_title", fallback_title, planet=planet),
                self._t(
                    "events_api.planetary.moon_conjunction_description",
                    fallback_description,
                    planet=planet,
                    separation_degrees=sep_value,
                ),
            )

        if event_type == EventType.PLANETARY_CONJUNCTION.value:
            planet1 = self._translate_planet_name(str(raw.get("planet1", "")))
            planet2 = self._translate_planet_name(str(raw.get("planet2", "")))
            return (
                self._t("events_api.planetary.conjunction_title", fallback_title, planet1=planet1, planet2=planet2),
                self._t(
                    "events_api.planetary.conjunction_description",
                    fallback_description,
                    planet1=planet1,
                    planet2=planet2,
                ),
            )

        if event_type == EventType.PLANETARY_OPPOSITION.value:
            planet = self._translate_planet_name(str(raw.get("planet", "")))
            return (
                self._t("events_api.planetary.opposition_title", fallback_title, planet=planet),
                self._t("events_api.planetary.opposition_description", fallback_description, planet=planet),
            )

        if event_type == EventType.PLANETARY_ELONGATION.value:
            planet = self._translate_planet_name(str(raw.get("planet", "")))
            elongation = event_data.get("elongation_degrees") or raw.get("elongation")
            elongation_value = f"{float(elongation):.1f}" if elongation is not None else ""
            return (
                self._t("events_api.planetary.elongation_title", fallback_title, planet=planet),
                self._t(
                    "events_api.planetary.elongation_description",
                    fallback_description,
                    planet=planet,
                    elongation_degrees=elongation_value,
                ),
            )

        if event_type == EventType.PLANETARY_RETROGRADE.value:
            planet = self._translate_planet_name(str(raw.get("planet", "")))
            duration_days = event_data.get("duration_days") or raw.get("duration_days")
            duration_value = f"{float(duration_days):.0f}" if duration_days is not None else ""
            return (
                self._t("events_api.planetary.retrograde_title", fallback_title, planet=planet),
                self._t(
                    "events_api.planetary.retrograde_description",
                    fallback_description,
                    planet=planet,
                    duration_days=duration_value,
                ),
            )

        return fallback_title, fallback_description

    def _localize_special_phenomena_text(self, event_data: Dict[str, Any]) -> tuple[str, str]:
        """Localize special phenomena title/description using raw event identifiers."""
        raw = event_data.get("raw_data", {}) or {}
        fallback_title = event_data.get("title", "Special Phenomenon")
        fallback_description = event_data.get("description", "")
        event_key = str(raw.get("event", "")).strip().lower()

        if event_key == "spring_equinox":
            return (
                self._t("events_api.special_phenomena.spring_equinox_title", fallback_title),
                self._t("events_api.special_phenomena.spring_equinox_description", fallback_description),
            )
        if event_key == "summer_solstice":
            return (
                self._t("events_api.special_phenomena.summer_solstice_title", fallback_title),
                self._t("events_api.special_phenomena.summer_solstice_description", fallback_description),
            )
        if event_key == "autumn_equinox":
            return (
                self._t("events_api.special_phenomena.autumn_equinox_title", fallback_title),
                self._t("events_api.special_phenomena.autumn_equinox_description", fallback_description),
            )
        if event_key == "winter_solstice":
            return (
                self._t("events_api.special_phenomena.winter_solstice_title", fallback_title),
                self._t("events_api.special_phenomena.winter_solstice_description", fallback_description),
            )
        if event_key == "zodiacal_light":
            viewing_raw = str(event_data.get("viewing_type") or raw.get("viewing_type") or "").strip().lower()
            viewing_type = (
                self._t(
                    "events_api.special_phenomena.zodiacal_viewing_morning",
                    "Morning",
                )
                if viewing_raw == "morning"
                else self._t(
                    "events_api.special_phenomena.zodiacal_viewing_evening",
                    "Evening",
                )
            )
            return (
                self._t(
                    "events_api.special_phenomena.zodiacal_light_title",
                    fallback_title,
                    viewing_type=viewing_type,
                ),
                self._t("events_api.special_phenomena.zodiacal_light_description", fallback_description),
            )

        return fallback_title, fallback_description

    def aggregate_all_events(
        self,
        solar_eclipse_data: Optional[Dict[str, Any]] = None,
        lunar_eclipse_data: Optional[Dict[str, Any]] = None,
        aurora_data: Optional[Dict[str, Any]] = None,
        iss_passes_data: Optional[Dict[str, Any]] = None,
        css_passes_data: Optional[Dict[str, Any]] = None,
        moon_phases_data: Optional[Dict[str, Any]] = None,
        planetary_events_data: Optional[Dict[str, Any]] = None,
        special_phenomena_data: Optional[Dict[str, Any]] = None,
        solar_system_events_data: Optional[Dict[str, Any]] = None,
        sidereal_time_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate all available events into a unified format.

        Args:
            solar_eclipse_data: Data from sun_eclipse endpoint
            lunar_eclipse_data: Data from moon_eclipse endpoint
            aurora_data: Data from aurora endpoint
            iss_passes_data: Data from ISS passes endpoint
            moon_phases_data: Data from moon phases endpoint
            planetary_events_data: Data from planetary events endpoint
            special_phenomena_data: Data from special phenomena endpoint
            solar_system_events_data: Data from solar system events endpoint
            sidereal_time_data: Data from sidereal time endpoint

        Returns:
            Unified events data with next event and filtered views
        """
        events = []

        # Add solar eclipse if available
        if solar_eclipse_data:
            try:
                solar_eclipse_events = self._extract_solar_eclipse_events(solar_eclipse_data)
                events.extend(solar_eclipse_events)
            except Exception as e:
                logger.warning(f"Error extracting solar eclipse events: {e}")

        # Add lunar eclipse if available
        if lunar_eclipse_data:
            try:
                lunar_eclipse_events = self._extract_lunar_eclipse_events(lunar_eclipse_data)
                events.extend(lunar_eclipse_events)
            except Exception as e:
                logger.warning(f"Error extracting lunar eclipse events: {e}")

        # Add aurora if available
        if aurora_data:
            try:
                aurora_events = self._extract_aurora_events(aurora_data)
                events.extend(aurora_events)
            except Exception as e:
                logger.warning(f"Error extracting aurora events: {e}")

        # Add moon phases if available
        if moon_phases_data:
            try:
                moon_events = self._extract_moon_phase_events(moon_phases_data)
                events.extend(moon_events)
            except Exception as e:
                logger.warning(f"Error extracting moon phase events: {e}")

        # Add ISS pass if available
        if iss_passes_data:
            try:
                iss_events = self._extract_iss_pass_events(iss_passes_data)
                events.extend(iss_events)
            except Exception as e:
                logger.warning(f"Error extracting ISS pass events: {e}")

        # Add CSS pass if available
        if css_passes_data:
            try:
                css_events = self._extract_css_pass_events(css_passes_data)
                events.extend(css_events)
            except Exception as e:
                logger.warning(f"Error extracting CSS pass events: {e}")

        # Add planetary events if available
        if planetary_events_data:
            try:
                planetary_events = self._extract_planetary_events(planetary_events_data)
                events.extend(planetary_events)
            except Exception as e:
                logger.warning(f"Error extracting planetary events: {e}")

        # Add special phenomena if available
        if special_phenomena_data:
            try:
                phenomena_events = self._extract_special_phenomena_events(special_phenomena_data)
                events.extend(phenomena_events)
            except Exception as e:
                logger.warning(f"Error extracting special phenomena events: {e}")

        # Add solar system events if available
        if solar_system_events_data:
            try:
                solsys_events = self._extract_solar_system_events(solar_system_events_data)
                events.extend(solsys_events)
            except Exception as e:
                logger.warning(f"Error extracting solar system events: {e}")

        # Sort by days until event
        events.sort(key=lambda x: x.days_until_event)

        # Prepare results
        result = {
            "aggregation_time": self.local_now.isoformat(),
            "upcoming_events": [asdict(e) for e in events],
            "events_count": len(events),
            "next_event": asdict(events[0]) if events else None,
            "events_next_7_days": [asdict(e) for e in events if e.days_until_event <= 7],
            "events_next_30_days": [asdict(e) for e in events if e.days_until_event <= 30],
        }

        return result

    def _extract_solar_eclipse_events(self, eclipse_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract solar eclipse event(s) from raw eclipse data"""
        events = []

        solar_eclipse = eclipse_data.get("solar_eclipse")
        if not solar_eclipse:
            return events

        # Only create event if eclipse is visible
        if not solar_eclipse.get("visible", False):
            return events

        peak_time_str = solar_eclipse.get("peak_time")
        peak_time = self._parse_iso_time(peak_time_str)
        days_until = (peak_time.date() - self.local_now.date()).days

        # Determine importance based on type and score
        eclipse_type = solar_eclipse.get("type", "Partial")
        score = solar_eclipse.get("astrophotography_score", 0)

        if eclipse_type == "Total":
            importance = EventImportance.CRITICAL.value
        elif eclipse_type == "Annular":
            importance = EventImportance.HIGH.value if score >= 6 else EventImportance.MEDIUM.value
        else:
            importance = EventImportance.MEDIUM.value if score >= 5 else EventImportance.LOW.value

        event = AstronomicalEvent(
            id=f"solar_eclipse_{peak_time_str.split('T')[0]}",
            event_type=EventType.SOLAR_ECLIPSE.value,
            icon_class="bi bi-sun",
            icon_color_class=self._importance_icon_color_class(importance),
            title=(
                f"{self._translate_eclipse_type(eclipse_type, 'sun')} "
                f"{self._t('sun.solar_eclipse', 'Solar Eclipse')}"
            ),
            description=(
                self._t(
                    "events_api.solar_eclipse_description",
                    f"{eclipse_type} eclipse with {solar_eclipse.get('obscuration_percent', 0):.1f}% "
                    f"obscuration. Peak at {solar_eclipse.get('peak_altitude_deg', 0):.1f}° altitude.",
                    eclipse_type=self._translate_eclipse_type(eclipse_type, "sun"),
                    obscuration_percent=f"{solar_eclipse.get('obscuration_percent', 0):.1f}",
                    peak_altitude_deg=f"{solar_eclipse.get('peak_altitude_deg', 0):.1f}",
                )
            ),
            start_time=solar_eclipse.get("start_time"),
            peak_time=peak_time_str,
            end_time=solar_eclipse.get("end_time"),
            days_until_event=days_until,
            visibility=True,
            importance=importance,
            score=score,
            raw_data=eclipse_data,
            structure_key="sun",
        )
        events.append(event)
        return events

    def _extract_lunar_eclipse_events(self, eclipse_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract lunar eclipse event(s) from raw eclipse data"""
        events = []

        lunar_eclipse = eclipse_data.get("lunar_eclipse")
        if not lunar_eclipse:
            return events

        visible = lunar_eclipse.get("visible", False)
        peak_time_str = lunar_eclipse.get("peak_time")

        if not peak_time_str:
            return events

        peak_time = self._parse_iso_time(peak_time_str)
        days_until = (peak_time.date() - self.local_now.date()).days

        eclipse_type = lunar_eclipse.get("type", "Penumbral")

        # Lunar eclipses are usually visible from wide areas
        if eclipse_type == "Total":
            importance = EventImportance.HIGH.value
        elif eclipse_type == "Partial":
            importance = EventImportance.MEDIUM.value
        else:
            importance = EventImportance.LOW.value

        event = AstronomicalEvent(
            id=f"lunar_eclipse_{peak_time_str.split('T')[0]}",
            event_type=EventType.LUNAR_ECLIPSE.value,
            icon_class="bi bi-moon-stars",
            icon_color_class=self._importance_icon_color_class(importance),
            title=(
                f"{self._translate_eclipse_type(eclipse_type, 'moon')} "
                f"{self._t('moon.lunar_eclipse', 'Lunar Eclipse')}"
            ),
            description=(
                self._t(
                    "events_api.lunar_eclipse_description",
                    f"{eclipse_type} lunar eclipse with {lunar_eclipse.get('obscuration_percent', 0):.1f}% "
                    f"coverage at peak.",
                    eclipse_type=self._translate_eclipse_type(eclipse_type, "moon"),
                    obscuration_percent=f"{lunar_eclipse.get('obscuration_percent', 0):.1f}",
                )
            ),
            start_time=lunar_eclipse.get("start_time"),
            peak_time=peak_time_str,
            end_time=lunar_eclipse.get("end_time"),
            days_until_event=days_until,
            visibility=visible,
            importance=importance,
            score=lunar_eclipse.get("astrophotography_score"),
            raw_data=eclipse_data,
            structure_key="moon",
        )
        events.append(event)
        return events

    def _extract_aurora_events(self, aurora_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Return only the first strong aurora visibility event.
        The aurora event is different because it is a forecast with multiple time slots (8 x 3h),
        so we will extract the most relevant one based on visibility likelihood and timing.
        """

        if not aurora_data:
            return []

        forecast = aurora_data.get("forecast", [])
        if not forecast:
            return []

        for entry in forecast:
            visibility_percent = entry.get("visibility_likelihood")
            if visibility_percent is None:
                visibility_percent = entry.get("probability", 0)

            # Only consider events with at least 70% visibility likelihood as worth reporting
            if visibility_percent < 70:
                continue

            timestamp = entry.get("timestamp")
            if not timestamp:
                continue

            try:
                event_date = datetime.datetime.fromisoformat(timestamp).astimezone(self.timezone)
            except Exception:
                continue

            days_until = (event_date.date() - self.local_now.date()).days
            kp_index = entry.get("kp_index", 0)

            importance = EventImportance.HIGH.value

            event = AstronomicalEvent(
                id=f"aurora_{timestamp}",
                event_type=EventType.AURORA.value,
                icon_class="bi bi-stars",
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._t("navbar.aurora", "Aurora Borealis"),
                description=(
                    self._t(
                        "events_api.aurora_description",
                        f"Aurora visibility: {visibility_percent:.0f}% likelihood. Kp index: {kp_index:.1f}",
                        visibility_percent=f"{visibility_percent:.0f}",
                        kp_index=f"{kp_index:.1f}",
                    )
                ),
                start_time=None,
                peak_time=event_date.isoformat(),
                end_time=None,
                days_until_event=days_until,
                visibility=True,
                importance=importance,
                score=visibility_percent,
                raw_data=entry,
                structure_key="aurora",
            )

            return [event]  # Immediately return the first strong event

        return []  # No strong events found

    def _extract_moon_phase_events(self, moon_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract moon phase events from 'phases' or 'next_7_nights' format"""
        events = []

        # 1. Standard 'phases' format
        phases = moon_data.get("phases", [])
        if phases:
            for phase in phases[:2]:  # Next 2 phases
                phase_type = phase.get("phase")
                phase_date_str = phase.get("date")
                if not phase_date_str:
                    continue
                phase_date = datetime.datetime.fromisoformat(phase_date_str).replace(tzinfo=self.timezone)
                days_until = (phase_date.date() - self.local_now.date()).days
                phase_info = {
                    "New Moon": {"importance": EventImportance.MEDIUM.value},
                    "First Quarter": {"importance": EventImportance.LOW.value},
                    "Full Moon": {"importance": EventImportance.MEDIUM.value},
                    "Last Quarter": {"importance": EventImportance.LOW.value},
                }
                phase_details = phase_info.get(phase_type, {"importance": EventImportance.LOW.value})
                localized_phase_type = self._get_moon_phase_translation(phase_type)
                event = AstronomicalEvent(
                    id=f"moon_phase_{phase_date_str}_{phase_type.lower().replace(' ', '_')}",
                    event_type=EventType.MOON_PHASE.value,
                    icon_class=self._phase_icon_class(phase_type),
                    icon_color_class=self._importance_icon_color_class(phase_details["importance"]),
                    title=localized_phase_type,
                    description=self._t(
                        "events_api.moon_phase_description",
                        f"{phase_type} occurs. Good time for {self._get_moon_phase_activity(phase_type)}.",
                        phase=localized_phase_type,
                        activity=self._get_moon_phase_activity(phase_type),
                    ),
                    start_time=None,
                    peak_time=phase_date_str,
                    end_time=None,
                    days_until_event=days_until,
                    visibility=True,
                    importance=phase_details["importance"],
                    score=None,
                    raw_data=moon_data,
                    structure_key="moon",
                )
                events.append(event)
            return events

        # 2. Adapted for 'next_7_nights' format
        nights = moon_data.get("next_7_nights", [])
        for night in nights:
            date_str = night.get("date")
            moon_info = night.get("moon", {})
            illumination = moon_info.get("illumination_percent")
            if date_str is None or illumination is None:
                continue
            # Heuristic: Full Moon >98%, New Moon <2%, else ignore
            if illumination >= 98:
                phase_type = "Full Moon"
                importance = EventImportance.MEDIUM.value
            elif illumination <= 2:
                phase_type = "New Moon"
                importance = EventImportance.MEDIUM.value
            else:
                continue  # Ignore other phases for now
            phase_date = datetime.datetime.fromisoformat(date_str).replace(tzinfo=self.timezone)
            days_until = (phase_date.date() - self.local_now.date()).days
            event = AstronomicalEvent(
                id=f"moon_phase_{date_str}_{phase_type.lower().replace(' ', '_')}",
                event_type=EventType.MOON_PHASE.value,
                icon_class=self._phase_icon_class(phase_type),
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._get_moon_phase_translation(phase_type),
                description=self._t(
                    "events_api.moon_phase_description",
                    f"{phase_type} occurs. Good time for {self._get_moon_phase_activity(phase_type)}.",
                    phase=self._get_moon_phase_translation(phase_type),
                    activity=self._get_moon_phase_activity(phase_type),
                ),
                start_time=None,
                peak_time=date_str,
                end_time=None,
                days_until_event=days_until,
                visibility=True,
                importance=importance,
                score=None,
                raw_data=moon_data,
                structure_key="moon",
            )
            events.append(event)
        return events

    def _extract_iss_pass_events(self, iss_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract ISS visible pass, solar transit, and lunar transit events occurring in the next 7 days."""
        raw_passes = iss_data.get("passes")
        if not isinstance(raw_passes, list):
            next_pass = iss_data.get("next_visible_passage")
            raw_passes = [next_pass] if next_pass else []

        raw_transits = iss_data.get("solar_transits")
        if not isinstance(raw_transits, list):
            next_transit = iss_data.get("next_solar_transit")
            raw_transits = [next_transit] if next_transit else []

        raw_lunar_transits = iss_data.get("lunar_transits")
        if not isinstance(raw_lunar_transits, list):
            next_lunar_transit = iss_data.get("next_lunar_transit")
            raw_lunar_transits = [next_lunar_transit] if next_lunar_transit else []

        events: List[AstronomicalEvent] = []

        for iss_pass in raw_passes:
            if not isinstance(iss_pass, dict):
                continue

            peak_time_str = iss_pass.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            # Passes are in chronological order; once beyond 7 days we can stop
            if days_until > 7:
                break
            if days_until < 0:
                continue

            score = float(iss_pass.get("visibility_score", 0) or 0)
            visibility_day_night = iss_pass.get("visibility_day_night", "Unknown")
            visibility_period_localized = self._translate_visibility_period(str(visibility_day_night))

            if score >= 75:
                importance = EventImportance.HIGH.value
            elif score >= 55:
                importance = EventImportance.MEDIUM.value
            else:
                importance = EventImportance.LOW.value

            event = AstronomicalEvent(
                id=f"iss_pass_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.ISS_PASS.value,
                icon_class="bi bi-iss",
                icon_color_class=self._importance_icon_color_class(importance),
                title=(
                    "ISS Visible Passage"
                    if self.i18n.get_language() == "en"
                    else self._t("iss.next_visible_passage", "ISS Visible Passage")
                ),
                description=(
                    self._t(
                        "events_api.iss_description",
                        f"ISS pass score {score:.0f}/100 ({visibility_day_night})."
                        f" Peak altitude {float(iss_pass.get('peak_altitude_deg', 0)):.1f}°.",
                        score=f"{score:.0f}",
                        visibility_day_night=visibility_period_localized,
                        peak_altitude_deg=f"{float(iss_pass.get('peak_altitude_deg', 0)):.1f}",
                    )
                ),
                start_time=iss_pass.get("start_time"),
                peak_time=peak_time_str,
                end_time=iss_pass.get("end_time"),
                days_until_event=days_until,
                visibility=bool(iss_pass.get("is_visible", False)),
                importance=importance,
                score=score,
                raw_data=iss_pass,
                structure_key="iss",
            )
            events.append(event)

        for transit in raw_transits:
            if not isinstance(transit, dict):
                continue

            peak_time_str = transit.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            if days_until < 0 or days_until > 7:
                continue

            min_sep_arcmin = float(transit.get("minimum_separation_arcmin", 0) or 0)
            duration_seconds = float(transit.get("duration_seconds", 0) or 0)
            sun_altitude_deg = float(transit.get("sun_altitude_deg", 0) or 0)
            solar_radius_arcmin = float(transit.get("solar_radius_arcmin", 0) or 0)

            score = 10.0
            importance = EventImportance.CRITICAL.value

            event = AstronomicalEvent(
                id=f"iss_solar_transit_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.ISS_SOLAR_TRANSIT.value,
                icon_class="bi bi-sun",
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._t(
                    "events_api.iss_solar_transit_title",
                    "ISS Solar Transit",
                ),
                description=self._t(
                    "events_api.iss_solar_transit_description",
                    "ISS crosses the solar disk from your location."
                    " Minimum separation {minimum_separation_arcmin}′, estimated transit window {duration_seconds}s"
                    " near {sun_altitude_deg}° solar altitude. Certified solar filter required.",
                    minimum_separation_arcmin=f"{min_sep_arcmin:.2f}",
                    duration_seconds=f"{duration_seconds:.1f}",
                    sun_altitude_deg=f"{sun_altitude_deg:.1f}",
                    solar_radius_arcmin=f"{solar_radius_arcmin:.2f}",
                ),
                start_time=transit.get("start_time"),
                peak_time=peak_time_str,
                end_time=transit.get("end_time"),
                days_until_event=days_until,
                visibility=bool(transit.get("is_visible", True)),
                importance=importance,
                score=score,
                raw_data=transit,
                structure_key="iss",
            )
            events.append(event)

        for lunar_transit in raw_lunar_transits:
            if not isinstance(lunar_transit, dict):
                continue

            peak_time_str = lunar_transit.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            if days_until < 0 or days_until > 7:
                continue

            min_sep_arcmin = float(lunar_transit.get("minimum_separation_arcmin", 0) or 0)
            duration_seconds = float(lunar_transit.get("duration_seconds", 0) or 0)
            moon_altitude_deg = float(lunar_transit.get("moon_altitude_deg", 0) or 0)
            lunar_radius_arcmin = float(lunar_transit.get("lunar_radius_arcmin", 0) or 0)
            moon_illumination_pct = float(lunar_transit.get("moon_illumination_pct", 0) or 0)

            score = 9.0
            importance = EventImportance.CRITICAL.value

            event = AstronomicalEvent(
                id=f"iss_lunar_transit_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.ISS_LUNAR_TRANSIT.value,
                icon_class="bi bi-moon-stars",
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._t(
                    "events_api.iss_lunar_transit_title",
                    "ISS Lunar Transit",
                ),
                description=self._t(
                    "events_api.iss_lunar_transit_description",
                    "ISS crosses the lunar disk from your location."
                    " Minimum separation {minimum_separation_arcmin}′, estimated transit window {duration_seconds}s"
                    " near {moon_altitude_deg}° lunar altitude. Moon illumination {moon_illumination_pct}%.",
                    minimum_separation_arcmin=f"{min_sep_arcmin:.2f}",
                    duration_seconds=f"{duration_seconds:.1f}",
                    moon_altitude_deg=f"{moon_altitude_deg:.1f}",
                    lunar_radius_arcmin=f"{lunar_radius_arcmin:.2f}",
                    moon_illumination_pct=f"{moon_illumination_pct:.0f}",
                ),
                start_time=lunar_transit.get("start_time"),
                peak_time=peak_time_str,
                end_time=lunar_transit.get("end_time"),
                days_until_event=days_until,
                visibility=bool(lunar_transit.get("is_visible", True)),
                importance=importance,
                score=score,
                raw_data=lunar_transit,
                structure_key="iss",
            )
            events.append(event)

        events.sort(key=lambda event: self._parse_iso_time(event.peak_time) if event.peak_time else self.local_now)
        return events

    def _extract_css_pass_events(self, css_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract CSS visible pass, solar transit, and lunar transit events occurring in the next 7 days."""
        raw_passes = css_data.get("passes")
        if not isinstance(raw_passes, list):
            next_pass = css_data.get("next_visible_passage")
            raw_passes = [next_pass] if next_pass else []

        raw_transits = css_data.get("solar_transits")
        if not isinstance(raw_transits, list):
            next_transit = css_data.get("next_solar_transit")
            raw_transits = [next_transit] if next_transit else []

        raw_lunar_transits = css_data.get("lunar_transits")
        if not isinstance(raw_lunar_transits, list):
            next_lunar_transit = css_data.get("next_lunar_transit")
            raw_lunar_transits = [next_lunar_transit] if next_lunar_transit else []

        events: List[AstronomicalEvent] = []

        for css_pass in raw_passes:
            if not isinstance(css_pass, dict):
                continue

            peak_time_str = css_pass.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            if days_until > 7:
                break
            if days_until < 0:
                continue

            score = float(css_pass.get("visibility_score", 0) or 0)
            visibility_day_night = css_pass.get("visibility_day_night", "Unknown")
            visibility_period_localized = self._translate_visibility_period(str(visibility_day_night))

            if score >= 75:
                importance = EventImportance.HIGH.value
            elif score >= 55:
                importance = EventImportance.MEDIUM.value
            else:
                importance = EventImportance.LOW.value

            event = AstronomicalEvent(
                id=f"css_pass_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.CSS_PASS.value,
                icon_class="bi bi-iss",
                icon_color_class=self._importance_icon_color_class(importance),
                title=(
                    "CSS Visible Passage"
                    if self.i18n.get_language() == "en"
                    else self._t("css.next_visible_passage", "CSS Visible Passage")
                ),
                description=(
                    self._t(
                        "events_api.css_description",
                        f"CSS pass score {score:.0f}/100 ({visibility_day_night})."
                        f" Peak altitude {float(css_pass.get('peak_altitude_deg', 0)):.1f}°.",
                        score=f"{score:.0f}",
                        visibility_day_night=visibility_period_localized,
                        peak_altitude_deg=f"{float(css_pass.get('peak_altitude_deg', 0)):.1f}",
                    )
                ),
                start_time=css_pass.get("start_time"),
                peak_time=peak_time_str,
                end_time=css_pass.get("end_time"),
                days_until_event=days_until,
                visibility=bool(css_pass.get("is_visible", False)),
                importance=importance,
                score=score,
                raw_data=css_pass,
                structure_key="css",
            )
            events.append(event)

        for transit in raw_transits:
            if not isinstance(transit, dict):
                continue

            peak_time_str = transit.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            if days_until < 0 or days_until > 7:
                continue

            min_sep_arcmin = float(transit.get("minimum_separation_arcmin", 0) or 0)
            duration_seconds = float(transit.get("duration_seconds", 0) or 0)
            sun_altitude_deg = float(transit.get("sun_altitude_deg", 0) or 0)
            solar_radius_arcmin = float(transit.get("solar_radius_arcmin", 0) or 0)

            score = 10.0
            importance = EventImportance.CRITICAL.value

            event = AstronomicalEvent(
                id=f"css_solar_transit_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.CSS_SOLAR_TRANSIT.value,
                icon_class="bi bi-sun",
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._t("events_api.css_solar_transit_title", "CSS Solar Transit"),
                description=self._t(
                    "events_api.css_solar_transit_description",
                    "CSS crosses the solar disk from your location."
                    " Minimum separation {minimum_separation_arcmin}′, estimated transit window {duration_seconds}s"
                    " near {sun_altitude_deg}° solar altitude. Certified solar filter required.",
                    minimum_separation_arcmin=f"{min_sep_arcmin:.2f}",
                    duration_seconds=f"{duration_seconds:.1f}",
                    sun_altitude_deg=f"{sun_altitude_deg:.1f}",
                    solar_radius_arcmin=f"{solar_radius_arcmin:.2f}",
                ),
                start_time=transit.get("start_time"),
                peak_time=peak_time_str,
                end_time=transit.get("end_time"),
                days_until_event=days_until,
                visibility=bool(transit.get("is_visible", True)),
                importance=importance,
                score=score,
                raw_data=transit,
                structure_key="css",
            )
            events.append(event)

        for lunar_transit in raw_lunar_transits:
            if not isinstance(lunar_transit, dict):
                continue

            peak_time_str = lunar_transit.get("peak_time")
            if not peak_time_str:
                continue

            peak_time = self._parse_iso_time(peak_time_str)
            days_until = (peak_time.date() - self.local_now.date()).days

            if days_until < 0 or days_until > 7:
                continue

            min_sep_arcmin = float(lunar_transit.get("minimum_separation_arcmin", 0) or 0)
            duration_seconds = float(lunar_transit.get("duration_seconds", 0) or 0)
            moon_altitude_deg = float(lunar_transit.get("moon_altitude_deg", 0) or 0)
            lunar_radius_arcmin = float(lunar_transit.get("lunar_radius_arcmin", 0) or 0)
            moon_illumination_pct = float(lunar_transit.get("moon_illumination_pct", 0) or 0)

            score = 9.0
            importance = EventImportance.CRITICAL.value

            event = AstronomicalEvent(
                id=f"css_lunar_transit_{peak_time_str.replace(':', '').replace('-', '')}",
                event_type=EventType.CSS_LUNAR_TRANSIT.value,
                icon_class="bi bi-moon-stars",
                icon_color_class=self._importance_icon_color_class(importance),
                title=self._t("events_api.css_lunar_transit_title", "CSS Lunar Transit"),
                description=self._t(
                    "events_api.css_lunar_transit_description",
                    "CSS crosses the lunar disk from your location."
                    " Minimum separation {minimum_separation_arcmin}′, estimated transit window {duration_seconds}s"
                    " near {moon_altitude_deg}° lunar altitude. Moon illumination {moon_illumination_pct}%.",
                    minimum_separation_arcmin=f"{min_sep_arcmin:.2f}",
                    duration_seconds=f"{duration_seconds:.1f}",
                    moon_altitude_deg=f"{moon_altitude_deg:.1f}",
                    lunar_radius_arcmin=f"{lunar_radius_arcmin:.2f}",
                    moon_illumination_pct=f"{moon_illumination_pct:.0f}",
                ),
                start_time=lunar_transit.get("start_time"),
                peak_time=peak_time_str,
                end_time=lunar_transit.get("end_time"),
                days_until_event=days_until,
                visibility=bool(lunar_transit.get("is_visible", True)),
                importance=importance,
                score=score,
                raw_data=lunar_transit,
                structure_key="css",
            )
            events.append(event)

        events.sort(key=lambda event: self._parse_iso_time(event.peak_time) if event.peak_time else self.local_now)
        return events

    def _get_moon_phase_activity(self, phase_type: str) -> str:
        """Get recommended activity for moon phase"""
        activity_key_map = {
            "New Moon": "deep_sky_observations",
            "First Quarter": "lunar_observations",
            "Full Moon": "lunar_photography",
            "Last Quarter": "lunar_observations",
        }
        activity_key = activity_key_map.get(phase_type, "observing")
        fallback_map = {
            "deep_sky_observations": "deep-sky observations",
            "lunar_observations": "lunar observations",
            "lunar_photography": "lunar photography",
            "observing": "observing",
        }
        return self._t(f"events_api.activities.{activity_key}", fallback_map.get(activity_key, "observing"))

    def _parse_iso_time(self, iso_string: str) -> datetime.datetime:
        """Parse ISO format time string"""
        try:
            dt = datetime.datetime.fromisoformat(iso_string)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.timezone)
            return dt
        except Exception as e:
            logger.warning(f"Failed to parse ISO time '{iso_string}': {e}")
            return self.local_now

    def _get_local_now(self) -> datetime.datetime:
        """Get current time in configured timezone"""
        return datetime.datetime.now(self.timezone)

    def _extract_planetary_events(self, planetary_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract planetary events from raw data"""
        events = []

        raw_events = planetary_data.get("events", [])
        if not isinstance(raw_events, list):
            return events

        for event_data in raw_events:
            try:
                peak_time_str = event_data.get("peak_time")
                if not peak_time_str:
                    continue

                peak_time = self._parse_iso_time(peak_time_str)
                days_until = (peak_time.date() - self.local_now.date()).days

                visibility = event_data.get("visibility", True)
                importance = event_data.get("importance", "medium")

                event_type = event_data.get("event_type", "Planetary Event")
                title, description = self._localize_planetary_text(event_data)
                icon_class = event_data.get("icon_class") or self._infer_icon_class(event_type)
                icon_color_class = event_data.get("icon_color_class") or self._importance_icon_color_class(importance)

                event = AstronomicalEvent(
                    id=(
                        f"planetary_{peak_time_str.replace(':', '').replace('-', '')}"
                        f"_{event_type.lower().replace(' ', '_')}"
                    ),
                    event_type=event_type,
                    icon_class=icon_class,
                    icon_color_class=icon_color_class,
                    title=title,
                    description=description,
                    start_time=event_data.get("start_time"),
                    peak_time=peak_time_str,
                    end_time=event_data.get("end_time"),
                    days_until_event=days_until,
                    visibility=visibility,
                    importance=importance,
                    score=event_data.get("score"),
                    raw_data=event_data,
                    structure_key="calendar",
                )
                events.append(event)
            except Exception as e:
                logger.debug(f"Error extracting planetary event: {e}")

        return events

    def _extract_special_phenomena_events(self, phenomena_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract special phenomena events from raw data"""
        events = []

        raw_events = phenomena_data.get("events", [])
        if not isinstance(raw_events, list):
            return events

        for event_data in raw_events:
            try:
                peak_time_str = event_data.get("peak_time")
                if not peak_time_str:
                    continue

                peak_time = self._parse_iso_time(peak_time_str)
                days_until = (peak_time.date() - self.local_now.date()).days

                visibility = event_data.get("visibility", True)
                importance = event_data.get("importance", "medium")

                event_type = event_data.get("event_type", "Special Phenomenon")
                title, description = self._localize_special_phenomena_text(event_data)
                icon_class = event_data.get("icon_class") or self._infer_icon_class(event_type)
                icon_color_class = event_data.get("icon_color_class") or self._importance_icon_color_class(importance)

                event = AstronomicalEvent(
                    id=(
                        f"phenomena_{peak_time_str.replace(':', '').replace('-', '')}"
                        f"_{event_type.lower().replace(' ', '_')}"
                    ),
                    event_type=event_type,
                    icon_class=icon_class,
                    icon_color_class=icon_color_class,
                    title=title,
                    description=description,
                    start_time=event_data.get("start_time"),
                    peak_time=peak_time_str,
                    end_time=event_data.get("end_time"),
                    days_until_event=days_until,
                    visibility=visibility,
                    importance=importance,
                    score=event_data.get("score"),
                    raw_data=event_data,
                    structure_key="calendar",
                )
                events.append(event)
            except Exception as e:
                logger.debug(f"Error extracting special phenomena event: {e}")

        return events

    def _extract_solar_system_events(self, solsys_data: Dict[str, Any]) -> List[AstronomicalEvent]:
        """Extract solar system events (meteor showers, comets, occultations) from raw data"""
        events = []

        raw_events = solsys_data.get("events", [])
        if not isinstance(raw_events, list):
            return events

        for event_data in raw_events:
            try:
                peak_time_str = event_data.get("peak_time")
                if not peak_time_str:
                    continue

                peak_time = self._parse_iso_time(peak_time_str)
                days_until = (peak_time.date() - self.local_now.date()).days

                visibility = event_data.get("visibility", True)
                importance = event_data.get("importance", "medium")

                event_type = event_data.get("event_type", "Solar System Event")
                title = event_data.get("title", "Solar System Event")
                description = event_data.get("description", "")
                icon_class = event_data.get("icon_class") or self._infer_icon_class(event_type, "bi bi-meteor")
                icon_color_class = event_data.get("icon_color_class") or self._importance_icon_color_class(importance)

                event = AstronomicalEvent(
                    id=(
                        f"solsys_{peak_time_str.replace(':', '').replace('-', '')}"
                        f"_{event_type.lower().replace(' ', '_')}"
                    ),
                    event_type=event_type,
                    icon_class=icon_class,
                    icon_color_class=icon_color_class,
                    title=title,
                    description=description,
                    start_time=event_data.get("start_time"),
                    peak_time=peak_time_str,
                    end_time=event_data.get("end_time"),
                    days_until_event=days_until,
                    visibility=visibility,
                    importance=importance,
                    score=event_data.get("score"),
                    raw_data=event_data,
                    structure_key="calendar",
                )
                events.append(event)
            except Exception as e:
                logger.debug(f"Error extracting solar system event: {e}")

        return events
