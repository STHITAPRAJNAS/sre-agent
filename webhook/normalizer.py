from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sre_agent.schemas.alert import AlertSource, NormalizedAlert


def normalize_datadog(payload: dict[str, Any]) -> NormalizedAlert:
    """Normalize a Datadog monitor webhook payload to NormalizedAlert.

    Datadog webhook body fields (when configured in Datadog webhook integration):
      - id, title, msg, alert_type (error|warning|info|success), priority
      - tags (comma-separated string), last_updated
      - scopes, hostname, aggreg_key
    """
    tags_raw: str = payload.get("tags", "")
    tags: dict[str, str] = {}
    for tag in tags_raw.split(","):
        tag = tag.strip()
        if ":" in tag:
            k, v = tag.split(":", 1)
            tags[k.strip()] = v.strip()
        elif tag:
            tags[tag] = "true"

    alert_type = payload.get("alert_type", "error").lower()
    severity_map = {"error": "high", "warning": "medium", "info": "low", "success": "low"}
    severity = severity_map.get(alert_type, "medium")
    if "critical" in tags_raw.lower() or "p1" in tags_raw.lower():
        severity = "critical"

    return NormalizedAlert(
        alert_id=str(payload.get("id", uuid.uuid4())),
        source=AlertSource.DATADOG,
        title=payload.get("title", "Datadog Alert"),
        body=payload.get("msg", payload.get("body", "")),
        severity=severity,
        affected_service=tags.get("service") or tags.get("env"),
        affected_cluster=tags.get("cluster_name") or tags.get("kube_cluster_name"),
        affected_namespace=tags.get("kube_namespace") or tags.get("namespace"),
        affected_job_name=tags.get("job_name") or tags.get("flink_job_name"),
        timestamp=payload.get("last_updated", _now_iso()),
        tags=tags,
        raw=payload,
    )


def normalize_cloudwatch(payload: dict[str, Any]) -> NormalizedAlert:
    """Normalize a CloudWatch alarm SNS notification to NormalizedAlert.

    CloudWatch → SNS → webhook. The SNS Message field is a JSON string containing
    AlarmName, AlarmDescription, NewStateValue, NewStateReason, StateChangeTime,
    Trigger (Namespace, MetricName, Dimensions).
    """
    message_str = payload.get("Message", "{}")
    try:
        message: dict = json.loads(message_str) if isinstance(message_str, str) else message_str
    except json.JSONDecodeError:
        message = {}

    alarm_name: str = message.get("AlarmName", "CloudWatch Alarm")
    state: str = message.get("NewStateValue", "ALARM")
    reason: str = message.get("NewStateReason", "")
    trigger: dict = message.get("Trigger", {})
    dimensions: list[dict] = trigger.get("Dimensions", [])

    dim_map = {d.get("name", d.get("Name", "")): d.get("value", d.get("Value", ""))
               for d in dimensions}

    severity = "critical" if state == "ALARM" else "low"

    return NormalizedAlert(
        alert_id=str(uuid.uuid4()),
        source=AlertSource.CLOUDWATCH,
        title=alarm_name,
        body=f"{reason} | Trigger: {trigger.get('MetricName', '')} {trigger.get('Namespace', '')}",
        severity=severity,
        affected_service=dim_map.get("ServiceName") or dim_map.get("service"),
        affected_cluster=dim_map.get("ClusterName") or dim_map.get("EKSCluster"),
        affected_namespace=dim_map.get("Namespace") or dim_map.get("namespace"),
        affected_job_name=dim_map.get("JobName") or dim_map.get("job_name"),
        timestamp=message.get("StateChangeTime", _now_iso()),
        tags={**dim_map, "alarm_name": alarm_name, "state": state},
        raw=payload,
    )


def normalize_pagerduty(payload: dict[str, Any]) -> NormalizedAlert:
    """Normalize a PagerDuty v3 webhook event to NormalizedAlert.

    PagerDuty sends an 'event' object with event_type and data.
    Incident data includes title, severity, body, service, assignments.
    """
    events: list[dict] = payload.get("event", {}) if isinstance(payload.get("event"), dict) else {}
    # PagerDuty v3 sends a list of events
    if "events" in payload:
        events = payload["events"][0] if payload["events"] else {}
    else:
        events = payload.get("event", {})

    incident: dict = events.get("data", {}) if isinstance(events, dict) else {}

    pd_severity = incident.get("severity", "error").lower()
    severity_map = {"critical": "critical", "error": "high", "warning": "medium", "info": "low"}
    severity = severity_map.get(pd_severity, "high")

    service_name = ""
    if isinstance(incident.get("service"), dict):
        service_name = incident["service"].get("name", "")
    elif isinstance(incident.get("service"), str):
        service_name = incident["service"]

    details: dict = incident.get("body", {})
    body_text = details.get("details", "") if isinstance(details, dict) else str(details)

    return NormalizedAlert(
        alert_id=incident.get("id", str(uuid.uuid4())),
        source=AlertSource.PAGERDUTY,
        title=incident.get("title", "PagerDuty Incident"),
        body=body_text,
        severity=severity,
        affected_service=service_name or None,
        affected_cluster=None,
        affected_namespace=None,
        affected_job_name=None,
        timestamp=events.get("occurred_at", _now_iso()) if isinstance(events, dict) else _now_iso(),
        tags={"pd_severity": pd_severity, "service": service_name},
        raw=payload,
    )


def normalize_manual(payload: dict[str, Any]) -> NormalizedAlert:
    """Normalize a manual/test alert payload to NormalizedAlert.

    Accepts any free-form dict with keys matching NormalizedAlert fields.
    Used for testing and ad-hoc investigations.
    """
    return NormalizedAlert(
        alert_id=payload.get("alert_id", str(uuid.uuid4())),
        source=AlertSource.MANUAL,
        title=payload.get("title", "Manual Alert"),
        body=payload.get("body", payload.get("description", "")),
        severity=payload.get("severity", "medium"),
        affected_service=payload.get("affected_service"),
        affected_cluster=payload.get("affected_cluster"),
        affected_namespace=payload.get("affected_namespace"),
        affected_job_name=payload.get("affected_job_name"),
        timestamp=payload.get("timestamp", _now_iso()),
        tags=payload.get("tags", {}),
        raw=payload,
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
