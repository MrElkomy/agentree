"""Knowledge file uploads (Task 17): file metadata and bytes (RLS), drafts link to their file.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
TABLES = ("knowledge_files", "knowledge_file_data")


def upgrade() -> None:
    op.create_table(
        "knowledge_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(32)),
        sa.Column("entry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_files"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_knowledge_files_business_id_businesses"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_knowledge_files_uploaded_by_user_id_users"),
        sa.UniqueConstraint("business_id", "id", name="uq_knowledge_files_business_id"),
        sa.CheckConstraint("kind IN ('pdf', 'docx', 'txt', 'md', 'csv', 'xlsx')",
                           name="ck_knowledge_files_kind"),
        sa.CheckConstraint("status IN ('processing', 'ready', 'stored', 'failed')",
                           name="ck_knowledge_files_status"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 10485760",
                           name="ck_knowledge_files_size_bytes"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_knowledge_files_sha256"),
    )  # fmt: skip
    op.create_index("ix_knowledge_files_business_id", "knowledge_files", ["business_id"])
    op.create_table(
        "knowledge_file_data",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("file_id", name="pk_knowledge_file_data"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_knowledge_file_data_business_id_businesses"),
        sa.ForeignKeyConstraint(["business_id", "file_id"],
                                ["knowledge_files.business_id", "knowledge_files.id"],
                                ondelete="CASCADE",
                                name="fk_knowledge_file_data_business_id_knowledge_files"),
    )  # fmt: skip
    op.create_index("ix_knowledge_file_data_business_id", "knowledge_file_data", ["business_id"])
    op.add_column("knowledge_entries", sa.Column("source_file_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_entries_source_file_id_knowledge_files", "knowledge_entries",
        "knowledge_files", ["source_file_id"], ["id"], ondelete="SET NULL",
    )  # fmt: skip
    op.create_index("ix_knowledge_entries_source_file_id", "knowledge_entries", ["source_file_id"])
    for table in TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    op.drop_index("ix_knowledge_entries_source_file_id", table_name="knowledge_entries")
    op.drop_constraint("fk_knowledge_entries_source_file_id_knowledge_files",
                       "knowledge_entries", type_="foreignkey")  # fmt: skip
    op.drop_column("knowledge_entries", "source_file_id")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
