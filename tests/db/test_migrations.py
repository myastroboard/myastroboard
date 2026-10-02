"""Alembic migrations: they apply cleanly both ways and match the table definitions."""

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from db import engine as db_engine
from db import migrate, schema


def _fresh_engine(tmp_path):
    return db_engine.configure_engine(f"sqlite:///{tmp_path / 'fresh.db'}")


def test_upgrade_from_empty_reaches_head(tmp_path):
    """An empty database is upgraded to the newest revision with every table present."""
    engine = _fresh_engine(tmp_path)
    assert migrate.current_revision(engine) is None

    migrate.upgrade_to_head(engine)

    assert migrate.current_revision(engine) == migrate.head_revision()
    tables = set(inspect(engine).get_table_names())
    assert set(schema.metadata.tables) <= tables


def test_upgrade_is_a_no_op_at_head(tmp_path):
    """Running the upgrade twice changes nothing the second time."""
    engine = _fresh_engine(tmp_path)
    migrate.upgrade_to_head(engine)
    migrate.upgrade_to_head(engine)
    assert migrate.current_revision(engine) == migrate.head_revision()


def test_downgrade_to_base_and_back(tmp_path):
    """Every revision can be rolled back to an empty schema and re-applied."""
    engine = _fresh_engine(tmp_path)
    migrate.upgrade_to_head(engine)

    migrate.downgrade_to('base', engine)
    assert migrate.current_revision(engine) is None
    assert set(inspect(engine).get_table_names()) <= {'alembic_version'}

    migrate.upgrade_to_head(engine)
    assert migrate.current_revision(engine) == migrate.head_revision()


def test_migrations_match_table_definitions(tmp_path):
    """db/schema.py and the migration scripts describe the same schema (no missing revision)."""
    engine = _fresh_engine(tmp_path)
    migrate.upgrade_to_head(engine)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={'compare_type': True})
        assert compare_metadata(context, schema.metadata) == []


def test_connection_pragmas(tmp_path):
    """Connections enforce foreign keys and use the WAL journal (the application defaults)."""
    engine = db_engine.configure_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    migrate.upgrade_to_head(engine)
    with db_engine.read() as conn:
        assert conn.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert str(conn.exec_driver_sql('PRAGMA journal_mode').scalar()).lower() == 'wal'
