"""
Planetary Events Service for MyAstroBoard

Calculates and provides information about planetary events:
- Planetary Conjunctions - when two planets appear very close in the sky
- Planetary Oppositions - best visibility of outer planets (180° from Sun)
- Planetary Elongations - maximum angular distance from the Sun
- Retrograde Motion - apparent backward motion of planets

Uses Astropy and Skyfield for accurate astronomical calculations.
All calculations account for observer location and timezone.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
from zoneinfo import ZoneInfo
from logging_config import get_logger

from astropy.coordinates import (
    EarthLocation,
    AltAz,
    get_body,
)
from astropy.time import Time
from astropy import units as u
import numpy as np

logger = get_logger(__name__)

# Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune
PLANETS = {
    'Mercury': {'min_elong': 18, 'has_opposition': False},
    'Venus': {'min_elong': 46, 'has_opposition': False},
    'Mars': {'min_elong': 0, 'has_opposition': True},
    'Jupiter': {'min_elong': 0, 'has_opposition': True},
    'Saturn': {'min_elong': 0, 'has_opposition': True},
    'Uranus': {'min_elong': 0, 'has_opposition': True},
    'Neptune': {'min_elong': 0, 'has_opposition': True},
}



class PlanetaryEventsService:
    """
    Calculates planetary events for a given location.
    Provides conjunction, opposition, elongation, and retrograde motion data.
    """

    def __init__(self, latitude: float, longitude: float, elevation: float = 0, timezone: str = "UTC"):
        """
        Initialize planetary events service.

        Args:
            latitude: Observer latitude in degrees
            longitude: Observer longitude in degrees
            elevation: Observer elevation in meters (default 0)
            timezone: IANA timezone string (default UTC)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.timezone = ZoneInfo(timezone)
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation * u.m)

    def get_planetary_events(self, days_ahead: int = 365) -> List[Dict[str, Any]]:
        """
        Get all planetary events for the next N days.

        Args:
            days_ahead: Number of days to calculate ahead (default 365)

        Returns:
            List of planetary events, sorted by date
        """
        events = []
        now_utc = datetime.now(tz=ZoneInfo("UTC"))
        start_date = Time(now_utc)
        end_date = Time(now_utc + timedelta(days=days_ahead))

        # Pre-compute all planet + sun positions in 8 vectorized calls.
        # This replaces ~21,000 individual Astropy calls with 8 array calls.
        self._prefetch_coords(start_date, days_ahead)

        try:
            events.extend(self._find_conjunctions(start_date, end_date))
            events.extend(self._find_moon_conjunctions(start_date, days_ahead))
            events.extend(self._find_oppositions(start_date, end_date))
            events.extend(self._find_elongations(start_date, end_date))
            events.extend(self._find_retrograde_periods(start_date, end_date))
        except Exception as e:
            logger.error(f"Error calculating planetary events: {e}")
            return []

        events.sort(key=lambda x: x.get('peak_time', x.get('start_time')))
        return events

    def _prefetch_coords(self, start_date: Time, days_ahead: int, step_days: float = 1.0) -> None:
        """Pre-compute all planet + sun SkyCoord arrays in vectorized Astropy calls.
        Results stored as self._t_arr and self._coords for use by the _find_* methods.
        """
        n = int(days_ahead / step_days) + 1
        t_arr = start_date + np.arange(n) * step_days * u.day
        self._t_arr = t_arr
        self._coords: Dict[str, Any] = {}
        for body in list(PLANETS.keys()) + ['sun']:
            self._coords[body] = get_body(body, t_arr, self.location)

    @staticmethod
    def _find_runs(boolean_arr: np.ndarray):
        """Return (start, end) index pairs for all contiguous True runs (end is exclusive)."""
        padded = np.concatenate([[False], boolean_arr, [False]])
        transitions = np.diff(padded.astype(int))
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]
        return list(zip(starts, ends))

    def _find_conjunctions(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """Find conjunctions using pre-computed vectorized positions."""
        coords = getattr(self, '_coords', None)
        t_arr = getattr(self, '_t_arr', None)
        if coords is None or t_arr is None:
            return []

        events = []
        planet_list = list(PLANETS.keys())
        n = len(t_arr)

        for i, planet1 in enumerate(planet_list):
            for planet2 in planet_list[i + 1 :]:
                try:
                    seps = np.asarray(coords[planet1].separation(coords[planet2]).degree)
                    for s, e in self._find_runs(seps < 5.0):
                        min_idx = s + int(np.argmin(seps[s:e]))
                        min_sep = float(seps[min_idx])
                        peak_time = t_arr[min_idx]
                        visible = self._is_event_visible(planet1, planet2, peak_time)
                        events.append(
                            {
                                'event_type': 'Planetary Conjunction',
                                'title': f'{planet1} - {planet2} Conjunction',
                                'description': f'{planet1} and {planet2} appear very close in the sky',
                                'peak_time': self._to_local_iso(peak_time),
                                'start_time': self._to_local_iso(t_arr[s]),
                                'end_time': self._to_local_iso(t_arr[min(e, n - 1)]),
                                'min_separation_degrees': min_sep,
                                'visibility': visible,
                                'importance': self._rate_importance(planet1, planet2, min_sep) if visible else 'low',
                                'raw_data': {
                                    'planet1': planet1,
                                    'planet2': planet2,
                                    'separation_degrees': min_sep,
                                },
                            }
                        )
                except Exception as ex:
                    logger.debug(f"Error finding conjunction {planet1}-{planet2}: {ex}")

        return events

    def _find_moon_conjunctions(self, start_date: Time, days_ahead: int) -> List[Dict[str, Any]]:
        """Find Moon-planet conjunctions using 6-hour sampling (Moon moves ~13°/day)."""
        step_days = 0.25  # 6-hour steps — coarser steps miss the minimum at ~3° threshold
        n = int(days_ahead / step_days) + 1
        t_arr = start_date + np.arange(n) * step_days * u.day

        try:
            moon_coords = get_body('moon', t_arr, self.location)
        except Exception as e:
            logger.warning(f"Failed to fetch moon positions: {e}")
            return []

        events = []
        threshold_deg = 3.0

        for planet in PLANETS.keys():
            try:
                planet_coords = get_body(planet, t_arr, self.location)
                seps = np.asarray(moon_coords.separation(planet_coords).degree)
                for s, e in self._find_runs(seps < threshold_deg):
                    min_idx = s + int(np.argmin(seps[s:e]))
                    min_sep = float(seps[min_idx])
                    peak_time = t_arr[min_idx]
                    visible = self._is_event_visible('moon', planet, peak_time)  # type: ignore[arg-type]
                    events.append(
                        {
                            'event_type': 'Moon Conjunction',
                            'title': f'Moon - {planet} Conjunction',
                            'description': (
                                f'The Moon passes within {min_sep:.1f}° of {planet}'
                            ),
                            'peak_time': self._to_local_iso(peak_time),  # type: ignore[arg-type]
                            'start_time': self._to_local_iso(t_arr[s]),  # type: ignore[arg-type]
                            'end_time': self._to_local_iso(t_arr[min(e, n - 1)]),  # type: ignore[arg-type]
                            'min_separation_degrees': min_sep,
                            'visibility': visible,
                            'importance': 'high' if visible else 'low',
                            'raw_data': {
                                'planet1': 'Moon',
                                'planet2': planet,
                                'separation_degrees': min_sep,
                            },
                        }
                    )
            except Exception as ex:
                logger.debug(f"Error finding Moon-{planet} conjunction: {ex}")

        return events

    def _find_oppositions(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """Find oppositions using pre-computed vectorized positions."""
        coords = getattr(self, '_coords', None)
        t_arr = getattr(self, '_t_arr', None)
        if coords is None or t_arr is None:
            return []

        events = []
        n = len(t_arr)
        outer_planets = ['Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune']

        for planet in outer_planets:
            try:
                seps = np.asarray(coords[planet].separation(coords['sun']).degree)
                in_opposition = (seps >= 170) & (seps <= 190)
                for s, e in self._find_runs(in_opposition):
                    window = seps[s:e]
                    peak_idx = s + int(np.argmin(np.abs(window - 180.0)))
                    peak_time = t_arr[peak_idx]
                    events.append(
                        {
                            'event_type': 'Planetary Opposition',
                            'title': f'{planet} at Opposition',
                            'description': f'{planet} is at opposition (best visibility). Optimal for observation.',
                            'peak_time': self._to_local_iso(peak_time),
                            'start_time': self._to_local_iso(t_arr[s]),
                            'end_time': self._to_local_iso(t_arr[min(e, n - 1)]),
                            'elongation_degrees': 180.0,
                            'visibility': True,
                            'importance': 'high',
                            'raw_data': {
                                'planet': planet,
                                'elongation': 180.0,
                                'best_viewing_time': self._to_local_iso(peak_time),
                            },
                        }
                    )
            except Exception as ex:
                logger.debug(f"Error finding opposition for {planet}: {ex}")

        return events

    def _find_elongations(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """Find maximum elongations using pre-computed vectorized positions."""
        coords = getattr(self, '_coords', None)
        t_arr = getattr(self, '_t_arr', None)
        if coords is None or t_arr is None:
            return []

        events = []
        inner_planets = ['Mercury', 'Venus']

        for planet in inner_planets:
            try:
                elong = np.asarray(coords[planet].separation(coords['sun']).degree)
                min_elong = PLANETS[planet]['min_elong']
                # Local maxima: higher than both neighbours, and above visibility threshold
                peak_mask = (elong[1:-1] > elong[:-2]) & (elong[1:-1] > elong[2:]) & (elong[1:-1] >= min_elong)
                for raw_idx in np.where(peak_mask)[0]:
                    peak_idx = int(raw_idx) + 1  # offset from slicing
                    max_elong_val = float(elong[peak_idx])
                    peak_time = t_arr[peak_idx]
                    events.append(
                        {
                            'event_type': 'Planetary Elongation',
                            'title': f'{planet} at Maximum Elongation',
                            'description': (
                                f'{planet} reaches maximum elongation ({max_elong_val:.1f}°). Best viewing time.'
                            ),
                            'peak_time': self._to_local_iso(peak_time),
                            'elongation_degrees': max_elong_val,
                            'visibility': True,
                            'importance': 'medium',
                            'raw_data': {
                                'planet': planet,
                                'elongation': max_elong_val,
                                'occurs_at': self._to_local_iso(peak_time),
                            },
                        }
                    )
            except Exception as ex:
                logger.debug(f"Error finding elongation for {planet}: {ex}")

        return events

    def _find_retrograde_periods(self, start_date: Time, end_date: Time) -> List[Dict[str, Any]]:
        """Find retrograde motion using pre-computed vectorized RA arrays."""
        coords = getattr(self, '_coords', None)
        t_arr = getattr(self, '_t_arr', None)
        if coords is None or t_arr is None:
            return []

        events = []
        n = len(t_arr)

        for planet in list(PLANETS.keys()):
            try:
                ra = np.asarray(coords[planet].ra.degree)
                dra = np.diff(ra)
                dra[dra > 180] -= 360
                dra[dra < -180] += 360
                is_retrograde = dra < -0.05
                for s, e in self._find_runs(is_retrograde):
                    duration_days = float(e - s)  # 1-day steps
                    start_time = t_arr[s]
                    end_time = t_arr[min(e, n - 1)]
                    events.append(
                        {
                            'event_type': 'Planetary Retrograde',
                            'title': f'{planet} Retrograde Motion',
                            'description': f'{planet} appears to move backward for ~{duration_days:.0f} days.',
                            'start_time': self._to_local_iso(start_time),
                            'end_time': self._to_local_iso(end_time),
                            'duration_days': duration_days,
                            'visibility': self._is_planet_visible(planet, start_time),
                            'importance': 'medium',
                            'raw_data': {
                                'planet': planet,
                                'duration_days': duration_days,
                            },
                        }
                    )
            except Exception as ex:
                logger.debug(f"Error finding retrograde for {planet}: {ex}")

        return events

    def _angular_separation(self, planet1: str, planet2: str, time: Time) -> float:
        """Calculate angular separation between two planets in degrees."""
        try:
            p1 = get_body(planet1, time, self.location)
            p2 = get_body(planet2, time, self.location)

            sep = p1.separation(p2)
            # Handle both scalar and array returns from Astropy
            sep_val = sep.degree
            if isinstance(sep_val, np.ndarray):
                return float(np.real(sep_val.flat[0]))
            elif isinstance(sep_val, complex):
                return float(np.real(sep_val))
            else:
                return float(np.real(sep_val))  # type: ignore
        except Exception as e:
            logger.debug(f"Error calculating separation {planet1}-{planet2}: {e}")
            return float('inf')

    def _get_elongation(self, planet: str, time: Time) -> float:
        """Get angular distance from Sun to planet (elongation) in degrees."""
        try:
            planet_obj = get_body(planet, time, self.location)
            sun_obj = get_body('sun', time, self.location)

            elongation = planet_obj.separation(sun_obj)
            # Handle both scalar and array returns from Astropy
            elong_val = elongation.degree
            if isinstance(elong_val, np.ndarray):
                return float(np.real(elong_val.flat[0]))
            elif isinstance(elong_val, complex):
                return float(np.real(elong_val))
            else:
                return float(np.real(elong_val))  # type: ignore
        except Exception as e:
            logger.debug(f"Error calculating elongation for {planet}: {e}")
            return 0.0

    def _is_event_visible(self, planet1: str, planet2: str, time: Time) -> bool:
        """Check if a conjunction is visible from the location."""
        try:
            p1 = get_body(planet1, time, self.location)
            p2 = get_body(planet2, time, self.location)

            if p1 is None or p2 is None:
                return False

            altaz_p1 = p1.transform_to(AltAz(obstime=time, location=self.location))
            altaz_p2 = p2.transform_to(AltAz(obstime=time, location=self.location))

            if altaz_p1 is None or altaz_p2 is None:
                return False

            # Both planets must be above horizon for conjunction to be visible
            alt1_val = altaz_p1.alt.degree  # type: ignore
            alt2_val = altaz_p2.alt.degree  # type: ignore

            if isinstance(alt1_val, np.ndarray):
                alt1 = float(np.real(alt1_val.flat[0]))
            elif isinstance(alt1_val, complex):
                alt1 = float(np.real(alt1_val))
            else:
                alt1 = float(np.real(alt1_val))  # type: ignore

            if isinstance(alt2_val, np.ndarray):
                alt2 = float(np.real(alt2_val.flat[0]))
            elif isinstance(alt2_val, complex):
                alt2 = float(np.real(alt2_val))
            else:
                alt2 = float(np.real(alt2_val))  # type: ignore

            return alt1 > 5 and alt2 > 5
        except Exception:
            return False

    def _is_planet_visible(self, planet: str, time: Time) -> bool:
        """Check if a planet is visible from the location."""
        try:
            planet_obj = get_body(planet, time, self.location)
            if planet_obj is None:
                return False

            altaz = planet_obj.transform_to(AltAz(obstime=time, location=self.location))
            if altaz is None:
                return False

            # Planet is visible if above horizon and not too close to Sun
            sun_obj = get_body('sun', time, self.location)
            if sun_obj is None:
                return False

            # Handle both scalar and array returns
            elong_val = planet_obj.separation(sun_obj).degree
            if isinstance(elong_val, np.ndarray):
                elongation = float(np.real(elong_val.flat[0]))
            elif isinstance(elong_val, complex):
                elongation = float(np.real(elong_val))
            else:
                elongation = float(np.real(elong_val))  # type: ignore

            alt_val = altaz.alt.degree  # type: ignore
            if isinstance(alt_val, np.ndarray):
                altitude = float(np.real(alt_val.flat[0]))
            elif isinstance(alt_val, complex):
                altitude = float(np.real(alt_val))
            else:
                altitude = float(np.real(alt_val))  # type: ignore

            return altitude > 5 and elongation > 10
        except Exception:
            return False

    def _to_local_iso(self, time: Time) -> str:
        """Convert Astropy Time to configured local timezone ISO string with offset."""
        dt = time.to_datetime(timezone=self.timezone)
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)

    def _rate_importance(self, planet1: str, planet2: str, separation: float) -> str:
        """Rate the importance of a conjunction based on brightness and separation."""
        # Major planets: Jupiter and Saturn
        major_planets = {'Jupiter', 'Saturn'}
        is_major = (planet1 in major_planets) or (planet2 in major_planets)

        # Closer conjunctions are more impressive
        if separation < 0.5:
            return 'high' if is_major else 'medium'
        elif separation < 2:
            return 'medium'
        else:
            return 'low'
