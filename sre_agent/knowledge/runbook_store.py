from __future__ import annotations

import json
import logging

import asyncpg
from pgvector.asyncpg import register_vector

from sre_agent.config import get_settings
from sre_agent.memory.embeddings import embed

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        s = get_settings()

        async def _init_conn(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        _pool = await asyncpg.create_pool(dsn=s.database_url, min_size=1, max_size=5, init=_init_conn)
    return _pool


async def search_runbooks(
    error_description: str,
    component: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """Search runbook knowledge base using semantic similarity.

    Embeds the error description and performs cosine similarity search over
    the pgvector-indexed runbook table. Returns the most relevant runbooks
    with investigation steps.

    Args:
        error_description: Error message, stack trace fragment, or symptom description.
        component: Optional component filter (flink|databricks|eks|api|kafka).
        top_k: Number of runbooks to return.

    Returns:
        List of runbook dicts with title, component, description, steps, similarity.
    """
    try:
        query_embedding = await embed(error_description)
        pool = await _get_pool()

        query = """
            SELECT title, component, description, steps, tags,
                   1 - (embedding <=> $1) AS similarity
            FROM   runbooks
            WHERE  embedding IS NOT NULL
              AND  1 - (embedding <=> $1) > 0.60
        """
        params: list = [query_embedding]

        if component:
            query += " AND component = $2"
            params.append(component)
            query += " ORDER BY embedding <=> $1 LIMIT $3"
            params.append(top_k)
        else:
            query += " ORDER BY embedding <=> $1 LIMIT $2"
            params.append(top_k)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            {
                "title": row["title"],
                "component": row["component"],
                "description": row["description"],
                "steps": json.loads(row["steps"]) if isinstance(row["steps"], str) else row["steps"],
                "tags": list(row["tags"] or []),
                "similarity": round(float(row["similarity"]), 3),
            }
            for row in rows
        ]
    except Exception:
        logger.exception("Runbook search failed for query: %s", error_description[:100])
        return []
