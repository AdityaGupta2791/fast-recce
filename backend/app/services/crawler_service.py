"""CrawlerService — M4. Crawls a property's website and returns a CrawlResult.

Flow per candidate:
1. Fetch robots.txt for the domain (cached). Skip if crawling disallowed.
2. Fetch the homepage.
3. Discover internal links matching /contact, /about, /venue, /events, /rooms.
4. Fetch each target page (bounded by max_pages).
5. Run the three extractors (structured, unstructured, media).
6. Compute a snapshot hash of concatenated page content hashes.
7. Return a CrawlResult.

Concurrency is per-domain: at most `per_domain_concurrency` simultaneous
requests to the same host, with a 1s delay between sequential requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

from app.schemas.crawl import (
    CrawlResult,
    FetchedPage,
    PageType,
    StructuredData,
    UnstructuredData,
)
from app.services.extractors.media import MediaExtractor
from app.services.extractors.structured import StructuredExtractor
from app.services.extractors.unstructured import UnstructuredExtractor

_USER_AGENT = (
    "FastRecceCrawler/0.1 (+https://fastrecce.example/bots; internal research)"
)

# Candidate paths to probe for richer content. Order matters — we try likely
# locations first and stop once we have enough pages.
_TARGET_PATH_PATTERNS: list[tuple[PageType, tuple[str, ...]]] = [
    ("contact", ("/contact", "/contact-us", "/contactus", "/reach-us")),
    ("about", ("/about", "/about-us", "/our-story", "/story")),
    ("venue", ("/venues", "/spaces", "/the-villa", "/the-resort")),
    ("events", ("/events", "/weddings", "/book-event")),
    ("rooms", ("/rooms", "/suites", "/accommodations")),
]


@dataclass
class _DomainState:
    semaphore: asyncio.Semaphore
    last_request_at: float = 0.0
    robots: RobotFileParser | None = None
    robots_fetched: bool = False


@dataclass
class CrawlerService:
    """Crawls a single property's website and returns structured output."""

    structured_extractor: StructuredExtractor = field(default_factory=StructuredExtractor)
    unstructured_extractor: UnstructuredExtractor = field(default_factory=UnstructuredExtractor)
    media_extractor: MediaExtractor = field(default_factory=MediaExtractor)
    timeout_seconds: float = 30.0
    max_pages: int = 6
    per_domain_concurrency: int = 2
    per_domain_delay_seconds: float = 1.0
    http_client: httpx.AsyncClient | None = None

    _domains: dict[str, _DomainState] = field(default_factory=dict)

    async def crawl_property(
        self, candidate_id: str, website_url: str
    ) -> CrawlResult:
        """Full crawl pipeline for a single property."""
        start = time.monotonic()
        errors: list[str] = []

        if not website_url:
            return _empty_result(
                candidate_id, website_url, "failed",
                errors=["no website_url provided"],
                duration=round(time.monotonic() - start, 3),
            )

        domain = _domain_of(website_url)
        if not domain:
            return _empty_result(
                candidate_id, website_url, "failed",
                errors=[f"could not parse domain from '{website_url}'"],
                duration=round(time.monotonic() - start, 3),
            )

        client = self.http_client or httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        owns_client = self.http_client is None

        try:
            allowed = await self._check_robots(client, website_url, errors)
            if not allowed:
                return _empty_result(
                    candidate_id, website_url, "skipped_robots",
                    errors=errors,
                    duration=round(time.monotonic() - start, 3),
                )

            pages = await self._fetch_pages(client, website_url, errors)

            structured = self.structured_extractor.extract(pages)
            unstructured = self.unstructured_extractor.extract(pages)
            media = self.media_extractor.extract(pages)

            successful = [p for p in pages if p.status_code < 400 and p.error is None]
            failed = [p for p in pages if p not in successful]

            snapshot_hash = _snapshot_hash([p.content_hash for p in successful])
            status = (
                "failed" if not successful
                else "partial" if failed
                else "completed"
            )

            return CrawlResult(
                candidate_id=candidate_id,
                website_url=website_url,
                pages_fetched=len(successful),
                pages_failed=len(failed),
                snapshot_hash=snapshot_hash,
                crawl_status=status,
                duration_seconds=round(time.monotonic() - start, 3),
                errors=errors,
                structured_data=structured,
                unstructured_data=unstructured,
                media_items=media,
                pages=pages,
            )
        finally:
            if owns_client:
                await client.aclose()

    # --- Fetching ---

    async def _fetch_pages(
        self,
        client: httpx.AsyncClient,
        homepage_url: str,
        errors: list[str],
    ) -> list[FetchedPage]:
        pages: list[FetchedPage] = []
        visited: set[str] = set()

        home = await self._fetch_single(client, homepage_url, "home", errors)
        if home is not None:
            pages.append(home)
            visited.add(_canonical_url(home.url))

        # Discover internal links from homepage.
        target_urls = self._discover_targets(pages) if pages else []

        for page_type, url in target_urls:
            if len(pages) >= self.max_pages:
                break
            canonical = _canonical_url(url)
            if canonical in visited:
                continue
            visited.add(canonical)
            page = await self._fetch_single(client, url, page_type, errors)
            if page is not None:
                pages.append(page)

        return pages

    def _discover_targets(
        self, pages: list[FetchedPage]
    ) -> list[tuple[PageType, str]]:
        """Walk the homepage anchor tags to find target-type sub-pages."""
        if not pages:
            return []
        home = pages[0]
        soup = BeautifulSoup(home.html, "lxml")
        base = home.url

        hits: dict[str, tuple[PageType, str]] = {}
        for anchor in soup.find_all("a", href=True):
            if not isinstance(anchor, Tag):
                continue
            href = anchor["href"].strip()
            if not href or href.startswith(("#", "javascript:")):
                continue

            absolute = urljoin(base, href)
            if not absolute.startswith(("http://", "https://")):
                continue
            if _domain_of(absolute) != _domain_of(base):
                continue

            path = urlparse(absolute).path.lower().rstrip("/")
            for page_type, patterns in _TARGET_PATH_PATTERNS:
                if any(p in path for p in patterns):
                    hits.setdefault(absolute, (page_type, absolute))
                    break

        # Return in PATTERN order to prioritize contact > about > venue > ...
        ordered: list[tuple[PageType, str]] = []
        for page_type, _patterns in _TARGET_PATH_PATTERNS:
            for url, (hit_type, hit_url) in hits.items():
                if hit_type == page_type and (page_type, hit_url) not in ordered:
                    ordered.append((page_type, hit_url))
        return ordered

    async def _fetch_single(
        self,
        client: httpx.AsyncClient,
        url: str,
        page_type: PageType,
        errors: list[str],
    ) -> FetchedPage | None:
        domain = _domain_of(url)
        if not domain:
            return None

        state = self._get_domain_state(domain)
        async with state.semaphore:
            delay_needed = (state.last_request_at + self.per_domain_delay_seconds) - time.monotonic()
            if delay_needed > 0:
                await asyncio.sleep(delay_needed)

            try:
                resp = await client.get(url)
                state.last_request_at = time.monotonic()
            except httpx.HTTPError as exc:
                state.last_request_at = time.monotonic()
                errors.append(f"fetch failed for {url}: {exc}")
                return FetchedPage(
                    url=url,
                    page_type=page_type,
                    status_code=0,
                    html="",
                    content_hash="",
                    fetched_at=_utcnow_iso(),
                    error=str(exc),
                )

            html = resp.text if resp.status_code < 400 else ""
            return FetchedPage(
                url=str(resp.url),
                page_type=page_type,
                status_code=resp.status_code,
                html=html,
                content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest() if html else "",
                fetched_at=_utcnow_iso(),
                error=None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )

    # --- robots.txt ---

    async def _check_robots(
        self, client: httpx.AsyncClient, url: str, errors: list[str]
    ) -> bool:
        domain = _domain_of(url)
        if not domain:
            return True
        state = self._get_domain_state(domain)

        if not state.robots_fetched:
            robots_url = urljoin(url, "/robots.txt")
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                resp = await client.get(robots_url, timeout=10.0)
                if resp.status_code == 200 and resp.text:
                    parser.parse(resp.text.splitlines())
                else:
                    parser.parse([])
            except httpx.HTTPError:
                # Missing/unreachable robots.txt means "no restrictions stated".
                parser.parse([])
            state.robots = parser
            state.robots_fetched = True

        parser = state.robots
        if parser is None:
            return True
        allowed = parser.can_fetch(_USER_AGENT, url)
        if not allowed:
            errors.append(f"robots.txt disallows {url}")
        return allowed

    def _get_domain_state(self, domain: str) -> _DomainState:
        if domain not in self._domains:
            self._domains[domain] = _DomainState(
                semaphore=asyncio.Semaphore(self.per_domain_concurrency)
            )
        return self._domains[domain]


# --- Module-private helpers ---


def _domain_of(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or "").lower()


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _snapshot_hash(page_hashes: list[str]) -> str:
    joined = "|".join(sorted(h for h in page_hashes if h))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else ""


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_result(
    candidate_id: str,
    website_url: str,
    status: str,
    errors: list[str],
    duration: float,
) -> CrawlResult:
    return CrawlResult(
        candidate_id=candidate_id,
        website_url=website_url,
        pages_fetched=0,
        pages_failed=0,
        snapshot_hash="",
        crawl_status=status,  # type: ignore[arg-type]
        duration_seconds=duration,
        errors=errors,
        structured_data=StructuredData(),
        unstructured_data=UnstructuredData(),
        media_items=[],
        pages=[],
    )


