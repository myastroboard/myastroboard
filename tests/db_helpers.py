"""Database helpers for tests only (no production code needs them)."""

from sqlalchemy import delete

from db import schema
from db.engine import transaction


def delete_setting(key):
    """Remove a setting, as on a brand-new install."""
    with transaction() as conn:
        conn.execute(delete(schema.settings).where(schema.settings.c.key == key))
