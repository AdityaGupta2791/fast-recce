"""seed phase1 sources and default queries

Revision ID: 6c40084298be
Revises: 221bb5995531
Create Date: 2026-04-14 13:11:42.371237

Seeds:
- 8 sources from the Phase 1 plan (Google Places, property websites, MahaRERA,
  4 restricted sources for manual-only import, and the manual_import channel).
- Starter query bank: villa/resort/bungalow/farmhouse queries for the 6 MVP
  cities. Analysts will expand this via the dashboard.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6c40084298be"
down_revision: str | None = "221bb5995531"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SOURCES = [
    {
        "source_name": "google_places",
        "source_type": "api",
        "access_policy": "allowed",
        "crawl_method": "api_call",
        "base_url": "https://places.googleapis.com",
        "refresh_frequency": "daily",
        "parser_version": "1.0",
        "rate_limit_rpm": 60,
        "is_enabled": True,
        "notes": "Primary discovery source. Text Search + Place Details.",
    },
    {
        "source_name": "property_website",
        "source_type": "website",
        "access_policy": "allowed",
        "crawl_method": "html_parser",
        "base_url": None,
        "refresh_frequency": "daily",
        "parser_version": "1.0",
        "rate_limit_rpm": 60,
        "is_enabled": True,
        "notes": "Direct property sites discovered via Google Places websiteUri.",
    },
    {
        "source_name": "maharera",
        "source_type": "website",
        "access_policy": "allowed",
        "crawl_method": "html_parser",
        "base_url": "https://maharera.mahaonline.gov.in",
        "refresh_frequency": "weekly",
        "parser_version": "1.0",
        "rate_limit_rpm": 30,
        "is_enabled": False,
        "notes": "Enrichment / validation source. Enable when dedup needs promoter signals.",
    },
    {
        "source_name": "airbnb",
        "source_type": "website",
        "access_policy": "restricted",
        "crawl_method": "browser_render",
        "base_url": "https://www.airbnb.co.in",
        "refresh_frequency": "monthly",
        "parser_version": "1.0",
        "rate_limit_rpm": 6,
        "is_enabled": False,
        "notes": "TOS forbids automated scraping. Manual analyst import only.",
    },
    {
        "source_name": "magicbricks",
        "source_type": "website",
        "access_policy": "restricted",
        "crawl_method": "browser_render",
        "base_url": "https://www.magicbricks.com",
        "refresh_frequency": "monthly",
        "parser_version": "1.0",
        "rate_limit_rpm": 6,
        "is_enabled": False,
        "notes": "TOS forbids automated scraping. Manual analyst import only.",
    },
    {
        "source_name": "99acres",
        "source_type": "website",
        "access_policy": "restricted",
        "crawl_method": "browser_render",
        "base_url": "https://www.99acres.com",
        "refresh_frequency": "monthly",
        "parser_version": "1.0",
        "rate_limit_rpm": 6,
        "is_enabled": False,
        "notes": "TOS forbids automated scraping. Manual analyst import only.",
    },
    {
        "source_name": "peerspace",
        "source_type": "website",
        "access_policy": "restricted",
        "crawl_method": "browser_render",
        "base_url": "https://www.peerspace.com",
        "refresh_frequency": "monthly",
        "parser_version": "1.0",
        "rate_limit_rpm": 6,
        "is_enabled": False,
        "notes": "Guidelines restrict harvesting member contacts. Manual import only.",
    },
    {
        "source_name": "manual_import",
        "source_type": "manual",
        "access_policy": "allowed",
        "crawl_method": "api_call",
        "base_url": None,
        "refresh_frequency": "daily",
        "parser_version": "1.0",
        "rate_limit_rpm": 60,
        "is_enabled": True,
        "notes": "Channel for analyst-initiated property imports (no crawl).",
    },
]


CITIES = ["Mumbai", "Thane", "Navi Mumbai", "Lonavala", "Pune", "Alibaug"]
PROPERTY_TYPE_QUERIES = [
    ("villa", "villa in {city}", ["premium", "residential"]),
    ("resort", "resort in {city}", ["premium", "outdoor"]),
    ("bungalow", "heritage bungalow in {city}", ["premium", "heritage"]),
    ("farmhouse", "farmhouse for events in {city}", ["outdoor", "events"]),
    ("boutique_hotel", "boutique hotel in {city}", ["premium"]),
    ("banquet_hall", "banquet hall in {city}", ["indoor", "events"]),
    ("cafe", "aesthetic cafe in {city}", ["indoor", "budget"]),
]


def upgrade() -> None:
    sources_table = sa.table(
        "sources",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("source_name", sa.String),
        sa.column("source_type", sa.String),
        sa.column("access_policy", sa.String),
        sa.column("crawl_method", sa.String),
        sa.column("base_url", sa.String),
        sa.column("refresh_frequency", sa.String),
        sa.column("parser_version", sa.String),
        sa.column("rate_limit_rpm", sa.Integer),
        sa.column("is_enabled", sa.Boolean),
        sa.column("notes", sa.String),
    )
    op.bulk_insert(
        sources_table,
        [{"id": uuid.uuid4(), **row} for row in SOURCES],
    )

    query_bank_table = sa.table(
        "query_bank",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("query_text", sa.String),
        sa.column("city", sa.String),
        sa.column("property_type", sa.String),
        sa.column("segment_tags", postgresql.JSONB),
        sa.column("is_enabled", sa.Boolean),
        sa.column("total_runs", sa.Integer),
        sa.column("total_results", sa.Integer),
        sa.column("new_properties", sa.Integer),
    )
    rows = []
    for city in CITIES:
        for prop_type, template, tags in PROPERTY_TYPE_QUERIES:
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "query_text": template.format(city=city),
                    "city": city,
                    "property_type": prop_type,
                    "segment_tags": tags,
                    "is_enabled": True,
                    "total_runs": 0,
                    "total_results": 0,
                    "new_properties": 0,
                }
            )
    op.bulk_insert(query_bank_table, rows)


def downgrade() -> None:
    op.execute("DELETE FROM query_bank")
    op.execute("DELETE FROM sources")
