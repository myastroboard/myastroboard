"""Initial schema: accounts, settings, per-user collections (relational), store revisions, import log.

Revision ID: 0001
Revises:
Create Date: 2026-10-01 21:41:44.176725
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'legacy_import',
        sa.Column('path', sa.String(length=512), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('imported_at', sa.String(length=40), nullable=True),
        sa.Column('deleted_at', sa.String(length=40), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('path', name=op.f('pk_legacy_import')),
    )
    op.create_table(
        'settings',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint('key', name=op.f('pk_settings')),
    )
    op.create_table(
        'store_revisions',
        sa.Column('store', sa.String(length=64), nullable=False),
        sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('store', name=op.f('pk_store_revisions')),
    )
    op.create_table(
        'users',
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=True),
        sa.Column('last_login', sa.String(length=40), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_users')),
        sa.UniqueConstraint('username', name=op.f('uq_users_username')),
    )
    op.create_table(
        'astrodex_items',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('catalogue', sa.String(length=64), nullable=True),
        sa.Column('type', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.String(length=40), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_astrodex_items_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_astrodex_items')),
        sa.UniqueConstraint('user_id', 'doc_key', 'id', name=op.f('uq_astrodex_items_user_id')),
    )
    with op.batch_alter_table('astrodex_items', schema=None) as batch_op:
        batch_op.create_index('ix_astrodex_items_owner', ['user_id', 'doc_key'], unique=False)

    op.create_table(
        'equipment_combinations',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('telescope_id', sa.String(length=64), nullable=True),
        sa.Column('camera_id', sa.String(length=64), nullable=True),
        sa.Column('guide_camera_id', sa.String(length=64), nullable=True),
        sa.Column('mount_id', sa.String(length=64), nullable=True),
        sa.Column('is_disabled', sa.Boolean(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_equipment_combinations_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_equipment_combinations')),
        sa.UniqueConstraint('user_id', 'doc_key', 'id', name=op.f('uq_equipment_combinations_user_id')),
    )
    with op.batch_alter_table('equipment_combinations', schema=None) as batch_op:
        batch_op.create_index('ix_equipment_combinations_camera_id', ['camera_id'], unique=False)
        batch_op.create_index('ix_equipment_combinations_mount_id', ['mount_id'], unique=False)
        batch_op.create_index('ix_equipment_combinations_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_equipment_combinations_telescope_id', ['telescope_id'], unique=False)

    op.create_table(
        'equipment_items',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('equipment_type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('is_shared', sa.Boolean(), nullable=True),
        sa.Column('is_disabled', sa.Boolean(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_equipment_items_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_equipment_items')),
    )
    with op.batch_alter_table('equipment_items', schema=None) as batch_op:
        batch_op.create_index('ix_equipment_items_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_equipment_items_type_shared', ['equipment_type', 'is_shared'], unique=False)
        batch_op.create_index('uq_equipment_items_owner_id', ['user_id', 'equipment_type', 'id'], unique=True)

    op.create_table(
        'observation_sessions',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('location_id', sa.String(length=64), nullable=True),
        sa.Column('combination_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.String(length=40), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_observation_sessions_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_observation_sessions')),
        sa.UniqueConstraint('user_id', 'doc_key', 'id', name=op.f('uq_observation_sessions_user_id')),
    )
    with op.batch_alter_table('observation_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_observation_sessions_combination_id', ['combination_id'], unique=False)
        batch_op.create_index('ix_observation_sessions_location_id', ['location_id'], unique=False)
        batch_op.create_index('ix_observation_sessions_owner', ['user_id', 'doc_key'], unique=False)

    op.create_table(
        'plans',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('plan_date', sa.String(length=40), nullable=True),
        sa.Column('location_id', sa.String(length=64), nullable=True),
        sa.Column('combination_id', sa.String(length=64), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_plans_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_plans')),
    )
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.create_index('ix_plans_combination_id', ['combination_id'], unique=False)
        batch_op.create_index('ix_plans_location_id', ['location_id'], unique=False)
        batch_op.create_index('ix_plans_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('uq_plans_owner', ['user_id', 'doc_key'], unique=True)

    op.create_table(
        'user_documents',
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=True),
        sa.Column('updated_at', sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_user_documents_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('user_id', 'kind', 'doc_key', name=op.f('pk_user_documents')),
    )
    with op.batch_alter_table('user_documents', schema=None) as batch_op:
        batch_op.create_index('ix_user_documents_kind', ['kind'], unique=False)

    op.create_table(
        'wishlist_items',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('catalogue', sa.String(length=64), nullable=True),
        sa.Column('catalogue_group_id', sa.String(length=128), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_wishlist_items_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_wishlist_items')),
        sa.UniqueConstraint('user_id', 'doc_key', 'id', name=op.f('uq_wishlist_items_user_id')),
    )
    with op.batch_alter_table('wishlist_items', schema=None) as batch_op:
        batch_op.create_index('ix_wishlist_items_owner', ['user_id', 'doc_key'], unique=False)

    op.create_table(
        'astrodex_pictures',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=True),
        sa.Column('date', sa.String(length=40), nullable=True),
        sa.Column('location_id', sa.String(length=64), nullable=True),
        sa.Column('combination_id', sa.String(length=64), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('is_main', sa.Boolean(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'],
            ['astrodex_items.pk'],
            name=op.f('fk_astrodex_pictures_parent_pk_astrodex_items'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_astrodex_pictures_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_astrodex_pictures')),
    )
    with op.batch_alter_table('astrodex_pictures', schema=None) as batch_op:
        batch_op.create_index('ix_astrodex_pictures_combination_id', ['combination_id'], unique=False)
        batch_op.create_index('ix_astrodex_pictures_filename', ['filename'], unique=False)
        batch_op.create_index('ix_astrodex_pictures_location_id', ['location_id'], unique=False)
        batch_op.create_index('ix_astrodex_pictures_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_astrodex_pictures_parent', ['parent_pk'], unique=False)

    op.create_table(
        'combination_equipment',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('equipment_id', sa.String(length=64), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'],
            ['equipment_combinations.pk'],
            name=op.f('fk_combination_equipment_parent_pk_equipment_combinations'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_combination_equipment_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_combination_equipment')),
    )
    with op.batch_alter_table('combination_equipment', schema=None) as batch_op:
        batch_op.create_index('ix_combination_equipment_equipment_id', ['equipment_id'], unique=False)
        batch_op.create_index('ix_combination_equipment_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_combination_equipment_parent', ['parent_pk'], unique=False)

    op.create_table(
        'observation_attachments',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'],
            ['observation_sessions.pk'],
            name=op.f('fk_observation_attachments_parent_pk_observation_sessions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_observation_attachments_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_observation_attachments')),
    )
    with op.batch_alter_table('observation_attachments', schema=None) as batch_op:
        batch_op.create_index('ix_observation_attachments_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_observation_attachments_parent', ['parent_pk'], unique=False)

    op.create_table(
        'observation_entries',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('night_id', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('catalogue', sa.String(length=64), nullable=True),
        sa.Column('combination_id', sa.String(length=64), nullable=True),
        sa.Column('astrodex_item_id', sa.String(length=64), nullable=True),
        sa.Column('astrodex_picture_id', sa.String(length=64), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'],
            ['observation_sessions.pk'],
            name=op.f('fk_observation_entries_parent_pk_observation_sessions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_observation_entries_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_observation_entries')),
    )
    with op.batch_alter_table('observation_entries', schema=None) as batch_op:
        batch_op.create_index('ix_observation_entries_combination_id', ['combination_id'], unique=False)
        batch_op.create_index('ix_observation_entries_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_observation_entries_parent', ['parent_pk'], unique=False)

    op.create_table(
        'observation_nights',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('date', sa.String(length=40), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'],
            ['observation_sessions.pk'],
            name=op.f('fk_observation_nights_parent_pk_observation_sessions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_observation_nights_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_observation_nights')),
    )
    with op.batch_alter_table('observation_nights', schema=None) as batch_op:
        batch_op.create_index('ix_observation_nights_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_observation_nights_parent', ['parent_pk'], unique=False)

    op.create_table(
        'plan_entries',
        sa.Column('pk', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('doc_key', sa.String(length=128), server_default='', nullable=False),
        sa.Column('parent_pk', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('catalogue', sa.String(length=64), nullable=True),
        sa.Column('done', sa.Boolean(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_pk'], ['plans.pk'], name=op.f('fk_plan_entries_parent_pk_plans'), ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'], name=op.f('fk_plan_entries_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('pk', name=op.f('pk_plan_entries')),
    )
    with op.batch_alter_table('plan_entries', schema=None) as batch_op:
        batch_op.create_index('ix_plan_entries_owner', ['user_id', 'doc_key'], unique=False)
        batch_op.create_index('ix_plan_entries_parent', ['parent_pk'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('plan_entries', schema=None) as batch_op:
        batch_op.drop_index('ix_plan_entries_parent')
        batch_op.drop_index('ix_plan_entries_owner')

    op.drop_table('plan_entries')
    with op.batch_alter_table('observation_nights', schema=None) as batch_op:
        batch_op.drop_index('ix_observation_nights_parent')
        batch_op.drop_index('ix_observation_nights_owner')

    op.drop_table('observation_nights')
    with op.batch_alter_table('observation_entries', schema=None) as batch_op:
        batch_op.drop_index('ix_observation_entries_parent')
        batch_op.drop_index('ix_observation_entries_owner')
        batch_op.drop_index('ix_observation_entries_combination_id')

    op.drop_table('observation_entries')
    with op.batch_alter_table('observation_attachments', schema=None) as batch_op:
        batch_op.drop_index('ix_observation_attachments_parent')
        batch_op.drop_index('ix_observation_attachments_owner')

    op.drop_table('observation_attachments')
    with op.batch_alter_table('combination_equipment', schema=None) as batch_op:
        batch_op.drop_index('ix_combination_equipment_parent')
        batch_op.drop_index('ix_combination_equipment_owner')
        batch_op.drop_index('ix_combination_equipment_equipment_id')

    op.drop_table('combination_equipment')
    with op.batch_alter_table('astrodex_pictures', schema=None) as batch_op:
        batch_op.drop_index('ix_astrodex_pictures_parent')
        batch_op.drop_index('ix_astrodex_pictures_owner')
        batch_op.drop_index('ix_astrodex_pictures_location_id')
        batch_op.drop_index('ix_astrodex_pictures_filename')
        batch_op.drop_index('ix_astrodex_pictures_combination_id')

    op.drop_table('astrodex_pictures')
    with op.batch_alter_table('wishlist_items', schema=None) as batch_op:
        batch_op.drop_index('ix_wishlist_items_owner')

    op.drop_table('wishlist_items')
    with op.batch_alter_table('user_documents', schema=None) as batch_op:
        batch_op.drop_index('ix_user_documents_kind')

    op.drop_table('user_documents')
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.drop_index('uq_plans_owner')
        batch_op.drop_index('ix_plans_owner')
        batch_op.drop_index('ix_plans_location_id')
        batch_op.drop_index('ix_plans_combination_id')

    op.drop_table('plans')
    with op.batch_alter_table('observation_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_observation_sessions_owner')
        batch_op.drop_index('ix_observation_sessions_location_id')
        batch_op.drop_index('ix_observation_sessions_combination_id')

    op.drop_table('observation_sessions')
    with op.batch_alter_table('equipment_items', schema=None) as batch_op:
        batch_op.drop_index('uq_equipment_items_owner_id')
        batch_op.drop_index('ix_equipment_items_type_shared')
        batch_op.drop_index('ix_equipment_items_owner')

    op.drop_table('equipment_items')
    with op.batch_alter_table('equipment_combinations', schema=None) as batch_op:
        batch_op.drop_index('ix_equipment_combinations_telescope_id')
        batch_op.drop_index('ix_equipment_combinations_owner')
        batch_op.drop_index('ix_equipment_combinations_mount_id')
        batch_op.drop_index('ix_equipment_combinations_camera_id')

    op.drop_table('equipment_combinations')
    with op.batch_alter_table('astrodex_items', schema=None) as batch_op:
        batch_op.drop_index('ix_astrodex_items_owner')

    op.drop_table('astrodex_items')
    op.drop_table('users')
    op.drop_table('store_revisions')
    op.drop_table('settings')
    op.drop_table('legacy_import')
