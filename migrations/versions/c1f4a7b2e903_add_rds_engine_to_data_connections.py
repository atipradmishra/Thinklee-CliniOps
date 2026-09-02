"""adding rds_engine to data source connections

Revision ID: c1f4a7b2e903
Revises: 7a889ed2c5de
Create Date: 2026-09-01

Managed relational sources (AWS RDS, Azure SQL) reuse the existing
host/port/database/username/password columns. RDS additionally needs to record
which engine the instance runs so the right SQLAlchemy dialect can be built.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1f4a7b2e903'
down_revision = '7a889ed2c5de'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('data_source_connections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rds_engine', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('data_source_connections', schema=None) as batch_op:
        batch_op.drop_column('rds_engine')
