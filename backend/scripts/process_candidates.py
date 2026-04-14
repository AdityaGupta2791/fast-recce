"""End-to-end pipeline runner: discovery_candidates -> properties + contacts.

For each pending DiscoveryCandidate:
  1. Crawl the website (M4)
  2. Upsert a Property row (M5/PropertyService)
  3. Resolve contacts from API + crawl (M5/ContactService)
  4. Mark the candidate as 'processed' (or 'failed' on error)

Usage:
    python -m scripts.process_candidates --limit 3
    python -m scripts.process_candidates --candidate-id <uuid>
    python -m scripts.process_candidates --limit 10 --skip-no-website
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.database import SessionLocal
from app.models.discovery import DiscoveryCandidate
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.contact_service import ContactService
from app.services.crawler_service import CrawlerService
from app.services.discovery_service import DiscoveryService
from app.services.property_service import PropertyService
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService


async def _pick_candidates(
    db: object, candidate_id: str | None, limit: int, skip_no_website: bool
) -> list[DiscoveryCandidate]:
    if candidate_id:
        row = await db.get(DiscoveryCandidate, UUID(candidate_id))  # type: ignore[attr-defined]
        if row is None:
            raise SystemExit(f"no candidate with id {candidate_id}")
        return [row]

    stmt = (
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.processing_status == "pending")
        .order_by(DiscoveryCandidate.discovered_at)
    )
    if skip_no_website:
        stmt = stmt.where(DiscoveryCandidate.website.is_not(None))
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)  # type: ignore[attr-defined]
    return list(result.scalars().all())


def _api_contact_from_candidate(c: DiscoveryCandidate) -> list[ExtractedContact]:
    """Build ExtractedContacts from the structured Google Places fields."""
    contacts: list[ExtractedContact] = []
    if c.phone:
        contacts.append(
            ExtractedContact(
                contact_type="phone",
                value=c.phone,
                source_url="",
                extraction_method="api_structured",
                confidence=0.95,
            )
        )
    if c.website:
        contacts.append(
            ExtractedContact(
                contact_type="website",
                value=c.website,
                source_url="",
                extraction_method="api_structured",
                confidence=0.95,
            )
        )
    return contacts


async def _process_one(
    candidate: DiscoveryCandidate,
    crawler: CrawlerService,
    property_service: PropertyService,
    contact_service: ContactService,
    discovery_service: DiscoveryService,
) -> None:
    print(f"\n--- {candidate.name[:60]} ({candidate.id}) ---")
    print(f"   website: {candidate.website or '(none)'}")

    # 1. Crawl website if there is one.
    crawl_result = None
    if candidate.website:
        crawl_result = await crawler.crawl_property(
            str(candidate.id), candidate.website
        )
        print(
            f"   crawl: {crawl_result.crawl_status}, "
            f"{crawl_result.pages_fetched} pages, "
            f"{len(crawl_result.errors)} errors"
        )

    # 2. Upsert property.
    payload = PropertyUpsertFromCandidate(
        candidate_id=candidate.id,
        canonical_name=candidate.name,
        city=candidate.city,
        locality=candidate.locality,
        lat=candidate.lat,
        lng=candidate.lng,
        property_type=candidate.property_type,  # type: ignore[arg-type]
        google_place_id=candidate.external_id,
        google_rating=candidate.google_rating,
        google_review_count=candidate.google_review_count,
        website=candidate.website,
        features_json=(
            {
                "amenities": crawl_result.unstructured_data.amenities,
                "feature_tags": crawl_result.unstructured_data.feature_tags,
                "description": crawl_result.unstructured_data.description,
            }
            if crawl_result
            else {}
        ),
    )
    prop = await property_service.upsert_from_candidate(payload)
    print(f"   property: {prop.id}  ({'reused' if prop.canonical_phone else 'new'})")

    # 3. Resolve contacts.
    api_contacts = _api_contact_from_candidate(candidate)
    crawl_contacts = crawl_result.all_contacts() if crawl_result else []
    result = await contact_service.resolve_contacts(prop.id, api_contacts, crawl_contacts)
    print(
        f"   contacts: in={result.contacts_in}, "
        f"persisted={result.contacts_persisted}, "
        f"flagged={result.contacts_flagged_personal}, "
        f"dnc_blocked={result.contacts_blocked_by_dnc}"
    )
    print(f"   canonical phone: {result.canonical_phone}")
    print(f"   canonical email: {result.canonical_email}")

    # 4. Mark candidate processed.
    await discovery_service.mark_processed(candidate.id)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the M3->M4->M5 chain.")
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--skip-no-website", action="store_true", default=True)
    args = parser.parse_args()

    crawler = CrawlerService()
    async with SessionLocal() as db:
        candidates = await _pick_candidates(
            db, args.candidate_id, args.limit, args.skip_no_website
        )
        if not candidates:
            print("no pending candidates with websites — nothing to do")
            return

        property_service = PropertyService(db=db)
        contact_service = ContactService(db=db, property_service=property_service)
        # DiscoveryService just for mark_processed; pass None for google_client since unused.
        discovery_service = DiscoveryService(
            db=db,
            google_client=None,  # type: ignore[arg-type]
            source_service=SourceService(db=db),
            query_bank_service=QueryBankService(db=db),
        )

        print(f"Processing {len(candidates)} candidate(s)...")
        success = 0
        failed = 0
        for c in candidates:
            try:
                await _process_one(
                    c, crawler, property_service, contact_service, discovery_service
                )
                success += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"   FAILED: {exc}")
                await discovery_service.mark_failed(c.id, str(exc))
            await db.commit()

        print()
        print("=" * 60)
        print(f"Processed: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
