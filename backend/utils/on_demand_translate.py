"""
On-demand translation helper for dynamic third-party content.

Uses free, no-key external providers and keeps a small in-memory cache to
avoid repeated calls for identical text.
"""

from __future__ import annotations

import html
import re
import time
from typing import Dict, List, Tuple

import requests

from utils.logging_config import get_logger

logger = get_logger(__name__)

_TRANSLATION_CACHE: Dict[Tuple[str, str, str], Tuple[str, float, str]] = {}
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_MAX_ENTRIES = 2000
_MAX_TEXT_LENGTH = 5000
_MYMEMORY_MAX_QUERY_CHARS = 450


def _cache_get(key: Tuple[str, str, str]) -> Tuple[str, str] | None:
    cached = _TRANSLATION_CACHE.get(key)
    if not cached:
        return None
    translated_text, created_at, provider = cached
    if (time.time() - created_at) > _CACHE_TTL_SECONDS:
        _TRANSLATION_CACHE.pop(key, None)
        return None
    return translated_text, provider


def _cache_set(key: Tuple[str, str, str], translated_text: str, provider: str) -> None:
    if len(_TRANSLATION_CACHE) >= _CACHE_MAX_ENTRIES:
        # Dict preserves insertion order; drop the oldest cache entry.
        oldest = next(iter(_TRANSLATION_CACHE), None)
        if oldest is not None:  # pragma: no branch
            _TRANSLATION_CACHE.pop(oldest, None)
    _TRANSLATION_CACHE[key] = (translated_text, time.time(), provider)


def _translate_with_mymemory(text: str, source_lang: str, target_lang: str) -> str | None:
    """Translate text using MyMemory free endpoint (no API key required)."""
    url = "https://api.mymemory.translated.net/get"
    params = {
        "q": text,
        "langpair": f"{source_lang}|{target_lang}",
    }
    try:
        response = requests.get(url, params=params, timeout=8)
        if not response.ok:
            return None
        payload = response.json()
        translated = payload.get("responseData", {}).get("translatedText")
        if not isinstance(translated, str):
            return None
        translated = html.unescape(translated).strip()
        if not translated:
            return None
        return translated
    except Exception as exc:
        logger.debug(f"MyMemory translation request failed: {exc}")
        return None


def _split_long_segment(segment: str, max_len: int) -> List[str]:
    """Split a long segment by sentence-like boundaries, then by whitespace if needed."""
    if len(segment) <= max_len:
        return [segment]

    pieces: List[str] = []
    # Keep sentence punctuation attached to each sentence.
    sentence_parts = re.split(r"(?<=[.!?])\s+", segment)
    current = ""

    for part in sentence_parts:
        if not part:
            continue
        candidate = part if not current else f"{current} {part}"
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""

        if len(part) <= max_len:
            current = part
            continue

        # Last resort: split a very long sentence by whitespace.
        words = part.split()
        line = ""
        for word in words:
            candidate_word_line = word if not line else f"{line} {word}"
            if len(candidate_word_line) <= max_len:
                line = candidate_word_line
            else:
                if line:
                    pieces.append(line)
                # If one token is still too long, hard-wrap it.
                if len(word) > max_len:
                    for i in range(0, len(word), max_len):
                        pieces.append(word[i : i + max_len])
                    line = ""
                else:
                    line = word
        if line:
            current = line

    if current:
        pieces.append(current)

    return pieces


def _chunk_text_for_provider(text: str, max_len: int) -> List[str]:
    """
    Build provider-safe chunks preserving paragraph boundaries where possible.
    """
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    paragraphs = text.split("\n")

    for paragraph in paragraphs:
        if not paragraph:
            # Preserve blank lines.
            chunks.append("")
            continue
        chunks.extend(_split_long_segment(paragraph, max_len))

    return chunks


def _translate_with_mymemory_chunked(text: str, source_lang: str, target_lang: str) -> str | None:
    """
    Translate text with transparent chunking to stay within provider query limits.
    """
    chunks = _chunk_text_for_provider(text, _MYMEMORY_MAX_QUERY_CHARS)
    translated_chunks: List[str] = []

    for chunk in chunks:
        if not chunk:
            translated_chunks.append("")
            continue
        translated_chunk = _translate_with_mymemory(chunk, source_lang, target_lang)
        if not translated_chunk:
            return None
        translated_chunks.append(translated_chunk)

    # Rebuild text and keep paragraph breaks.
    return "\n".join(translated_chunks)


def translate_text_on_demand(text: str, source_lang: str, target_lang: str) -> dict:
    """
    Translate dynamic text for UI on-demand.

    Returns a consistent payload even when the external service is unavailable.
    """
    source = (source_lang or "en").split("-")[0].lower().strip()
    target = (target_lang or "en").split("-")[0].lower().strip()
    original_text = (text or "").strip()

    if not original_text:
        return {
            "success": False,
            "translated_text": "",
            "source_lang": source,
            "target_lang": target,
            "cached": False,
            "provider": "none",
            "error": "missing_text",
        }

    if len(original_text) > _MAX_TEXT_LENGTH:
        return {
            "success": False,
            "translated_text": original_text,
            "source_lang": source,
            "target_lang": target,
            "cached": False,
            "provider": "none",
            "error": "text_too_long",
        }

    if source == target:
        return {
            "success": True,
            "translated_text": original_text,
            "source_lang": source,
            "target_lang": target,
            "cached": False,
            "provider": "none",
            "error": None,
        }

    cache_key = (source, target, original_text)
    cached = _cache_get(cache_key)
    if cached is not None:
        translated_text, provider = cached
        return {
            "success": True,
            "translated_text": translated_text,
            "source_lang": source,
            "target_lang": target,
            "cached": True,
            "provider": provider,
            "error": None,
        }

    translated = _translate_with_mymemory_chunked(original_text, source, target)
    if translated:
        _cache_set(cache_key, translated, "mymemory")
        return {
            "success": True,
            "translated_text": translated,
            "source_lang": source,
            "target_lang": target,
            "cached": False,
            "provider": "mymemory",
            "error": None,
        }

    # Graceful fallback: keep original content visible and let frontend show
    # an unobtrusive "translation unavailable" hint.
    return {
        "success": False,
        "translated_text": original_text,
        "source_lang": source,
        "target_lang": target,
        "cached": False,
        "provider": "none",
        "error": "provider_unavailable",
    }
