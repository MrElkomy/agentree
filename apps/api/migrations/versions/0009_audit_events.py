"""Append-only audit events, tenant-scoped with RLS.

The app role keeps INSERT and SELECT only: UPDATE, DELETE and TRUNCATE are revoked, so the
application cannot rewrite or erase the trail. Rows go away only with their business
(ON DELETE CASCADE, a referential action run by the table owner).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64)),
        sa.Column("details", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_audit_events_business_id_businesses"),
        sa.CheckConstraint("action ~ '^[a-z_]+\\.[a-z_]+$'", name="ck_audit_events_action"),
        sa.CheckConstraint("jsonb_typeof(details) = 'object' AND pg_column_size(details) <= 4096",
                           name="ck_audit_events_details"),
    )  # fmt: skip
    op.create_index("ix_audit_events_business_id_id", "audit_events", ["business_id", "id"])
    for stmt in enable_tenant_rls("audit_events"):
        op.execute(stmt)
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM agentree_app")


def downgrade() -> None:
    for stmt in disable_tenant_rls("audit_events"):
        op.execute(stmt)
    op.drop_table("audit_events")
