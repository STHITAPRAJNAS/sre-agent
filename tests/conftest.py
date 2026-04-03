from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_settings(monkeypatch):
    """Patch Settings with safe test defaults so no real credentials are needed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api-key")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app-key")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("DATABRICKS_HOST", "adb-test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("FLINK_JOBMANAGER_URL", "http://localhost:8081")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_INCIDENT_CHANNEL", "#sre-test")
    monkeypatch.setenv("SPLUNK_MCP_URL", "http://localhost:8090/sse")
    monkeypatch.setenv("EKS_MCP_URL", "http://localhost:8091/sse")
    monkeypatch.setenv("BITBUCKET_MCP_URL", "http://localhost:8092/sse")
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    monkeypatch.setenv("OPENSEARCH_CODE_INDEX", "test-code-chunks")
    monkeypatch.setenv("CODE_AGENT_A2A_URL", "http://localhost:9090")
    # Clear lru_cache so patched env is picked up
    from sre_agent.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
