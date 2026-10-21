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
SIGNATURE = "agentree_provider_health_counts(timestamptz)"

# SECURITY DEFINER (owned by the migrator), EXECUTE only for agentree_app: platform-wide counts
# of stored keys by breaker state for monitoring. Counts only: no business ids, keys or models.
HEALTH_FUNCTION = """
CREATE FUNCTION agentree_provider_health_counts(p_now timestamptz)
RETURNS TABLE (state text, keys bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT CASE
           WHEN c.breaker_open_until IS NULL THEN 'closed'
           WHEN c.breaker_open_until > p_now THEN 'open'
           ELSE 'half_open'
         END AS state,
         count(*) AS keys
    FROM public.provider_credentials c
   GROUP BY 1
$$
"""


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
    op.execute(HEALTH_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO agentree_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
    op.drop_constraint("ck_provider_credentials_failure_count", "provider_credentials")
    for column in ("probe_until", "breaker_open_until", "last_failure_at", "failure_count"):
        op.drop_column("provider_credentials", column)
