"""adding tour_completed_at to user

Revision ID: e5b2d9c74a10
Revises: c1f4a7b2e903
Create Date: 2026-09-01

Tracks whether a user has seen the first-login product tour. NULL means the
tour has not been shown yet. Stored on the user (rather than in localStorage)
so the tour does not reappear on a second browser or device.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5b2d9c74a10'
down_revision = 'c1f4a7b2e903'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tour_completed_at', sa.DateTime(), nullable=True))

    # Existing users have already found their way around; don't interrupt them
    # with a tour on their next login.
    op.execute(
        "UPDATE user SET tour_completed_at = CURRENT_TIMESTAMP "
        "WHERE tour_completed_at IS NULL AND org_setup_completed = 1"
    )


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('tour_completed_at')
