"""Cross-user searches answered in SQL over the collection tables.

These used to load every user's JSON file and walk it in Python (delete guards, the
"is this picture visible" check, shared equipment...). Each function is one indexed query.
"""

from typing import Any

from sqlalchemy import and_, distinct, func, or_, select

from db import schema
from db.engine import read

_pictures = schema.astrodex_pictures
_sessions = schema.observation_sessions
_entries = schema.observation_entries
_plans = schema.plans
_equipment = schema.equipment_items
_combinations = schema.equipment_combinations
_combination_equipment = schema.combination_equipment


def _count(query) -> int:
    with read() as conn:
        return int(conn.execute(query).scalar_one())


# --- Astrodex ----------------------------------------------------------------------------


def count_astrodex_pictures(location_id: str | None = None, combination_id: str | None = None) -> int:
    """Pictures (all users) taken at a location preset and/or with a combination."""
    query = select(func.count()).select_from(_pictures)
    if location_id is not None:
        query = query.where(_pictures.c.location_id == location_id)
    if combination_id is not None:
        query = query.where(_pictures.c.combination_id == combination_id)
    return _count(query)


def astrodex_picture_exists(filename: str, user_id: str | None = None) -> bool:
    """Whether an Astrodex picture has this file name (of one user, or of anybody)."""
    query = select(func.count()).select_from(_pictures).where(_pictures.c.filename == filename)
    if user_id is not None:
        query = query.where(_pictures.c.user_id == user_id)
    return _count(query) > 0


# --- Observation log ---------------------------------------------------------------------


def count_sessions_for_location(location_id: str) -> int:
    """Sessions (all users) at a location preset."""
    return _count(select(func.count()).select_from(_sessions).where(_sessions.c.location_id == location_id))


def count_sessions_for_combination(combination_id: str) -> int:
    """Sessions (all users) using a combination, at session level or in any of their entries."""
    entry_sessions = select(_entries.c.parent_pk).where(_entries.c.combination_id == combination_id)
    query = select(func.count(distinct(_sessions.c.pk))).where(
        or_(_sessions.c.combination_id == combination_id, _sessions.c.pk.in_(entry_sessions))
    )
    return _count(query)


# --- Plans -------------------------------------------------------------------------------


def count_plans(location_id: str | None = None, combination_id: str | None = None) -> int:
    """Plans (all users) pinned to a location preset and/or a combination."""
    query = select(func.count()).select_from(_plans)
    if location_id is not None:
        query = query.where(_plans.c.location_id == location_id)
    if combination_id is not None:
        query = query.where(_plans.c.combination_id == combination_id)
    return _count(query)


def plans_for_location(location_id: str) -> list[tuple[str, str]]:
    """``(user_id, doc_key)`` of every plan pinned to a location preset."""
    with read() as conn:
        rows = conn.execute(select(_plans.c.user_id, _plans.c.doc_key).where(_plans.c.location_id == location_id))
        return [(row.user_id, row.doc_key) for row in rows]


# --- Equipment ---------------------------------------------------------------------------

# Combination columns referencing one equipment id, by equipment type
COMBINATION_SCALAR_FIELDS: dict[str, tuple[str, ...]] = {
    'telescopes': ('telescope_id',),
    'cameras': ('camera_id', 'guide_camera_id'),
    'mounts': ('mount_id',),
}
# combination_equipment role referencing a list of equipment ids, by equipment type
COMBINATION_LIST_ROLES: dict[str, str] = {'filters': 'filter', 'accessories': 'accessory'}


def combinations_referencing(equipment_type: str, equipment_id: str) -> list[dict[str, Any]]:
    """``{name, owner_id}`` of every combination (any user) referencing this equipment id."""
    conditions = [_combinations.c[field] == equipment_id for field in COMBINATION_SCALAR_FIELDS.get(equipment_type, ())]
    role = COMBINATION_LIST_ROLES.get(equipment_type)
    if role:
        linked = select(_combination_equipment.c.parent_pk).where(
            and_(_combination_equipment.c.role == role, _combination_equipment.c.equipment_id == equipment_id)
        )
        conditions.append(_combinations.c.pk.in_(linked))
    if not conditions:
        return []
    query = (
        select(_combinations.c.user_id, _combinations.c.name)
        .where(or_(*conditions))
        .order_by(_combinations.c.user_id, _combinations.c.position)
    )
    with read() as conn:
        return [{'name': row.name or '', 'owner_id': row.user_id} for row in conn.execute(query)]


def shared_equipment(equipment_type: str, exclude_user_id: str) -> list[tuple[str, Any]]:
    """``(owner_id, item)`` for every item of ``equipment_type`` shared by another user."""
    query = (
        select(_equipment.c.user_id, _equipment.c.data)
        .where(
            _equipment.c.equipment_type == equipment_type,
            _equipment.c.is_shared.is_(True),
            _equipment.c.user_id != exclude_user_id,
        )
        .order_by(_equipment.c.user_id, _equipment.c.position)
    )
    with read() as conn:
        return [(row.user_id, row.data) for row in conn.execute(query)]
