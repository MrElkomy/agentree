"""Uploaded CSV/XLSX profiles (Task 18b): column names, types and row count, never cell values.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_files", sa.Column("profile", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_files", "profile")
