"""enable postgres extensions

Revision ID: 0a1e68db884a
Revises:
Create Date: 2026-04-14 13:08:11.806951

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0a1e68db884a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto — gen_random_uuid() for UUID primary keys
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    # postgis — GEOGRAPHY type and ST_DWithin for spatial dedup
    op.execute('CREATE EXTENSION IF NOT EXISTS "postgis"')
    # pg_trgm — trigram similarity for fuzzy name matching in dedup
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "postgis"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
