"""Split per-user documents into the relational tables, and assemble them back.

A feature module still loads and saves one dict per user (``{"items": [...], ...}``).
On write, each list of objects becomes rows of its table (one row per object, nested
lists in child tables linked by ``parent_pk``); what remains of the document (owner
name, dates) is the header row in ``user_documents``. On read, the same document comes
back, field for field.

Lossless by construction:

- every object row keeps the object itself in ``data`` (minus its split lists); the
  query columns are copies, set only when the value has the column's type;
- a split list is remembered in a reserved ``__split__`` key, so ``"pictures": []`` and
  a missing ``"pictures"`` stay different, and a list holding something that is not an
  object (or a key holding something that is not a list) is stored as is.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import Boolean, Float, String, delete, insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import Table

from db import schema

SPLIT_MARKER = '__split__'
_MISSING = object()


@dataclass(frozen=True)
class Node:
    """One list (or single object) of a document, stored in ``table``."""

    table: Table
    key: str
    # Object fields copied into the same-named query columns
    columns: Tuple[str, ...] = ()
    # False: ``key`` holds one object (a plan), not a list
    many: bool = True
    # The list holds plain values (ids), stored in ``value_column``
    scalar: bool = False
    value_column: Optional[str] = None
    # Constant columns telling apart the nodes sharing one table (equipment type, role)
    fixed: Tuple[Tuple[str, Any], ...] = ()
    children: Tuple['Node', ...] = ()


def _equipment(equipment_type: str) -> Node:
    return Node(
        schema.equipment_items,
        'items',
        ('name', 'is_shared', 'is_disabled'),
        fixed=(('equipment_type', equipment_type),),
    )


KINDS: Dict[str, Node] = {
    'astrodex': Node(
        schema.astrodex_items,
        'items',
        ('name', 'catalogue', 'type', 'created_at'),
        children=(
            Node(
                schema.astrodex_pictures,
                'pictures',
                ('filename', 'date', 'location_id', 'combination_id', 'latitude', 'longitude', 'is_main'),
            ),
        ),
    ),
    'observation_sessions': Node(
        schema.observation_sessions,
        'sessions',
        ('location_id', 'combination_id', 'created_at'),
        children=(
            Node(schema.observation_nights, 'nights', ('date',)),
            Node(
                schema.observation_entries,
                'entries',
                ('night_id', 'name', 'catalogue', 'combination_id', 'astrodex_item_id', 'astrodex_picture_id'),
            ),
            Node(schema.observation_attachments, 'attachments', ('filename',)),
        ),
    ),
    'wishlist': Node(schema.wishlist_items, 'items', ('name', 'catalogue', 'catalogue_group_id', 'priority', 'source')),
    'equipment.telescopes': _equipment('telescopes'),
    'equipment.cameras': _equipment('cameras'),
    'equipment.mounts': _equipment('mounts'),
    'equipment.filters': _equipment('filters'),
    'equipment.accessories': _equipment('accessories'),
    'equipment.combinations': Node(
        schema.equipment_combinations,
        'items',
        ('name', 'telescope_id', 'camera_id', 'guide_camera_id', 'mount_id', 'is_disabled'),
        children=(
            Node(
                schema.combination_equipment,
                'filter_ids',
                scalar=True,
                value_column='equipment_id',
                fixed=(('role', 'filter'),),
            ),
            Node(
                schema.combination_equipment,
                'accessory_ids',
                scalar=True,
                value_column='equipment_id',
                fixed=(('role', 'accessory'),),
            ),
        ),
    ),
    'plan': Node(
        schema.plans,
        'plan',
        ('plan_date', 'location_id', 'combination_id'),
        many=False,
        children=(Node(schema.plan_entries, 'entries', ('name', 'catalogue', 'done')),),
    ),
}

# Every collection table, children before parents (safe deletion order without cascades)
COLLECTION_TABLES: Tuple[Table, ...] = (
    schema.astrodex_pictures,
    schema.astrodex_items,
    schema.observation_nights,
    schema.observation_entries,
    schema.observation_attachments,
    schema.observation_sessions,
    schema.wishlist_items,
    schema.combination_equipment,
    schema.equipment_combinations,
    schema.equipment_items,
    schema.plan_entries,
    schema.plans,
)


def is_collection(kind: str) -> bool:
    """True when documents of ``kind`` are stored in relational tables."""
    return kind in KINDS


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _splittable(node: Node, value: Any) -> bool:
    return isinstance(value, list) if node.many else isinstance(value, dict)


# --- Column values -----------------------------------------------------------------------


def _column_value(table: Table, column: str, value: Any) -> Any:
    """``value`` when it fits the column's type, else None (``data`` keeps the original)."""
    column_type = table.c[column].type
    if isinstance(column_type, Boolean):
        return value if isinstance(value, bool) else None
    if isinstance(column_type, Float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(column_type, String):
        if isinstance(value, str) and (column_type.length is None or len(value) <= column_type.length):
            return value
        return None
    return value  # pragma: no cover - every query column is one of the above


def _owner_filter(node: Node, user_id: Optional[str], doc_key: Optional[str]):
    table = node.table
    conditions = [table.c[name] == value for name, value in node.fixed]
    if user_id is not None:
        conditions.append(table.c.user_id == user_id)
    if doc_key is not None:
        conditions.append(table.c.doc_key == doc_key)
    return conditions


# --- Writing -----------------------------------------------------------------------------


def delete_rows(conn: Connection, kind: str, user_id: Optional[str] = None, doc_key: Optional[str] = None) -> None:
    """Delete the rows of ``kind`` (of one document, one user, or everybody when both are None)."""
    for node in reversed(list(_walk(KINDS[kind]))):
        conn.execute(delete(node.table).where(*_owner_filter(node, user_id, doc_key)))


def delete_user_rows(conn: Connection, user_id: str) -> None:
    """Delete every collection row of a user (account deletion)."""
    for table in COLLECTION_TABLES:
        conn.execute(delete(table).where(table.c.user_id == user_id))


def _insert(
    conn: Connection,
    node: Node,
    user_id: str,
    doc_key: str,
    parent_pk: Optional[int],
    position: int,
    element: Any,
) -> None:
    row: Dict[str, Any] = {'user_id': user_id, 'doc_key': doc_key, 'position': position}
    row.update(dict(node.fixed))
    if parent_pk is not None:
        row['parent_pk'] = parent_pk

    if node.scalar:
        assert node.value_column is not None
        row['data'] = element
        row[node.value_column] = _column_value(node.table, node.value_column, element)
        conn.execute(insert(node.table).values(**row))
        return

    if not isinstance(element, dict):
        row['data'] = element  # not an object: kept as is, no query column
        conn.execute(insert(node.table).values(**row))
        return

    data = dict(element)
    split_children: List[Tuple[Node, Any]] = []
    for child in node.children:
        value = data.get(child.key, _MISSING)
        if value is not _MISSING and _splittable(child, value):
            split_children.append((child, data.pop(child.key)))
    if split_children:
        data[SPLIT_MARKER] = [child.key for child, _value in split_children]
    row['data'] = data
    row['id'] = _column_value(node.table, 'id', element.get('id'))
    for column in node.columns:
        row[column] = _column_value(node.table, column, element.get(column))
    pk = conn.execute(insert(node.table).values(**row).returning(node.table.c.pk)).scalar_one()

    for child, value in split_children:
        items = value if child.many else [value]
        for child_position, child_element in enumerate(items):
            _insert(conn, child, user_id, doc_key, pk, child_position, child_element)


def write(conn: Connection, kind: str, user_id: str, doc_key: str, document: Any) -> Any:
    """Replace the rows of one document; return its header (what goes in ``user_documents``)."""
    node = KINDS[kind]
    delete_rows(conn, kind, user_id, doc_key)
    if not isinstance(document, dict):
        return document
    header = dict(document)
    value = header.get(node.key, _MISSING)
    if value is _MISSING or not _splittable(node, value):
        return header
    header.pop(node.key)
    header[SPLIT_MARKER] = [node.key]
    items = value if node.many else [value]
    for position, element in enumerate(items):
        _insert(conn, node, user_id, doc_key, None, position, element)
    return header


# --- Reading -----------------------------------------------------------------------------


def _rows_by_parent(conn: Connection, node: Node, user_id: str, doc_key: str) -> Dict[Optional[int], List[Any]]:
    table = node.table
    columns = [table.c.pk, table.c.data] + ([table.c.parent_pk] if 'parent_pk' in table.c else [])
    grouped: Dict[Optional[int], List[Any]] = {}
    query = select(*columns).where(*_owner_filter(node, user_id, doc_key)).order_by(table.c.position)
    for row in conn.execute(query):
        parent = row.parent_pk if 'parent_pk' in table.c else None
        grouped.setdefault(parent, []).append(row)
    return grouped


def _assemble(row: Any, node: Node, fetched: Dict[Node, Dict[Optional[int], List[Any]]]) -> Any:
    data = row.data
    if node.scalar or not isinstance(data, dict) or SPLIT_MARKER not in data:
        return data
    data = dict(data)
    split_keys = data.pop(SPLIT_MARKER)
    for child in node.children:
        if child.key not in split_keys:
            continue
        child_rows = fetched[child].get(row.pk, [])
        values = [_assemble(child_row, child, fetched) for child_row in child_rows]
        data[child.key] = values if child.many else (values[0] if values else None)
    return data


def read(conn: Connection, kind: str, user_id: str, doc_key: str, header: Any) -> Any:
    """The full document, from its ``user_documents`` header and its rows."""
    if not isinstance(header, dict) or SPLIT_MARKER not in header:
        return header
    node = KINDS[kind]
    document = dict(header)
    document.pop(SPLIT_MARKER)
    fetched = {each: _rows_by_parent(conn, each, user_id, doc_key) for each in _walk(node)}
    values = [_assemble(row, node, fetched) for row in fetched[node].get(None, [])]
    document[node.key] = values if node.many else (values[0] if values else None)
    return document
