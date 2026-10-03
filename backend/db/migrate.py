"""Run Alembic migrations from the application.

Alembic is configured in code here, so the runtime never depends on an ini file or on
the working directory.
"""

import os
from functools import lru_cache

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from db.engine import get_engine
from utils.logging_config import get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')


def alembic_config() -> Config:
    """An Alembic ``Config`` pointing at ``db/migrations``."""
    config = Config()
    config.set_main_option('script_location', MIGRATIONS_DIR)
    return config


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    """The newest revision shipped with this version of the application (fixed for the process)."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine | None = None) -> str | None:
    """The revision the database is at (``None`` for an empty database)."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade_to_head(engine: Engine | None = None) -> None:
    """Upgrade the database schema to the newest revision (no-op when already there)."""
    engine = engine or get_engine()
    before = current_revision(engine)
    target = head_revision()
    if before == target:
        return
    config = alembic_config()
    with engine.connect() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, 'head')
    logger.info(f"Database schema upgraded from {before or 'empty'} to {target}")


def downgrade_to(revision: str, engine: Engine | None = None) -> None:
    """Downgrade the schema to ``revision`` ("base" removes every table). Used by tests and by hand."""
    config = alembic_config()
    with (engine or get_engine()).connect() as conn:
        config.attributes['connection'] = conn
        command.downgrade(config, revision)
