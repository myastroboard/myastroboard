"""
AstroDex Stream engine - renders the "current frame" of a user's (or the shared) AstroDex
slideshow as a single JPEG, and mints/verifies the per-user signing token that gates it.

See feature-astrodex-stream.md for the full design rationale. In short: this deliberately is
NOT a video stream. The frame is a pure function of wall-clock time (which "slot" the clock
puts us in, and which picture that slot maps to), so there is no per-viewer session and no
background thread - a client (Home Assistant's Generic Camera integration, a browser tab, ...)
just polls the same URL and gets whatever is "now".

No crossfade: a client that polls mid-transition would receive one blended frame and then
display it, static, until its own next poll - which can be much later than the transition
itself, so a half-blended frame would sit on screen looking broken rather than transitioning.
Every frame is one full, clean photo; only which photo changes between slots.

Token scheme: a stream URL embeds an HMAC-SHA256 token of its subject (a user_id, or a fixed
shared-feed marker) keyed by a signing secret generated once on first use and never entered
by an admin (utils.connector_secrets sidecar, like the auto-generated VAPID keys). The token
is a pure function of (subject, secret) - nothing per-user is stored, so verifying a request
just recomputes it. Rotating the secret (see rotate_signing_secret(), wired to an admin-only
"Rotate keys" action) invalidates every existing URL at once - the only revocation mechanism,
documented in the connector's UI copy.
"""

import hashlib
import hmac
import io
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from connectors.astrodex_stream_connector import AstroDexStreamConnector
from observation import astrodex
from utils.connector_secrets import load_secrets, save_secrets
from utils.logging_config import get_logger

logger = get_logger(__name__)

_SHARED_SUBJECT = "__shared__"
_TOKEN_BYTES = 16  # a capability token embedded in a URL, not a MAC needing full SHA-256 length

_CONNECTOR_NAME = AstroDexStreamConnector.name

# feed_key -> {time-bucket: jpeg bytes}. A short TTL just collapses near-simultaneous polls
# (a user's own browser tab + a Home Assistant card both requesting the same feed within the
# same second or two) into a single render; it is not a freshness cache in any other sense.
_FRAME_CACHE: Dict[Tuple[str, str, int], bytes] = {}
_FRAME_CACHE_TTL_SECONDS = 2
_FRAME_CACHE_MAX_ENTRIES = 256

ASPECT_RATIOS: Dict[str, Tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "1:1": (1, 1),
}
DEFAULT_ASPECT_RATIO = "16:9"
RENDER_LONG_EDGE = 1280  # long-edge target; plenty for a still-image poll, keeps renders cheap


# ---------------------------------------------------------------------------
# Signing / tokens
# ---------------------------------------------------------------------------


def _signing_secret() -> str:
    """The connector's per-install signing secret, generated once on first use.

    Read fresh from the sidecar on every call (a small local JSON read) rather than cached
    in memory, so a rotation is picked up by every gunicorn worker without a restart - see
    mqtt_publisher.py's _current_source_signature() for why in-memory caching of a
    cross-worker file is the wrong default in this codebase.
    """
    stored = load_secrets(_CONNECTOR_NAME).get("signing_secret", "")
    if stored:
        return stored
    secret = os.urandom(32).hex()
    if not save_secrets(_CONNECTOR_NAME, {"signing_secret": secret}):
        logger.error("AstroDex Stream: could not persist signing secret - tokens will not survive a restart")
    return secret


def rotate_signing_secret() -> None:
    """Issue a brand new signing secret, invalidating every previously handed-out URL."""
    secret = os.urandom(32).hex()
    if not save_secrets(_CONNECTOR_NAME, {"signing_secret": secret}):
        raise RuntimeError("could not persist rotated signing secret")


def _token_for(subject: str) -> str:
    digest = hmac.new(_signing_secret().encode("utf-8"), subject.encode("utf-8"), hashlib.sha256).digest()
    return digest[:_TOKEN_BYTES].hex()


def personal_token(user_id: str) -> str:
    return _token_for(f"user:{user_id}")


def shared_token() -> str:
    return _token_for(_SHARED_SUBJECT)


def verify_personal_token(user_id: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(_token_for(f"user:{user_id}"), token)


def verify_shared_token(token: str) -> bool:
    return bool(token) and hmac.compare_digest(_token_for(_SHARED_SUBJECT), token)


# ---------------------------------------------------------------------------
# Eligible pictures
# ---------------------------------------------------------------------------


def _eligible_pictures_personal(user_id: str) -> List[Dict[str, Any]]:
    """This user's own pictures, ordered stably, item name attached, no owner (always self)."""
    data = astrodex.load_user_astrodex(user_id)
    pictures: List[Dict[str, Any]] = []
    for item in data.get("items", []) or []:
        item_name = item.get("name", "")
        for picture in item.get("pictures", []) or []:
            filename = picture.get("filename")
            if not filename:
                continue
            pictures.append(
                {
                    "filename": filename,
                    "date": picture.get("date"),
                    "item_name": item_name,
                    "owner_username": None,
                }
            )
    pictures.sort(key=lambda p: (p["item_name"], p["filename"]))
    return pictures


def _eligible_pictures_shared() -> List[Dict[str, Any]]:
    """Every user's pictures in the merged (non-private) view, owner attached, GPS stripped.

    current_user_id="" never matches a real owner, so get_visible_astrodex()'s existing
    per-picture GPS-stripping (private to the picture's owner) applies to every picture here -
    nothing in this feed is treated as "owned by the viewer", which is correct: there is no
    single viewer behind the shared feed.
    """
    visible = astrodex.get_visible_astrodex(current_user_id="", private_mode=False)
    pictures: List[Dict[str, Any]] = []
    for item in visible.get("items", []) or []:
        item_name = item.get("name", "")
        for picture in item.get("pictures", []) or []:
            filename = picture.get("filename")
            if not filename:
                continue
            pictures.append(
                {
                    "filename": filename,
                    "date": picture.get("date"),
                    "item_name": item_name,
                    "owner_username": picture.get("owner_username"),
                }
            )
    pictures.sort(key=lambda p: (p["item_name"], p["filename"]))
    return pictures


# ---------------------------------------------------------------------------
# Frame timing (pure function of wall-clock time)
# ---------------------------------------------------------------------------


def _current_slot(now: float, display_seconds: int) -> int:
    """An ever-increasing slot number - deliberately NOT reduced mod picture count here, so it
    carries no notion of "which picture" on its own. _slot_to_picture_index() maps a slot to a
    picture, which is what makes shuffling possible without this function knowing about
    pictures at all."""
    cycle = max(1, display_seconds)
    return int(now // cycle)


def _raw_cycle_shuffle(seed: str, cycle: int, count: int) -> List[int]:
    """A fixed, seeded shuffle of range(count), with no cross-cycle adjustment - one full,
    non-repeating pass through the collection. Deterministic: the same (seed, cycle) always
    shuffles the same way. Kept separate from _cycle_order() below so that the boundary check
    has an unadjusted value to compare against without recursing into cycle - 1's own
    adjustment (which would make the cost of computing one frame grow with the cycle number,
    i.e. with elapsed time - unacceptable for a function called on every poll)."""
    order = list(range(count))
    random.Random(f"{seed}:{cycle}").shuffle(order)
    return order


def _cycle_order(seed: str, cycle: int, count: int) -> List[int]:
    """The order actually shown for one full cycle - _raw_cycle_shuffle(), with its first two
    positions swapped if the shuffle would otherwise open on the same picture the previous
    cycle closed on. Computed as a whole and indexed by the caller, never recomputed
    per-position - recomputing the swap decision separately for each position independently
    (an earlier version's bug) let position 0's swapped value and position 1's unswapped value
    silently collide, since they disagreed about whether the swap had happened at all.
    """
    order = _raw_cycle_shuffle(seed, cycle, count)
    if count > 1 and cycle > 0:
        previous_last = _raw_cycle_shuffle(seed, cycle - 1, count)[-1]
        if order[0] == previous_last:
            order[0], order[1] = order[1], order[0]
    return order


def _slot_to_picture_index(seed: str, slot: int, count: int) -> int:
    """A pseudo-random but fully reproducible picture index for this slot.

    Same (seed, slot) always maps to the same index - every viewer polling at the same moment
    sees the same picture without any shared state (no thread, no per-viewer session, nothing
    written to disk).

    Slots are grouped into cycles of `count` (one full pass through the collection); within a
    cycle the order is a fixed shuffle, so two adjacent slots in the same cycle can never repeat
    a picture - a permutation never places the same value twice - and _cycle_order() additionally
    resolves the one seam a fresh shuffle cannot rule out on its own: the boundary between two
    cycles (the last picture of one, the first of the next).
    """
    if count <= 1:
        return 0
    if count == 2:
        # With exactly two pictures, strict alternation is the only sequence that never
        # repeats adjacently - there is no other non-repeating arrangement to shuffle between.
        # `start` just picks which of the two a given feed opens on.
        start = random.Random(seed).randrange(2)
        return (slot + start) % 2
    cycle, position = divmod(slot, count)
    return _cycle_order(seed, cycle, count)[position]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _target_size(aspect_ratio: str) -> Tuple[int, int]:
    w_ratio, h_ratio = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS[DEFAULT_ASPECT_RATIO])
    if w_ratio >= h_ratio:
        width = RENDER_LONG_EDGE
        height = round(RENDER_LONG_EDGE * h_ratio / w_ratio)
    else:
        height = RENDER_LONG_EDGE
        width = round(RENDER_LONG_EDGE * w_ratio / h_ratio)
    return max(1, width), max(1, height)


def _center_crop_resize(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = round(src_h * target_ratio)
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = round(src_w / target_ratio)
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return image.resize((target_w, target_h), Image.Resampling.LANCZOS, box=box)


def _load_source_image(filename: str) -> Optional[Image.Image]:
    path = astrodex._resolve_image_file_path(filename)
    if not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as img:
            img.load()
            return img.convert("RGB")
    except Exception as exc:
        logger.warning("AstroDex Stream: could not open picture %r: %s", filename, exc)
        return None


_AnyFont = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]
_font_cache: Dict[int, _AnyFont] = {}


def _font(size: int) -> _AnyFont:
    """DejaVu Sans, bundled by matplotlib (already a hard dependency) - avoids shipping a
    new font asset just for this banner."""
    cached = _font_cache.get(size)
    if cached is not None:
        return cached
    try:
        import matplotlib

        path = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans.ttf")
        font = ImageFont.truetype(path, size)
    except Exception as exc:  # pragma: no cover - matplotlib always ships this file
        logger.warning("AstroDex Stream: could not load DejaVuSans.ttf, falling back to default: %s", exc)
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _format_date(value: Any) -> str:
    if not value:
        return ""
    return str(value).split("T", 1)[0]


def _banner_lines(picture: Dict[str, Any]) -> List[str]:
    lines = []
    name = picture.get("item_name")
    if name:
        lines.append(str(name))
    date_text = _format_date(picture.get("date"))
    if date_text:
        lines.append(date_text)
    owner = picture.get("owner_username")
    if owner:
        lines.append(str(owner))
    return lines


def _draw_banner(image: Image.Image, lines: List[str]) -> Image.Image:
    """A small, semi-transparent bottom-right banner - secondary info, kept discreet."""
    if not lines:
        return image
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = max(14, base.width // 55)
    font = _font(font_size)
    text = "   -   ".join(lines)
    padding = font_size // 2
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    box_w = text_w + padding * 2
    box_h = (bbox[3] - bbox[1]) + padding * 2
    x0 = base.width - box_w - padding
    y0 = base.height - box_h - padding
    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=(0, 0, 0, 110))
    draw.text((x0 + padding, y0 + padding - bbox[1]), text, font=font, fill=(255, 255, 255, 230))
    return Image.alpha_composite(base, overlay).convert("RGB")


def _placeholder_image(target_w: int, target_h: int) -> Image.Image:
    """Generated in-process (no bundled asset) - astrodex.DEFAULT_IMAGE turns out to point at
    an .svg (static/img/default_astro_object.svg), which Pillow cannot rasterize without an
    extra dependency, so this connector never relies on it."""
    frame = Image.new("RGB", (target_w, target_h), (18, 22, 34))
    draw = ImageDraw.Draw(frame)
    font = _font(max(16, target_w // 30))
    text = "AstroDex - no photo yet"
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (target_w - (bbox[2] - bbox[0])) // 2
    y = (target_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=(150, 160, 190))
    return frame


def _encode_jpeg(frame: Image.Image) -> bytes:
    if frame.mode != "RGB":
        frame = frame.convert("RGB")
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def render_current_frame(pictures: List[Dict[str, Any]], config: Dict[str, Any], seed: str = "") -> bytes:
    display_seconds = int(config.get("display_seconds") or 20)
    aspect_ratio = str(config.get("aspect_ratio") or DEFAULT_ASPECT_RATIO)
    target_w, target_h = _target_size(aspect_ratio)

    if not pictures:
        return _encode_jpeg(_placeholder_image(target_w, target_h))

    slot = _current_slot(time.time(), display_seconds)
    idx = _slot_to_picture_index(seed, slot, len(pictures))
    current = pictures[idx]

    base_img = _load_source_image(current["filename"])
    if base_img is None:
        return _encode_jpeg(_placeholder_image(target_w, target_h))
    frame = _center_crop_resize(base_img, target_w, target_h)
    frame = _draw_banner(frame, _banner_lines(current))
    return _encode_jpeg(frame)


def _config_fingerprint(config: Dict[str, Any]) -> str:
    """The subset of config that changes what gets rendered - part of the cache key so a
    config change (or, as in the test suite, varying it between calls) can never return a
    stale render for a different aspect ratio than the one just requested."""
    return "|".join(str(config.get(k)) for k in ("display_seconds", "aspect_ratio"))


def _render_cached(feed_key: str, pictures: List[Dict[str, Any]], config: Dict[str, Any]) -> bytes:
    bucket = int(time.time() // _FRAME_CACHE_TTL_SECONDS)
    cache_key = (feed_key, _config_fingerprint(config), bucket)
    cached = _FRAME_CACHE.get(cache_key)
    if cached is not None:
        return cached
    data = render_current_frame(pictures, config, seed=feed_key)
    _FRAME_CACHE[cache_key] = data
    if len(_FRAME_CACHE) > _FRAME_CACHE_MAX_ENTRIES:
        for key in [k for k in _FRAME_CACHE if k[2] < bucket]:
            _FRAME_CACHE.pop(key, None)
    return data


def personal_frame(user_id: str, config: Dict[str, Any]) -> bytes:
    return _render_cached(f"user:{user_id}", _eligible_pictures_personal(user_id), config)


def shared_frame(config: Dict[str, Any]) -> bytes:
    return _render_cached("shared", _eligible_pictures_shared(), config)
