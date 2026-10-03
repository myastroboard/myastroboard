"""Per-user documents: one dict per user and kind, stored relationally.

A document is the dict a feature module used to keep in ``<user_id>_<kind>.json``. For
the kinds listed in ``db/collections.py`` its lists live in their own tables (one row per
object) and ``user_documents`` holds the rest (the header); this module hides that: a
document goes in and comes back whole. Every write bumps the ``doc:<kind>`` store
revision in the same transaction.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from db import collections, schema
from db.engine import bump_revision, read, transaction

_table = schema.user_documents


def _store(kind: str) -> str:
    return f'doc:{kind}'


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _assemble(conn: Connection, user_id: str, kind: str, doc_key: str, header: Any) -> Any:
    if collections.is_collection(kind):
        return collections.read(conn, kind, user_id, doc_key, header)
    return header


def get_document(user_id: str, kind: str, doc_key: str = '') -> dict[str, Any] | None:
    """The stored document, or ``None`` when the user has none of this kind/key."""
    with read() as conn:
        header = conn.execute(
            select(_table.c.data).where(_table.c.user_id == user_id, _table.c.kind == kind, _table.c.doc_key == doc_key)
        ).scalar()
        if header is None:
            return None
        return _assemble(conn, user_id, kind, doc_key, header)


def put_document(user_id: str, kind: str, data: dict[str, Any], doc_key: str = '') -> None:
    """Insert or replace a document. The user must exist (foreign key)."""
    now = _now()
    fields = data if isinstance(data, dict) else {}
    created_at = fields.get('created_at') if isinstance(fields.get('created_at'), str) else now
    updated_at = fields.get('updated_at') if isinstance(fields.get('updated_at'), str) else now
    with transaction() as conn:
        header = collections.write(conn, kind, user_id, doc_key, data) if collections.is_collection(kind) else data
        stmt = insert(_table).values(
            user_id=user_id, kind=kind, doc_key=doc_key, data=header, created_at=created_at, updated_at=updated_at
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[_table.c.user_id, _table.c.kind, _table.c.doc_key],
            set_={'data': stmt.excluded.data, 'updated_at': stmt.excluded.updated_at},
        )
        conn.execute(stmt)
        bump_revision(conn, _store(kind))


def delete_document(user_id: str, kind: str, doc_key: str = '') -> bool:
    """Delete one document; True when it existed."""
    with transaction() as conn:
        if collections.is_collection(kind):
            collections.delete_rows(conn, kind, user_id, doc_key)
        result = conn.execute(
            delete(_table).where(_table.c.user_id == user_id, _table.c.kind == kind, _table.c.doc_key == doc_key)
        )
        if result.rowcount:
            bump_revision(conn, _store(kind))
        return bool(result.rowcount)


def delete_kind(kind: str) -> None:
    """Delete every document of ``kind``, all users (backup restore)."""
    with transaction() as conn:
        if collections.is_collection(kind):
            collections.delete_rows(conn, kind)
        conn.execute(delete(_table).where(_table.c.kind == kind))
        bump_revision(conn, _store(kind))


def delete_user_documents(conn: Connection, user_id: str) -> list[str]:
    """Delete every document of a user inside the caller's transaction; return the kinds touched."""
    kinds = sorted(set(conn.execute(select(_table.c.kind).where(_table.c.user_id == user_id)).scalars()))
    collections.delete_user_rows(conn, user_id)
    conn.execute(delete(_table).where(_table.c.user_id == user_id))
    for kind in kinds:
        bump_revision(conn, _store(kind))
    return kinds


def list_documents(kind: str, doc_key: str | None = None) -> list[tuple[str, str, dict[str, Any]]]:
    """``(user_id, doc_key, data)`` for every document of ``kind`` (optionally one ``doc_key``)."""
    query = select(_table.c.user_id, _table.c.doc_key, _table.c.data).where(_table.c.kind == kind)
    if doc_key is not None:
        query = query.where(_table.c.doc_key == doc_key)
    with read() as conn:
        rows = conn.execute(query.order_by(_table.c.user_id, _table.c.doc_key)).all()
        return [(row.user_id, row.doc_key, _assemble(conn, row.user_id, kind, row.doc_key, row.data)) for row in rows]


def list_user_documents(user_id: str, kind: str) -> list[tuple[str, dict[str, Any]]]:
    """``(doc_key, data)`` for every document of ``kind`` owned by ``user_id``."""
    query = (
        select(_table.c.doc_key, _table.c.data)
        .where(_table.c.user_id == user_id, _table.c.kind == kind)
        .order_by(_table.c.doc_key)
    )
    with read() as conn:
        rows = conn.execute(query).all()
        return [(row.doc_key, _assemble(conn, user_id, kind, row.doc_key, row.data)) for row in rows]


def list_all_user_documents(user_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    """``(kind, doc_key, data)`` for every document of ``user_id`` (personal data export)."""
    query = (
        select(_table.c.kind, _table.c.doc_key, _table.c.data)
        .where(_table.c.user_id == user_id)
        .order_by(_table.c.kind, _table.c.doc_key)
    )
    with read() as conn:
        rows = conn.execute(query).all()
        return [(row.kind, row.doc_key, _assemble(conn, user_id, row.kind, row.doc_key, row.data)) for row in rows]
