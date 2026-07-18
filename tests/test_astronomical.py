"""
Unit tests for Moon and Sun phase calculations
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo


# Import services to test
from astroweather.moon_phases import MoonService, MoonAstroPhotoInfo
from astroweather.sun_phases import SunService, SunAstroInfo


class TestMoonService:
    """Test Moon calculation service"""
    
    @pytest.fixture
    def moon_service(self):
        """Create a MoonService instance for testing"""
        # Use Montreal coordinates as test location
        return MoonService(
            latitude=45.5,
            longitude=-73.5,
            timezone="America/Montreal"
        )
    
    def test_moon_service_initialization(self, moon_service):
        """Test MoonService initializes correctly"""
        assert moon_service.latitude == 45.5
        assert moon_service.longitude == -73.5
        assert moon_service.timezone == ZoneInfo("America/Montreal")
        assert moon_service.observer is not None
        assert moon_service.location is not None
    
    def test_get_report_returns_valid_structure(self, moon_service):
        """Test that get_report returns MoonAstroPhotoInfo with expected fields"""
        report = moon_service.get_report()
        
        # Check type
        assert isinstance(report, MoonAstroPhotoInfo)
        
        # Check all required fields exist
        assert hasattr(report, 'phase_name')
        assert hasattr(report, 'illumination_percent')
        assert hasattr(report, 'distance_km')
        assert hasattr(report, 'altitude_deg')
        assert hasattr(report, 'azimuth_deg')
        assert hasattr(report, 'next_moonrise')
        assert hasattr(report, 'next_moonset')
        assert hasattr(report, 'next_full_moon')
        assert hasattr(report, 'next_new_moon')
        assert hasattr(report, 'next_dark_night_start')
        assert hasattr(report, 'next_dark_night_end')
    
    def test_moon_phase_name_is_valid(self, moon_service):
        """Test that phase name is one of the expected values"""
        report = moon_service.get_report()
        valid_phases = [
            "New Moon", "Waxing Crescent", "First Quarter", 
            "Waxing Gibbous", "Full Moon", "Waning Gibbous",
            "Last Quarter", "Waning Crescent"
        ]
        assert report.phase_name in valid_phases
    
    def test_moon_illumination_range(self, moon_service):
        """Test that illumination is between 0 and 100"""
        report = moon_service.get_report()
        assert 0 <= report.illumination_percent <= 100
        assert isinstance(report.illumination_percent, (int, float))
    
    def test_moon_distance_positive(self, moon_service):
        """Test that moon distance is positive and reasonable"""
        report = moon_service.get_report()
        # Moon distance varies between ~356,500 km and ~406,700 km
        assert 300000 <= report.distance_km <= 500000
    
    def test_moon_altitude_range(self, moon_service):
        """Test that altitude is in valid range"""
        report = moon_service.get_report()
        assert -90 <= report.altitude_deg <= 90
    
    def test_moon_azimuth_range(self, moon_service):
        """Test that azimuth is in valid range"""
        report = moon_service.get_report()
        assert 0 <= report.azimuth_deg <= 360
    
    def test_moon_rise_set_format(self, moon_service):
        """Test that moonrise/moonset are formatted strings"""
        report = moon_service.get_report()
        assert isinstance(report.next_moonrise, str)
        assert isinstance(report.next_moonset, str)
        # Should be ISO format with timezone info
        assert 'T' in report.next_moonrise or report.next_moonrise == "Not found"
    
    def test_phase_name_new_moon(self, moon_service):
        """Test phase name for new moon (angle near 0)"""
        phase_name = moon_service._phase_name(5)
        assert phase_name == "New Moon"
    
    def test_phase_name_full_moon(self, moon_service):
        """Test phase name for full moon (angle near 180)"""
        phase_name = moon_service._phase_name(180)
        assert phase_name == "Full Moon"
    
    def test_phase_name_first_quarter(self, moon_service):
        """Test phase name for first quarter (angle near 90)"""
        phase_name = moon_service._phase_name(95)
        assert phase_name == "First Quarter"
    
    def test_phase_name_waxing_crescent(self, moon_service):
        """Test phase name for waxing crescent"""
        phase_name = moon_service._phase_name(45)
        assert "Crescent" in phase_name


class TestSunService:
    """Test Sun calculation service"""
    
    @pytest.fixture
    def sun_service(self):
        """Create a SunService instance for testing"""
        # Use Montreal coordinates as test location
        return SunService(
            latitude=45.5,
            longitude=-73.5,
            timezone="America/Montreal"
        )
    
    def test_sun_service_initialization(self, sun_service):
        """Test SunService initializes correctly"""
        assert sun_service.latitude == 45.5
        assert sun_service.longitude == -73.5
        assert sun_service.timezone == ZoneInfo("America/Montreal")
        assert sun_service.location is not None
    
    def test_get_today_report_returns_valid_structure(self, sun_service):
        """Test that get_today_report returns SunAstroInfo with expected fields"""
        report = sun_service.get_today_report()
        
        # Check type
        assert isinstance(report, SunAstroInfo)
        
        # Check all required fields exist
        assert hasattr(report, 'sunrise')
        assert hasattr(report, 'sunset')
        assert hasattr(report, 'civil_dusk')
        assert hasattr(report, 'civil_dawn')
        assert hasattr(report, 'nautical_dusk')
        assert hasattr(report, 'nautical_dawn')
        assert hasattr(report, 'astronomical_dusk')
        assert hasattr(report, 'astronomical_dawn')
        assert hasattr(report, 'true_night_hours')
    
    def test_get_tomorrow_report_returns_valid_structure(self, sun_service):
        """Test that get_tomorrow_report works"""
        report = sun_service.get_tomorrow_report()
        assert isinstance(report, SunAstroInfo)
    
    def test_sunrise_sunset_are_strings(self, sun_service):
        """Test that sunrise and sunset are formatted strings"""
        report = sun_service.get_today_report()
        assert isinstance(report.sunrise, str)
        assert isinstance(report.sunset, str)
    
    def test_twilight_times_are_strings(self, sun_service):
        """Test that twilight times are formatted strings"""
        report = sun_service.get_today_report()
        assert isinstance(report.civil_dusk, str)
        assert isinstance(report.civil_dawn, str)
        assert isinstance(report.nautical_dusk, str)
        assert isinstance(report.nautical_dawn, str)
        assert isinstance(report.astronomical_dusk, str)
        assert isinstance(report.astronomical_dawn, str)
    
    def test_true_night_hours_is_number(self, sun_service):
        """Test that true_night_hours is a number"""
        report = sun_service.get_today_report()
        assert isinstance(report.true_night_hours, (int, float))
    
    def test_true_night_hours_reasonable_range(self, sun_service):
        """Test that night hours are in reasonable range (0-24)"""
        report = sun_service.get_today_report()
        assert 0 <= report.true_night_hours <= 24
    
    def test_sun_altitude_calculation(self, sun_service):
        """Test that _sun_altitude returns valid altitude"""
        # Test at a specific time
        test_time = datetime.now(sun_service.timezone)
        altitude = sun_service._sun_altitude(test_time)
        assert -90 <= altitude <= 90
        assert isinstance(altitude, (int, float))


class TestMoonServiceDifferentLocations:
    """Test MoonService with different locations"""
    
    def test_equator_location(self):
        """Test moon service at equator"""
        service = MoonService(0, 0, "UTC")
        report = service.get_report()
        assert isinstance(report, MoonAstroPhotoInfo)
    
    def test_southern_hemisphere(self):
        """Test moon service in southern hemisphere"""
        # Sydney, Australia
        service = MoonService(-33.865, 151.209, "Australia/Sydney")
        report = service.get_report()
        assert isinstance(report, MoonAstroPhotoInfo)
    
    def test_northern_extreme(self):
        """Test moon service at high northern latitude"""
        # Reykjavik, Iceland
        service = MoonService(64.146, -21.942, "Atlantic/Reykjavik")
        report = service.get_report()
        assert isinstance(report, MoonAstroPhotoInfo)


class TestSunServiceDifferentLocations:
    """Test SunService with different locations"""
    
    def test_equator_location(self):
        """Test sun service at equator"""
        service = SunService(0, 0, "UTC")
        report = service.get_today_report()
        assert isinstance(report, SunAstroInfo)
    
    def test_southern_hemisphere(self):
        """Test sun service in southern hemisphere"""
        # Sydney, Australia
        service = SunService(-33.865, 151.209, "Australia/Sydney")
        report = service.get_today_report()
        assert isinstance(report, SunAstroInfo)
    
    def test_european_location(self):
        """Test sun service in Europe"""
        # Paris, France
        service = SunService(48.856, 2.352, "Europe/Paris")
        report = service.get_today_report()
        assert isinstance(report, SunAstroInfo)
        # Check that times are formatted (not "Not found")
        assert report.sunrise != "Not found"
        assert report.sunset != "Not found"
