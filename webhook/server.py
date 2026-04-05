from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Header, HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app

from sre_agent.config import get_settings
from sre_agent.dedup.dedup import is_duplicate
from sre_agent.telemetry.tracing import setup_tracing
from webhook.normalizer import (
    normalize_cloudwatch,
    normalize_datadog,
    normalize_manual,
    normalize_pagerduty,
)
from webhook.runner import invoke_sre_agent

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):  # type: ignore[type-arg]
    """Startup: initialise OTEL tracing + proactive health check scheduler.
    Shutdown: gracefully stop the scheduler."""
    s = get_settings()

    if s.otel_enabled:
        setup_tracing(service_name="sre-agent", otlp_endpoint=s.otlp_endpoint)
        logger.info("OpenTelemetry tracing enabled → %s", s.otlp_endpoint)

    scheduler = None
    if s.health_check_enabled:
        from scheduler.health_check import start_scheduler
        scheduler = start_scheduler()

    yield

    if scheduler:
        from scheduler.health_check import stop_scheduler
        stop_scheduler()


# ADK's get_fast_api_app provides /run, /run_sse, /list-apps, and the Dev UI (/dev-ui).
# session_service_uri wires it to PostgreSQL via DatabaseSessionService.
app = get_fast_api_app(
    agents_dir=Path(__file__).parent.parent / "sre_agent",
    session_service_uri=get_settings().database_url,
    allow_origins=["*"],
    web=True,
)
app.router.lifespan_context = lifespan


def _verify_hmac(body: bytes, signature: str | None, secret: str) -> None:
    if not secret or not signature:
        return
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@app.get("/health")
async def health() -> dict:
    """Liveness + readiness health check."""
    return {"status": "ok", "agent": "sre_orchestrator"}


@app.post("/webhook/datadog", status_code=202)
async def datadog_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_datadog_signature: str | None = Header(default=None),
) -> dict:
    """Receive Datadog monitor webhook → deduplicate → SRE investigation."""
    body = await request.body()
    _verify_hmac(body, x_datadog_signature, get_settings().webhook_secret)
    alert = normalize_datadog(await request.json())
    if await is_duplicate(alert):
        return {"accepted": False, "reason": "duplicate", "alert_id": alert.alert_id}
    logger.info("Datadog webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)
    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/cloudwatch", status_code=202)
async def cloudwatch_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive CloudWatch SNS alarm → deduplicate → SRE investigation."""
    payload = await request.json()
    if payload.get("Type") == "SubscriptionConfirmation":
        return {"accepted": True, "type": "confirmation"}
    alert = normalize_cloudwatch(payload)
    if await is_duplicate(alert):
        return {"accepted": False, "reason": "duplicate", "alert_id": alert.alert_id}
    logger.info("CloudWatch webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)
    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/pagerduty", status_code=202)
async def pagerduty_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive PagerDuty v3 webhook → deduplicate → SRE investigation."""
    alert = normalize_pagerduty(await request.json())
    if await is_duplicate(alert):
        return {"accepted": False, "reason": "duplicate", "alert_id": alert.alert_id}
    logger.info("PagerDuty webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)
    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/manual", status_code=202)
async def manual_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Free-form test alert. No dedup applied.

    Example:
        curl -X POST http://localhost:8000/webhook/manual \\
          -H 'Content-Type: application/json' \\
          -d '{
            "title": "Flink job kafka-flink-orders restarting",
            "severity": "critical",
            "affected_job_name": "kafka-flink-orders",
            "affected_namespace": "flink-prod",
            "body": "5 restarts in 10min. Deploy at 14:15 UTC.",
            "tags": {"env": "prod"}
          }'
    """
    alert = normalize_manual(await request.json())
    logger.info("Manual alert: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)
    return {"accepted": True, "alert_id": alert.alert_id}
