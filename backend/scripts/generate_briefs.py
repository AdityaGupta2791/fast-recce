"""Generate operational briefs for properties (M8).

Usage:
    python -m scripts.generate_briefs                         # all unbriefed
    python -m scripts.generate_briefs --property-id <uuid>    # single
    python -m scripts.generate_briefs --regenerate-all        # rewrite everything
    python -m scripts.generate_briefs --delay 25              # throttle for free tier
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.integrations.llm import LLMClient
from app.models.property import Property
from app.services.briefing_service import BriefingService
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService


async def _show_brief(db: object, property_id: UUID) -> None:
    prop = await PropertyService(db=db).get(property_id)  # type: ignore[arg-type]
    print()
    print(f"--- {prop.canonical_name} ({prop.city}) ---")
    print(f"  score: {prop.relevance_score}")
    print(f"  brief: {prop.short_brief}")


async def _print_briefs(db: object, limit: int = 10) -> None:
    stmt = (
        select(Property)
        .where(Property.is_duplicate.is_(False))
        .where(Property.short_brief.is_not(None))
        .order_by(Property.relevance_score.desc().nulls_last())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()  # type: ignore[attr-defined]

    print()
    print("=" * 70)
    print(f"Top {len(rows)} briefs")
    print("=" * 70)
    for prop in rows:
        score = f"{prop.relevance_score:.2f}" if prop.relevance_score else "n/a"
        print()
        print(f"[{score}] {prop.canonical_name}  ({prop.city})")
        print(f"  {prop.short_brief}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI briefs (M8).")
    parser.add_argument("--property-id", default=None)
    parser.add_argument("--regenerate-all", action="store_true")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between properties (use ~25 on Gemini free tier)",
    )
    args = parser.parse_args()

    settings = get_settings()
    llm = LLMClient(api_key=settings.gemini_api_key, model=settings.gemini_model)

    async with SessionLocal() as db:
        property_service = PropertyService(db=db)
        contact_service = ContactService(db=db, property_service=property_service)
        briefing_service = BriefingService(
            db=db,
            llm_client=llm,
            property_service=property_service,
            contact_service=contact_service,
        )

        if args.property_id:
            pid = UUID(args.property_id)
            result = await briefing_service.generate_brief(
                pid, force=args.regenerate_all
            )
            await db.commit()
            print(f"source:       {result.source}")
            print(f"regenerated:  {result.regenerated}")
            await _show_brief(db, pid)
        else:
            print(f"Generating briefs (delay={args.delay}s between properties)...")
            result = await briefing_service.generate_batch(
                only_unbriefed=not args.regenerate_all,
                per_property_delay_seconds=args.delay,
            )
            await db.commit()
            print()
            print(f"  generated:         {result.generated}")
            print(f"  skipped (cached):  {result.skipped_unchanged}")
            print(f"  failed:            {result.failed}")
            print(f"  llm fallbacks:     {result.llm_fallbacks_used}")
            print(f"  duration:          {result.duration_seconds}s")
            await _print_briefs(db)

    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
