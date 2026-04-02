from __future__ import annotations

import httpx

from sre_agent.config import get_settings


def _base_url() -> str:
    return get_settings().flink_jobmanager_url.rstrip("/")


async def list_flink_jobs(status: str | None = None) -> dict:
    """List Flink jobs on the cluster, optionally filtered by status.

    Args:
        status: Optional filter — RUNNING | FAILED | CANCELED | FINISHED.
                If omitted, all jobs are returned.

    Returns:
        dict with key 'jobs' — list of {id, name, state, start-time, duration}.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_base_url()}/jobs/overview", timeout=10)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])

    if status:
        jobs = [j for j in jobs if j.get("state", "").upper() == status.upper()]

    return {"jobs": jobs, "count": len(jobs)}


async def get_flink_job_details(job_id: str) -> dict:
    """Get full details for a Flink job including vertex status and durations.

    Args:
        job_id: Flink job ID (hex string).

    Returns:
        dict with job details: jid, name, state, start-time, end-time,
        vertices (list), plan.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_base_url()}/jobs/{job_id}", timeout=10)
        resp.raise_for_status()
        return resp.json()


async def get_flink_job_exceptions(job_id: str, max_exceptions: int = 20) -> dict:
    """Get recent exceptions and stack traces for a Flink job.

    Args:
        job_id: Flink job ID.
        max_exceptions: Maximum number of exceptions to return.

    Returns:
        dict with keys: root-exception, all-exceptions (list of {exception,
        timestamp, taskName, location}).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/jobs/{job_id}/exceptions",
            params={"maxExceptions": max_exceptions},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()


async def get_flink_job_checkpoints(job_id: str) -> dict:
    """Get checkpoint statistics for a Flink job.

    Args:
        job_id: Flink job ID.

    Returns:
        dict with counts (restored, total, in_progress, completed, failed),
        summary (duration, state_size), latest checkpoint details, and
        history (list of recent checkpoints with trigger_timestamp, status,
        end_to_end_duration, state_size, failure reason).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/jobs/{job_id}/checkpoints",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()


async def get_flink_job_metrics(job_id: str, metric_names: str) -> dict:
    """Get job-level metrics for a Flink job.

    Args:
        job_id: Flink job ID.
        metric_names: Comma-separated metric names, e.g.
            'numRecordsInPerSecond,numRecordsOutPerSecond,lastCheckpointDuration,
             numberOfFailedCheckpoints,uptime'.

    Returns:
        dict with 'metrics' list of {id, value}.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/jobs/{job_id}/metrics",
            params={"get": metric_names},
            timeout=10,
        )
        resp.raise_for_status()
        return {"job_id": job_id, "metrics": resp.json()}


async def list_flink_taskmanagers() -> dict:
    """List all TaskManagers connected to the Flink cluster.

    Returns:
        dict with 'taskmanagers' list containing id, path, dataPort,
        jmxPort, timeSinceLastHeartbeat, slotsNumber, freeSlots, hardware.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_base_url()}/taskmanagers", timeout=10)
        resp.raise_for_status()
        return resp.json()


async def get_flink_taskmanager_logs(taskmanager_id: str) -> dict:
    """Get recent log entries for a specific Flink TaskManager.

    Args:
        taskmanager_id: TaskManager ID string.

    Returns:
        dict with 'logs' list of {name, size} (available log files) and
        'taskmanager_id'.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base_url()}/taskmanagers/{taskmanager_id}/logs",
            timeout=10,
        )
        resp.raise_for_status()
        return {"taskmanager_id": taskmanager_id, "logs": resp.json().get("logs", [])}
