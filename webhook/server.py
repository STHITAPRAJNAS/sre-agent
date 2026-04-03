from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

from fastapi import BackgroundTasks, Header, HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app

from sre_agent.config import get_settings
from webhook.normalizer import (
    normalize_cloudwatch,
    normalize_datadog,
    normalize_manual,
    normalize_pagerduty,
)
from webhook.runner import invoke_sre_agent

logger = logging.getLogger(__name__)

# Build the FastAPI app using ADK's wrapper — provides /run, /run_sse,
# /list-apps, and the ADK dev UI at /dev-ui out of the box.
app = get_fast_api_app(
    agents_dir=Path(__file__).parent.parent / "sre_agent",
    session_service_uri=None,   # in-memory; swap for e.g. "sqlite:///sre.db" in prod
    allow_origins=["*"],
    web=True,
)


def _verify_hmac(body: bytes, signature: str | None, secret: str) -> None:
    """Verify HMAC-SHA256 webhook signature if secret is configured."""
    if not secret or not signature:
        return
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "agent": "sre_orchestrator"}


@app.post("/webhook/datadog", status_code=202)
async def datadog_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_datadog_signature: str | None = Header(default=None),
) -> dict:
    """Receive a Datadog monitor webhook and trigger SRE investigation."""
    body = await request.body()
    _verify_hmac(body, x_datadog_signature, get_settings().webhook_secret)

    payload = await request.json()
    alert = normalize_datadog(payload)

    logger.info("Received Datadog webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)

    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/cloudwatch", status_code=202)
async def cloudwatch_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive a CloudWatch alarm SNS notification and trigger SRE investigation."""
    payload = await request.json()

    # SNS sends a SubscriptionConfirmation on setup — auto-confirm it
    if payload.get("Type") == "SubscriptionConfirmation":
        logger.info("SNS subscription confirmation received")
        return {"accepted": True, "type": "confirmation"}

    alert = normalize_cloudwatch(payload)
    logger.info("Received CloudWatch webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)

    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/pagerduty", status_code=202)
async def pagerduty_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive a PagerDuty v3 webhook event and trigger SRE investigation."""
    payload = await request.json()
    alert = normalize_pagerduty(payload)

    logger.info("Received PagerDuty webhook: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)

    return {"accepted": True, "alert_id": alert.alert_id}


@app.post("/webhook/manual", status_code=202)
async def manual_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Accept a free-form alert payload for testing and ad-hoc investigations.

    Example payload:
        {
          "title": "Flink job kafka-flink-orders restarting",
          "severity": "critical",
          "affected_job_name": "kafka-flink-orders",
          "affected_namespace": "flink-prod",
          "body": "Job has restarted 5 times in 10 minutes. Suspect recent deploy.",
          "tags": {"env": "prod", "team": "data-platform"}
        }
    """
    payload = await request.json()
    alert = normalize_manual(payload)

    logger.info("Received manual alert: %s [%s]", alert.title, alert.severity)
    background_tasks.add_task(invoke_sre_agent, alert)

    return {"accepted": True, "alert_id": alert.alert_id}
