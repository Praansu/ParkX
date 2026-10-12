"""Operator auth — API keys with roles.

Drivers use the public endpoints (status, booking, chat) with no key.
Lot operations (view all bookings, cancel, simulate, alerts) need an
operator key sent as `X-API-Key`. Keys are stored as SHA-256 hashes;
raw keys exist only in the operator's hands and in server env at seed time.

Roles: owner (everything) > attendant (bookings + alerts, no simulate).
"""

import hashlib
import secrets
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

import parking_backend.database as db
from parking_backend.database import get_connection

ROLE_RANK = {"attendant": 1, "owner": 2}

api_key_header: Optional[str] = None

try:
    _header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def _get_key(key: Optional[str] = Depends(_header_scheme)) -> Optional[str]:
        return key
except Exception:  # pragma: no cover - import-time safety
    async def _get_key() -> Optional[str]:  # type: ignore[misc]
        return None


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_operator(name: str, role: str = "attendant") -> str:
    """Create an operator, return the raw key ONCE (it is never stored)."""
    if role not in ROLE_RANK:
        raise ValueError(f"Unknown role {role!r}.")
    raw = f"pkx_{secrets.token_urlsafe(24)}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO operators(name, role, key_hash, active) VALUES(?,?,?,1)",
            (name, role, hash_key(raw)),
        )
    return raw


def lookup_role(raw_key: str) -> Optional[str]:
    if not raw_key:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT role FROM operators WHERE key_hash = ? AND active = 1",
            (hash_key(raw_key),),
        ).fetchone()
        return row["role"] if row else None


def seed_admin_from_env() -> Optional[str]:
    """Create the owner account from ADMIN_API_KEY once. Returns the key
    only if it was just created ( printed at boot, never again)."""
    import os

    raw = os.getenv("ADMIN_API_KEY", "")
    if not raw:
        return None
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM operators WHERE name = 'admin'"
        ).fetchone()
        if exists:
            return None
        conn.execute(
            "INSERT INTO operators(name, role, key_hash, active) VALUES(?,?,?,1)",
            ("admin", "owner", hash_key(raw)),
        )
        print("[AUTH] Seeded owner 'admin' from ADMIN_API_KEY.")
        return raw


def _require(min_role: str):
    async def guard(key: Optional[str] = Depends(_get_key)) -> str:
        role = lookup_role(key or "")
        if role is None:
            raise HTTPException(401, "Missing or invalid X-API-Key.")
        if ROLE_RANK.get(role, 0) < ROLE_RANK[min_role]:
            raise HTTPException(403, f"Requires {min_role} role.")
        return role

    return guard


require_owner = _require("owner")
require_attendant = _require("attendant")
