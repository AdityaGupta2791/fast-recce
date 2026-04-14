"""rewrite seed queries with google-friendly terms

Revision ID: 4af2187029ca
Revises: 4a88908c8aca
Create Date: 2026-04-14 15:14:45.578321

Live testing against Google Places API (New) showed that our original seed
query templates (e.g. 'villa in Alibaug') return ZERO_RESULTS because
Google's index categorises Indian listings differently. Plural/simplified
forms ('villas in Alibaug for rent') return 20+ results per query.

This migration rewrites the seeded query_text values in place. Queries
that reviewers added manually after the initial seed are left untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4af2187029ca"
down_revision: str | None = "4a88908c8aca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CITIES = ["Mumbai", "Thane", "Navi Mumbai", "Lonavala", "Pune", "Alibaug"]

# (property_type, old_template, new_template)
QUERY_REWRITES = [
    ("villa", "villa in {city}", "villas in {city} for rent"),
    ("resort", "resort in {city}", "resorts in {city}"),
    ("bungalow", "heritage bungalow in {city}", "bungalows in {city}"),
    ("farmhouse", "farmhouse for events in {city}", "farmhouses in {city}"),
    ("boutique_hotel", "boutique hotel in {city}", "boutique hotels in {city}"),
    ("banquet_hall", "banquet hall in {city}", "banquet halls in {city}"),
    ("cafe", "aesthetic cafe in {city}", "cafes in {city}"),
]


def upgrade() -> None:
    for city in CITIES:
        for _prop_type, old_template, new_template in QUERY_REWRITES:
            op.execute(
                sa.text(
                    "UPDATE query_bank "
                    "SET query_text = :new_text "
                    "WHERE query_text = :old_text AND city = :city"
                ).bindparams(
                    new_text=new_template.format(city=city),
                    old_text=old_template.format(city=city),
                    city=city,
                )
            )


def downgrade() -> None:
    for city in CITIES:
        for _prop_type, old_template, new_template in QUERY_REWRITES:
            op.execute(
                sa.text(
                    "UPDATE query_bank "
                    "SET query_text = :old_text "
                    "WHERE query_text = :new_text AND city = :city"
                ).bindparams(
                    new_text=new_template.format(city=city),
                    old_text=old_template.format(city=city),
                    city=city,
                )
            )
