"""Data types produced by the Crawl & Extraction engine (M4).

All types are Pydantic so they can be serialized for logging, debugging, or
passed between pipeline stages. No DB persistence here — downstream modules
(M5 Contacts, M7 Scoring) consume these and write the canonical rows.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PageType = Literal["home", "contact", "about", "venue", "events", "rooms", "footer", "other"]
ExtractionMethod = Literal[
    "api_structured",   # contact came from Google Places details
    "schema_org",       # JSON-LD schema.org markup
    "html_tel_link",    # <a href="tel:...">
    "html_mailto",      # <a href="mailto:...">
    "whatsapp_link",    # wa.me or api.whatsapp.com link
    "contact_form",     # <form> on /contact
    "text_regex",       # regex match in free text
    "meta_tag",         # <meta> description, og:title, etc.
    "instagram",        # instagram profile link
    "manual",           # analyst-entered
]
ContactType = Literal["phone", "email", "whatsapp", "form", "website", "instagram"]
CrawlStatus = Literal["completed", "partial", "failed", "skipped_unchanged", "skipped_robots"]


class FetchedPage(BaseModel):
    """One page successfully (or unsuccessfully) fetched from a property website."""

    url: str
    page_type: PageType
    status_code: int
    html: str = ""
    content_hash: str
    fetched_at: str  # ISO timestamp
    error: str | None = None


class ExtractedContact(BaseModel):
    """Raw contact extracted from a page. Resolution to canonical happens in M5."""

    contact_type: ContactType
    value: str
    source_url: str           # which page it was found on
    extraction_method: ExtractionMethod
    confidence: float = Field(ge=0.0, le=1.0)


class StructuredData(BaseModel):
    """Output of StructuredExtractor — data with clear semantics."""

    phones: list[ExtractedContact] = Field(default_factory=list)
    emails: list[ExtractedContact] = Field(default_factory=list)
    whatsapp_links: list[ExtractedContact] = Field(default_factory=list)
    contact_forms: list[ExtractedContact] = Field(default_factory=list)
    instagram_links: list[ExtractedContact] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    schema_org_data: dict[str, Any] | None = None
    meta_description: str | None = None
    meta_title: str | None = None
    og_image: str | None = None


class UnstructuredData(BaseModel):
    """Output of UnstructuredExtractor — free-text-derived signals."""

    description: str | None = None
    amenities: list[str] = Field(default_factory=list)
    feature_tags: list[str] = Field(default_factory=list)
    text_contacts: list[ExtractedContact] = Field(default_factory=list)


class MediaItem(BaseModel):
    """One image or media asset referenced from a property page."""

    media_url: str
    media_type: Literal["image", "video", "virtual_tour"] = "image"
    alt_text: str | None = None
    source_page_url: str
    width: int | None = None
    height: int | None = None


class CrawlResult(BaseModel):
    """Aggregated output of crawling a single property's website."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Attribution
    candidate_id: str           # discovery_candidates.id (UUID as str)
    website_url: str

    # Stats
    pages_fetched: int
    pages_failed: int
    snapshot_hash: str          # sha256 of the sorted page content hashes
    crawl_status: CrawlStatus
    duration_seconds: float
    errors: list[str] = Field(default_factory=list)

    # Extracted content
    structured_data: StructuredData = Field(default_factory=StructuredData)
    unstructured_data: UnstructuredData = Field(default_factory=UnstructuredData)
    media_items: list[MediaItem] = Field(default_factory=list)
    pages: list[FetchedPage] = Field(default_factory=list)

    # Convenience: all contacts from structured + unstructured, ordered by confidence
    def all_contacts(self) -> list[ExtractedContact]:
        contacts = (
            self.structured_data.phones
            + self.structured_data.emails
            + self.structured_data.whatsapp_links
            + self.structured_data.contact_forms
            + self.structured_data.instagram_links
            + self.unstructured_data.text_contacts
        )
        return sorted(contacts, key=lambda c: c.confidence, reverse=True)
