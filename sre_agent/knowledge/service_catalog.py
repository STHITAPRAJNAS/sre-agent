from __future__ import annotations

import logging

import asyncpg

from sre_agent.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=get_settings().database_url, min_size=1, max_size=5)
    return _pool


async def lookup_service(service_name: str) -> dict | None:
    """Look up a service or job in the service catalog.

    Supports partial/fuzzy matching: looks for exact match first, then ILIKE prefix,
    then ILIKE substring.

    Args:
        service_name: Service, job, or namespace name to look up.

    Returns:
        Service catalog entry dict, or None if not found.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Try exact match first
            row = await conn.fetchrow(
                "SELECT * FROM service_catalog WHERE service_name = $1", service_name
            )
            if not row:
                # Try prefix match
                row = await conn.fetchrow(
                    "SELECT * FROM service_catalog WHERE service_name ILIKE $1",
                    f"{service_name}%",
                )
            if not row:
                # Try substring match
                row = await conn.fetchrow(
                    "SELECT * FROM service_catalog WHERE service_name ILIKE $1 OR display_name ILIKE $1",
                    f"%{service_name}%",
                )
        if row:
            return dict(row)
        return None
    except Exception:
        logger.exception("Service catalog lookup failed for: %s", service_name)
        return None


async def list_services_by_namespace(namespace: str) -> list[dict]:
    """List all services running in a given EKS namespace.

    Args:
        namespace: Kubernetes namespace, e.g. 'flink-prod'.

    Returns:
        List of service catalog entries.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM service_catalog WHERE eks_namespace = $1 ORDER BY service_name",
                namespace,
            )
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Service catalog namespace lookup failed for: %s", namespace)
        return []
