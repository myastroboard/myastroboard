"""
Sidereal Time Service for MyAstroBoard

Provides sidereal time calculations useful for:
- Equatorial mount tracking
- Star tracking and alignment
- Telescope pointing calculations
- Right ascension based observations

Sidereal time is the hour angle of the vernal equinox,
used to determine the positions of celestial objects.
"""

from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from utils.logging_config import get_logger

from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz
from astropy import units as u
import numpy as np

logger = get_logger(__name__)

# Ratio of the mean solar day to the mean sidereal day: local sidereal time
# advances this many sidereal hours per solar hour (1 solar hour = 1.00273790935
# sidereal hours). Used to convert a sidereal-hour offset into elapsed civil time.
SIDEREAL_TO_SOLAR_RATIO = 1.00273790935


class SiderealTimeService:
    """
    Provides sidereal time calculations for astronomical observations.
    Useful for equatorial mount alignment and star tracking.
    """

    def __init__(self, latitude: float, longitude: float, elevation: float = 0, timezone: str = "UTC"):
        """
        Initialize sidereal time service.

        Args:
            latitude: Observer latitude in degrees
            longitude: Observer longitude in degrees
            elevation: Observer elevation in meters (default 0)
            timezone: IANA timezone string (default UTC)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.timezone = timezone
        self.location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=elevation * u.m)

    def get_current_sidereal_info(self) -> Dict[str, Any]:
        """
        Get current sidereal time and related information.

        Returns:
            Dictionary with current sidereal time, LST, and other useful data
        """
        try:
            # Get current UTC time
            now_utc = Time.now()

            return self._calculate_sidereal_info(now_utc)
        except Exception as e:
            logger.error(f"Error getting current sidereal time: {e}")
            return {}

    def get_sidereal_info_for_time(self, target_datetime: datetime) -> Dict[str, Any]:
        """
        Get sidereal time information for a specific time.

        Args:
            target_datetime: Target datetime for calculation

        Returns:
            Dictionary with sidereal time information
        """
        try:
            time_obj = Time(target_datetime)
            return self._calculate_sidereal_info(time_obj)
        except Exception as e:
            logger.error(f"Error calculating sidereal time: {e}")
            return {}

    def get_hourly_sidereal_times(self, target_date: date, num_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get sidereal times for each hour of a given day.
        Useful for planning observations over a night.

        Args:
            target_date: Target date for calculation
            num_hours: Number of hourly data points (default 24 for full day)

        Returns:
            List of hourly sidereal time data
        """
        results = []

        try:
            # Start at beginning of day
            start_time = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

            for hour in range(num_hours):
                hour_time = start_time + timedelta(hours=hour)
                time_obj = Time(hour_time)

                info = self._calculate_sidereal_info(time_obj)
                info['hour'] = hour
                info['datetime_utc'] = hour_time.isoformat()
                results.append(info)

        except Exception as e:
            logger.error(f"Error calculating hourly sidereal times: {e}")

        return results

    def get_object_lst_for_transit(
        self, ra_degrees: float, target_date: date, dec_degrees: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Get the Local Sidereal Time when an object at a given RA will transit (cross meridian).
        Useful for planning observations of specific objects.

        Args:
            ra_degrees: Right Ascension of target object in degrees
            target_date: Date for which to calculate (local date)
            dec_degrees: Declination of target in degrees. Required to determine
                whether the object is circumpolar; when omitted the
                ``is_circumpolar`` field is reported as ``None`` (unknown).

        Returns:
            Dictionary with transit time and LST information
        """
        try:
            # RA in hours (RA ranges from 0-24 hours = 0-360 degrees)
            ra_hours = (ra_degrees / 360.0) * 24.0

            # Local Sidereal Time at transit equals the RA of the object
            lst_at_transit = ra_hours

            # Calculate Greenwich Sidereal Time and UTC time at transit
            # GST = LST - (longitude in hours, west negative)
            lon_hours = self.longitude / 15.0  # Convert degrees to hours
            gst_at_transit = lst_at_transit - lon_hours

            # Normalize to 0-24 range
            while gst_at_transit < 0:
                gst_at_transit += 24
            while gst_at_transit >= 24:
                gst_at_transit -= 24

            # Estimate UTC time (simplified)
            # More accurate calculation would use UT1 and actual Earth rotation angle
            start_of_day = datetime(
                target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=ZoneInfo("UTC")
            )
            time_obj = Time(start_of_day)
            daily_sidereal_info = self._calculate_sidereal_info(time_obj)
            lst_at_midnight = float(daily_sidereal_info['local_sidereal_time_hours'])

            # Calculate hours since midnight when transit occurs. The offset is in
            # sidereal hours; convert to elapsed civil (solar) time by dividing by the
            # sidereal-to-solar rate, otherwise the transit drifts up to ~4 min late.
            sidereal_offset = lst_at_transit - lst_at_midnight
            if sidereal_offset < 0:
                sidereal_offset += 24
            hours_offset = sidereal_offset / SIDEREAL_TO_SOLAR_RATIO

            transit_time = start_of_day + timedelta(hours=hours_offset)
            transit_time_obj = Time(transit_time)

            return {
                'target_ra_degrees': ra_degrees,
                'target_ra_hours': ra_hours,
                'local_sidereal_time_at_transit_hours': lst_at_transit,
                'transit_time_utc': transit_time_obj.iso,
                'transit_time_local': transit_time.isoformat(),
                'is_circumpolar': (self._is_circumpolar(dec_degrees) if dec_degrees is not None else None),
                'accuracy_note': 'Transit time is approximate; use more precise ephemeris for exact pointing',
            }

        except Exception as e:
            logger.error(f"Error calculating object transit time: {e}")
            return {}

    def _calculate_sidereal_info(self, time_obj: Time) -> Dict[str, Any]:
        """Calculate comprehensive sidereal time information."""
        try:
            # Greenwich Apparent Sidereal Time (includes nutation / the equation of
            # the equinoxes, up to ~1.1 s more accurate than mean sidereal time and
            # consistent with the apparent LST used elsewhere in the app).
            gst = time_obj.sidereal_time('apparent', longitude=0 * u.deg)
            gst_hour_val = gst.hour
            if isinstance(gst_hour_val, (np.ndarray, complex)):
                gst_hours = float(np.real(np.atleast_1d(gst_hour_val).flat[0]))
            else:
                gst_hours = float(gst_hour_val)  # type: ignore
            gst_hms = self._decimal_hours_to_hms(gst_hours)

            # Local Sidereal Time (corrected for observer longitude)
            # LST = GST + (observer longitude in hours)
            lon_hours = self.longitude / 15.0  # Convert degrees to hours
            lst_hours = gst_hours + lon_hours

            # Normalize to 0-24 range
            while lst_hours < 0:
                lst_hours += 24
            while lst_hours >= 24:
                lst_hours -= 24

            lst_hms = self._decimal_hours_to_hms(lst_hours)

            # Calculate hour angle for some reference objects
            # Hour angle = LST - RA (in hours)

            # Hour angle of vernal equinox (RA = 0h)
            ha_vernal_equinox = lst_hours  # Since RA = 0

            # Position of celestial pole (always at observer's latitude)
            north_celestial_pole_alt = abs(self.latitude)

            # Meridian info
            meridian_ra_hours = lst_hours
            meridian_ra_degrees = (meridian_ra_hours / 24.0) * 360.0

            # UTC time
            utc_time_dt = time_obj.to_datetime(timezone=ZoneInfo('UTC'))  # type: ignore

            return {
                'datetime_utc': utc_time_dt.isoformat() if isinstance(utc_time_dt, datetime) else str(utc_time_dt),
                'julian_date': float(time_obj.jd),  # type: ignore[arg-type]
                'greenwich_sidereal_time_hours': round(float(gst_hours), 6),
                'greenwich_sidereal_time_hms': gst_hms,
                'local_sidereal_time_hours': round(float(lst_hours), 6),
                'local_sidereal_time_hms': lst_hms,
                'observer_longitude_degrees': self.longitude,
                'observer_latitude_degrees': self.latitude,
                'hour_angle_vernal_equinox_hours': round(float(ha_vernal_equinox), 6),
                'north_celestial_pole_altitude_degrees': north_celestial_pole_alt,
                'meridian_ra_hours': round(float(meridian_ra_hours), 6),
                'meridian_ra_degrees': round(float(meridian_ra_degrees), 4),
                'unit_ra': 'hours (1h = 15°)',
                'unit_lst': 'hours (24h sidereal day)',
                'reference': 'Vernal Equinox at RA = 0h',
            }

        except Exception as e:
            logger.error(f"Error in sidereal calculations: {e}")
            return {}

    def get_best_observation_times(
        self, target_ra_hours: float, target_dec_degrees: float, observation_date: date, min_altitude: float = 20.0
    ) -> Dict[str, Any]:
        """
        Get the best observation times for a target object.

        Args:
            target_ra_hours: Right Ascension of target in hours (0-24)
            target_dec_degrees: Declination of target in degrees (-90 to +90)
            observation_date: Date for observation
            min_altitude: Minimum altitude above horizon (default 20 degrees)

        Returns:
            Dictionary with observation timing information
        """
        try:
            from astropy.coordinates import SkyCoord, ICRS

            # Convert RA hours to degrees
            target_ra_degrees = (target_ra_hours / 24.0) * 360.0

            # Create coordinate object
            target = SkyCoord(ra=target_ra_degrees * u.deg, dec=target_dec_degrees * u.deg, frame=ICRS)

            # Check visibility throughout the night/day
            start_time = datetime(
                observation_date.year, observation_date.month, observation_date.day, 0, 0, 0, tzinfo=ZoneInfo("UTC")
            )

            best_altitude = -90.0
            best_time = None
            rise_time = None
            set_time = None

            # Check 24 hours in 1-hour increments
            for hour in range(24):
                check_time = start_time + timedelta(hours=hour)
                time_obj = Time(check_time)

                altaz = target.transform_to(AltAz(obstime=time_obj, location=self.location))

                if altaz is None:
                    continue

                # Extract altitude value from Quantity
                alt_val = altaz.alt.degree  # type: ignore
                if isinstance(alt_val, (np.ndarray, complex)):
                    alt = float(np.real(np.atleast_1d(alt_val).flat[0]))
                else:
                    alt = float(alt_val)  # type: ignore

                # Track best (highest) altitude
                if alt > best_altitude:
                    best_altitude = alt
                    best_time = check_time

                # Track rise and set times (crossing horizon)
                if alt >= 0 and rise_time is None:
                    rise_time = check_time

                if alt < 0 and rise_time is not None and set_time is None:
                    set_time = check_time

            # Get sidereal info at best time
            best_time_sidereal = self._calculate_sidereal_info(Time(best_time)) if best_time else {}

            return {
                'target_ra_hours': target_ra_hours,
                'target_dec_degrees': target_dec_degrees,
                'observation_date': observation_date.isoformat(),
                'best_time_utc': best_time.isoformat() if best_time else None,
                'best_altitude_degrees': round(float(best_altitude), 2),
                'rise_time_utc': rise_time.isoformat() if rise_time else None,
                'set_time_utc': set_time.isoformat() if set_time else None,
                'visible': float(best_altitude) >= min_altitude,
                'min_altitude_requirement': min_altitude,
                'local_sidereal_time_at_best': best_time_sidereal.get('local_sidereal_time_hms', 'N/A'),
                'observation_window_hours': (
                    (set_time - rise_time).total_seconds() / 3600 if rise_time and set_time else None
                ),
            }

        except Exception as e:
            logger.error(f"Error calculating best observation times: {e}")
            return {}

    def _decimal_hours_to_hms(self, hours: float) -> str:
        """Convert decimal hours to HH:MM:SS format."""
        h = int(hours)
        m = int((hours - h) * 60)
        s = ((hours - h) * 60 - m) * 60
        return f"{h:02d}h {m:02d}m {s:05.2f}s"

    def _is_circumpolar(self, dec_degrees: float) -> bool:
        """
        Check if an object at a given declination is circumpolar (never sets).

        An object never sets when its declination lies within the observer's
        latitude of the visible celestial pole: ``dec >= 90 - lat`` in the
        northern hemisphere, ``dec <= -(90 + lat)`` in the southern. Right
        ascension has no bearing on circumpolarity - only declination and the
        observer's latitude do.
        """
        lat = self.latitude
        if lat >= 0:
            return dec_degrees >= (90.0 - lat)
        return dec_degrees <= -(90.0 + lat)
