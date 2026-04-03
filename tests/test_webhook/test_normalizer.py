from __future__ import annotations

import json
import pytest

from sre_agent.schemas.alert import AlertSource
from webhook.normalizer import (
    normalize_cloudwatch,
    normalize_datadog,
    normalize_manual,
    normalize_pagerduty,
)


class TestNormalizeDatadog:
    def test_basic_alert(self):
        payload = {
            "id": "12345",
            "title": "Flink job kafka-orders is down",
            "msg": "Job has been FAILED for 5 minutes",
            "alert_type": "error",
            "tags": "service:flink-orders,kube_namespace:flink-prod,job_name:kafka-orders,env:prod",
            "last_updated": "2024-01-15T14:35:00Z",
        }
        alert = normalize_datadog(payload)

        assert alert.alert_id == "12345"
        assert alert.source == AlertSource.DATADOG
        assert alert.title == "Flink job kafka-orders is down"
        assert alert.severity == "high"
        assert alert.affected_service == "flink-orders"
        assert alert.affected_namespace == "flink-prod"
        assert alert.affected_job_name == "kafka-orders"
        assert alert.timestamp == "2024-01-15T14:35:00Z"

    def test_critical_from_tag(self):
        payload = {
            "id": "999",
            "title": "P1 Alert",
            "msg": "Critical issue",
            "alert_type": "error",
            "tags": "p1:true,service:orders-api",
            "last_updated": "2024-01-15T14:35:00Z",
        }
        alert = normalize_datadog(payload)
        assert alert.severity == "critical"

    def test_missing_fields_handled(self):
        alert = normalize_datadog({})
        assert alert.source == AlertSource.DATADOG
        assert alert.title == "Datadog Alert"
        assert alert.severity == "medium"


class TestNormalizeCloudWatch:
    def test_alarm_notification(self):
        message = {
            "AlarmName": "flink-taskmanager-cpu-high",
            "NewStateValue": "ALARM",
            "NewStateReason": "Threshold Crossed: CPUUtilization > 90 for 5 minutes",
            "StateChangeTime": "2024-01-15T14:35:00.000Z",
            "Trigger": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EKS",
                "Dimensions": [
                    {"name": "ClusterName", "value": "platform-prod"},
                    {"name": "Namespace", "value": "flink-prod"},
                ],
            },
        }
        payload = {"Type": "Notification", "Message": json.dumps(message)}
        alert = normalize_cloudwatch(payload)

        assert alert.source == AlertSource.CLOUDWATCH
        assert alert.title == "flink-taskmanager-cpu-high"
        assert alert.severity == "critical"
        assert alert.affected_cluster == "platform-prod"
        assert alert.affected_namespace == "flink-prod"

    def test_subscription_confirmation_passthrough(self):
        payload = {"Type": "SubscriptionConfirmation", "SubscribeURL": "https://..."}
        # normalizer should not crash; body will be empty
        alert = normalize_cloudwatch(payload)
        assert alert.source == AlertSource.CLOUDWATCH

    def test_missing_message_handled(self):
        alert = normalize_cloudwatch({"Type": "Notification"})
        assert alert.source == AlertSource.CLOUDWATCH


class TestNormalizePagerDuty:
    def test_incident_trigger(self):
        payload = {
            "events": [
                {
                    "event_type": "incident.triggered",
                    "occurred_at": "2024-01-15T14:35:00Z",
                    "data": {
                        "id": "PD123",
                        "title": "Databricks job pipeline-etl-orders failed",
                        "severity": "critical",
                        "body": {"details": "Job run 98765 failed with exit code 1"},
                        "service": {"name": "databricks-etl"},
                    },
                }
            ]
        }
        alert = normalize_pagerduty(payload)

        assert alert.alert_id == "PD123"
        assert alert.source == AlertSource.PAGERDUTY
        assert alert.severity == "critical"
        assert alert.affected_service == "databricks-etl"
        assert "exit code 1" in alert.body


class TestNormalizeManual:
    def test_full_payload(self):
        payload = {
            "title": "Test alert",
            "severity": "high",
            "affected_job_name": "test-flink-job",
            "body": "This is a test",
            "tags": {"env": "staging"},
        }
        alert = normalize_manual(payload)

        assert alert.source == AlertSource.MANUAL
        assert alert.title == "Test alert"
        assert alert.severity == "high"
        assert alert.affected_job_name == "test-flink-job"
        assert alert.tags == {"env": "staging"}

    def test_minimal_payload(self):
        alert = normalize_manual({"title": "Minimal"})
        assert alert.source == AlertSource.MANUAL
        assert alert.severity == "medium"
