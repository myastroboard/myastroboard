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
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from utils import parse_iso_to_utc
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

    # Known meteor showers with peak dates and full IMO activity periods. The
    # activity window (start/end month+day) is what the shower is genuinely "on"
    # for - weeks around the peak - and drives the "happening now" display; these
    # values are annually stable (the Earth recrosses the same debris stream), so
    # they are curated rather than fetched.
    METEOR_SHOWERS = {
        'Quadrantids': {
            'peak_month': 1,
            'peak_day_start': 1,
            'peak_day_end': 5,
            'activity_start_month': 12,
            'activity_start_day': 28,
            'activity_end_month': 1,
            'activity_end_day': 12,
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
            'activity_start_month': 4,
            'activity_start_day': 16,
            'activity_end_month': 4,
            'activity_end_day': 25,
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
            'activity_start_month': 4,
            'activity_start_day': 19,
            'activity_end_month': 5,
            'activity_end_day': 28,
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
            'activity_start_month': 7,
            'activity_start_day': 12,
            'activity_end_month': 8,
            'activity_end_day': 23,
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
            'activity_start_month': 7,
            'activity_start_day': 17,
            'activity_end_month': 8,
            'activity_end_day': 24,
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
            'activity_start_month': 10,
            'activity_start_day': 6,
            'activity_end_month': 10,
            'activity_end_day': 10,
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
            'activity_start_month': 10,
            'activity_start_day': 2,
            'activity_end_month': 11,
            'activity_end_day': 7,
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
            'activity_start_month': 12,
            'activity_start_day': 4,
            'activity_end_month': 12,
            'activity_end_day': 20,
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
            'activity_start_month': 12,
            'activity_start_day': 17,
            'activity_end_month': 12,
            'activity_end_day': 26,
            'radiant_ra': 217,
            'radiant_dec': 75,
            'zenith_hourly_rate': 10,
            'parent_body': '8P/Tuttle',
            'hemisphere': 'Northern',
        },
    }

    # Fallback comet list, used ONLY when the live SkyTonight comet dataset cannot
    # be read (see _find_comet_visibility_windows). Comet apparitions are one-off
    # dated events, so unlike the annually-recurring meteor showers above they
    # cannot be hardcoded long-term; the primary source is the MPC-fed dataset,
    # which stays current automatically. This short curated list is a safety net.
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

        # Sort by absolute instant (parsed from the local ISO strings) so events
        # stay correctly ordered across a daylight-saving offset change.
        events.sort(key=lambda x: parse_iso_to_utc(x.get('peak_time') or x.get('start_time')))

        return events

    @staticmethod
    def _shower_activity_window(peak_date: datetime, shower_data: Dict[str, Any]):
        """Return (start_dt, end_dt) UTC datetimes bracketing the peak for the shower's
        real IMO activity period.

        The window brackets the peak, so a shower whose activity opens in the
        previous calendar year (e.g. the Quadrantids, active late December to early
        January) or closes in the next year is anchored to the correct years.
        """
        peak_year = peak_date.year
        start_month = shower_data['activity_start_month']
        start_day = shower_data['activity_start_day']
        end_month = shower_data['activity_end_month']
        end_day = shower_data['activity_end_day']
        start_year = peak_year if start_month <= peak_date.month else peak_year - 1
        end_year = peak_year if end_month >= peak_date.month else peak_year + 1
        start_dt = datetime(start_year, start_month, start_day, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        end_dt = datetime(end_year, end_month, end_day, 23, 59, 0, tzinfo=ZoneInfo("UTC"))
        return start_dt, end_dt

    def _find_meteor_shower_peaks(self, start_date: date, days_ahead: int) -> List[Dict[str, Any]]:
        """Find meteor shower peak events.

        Each shower is checked for both the start year and the following year so a
        window that crosses a calendar boundary (e.g. a 365-day search started in
        mid-year) still surfaces early-year showers of the next year instead of
        silently dropping them.
        """
        events = []
        end_date = start_date + timedelta(days=days_ahead)
        years_to_check = [start_date.year, start_date.year + 1]

        for shower_name, shower_data in self.METEOR_SHOWERS.items():
            try:
                # Check if this shower is visible from this hemisphere
                if shower_data['hemisphere'] == 'Northern' and self.hemisphere == 'Southern':
                    continue
                elif shower_data['hemisphere'] == 'Southern' and self.hemisphere == 'Northern':
                    continue

                peak_month = shower_data['peak_month']
                peak_day_start = shower_data['peak_day_start']
                peak_day_end = shower_data['peak_day_end']
                peak_day = (peak_day_start + peak_day_end) // 2

                for year in years_to_check:
                    peak_date = datetime(year, peak_month, peak_day, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

                    if not (start_date <= peak_date.date() <= end_date):
                        continue

                    peak_time = Time(peak_date)
                    activity_start, activity_end = self._shower_activity_window(peak_date, shower_data)
                    # Evaluate radiant visibility at a representative deep-night hour
                    # (02:00 observer-local), when meteors are actually watched, rather
                    # than at the noon-UTC peak marker which bears no relation to the
                    # observer's night.
                    visibility_dt = datetime(year, peak_month, peak_day, 2, 0, 0, tzinfo=self.timezone)
                    is_visible = self._is_radiant_visible(
                        shower_data['radiant_ra'], shower_data['radiant_dec'], Time(visibility_dt)
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
                            # Full IMO activity window so the shower reads as "happening
                            # now" for its whole multi-week span, not only around the peak.
                            'start_time': self._to_local_iso(Time(activity_start)),
                            'end_time': self._to_local_iso(Time(activity_end)),
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

    # Comets brighter (lower absolute magnitude) than this are treated as
    # "notable" and surfaced from the live dataset; the rest of the ~1000-entry
    # MPC catalogue is skipped so the events list stays a short, meaningful set.
    _COMET_NOTABLE_ABS_MAG_MAX = 10.0

    def _find_comet_visibility_windows(self, start_date: date, days_ahead: int) -> List[Dict[str, Any]]:
        """Find comet visibility windows around each comet's perihelion.

        Comet apparitions are one-off dated events (unlike the annually-recurring
        meteor showers), so a hardcoded list goes stale. Candidates are therefore
        read from the live SkyTonight comet dataset, which is rebuilt from the MPC
        CometEls.txt feed and so stays current on its own. The small curated
        NOTABLE_COMETS list is used only as a fallback when the dataset is
        unavailable (e.g. not built yet).
        """
        end_date = start_date + timedelta(days=days_ahead)

        candidates = self._dataset_comet_candidates()
        source = 'dataset'
        if not candidates:
            candidates = self._curated_comet_candidates()
            source = 'curated'

        events: List[Dict[str, Any]] = []
        for candidate in candidates:
            try:
                event = self._build_comet_event(candidate, start_date, end_date, source)
                if event is not None:
                    events.append(event)
            except Exception as e:
                logger.debug(f"Error calculating comet visibility for {candidate.get('name')}: {e}")

        return events

    def _dataset_comet_candidates(self) -> List[Dict[str, Any]]:
        """Notable-comet candidates derived from the live MPC-sourced dataset.

        Keeps only comets with a parseable perihelion date and an absolute
        magnitude at or brighter than ``_COMET_NOTABLE_ABS_MAG_MAX``. Returns an
        empty list when the dataset cannot be read, so the caller falls back to
        the curated list.
        """
        try:
            from skytonight.skytonight_targets import load_targets_dataset

            dataset = load_targets_dataset()
        except Exception as e:  # dataset not built yet or read failure
            logger.debug(f"Comet dataset unavailable, using curated fallback: {e}")
            return []

        candidates: List[Dict[str, Any]] = []
        for target in dataset.get('targets', []):
            is_dict = isinstance(target, dict)
            category = target.get('category') if is_dict else getattr(target, 'category', None)
            if category != 'comets':
                continue
            magnitude = target.get('magnitude') if is_dict else getattr(target, 'magnitude', None)
            if magnitude is None or magnitude > self._COMET_NOTABLE_ABS_MAG_MAX:
                continue
            metadata = target.get('metadata') if is_dict else getattr(target, 'metadata', None)
            metadata = metadata if isinstance(metadata, dict) else {}
            perihelion = self._parse_perihelion(metadata.get('perihelion_date'))
            if perihelion is None:
                continue
            name = target.get('preferred_name') if is_dict else getattr(target, 'preferred_name', None)
            candidates.append(
                {
                    'name': str(name or 'Comet'),
                    'perihelion': perihelion,
                    'magnitude': float(magnitude),
                    'equipment': None,
                }
            )
        return candidates

    def _curated_comet_candidates(self) -> List[Dict[str, Any]]:
        """Fallback candidates from the small hardcoded NOTABLE_COMETS list."""
        candidates: List[Dict[str, Any]] = []
        for name, data in self.NOTABLE_COMETS.items():
            try:
                perihelion = datetime(
                    data['perihelion_year'],
                    data['perihelion_month'],
                    data['perihelion_day'],
                    12,
                    0,
                    0,
                    tzinfo=ZoneInfo("UTC"),
                )
            except (KeyError, ValueError):
                continue
            candidates.append(
                {
                    'name': name,
                    'perihelion': perihelion,
                    'magnitude': data.get('magnitude'),
                    'equipment': data.get('visibility'),
                }
            )
        return candidates

    @staticmethod
    def _parse_perihelion(value: Any) -> Optional[datetime]:
        """Parse a 'YYYY-MM-DD' perihelion date into a UTC datetime at noon."""
        if not value:
            return None
        try:
            parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
        return parsed.replace(hour=12, tzinfo=ZoneInfo("UTC"))

    @staticmethod
    def _equipment_label(magnitude: Optional[float]) -> str:
        """Map an (absolute) comet magnitude to a rough required-equipment hint."""
        if magnitude is None:
            return 'telescope'
        if magnitude <= 6.0:
            return 'naked_eye_possible'
        if magnitude <= 9.0:
            return 'binoculars'
        return 'telescope'

    def _build_comet_event(
        self, candidate: Dict[str, Any], start_date: date, end_date: date, source: str
    ) -> Optional[Dict[str, Any]]:
        """Build one comet event dict when its ±30-day window overlaps the search range."""
        perihelion_date: datetime = candidate['perihelion']
        magnitude = candidate.get('magnitude')

        # Comets are typically visible within ~30 days of perihelion
        visibility_start = perihelion_date - timedelta(days=30)
        visibility_end = perihelion_date + timedelta(days=30)
        if not (visibility_start.date() <= end_date and visibility_end.date() >= start_date):
            return None

        comet_name = candidate['name']
        equipment = candidate.get('equipment') or self._equipment_label(magnitude)
        visibility_type = self._estimate_comet_visibility(magnitude) if magnitude is not None else False

        title = self.i18n.t('events_api.solar_system.comet_title', comet_name=comet_name)
        description = self.i18n.t(
            'events_api.solar_system.comet_description',
            magnitude=magnitude if magnitude is not None else '—',
            visibility=equipment,
        )

        return {
            'event_type': 'Comet Appearance',
            'title': title,
            'description': description,
            'icon_class': 'bi bi-comet',
            'peak_time': self._to_local_iso(Time(perihelion_date)),
            'start_time': self._to_local_iso(Time(visibility_start)),
            'end_time': self._to_local_iso(Time(visibility_end)),
            'perihelion_date': perihelion_date.isoformat(),
            'magnitude': magnitude,
            'visibility': visibility_type,
            'equipment_needed': equipment,
            'importance': self._rate_comet_importance(magnitude) if magnitude is not None else 'low',
            'raw_data': {
                'comet': comet_name,
                'perihelion': perihelion_date.isoformat(),
                'magnitude': magnitude,
                'source': source,
            },
        }

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
