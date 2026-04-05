from __future__ import annotations

import json

from sre_agent.knowledge.runbook_store import search_runbooks


async def search_runbook(
    error_description: str,
    component: str | None = None,
    top_k: int = 3,
) -> dict:
    """Search the platform runbook knowledge base for relevant investigation steps.

    The runbook knowledge base is stored in PostgreSQL + pgvector. Each runbook
    contains known error patterns, investigation steps, and escalation guidance
    for common data platform failures (Flink, Databricks, EKS, Kafka, APIs).

    Call this FIRST at the start of any investigation — it surfaces known patterns
    before querying external systems, making investigations faster and cheaper.

    Args:
        error_description: Error message, symptom, or alert description to search for.
            Examples:
              - 'Flink checkpoint timeout NullPointerException'
              - 'TaskManager OOMKilled CrashLoopBackOff'
              - 'Databricks cluster terminated spot instance'
        component: Optional filter to restrict results to one component.
            Values: flink | databricks | eks | api | kafka
        top_k: Number of runbooks to return (default 3, max 5).

    Returns:
        dict with 'runbooks' list. Each runbook has:
          - title: Short runbook name
          - component: Affected component
          - description: Problem summary
          - steps: Ordered list of investigation/escalation steps
          - similarity: Relevance score (0-1)
    """
    results = await search_runbooks(
        error_description=error_description,
        component=component,
        top_k=min(top_k, 5),
    )
    return {
        "runbooks": results,
        "count": len(results),
        "note": "No matching runbooks found — this may be a novel issue." if not results else None,
    }
