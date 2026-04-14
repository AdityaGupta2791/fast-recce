"""Manual crawl run — pick a discovery candidate and crawl its website.

Usage:
    python -m scripts.run_crawl                       # picks the first candidate with a website
    python -m scripts.run_crawl --candidate-id <uuid> # targets a specific candidate
    python -m scripts.run_crawl --website-url https://example.com  # ad-hoc crawl
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.database import SessionLocal
from app.models.discovery import DiscoveryCandidate
from app.services.crawler_service import CrawlerService


async def _pick_candidate(website_url: str | None, candidate_id: str | None) -> tuple[str, str]:
    if website_url:
        return ("ad-hoc", website_url)

    async with SessionLocal() as db:
        if candidate_id:
            row = await db.get(DiscoveryCandidate, UUID(candidate_id))
            if row is None:
                raise SystemExit(f"no candidate with id {candidate_id}")
        else:
            stmt = (
                select(DiscoveryCandidate)
                .where(DiscoveryCandidate.website.is_not(None))
                .order_by(DiscoveryCandidate.discovered_at.desc())
                .limit(1)
            )
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise SystemExit(
                    "no discovery candidates with a website — run `scripts.run_discovery` first"
                )
        if not row.website:
            raise SystemExit(f"candidate {row.id} has no website_url")
        return (str(row.id), row.website)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl a property website.")
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--website-url", default=None)
    parser.add_argument("--max-pages", type=int, default=6)
    args = parser.parse_args()

    candidate_id, website = await _pick_candidate(args.website_url, args.candidate_id)

    print(f"Crawling candidate={candidate_id} website={website}")

    service = CrawlerService(max_pages=args.max_pages)
    result = await service.crawl_property(candidate_id, website)

    _print_result(result)


def _print_result(result: object) -> None:
    from app.schemas.crawl import CrawlResult

    r: CrawlResult = result  # type: ignore[assignment]
    print()
    print("=" * 70)
    print("Crawl result")
    print("=" * 70)
    print(f"status:         {r.crawl_status}")
    print(f"pages fetched:  {r.pages_fetched}")
    print(f"pages failed:   {r.pages_failed}")
    print(f"duration:       {r.duration_seconds}s")
    print(f"snapshot hash:  {r.snapshot_hash[:16]}..." if r.snapshot_hash else "snapshot hash:  (none)")

    if r.errors:
        print()
        print("Errors:")
        for err in r.errors:
            print(f"  - {err}")

    print()
    print("Pages crawled:")
    for page in r.pages:
        marker = "OK" if page.status_code < 400 and page.error is None else "XX"
        print(f"  {marker} [{page.page_type:8s}] HTTP {page.status_code:3d}  {page.url}")

    sd = r.structured_data
    print()
    print("Structured data:")
    print(f"  meta_title:       {sd.meta_title}")
    print(f"  meta_description: {_trim(sd.meta_description, 80)}")
    print(f"  og_image:         {_trim(sd.og_image, 80)}")
    print(f"  phones ({len(sd.phones)}):    {[c.value for c in sd.phones[:3]]}")
    print(f"  emails ({len(sd.emails)}):    {[c.value for c in sd.emails[:3]]}")
    print(f"  whatsapp ({len(sd.whatsapp_links)}): {[c.value for c in sd.whatsapp_links[:2]]}")
    print(f"  contact_forms ({len(sd.contact_forms)})")
    print(f"  addresses:        {sd.addresses[:2]}")

    ud = r.unstructured_data
    print()
    print("Unstructured data:")
    print(f"  description:      {_trim(ud.description, 160)}")
    print(f"  amenities ({len(ud.amenities)}):  {ud.amenities}")
    print(f"  feature_tags:     {ud.feature_tags}")
    print(f"  text_contacts ({len(ud.text_contacts)})")

    print()
    print(f"Media items: {len(r.media_items)}")
    for item in r.media_items[:5]:
        alt = f'  alt="{item.alt_text}"' if item.alt_text else ""
        print(f"  - {item.media_url}{alt}")

    print()
    print("All contacts (ordered by confidence):")
    for c in r.all_contacts()[:10]:
        print(f"  {c.confidence:.2f}  [{c.contact_type:8s}/{c.extraction_method:14s}] {c.value}")


def _trim(value: str | None, n: int) -> str:
    if value is None:
        return "(none)"
    return value[:n] + ("..." if len(value) > n else "")


if __name__ == "__main__":
    asyncio.run(main())
