"""Allow Groq as a BYOK provider.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "provider_credentials"
NAME = "ck_provider_credentials_provider"


def upgrade() -> None:
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, "provider IN ('openai', 'anthropic', 'gemini', 'groq')")


def downgrade() -> None:
    # Fails while Groq credentials exist: remove or replace them first (no silent data loss).
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, "provider IN ('openai', 'anthropic', 'gemini')")
