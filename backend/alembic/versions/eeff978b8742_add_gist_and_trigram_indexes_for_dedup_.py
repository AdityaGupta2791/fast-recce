"""add gist and trigram indexes for dedup queries

Revision ID: eeff978b8742
Revises: 28197a269f8b
Create Date: 2026-04-14 15:56:49.058987

Adds the two PostgreSQL-specific indexes M6 (Deduplication) needs:
  * GIST spatial index on properties.location for ST_DWithin geo queries
    (radius-based "find properties within N meters" lookups).
  * GIN trigram index on properties.normalized_name for similarity()
    fuzzy name matching.

Both deferred from M5 because they are PG-only and can't be created on the
SQLite test DB. The pg_trgm extension was enabled in the very first migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "eeff978b8742"
down_revision: str | None = "28197a269f8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_properties_location "
        "ON properties USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_properties_normalized_name_trgm "
        "ON properties USING GIN (normalized_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_properties_normalized_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_properties_location")
