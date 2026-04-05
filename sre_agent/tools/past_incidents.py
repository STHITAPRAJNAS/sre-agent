from __future__ import annotations

import logging

from sre_agent.config import get_settings
from sre_agent.memory.embeddings import embed

logger = logging.getLogger(__name__)


async def search_past_incidents(
    query: str,
    component: str | None = None,
    top_k: int = 3,
) -> dict:
    """Search past incident RCA reports for similar historical issues.

    Uses semantic similarity search over the pgvector incident memory store.
    Call this early in investigation to check if this pattern has been seen before —
    past RCAs may contain the exact root cause and fix.

    Args:
        query: Description of the current issue to search against past incidents.
            Examples:
              - 'Flink job kafka-orders checkpoint failing OOM'
              - 'Databricks ETL job failed FileNotFoundException'
              - 'EKS pods CrashLoopBackOff flink namespace'
        component: Optional filter: flink | databricks | eks | api | kafka
        top_k: Max number of past incidents to return (default 3).

    Returns:
        dict with 'past_incidents' list. Each entry has:
          - alert_title: Original alert title
          - component: Affected component
          - severity: Incident severity
          - root_cause: Root cause identified at the time
          - summary: Full RCA summary excerpt (500 chars)
          - similarity: Relevance score (0.0 - 1.0)
          - date: When this incident occurred
    """
    try:
        import asyncpg
        from pgvector.asyncpg import register_vector

        s = get_settings()
        query_embedding = await embed(query)

        async def _init(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        conn = await asyncpg.connect(dsn=s.database_url, init=_init)
        try:
            sql = """
                SELECT alert_title, component, severity, root_cause,
                       summary, created_at,
                       1 - (embedding <=> $1) AS similarity
                FROM   incident_memory
                WHERE  embedding IS NOT NULL
                  AND  1 - (embedding <=> $1) > 0.65
            """
            params: list = [query_embedding]

            if component:
                sql += " AND component = $2 ORDER BY embedding <=> $1 LIMIT $3"
                params += [component, top_k]
            else:
                sql += " ORDER BY embedding <=> $1 LIMIT $2"
                params.append(top_k)

            rows = await conn.fetch(sql, *params)
        finally:
            await conn.close()

        incidents = [
            {
                "alert_title": row["alert_title"] or "Unknown",
                "component": row["component"] or "unknown",
                "severity": row["severity"] or "unknown",
                "root_cause": row["root_cause"] or "Not recorded",
                "summary": (row["summary"] or "")[:500],
                "similarity": round(float(row["similarity"]), 3),
                "date": row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else "unknown",
            }
            for row in rows
        ]
        return {
            "past_incidents": incidents,
            "count": len(incidents),
            "note": "No similar past incidents found." if not incidents else None,
        }

    except Exception:
        logger.exception("Past incident search failed for query: %s", query[:100])
        return {"past_incidents": [], "count": 0, "error": "Memory search unavailable"}
