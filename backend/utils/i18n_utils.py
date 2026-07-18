"""
Internationalization (i18n) utilities for MyAstroBoard backend

This module provides translation support for API responses and backend messages.
Messages sent to the frontend should use translation keys instead of hardcoded strings.

Usage:
    from utils.i18n_utils import get_translated_message, I18nManager

    # Get translated string with placeholders
    message = get_translated_message('weather_alerts.critical_dew_risk', time='14:30')

    # Or use the manager directly
    manager = I18nManager('fr')  # French
    title = manager.t('astro_weather.section_title')
"""

import json
import os
from typing import Dict, Any
from datetime import datetime
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Supported languages
DEFAULT_LANGUAGE = 'en'
_TRANSLATION_FILENAMES = {
    'en': 'en.json',
    'fr': 'fr.json',
    'es': 'es.json',
    'de': 'de.json',
    'it': 'it.json',
    'pt': 'pt.json',
}
SUPPORTED_LANGUAGES = list(_TRANSLATION_FILENAMES.keys())

# Cache for loaded translations
_translation_cache: Dict[str, Dict] = {}


def _is_safe_path(base_dir: str, candidate_path: str) -> bool:
    """Return True only if candidate_path resolves inside base_dir.

    Uses realpath + startswith (rather than os.path.commonpath) because that
    is the pattern CodeQL's py/path-injection query recognises as a
    sanitizer barrier.
    """
    base_real = os.path.realpath(base_dir)
    candidate_real = os.path.realpath(candidate_path)
    return candidate_real.startswith(base_real + os.sep)


def _load_translation_file(language: str) -> Dict:
    """
    Load translation file for a specific language

    Args:
        language: Language code (e.g., 'en', 'fr')

    Returns:
        Dictionary of translations or empty dict if not found
    """
    # Force language to a known-safe value before building file paths.
    if language not in SUPPORTED_LANGUAGES:
        logger.warning(f"Unsupported language '{language}', using default '{DEFAULT_LANGUAGE}'")
        language = DEFAULT_LANGUAGE

    if language in _translation_cache:
        return _translation_cache[language]

    language_file = _TRANSLATION_FILENAMES[language]

    # Try to find the translation file
    translation_path = None

    # Check multiple possible locations (for both Docker and development)
    possible_base_dirs = [
        os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'i18n'),
        os.path.join(os.getcwd(), 'static', 'i18n'),
        os.path.join('/app', 'static', 'i18n'),
    ]

    for base_dir in possible_base_dirs:
        path = os.path.join(base_dir, language_file)
        if _is_safe_path(base_dir, path) and os.path.exists(path):
            translation_path = path
            break

    if not translation_path:
        logger.warning(f"Translation file not found for language '{language}'")
        return {}

    try:
        with open(translation_path, 'r', encoding='utf-8') as f:
            translations = json.load(f)
        _translation_cache[language] = translations
        logger.debug(f"Loaded translations for language: {language}")
        return translations
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading translations for '{language}': {e}")
        return {}


class I18nManager:
    """
    Backend internationalization manager

    Handles translation lookups and placeholder replacement for API responses
    """

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        """
        Initialize I18n manager with a specific language

        Args:
            language: Language code (defaults to 'en')
        """
        self.language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        self.fallback_language = DEFAULT_LANGUAGE
        self._load_translations()

    def _load_translations(self):
        """Load translations for current and fallback languages"""
        self.translations = _load_translation_file(self.language)
        if self.language != self.fallback_language:
            self.fallback_translations = _load_translation_file(self.fallback_language)
        else:
            self.fallback_translations = self.translations

    def t(self, key: str, **params) -> str:
        """
        Get translated string by key path with optional placeholder replacement

        Args:
            key: Translation key using dot notation (e.g., 'common.loading')
            **params: Keyword arguments for placeholder replacement (e.g., time='14:30')

        Returns:
            Translated string or the key itself if not found
        """
        # Split key by dots for nested access
        keys = key.split('.')

        # Try to get from current language translations
        current = self.translations
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                # Try fallback language
                current = self.fallback_translations
                for fallback_k in keys:
                    if isinstance(current, dict) and fallback_k in current:
                        current = current[fallback_k]
                    else:
                        # Return key if not found
                        return key
                break

        # Ensure we have a string
        if not isinstance(current, str):
            return key

        result = current

        # Replace placeholders in format {key}
        for param_key, param_value in params.items():
            placeholder = f'{{{param_key}}}'
            result = result.replace(placeholder, str(param_value))

        return result

    def set_language(self, language: str):
        """
        Change the language for this manager instance

        Args:
            language: Language code to switch to
        """
        if language in SUPPORTED_LANGUAGES:
            self.language = language
            self._load_translations()
        else:
            logger.warning(f"Unsupported language: {language}. Keeping {self.language}")

    def get_language(self) -> str:
        """Get current language code"""
        return self.language

    def get_namespace(self, namespace: str) -> Dict:
        """
        Get all translations for a specific namespace

        Args:
            namespace: Namespace name (e.g., 'weather_alerts')

        Returns:
            Dictionary of translations for that namespace
        """
        if isinstance(self.translations, dict) and namespace in self.translations:
            return self.translations[namespace]
        return {}

    @staticmethod
    def get_supported_languages() -> list:
        """Get list of supported languages"""
        return SUPPORTED_LANGUAGES


# Global default manager instance
_default_manager = I18nManager()


def get_translated_message(key: str, language: str = DEFAULT_LANGUAGE, **params) -> str:
    """
    Convenience function to get a translated message

    Args:
        key: Translation key (e.g., 'weather_alerts.critical_dew_risk')
        language: Language code (defaults to 'en')
        **params: Placeholder values

    Returns:
        Translated string

    Example:
        message = get_translated_message('weather_alerts.critical_dew_risk', 'en', time='14:30')
    """
    manager = I18nManager(language)
    translated = manager.t(key, **params)
    if translated == key and language == DEFAULT_LANGUAGE:
        return _default_manager.t(key, **params)
    return translated


def create_translated_alert(
    alert_type: str, severity: str, time: str, language: str = DEFAULT_LANGUAGE
) -> Dict[str, Any]:
    """
    Create a weather alert dictionary with translated message

    Args:
        alert_type: Type of alert (e.g., 'DEW_WARNING', 'WIND_WARNING')
        severity: Severity level (e.g., 'HIGH', 'MEDIUM')
        time: ISO timestamp string
        language: Language code for translation

    Returns:
        Alert dictionary with translated message
    """
    manager = I18nManager(language)

    # Map alert types to translation keys
    alert_message_keys = {
        'DEW_WARNING': 'weather_alerts.critical_dew_risk',
        'WIND_WARNING': 'weather_alerts.critical_wind_conditions',
        'SEEING_WARNING': 'weather_alerts.poor_seeing_conditions',
        'TRANSPARENCY_WARNING': 'weather_alerts.poor_transparency_conditions',
    }

    # Format display time for message placeholder
    display_time = time
    try:
        display_time = datetime.fromisoformat(time).strftime('%H:%M')
    except Exception:
        pass  # non-ISO time string — display as-is

    # Get translated message
    message_key = alert_message_keys.get(alert_type, 'weather_alerts.section_title')
    message = manager.t(message_key, time=display_time)

    return {'type': alert_type, 'severity': severity, 'message': message, 'time': time}


def init_i18n_for_request(language_code: str = DEFAULT_LANGUAGE) -> I18nManager:
    """
    Initialize i18n manager for a specific request
    Useful for Flask request handlers

    Args:
        language_code: Language code to use

    Returns:
        Configured I18nManager instance
    """
    return I18nManager(language_code)
