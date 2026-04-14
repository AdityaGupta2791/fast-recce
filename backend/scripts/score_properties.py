"""Score properties using M7's ScoringService.

Modes:
    --all        Score all unscored, non-duplicate properties (default).
    --property-id <uuid>   Score a single property (re-score if already scored).
    --rescore-all  Re-score every property (including already scored).

After scoring, prints the top-N leaderboard.
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
from app.services.contact_service import ContactService
from app.services.property_service import PropertyService
from app.services.scoring_service import ScoringService


async def _score_one(
    property_id: UUID, service: ScoringService
) -> None:
    result = await service.score_property(property_id)
    print(f"\n--- property {result.property_id} ---")
    print(f"  relevance_score: {result.relevance_score:.3f}")
    if result.llm_sub_scores_used_fallback:
        print("  (LLM fallback used for at least one sub-score)")
    for s in result.sub_scores:
        marker = "*" if s.source == "llm" else " "
        print(
            f"  {marker} {s.name:22s} {s.value:.2f} x {s.weight:.2f} "
            f"= {s.value * s.weight:.3f}   [{s.source}]  {s.reasoning[:60]}"
        )


async def _print_leaderboard(db: object, limit: int = 5) -> None:
    stmt = (
        select(Property)
        .where(Property.is_duplicate.is_(False))
        .where(Property.scored_at.is_not(None))
        .order_by(Property.relevance_score.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()  # type: ignore[attr-defined]

    print()
    print("=" * 70)
    print(f"Top {len(rows)} properties by relevance_score")
    print("=" * 70)
    for i, prop in enumerate(rows, start=1):
        score_display = f"{prop.relevance_score:.3f}" if prop.relevance_score is not None else "n/a"
        print(
            f"{i:2d}. {score_display}  [{prop.property_type:14s}] "
            f"{prop.canonical_name[:50]:50s}  {prop.city}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Score properties (M7).")
    parser.add_argument("--property-id", default=None)
    parser.add_argument("--rescore-all", action="store_true")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between properties (use ~25 on Gemini free tier)",
    )
    args = parser.parse_args()

    settings = get_settings()
    llm = LLMClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )

    async with SessionLocal() as db:
        property_service = PropertyService(db=db)
        contact_service = ContactService(db=db, property_service=property_service)
        scoring_service = ScoringService(
            db=db,
            llm_client=llm,
            property_service=property_service,
            contact_service=contact_service,
        )

        if args.property_id:
            await _score_one(UUID(args.property_id), scoring_service)
        else:
            print(
                f"Scoring properties (delay={args.delay}s between properties)..."
            )
            result = await scoring_service.score_batch(
                only_unscored=not args.rescore_all,
                per_property_delay_seconds=args.delay,
            )
            print()
            print(f"  scored:           {result.scored}")
            print(f"  failed:           {result.failed}")
            print(f"  llm fallbacks:    {result.llm_fallbacks_used}")
            print(f"  average score:    {result.avg_score}")
            if result.top_property_id:
                print(
                    f"  top property:     {result.top_property_id} "
                    f"(score {result.top_property_score})"
                )
            print(f"  duration:         {result.duration_seconds}s")

        await db.commit()
        await _print_leaderboard(db)

    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
