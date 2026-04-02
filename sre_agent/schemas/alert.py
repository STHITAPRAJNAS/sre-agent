from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AlertSource(str, Enum):
    DATADOG = "datadog"
    PAGERDUTY = "pagerduty"
    CLOUDWATCH = "cloudwatch"
    MANUAL = "manual"


class NormalizedAlert(BaseModel):
    alert_id: str
    source: AlertSource
    title: str
    body: str
    severity: str = Field(description="critical | high | medium | low")
    affected_service: str | None = None
    affected_cluster: str | None = None
    affected_namespace: str | None = None
    affected_job_name: str | None = None
    timestamp: str
    tags: dict[str, str] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
