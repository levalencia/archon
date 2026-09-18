"""Promote exactly one existing user to the sole administrator role."""

from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.services.db_store import DatabaseStore


async def promote(email: str) -> None:
    settings = Settings()
    store = DatabaseStore(settings.database_url)
    try:
        user = await store.promote_sole_admin(email)
    finally:
        await store.close()
    print(f"ADMIN_PROMOTION=PASS user_id={user['user_id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing user's email address")
    args = parser.parse_args()
    asyncio.run(promote(args.email))


if __name__ == "__main__":
    main()
