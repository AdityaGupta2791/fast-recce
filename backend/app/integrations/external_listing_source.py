"""Protocol every external-listing scraper must satisfy.

Satisfied by: `AirbnbScraper`, `MagicBricksScraper`, and any future source.
`SearchService._run_external_source_path` is coded against this protocol
so adding a new source is just: implement the protocol + register it
in the source router + add a feature flag.

We use `Protocol` (structural typing) rather than an abstract base class
so scraper classes don't need to inherit from it — they just happen to
have the right attributes and methods. Keeps the existing AirbnbScraper
refactor minimal.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.integrations.external_listing import ExternalListing


class ScraperBlockedError(Exception):
    """Raised when a source actively blocks our request.

    Covers 403 / 429 / 5xx status codes and CAPTCHA / "Access Denied"
    HTML walls. The source router's early-abort guard counts ONLY these
    toward its consecutive-block threshold, because they're the real
    signal that the IP is rate-limited or fingerprinted.

    Distinct from a plain `None` return, which scrapers use for "soft"
    misses like 410 Gone (listing delisted), 404 (bad URL in DDG index),
    or parse failures. Those are harmless and shouldn't trigger abort.
    """


@runtime_checkable
class ExternalListingSource(Protocol):
    """Async context-managed scraper for one third-party listing source."""

    source_id: str            # e.g. "airbnb", "magicbricks"
    source_label: str         # e.g. "Airbnb", "MagicBricks"
    exposes_contacts: bool    # today: always False; kept for future sources

    async def __aenter__(self) -> "ExternalListingSource": ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def scrape_listing(self, url: str) -> ExternalListing | None:
        """Fetch + parse one listing URL. Returns None on failure / block."""
        ...
