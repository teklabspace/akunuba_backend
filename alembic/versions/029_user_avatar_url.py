"""Add avatar_url to users (profile pictures).

Revision ID: 029_user_avatar_url
Revises: 028_listing_suspension
"""
from alembic import op
import sqlalchemy as sa

revision = "029_user_avatar_url"
down_revision = "028_listing_suspension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
