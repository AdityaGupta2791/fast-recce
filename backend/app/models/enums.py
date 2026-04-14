"""Enum-like string constants used as CHECK constraints on VARCHAR columns.

We avoid PostgreSQL ENUM types because adding a value requires ALTER TYPE
outside a transaction (painful in migrations). Keeping them as CHECK
constraints on VARCHAR makes schema evolution trivial.
"""

from typing import Final

SOURCE_TYPES: Final[tuple[str, ...]] = ("api", "website", "manual", "partner_feed")

ACCESS_POLICIES: Final[tuple[str, ...]] = ("allowed", "manual_only", "restricted")

CRAWL_METHODS: Final[tuple[str, ...]] = (
    "api_call",
    "sitemap",
    "html_parser",
    "browser_render",
)

PROPERTY_TYPES: Final[tuple[str, ...]] = (
    "boutique_hotel",
    "villa",
    "bungalow",
    "heritage_home",
    "farmhouse",
    "resort",
    "banquet_hall",
    "cafe",
    "restaurant",
    "warehouse",
    "industrial_shed",
    "office_space",
    "school_campus",
    "coworking_space",
    "rooftop_venue",
    "theatre_studio",
    "club_lounge",
    "other",
)

REFRESH_FREQUENCIES: Final[tuple[str, ...]] = ("hourly", "daily", "weekly", "monthly")

CANDIDATE_STATUSES: Final[tuple[str, ...]] = (
    "pending",          # discovered, not yet processed by downstream stages
    "processed",        # crawl + upsert completed, canonical property exists
    "failed",           # downstream pipeline raised; see error_message
    "skipped_duplicate",# filtered by dedup before processing
)


def check_constraint(values: tuple[str, ...]) -> str:
    """Render a SQL CHECK constraint clause for a column.

    Example: check_constraint(SOURCE_TYPES)
        → "IN ('api', 'website', 'manual', 'partner_feed')"
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"IN ({quoted})"
