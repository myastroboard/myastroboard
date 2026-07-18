"""
Solar System Events Service for MyAstroBoard

Calculates solar system phenomena:
- Meteor Showers - peak times and radiant positions
- Comet Appearances - perihelion passages or brightest dates
- Asteroid Occultations - when an asteroid passes in front of a star

Uses a curated database of known events for accuracy.
Provides detailed visibility information for each event.
"""

from datetime import datetime, timedelta, date
from typing import List, Dict, Any
from zoneinfo import ZoneInfo
from utils.logging_config import get_logger
from utils.i18n_utils import I18nManager

from astropy.coordinates import EarthLocation, AltAz, SkyCoord, ICRS
from astropy.time import Time
from astropy import units as u
import numpy as np

logger = get_logger(__name__)


class SolarSystemEventsService:
    """
    Provides information about solar system events.
    Includes meteor showers, comet appearances, and asteroid occultations.
    """

    # Known active meteor showers throughout the year with peak dates
    METEOR_SHOWERS = {
        'Quadrantids': {
            'peak_month': 1,
            'peak_day_start': 1,
            'peak_day_end': 5,
            'radiant_ra': 230,  # degrees
            'radiant_dec': 49,  # degrees
            'zenith_hourly_rate': 40,
            'parent_body': '2003 EH1 (asteroid)',
            'hemisphere': 'both',
        },
        'Lyrids': {
            'peak_month': 4,
            'peak_day_start': 16,
            'peak_day_end': 25,
            'radiant_ra': 271,
            'radiant_dec': 34,
            'zenith_hourly_rate': 18,
            'parent_body': 'C/1861 G1 (Thatcher)',
            'hemisphere': 'both',
        },
        'Eta Aquariids': {
            'peak_month': 5,
            'peak_day_start': 1,
            'peak_day_end': 10,
            'radiant_ra': 336,
            'radiant_dec': -1,
            'zenith_hourly_rate': 40,
            'parent_body': '1P/Halley (comet)',
            'hemisphere': 'both',
        },
        'Delta Aquariids': {
            'peak_month': 7,
            'peak_day_start': 12,
            'peak_day_end': 20,
            'radiant_ra': 339,
            'radiant_dec': -16,
            'zenith_hourly_rate': 20,
            'parent_body': '96P/Machholz 1',
            'hemisphere': 'both',
        },
        'Perseids': {
            'peak_month': 8,
            'peak_day_start': 10,
            'peak_day_end': 14,
            'radiant_ra': 48,
            'radiant_dec': 58,
            'zenith_hourly_rate': 80,
            'parent_body': '109P/Swift-Tuttle',
            'hemisphere': 'Northern',
        },
        'Draconids': {
            'peak_month': 10,
            'peak_day_start': 6,
            'peak_day_end': 10,
            'radiant_ra': 262,
            'radiant_dec': 54,
            'zenith_hourly_rate': 10,
            'parent_body': '21P/Giacobini-Zinner',
            'hemisphere': 'Northern',
        },
        'Orionids': {
            'peak_month': 10,
            'peak_day_start': 15,
            'peak_day_end': 29,
            'radiant_ra': 95,
            'radiant_dec': 16,
            'zenith_hourly_rate': 20,
            'parent_body': '1P/Halley (comet)',
            'hemisphere': 'both',
        },
        'Geminids': {
            'peak_month': 12,
            'peak_day_start': 7,
            'peak_day_end': 17,
            'radiant_ra': 112,
            'radiant_dec': 33,
            'zenith_hourly_rate': 100,
            'parent_body': '3200 Phaethon (asteroid)',
            'hemisphere': 'both',
        },
        'Ursids': {
            'peak_month': 12,
            'peak_day_start': 17,
            'peak_day_end': 26,
            'radiant_ra': 217,
            'radiant_dec': 75,
            'zenith_hourly_rate': 10,
            'parent_body': '8P/Tuttle',
            'hemisphere': 'Northern',
        },
    }

    # Notable comets visible this decade
    NOTABLE_COMETS = {
        '6P/d\'Arrest': {
            'perihelion_month': 4,
            'perihelion_day': 15,
            'perihelion_year': 2026,
            'magnitude': 8.5,
            'visibility': 'binoculars',
        },
        '13P/Olbers': {
            'perihelion_month': 10,
            'perihelion_day': 20,
            'perihelion_year': 2026,
            'magnitude': 7,
            'visibility': 'naked_eye_possible',
        },
        '65P/Gunn': {
            'perihelion_month': 6,
            'perihelion_day': 10,
            'perihelion_year': 2026,
            'magnitude': 8,
            'visibility': 'binoculars',
        },
    }

    def __init__(
        self, latitude: float, longitude: float, elevation: float = 0, timezone: str = "UTC", language: str = "en"
    ):
        """
        Initialize solar system events service.

        Args:
            latitude: Observer latitude in degrees
            longitude: Observer longitude in degrees
            elevation: Observer elevation in meters (default 0)
            timezone: IANA timezone string (default UTC)
            language: Language code for translations (default 'en')
        """
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.timezone = ZoneInfo(timezone)
        self.language = language
        self.i18n = I18nManager(language)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation * u.m)
        # Determine hemisphere
        self.hemisphere = 'Northern' if latitude >= 0 else 'Southern'

    def get_solar_system_events(self, days_ahead: int = 365) -> List[Dict[str, Any]]:
        """
        Get all solar system events for the next N days.

        Args:
            days_ahead: Number of days to calculate ahead (default 365)

        Returns:
            List of solar system events, sorted by date
        """
        events = []
        today = datetime.now(tz=ZoneInfo("UTC")).date()

        try:
            # Get meteor shower events
            meteor_events = self._find_meteor_shower_peaks(today, days_ahead)
            events.extend(meteor_events)

            # Get comet visibility events
            comet_events = self._find_comet_visibility_windows(today, days_ahead)
            events.extend(comet_events)

            # Get asteroid occultation events (if any known ones exist)
            occultation_events = self._find_asteroid_occultations(today, days_ahead)
            events.extend(occultation_events)

        except Exception as e:
            logger.error(f"Error calculating solar system events: {e}")
            return []

        # Sort by time
        events.sort(key=lambda x: x.get('peak_time', x.get('start_time')))

        return events

    def _find_meteor_shower_peaks(self, start_date: date, days_ahead: int) -> List[Dict[str, Any]]:
        """Find meteor shower peak events."""
        events = []
        current_year = start_date.year
        end_date = start_date + timedelta(days=days_ahead)

        for shower_name, shower_data in self.METEOR_SHOWERS.items():
            try:
                # Check if this shower is visible from this hemisphere
                if shower_data['hemisphere'] == 'Northern' and self.hemisphere == 'Southern':
                    continue
                elif shower_data['hemisphere'] == 'Southern' and self.hemisphere == 'Northern':
                    continue

                # Calculate peak day for this year
                peak_month = shower_data['peak_month']
                peak_day_start = shower_data['peak_day_start']
                peak_day_end = shower_data['peak_day_end']
                peak_day = (peak_day_start + peak_day_end) // 2

                peak_date = datetime(current_year, peak_month, peak_day, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

                if start_date <= peak_date.date() <= end_date:
                    # Check if radiant is visible
                    peak_time = Time(peak_date)
                    is_visible = self._is_radiant_visible(
                        shower_data['radiant_ra'], shower_data['radiant_dec'], peak_time
                    )

                    # Get translated title and description
                    title = self.i18n.t('events_api.solar_system.meteor_shower_title', shower_name=shower_name)
                    description = self.i18n.t(
                        'events_api.solar_system.meteor_shower_description',
                        zenith_hourly_rate=shower_data['zenith_hourly_rate'],
                        parent_body=shower_data['parent_body'],
                    )

                    # Score 0-10: ZHR drives 70 %, radiant visibility drives 30 %
                    zhr = shower_data['zenith_hourly_rate']
                    score = round(min(10.0, (zhr / 100.0) * 7.0 + (3.0 if is_visible else 0.0)), 1)

                    events.append(
                        {
                            'event_type': 'Meteor Shower',
                            'title': title,
                            'description': description,
                            'icon_class': 'bi bi-comet',
                            'peak_time': self._to_local_iso(peak_time),
                            'start_time': self._to_local_iso(
                                peak_time - (2 * u.day)
                            ),  # Peak activity is 2 days before to 2 days after
                            'end_time': self._to_local_iso(peak_time + (2 * u.day)),
                            'visibility_range': f'{start_date} to {end_date}',
                            'radiant_coordinates': {
                                'ra_degrees': shower_data['radiant_ra'],
                                'dec_degrees': shower_data['radiant_dec'],
                            },
                            'zenith_hourly_rate': shower_data['zenith_hourly_rate'],
                            'parent_body': shower_data['parent_body'],
                            'best_viewing_time': 'After midnight (local time)',
                            'visibility': is_visible,
                            'importance': self._rate_meteor_shower_importance(shower_data['zenith_hourly_rate']),
                            'score': score,
                            'raw_data': {
                                'shower': shower_name,
                                'peak_month': peak_month,
                                'peak_day': peak_day,
                                'radiant_ra': shower_data['radiant_ra'],
                                'radiant_dec': shower_data['radiant_dec'],
                            },
                        }
                    )

            except Exception as e:
                logger.debug(f"Error calculating meteor shower {shower_name}: {e}")

        return events

    def _find_comet_visibility_windows(self, start_date: date, days_ahead: int) -> List[Dict[str, Any]]:
        """Find comet visibility windows based on perihelion dates."""
        events = []
        end_date = start_date + timedelta(days=days_ahead)

        for comet_name, comet_data in self.NOTABLE_COMETS.items():
            try:
                # Calculate perihelion date
                perihelion_date = datetime(
                    comet_data['perihelion_year'],
                    comet_data['perihelion_month'],
                    comet_data['perihelion_day'],
                    12,
                    0,
                    0,
                    tzinfo=ZoneInfo("UTC"),
                )

                # Comets are typically visible within ~30 days of perihelion
                visibility_start = perihelion_date - timedelta(days=30)
                visibility_end = perihelion_date + timedelta(days=30)

                # Check if this window overlaps with our search period
                if visibility_start.date() <= end_date and visibility_end.date() >= start_date:
                    # Calculate magnitude at different points
                    visibility_type = self._estimate_comet_visibility(comet_data['magnitude'])

                    # Get translated title and description
                    title = self.i18n.t('events_api.solar_system.comet_title', comet_name=comet_name)
                    description = self.i18n.t(
                        'events_api.solar_system.comet_description',
                        magnitude=comet_data['magnitude'],
                        visibility=comet_data['visibility'],
                    )

                    events.append(
                        {
                            'event_type': 'Comet Appearance',
                            'title': title,
                            'description': description,
                            'icon_class': 'bi bi-comet',
                            'peak_time': self._to_local_iso(Time(perihelion_date)),
                            'start_time': self._to_local_iso(Time(visibility_start)),
                            'end_time': self._to_local_iso(Time(visibility_end)),
                            'perihelion_date': perihelion_date.isoformat(),
                            'magnitude': comet_data['magnitude'],
                            'visibility': visibility_type,
                            'equipment_needed': comet_data['visibility'],
                            'importance': self._rate_comet_importance(comet_data['magnitude']),
                            'raw_data': {
                                'comet': comet_name,
                                'perihelion': perihelion_date.isoformat(),
                                'magnitude': comet_data['magnitude'],
                            },
                        }
                    )

            except Exception as e:
                logger.debug(f"Error calculating comet visibility for {comet_name}: {e}")

        return events

    def _find_asteroid_occultations(self, start_date: date, days_ahead: int) -> List[Dict[str, Any]]:
        """
        Find asteroid occultation events.

        Note: This would require a database of known occultations.
        For now, we provide a template for how this would work.
        In a production system, this would query IOTA or similar databases.
        """
        events = []

        # Example structure for an asteroid occultation
        # In production, this would be queried from IOTA/IOD database
        # https://www.occultations.org/

        logger.debug("Asteroid occultation data would be fetched from IOTA/IOD database")

        return events

    def _is_radiant_visible(self, radiant_ra: float, radiant_dec: float, time: Time) -> bool:
        """Check if a meteor shower radiant is visible from the observer location."""
        try:
            radiant = SkyCoord(ra=radiant_ra * u.deg, dec=radiant_dec * u.deg, frame=ICRS)
            altaz = radiant.transform_to(AltAz(obstime=time, location=self.location))

            if altaz is None:
                return False

            # Radiant should be above horizon
            alt_val = altaz.alt.degree  # type: ignore
            if isinstance(alt_val, (np.ndarray, complex)):
                altitude = float(np.real(np.atleast_1d(alt_val).flat[0]))
            else:
                altitude = float(alt_val)  # type: ignore

            return altitude > 10
        except Exception:
            return False

    def _estimate_comet_visibility(self, magnitude: float) -> bool:
        """Estimate if comet is visible (naked eye vs binoculars)."""
        # Magnitude 6 is naked eye limit
        return magnitude <= 6.0

    def _rate_meteor_shower_importance(self, zhr: int) -> str:
        """Rate importance based on Zenith Hourly Rate."""
        if zhr >= 50:
            return 'high'
        elif zhr >= 20:
            return 'medium'
        else:
            return 'low'

    def _rate_comet_importance(self, magnitude: float) -> str:
        """Rate importance based on magnitude."""
        if magnitude <= 5:
            return 'high'
        elif magnitude <= 7:
            return 'medium'
        else:
            return 'low'

    def _to_local_iso(self, time: Time) -> str:
        """Convert Astropy Time to configured local timezone ISO string with offset."""
        from datetime import datetime

        dt = time.to_datetime(timezone=self.timezone)
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)
