"""Knowledge scoping: which agents may use a knowledge entry (empty: every agent).

Expand-only: a new column with an empty default, so every existing entry stays available to
every agent, exactly as before.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_entries",
        sa.Column("agent_roles", ARRAY(sa.String(32)), server_default=sa.text("'{}'"),
                  nullable=False),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_column("knowledge_entries", "agent_roles")
