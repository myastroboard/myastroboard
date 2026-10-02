"""Alembic environment.

Runs both from the application (``db.migrate.upgrade_to_head``, which hands over an
open connection) and from the Alembic command line during development:

    alembic -c backend/db/alembic.ini revision --autogenerate -m "describe the change"
    alembic -c backend/db/alembic.ini upgrade head
"""

import os
import sys

from alembic import context

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _BACKEND_DIR not in sys.path:  # pragma: no cover - only when started from the Alembic CLI
    sys.path.insert(0, _BACKEND_DIR)

from db import schema  # noqa: E402
from db.engine import get_engine  # noqa: E402

config = context.config
target_metadata = schema.metadata


def _configure_and_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place: "batch" mode rebuilds the table.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get('connection')
    if connection is not None:
        _configure_and_run(connection)
        return
    with get_engine().connect() as connection:  # pragma: no cover - Alembic CLI path
        _configure_and_run(connection)


if context.is_offline_mode():  # pragma: no cover - SQL script generation is not used
    raise RuntimeError('Offline (--sql) migrations are not supported')

run_migrations_online()
