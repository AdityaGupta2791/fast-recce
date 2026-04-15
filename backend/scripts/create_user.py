"""Create or update a dashboard user.

Usage:
    python -m scripts.create_user --email admin@fastrecce.local --password adminpass --role admin --name "Admin User"
    python -m scripts.create_user --email me@fastrecce.local --password pass1234  # defaults to viewer
"""

from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.exceptions import ConflictError
from app.schemas.auth import UserCreate, UserUpdate
from app.services.auth_service import hash_password
from app.services.user_service import UserService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a dashboard user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Unnamed User")
    parser.add_argument(
        "--role",
        default="viewer",
        choices=["admin", "reviewer", "sales", "viewer"],
    )
    args = parser.parse_args()

    async with SessionLocal() as db:
        service = UserService(db=db)
        try:
            user = await service.create(
                UserCreate(
                    email=args.email,
                    password=args.password,
                    full_name=args.name,
                    role=args.role,
                )
            )
            action = "created"
        except ConflictError:
            existing = await service.get_by_email(args.email)
            assert existing is not None
            existing.password_hash = hash_password(args.password)
            await service.update(
                existing.id,
                UserUpdate(role=args.role, full_name=args.name, is_active=True),
            )
            user = existing
            action = "updated"

        await db.commit()
        print(f"{action} user: {user.email}  role={user.role}  id={user.id}")


if __name__ == "__main__":
    asyncio.run(main())
