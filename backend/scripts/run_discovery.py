"""Manual discovery run — handy for smoke-testing against the real API.

Usage:
    python -m scripts.run_discovery --cities Alibaug --max-queries 1
    python -m scripts.run_discovery --cities Mumbai Pune --max-queries 3
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.database import SessionLocal
from app.integrations.google_places import GooglePlacesClient
from app.services.discovery_service import DiscoveryService
from app.services.query_bank_service import QueryBankService
from app.services.source_service import SourceService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a one-off discovery pass.")
    parser.add_argument("--cities", nargs="*", default=None)
    parser.add_argument("--property-types", nargs="*", default=None)
    parser.add_argument("--max-queries", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()

    async with GooglePlacesClient(api_key=settings.google_places_api_key) as google:
        async with SessionLocal() as db:
            service = DiscoveryService(
                db=db,
                google_client=google,
                source_service=SourceService(db=db),
                query_bank_service=QueryBankService(db=db),
            )
            result = await service.discover(
                cities=args.cities,
                property_types=args.property_types,
                max_queries=args.max_queries,
            )
            await db.commit()

            print("=" * 60)
            print("Discovery run result")
            print("=" * 60)
            print(f"queries executed:    {result.queries_executed}")
            print(f"google results:      {result.google_results_total}")
            print(f"candidates created:  {result.candidates_created}")
            print(f"skipped (known):     {result.candidates_skipped_known}")
            print(f"errors:              {len(result.errors)}")
            for err in result.errors:
                print(f"  - {err}")
            print(f"duration:            {result.duration_seconds}s")

            recent = await service.list_recent_candidates(limit=10)
            print()
            print(f"Most recent {len(recent)} candidates:")
            for c in recent:
                print(
                    f"  - [{c.property_type:12s}] {c.name[:45]:45s} "
                    f"{c.city:10s} rating={c.google_rating} "
                    f"website={'yes' if c.website else 'no ':3s} "
                    f"phone={'yes' if c.phone else 'no'}"
                )


if __name__ == "__main__":
    asyncio.run(main())
