"""Initial cloud database schema.

Revision ID: 0001_cloud_schema
Revises: none
"""

from __future__ import annotations

from alembic import op

from webapp.cloud.db.models import Base

revision = "0001_cloud_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The declarative metadata is the canonical locked schema. Using the
    # metadata here keeps SQLite acceptance runs and PostgreSQL deployment in
    # exact agreement, including CHECK constraints and expression indexes.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=False)

