from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import TYPE_CHECKING

import asyncpg

from sre_agent.config import get_settings

if TYPE_CHECKING:
    from sre_agent.schemas.alert import NormalizedAlert

logger = logging.getLogger(__name__)

# In-process fallback cache (used when DB is unreachable)
_local_cache: dict[str, float] = {}
_cache_lock = asyncio.Lock()

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=get_settings().database_url, min_size=1, max_size=3)
    return _pool


def _make_key(alert: "NormalizedAlert") -> str:
    """Build a deterministic dedup key for an alert.

    Combines source, affected_job_name (or normalized title), and severity
    so that the same logical alert firing repeatedly maps to the same key.
    """
    title_slug = (alert.affected_job_name or alert.title).lower()[:120]
    raw = f"{alert.source.value}:{title_slug}:{alert.severity}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


async def is_duplicate(alert: "NormalizedAlert") -> bool:
    """Check whether this alert is a duplicate within the dedup TTL window.

    Uses PostgreSQL as the primary store so the window is shared across
    all webhook server instances. Falls back to an in-process dict if the
    DB is unreachable (avoids blocking alert processing on DB outage).

    Side effect: records/updates the alert in the dedup table if it is NOT
    a duplicate. Increments the counter if it IS a duplicate.

    Args:
        alert: Normalized alert to check.

    Returns:
        True  → duplicate, suppress this alert (already being investigated).
        False → new alert, proceed with investigation.
    """
    s = get_settings()
    ttl_seconds = s.alert_dedup_ttl_minutes * 60
    key = _make_key(alert)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_seen, suppressed FROM alert_dedup WHERE dedup_key = $1",
                key,
            )

            if row:
                age = time.time() - row["last_seen"].timestamp()
                if age < ttl_seconds:
                    # Within TTL — this is a duplicate; increment counter
                    await conn.execute(
                        """
                        UPDATE alert_dedup
                        SET    last_seen = NOW(), count = count + 1, suppressed = true
                        WHERE  dedup_key = $1
                        """,
                        key,
                    )
                    logger.info(
                        "Alert suppressed (duplicate within %dm window): %s",
                        s.alert_dedup_ttl_minutes,
                        alert.title,
                    )
                    return True
                else:
                    # TTL expired — treat as new alert, reset window
                    await conn.execute(
                        """
                        UPDATE alert_dedup
                        SET    alert_id = $2, alert_title = $3, first_seen = NOW(),
                               last_seen = NOW(), count = 1, suppressed = false
                        WHERE  dedup_key = $1
                        """,
                        key,
                        alert.alert_id,
                        alert.title,
                    )
                    return False
            else:
                # New alert — insert and proceed
                await conn.execute(
                    """
                    INSERT INTO alert_dedup (dedup_key, alert_id, alert_title)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (dedup_key) DO NOTHING
                    """,
                    key,
                    alert.alert_id,
                    alert.title,
                )
                return False

    except Exception:
        logger.warning("DB dedup unavailable, using in-process cache", exc_info=True)
        return await _local_is_duplicate(key, ttl_seconds)


async def _local_is_duplicate(key: str, ttl_seconds: float) -> bool:
    """In-process fallback dedup using a dict with TTL."""
    async with _cache_lock:
        now = time.time()
        if key in _local_cache and now - _local_cache[key] < ttl_seconds:
            return True
        _local_cache[key] = now
        # Prune expired entries
        expired = [k for k, t in _local_cache.items() if now - t >= ttl_seconds]
        for k in expired:
            del _local_cache[k]
        return False


async def clear_dedup_window(alert: "NormalizedAlert") -> None:
    """Manually clear the dedup window for an alert (e.g. after resolution).

    Allows the same alert to be re-investigated immediately without waiting
    for TTL expiry.
    """
    key = _make_key(alert)
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM alert_dedup WHERE dedup_key = $1", key)
    except Exception:
        logger.warning("Could not clear dedup window for %s", alert.alert_id)
    async with _cache_lock:
        _local_cache.pop(key, None)
