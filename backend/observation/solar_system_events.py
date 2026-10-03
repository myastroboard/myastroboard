"""
Solar System Events Service for MyAstroBoard

Calculates solar system phenomena:
- Meteor Showers - peak times and radiant positions
- Comet Appearances - perihelion passages or brightest dates
- Asteroid Occultations - when an asteroid passes in front of a star

Uses a curated database of known events for accuracy.
Provides detailed visibility information for each event.
"""

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from astropy import units as u
from astropy.coordinates import ICRS, AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from utils import distant_epoch_precision_warnings_muted, parse_iso_to_utc
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger

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
        self,
        latitude: float,
        longitude: float,
        elevation: float = 0,
        timezone: str = "UTC",
        language: str = "en",
        altitude_constraint_min: float = 30.0,
        airmass_constraint: float = 2.0,
    ):
        """
        Initialize solar system events service.

        Args:
            latitude: Observer latitude in degrees
            longitude: Observer longitude in degrees
            elevation: Observer elevation in meters (default 0)
            timezone: IANA timezone string (default UTC)
            language: Language code for translations (default 'en')
            altitude_constraint_min: SkyTonight altitude floor in degrees, used only to flag
                comet events the configured site can never actually see (default 30)
            airmass_constraint: SkyTonight airmass ceiling, same purpose (default 2)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.timezone = ZoneInfo(timezone)
        self.language = language
        self.i18n = I18nManager(language)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation * u.m)
        # Same effective floor as the SkyTonight observability calculator (see
        # skytonight_calculator._compute_target_result): the stricter of the
        # configured altitude minimum and the altitude implied by the airmass
        # constraint (airmass = 1 / sin(altitude)).
        self.effective_altitude_min = altitude_constraint_min
        if airmass_constraint >= 1.0:
            alt_from_airmass = math.degrees(math.asin(min(1.0, 1.0 / airmass_constraint)))
            self.effective_altitude_min = max(altitude_constraint_min, alt_from_airmass)
        # Determine hemisphere
        self.hemisphere = 'Northern' if latitude >= 0 else 'Southern'

    def get_solar_system_events(self, days_ahead: int = 365) -> list[dict[str, Any]]:
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
    def _shower_activity_window(peak_date: datetime, shower_data: dict[str, Any]):
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

    def _find_meteor_shower_peaks(self, start_date: date, days_ahead: int) -> list[dict[str, Any]]:
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

    def _find_comet_visibility_windows(self, start_date: date, days_ahead: int) -> list[dict[str, Any]]:
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

        events: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                event = self._build_comet_event(candidate, start_date, end_date, source)
                if event is not None:
                    events.append(event)
            except Exception as e:
                logger.debug(f"Error calculating comet visibility for {candidate.get('name')}: {e}")

        return events

    def _dataset_comet_candidates(self) -> list[dict[str, Any]]:
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

        candidates: list[dict[str, Any]] = []
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
            target_id = target.get('target_id') if is_dict else getattr(target, 'target_id', None)
            candidates.append(
                {
                    'name': str(name or 'Comet'),
                    'perihelion': perihelion,
                    'magnitude': float(magnitude),
                    'equipment': None,
                    'orbital_elements': self._extract_orbital_elements(metadata),
                    'target_id': str(target_id) if target_id else None,
                }
            )
        return candidates

    @staticmethod
    def _extract_orbital_elements(metadata: dict[str, Any]) -> dict[str, Any] | None:
        """Pull the raw MPC orbital elements out of a comet's dataset metadata.

        Returns None when any element is missing or unparseable (e.g. curated
        fallback comets, which only carry a name/magnitude/perihelion date), so
        the caller can fall back to the simpler perihelion + absolute-magnitude
        estimate.
        """
        try:
            return {
                'q': float(metadata['q']),
                'e': float(metadata['e']),
                'omega': float(metadata['omega']),
                'Omega': float(metadata['Omega']),
                'inclination': float(metadata['inclination']),
                'perihelion_year': int(metadata['perihelion_year']),
                'perihelion_month': int(metadata['perihelion_month']),
                'perihelion_day': float(metadata['perihelion_day']),
                'slope': float(metadata['slope']),
            }
        except KeyError, TypeError, ValueError:
            return None

    def _curated_comet_candidates(self) -> list[dict[str, Any]]:
        """Fallback candidates from the small hardcoded NOTABLE_COMETS list."""
        candidates: list[dict[str, Any]] = []
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
            except KeyError, ValueError:
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
    def _parse_perihelion(value: Any) -> datetime | None:
        """Parse a 'YYYY-MM-DD' perihelion date into a UTC datetime at noon."""
        if not value:
            return None
        try:
            parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError, TypeError:
            return None
        return parsed.replace(hour=12, tzinfo=ZoneInfo("UTC"))

    @staticmethod
    def _equipment_label(magnitude: float | None) -> str:
        """Map a comet's apparent magnitude (absolute magnitude as a fallback) to a rough equipment hint."""
        if magnitude is None:
            return 'telescope'
        if magnitude <= 6.0:
            return 'naked_eye_possible'
        if magnitude <= 9.0:
            return 'binoculars'
        return 'telescope'

    def _equipment_display_label(self, equipment: str) -> str:
        """Translate an internal equipment key (e.g. 'naked_eye_possible') for display."""
        return self.i18n.t(f'events_api.solar_system.visibility_{equipment}')

    @staticmethod
    def _apparent_magnitude(abs_mag: float, slope: float, r_au: float, delta_au: float) -> float | None:
        """Standard MPC comet brightness law: m = H + 5*log10(delta) + 2.5*n*log10(r)."""
        if r_au <= 0 or delta_au <= 0:
            return None
        return abs_mag + 5.0 * math.log10(delta_au) + 2.5 * slope * math.log10(r_au)

    def _compute_true_brightness_peak(
        self, candidate: dict[str, Any], visibility_start: datetime, visibility_end: datetime
    ) -> tuple[datetime, float, float] | None:
        """Find the day of maximum apparent brightness within a comet's visibility window.

        Perihelion (closest approach to the Sun) and the day a comet is
        actually brightest can differ by a day or two once the Earth's
        distance is factored in, which matters for anyone timing a telescope
        session around the "peak". Samples daily across the window using the
        same Keplerian propagation as the SkyTonight comet dataset. Also
        tracks the best (highest) transit altitude reached at the configured
        site over the whole window, using the closed-form upper-culmination
        altitude (90 - |latitude - declination|), so the caller can flag
        comets that never clear the site's observability floor even though
        they are otherwise a notable event. Returns None when orbital
        elements are unavailable (e.g. curated fallback comets) or
        propagation fails, so the caller can fall back to perihelion +
        absolute magnitude.
        """
        elements = candidate.get('orbital_elements')
        abs_mag = candidate.get('magnitude')
        if not elements or abs_mag is None:
            return None

        try:
            from skytonight.skytonight_comets import _comet_ra_dec, _get_earth_heliocentric
        except Exception:
            return None

        best_date: datetime | None = None
        best_magnitude: float | None = None
        max_transit_altitude: float | None = None
        total_days = max(0, (visibility_end - visibility_start).days)

        for offset in range(total_days + 1):
            sample_dt = visibility_start + timedelta(days=offset)
            try:
                earth_helio = _get_earth_heliocentric(sample_dt)
                _, dec_deg, r_au, delta_au = _comet_ra_dec(
                    elements['q'],
                    elements['e'],
                    elements['omega'],
                    elements['Omega'],
                    elements['inclination'],
                    elements['perihelion_year'],
                    elements['perihelion_month'],
                    elements['perihelion_day'],
                    sample_dt,
                    earth_helio,
                )
            except Exception:
                continue
            if r_au is None or delta_au is None:
                continue
            if dec_deg is not None:
                transit_altitude = 90.0 - abs(self.latitude - dec_deg)
                if max_transit_altitude is None or transit_altitude > max_transit_altitude:
                    max_transit_altitude = transit_altitude
            magnitude = self._apparent_magnitude(abs_mag, elements['slope'], r_au, delta_au)
            if magnitude is None:
                continue
            if best_magnitude is None or magnitude < best_magnitude:
                best_magnitude = magnitude
                best_date = sample_dt

        if best_date is None or best_magnitude is None or max_transit_altitude is None:
            return None
        return best_date, round(best_magnitude, 1), max_transit_altitude

    def _build_comet_event(
        self, candidate: dict[str, Any], start_date: date, end_date: date, source: str
    ) -> dict[str, Any] | None:
        """Build one comet event dict when its ±30-day window overlaps the search range."""
        perihelion_date: datetime = candidate['perihelion']
        magnitude = candidate.get('magnitude')

        # Comets are typically visible within ~30 days of perihelion
        visibility_start = perihelion_date - timedelta(days=30)
        visibility_end = perihelion_date + timedelta(days=30)
        if not (visibility_start.date() <= end_date and visibility_end.date() >= start_date):
            return None

        peak_date = perihelion_date
        # Unknown (no orbital elements to check) defaults to "not flagged" rather than
        # assuming it's out of reach - we simply can't tell for curated fallback comets.
        altitude_limited = False
        brightness_peak = self._compute_true_brightness_peak(candidate, visibility_start, visibility_end)
        if brightness_peak is not None:
            peak_date, magnitude, max_transit_altitude = brightness_peak
            altitude_limited = max_transit_altitude < self.effective_altitude_min

        comet_name = candidate['name']
        equipment = candidate.get('equipment') or self._equipment_label(magnitude)
        visibility_type = self._estimate_comet_visibility(magnitude) if magnitude is not None else False

        title = self.i18n.t('events_api.solar_system.comet_title', comet_name=comet_name)
        description = self.i18n.t(
            'events_api.solar_system.comet_description',
            magnitude=magnitude if magnitude is not None else '—',
            visibility=self._equipment_display_label(equipment),
        )

        return {
            'event_type': 'Comet Appearance',
            'title': title,
            'description': description,
            'icon_class': 'bi bi-comet',
            'peak_time': self._to_local_iso(Time(peak_date)),
            'start_time': self._to_local_iso(Time(visibility_start)),
            'end_time': self._to_local_iso(Time(visibility_end)),
            'perihelion_date': perihelion_date.isoformat(),
            'magnitude': magnitude,
            'visibility': visibility_type,
            'equipment_needed': equipment,
            'altitude_limited': altitude_limited,
            'target_id': candidate.get('target_id'),
            'importance': self._rate_comet_importance(magnitude) if magnitude is not None else 'low',
            'raw_data': {
                'comet': comet_name,
                'perihelion': perihelion_date.isoformat(),
                'magnitude': magnitude,
                'source': source,
            },
        }

    def _find_asteroid_occultations(self, start_date: date, days_ahead: int) -> list[dict[str, Any]]:
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
        """Check if a meteor shower radiant is visible from the observer location.

        Peaks are checked up to a year ahead (see ``_find_meteor_shower_peaks``),
        which can land past the ~1-year IERS Earth-orientation table coverage.
        The resulting precision warnings are muted the same way as the eclipse
        services - see ``distant_epoch_precision_warnings_muted`` for why that's
        safe here too.
        """
        try:
            radiant = SkyCoord(ra=radiant_ra * u.deg, dec=radiant_dec * u.deg, frame=ICRS)
            with distant_epoch_precision_warnings_muted():
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
