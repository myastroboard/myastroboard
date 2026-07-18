"""
Weather utility functions for Open-Meteo API
Provides centralized weather client creation to avoid code duplication
"""

import os
import requests
import openmeteo_requests
import requests_cache
from retry_requests import retry
from utils.constants import WEATHER_CACHE_TTL, OPENMETEO_RETRY_COUNT, OPENMETEO_BACKOFF_FACTOR, DATA_DIR_CACHE

# Ensure cache directory exists
os.makedirs(DATA_DIR_CACHE, exist_ok=True)


def create_weather_client():
    """
    Create a configured Open-Meteo API client with caching and retry logic
    Used for UI forecasts where caching is beneficial.

    Returns:
        openmeteo_requests.Client: Configured client instance with:
            - Cache session (1 hour TTL)
            - Retry logic (5 retries with exponential backoff)
    """
    cache_session = requests_cache.CachedSession(
        os.path.join(DATA_DIR_CACHE, ".weather_cache"), expire_after=WEATHER_CACHE_TTL
    )
    retry_session = retry(cache_session, retries=OPENMETEO_RETRY_COUNT, backoff_factor=OPENMETEO_BACKOFF_FACTOR)
    client = openmeteo_requests.Client(session=retry_session)  # type: ignore[arg-type]
    return client


def create_fresh_weather_client():
    """
    Create a non-cached Open-Meteo API client for real-time data.
    Used for SkyTonight conditions where fresh data is required.

    Returns:
        openmeteo_requests.Client: Configured client instance with:
            - NO caching (always fresh data)
            - Retry logic (5 retries with exponential backoff)
    """
    session = requests.Session()
    retry_session = retry(session, retries=OPENMETEO_RETRY_COUNT, backoff_factor=OPENMETEO_BACKOFF_FACTOR)
    client = openmeteo_requests.Client(session=retry_session)  # type: ignore[arg-type]
    return client
