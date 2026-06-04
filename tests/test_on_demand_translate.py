"""
Tests for on_demand_translate.py
Covers pure-logic branches and mocked HTTP calls.
"""

import pytest
from unittest.mock import patch, MagicMock
import on_demand_translate as odt
from on_demand_translate import (
    translate_text_on_demand,
    _cache_get,
    _cache_set,
    _split_long_segment,
    _chunk_text_for_provider,
    _TRANSLATION_CACHE,
)


def _clear_cache():
    _TRANSLATION_CACHE.clear()


class TestTranslateTextOnDemand:
    """Tests for the main translate_text_on_demand entry point."""

    def setup_method(self):
        _clear_cache()

    def test_empty_text_returns_error(self):
        result = translate_text_on_demand("", "en", "fr")
        assert result["success"] is False
        assert result["error"] == "missing_text"

    def test_whitespace_only_text_returns_error(self):
        result = translate_text_on_demand("   ", "en", "fr")
        assert result["success"] is False
        assert result["error"] == "missing_text"

    def test_same_source_and_target_language_returns_original(self):
        result = translate_text_on_demand("Hello world", "en", "en")
        assert result["success"] is True
        assert result["translated_text"] == "Hello world"
        assert result["provider"] == "none"

    def test_same_language_with_locale_subtag(self):
        """en-US and en-GB should both normalize to 'en'."""
        result = translate_text_on_demand("Hello", "en-US", "en-GB")
        assert result["success"] is True
        assert result["provider"] == "none"

    def test_text_too_long_returns_error(self):
        long_text = "A" * (odt._MAX_TEXT_LENGTH + 1)
        result = translate_text_on_demand(long_text, "en", "fr")
        assert result["success"] is False
        assert result["error"] == "text_too_long"

    @patch("on_demand_translate._translate_with_mymemory")
    def test_successful_translation(self, mock_mymemory):
        mock_mymemory.return_value = "Bonjour le monde"
        result = translate_text_on_demand("Hello world", "en", "fr")
        assert result["success"] is True
        assert result["translated_text"] == "Bonjour le monde"
        assert result["provider"] == "mymemory"
        assert result["cached"] is False

    @patch("on_demand_translate._translate_with_mymemory")
    def test_caches_successful_translation(self, mock_mymemory):
        mock_mymemory.return_value = "Bonjour"
        translate_text_on_demand("Hello", "en", "fr")
        # Second call should use cache
        result = translate_text_on_demand("Hello", "en", "fr")
        assert result["cached"] is True
        assert result["translated_text"] == "Bonjour"
        # Provider call should only happen once
        assert mock_mymemory.call_count == 1

    @patch("on_demand_translate._translate_with_mymemory")
    def test_provider_failure_returns_fallback(self, mock_mymemory):
        mock_mymemory.return_value = None
        result = translate_text_on_demand("Hello world", "en", "fr")
        assert result["success"] is False
        assert result["error"] == "provider_unavailable"
        assert result["translated_text"] == "Hello world"

    def test_language_code_normalized_to_lowercase(self):
        result = translate_text_on_demand("Test", "EN", "EN")
        assert result["source_lang"] == "en"
        assert result["target_lang"] == "en"


class TestCacheHelpers:
    """Tests for _cache_get and _cache_set."""

    def setup_method(self):
        _clear_cache()

    def test_cache_miss_returns_none(self):
        result = _cache_get(("en", "fr", "hello"))
        assert result is None

    def test_cache_roundtrip(self):
        key = ("en", "de", "test text")
        _cache_set(key, "Testtext", "mymemory")
        result = _cache_get(key)
        assert result is not None
        assert result[0] == "Testtext"
        assert result[1] == "mymemory"

    def test_expired_cache_returns_none(self):
        import time
        key = ("en", "es", "expiry test")
        _cache_set(key, "prueba", "mymemory")
        # Manually make the entry stale
        _TRANSLATION_CACHE[key] = ("prueba", time.time() - odt._CACHE_TTL_SECONDS - 1, "mymemory")
        result = _cache_get(key)
        assert result is None

    def test_cache_evicts_oldest_when_full(self):
        """When cache is at max capacity, oldest entry should be evicted."""
        # Fill cache to near-max
        original_max = odt._CACHE_MAX_ENTRIES
        # Temporarily set max to a small value
        odt._CACHE_MAX_ENTRIES = 3
        try:
            _clear_cache()
            import time
            for i in range(3):
                _TRANSLATION_CACHE[("en", "fr", f"word{i}")] = (f"mot{i}", time.time(), "mymemory")
            # Adding another entry should evict the oldest
            _cache_set(("en", "fr", "word3"), "mot3", "mymemory")
            assert len(_TRANSLATION_CACHE) == 3
        finally:
            odt._CACHE_MAX_ENTRIES = original_max


class TestSplitLongSegment:
    """Tests for _split_long_segment pure logic."""

    def test_short_segment_not_split(self):
        text = "Hello world"
        result = _split_long_segment(text, 50)
        assert result == [text]

    def test_long_segment_is_split(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _split_long_segment(text, 20)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 20

    def test_empty_string(self):
        result = _split_long_segment("", 50)
        # Empty string is shorter than max_len so it's returned as-is
        assert result == [""] or result == []

    def test_very_long_word_is_hard_wrapped(self):
        long_word = "A" * 100
        result = _split_long_segment(long_word, 10)
        for chunk in result:
            assert len(chunk) <= 10


class TestChunkTextForProvider:
    """Tests for _chunk_text_for_provider paragraph splitting."""

    def test_short_text_not_chunked(self):
        text = "Short text"
        result = _chunk_text_for_provider(text, 100)
        assert result == [text]

    def test_paragraph_boundaries_preserved(self):
        text = "Para1\nPara2\nPara3"
        result = _chunk_text_for_provider(text, 100)
        # Under 100 chars total, so single chunk
        assert result == [text]

    def test_long_text_is_chunked_on_newlines(self):
        para = "A" * 50
        text = "\n".join([para] * 3)
        result = _chunk_text_for_provider(text, 60)
        # Each paragraph is 50 chars, fits within 60 per chunk
        for chunk in result:
            assert len(chunk) <= 60
