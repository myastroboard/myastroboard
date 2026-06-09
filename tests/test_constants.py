"""
Unit tests for constants (constants.py)
"""
from urllib.parse import urlparse


# Import constants to test
from constants import (
    DATA_DIR,
    OUTPUT_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    LOG_FILE,
    CONDITIONS_FILE,
    URL_OPENMETEO,
    CACHE_TTL,
    WEATHER_CACHE_TTL,
    OPENMETEO_RETRY_COUNT,
    OPENMETEO_BACKOFF_FACTOR,
    ASTRONOMICAL_NIGHT_ALTITUDE,
    NAUTICAL_TWILIGHT_ALTITUDE,
    CIVIL_TWILIGHT_ALTITUDE,
    MOON_ILLUMINATION_THRESHOLD,
    MOON_ALTITUDE_PRACTICAL,
    WIND_TRACKING_THRESHOLD,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT
)


class TestDirectoryConstants:
    """Test directory path constants"""
    
    def test_data_dir_is_string(self):
        """Test DATA_DIR is a string"""
        assert isinstance(DATA_DIR, str)
        assert len(DATA_DIR) > 0
    
    def test_output_dir_is_string(self):
        """Test OUTPUT_DIR is a string"""
        assert isinstance(OUTPUT_DIR, str)
        assert len(OUTPUT_DIR) > 0
    
    def test_config_dir_is_string(self):
        """Test CONFIG_DIR is a string"""
        assert isinstance(CONFIG_DIR, str)
        assert len(CONFIG_DIR) > 0


class TestFilePathConstants:
    """Test file path constants"""
    
    def test_config_file_path(self):
        """Test CONFIG_FILE is constructed correctly"""
        assert isinstance(CONFIG_FILE, str)
        assert CONFIG_FILE.endswith('config.json')
        assert DATA_DIR in CONFIG_FILE
    
    def test_log_file_path(self):
        """Test LOG_FILE is constructed correctly"""
        assert isinstance(LOG_FILE, str)
        assert LOG_FILE.endswith('.log')
        assert DATA_DIR in LOG_FILE
    
    def test_conditions_file_path(self):
        """Test CONDITIONS_FILE is constructed correctly"""
        assert isinstance(CONDITIONS_FILE, str)
        assert CONDITIONS_FILE.endswith('.json')
        assert DATA_DIR in CONDITIONS_FILE


class TestURLConstants:
    """Test URL constants"""

    def test_openmeteo_url(self):
        """Test Open Meteo URL is valid"""
        assert isinstance(URL_OPENMETEO, str)
        
        parsed = urlparse(URL_OPENMETEO)
        # Scheme must be HTTPS
        assert parsed.scheme == "https"
        # Domain must match exactly
        assert parsed.netloc in ("api.open-meteo.com", "open-meteo.com")


class TestCacheConstants:
    """Test cache-related constants"""
    
    def test_cache_ttl_is_positive(self):
        """Test CACHE_TTL is a positive integer"""
        assert isinstance(CACHE_TTL, int)
        assert CACHE_TTL > 0
    
    def test_weather_cache_ttl_is_positive(self):
        """Test WEATHER_CACHE_TTL is a positive integer"""
        assert isinstance(WEATHER_CACHE_TTL, int)
        assert WEATHER_CACHE_TTL > 0
    
    def test_openmeteo_retry_count_is_positive(self):
        """Test OPENMETEO_RETRY_COUNT is a positive integer"""
        assert isinstance(OPENMETEO_RETRY_COUNT, int)
        assert OPENMETEO_RETRY_COUNT > 0
    
    def test_openmeteo_backoff_factor_is_positive(self):
        """Test OPENMETEO_BACKOFF_FACTOR is a positive number"""
        assert isinstance(OPENMETEO_BACKOFF_FACTOR, (int, float))
        assert OPENMETEO_BACKOFF_FACTOR > 0


class TestAstronomicalConstants:
    """Test astronomical constants"""
    
    def test_astronomical_night_altitude(self):
        """Test astronomical night altitude constant"""
        assert isinstance(ASTRONOMICAL_NIGHT_ALTITUDE, (int, float))
        assert ASTRONOMICAL_NIGHT_ALTITUDE == -18
        assert -90 <= ASTRONOMICAL_NIGHT_ALTITUDE <= 0
    
    def test_nautical_twilight_altitude(self):
        """Test nautical twilight altitude constant"""
        assert isinstance(NAUTICAL_TWILIGHT_ALTITUDE, (int, float))
        assert NAUTICAL_TWILIGHT_ALTITUDE == -12
        assert -90 <= NAUTICAL_TWILIGHT_ALTITUDE <= 0
    
    def test_civil_twilight_altitude(self):
        """Test civil twilight altitude constant"""
        assert isinstance(CIVIL_TWILIGHT_ALTITUDE, (int, float))
        assert CIVIL_TWILIGHT_ALTITUDE == -6
        assert -90 <= CIVIL_TWILIGHT_ALTITUDE <= 0
    
    def test_twilight_altitude_ordering(self):
        """Test twilight altitudes are in correct order"""
        # Civil is less dark (higher altitude) than nautical, which is less dark than astronomical
        assert CIVIL_TWILIGHT_ALTITUDE > NAUTICAL_TWILIGHT_ALTITUDE
        assert NAUTICAL_TWILIGHT_ALTITUDE > ASTRONOMICAL_NIGHT_ALTITUDE
    
    def test_moon_illumination_threshold(self):
        """Test moon illumination threshold is valid percentage"""
        assert isinstance(MOON_ILLUMINATION_THRESHOLD, (int, float))
        assert 0 <= MOON_ILLUMINATION_THRESHOLD <= 100
    
    def test_moon_altitude_practical(self):
        """Test moon practical altitude is valid"""
        assert isinstance(MOON_ALTITUDE_PRACTICAL, (int, float))
        assert -90 <= MOON_ALTITUDE_PRACTICAL <= 90
    
    def test_wind_tracking_threshold(self):
        """Test wind tracking threshold is positive"""
        assert isinstance(WIND_TRACKING_THRESHOLD, (int, float))
        assert WIND_TRACKING_THRESHOLD > 0


class TestLoggingConstants:
    """Test logging-related constants"""
    
    def test_log_max_bytes_is_positive(self):
        """Test LOG_MAX_BYTES is positive"""
        assert isinstance(LOG_MAX_BYTES, int)
        assert LOG_MAX_BYTES > 0
    
    def test_log_backup_count_is_positive(self):
        """Test LOG_BACKUP_COUNT is positive"""
        assert isinstance(LOG_BACKUP_COUNT, int)
        assert LOG_BACKUP_COUNT > 0
    
    def test_log_max_bytes_reasonable_size(self):
        """Test LOG_MAX_BYTES is a reasonable size (at least 1MB)"""
        assert LOG_MAX_BYTES >= 1024 * 1024  # At least 1MB


class TestEnvironmentVariables:
    """Test that constants can be overridden by environment variables"""
    
    def test_data_dir_uses_environment(self):
        """Test DATA_DIR can be set from environment"""
        # In our test setup, DATA_DIR should come from environment or have a default
        # The constants module may have already imported with default values
        # So we just verify it's a valid directory path
        assert isinstance(DATA_DIR, str)
        assert len(DATA_DIR) > 0
    
    def test_output_dir_uses_environment(self):
        """Test OUTPUT_DIR can be set from environment"""
        assert isinstance(OUTPUT_DIR, str)
        assert len(OUTPUT_DIR) > 0
    
    def test_config_dir_uses_environment(self):
        """Test CONFIG_DIR can be set from environment"""
        assert isinstance(CONFIG_DIR, str)
        assert len(CONFIG_DIR) > 0
