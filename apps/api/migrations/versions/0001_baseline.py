"""Baseline: empty schema marker.

Revision ID: 0001
Revises:
Create Date: 2026-10-19

Intentionally empty. It establishes the migration chain; tenant tables, roles and
RLS policies arrive in Task 02.
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
