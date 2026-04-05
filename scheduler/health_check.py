from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sre_agent.config import get_settings
from sre_agent.schemas.alert import AlertSource, NormalizedAlert
from sre_agent.tools.databricks import search_databricks_failed_runs
from sre_agent.tools.flink import list_flink_jobs

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _check_flink_health() -> list[NormalizedAlert]:
    """Check for Flink jobs that have entered FAILED state since last check."""
    alerts: list[NormalizedAlert] = []
    try:
        result = await list_flink_jobs(status="FAILED")
        for job in result.get("jobs", []):
            job_name = job.get("name", "unknown")
            alerts.append(
                NormalizedAlert(
                    alert_id=f"proactive-flink-{job.get('id', uuid.uuid4())}",
                    source=AlertSource.MANUAL,
                    title=f"[Proactive] Flink job FAILED: {job_name}",
                    body=(
                        f"Proactive health check detected Flink job '{job_name}' "
                        f"in FAILED state. Job ID: {job.get('id')}. "
                        f"Start time: {job.get('start-time')}."
                    ),
                    severity="high",
                    affected_service="flink",
                    affected_job_name=job_name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tags={"source": "proactive_health_check", "component": "flink"},
                )
            )
    except Exception:
        logger.exception("Proactive Flink health check failed")
    return alerts


async def _check_databricks_health() -> list[NormalizedAlert]:
    """Check for Databricks job failures in the past health_check_interval window."""
    alerts: list[NormalizedAlert] = []
    s = get_settings()
    try:
        lookback = s.health_check_interval_minutes + 2  # slight overlap to avoid gaps
        result = await search_databricks_failed_runs(lookback_minutes=lookback)
        for run in result.get("failed_runs", []):
            job_name = run.get("run_name", f"job-{run.get('job_id')}")
            alerts.append(
                NormalizedAlert(
                    alert_id=f"proactive-dbx-{run.get('run_id', uuid.uuid4())}",
                    source=AlertSource.MANUAL,
                    title=f"[Proactive] Databricks run FAILED: {job_name}",
                    body=(
                        f"Proactive health check detected Databricks run failure. "
                        f"Job: {job_name} | Run ID: {run.get('run_id')} | "
                        f"State: {run.get('result_state')} | "
                        f"Error: {run.get('state_message', 'unknown')}"
                    ),
                    severity="high",
                    affected_service="databricks",
                    affected_job_name=job_name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tags={"source": "proactive_health_check", "component": "databricks"},
                )
            )
    except Exception:
        logger.exception("Proactive Databricks health check failed")
    return alerts


async def run_health_check() -> None:
    """Run a full proactive platform health check.

    Called on a schedule (every N minutes). Checks Flink and Databricks for
    silent failures that may not have triggered Datadog/PagerDuty alerts.
    Sends any detected issues to the SRE agent for investigation.
    """
    logger.info("Running proactive platform health check")

    # Import here to avoid circular imports at module load time
    from sre_agent.dedup.dedup import is_duplicate
    from webhook.runner import invoke_sre_agent

    flink_alerts, databricks_alerts = await asyncio.gather(
        _check_flink_health(),
        _check_databricks_health(),
        return_exceptions=True,
    )

    all_alerts: list[NormalizedAlert] = []
    if isinstance(flink_alerts, list):
        all_alerts.extend(flink_alerts)
    if isinstance(databricks_alerts, list):
        all_alerts.extend(databricks_alerts)

    for alert in all_alerts:
        # Deduplicate to avoid re-investigating the same failure every 5 minutes
        if await is_duplicate(alert):
            logger.debug("Proactive alert suppressed (duplicate): %s", alert.title)
            continue

        logger.info("Proactive alert dispatched: %s [%s]", alert.title, alert.severity)
        asyncio.create_task(invoke_sre_agent(alert))

    if not all_alerts:
        logger.debug("Proactive health check: platform healthy — no issues found")


def start_scheduler() -> AsyncIOScheduler:
    """Start the APScheduler background scheduler for proactive health checks.

    Returns the scheduler instance so it can be shut down cleanly on app exit.
    """
    global _scheduler
    s = get_settings()

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_health_check,
        trigger=IntervalTrigger(minutes=s.health_check_interval_minutes),
        id="platform_health_check",
        name="Platform Health Check",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    logger.info(
        "Proactive health check scheduler started (interval: %dm)",
        s.health_check_interval_minutes,
    )
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Health check scheduler stopped")
