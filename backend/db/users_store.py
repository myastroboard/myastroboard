"""Accounts (``users`` table).

Rows hold ``User.to_dict()`` in ``data``; ``username``/``role``/dates are copied into
columns for lookups and the uniqueness constraint. Every write bumps the ``users``
store revision in the same transaction.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from db import schema
from db.engine import bump_revision, get_revision, read, transaction

STORE = 'users'

_table = schema.users


def _row(user: dict[str, Any]) -> dict[str, Any]:
    return {
        'user_id': user['user_id'],
        'username': user['username'],
        'role': user['role'],
        'created_at': user.get('created_at'),
        'last_login': user.get('last_login'),
        'data': user,
    }


def get_all_users() -> dict[str, dict[str, Any]]:
    """Every account, keyed by user id."""
    with read() as conn:
        return {row.user_id: row.data for row in conn.execute(select(_table.c.user_id, _table.c.data))}


def get_user(user_id: str) -> dict[str, Any] | None:
    """One account, or None."""
    with read() as conn:
        return conn.execute(select(_table.c.data).where(_table.c.user_id == user_id)).scalar()


def upsert_users(users: Iterable[dict[str, Any]]) -> None:
    """Insert or update accounts. Never deletes: removing an account cascades to all of
    its documents, so that only happens through :func:`delete_user`."""
    rows = [_row(user) for user in users]
    if not rows:
        return
    with transaction() as conn:
        for row in rows:
            stmt = insert(_table).values(**row)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[_table.c.user_id],
                    set_={key: stmt.excluded[key] for key in row if key != 'user_id'},
                )
            )
        bump_revision(conn, STORE)


def insert_imported_user(user: dict[str, Any]) -> None:
    """Insert one account from the legacy import; the id must not exist yet."""
    with transaction() as conn:
        conn.execute(insert(_table).values(**_row(user)))
        bump_revision(conn, STORE)


def delete_user(user_id: str) -> bool:
    """Delete an account and every document it owns (right to erasure).

    The documents are deleted explicitly, in the same transaction; the foreign key's
    ON DELETE CASCADE is the safety net behind it.
    """
    from db import documents  # documents imports nothing from here; lazy keeps the module order free

    with transaction() as conn:
        documents.delete_user_documents(conn, user_id)
        result = conn.execute(delete(_table).where(_table.c.user_id == user_id))
        if result.rowcount:
            bump_revision(conn, STORE)
        return bool(result.rowcount)


def users_revision() -> int:
    """Revision of the users store, for the per-process user cache."""
    return get_revision(STORE)
