"""How a user appears to the other members of the instance: display name, avatar, profile.

Every place that shows a person - a shared Astrodex picture, shared equipment, the
Community tab, the navbar - goes through this module, so a member is named the same way
everywhere. The profile itself is stored on the account (``User.profile``, see
``utils/auth.py``), so account deletion erases it and the personal data export carries it;
the avatar picture is a ``<user_id>_avatar_...`` file in ``AVATARS_DIR``, listed in
``utils.user_data.user_data_dirs()`` for the same reason.

Private by default: the display name and avatar only replace the login name where a name
was already shown to others; everything else on the profile (bio, badges, figures,
pictures, equipment, activity) is visible to the other members only once the user joins
the Community and only for the blocks they turn on.

This module imports no feature package, so any module can use it.
"""

import copy
import hashlib
import io
import os
import re
import secrets
import unicodedata
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from PIL import Image, ImageOps

from utils.constants import DATA_DIR
from utils.image_privacy import strip_image_metadata
from utils.logging_config import get_logger

logger = get_logger(__name__)

AVATARS_DIR = os.path.join(DATA_DIR, 'avatars')

DISPLAY_NAME_MAX_LENGTH = 40
BIO_MAX_LENGTH = 280
# Avatars are re-encoded to one small square: enough for a profile header on a phone.
AVATAR_SIZE = 256
AVATAR_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# Refuse decompression bombs before decoding: a 4000 x 4000 phone photo is 16 Mpx.
AVATAR_MAX_PIXELS = 50_000_000
AVATAR_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'webp', 'gif'})

# The profile blocks a member can show to the others, once they join the Community.
COMMUNITY_BLOCKS: tuple[str, ...] = ('badges', 'stats', 'pictures', 'equipment', 'activity')

DEFAULT_PROFILE: dict[str, Any] = {
    'display_name': None,
    'bio': '',
    'avatar': None,
    'community': {
        # Joined the Community: listed in the member directory, profile readable by members.
        'listed': False,
        'show_badges': True,
        'show_stats': True,
        'show_pictures': True,
        'show_equipment': False,
        'show_activity': True,
    },
}

_AVATAR_FILENAME = re.compile(r'^[A-Za-z0-9-]+_avatar_[0-9a-f]{16}\.webp$')
_WHITESPACE = re.compile(r'\s+')

# Background colours of the generated initials avatar; white text reads on each of them.
_INITIALS_COLOURS = ('#4f46e5', '#0e7490', '#047857', '#b45309', '#be123c', '#7c3aed', '#1d4ed8', '#0f766e')


class ProfileError(ValueError):
    """A rejected profile change; ``key`` is the i18n key of the message shown to the user."""

    def __init__(self, message: str, key: str):
        super().__init__(message)
        self.key = key


# ---------------------------------------------------------------------------
# Profile record
# ---------------------------------------------------------------------------


def default_profile() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PROFILE)


def sanitize_profile(raw: Any) -> dict[str, Any]:
    """The stored profile merged over the defaults; unknown or malformed values are dropped.

    Never raises: a hand-edited or older account row must load, at worst with defaults.
    """
    profile = default_profile()
    if not isinstance(raw, dict):
        return profile
    name = raw.get('display_name')
    if isinstance(name, str):
        try:
            profile['display_name'] = normalize_display_name(name)
        except ProfileError:
            profile['display_name'] = None
    bio = raw.get('bio')
    if isinstance(bio, str):
        profile['bio'] = _clean_bio(bio)[:BIO_MAX_LENGTH]
    avatar = raw.get('avatar')
    if isinstance(avatar, dict) and _AVATAR_FILENAME.match(str(avatar.get('filename') or '')):
        profile['avatar'] = {'filename': avatar['filename'], 'updated_at': str(avatar.get('updated_at') or '')}
    community = raw.get('community')
    if isinstance(community, dict):
        for key in profile['community']:
            if isinstance(community.get(key), bool):
                profile['community'][key] = community[key]
    return profile


def normalize_display_name(value: Any) -> str | None:
    """Trimmed display name with inner whitespace collapsed; None when empty.

    Raises ``ProfileError`` for a name that is too long or carries control characters.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileError('Display name must be text', 'profile.error_display_name_invalid')
    text = _WHITESPACE.sub(' ', unicodedata.normalize('NFC', value)).strip()
    if not text:
        return None
    if len(text) > DISPLAY_NAME_MAX_LENGTH:
        raise ProfileError('Display name is too long', 'profile.error_display_name_length')
    if any(unicodedata.category(char) in ('Cc', 'Cf', 'Co', 'Cs') for char in text):
        raise ProfileError('Display name contains invalid characters', 'profile.error_display_name_invalid')
    return text


def _clean_bio(value: str) -> str:
    """Bio text: line breaks kept (at most two in a row), other control characters removed."""
    text = unicodedata.normalize('NFC', value).replace('\r\n', '\n').replace('\r', '\n')
    text = ''.join(char for char in text if char == '\n' or unicodedata.category(char) not in ('Cc', 'Cf', 'Co', 'Cs'))
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(line.rstrip() for line in text.split('\n')).strip()


def apply_profile_update(profile: dict[str, Any], updates: Any) -> dict[str, Any]:
    """A copy of ``profile`` with the user's ``updates`` applied (display name, bio, community).

    The avatar is not set here: it has its own upload route. Raises ``ProfileError``.
    """
    if not isinstance(updates, dict):
        raise ProfileError('Profile payload must be an object', 'profile.error_invalid')
    result = sanitize_profile(profile)
    if 'display_name' in updates:
        result['display_name'] = normalize_display_name(updates['display_name'])
    if 'bio' in updates:
        bio = updates['bio']
        if bio is None:
            bio = ''
        if not isinstance(bio, str):
            raise ProfileError('Bio must be text', 'profile.error_invalid')
        cleaned = _clean_bio(bio)
        if len(cleaned) > BIO_MAX_LENGTH:
            raise ProfileError('Bio is too long', 'profile.error_bio_length')
        result['bio'] = cleaned
    if 'community' in updates:
        community = updates['community']
        if not isinstance(community, dict):
            raise ProfileError('Community settings must be an object', 'profile.error_invalid')
        for key, value in community.items():
            if key not in result['community']:
                continue
            if not isinstance(value, bool):
                raise ProfileError(f'{key} must be true or false', 'profile.error_invalid')
            result['community'][key] = value
    return result


# ---------------------------------------------------------------------------
# Identity as seen by others
# ---------------------------------------------------------------------------


def _profile_of(user: Any) -> dict[str, Any]:
    raw = user.get('profile') if isinstance(user, dict) else getattr(user, 'profile', None)
    return sanitize_profile(raw)


def _field(user: Any, name: str) -> Any:
    return user.get(name) if isinstance(user, dict) else getattr(user, name, None)


def display_name_of(user: Any) -> str:
    """The name shown to others: the display name, or the login name when none is set."""
    return _profile_of(user).get('display_name') or str(_field(user, 'username') or '')


def avatar_url(user: Any) -> str:
    """Address of the user's avatar; a generated initials picture when none was uploaded.

    The ``v`` parameter changes with every new picture or name, so browsers never show a
    stale one.
    """
    profile = _profile_of(user)
    avatar = profile.get('avatar') or {}
    if avatar:
        version = avatar.get('filename', '')[-21:-5]
    else:
        version = hashlib.sha256(display_name_of(user).encode('utf-8')).hexdigest()[:12]
    return f'/api/users/{_field(user, "user_id")}/avatar?v={version}'


def public_identity(user: Any) -> dict[str, Any]:
    """What any member may know about another member: id, name and avatar."""
    return {
        'user_id': _field(user, 'user_id'),
        'display_name': display_name_of(user),
        'avatar_url': avatar_url(user),
        'has_avatar': bool(_profile_of(user).get('avatar')),
    }


def is_listed(user: Any) -> bool:
    """Whether the user joined the Community (listed in the member directory)."""
    return bool(_profile_of(user)['community'].get('listed'))


def shows_block(user: Any, block: str) -> bool:
    """Whether a listed member shows one profile block (``COMMUNITY_BLOCKS``) to the others."""
    community = _profile_of(user)['community']
    return bool(community.get('listed')) and bool(community.get(f'show_{block}'))


def community_enabled(config: Any) -> bool:
    """The admin switch for the whole Community tab (App settings -> Configuration)."""
    block = config.get('community') if isinstance(config, dict) else None
    return not isinstance(block, dict) or block.get('enabled') is not False


# ---------------------------------------------------------------------------
# Avatar pictures
# ---------------------------------------------------------------------------


def is_avatar_filename(filename: Any) -> bool:
    return isinstance(filename, str) and bool(_AVATAR_FILENAME.match(filename))


def avatar_path(filename: str) -> str | None:
    """Absolute path of a stored avatar, or None for a name that is not one of ours."""
    if not is_avatar_filename(filename):
        return None
    base_dir = os.path.realpath(AVATARS_DIR)
    path = os.path.realpath(os.path.join(base_dir, filename))
    return path if path.startswith(base_dir + os.sep) else None


def process_avatar(data: bytes) -> bytes:
    """Square ``AVATAR_SIZE`` WebP from an uploaded picture, with no metadata at all.

    The picture is decoded and re-encoded from its pixels, which drops EXIF (GPS position,
    camera serials) by construction; ``strip_image_metadata`` runs on the input first
    anyway, as for every upload. Raises ``ProfileError`` for anything that is not a usable
    picture.
    """
    if not data:
        raise ProfileError('Empty file', 'profile.error_avatar_invalid')
    if len(data) > AVATAR_MAX_UPLOAD_BYTES:
        raise ProfileError('Picture is too large', 'profile.error_avatar_too_large')
    try:
        cleaned = strip_image_metadata(data)
        with Image.open(io.BytesIO(cleaned)) as probe:
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > AVATAR_MAX_PIXELS:
                raise ProfileError('Picture is too large', 'profile.error_avatar_too_large')
            probe.seek(0)
            image = ImageOps.exif_transpose(probe) or probe
            image.load()
            image = image.convert('RGBA') if image.mode in ('RGBA', 'LA', 'P') else image.convert('RGB')
    except ProfileError:
        raise
    except Exception as error:
        raise ProfileError(f'Not a readable picture: {error}', 'profile.error_avatar_invalid') from error

    square = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)
    output = io.BytesIO()
    square.save(output, format='WEBP', quality=86, method=4)
    return output.getvalue()


def store_avatar(user_id: str, data: bytes) -> str:
    """Write a processed avatar for ``user_id``; return its file name."""
    if not re.match(r'^[A-Za-z0-9-]+$', str(user_id)):
        raise ProfileError('Invalid user id', 'profile.error_invalid')
    filename = f'{user_id}_avatar_{secrets.token_hex(8)}.webp'
    os.makedirs(AVATARS_DIR, exist_ok=True)
    path = avatar_path(filename)
    if path is None:  # pragma: no cover - the name is built above from a validated id
        raise ProfileError('Invalid file name', 'profile.error_invalid')
    temporary = f'{path}.tmp'
    with open(temporary, 'wb') as handle:
        handle.write(data)
    os.replace(temporary, path)
    return filename


def remove_avatar_file(filename: Any) -> None:
    """Delete a stored avatar; a missing or foreign name is ignored."""
    path = avatar_path(filename) if isinstance(filename, str) else None
    if path is None:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as error:
        logger.warning(f'Could not delete avatar {filename}: {error}')


def _initials(name: str) -> str:
    words = [word for word in re.split(r'[\s._-]+', name or '') if word]
    letters = ''.join(word[0] for word in words[:2]) if len(words) > 1 else (words[0][:2] if words else '?')
    return letters.upper()


def initials_svg(user: Any) -> bytes:
    """A round initials picture for a user without an avatar (no third-party service)."""
    initials = xml_escape(_initials(display_name_of(user)))
    user_id = str(_field(user, 'user_id') or '')
    colour = _INITIALS_COLOURS[sum(user_id.encode('utf-8')) % len(_INITIALS_COLOURS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<circle cx="32" cy="32" r="32" fill="{colour}"/>'
        '<text x="32" y="32" dy="0.35em" text-anchor="middle" fill="#ffffff" '
        'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" font-size="26" font-weight="600">'
        f'{initials}</text></svg>'
    )
    return svg.encode('utf-8')
