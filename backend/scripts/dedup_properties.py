"""Run dedup over the properties table.

Modes:
    --mode list       Show candidate duplicate pairs without changes (default).
    --mode auto       Auto-merge pairs at confidence >= AUTO_MERGE_THRESHOLD.
    --mode merge      Merge a specific pair: --source <uuid> --target <uuid>.

Examples:
    python -m scripts.dedup_properties --mode list
    python -m scripts.dedup_properties --mode list --city Alibaug
    python -m scripts.dedup_properties --mode auto --city Alibaug
    python -m scripts.dedup_properties --mode merge --source <uuid> --target <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.database import SessionLocal
from app.services.contact_service import ContactService
from app.services.dedup_service import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    DedupService,
)
from app.services.property_service import PropertyService


async def cmd_list(city: str | None) -> None:
    async with SessionLocal() as db:
        property_service = PropertyService(db=db)
        dedup = DedupService(db=db, property_service=property_service)

        result = await dedup.run_batch_dedup(
            city=city, confidence_threshold=REVIEW_THRESHOLD, auto_merge=False
        )

        print("=" * 70)
        print("Batch dedup (list mode)")
        print("=" * 70)
        print(f"properties scanned: {result.pairs_compared}")
        print(f"flagged pairs:      {result.flagged_for_review}")
        print(f"duration:           {result.duration_seconds}s")
        print()

        if not result.pairs:
            print("No duplicate pairs found.")
            return

        for older_id, newer_id, confidence in sorted(
            result.pairs, key=lambda p: -p[2]
        ):
            older = await property_service.get(older_id)
            newer = await property_service.get(newer_id)
            tag = "AUTO" if confidence >= AUTO_MERGE_THRESHOLD else "REVIEW"
            print(f"[{tag}] confidence={confidence:.2f}")
            print(f"   older  ({older_id}) : {older.canonical_name}  [{older.city}]")
            print(f"   newer  ({newer_id}) : {newer.canonical_name}  [{newer.city}]")
            print()


async def cmd_auto(city: str | None) -> None:
    async with SessionLocal() as db:
        property_service = PropertyService(db=db)
        dedup = DedupService(db=db, property_service=property_service)

        result = await dedup.run_batch_dedup(city=city, auto_merge=True)
        await db.commit()

        print("=" * 70)
        print("Batch dedup (auto-merge mode)")
        print("=" * 70)
        print(f"properties scanned: {result.pairs_compared}")
        print(f"auto-merged:        {result.auto_merged}")
        print(f"flagged for review: {result.flagged_for_review}")
        print(f"duration:           {result.duration_seconds}s")


async def cmd_merge(source: UUID, target: UUID) -> None:
    async with SessionLocal() as db:
        property_service = PropertyService(db=db)
        dedup = DedupService(db=db, property_service=property_service)
        contact_service = ContactService(db=db, property_service=property_service)

        result = await dedup.merge_properties(source_id=source, target_id=target)
        await db.commit()

        print(f"Merge: {result.status}")
        print(f"  contacts moved:        {result.contacts_moved}")
        print(f"  contacts already had:  {result.contacts_already_existed}")

        # Show target's resulting contacts.
        contacts = await contact_service.get_contacts_for_property(target)
        print(f"\nTarget now has {len(contacts)} contact(s):")
        for c in contacts[:10]:
            primary = " (primary)" if c.is_primary else ""
            flag = " (flagged)" if c.flagged_personal else ""
            print(
                f"  {c.confidence:.2f} [{c.contact_type:8s}] "
                f"{c.contact_value}{primary}{flag}"
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Property dedup runner.")
    parser.add_argument("--mode", choices=["list", "auto", "merge"], default="list")
    parser.add_argument("--city", default=None)
    parser.add_argument("--source", default=None, help="source property UUID (for merge)")
    parser.add_argument("--target", default=None, help="target property UUID (for merge)")
    args = parser.parse_args()

    if args.mode == "merge":
        if not args.source or not args.target:
            raise SystemExit("--mode merge requires --source and --target UUIDs")
        await cmd_merge(UUID(args.source), UUID(args.target))
    elif args.mode == "auto":
        await cmd_auto(args.city)
    else:
        await cmd_list(args.city)


if __name__ == "__main__":
    asyncio.run(main())
