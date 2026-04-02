from __future__ import annotations

import time

import httpx

from sre_agent.config import get_settings


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=f"https://{s.databricks_host}",
        headers={"Authorization": f"Bearer {s.databricks_token}"},
        timeout=20,
    )


async def list_databricks_job_runs(
    job_id: int | None = None,
    limit: int = 25,
    active_only: bool = False,
    completed_only: bool = False,
) -> dict:
    """List recent Databricks job runs.

    Args:
        job_id: Optional job ID to filter. If omitted, all jobs are returned.
        limit: Max number of runs (default 25, max 100).
        active_only: Return only active/running jobs.
        completed_only: Return only completed jobs.

    Returns:
        dict with 'runs' list of {run_id, job_id, run_name, state,
        start_time, end_time, run_duration, error_message}.
    """
    params: dict = {"limit": min(limit, 100)}
    if job_id is not None:
        params["job_id"] = job_id
    if active_only:
        params["active_only"] = "true"
    if completed_only:
        params["completed_only"] = "true"

    async with _client() as client:
        resp = await client.get("/api/2.1/jobs/runs/list", params=params)
        resp.raise_for_status()
        data = resp.json()

    runs = []
    for r in data.get("runs", []):
        state = r.get("state", {})
        runs.append(
            {
                "run_id": r.get("run_id"),
                "job_id": r.get("job_id"),
                "run_name": r.get("run_name", ""),
                "life_cycle_state": state.get("life_cycle_state"),
                "result_state": state.get("result_state"),
                "state_message": state.get("state_message", ""),
                "start_time_ms": r.get("start_time"),
                "end_time_ms": r.get("end_time"),
                "run_duration_ms": r.get("run_duration"),
            }
        )
    return {"runs": runs, "has_more": data.get("has_more", False)}


async def get_databricks_run_output(run_id: int) -> dict:
    """Get the full output, logs URL, and error for a completed Databricks run.

    Args:
        run_id: Databricks run ID.

    Returns:
        dict with run details, notebook_output, error, error_trace,
        and metadata.run_page_url.
    """
    async with _client() as client:
        resp = await client.get("/api/2.1/jobs/runs/get-output", params={"run_id": run_id})
        resp.raise_for_status()
        return resp.json()


async def get_databricks_cluster_info(cluster_id: str) -> dict:
    """Get the current state and configuration of a Databricks cluster.

    Args:
        cluster_id: Databricks cluster ID.

    Returns:
        dict with cluster_id, cluster_name, state, state_message,
        spark_version, node_type_id, autoscale, num_workers,
        last_restarted_time, last_activity_time.
    """
    async with _client() as client:
        resp = await client.get("/api/2.0/clusters/get", params={"cluster_id": cluster_id})
        resp.raise_for_status()
        data = resp.json()

    return {
        "cluster_id": data.get("cluster_id"),
        "cluster_name": data.get("cluster_name"),
        "state": data.get("state"),
        "state_message": data.get("state_message", ""),
        "spark_version": data.get("spark_version"),
        "node_type_id": data.get("node_type_id"),
        "autoscale": data.get("autoscale"),
        "num_workers": data.get("num_workers"),
        "last_restarted_time": data.get("last_restarted_time"),
        "last_activity_time": data.get("last_activity_time"),
        "cluster_memory_mb": data.get("cluster_memory_mb"),
        "cluster_cores": data.get("cluster_cores"),
    }


async def list_databricks_clusters() -> dict:
    """List all Databricks clusters with their current state and metadata.

    Returns:
        dict with 'clusters' list of {cluster_id, cluster_name, state,
        spark_version, creator_user_name, cluster_source}.
    """
    async with _client() as client:
        resp = await client.get("/api/2.0/clusters/list")
        resp.raise_for_status()
        data = resp.json()

    clusters = [
        {
            "cluster_id": c.get("cluster_id"),
            "cluster_name": c.get("cluster_name"),
            "state": c.get("state"),
            "state_message": c.get("state_message", ""),
            "spark_version": c.get("spark_version"),
            "creator_user_name": c.get("creator_user_name", ""),
            "cluster_source": c.get("cluster_source", ""),
        }
        for c in data.get("clusters", [])
    ]
    return {"clusters": clusters, "count": len(clusters)}


async def search_databricks_failed_runs(lookback_minutes: int = 60) -> dict:
    """Find all failed Databricks job runs in the last N minutes across all jobs.

    Args:
        lookback_minutes: How far back to look (default 60 minutes).

    Returns:
        dict with 'failed_runs' list of {run_id, job_id, run_name,
        result_state, state_message, start_time_ms, run_duration_ms}.
    """
    cutoff_ms = int((time.time() - lookback_minutes * 60) * 1000)

    async with _client() as client:
        resp = await client.get(
            "/api/2.1/jobs/runs/list",
            params={"completed_only": "true", "limit": 100},
        )
        resp.raise_for_status()
        data = resp.json()

    failed = []
    for r in data.get("runs", []):
        state = r.get("state", {})
        start_time = r.get("start_time", 0)
        if (
            state.get("result_state") in ("FAILED", "TIMEDOUT", "CANCELED")
            and start_time >= cutoff_ms
        ):
            failed.append(
                {
                    "run_id": r.get("run_id"),
                    "job_id": r.get("job_id"),
                    "run_name": r.get("run_name", ""),
                    "result_state": state.get("result_state"),
                    "state_message": state.get("state_message", ""),
                    "start_time_ms": start_time,
                    "run_duration_ms": r.get("run_duration"),
                }
            )

    return {"failed_runs": failed, "count": len(failed), "lookback_minutes": lookback_minutes}
