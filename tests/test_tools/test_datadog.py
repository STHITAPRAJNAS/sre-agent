from __future__ import annotations

import pytest
import respx
import httpx

from sre_agent.tools.datadog import (
    get_datadog_monitor_status,
    search_datadog_monitors,
    get_datadog_metric_timeseries,
    get_datadog_logs,
    get_datadog_active_incidents,
)


@pytest.mark.asyncio
class TestDatadogTools:
    @respx.mock
    async def test_get_monitor_status(self, mock_settings):
        respx.get("https://api.datadoghq.com/api/v1/monitor/42").mock(
            return_value=httpx.Response(
                200,
                json={"id": 42, "name": "Flink Job Down", "overall_state": "Alert"},
            )
        )
        result = await get_datadog_monitor_status(42)
        assert result["id"] == 42
        assert result["name"] == "Flink Job Down"

    @respx.mock
    async def test_search_monitors(self, mock_settings):
        respx.get("https://api.datadoghq.com/api/v1/monitor").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "name": "Test"}])
        )
        result = await search_datadog_monitors("flink")
        assert result["count"] == 1
        assert result["monitors"][0]["name"] == "Test"

    @respx.mock
    async def test_get_metric_timeseries(self, mock_settings):
        respx.get("https://api.datadoghq.com/api/v1/query").mock(
            return_value=httpx.Response(200, json={"series": [{"metric": "flink.job.uptime"}]})
        )
        result = await get_datadog_metric_timeseries("avg:flink.job.uptime{*}", 1700000000, 1700003600)
        assert "series" in result

    @respx.mock
    async def test_get_logs(self, mock_settings):
        respx.post("https://api.datadoghq.com/api/v2/logs/events/search").mock(
            return_value=httpx.Response(200, json={"data": [], "meta": {}})
        )
        result = await get_datadog_logs("service:flink ERROR", "2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z")
        assert "data" in result

    @respx.mock
    async def test_get_active_incidents(self, mock_settings):
        respx.get("https://api.datadoghq.com/api/v2/incidents").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        result = await get_datadog_active_incidents()
        assert "data" in result
