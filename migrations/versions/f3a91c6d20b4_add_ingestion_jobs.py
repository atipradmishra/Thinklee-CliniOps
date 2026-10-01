"""adding ingestion_jobs for background document ingestion

Revision ID: f3a91c6d20b4
Revises: e5b2d9c74a10
Create Date: 2026-10-01

Document ingestion embeds every chunk of every uploaded file, which runs for
minutes on CPU. It is no longer done inside the request; the upload endpoint
stages the files and records a job here for a background worker to pick up.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a91c6d20b4'
down_revision = 'e5b2d9c74a10'
branch_labels = None
depends_on = None


def _table_exists(name):
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _index_names(table):
    bind = op.get_bind()
    try:
        return {i["name"] for i in sa.inspect(bind).get_indexes(table)}
    except Exception:
        return set()


def upgrade():
    # run.py calls db.create_all() at import, which builds this table straight
    # from the model before Alembic ever runs. Without this guard `db upgrade`
    # dies on "table already exists" and the revision is never stamped,
    # leaving the database permanently one migration behind.
    if _table_exists('ingestion_jobs'):
        existing = _index_names('ingestion_jobs')
        with op.batch_alter_table('ingestion_jobs', schema=None) as batch_op:
            for col in ('user_id', 'organization_id', 'status', 'created_at'):
                name = f'ix_ingestion_jobs_{col}'
                if name not in existing:
                    batch_op.create_index(name, [col])
        return

    op.create_table(
        'ingestion_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('file_category', sa.String(length=20), nullable=False, server_default='unstructured'),
        sa.Column('total_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('succeeded_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('results', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('staging_dir', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ingestion_jobs', schema=None) as batch_op:
        batch_op.create_index('ix_ingestion_jobs_user_id', ['user_id'])
        batch_op.create_index('ix_ingestion_jobs_organization_id', ['organization_id'])
        batch_op.create_index('ix_ingestion_jobs_status', ['status'])
        batch_op.create_index('ix_ingestion_jobs_created_at', ['created_at'])


def downgrade():
    with op.batch_alter_table('ingestion_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_ingestion_jobs_created_at')
        batch_op.drop_index('ix_ingestion_jobs_status')
        batch_op.drop_index('ix_ingestion_jobs_organization_id')
        batch_op.drop_index('ix_ingestion_jobs_user_id')
    op.drop_table('ingestion_jobs')
