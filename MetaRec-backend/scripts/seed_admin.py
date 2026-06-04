"""Promote registered users to the ADMIN role.

Usage:
    python scripts/seed_admin.py admin@example.com [other@example.com ...]
    # or, with no args, fall back to the METAREC_ADMIN_EMAILS env allowlist:
    METAREC_ADMIN_EMAILS="admin@example.com" python scripts/seed_admin.py

Idempotent: a user must already exist (register first); unknown emails are
skipped. Requires DATABASE_URL to be set.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make backend modules importable. Importing business_db at module load (before
# asyncio.run creates the event loop) lets it install the Windows selector-loop
# policy that psycopg's async driver requires.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from business_repositories import auth_repository  # noqa: E402
from business_db import dispose_async_engine  # noqa: E402


def _emails_from_args_or_env() -> list[str]:
    if len(sys.argv) > 1:
        return [arg.strip() for arg in sys.argv[1:] if arg.strip()]
    raw = os.getenv("METAREC_ADMIN_EMAILS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _run(emails: list[str]) -> int:
    try:
        return await auth_repository.promote_admins(emails)
    finally:
        await dispose_async_engine()


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(2)

    emails = _emails_from_args_or_env()
    if not emails:
        print(
            "No emails provided. Pass them as arguments or set METAREC_ADMIN_EMAILS.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    promoted = asyncio.run(_run(emails))
    print(f"Promoted {promoted}/{len(emails)} user(s) to ADMIN: {', '.join(emails)}")
    skipped = len(emails) - promoted
    if skipped:
        print(f"{skipped} email(s) had no matching registered user and were skipped.")


if __name__ == "__main__":
    main()
