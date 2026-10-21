"""Per-key circuit breaker state on provider credentials.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "provider_credentials",
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("provider_credentials", sa.Column("last_failure_at", TS))
    op.add_column("provider_credentials", sa.Column("breaker_open_until", TS))
    op.add_column("provider_credentials", sa.Column("probe_until", TS))
    op.create_check_constraint(
        "ck_provider_credentials_failure_count", "provider_credentials", "failure_count >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_provider_credentials_failure_count", "provider_credentials")
    for column in ("probe_until", "breaker_open_until", "last_failure_at", "failure_count"):
        op.drop_column("provider_credentials", column)
