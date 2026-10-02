"""Table definitions (SQLAlchemy Core).

This metadata is what Alembic compares against when generating a revision; any change
here needs a matching revision in ``db/migrations/versions/`` (the CI drift check fails
otherwise).

Per-user data is relational: one row per Astrodex item, picture, observation session,
night, entry, attachment, wishlist item, piece of equipment, combination and plan entry,
with parent -> child foreign keys (ON DELETE CASCADE), an index on every column used to
search across users, and a unique natural id per user where the application relies on
one. ``user_documents`` keeps what is left of each per-user document once its lists are
split into those tables (owner name, dates).

Each object row also carries its own fields in ``data`` (JSON), which is what the
application reads back: the query columns are derived from it on every write, so a field
the schema does not know yet is never lost. ``db/collections.py`` does the splitting and
assembling; the feature modules keep working on plain dicts.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

# Deterministic constraint names, so batch (copy-and-move) migrations on SQLite can
# find and alter them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

users = Table(
    "users",
    metadata,
    Column("user_id", String(64), primary_key=True),
    Column("username", String(255), nullable=False, unique=True),
    Column("role", String(32), nullable=False),
    Column("created_at", String(40)),
    Column("last_login", String(40)),
    # The full User.to_dict(); the columns above duplicate its lookup fields.
    Column("data", JSON, nullable=False),
)

user_documents = Table(
    "user_documents",
    metadata,
    Column("user_id", String(64), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
    # Document family, e.g. "astrodex", "observation_sessions", "equipment.cameras", "plan".
    Column("kind", String(64), primary_key=True),
    # Distinguishes several documents of one kind for one user (plan per combination); "" otherwise.
    Column("doc_key", String(128), primary_key=True, server_default=""),
    Column("data", JSON, nullable=False),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

Index("ix_user_documents_kind", user_documents.c.kind)

settings = Table(
    "settings",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("data", JSON, nullable=False),
    Column("updated_at", String(40)),
)

# Monotonic per-store counter, bumped in the same transaction as every write to the
# store. Per-process caches compare it to see writes made by other gunicorn workers
# (it replaces the file-mtime checks used when the stores were JSON files).
store_revisions = Table(
    "store_revisions",
    metadata,
    Column("store", String(64), primary_key=True),
    Column("revision", Integer, nullable=False, server_default="0"),
)

# One row per legacy JSON file seen by the one-shot importer (see db/legacy_import.py).
legacy_import = Table(
    "legacy_import",
    metadata,
    Column("path", String(512), primary_key=True),
    Column("sha256", String(64)),
    # imported | orphaned | deleted | failed
    Column("status", String(16), nullable=False),
    Column("imported_at", String(40)),
    Column("deleted_at", String(40)),
    Column("detail", Text),
)


# --- Per-user collections ----------------------------------------------------------------
#
# Every collection table has the same bookkeeping columns: ``pk`` (surrogate key),
# ``user_id``/``doc_key`` (which document the row belongs to), ``parent_pk`` (the row it
# belongs to, for nested lists), ``position`` (order in its list), ``id`` (the
# application's own id, when the object has one) and ``data`` (the object, see above).


def _collection_table(name, *columns, parent=None, unique_id=False):
    """A collection table with the shared bookkeeping columns plus ``columns``."""
    table_columns = [
        Column("pk", Integer, primary_key=True, autoincrement=True),
        Column("user_id", String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        Column("doc_key", String(128), nullable=False, server_default=""),
    ]
    if parent is not None:
        table_columns.append(
            Column("parent_pk", Integer, ForeignKey(f"{parent}.pk", ondelete="CASCADE"), nullable=False)
        )
    table_columns += [
        Column("position", Integer, nullable=False),
        Column("id", String(128)),
        *columns,
        Column("data", JSON, nullable=False),
    ]
    constraints = [UniqueConstraint("user_id", "doc_key", "id")] if unique_id else []
    table = Table(name, metadata, *table_columns, *constraints)
    Index(f"ix_{name}_owner", table.c.user_id, table.c.doc_key)
    if parent is not None:
        Index(f"ix_{name}_parent", table.c.parent_pk)
    return table


astrodex_items = _collection_table(
    "astrodex_items",
    Column("name", String(255)),
    Column("catalogue", String(64)),
    Column("type", String(64)),
    Column("created_at", String(40)),
    unique_id=True,
)
astrodex_pictures = _collection_table(
    "astrodex_pictures",
    Column("filename", String(255)),
    Column("date", String(40)),
    Column("location_id", String(64)),
    Column("combination_id", String(64)),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("is_main", Boolean),
    parent="astrodex_items",
)
Index("ix_astrodex_pictures_filename", astrodex_pictures.c.filename)
Index("ix_astrodex_pictures_location_id", astrodex_pictures.c.location_id)
Index("ix_astrodex_pictures_combination_id", astrodex_pictures.c.combination_id)

observation_sessions = _collection_table(
    "observation_sessions",
    Column("location_id", String(64)),
    Column("combination_id", String(64)),
    Column("created_at", String(40)),
    unique_id=True,
)
Index("ix_observation_sessions_location_id", observation_sessions.c.location_id)
Index("ix_observation_sessions_combination_id", observation_sessions.c.combination_id)
observation_nights = _collection_table(
    "observation_nights",
    Column("date", String(40)),
    parent="observation_sessions",
)
observation_entries = _collection_table(
    "observation_entries",
    Column("night_id", String(64)),
    Column("name", String(255)),
    Column("catalogue", String(64)),
    Column("combination_id", String(64)),
    Column("astrodex_item_id", String(64)),
    Column("astrodex_picture_id", String(64)),
    parent="observation_sessions",
)
Index("ix_observation_entries_combination_id", observation_entries.c.combination_id)
observation_attachments = _collection_table(
    "observation_attachments",
    Column("filename", String(255)),
    parent="observation_sessions",
)

wishlist_items = _collection_table(
    "wishlist_items",
    Column("name", String(255)),
    Column("catalogue", String(64)),
    Column("catalogue_group_id", String(128)),
    Column("priority", String(16)),
    Column("source", String(32)),
    unique_id=True,
)

# Telescopes, cameras, mounts, filters and accessories: one table, told apart by
# ``equipment_type`` (one list per user and type).
equipment_items = _collection_table(
    "equipment_items",
    Column("equipment_type", String(32), nullable=False),
    Column("name", String(255)),
    Column("is_shared", Boolean),
    Column("is_disabled", Boolean),
)
Index("ix_equipment_items_type_shared", equipment_items.c.equipment_type, equipment_items.c.is_shared)
Index(
    "uq_equipment_items_owner_id",
    equipment_items.c.user_id,
    equipment_items.c.equipment_type,
    equipment_items.c.id,
    unique=True,
)

equipment_combinations = _collection_table(
    "equipment_combinations",
    Column("name", String(255)),
    Column("telescope_id", String(64)),
    Column("camera_id", String(64)),
    Column("guide_camera_id", String(64)),
    Column("mount_id", String(64)),
    Column("is_disabled", Boolean),
    unique_id=True,
)
Index("ix_equipment_combinations_telescope_id", equipment_combinations.c.telescope_id)
Index("ix_equipment_combinations_camera_id", equipment_combinations.c.camera_id)
Index("ix_equipment_combinations_mount_id", equipment_combinations.c.mount_id)
# The filter_ids / accessory_ids lists of a combination, one row per referenced id. No
# foreign key to equipment_items on purpose: a combination may reference another user's
# shared item, and a dangling reference is a normal state the app reports as "invalid".
combination_equipment = _collection_table(
    "combination_equipment",
    Column("role", String(16), nullable=False),
    Column("equipment_id", String(64)),
    parent="equipment_combinations",
)
Index("ix_combination_equipment_equipment_id", combination_equipment.c.equipment_id)

# One row per stored plan (doc_key = combination id, or "default").
plans = _collection_table(
    "plans",
    Column("plan_date", String(40)),
    Column("location_id", String(64)),
    Column("combination_id", String(64)),
)
Index("uq_plans_owner", plans.c.user_id, plans.c.doc_key, unique=True)
Index("ix_plans_location_id", plans.c.location_id)
Index("ix_plans_combination_id", plans.c.combination_id)
plan_entries = _collection_table(
    "plan_entries",
    Column("name", String(255)),
    Column("catalogue", String(64)),
    Column("done", Boolean),
    parent="plans",
)
