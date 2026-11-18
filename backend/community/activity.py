"""The activity feed and the "together" totals of the Community.

The feed is chronological (the latest days with something new) and grouped by member and
day ("Sam, 14 November: 2 new objects, 3 pictures, a badge"), never sorted by how much
someone did. The totals add every member
up into one shared figure ("together: 96 of 110 Messier objects") and point at what nobody
has captured yet - something to go after together, not a podium.

Who takes part:

- the feed: listed members who show their activity; inside it, badges only for members who
  also show their badges (and kept badges on), pictures only when they show their pictures
  and the instance shares Astrodex pictures;
- the totals: listed members who show their figures.
"""

import datetime
import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

from community import members
from observation import achievement_definitions, achievements
from utils import user_identity

# The feed shows the latest days with something new, however old: a quiet instance still
# has a history to look at. ``days`` narrows it when a caller wants a window.
FEED_DAYS: int | None = None
FEED_LIMIT = 40
PROFILE_FEED_LIMIT = 10
FEED_ITEMS_PER_KIND = 6
REMAINING_EXAMPLES = 8


def _natural_key(text: str) -> tuple:
    """ "M 2" before "M 10"."""
    parts: list[Any] = []
    number = ''
    for char in text:
        if char.isdigit():
            number += char
            continue
        if number:
            parts.append((0, int(number)))
            number = ''
        parts.append((1, char.casefold()))
    if number:
        parts.append((0, int(number)))
    return tuple(parts)


def _member_digests(member: dict[str, Any], since: str, pictures_shared: bool) -> list[dict[str, Any]]:
    """One member's feed entries since ``since`` (YYYY-MM-DD), one per day with something new."""
    user = member['user']
    facts = member['facts']
    days: dict[str, dict[str, list]] = {}

    def day_entry(day: str) -> dict[str, list]:
        return days.setdefault(day, {'new_objects': [], 'pictures': [], 'badges': []})

    for capture in facts.get('captures', {}).values():
        day = capture.get('first_date') or ''
        if day and day >= since:
            day_entry(day)['new_objects'].append(
                {'name': capture.get('preferred_name') or capture.get('name'), 'object_class': capture['object_class']}
            )
    if user_identity.shows_block(user, 'pictures') and pictures_shared:
        for picture in members.member_pictures(member['items']):
            if picture['date'] and picture['date'] >= since:
                day_entry(picture['date'])['pictures'].append(
                    {'filename': picture['filename'], 'item_name': picture['item_name']}
                )
    if members.badges_allowed(user):
        for badge in member.get('badges') or []:
            day = badge.get('earned_on') or ''
            if day and day >= since:
                day_entry(day)['badges'].append(badge)

    identity = user_identity.public_identity(user)
    digests = []
    for day, entry in days.items():
        entry['new_objects'].sort(key=lambda item: _natural_key(str(item['name'] or '')))
        digests.append(
            {
                'date': day,
                'member': identity,
                'new_objects_count': len(entry['new_objects']),
                'new_objects': entry['new_objects'][:FEED_ITEMS_PER_KIND],
                'pictures_count': len(entry['pictures']),
                'pictures': entry['pictures'][:FEED_ITEMS_PER_KIND],
                'badges': entry['badges'],
            }
        )
    return digests


def build_feed(
    member_data: Iterable[dict[str, Any]],
    today: datetime.date,
    *,
    pictures_shared: bool,
    days: int | None = FEED_DAYS,
    limit: int = FEED_LIMIT,
) -> list[dict[str, Any]]:
    """The newest digests of every member taking part, newest day first.

    ``member_data`` entries come from ``members.load_member_data`` plus a ``badges`` list
    (``members.earned_badges``).
    """
    since = (today - datetime.timedelta(days=days)).isoformat() if days is not None else ''
    upcoming = (today + datetime.timedelta(days=1)).isoformat()
    digests: list[dict[str, Any]] = []
    for member in member_data:
        if not user_identity.shows_block(member['user'], 'activity'):
            continue
        digests.extend(
            digest for digest in _member_digests(member, since, pictures_shared) if digest['date'] <= upcoming
        )
    digests.sort(key=lambda digest: (digest['date'], digest['member']['display_name'].casefold()), reverse=True)
    return digests[: max(0, int(limit))]


def build_together(member_data: Iterable[dict[str, Any]], totals: dict[str, int]) -> dict[str, Any]:
    """Everyone's progress added up, and what nobody has captured yet in each catalogue."""
    contributing = [member for member in member_data if user_identity.shows_block(member['user'], 'stats')]
    keys: set[str] = set()
    captures_by_key: dict[str, dict[str, Any]] = {}
    minutes = 0.0
    nights = 0
    constellations: set[str] = set()
    for member in contributing:
        facts = member['facts']
        for key, capture in facts.get('captures', {}).items():
            keys.add(key)
            captures_by_key.setdefault(key, capture)
            if capture.get('constellation'):
                constellations.add(capture['constellation'])
        minutes += sum(value for _day, value, _key in facts.get('integration', []))
        nights += len({night.get('date') for night in facts.get('nights', []) if night.get('date')})

    union_facts = {'captures': captures_by_key}
    catalogues = []
    for row in achievements.catalogue_progress(union_facts, totals, achievement_definitions.BADGE_CATALOGUES):
        if row['captured'] <= 0:
            continue
        remaining = []
        if row['captured'] < row['total']:
            try:
                remaining = sorted(
                    (
                        member['identifier']
                        for member in achievements.catalogue_members(row['catalogue'])
                        if member['target_id'] not in keys
                    ),
                    key=_natural_key,
                )
            except Exception:
                remaining = []
        catalogues.append({**row, 'remaining_examples': remaining[:REMAINING_EXAMPLES]})

    return {
        'members': len(contributing),
        'objects': len(keys),
        'integration_minutes': round(minutes, 1),
        'nights': nights,
        'constellations': len(constellations),
        'catalogues': catalogues,
    }


class TtlCache:
    """A tiny per-process cache for the Community payloads (rebuilt at most every ``ttl`` s).

    The feed reads every member's log and Astrodex; a short cache keeps a busy page cheap
    while staying fresh enough for a feed.
    """

    def __init__(self, ttl: float = 60.0, max_entries: int = 16):
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        # Shared by the request threads of the process.
        self._lock = threading.Lock()

    def get(self, key: Any, now: float) -> Any:
        with self._lock:
            hit = self._entries.get(key)
        if hit is None or now - hit[0] > self.ttl:
            return None
        return hit[1]

    def put(self, key: Any, value: Any, now: float) -> None:
        with self._lock:
            self._entries[key] = (now, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
