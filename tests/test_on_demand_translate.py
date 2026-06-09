"""
Tests for on_demand_translate.py
Covers pure-logic branches and mocked HTTP calls.
"""

from unittest.mock import patch, MagicMock
import on_demand_translate as odt

translate_text_on_demand = odt.translate_text_on_demand
_cache_get = odt._cache_get
_cache_set = odt._cache_set
_split_long_segment = odt._split_long_segment
_chunk_text_for_provider = odt._chunk_text_for_provider
_TRANSLATION_CACHE = odt._TRANSLATION_CACHE
_translate_with_mymemory = odt._translate_with_mymemory
_translate_with_mymemory_chunked = odt._translate_with_mymemory_chunked


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

    def test_empty_part_from_trailing_punctuation_skipped(self):
        """Line 84: re.split produces empty string at end → if not part: continue."""
        text = "Hello world! "
        result = _split_long_segment(text, 5)
        assert all(chunk for chunk in result)


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

    def test_blank_lines_preserved_as_empty_chunks(self):
        """Text with blank lines should produce empty string chunks (max_len forces split)."""
        text = "Para1\n\nPara2"
        result = _chunk_text_for_provider(text, 3)  # small max_len forces chunking path
        assert "" in result


class TestTranslateWithMymemory:
    """Direct tests for _translate_with_mymemory."""

    @patch("on_demand_translate.requests.get")
    def test_successful_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"responseData": {"translatedText": "Bonjour"}}
        mock_get.return_value = mock_resp
        result = _translate_with_mymemory("Hello", "en", "fr")
        assert result == "Bonjour"

    @patch("on_demand_translate.requests.get")
    def test_non_ok_response_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_get.return_value = mock_resp
        result = _translate_with_mymemory("Hello", "en", "fr")
        assert result is None

    @patch("on_demand_translate.requests.get")
    def test_non_string_translated_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"responseData": {"translatedText": 123}}
        mock_get.return_value = mock_resp
        result = _translate_with_mymemory("Hello", "en", "fr")
        assert result is None

    @patch("on_demand_translate.requests.get")
    def test_empty_translated_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"responseData": {"translatedText": "   "}}
        mock_get.return_value = mock_resp
        result = _translate_with_mymemory("Hello", "en", "fr")
        assert result is None

    @patch("on_demand_translate.requests.get", side_effect=Exception("network error"))
    def test_exception_returns_none(self, mock_get):
        result = _translate_with_mymemory("Hello", "en", "fr")
        assert result is None

    @patch("on_demand_translate.requests.get")
    def test_html_entities_unescaped(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"responseData": {"translatedText": "Bonjour &amp; monde"}}
        mock_get.return_value = mock_resp
        result = _translate_with_mymemory("Hello & world", "en", "fr")
        assert result == "Bonjour & monde"


class TestTranslateWithMymemoryChunked:
    """Tests for _translate_with_mymemory_chunked including blank-line passthrough."""

    @patch("on_demand_translate._chunk_text_for_provider")
    @patch("on_demand_translate._translate_with_mymemory")
    def test_blank_chunks_pass_through_without_translation(self, mock_translate, mock_chunk):
        """Empty chunks (blank lines) should be kept without calling the provider."""
        mock_chunk.return_value = ["Hello", "", "World"]
        mock_translate.return_value = "Traduit"
        result = _translate_with_mymemory_chunked("Hello\n\nWorld", "en", "fr")
        # Blank line should be preserved; provider called only for non-empty chunks
        assert result is not None
        assert "\n" in result
        assert mock_translate.call_count == 2  # only non-empty chunks translated

    @patch("on_demand_translate._translate_with_mymemory")
    def test_provider_failure_on_any_chunk_returns_none(self, mock_translate):
        mock_translate.return_value = None
        result = _translate_with_mymemory_chunked("Hello", "en", "fr")
        assert result is None


class TestSplitLongSegmentWordLevel:
    """Additional tests for word-level splitting in _split_long_segment."""

    def test_multiple_short_words_split_at_max_len(self):
        """Words that individually fit but combined exceed max_len."""
        text = "Hello World How Are You Doing"
        result = _split_long_segment(text, 12)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 12

    def test_empty_parts_in_sentence_split(self):
        """Sentence split that produces empty parts is handled gracefully."""
        # re.split on a string like "Hello.  World" won't produce empty parts,
        # but create a scenario where current is non-empty when we overflow.
        text = "First sentence. This is a very long second sentence that exceeds limits."
        result = _split_long_segment(text, 20)
        assert isinstance(result, list)
        assert len(result) >= 1
