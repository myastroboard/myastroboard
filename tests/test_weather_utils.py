"""
Unit tests for weather utilities (weather_utils.py)
"""
from unittest.mock import Mock, patch


# Import the function to test
from weather_utils import create_weather_client, create_fresh_weather_client

RETRY_COUNT = 2
BACKOFF_FACTOR = 0.5


class TestWeatherClientCreation:
    """Test weather client creation"""
    
    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests_cache.CachedSession')
    def test_create_weather_client_returns_client(self, mock_cached_session, mock_retry, mock_client):
        """Test that create_weather_client returns a client object"""
        # Setup mocks
        mock_session = Mock()
        mock_cached_session.return_value = mock_session
        mock_retry_session = Mock()
        mock_retry.return_value = mock_retry_session
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        
        # Call the function
        result = create_weather_client()
        
        # Verify the client was created
        assert result == mock_client_instance
    
    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests_cache.CachedSession')
    def test_create_weather_client_uses_cache(self, mock_cached_session, mock_retry, mock_client):
        """Test that client is created with caching enabled"""
        mock_session = Mock()
        mock_cached_session.return_value = mock_session
        mock_retry_session = Mock()
        mock_retry.return_value = mock_retry_session
        
        create_weather_client()
        
        # Verify cache session was created with correct TTL
        mock_cached_session.assert_called_once()
        call_args = mock_cached_session.call_args
        assert call_args[0][0].endswith(".weather_cache")  # Cache filename
        # Check expire_after parameter
        assert 'expire_after' in call_args[1]
    
    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests_cache.CachedSession')
    def test_create_weather_client_uses_retry(self, mock_cached_session, mock_retry, mock_client):
        """Test that client is created with retry logic"""
        mock_session = Mock()
        mock_cached_session.return_value = mock_session
        mock_retry_session = Mock()
        mock_retry.return_value = mock_retry_session
        
        create_weather_client()
        
        # Verify retry was configured
        mock_retry.assert_called_once()
        call_args = mock_retry.call_args
        assert call_args[0][0] == mock_session
        # Check retry parameters
        assert 'retries' in call_args[1]
        assert 'backoff_factor' in call_args[1]
    
    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests_cache.CachedSession')
    def test_create_weather_client_integration(self, mock_cached_session, mock_retry, mock_client):
        """Test the full integration of cache + retry + client"""
        mock_session = Mock()
        mock_cached_session.return_value = mock_session
        mock_retry_session = Mock()
        mock_retry.return_value = mock_retry_session
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        
        result = create_weather_client()
        
        # Verify the chain: cache session -> retry session -> client
        mock_cached_session.assert_called_once()
        mock_retry.assert_called_once_with(
            mock_session,
            retries=RETRY_COUNT,
            backoff_factor=BACKOFF_FACTOR
        )
        mock_client.assert_called_once_with(session=mock_retry_session)
        assert result == mock_client_instance


class TestFreshWeatherClientCreation:
    """Test fresh weather client creation (no cache)"""
    RETRY_COUNT = 2
    BACKOFF_FACTOR = 0.5

    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests.Session')
    def test_create_fresh_weather_client_returns_client(self, mock_session_cls, mock_retry, mock_client):
        """Test that create_fresh_weather_client returns a client object"""
        mock_session = Mock()
        mock_session_cls.return_value = mock_session
        mock_retry_session = Mock()
        mock_retry.return_value = mock_retry_session
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance

        result = create_fresh_weather_client()

        mock_session_cls.assert_called_once_with()
        mock_retry.assert_called_once_with(mock_session, retries=self.RETRY_COUNT, backoff_factor=self.BACKOFF_FACTOR)
        mock_client.assert_called_once_with(session=mock_retry_session)
        assert result == mock_client_instance

    @patch('weather_utils.requests_cache.CachedSession')
    @patch('weather_utils.openmeteo_requests.Client')
    @patch('weather_utils.retry')
    @patch('weather_utils.requests.Session')
    def test_create_fresh_weather_client_does_not_use_cache(self, mock_session_cls, mock_retry, mock_client, mock_cached_session):
        """Test that fresh client path does not create a cached session"""
        mock_session_cls.return_value = Mock()
        mock_retry.return_value = Mock()

        create_fresh_weather_client()

        mock_cached_session.assert_not_called()
