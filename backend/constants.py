"""
Shared constants and configuration for MyAstroBoard backend
Centralizes commonly used values to avoid duplication and ensure consistency
"""

import os

# Directory paths
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
DATA_DIR = os.environ.get('DATA_DIR', DEFAULT_DATA_DIR)
DATA_DIR_CACHE = os.path.join(DATA_DIR, 'cache')
IERS_CACHE_FILE = os.path.join(DATA_DIR_CACHE, 'iers', 'finals2000A.all')
SKYTONIGHT_DIR = os.environ.get('SKYTONIGHT_DIR', os.path.join(DATA_DIR, 'skytonight'))
SKYTONIGHT_CATALOGUES_DIR = os.path.join(SKYTONIGHT_DIR, 'catalogues')
SKYTONIGHT_DATASET_FILE = os.path.join(SKYTONIGHT_CATALOGUES_DIR, 'targets.json')
SKYTONIGHT_CALCULATIONS_DIR = os.path.join(SKYTONIGHT_DIR, 'calculations')
SKYTONIGHT_RESULTS_FILE = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, 'calculation_results.json')
SKYTONIGHT_DSO_RESULTS_FILE = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, 'dso_results.json')
SKYTONIGHT_BODIES_RESULTS_FILE = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, 'bodies_results.json')
SKYTONIGHT_COMETS_RESULTS_FILE = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, 'comets_results.json')
SKYTONIGHT_SKYMAP_FILE = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, 'skymap_data.json')

# File paths
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'myastroboard.log')
CONDITIONS_FILE = os.path.join(DATA_DIR_CACHE, 'conditions.json')
CONFIG_DIR = os.path.join(SKYTONIGHT_DIR, 'configs')
OUTPUT_DIR = os.path.join(SKYTONIGHT_DIR, 'outputs')
SKYTONIGHT_OUTPUT_DIR = os.path.join(SKYTONIGHT_DIR, 'outputs')
SKYTONIGHT_LOGS_DIR = os.path.join(SKYTONIGHT_DIR, 'logs')
SKYTONIGHT_RUNTIME_DIR = os.path.join(SKYTONIGHT_DIR, 'runtime')
SKYTONIGHT_CALCULATION_LOG_FILE = os.path.join(SKYTONIGHT_LOGS_DIR, 'last_calculation.log')
SKYTONIGHT_SCHEDULER_STATUS_FILE = os.path.join(SKYTONIGHT_RUNTIME_DIR, 'scheduler_status.json')
SKYTONIGHT_SCHEDULER_TRIGGER_FILE = os.path.join(SKYTONIGHT_RUNTIME_DIR, 'scheduler_trigger')
SKYTONIGHT_SCHEDULER_LOCK_FILE = os.path.join(SKYTONIGHT_RUNTIME_DIR, 'scheduler.lock')

# API/Service URLs
URL_OPENMETEO = "https://api.open-meteo.com/v1/forecast"

# Cache configuration
CACHE_TTL = 1800  # seconds (legacy default, prefer per-job TTLs below)
CACHE_SCHEDULER_INTERVAL_SECONDS = 300  # 5 minutes

# Per-job cache TTLs - each cache is refreshed only when its own TTL expires.
# The scheduler polls every ~5 min but only runs a job if its TTL has elapsed.
CACHE_TTL_MOON_REPORT = 7200  # 2 hours - moon phase changes gradually (~0.5%/h)
CACHE_TTL_DARK_WINDOW = 7200  # 2 hours - derived from moon report (same TTL)
CACHE_TTL_MOON_PLANNER = 7200  # 2 hours - 7-night forecast, daily precision
CACHE_TTL_SUN_REPORT = 21600  # 6 hours - sunrise/sunset changes ~1 min/day
CACHE_TTL_BEST_WINDOW = 10800  # 3 hours - observation window changes slowly
CACHE_TTL_SOLAR_ECLIPSE = 86400  # 24 hours - next event is months away
CACHE_TTL_LUNAR_ECLIPSE = 86400  # 24 hours - next event is months away
CACHE_TTL_HORIZON_GRAPH = 21600  # 6 hours - daily arc computed for the full day
CACHE_TTL_AURORA = 3600  # 1 hour  - geomagnetic forecast updates hourly
CACHE_TTL_ISS_PASSES = 21600  # 6 hours - 20-day window, stable predictions
CACHE_TTL_CSS_PASSES = 21600  # 6 hours - 20-day window, stable predictions
CACHE_TTL_PLANETARY_EVENTS = 86400  # 24 hours - 365-day planetary forecast
CACHE_TTL_SPECIAL_PHENOMENA = 86400  # 24 hours - annual events (equinoxes, etc.)
CACHE_TTL_SOLAR_SYSTEM_EVENTS = 86400  # 24 hours - annual events (meteor showers, etc.)
CACHE_TTL_SIDEREAL_TIME = 3600  # 1 hour  - hourly precision is sufficient
CACHE_TTL_SEEING_FORECAST = 21600  # 6 hours - 7Timer API resolution

# IERS-A Earth-orientation data - covers ~1 year ahead from download date; 21-day TTL is well within that window
CACHE_TTL_IERS = 1814400  # 21 days

# Spaceflight cache TTLs (Launch Library 2 free tier: ~15 req/h - keep calls minimal)
CACHE_TTL_SPACEFLIGHT_LAUNCHES = 7200  # 2 hours - free tier ~15 req/h; 3 endpoints per cycle → max 2 cycles/h
CACHE_TTL_SPACEFLIGHT_ASTRONAUTS = 21600  # 6 hours - crew changes are rare
CACHE_TTL_SPACEFLIGHT_EVENTS = 7200  # 2 hours - free tier budget; events timeline changes slowly

# Weather API configuration
WEATHER_CACHE_TTL = 3600  # seconds (1 hour)

# Version update check configuration
VERSION_UPDATE_CACHE_TTL = 14400  # seconds (4 hours)
OPENMETEO_RETRY_COUNT = 2
OPENMETEO_BACKOFF_FACTOR = 0.5

# Astronomical constants (angles in degrees)
ASTRONOMICAL_NIGHT_ALTITUDE = -18  # Sun altitude for astronomical night
NAUTICAL_TWILIGHT_ALTITUDE = -12  # Sun altitude for nautical twilight
CIVIL_TWILIGHT_ALTITUDE = -6  # Sun altitude for civil twilight
MOON_ILLUMINATION_THRESHOLD = 15  # Percentage - moon considered "low" below this
MOON_ALTITUDE_PRACTICAL = 5  # Degrees - minimum moon altitude for visibility
WIND_TRACKING_THRESHOLD = 15.0  # km/h - wind speed that affects mount tracking
ASTRO_BEST_PERIOD_MIN_DURATION_HOURS = 2.0  # Hide short windows that are not practical for setup/imaging

# Connector cache TTLs
CACHE_TTL_ALLSKY_SENSOR = 300  # 5 min  - live sensor data (temp, gain, etc.)
CACHE_TTL_ALLSKY_HEALTH = 300  # 5 min  - per-module reachability checks

# Logging configuration
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING').upper()  # Global log level for file output
CONSOLE_LOG_LEVEL = os.environ.get('CONSOLE_LOG_LEVEL', 'WARNING').upper()  # Console log level

# SkyTonight dataset configuration
SKYTONIGHT_PREFERRED_NAME_ORDER = [
    'CommonName',
    'Messier',
    'OpenNGC',
    'OpenIC',
    'Caldwell',
    'LBN',
    'Herschel400',
    'Pensack500',
    'GaryImm',
    'Arp',
    'Sharpless',
    'Barnard',
    'vdB',
    'AbellPNe',
    'AbellClusters',
]
