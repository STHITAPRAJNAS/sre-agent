from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.sessions.base_session_service import GetSessionConfig
from google.genai import types as genai_types

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

        _pool = await asyncpg.create_pool(
            dsn=s.database_url,
            min_size=2,
            max_size=10,
            init=_init_conn,
        )
    return _pool


def _extract_session_summary(session: Any) -> dict[str, str] | None:
    """Extract a meaningful summary from an ADK session's event history.

    Looks for the final text response (RCA report) from the reporting agent
    and key alert metadata stored in session state.
    """
    # Try to get summary from session state (set by reporting_agent via output_key)
    state: dict = getattr(session, "state", {}) or {}
    summary = state.get("rca_summary") or state.get("final_report")

    # Fall back to last agent text in events
    if not summary:
        events = getattr(session, "events", []) or []
        for event in reversed(events):
            content = getattr(event, "content", None)
            if content:
                parts = getattr(content, "parts", []) or []
                for part in parts:
                    text = getattr(part, "text", None)
                    if text and len(text) > 100:
                        summary = text[:2000]
                        break
            if summary:
                break

    if not summary:
        return None

    return {
        "summary": summary,
        "alert_id": state.get("alert_id", ""),
        "alert_title": state.get("alert_title", ""),
        "root_cause": state.get("root_cause", ""),
        "component": state.get("primary_component", ""),
        "severity": state.get("severity", ""),
    }


class PgVectorMemoryService(BaseMemoryService):
    """ADK memory service backed by PostgreSQL + pgvector.

    Stores RCA summaries from completed incident sessions as vector embeddings.
    On search, performs cosine similarity search to surface past similar incidents.

    The orchestrator agent can call search_past_incidents() to inject historical
    context: 'Last month, the same Flink job failed after a schema change in PR #312.'
    """

    async def add_session_to_memory(self, session: Any) -> None:
        """Persist a completed session's RCA summary to the vector store.

        Called automatically by the ADK Runner after each completed run.
        Extracts the RCA content, embeds it, and stores with metadata.
        """
        extracted = _extract_session_summary(session)
        if not extracted:
            logger.debug("No meaningful summary in session %s — skipping memory store", session.id)
            return

        try:
            embedding = await embed(extracted["summary"])
            pool = await _get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO incident_memory
                        (app_name, user_id, session_id, alert_id, alert_title,
                         summary, root_cause, component, severity, embedding, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    getattr(session, "app_name", "sre_agent"),
                    getattr(session, "user_id", "system"),
                    session.id,
                    extracted["alert_id"],
                    extracted["alert_title"],
                    extracted["summary"],
                    extracted["root_cause"],
                    extracted["component"],
                    extracted["severity"],
                    embedding,
                    json.dumps({}),
                )
            logger.info(
                "Stored incident memory for session %s (alert: %s)",
                session.id,
                extracted["alert_id"],
            )
        except Exception:
            logger.exception("Failed to store incident memory for session %s", session.id)

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
        config: Any = None,
    ) -> SearchMemoryResponse:
        """Semantic search over past incidents using cosine similarity.

        Args:
            app_name: ADK app name (used for tenant isolation).
            user_id: ADK user ID.
            query: Natural language query, e.g. 'Flink checkpoint timeout kafka-orders'.
            config: Optional MemoryQueryConfig (top_k, etc.).

        Returns:
            SearchMemoryResponse with list of MemoryResult objects.
        """
        top_k = 3
        if config and hasattr(config, "max_results"):
            top_k = config.max_results

        try:
            query_embedding = await embed(query)
            pool = await _get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT alert_title, summary, root_cause, component, severity,
                           created_at,
                           1 - (embedding <=> $1) AS similarity
                    FROM   incident_memory
                    WHERE  app_name = $2
                      AND  embedding IS NOT NULL
                      AND  1 - (embedding <=> $1) > 0.70
                    ORDER  BY embedding <=> $1
                    LIMIT  $3
                    """,
                    query_embedding,
                    app_name,
                    top_k,
                )
        except Exception:
            logger.exception("Failed to search incident memory")
            return SearchMemoryResponse(memories=[])

        memories = []
        for row in rows:
            text = (
                f"Past incident ({row['created_at'].strftime('%Y-%m-%d')}): "
                f"{row['alert_title']} | Component: {row['component']} | "
                f"Severity: {row['severity']} | "
                f"Root cause: {row['root_cause'] or 'unknown'} | "
                f"Summary: {row['summary'][:500]}"
            )
            memories.append(
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=text)],
                )
            )

        return SearchMemoryResponse(memories=memories)
