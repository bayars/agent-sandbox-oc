import asyncpg
import asyncio
import time
from typing import Optional
from server.config import DATABASE_URL

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool


async def init_db(retries: int = 10, delay: float = 3.0) -> None:
    for attempt in range(retries):
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id          TEXT PRIMARY KEY,
                        namespace   TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'creating',
                        oc_session  TEXT,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
            return
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[db] Waiting for PostgreSQL ({exc}), retry {attempt + 1}/{retries}...")
            await asyncio.sleep(delay)


async def create_session(session_id: str, namespace: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sessions (id, namespace, status)
            VALUES ($1, $2, 'creating')
            RETURNING id, namespace, status, oc_session,
                      created_at::text, updated_at::text
            """,
            session_id, namespace,
        )
    return dict(row)


async def get_session(session_id: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, namespace, status, oc_session,
                   created_at::text, updated_at::text
            FROM sessions WHERE id = $1
            """,
            session_id,
        )
    return dict(row) if row else None


async def list_sessions() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, namespace, status, oc_session,
                   created_at::text, updated_at::text
            FROM sessions
            WHERE status != 'deleted'
            ORDER BY created_at DESC
            """
        )
    return [dict(r) for r in rows]


async def update_session(session_id: str, **kwargs) -> None:
    allowed = {"status", "oc_session"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    pool = await get_pool()
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
    values = list(fields.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE sessions SET {sets}, updated_at = NOW() WHERE id = $1",
            session_id, *values,
        )
