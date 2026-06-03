"""Idempotently seed a full admin login account into PostgreSQL.

Unlike scripts/seed_admin.py (which only *promotes* an already-registered user),
this creates the account if it does not exist yet, then ensures it has the ADMIN
role. Safe to run repeatedly:

    python scripts/seed_admin_user.py [email] [password]
    # or via env:
    SEED_ADMIN_EMAIL=admin@metarec.local SEED_ADMIN_PASSWORD=Admin12345! \
        python scripts/seed_admin_user.py

Behavior:
    - If no user with the email exists -> register it, then set role=admin.
    - If the user already exists       -> leave the password untouched, just
                                          (re)ensure role=admin.

Requires DATABASE_URL to be set.
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

from business_models import UserRole  # noqa: E402
from business_repositories import auth_repository  # noqa: E402
from business_db import dispose_async_engine  # noqa: E402

DEFAULT_EMAIL = "admin@metarec.local"
DEFAULT_PASSWORD = "Admin12345!"


def _credentials() -> tuple[str, str]:
    email = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("SEED_ADMIN_EMAIL") or DEFAULT_EMAIL).strip()
    password = sys.argv[2] if len(sys.argv) > 2 else os.getenv("SEED_ADMIN_PASSWORD") or DEFAULT_PASSWORD
    return email, password


async def _seed(email: str, password: str) -> str:
    """Returns one of: 'created', 'exists'. Always ensures ADMIN role."""
    try:
        try:
            await auth_repository.register(email=email, password=password, display_name="Admin")
            outcome = "created"
        except ValueError as exc:
            if "already registered" not in str(exc):
                raise
            outcome = "exists"
        # Idempotently (re)assert the admin role either way.
        if not await auth_repository.set_role_by_email(email, UserRole.ADMIN):
            raise RuntimeError(f"could not set admin role for {email} (user not found after seed)")
        return outcome
    finally:
        await dispose_async_engine()


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(2)

    email, password = _credentials()
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        raise SystemExit(2)

    outcome = asyncio.run(_seed(email, password))
    if outcome == "created":
        print(f"Seeded new ADMIN account: {email} (password set as provided)")
    else:
        print(f"Account {email} already existed; ensured ADMIN role (password left unchanged)")


if __name__ == "__main__":
    main()
