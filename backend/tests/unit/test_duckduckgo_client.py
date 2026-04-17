"""Unit tests for the DuckDuckGo client.

These tests never hit the real DDG network — we patch the internal
`_search` coroutine to return canned results and assert the filtering /
normalization behavior.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from app.integrations.duckduckgo import DDGResult, DuckDuckGoClient

pytestmark = pytest.mark.asyncio


def _patch_search(
    client: DuckDuckGoClient,
    canned: list[DDGResult],
) -> Callable[[str], Awaitable[list[DDGResult]]]:
    """Replace `DuckDuckGoClient._search` with a canned-responses fake."""
    calls: list[tuple[str, int]] = []

    async def _fake(query: str, *, max_results: int = 10) -> list[DDGResult]:
        calls.append((query, max_results))
        return canned

    client._search = _fake  # type: ignore[assignment]
    client._calls = calls  # type: ignore[attr-defined]
    return _fake


async def test_find_airbnb_listing_urls_filters_and_dedupes() -> None:
    client = DuckDuckGoClient(per_request_delay_seconds=0.0)
    _patch_search(
        client,
        [
            DDGResult(
                title="Villa Sunset",
                href="https://www.airbnb.com/rooms/12345?source=search",
                body="",
            ),
            # Same listing id, different query string → must dedup.
            DDGResult(
                title="Villa Sunset",
                href="https://www.airbnb.com/rooms/12345?adults=2",
                body="",
            ),
            # Different listing id on .co.in TLD → kept.
            DDGResult(
                title="Ocean Villa",
                href="https://airbnb.co.in/rooms/99999",
                body="",
            ),
            # Non-listing Airbnb page → rejected.
            DDGResult(
                title="Help Center",
                href="https://www.airbnb.com/help/article/12",
                body="",
            ),
            # Non-Airbnb URL → rejected.
            DDGResult(title="Some blog", href="https://example.com/", body=""),
        ],
    )

    urls = await client.find_airbnb_listing_urls("villa in Alibaug", limit=10)

    # Canonicalized to www.airbnb.com regardless of the original TLD —
    # locale subdomains / TLDs serve translated pages that break our
    # __NEXT_DATA__ extractor.
    assert urls == [
        "https://www.airbnb.com/rooms/12345",
        "https://www.airbnb.com/rooms/99999",
    ]


async def test_find_airbnb_listing_urls_respects_limit() -> None:
    client = DuckDuckGoClient(per_request_delay_seconds=0.0)
    _patch_search(
        client,
        [
            DDGResult(
                title=f"Villa {i}",
                href=f"https://www.airbnb.com/rooms/{i:05d}",
                body="",
            )
            for i in range(20)
        ],
    )

    urls = await client.find_airbnb_listing_urls("villa", limit=3)
    assert len(urls) == 3


async def test_find_airbnb_listing_urls_empty_when_no_airbnb_results() -> None:
    client = DuckDuckGoClient(per_request_delay_seconds=0.0)
    _patch_search(
        client,
        [
            DDGResult(title="Some page", href="https://example.com/", body=""),
            DDGResult(title="OYO", href="https://oyorooms.com/1", body=""),
        ],
    )
    urls = await client.find_airbnb_listing_urls("villa", limit=5)
    assert urls == []


# Note: `find_property_website` was removed in Part 3 (Airbnb is now a
# discovery-only source — we no longer chain to villa websites). If a
# similar search-and-filter helper comes back, mirror the patterns above.
