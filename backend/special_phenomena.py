"""
Special Phenomena Service for MyAstroBoard

Calculates special astronomical phenomena:
- Equinoxes and Solstices - start of seasons
- Zodiacal Light Visibility Windows - faint diffuse light from interplanetary dust
- Ecliptic and Galactic Alignments - e.g., Milky Way core visibility

Uses Astropy for accurate astronomical calculations.
All calculations account for observer location and timezone.
"""

from datetime import datetime, timedelta, date as date_type
from typing import List, Dict, Any
from zoneinfo import ZoneInfo
from logging_config import get_logger
from i18n_utils import I18nManager

from astropy.coordinates import (
    EarthLocation,
    AltAz,
    get_body,
    get_sun,
    SkyCoord,
    ICRS,
)
from astropy.time import Time
from astropy import units as u
import numpy as np

logger = get_logger(__name__)


class SpecialPhenomenaService:
    """
    Calculates special astronomical phenomena for a given location.
    Provides equinox, solstice, zodiacal light, and alignment information.
    """

    def __init__(self, latitude: float, longitude: float, elevation: float = 0, timezone: str = "UTC", language: str = "en"):
        """
        Initialize special phenomena service.
        
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
        self.timezone = timezone
        self.language = language
        self.i18n = I18nManager(language)
        self.location = EarthLocation(
            lat=latitude * u.deg,
            lon=longitude * u.deg,
            height=elevation * u.m
        )

    def _t(self, key: str, fallback: str, **kwargs: Any) -> str:
        """Translate key with fallback text when translation is unavailable."""
        translated = self.i18n.t(key, **kwargs)
        if translated and translated != key:
            return translated

        if kwargs:
            try:
                return fallback.format(**kwargs)
            except Exception:
                return fallback

        return fallback

    def get_special_phenomena(self, days_ahead: int = 365) -> List[Dict[str, Any]]:
        """
        Get all special phenomena for the next N days.
        
        Args:
            days_ahead: Number of days to calculate ahead (default 365)
            
        Returns:
            List of special phenomena events, sorted by date
        """
        events = []
        now_utc = datetime.now(tz=ZoneInfo("UTC"))
        start_date = Time(now_utc)
        end_date = Time(now_utc + timedelta(days=days_ahead))

        try:
            # Equinoxes and Solstices
            seasonal = self._find_seasonal_events(start_date, end_date)
            events.extend(seasonal)

            # Zodiacal Light Windows
            zodiacal = self._find_zodiacal_light_windows(start_date, end_date)
            events.extend(zodiacal)

            # Milky Way Core Visibility
            milky_way = self._find_milky_way_core_visibility(start_date, end_date)
            events.extend(milky_way)

        except Exception as e:
            logger.error(f"Error calculating special phenomena: {e}")
            return []

        # Sort by time
        events.sort(key=lambda x: x.get('peak_time', x.get('start_time')))
        
        return events

    def _find_seasonal_events(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """
        Find equinoxes and solstices.
        These are the four points of the Earth's orbit where declination of the Sun is extremal.
        """
        events = []
        current_year = start_date.to_datetime(timezone=ZoneInfo(self.timezone)).year  # type: ignore
        years_to_check = [current_year, current_year + 1]
        
        for year in years_to_check:
            try:
                # Spring Equinox (March ~20-21)
                spring_eq = self._approximate_equinox(year, 'spring')
                if float(start_date.jd) <= float(spring_eq.jd) < float(end_date.jd):  # type: ignore
                    spring_eq_refined = self._refine_equinox_time(spring_eq, 'spring')
                    events.append({
                        'event_type': 'Equinox',
                        'title': self._t(
                            'events_api.special_phenomena.spring_equinox_title',
                            'Vernal Equinox (Spring)'
                        ),
                        'description': self._t(
                            'events_api.special_phenomena.spring_equinox_description',
                            'First day of spring. Equal day and night length. Sun directly above equator.'
                        ),
                        'icon_class': 'bi bi-sunrise',
                        'peak_time': self._to_local_iso(spring_eq_refined),
                        'season_start': True,
                        'hemisphere': 'Northern',
                        'visibility': True,
                        'importance': 'high',
                        'raw_data': {
                            'event': 'spring_equinox',
                            'year': year,
                            'date': self._to_local_iso(spring_eq_refined),
                        }
                    })
                
                # Summer Solstice (June ~20-21)
                summer_sol = self._approximate_solstice(year, 'summer')
                if float(start_date.jd) <= float(summer_sol.jd) < float(end_date.jd):  # type: ignore
                    summer_sol_refined = self._refine_solstice_time(summer_sol, 'summer')
                    events.append({
                        'event_type': 'Solstice',
                        'title': self._t(
                            'events_api.special_phenomena.summer_solstice_title',
                            'Summer Solstice'
                        ),
                        'description': self._t(
                            'events_api.special_phenomena.summer_solstice_description',
                            'First day of summer. Longest day of the year in Northern Hemisphere.'
                        ),
                        'icon_class': 'bi bi-sun',
                        'peak_time': self._to_local_iso(summer_sol_refined),
                        'season_start': True,
                        'hemisphere': 'Northern',
                        'visibility': True,
                        'importance': 'high',
                        'raw_data': {
                            'event': 'summer_solstice',
                            'year': year,
                            'date': self._to_local_iso(summer_sol_refined),
                        }
                    })
                
                # Autumn Equinox (September ~22-23)
                autumn_eq = self._approximate_equinox(year, 'autumn')
                if float(start_date.jd) <= float(autumn_eq.jd) < float(end_date.jd):  # type: ignore
                    autumn_eq_refined = self._refine_equinox_time(autumn_eq, 'autumn')
                    events.append({
                        'event_type': 'Equinox',
                        'title': self._t(
                            'events_api.special_phenomena.autumn_equinox_title',
                            'Autumnal Equinox (Fall)'
                        ),
                        'description': self._t(
                            'events_api.special_phenomena.autumn_equinox_description',
                            'First day of autumn. Equal day and night length. Sun directly above equator.'
                        ),
                        'icon_class': 'bi bi-sunset',
                        'peak_time': self._to_local_iso(autumn_eq_refined),
                        'season_start': True,
                        'hemisphere': 'Northern',
                        'visibility': True,
                        'importance': 'high',
                        'raw_data': {
                            'event': 'autumn_equinox',
                            'year': year,
                            'date': self._to_local_iso(autumn_eq_refined),
                        }
                    })
                
                # Winter Solstice (December ~21-22)
                winter_sol = self._approximate_solstice(year, 'winter')
                if float(start_date.jd) <= float(winter_sol.jd) < float(end_date.jd):  # type: ignore
                    winter_sol_refined = self._refine_solstice_time(winter_sol, 'winter')
                    events.append({
                        'event_type': 'Solstice',
                        'title': self._t(
                            'events_api.special_phenomena.winter_solstice_title',
                            'Winter Solstice'
                        ),
                        'description': self._t(
                            'events_api.special_phenomena.winter_solstice_description',
                            'First day of winter. Shortest day of the year in Northern Hemisphere.'
                        ),
                        'icon_class': 'bi bi-snow',
                        'peak_time': self._to_local_iso(winter_sol_refined),
                        'season_start': True,
                        'hemisphere': 'Northern',
                        'visibility': True,
                        'importance': 'high',
                        'raw_data': {
                            'event': 'winter_solstice',
                            'year': year,
                            'date': self._to_local_iso(winter_sol_refined),
                        }
                    })
            
            except Exception as e:
                logger.debug(f"Error calculating seasonal events for {year}: {e}")
        
        return events

    def _approximate_equinox(self, year: int, season: str) -> Time:
        """Get approximate equinox time for the given year and season."""
        # Approximate dates for equinoxes (UTC)
        if season == 'spring':
            return Time(f"{year}-03-20T12:00:00", format='isot', scale='utc', location=self.location)
        elif season == 'autumn':
            return Time(f"{year}-09-22T12:00:00", format='isot', scale='utc', location=self.location)
        return Time(f"{year}-03-20T12:00:00", format='isot', scale='utc', location=self.location)

    def _approximate_solstice(self, year: int, season: str) -> Time:
        """Get approximate solstice time for the given year and season."""
        # Approximate dates for solstices (UTC)
        if season == 'summer':
            return Time(f"{year}-06-21T12:00:00", format='isot', scale='utc', location=self.location)
        elif season == 'winter':
            return Time(f"{year}-12-21T12:00:00", format='isot', scale='utc', location=self.location)
        return Time(f"{year}-06-21T12:00:00", format='isot', scale='utc', location=self.location)

    def _refine_equinox_time(self, approx_time: Time, season: str) -> Time:
        """Refine equinox time by finding when Sun's declination is closest to 0."""
        # Check around approximate time
        step_hours = 1.0 * u.hour
        current = approx_time - (5 * u.day)  # Start 5 days before
        end_time = approx_time + (5 * u.day)
        best_time = current
        
        try:
            sun_current = get_sun(current)
            if sun_current is None:
                return best_time
            dec_val = sun_current.dec.degree  # type: ignore
            if isinstance(dec_val, (np.ndarray, complex)):
                min_declination = abs(float(np.real(np.atleast_1d(dec_val).flat[0])))
            else:
                min_declination = abs(float(dec_val))  # type: ignore
        except Exception:
            min_declination = 180.0
        
        while current < end_time:
            try:
                sun = get_sun(current)
                if sun is None:
                    current = current + step_hours
                    continue
                    
                dec_val = sun.dec.degree  # type: ignore
                if isinstance(dec_val, (np.ndarray, complex)):
                    declination = abs(float(np.real(np.atleast_1d(dec_val).flat[0])))
                else:
                    declination = abs(float(dec_val))  # type: ignore
                
                if declination < min_declination:
                    min_declination = declination
                    best_time = current
            except Exception:
                pass
            
            current = current + step_hours  # Step by 1 hour
        
        return best_time

    def _refine_solstice_time(self, approx_time: Time, season: str) -> Time:
        """Refine solstice time by finding when Sun's declination is at extremum."""
        # Check around approximate time
        step_hours = 1.0 * u.hour
        current = approx_time - (5 * u.day)  # Start 5 days before
        end_time = approx_time + (5 * u.day)
        best_time = current
        
        try:
            sun_current = get_sun(current)
            if sun_current is None:
                return best_time
            dec_val = sun_current.dec.degree  # type: ignore
            if isinstance(dec_val, (np.ndarray, complex)):
                max_declination = float(np.real(np.atleast_1d(dec_val).flat[0]))
            else:
                max_declination = float(dec_val)  # type: ignore
        except Exception:
            max_declination = 0.0
        
        target_max = (season == 'summer')
        
        while current < end_time:
            try:
                sun = get_sun(current)
                if sun is None:
                    current = current + step_hours
                    continue
                    
                dec_val = sun.dec.degree  # type: ignore
                if isinstance(dec_val, (np.ndarray, complex)):
                    declination = float(np.real(np.atleast_1d(dec_val).flat[0]))
                else:
                    declination = float(dec_val)  # type: ignore
                
                if target_max and declination > max_declination:
                    max_declination = declination
                    best_time = current
                elif not target_max and declination < max_declination:
                    max_declination = declination
                    best_time = current
            except Exception:
                pass
            
            current = current + step_hours  # Step by 1 hour
        
        return best_time

    def _find_zodiacal_light_windows(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """
        Find zodiacal light visibility windows.
        Zodiacal light is visible when:
        1. Sun is far below horizon (twilight to deep night)
        2. Ecliptic is high above horizon
        3. No moonlight interference
        
        Best viewed in spring (morning) and autumn (evening) from mid-Northern latitudes.
        """
        events = []
        current_time = start_date
        step_days = 1.0 * u.day
        
        # Zodiacal light is best in spring and autumn
        # Spring (March-May), Autumn (August-October)
        spring_start_month = 3
        spring_end_month = 5
        autumn_start_month = 8
        autumn_end_month = 10
        
        while current_time < end_date:
            try:
                dt = current_time.to_datetime(timezone=ZoneInfo(self.timezone))
                month = dt.month  # type: ignore
                
                # Check if we're in zodiacal light season
                is_spring = spring_start_month <= month <= spring_end_month
                is_autumn = autumn_start_month <= month <= autumn_end_month
                
                if is_spring or is_autumn:
                    # Check visibility conditions
                    sun = get_sun(current_time)
                    if sun is None:
                        current_time += step_days
                        continue
                        
                    sun_altaz = sun.transform_to(AltAz(obstime=current_time, location=self.location))
                    if sun_altaz is None:
                        current_time += step_days
                        continue
                    
                    # Sun must be below horizon (twilight or night)
                    alt_val = sun_altaz.alt.degree  # type: ignore
                    if isinstance(alt_val, (np.ndarray, complex)):
                        sun_alt = float(np.real(np.atleast_1d(alt_val).flat[0]))
                    else:
                        sun_alt = float(alt_val)  # type: ignore
                    
                    if sun_alt < -6:  # End of twilight
                        # Check if ecliptic is positioned well
                        ecliptic_alt = self._get_ecliptic_altitude(current_time)
                        
                        # Ecliptic should be reasonably high
                        if ecliptic_alt > 20:
                            # Check moon phase - no bright moon
                            moon = get_body('moon', current_time, self.location)
                            if moon is None:
                                current_time += step_days
                                continue
                                
                            moon_altaz = moon.transform_to(AltAz(obstime=current_time, location=self.location))
                            if moon_altaz is None:
                                current_time += step_days
                                continue
                            
                            # Moon either below horizon or in new moon phase
                            moon_alt_val = moon_altaz.alt.degree  # type: ignore
                            if isinstance(moon_alt_val, (np.ndarray, complex)):
                                moon_alt = float(np.real(np.atleast_1d(moon_alt_val).flat[0]))
                            else:
                                moon_alt = float(moon_alt_val)  # type: ignore
                            
                            is_moon_ok = moon_alt < 5  # Moon below horizon
                            
                            if is_moon_ok:
                                viewing_type = 'Evening' if is_spring else 'Morning'
                                viewing_type_localized = self._t(
                                    'events_api.special_phenomena.zodiacal_viewing_evening',
                                    'Evening'
                                ) if is_spring else self._t(
                                    'events_api.special_phenomena.zodiacal_viewing_morning',
                                    'Morning'
                                )
                                events.append({
                                    'event_type': 'Zodiacal Light Window',
                                    'title': self._t(
                                        'events_api.special_phenomena.zodiacal_light_title',
                                        'Zodiacal Light Visible ({viewing_type})',
                                        viewing_type=viewing_type_localized
                                    ),
                                    'description': self._t(
                                        'events_api.special_phenomena.zodiacal_light_description',
                                        'Faint cone of light from interplanetary dust visible during twilight. Best viewed in dark skies.'
                                    ),
                                    'icon_class': 'bi bi-stars',
                                    'peak_time': self._to_local_iso(current_time),
                                    'start_time': self._to_local_iso(current_time),
                                    'end_time': self._to_local_iso(current_time + (2 * u.hour)),  # 2-hour window
                                    'viewing_type': viewing_type,
                                    'season': 'spring' if is_spring else 'autumn',
                                    'ecliptic_altitude': ecliptic_alt,
                                    'visibility': True,
                                    'importance': 'medium',
                                    'raw_data': {
                                        'event': 'zodiacal_light',
                                        'viewing_window_hours': 2,
                                        'ecliptic_altitude': ecliptic_alt,
                                    }
                                })
            
            except Exception as e:
                logger.debug(f"Error in zodiacal light calculation: {e}")
            
            current_time = current_time + step_days
        
        return events

    def _find_milky_way_core_visibility(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """
        Find Milky Way core visibility windows.
        Core is visible when:
        1. Galactic center (Sagittarius region) is above horizon
        2. Sun is well below horizon (nautical twilight or darker)
        3. Moon is not bright / below horizon

        Season (Northern Hemisphere): May-September
        Season (Southern Hemisphere): November-March

        To avoid time-of-day bias the check is performed at 02:00 local time each night
        (deep into astronomical night for most latitudes). Results are deduplicated so
        only one event is emitted per 14-day window.
        """
        events = []
        tz = ZoneInfo(self.timezone)

        # Hemisphere-aware season months
        if self.latitude >= 0:
            mw_season_months = {5, 6, 7, 8, 9}       # Northern: May-Sep
        else:
            mw_season_months = {11, 12, 1, 2, 3}      # Southern: Nov-Mar

        # Galactic center coordinates (Sgr A* region)
        _galactic_center = SkyCoord(ra=266.417 * u.deg, dec=-29.008 * u.deg, frame=ICRS)

        # The GC barely clears the horizon from high latitudes; use a permissive threshold
        gc_min_altitude = 5.0   # degrees

        start_dt: datetime = start_date.to_datetime(timezone=tz)  # type: ignore[assignment]
        end_dt: datetime   = end_date.to_datetime(timezone=tz)    # type: ignore[assignment]

        current_date: date_type = start_dt.date()
        end_local_date: date_type = end_dt.date()

        last_event_date: date_type | None = None  # deduplication cursor

        while current_date <= end_local_date:
            try:
                if current_date.month not in mw_season_months:
                    current_date += timedelta(days=1)
                    continue

                # Check at 02:00 local time — representative deep-night hour
                check_dt = datetime(
                    current_date.year, current_date.month, current_date.day,
                    2, 0, 0, tzinfo=tz
                )
                check_time = Time(check_dt)

                # --- Sun must be below nautical twilight ---
                sun = get_sun(check_time)
                if sun is None:
                    current_date += timedelta(days=1)
                    continue

                sun_altaz = sun.transform_to(AltAz(obstime=check_time, location=self.location))
                sun_alt_val = sun_altaz.alt.degree  # type: ignore
                if isinstance(sun_alt_val, (np.ndarray, complex)):
                    sun_alt = float(np.real(np.atleast_1d(sun_alt_val).flat[0]))
                else:
                    sun_alt = float(sun_alt_val)  # type: ignore

                if sun_alt >= -12.0:
                    current_date += timedelta(days=1)
                    continue

                # --- Galactic center must be above the minimum altitude ---
                gc_altaz = _galactic_center.transform_to(AltAz(obstime=check_time, location=self.location))
                gc_alt_val = gc_altaz.alt.degree  # type: ignore
                if isinstance(gc_alt_val, (np.ndarray, complex)):
                    gc_altitude = float(np.real(np.atleast_1d(gc_alt_val).flat[0]))
                else:
                    gc_altitude = float(gc_alt_val)  # type: ignore

                if gc_altitude < gc_min_altitude:
                    current_date += timedelta(days=1)
                    continue

                # --- Moon must be below horizon ---
                moon = get_body('moon', check_time, self.location)
                if moon is None:
                    current_date += timedelta(days=1)
                    continue

                moon_altaz = moon.transform_to(AltAz(obstime=check_time, location=self.location))
                moon_alt_val = moon_altaz.alt.degree  # type: ignore
                if isinstance(moon_alt_val, (np.ndarray, complex)):
                    moon_alt = float(np.real(np.atleast_1d(moon_alt_val).flat[0]))
                else:
                    moon_alt = float(moon_alt_val)  # type: ignore

                if moon_alt >= 5.0:
                    current_date += timedelta(days=1)
                    continue

                # --- Conditions met — deduplicate to one event per 14-day window ---
                if last_event_date is not None and (current_date - last_event_date).days < 14:
                    current_date += timedelta(days=1)
                    continue

                # Score: weighted altitude (0-8) + dark-sky bonus (always 2 here, moon already filtered)
                score = round(min(10.0, (gc_altitude / 60.0) * 8.0 + 2.0), 1)

                title = self._t(
                    'events_api.special_phenomena.milky_way_title',
                    'Milky Way Core Visible'
                )
                description = self._t(
                    'events_api.special_phenomena.milky_way_description',
                    'Galactic center visible at {gc_altitude}° altitude. Excellent night for wide-field astrophotography.',
                    gc_altitude=f"{gc_altitude:.0f}"
                )

                events.append({
                    'event_type': 'Milky Way Core Visibility',
                    'title': title,
                    'description': description,
                    'icon_class': 'bi bi-stars',
                    'peak_time': self._to_local_iso(check_time),
                    'start_time': self._to_local_iso(check_time),
                    'end_time': self._to_local_iso(check_time + (5 * u.hour)),
                    'galactic_center_altitude': round(gc_altitude, 1),
                    'best_season': 'Summer' if self.latitude >= 0 else 'Winter',
                    'visibility': True,
                    'importance': 'high' if gc_altitude >= 20 else 'medium',
                    'score': score,
                    'raw_data': {
                        'event': 'milky_way_core',
                        'galactic_center_altitude': round(gc_altitude, 1),
                        'useful_window_hours': 5,
                    }
                })

                last_event_date = current_date

            except Exception as e:
                logger.debug(f"Error in Milky Way calculation for {current_date}: {e}")

            current_date += timedelta(days=1)

        return events

    def _get_ecliptic_altitude(self, time: Time) -> float:
        """Get altitude of ecliptic above horizon at given time."""
        try:
            # Ecliptic is the Sun's apparent path
            sun = get_sun(time)
            if sun is None:
                return 0.0
                
            ecliptic_altaz = sun.transform_to(AltAz(obstime=time, location=self.location))
            if ecliptic_altaz is None:
                return 0.0
                
            alt_val = ecliptic_altaz.alt.degree  # type: ignore
            if isinstance(alt_val, (np.ndarray, complex)):
                return float(np.real(np.atleast_1d(alt_val).flat[0]))
            else:
                return float(alt_val)  # type: ignore
        except Exception:
            return 0.0

    def _get_galactic_center_altitude(self, time: Time) -> float:
        """Get altitude of galactic center above horizon."""
        try:
            # Galactic center coordinates (Sagittarius region)
            # RA: ~17h45m, Dec: ~-29°
            from astropy.coordinates import ICRS, SkyCoord
            
            gc = SkyCoord(ra=266.41 * u.deg, dec=-29.00 * u.deg, frame=ICRS)
            gc_altaz = gc.transform_to(AltAz(obstime=time, location=self.location))
            
            alt_val = gc_altaz.alt.degree  # type: ignore
            if isinstance(alt_val, (np.ndarray, complex)):
                return float(np.real(np.atleast_1d(alt_val).flat[0]))
            else:
                return float(alt_val)  # type: ignore
        except Exception:
            return 0.0

    def _to_local_iso(self, time: Time) -> str:
        """Convert Astropy Time to configured local timezone ISO string with offset."""
        tz = ZoneInfo(self.timezone)
        dt = time.to_datetime(timezone=tz)
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)
