"""Unit tests for CrawlerService with mocked HTTP via httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.crawler_service import CrawlerService

pytestmark = pytest.mark.asyncio


HOME_HTML = """
<html><head>
  <meta property="og:title" content="Sunset Villa">
  <meta name="description" content="Heritage villa in Alibaug.">
</head><body>
  <a href="/contact">Contact</a>
  <a href="/about">About</a>
  <a href="/rooms">Rooms</a>
  <a href="https://external.com/foo">External</a>
  <img src="/img/hero.jpg" alt="Hero" width="1200" height="800">
  <p>Pool, lawn, terrace. Perfect for photoshoots.</p>
</body></html>
"""

CONTACT_HTML = """
<html><body>
  <a href="tel:+919876543210">Call</a>
  <a href="mailto:info@sunsetvilla.com">Email</a>
  <a href="https://wa.me/919876543210">WhatsApp</a>
  <form><input name="name"><input name="email"></form>
</body></html>
"""

ABOUT_HTML = """
<html><body>
  <p>Nestled along the Alibaug coast, Sunset Villa is a heritage property
  built in 1924, offering private lawns, a pool, and rooftop terrace.
  Known for hosting film shoots, brand campaigns, and outdoor events.</p>
</body></html>
"""


def _make_handler(
    responses: dict[str, tuple[int, str]],
    *,
    robots_txt: str = "",
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=robots_txt, headers={"content-type": "text/plain"})
        key = str(request.url)
        if key not in responses:
            # Strip trailing slash for matching
            key_alt = key.rstrip("/")
            if key_alt in responses:
                key = key_alt
        status, body = responses.get(key, (404, ""))
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})

    return handler


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "test"},
        follow_redirects=True,
    )


async def test_crawl_happy_path(
) -> None:
    responses: dict[str, tuple[int, str]] = {
        "https://sunset.com/": (200, HOME_HTML),
        "https://sunset.com/contact": (200, CONTACT_HTML),
        "https://sunset.com/about": (200, ABOUT_HTML),
        "https://sunset.com/rooms": (200, "<html><body>Rooms</body></html>"),
    }
    service = CrawlerService(
        per_domain_delay_seconds=0.0,
        http_client=_client(_make_handler(responses)),
    )

    result = await service.crawl_property(
        candidate_id="cand-1", website_url="https://sunset.com/"
    )

    assert result.crawl_status == "completed"
    assert result.pages_fetched >= 3  # home + contact + about (+ rooms)
    assert result.pages_failed == 0
    assert result.errors == []

    contacts = result.all_contacts()
    values = {c.value for c in contacts}
    assert any("9876543210" in v for v in values)
    assert any("sunsetvilla.com" in v for v in values)

    # Structured data captured meta title and og image absence tolerated.
    assert result.structured_data.meta_title == "Sunset Villa"
    assert "pool" in result.unstructured_data.amenities
    assert any("hero.jpg" in m.media_url for m in result.media_items)


async def test_crawl_handles_404_on_subpage() -> None:
    responses: dict[str, tuple[int, str]] = {
        "https://sunset.com/": (200, HOME_HTML),
        "https://sunset.com/contact": (404, ""),
        "https://sunset.com/about": (200, ABOUT_HTML),
    }
    service = CrawlerService(
        per_domain_delay_seconds=0.0,
        http_client=_client(_make_handler(responses)),
    )

    result = await service.crawl_property("cand-2", "https://sunset.com/")

    assert result.crawl_status == "partial"
    assert result.pages_failed >= 1


async def test_crawl_respects_robots_txt_disallow() -> None:
    responses: dict[str, tuple[int, str]] = {
        "https://blocked.com/": (200, HOME_HTML),
    }
    robots = "User-agent: *\nDisallow: /\n"
    service = CrawlerService(
        per_domain_delay_seconds=0.0,
        http_client=_client(_make_handler(responses, robots_txt=robots)),
    )

    result = await service.crawl_property("cand-3", "https://blocked.com/")

    assert result.crawl_status == "skipped_robots"
    assert result.pages_fetched == 0
    assert any("robots.txt" in e for e in result.errors)


async def test_crawl_fails_gracefully_on_no_website() -> None:
    service = CrawlerService(per_domain_delay_seconds=0.0)
    result = await service.crawl_property("cand-4", website_url="")
    assert result.crawl_status == "failed"
    assert result.pages_fetched == 0


async def test_crawl_stops_at_max_pages() -> None:
    many_links = "".join(
        f'<a href="/page{i}">P{i}</a>' for i in range(30)
    )
    home = f"<html><body>{many_links}<a href='/contact'>c</a><a href='/about'>a</a></body></html>"
    responses: dict[str, tuple[int, str]] = {
        "https://many.com/": (200, home),
        "https://many.com/contact": (200, "<html><body>ok</body></html>"),
        "https://many.com/about": (200, "<html><body>ok</body></html>"),
    }
    service = CrawlerService(
        max_pages=3,
        per_domain_delay_seconds=0.0,
        http_client=_client(_make_handler(responses)),
    )

    result = await service.crawl_property("cand-5", "https://many.com/")
    assert result.pages_fetched <= 3


async def test_crawl_snapshot_hash_stable_across_runs(
) -> None:
    responses: dict[str, tuple[int, str]] = {
        "https://sunset.com/": (200, HOME_HTML),
        "https://sunset.com/contact": (200, CONTACT_HTML),
    }

    def _run() -> Any:
        return CrawlerService(
            per_domain_delay_seconds=0.0,
            http_client=_client(_make_handler(responses)),
        )

    r1 = await _run().crawl_property("c", "https://sunset.com/")
    r2 = await _run().crawl_property("c", "https://sunset.com/")
    assert r1.snapshot_hash == r2.snapshot_hash
    assert r1.snapshot_hash  # non-empty


async def test_crawl_does_not_follow_external_links() -> None:
    """External links discovered on the homepage must NOT be crawled."""
    responses: dict[str, tuple[int, str]] = {
        "https://sunset.com/": (200, HOME_HTML),
        "https://sunset.com/contact": (200, CONTACT_HTML),
        "https://sunset.com/about": (200, ABOUT_HTML),
        "https://sunset.com/rooms": (200, "<html></html>"),
    }
    visited_external = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal visited_external
        if request.url.host == "external.com":
            visited_external = True
            return httpx.Response(200, text="<html></html>")
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        status, body = responses.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)

    service = CrawlerService(
        per_domain_delay_seconds=0.0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await service.crawl_property("c", "https://sunset.com/")
    assert visited_external is False
