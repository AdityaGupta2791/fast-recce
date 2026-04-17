"""Shared dataclass for third-party listings scraped from external sources.

Used by AirbnbScraper, MagicBricksScraper, and any future source (99acres,
NoBroker, Housing.com). The `source` field is the single discriminator
that SearchService uses to drive source-aware behavior — e.g., deciding
which rows to suppress contacts on, which pill label to render.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExternalListing:
    source: str                       # "airbnb" | "magicbricks"
    listing_id: str
    url: str                          # canonical URL pointing back to the source
    title: str
    description: str | None = None
    city_hint: str | None = None
    neighborhood: str | None = None
    locality: str | None = None
    amenities: list[str] = field(default_factory=list)
    primary_image_url: str | None = None
    image_urls: list[str] = field(default_factory=list)
    # Contact fields — populated if a future source exposes them.
    # Today: always empty for airbnb / magicbricks.
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    # Drift-detection: top-level keys of the raw payload (JSON blob or ld+json).
    raw_top_keys: list[str] = field(default_factory=list)
