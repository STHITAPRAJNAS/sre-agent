from __future__ import annotations

import httpx

from sre_agent.config import get_settings


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"DD-API-KEY": s.datadog_api_key, "DD-APPLICATION-KEY": s.datadog_app_key}


def _base_url() -> str:
    return f"https://api.{get_settings().datadog_site}"


async def get_datadog_monitor_status(monitor_id: int) -> dict:
    """Get the current state, name, tags, and message for a Datadog monitor.

    Args:
        monitor_id: Numeric ID of the Datadog monitor.

    Returns:
        dict with keys: id, name, type, status, message, tags, created, modified.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/api/v1/monitor/{monitor_id}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def search_datadog_monitors(query: str, page: int = 0, per_page: int = 20) -> dict:
    """Search Datadog monitors by name or tag.

    Args:
        query: Free-text search string, e.g. 'flink' or 'tag:env:prod'.
        page: Page number (0-indexed).
        per_page: Results per page (max 1000).

    Returns:
        dict with keys: monitors (list), metadata (total_count, page).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/api/v1/monitor",
            headers=_headers(),
            params={"query": query, "page": page, "page_size": per_page},
            timeout=15,
        )
        resp.raise_for_status()
        monitors = resp.json()
        return {"monitors": monitors, "metadata": {"count": len(monitors), "page": page}}


async def get_datadog_metric_timeseries(
    metric_query: str, from_ts: int, to_ts: int
) -> dict:
    """Query a Datadog metrics timeseries.

    Args:
        metric_query: Datadog query string, e.g.
            'avg:flink.job.uptime{job_name:kafka-flink-orders}'.
        from_ts: Start time as Unix epoch seconds.
        to_ts: End time as Unix epoch seconds.

    Returns:
        dict with keys: series (list of {metric, pointlist, scope}).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/api/v1/query",
            headers=_headers(),
            params={"query": metric_query, "from": from_ts, "to": to_ts},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()


async def get_datadog_logs(
    query: str,
    from_ts: str,
    to_ts: str,
    limit: int = 50,
) -> dict:
    """Search Datadog Logs.

    Args:
        query: Datadog log search query, e.g. 'service:flink-orders status:error'.
        from_ts: Start time in ISO8601, e.g. '2024-01-15T14:00:00Z'.
        to_ts: End time in ISO8601.
        limit: Maximum number of log events to return (max 1000).

    Returns:
        dict with keys: data (list of log events), meta.
    """
    payload = {
        "filter": {"query": query, "from": from_ts, "to": to_ts},
        "sort": "timestamp",
        "page": {"limit": limit},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_base_url()}/api/v2/logs/events/search",
            headers={**_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()


async def get_datadog_active_incidents() -> dict:
    """List all open or stable Datadog incidents on the platform.

    Returns:
        dict with key 'data' containing a list of incidents with id, title,
        severity, status, created_at, and customer_impact_scope.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/api/v2/incidents",
            headers=_headers(),
            params={"filter[status]": "active,stable"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
