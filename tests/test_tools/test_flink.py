from __future__ import annotations

import pytest
import respx
import httpx

from sre_agent.tools.flink import (
    list_flink_jobs,
    get_flink_job_details,
    get_flink_job_exceptions,
    get_flink_job_checkpoints,
    get_flink_job_metrics,
    list_flink_taskmanagers,
)

FLINK_BASE = "http://localhost:8081"

SAMPLE_JOBS = {
    "jobs": [
        {"id": "abc123", "name": "kafka-flink-orders", "state": "FAILED", "start-time": 1700000000},
        {"id": "def456", "name": "kafka-flink-payments", "state": "RUNNING", "start-time": 1700000000},
    ]
}


@pytest.mark.asyncio
class TestFlinkTools:
    @respx.mock
    async def test_list_all_jobs(self, mock_settings):
        respx.get(f"{FLINK_BASE}/jobs/overview").mock(
            return_value=httpx.Response(200, json=SAMPLE_JOBS)
        )
        result = await list_flink_jobs()
        assert result["count"] == 2

    @respx.mock
    async def test_list_jobs_filtered_by_status(self, mock_settings):
        respx.get(f"{FLINK_BASE}/jobs/overview").mock(
            return_value=httpx.Response(200, json=SAMPLE_JOBS)
        )
        result = await list_flink_jobs(status="FAILED")
        assert result["count"] == 1
        assert result["jobs"][0]["name"] == "kafka-flink-orders"

    @respx.mock
    async def test_get_job_details(self, mock_settings):
        respx.get(f"{FLINK_BASE}/jobs/abc123").mock(
            return_value=httpx.Response(200, json={"jid": "abc123", "name": "kafka-flink-orders", "state": "FAILED"})
        )
        result = await get_flink_job_details("abc123")
        assert result["jid"] == "abc123"
        assert result["state"] == "FAILED"

    @respx.mock
    async def test_get_job_exceptions(self, mock_settings):
        respx.get(f"{FLINK_BASE}/jobs/abc123/exceptions").mock(
            return_value=httpx.Response(200, json={
                "root-exception": "java.lang.NullPointerException",
                "all-exceptions": [{"exception": "NPE", "timestamp": 1700000000}]
            })
        )
        result = await get_flink_job_exceptions("abc123")
        assert "root-exception" in result
        assert "NullPointerException" in result["root-exception"]

    @respx.mock
    async def test_get_job_checkpoints(self, mock_settings):
        respx.get(f"{FLINK_BASE}/jobs/abc123/checkpoints").mock(
            return_value=httpx.Response(200, json={
                "counts": {"completed": 10, "failed": 3},
                "summary": {"state_size": {"max": 1073741824}}
            })
        )
        result = await get_flink_job_checkpoints("abc123")
        assert result["counts"]["failed"] == 3

    @respx.mock
    async def test_list_taskmanagers(self, mock_settings):
        respx.get(f"{FLINK_BASE}/taskmanagers").mock(
            return_value=httpx.Response(200, json={"taskmanagers": [{"id": "tm-001", "slotsNumber": 4, "freeSlots": 0}]})
        )
        result = await list_flink_taskmanagers()
        assert len(result["taskmanagers"]) == 1
