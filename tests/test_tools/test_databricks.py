from __future__ import annotations

import time
import pytest
import respx
import httpx

from sre_agent.tools.databricks import (
    list_databricks_job_runs,
    get_databricks_run_output,
    list_databricks_clusters,
    search_databricks_failed_runs,
)

DBKS_BASE = "https://adb-test.azuredatabricks.net"


@pytest.mark.asyncio
class TestDatabricksTools:
    @respx.mock
    async def test_list_job_runs(self, mock_settings):
        respx.get(f"{DBKS_BASE}/api/2.1/jobs/runs/list").mock(
            return_value=httpx.Response(200, json={
                "runs": [
                    {"run_id": 1, "job_id": 100, "run_name": "etl-orders",
                     "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
                     "start_time": 1700000000000}
                ],
                "has_more": False
            })
        )
        result = await list_databricks_job_runs()
        assert len(result["runs"]) == 1
        assert result["runs"][0]["run_id"] == 1

    @respx.mock
    async def test_get_run_output(self, mock_settings):
        respx.get(f"{DBKS_BASE}/api/2.1/jobs/runs/get-output").mock(
            return_value=httpx.Response(200, json={
                "error": "FileNotFoundException: /mnt/data/input not found",
                "error_trace": "Traceback...",
                "metadata": {"run_page_url": "https://..."}
            })
        )
        result = await get_databricks_run_output(12345)
        assert "FileNotFoundException" in result["error"]

    @respx.mock
    async def test_list_clusters(self, mock_settings):
        respx.get(f"{DBKS_BASE}/api/2.0/clusters/list").mock(
            return_value=httpx.Response(200, json={
                "clusters": [
                    {"cluster_id": "c-001", "cluster_name": "etl-cluster",
                     "state": "RUNNING", "spark_version": "13.3.x-scala2.12"}
                ]
            })
        )
        result = await list_databricks_clusters()
        assert result["count"] == 1
        assert result["clusters"][0]["state"] == "RUNNING"

    @respx.mock
    async def test_search_failed_runs(self, mock_settings):
        now_ms = int(time.time() * 1000)
        respx.get(f"{DBKS_BASE}/api/2.1/jobs/runs/list").mock(
            return_value=httpx.Response(200, json={
                "runs": [
                    {"run_id": 99, "job_id": 200, "run_name": "ml-training",
                     "state": {"life_cycle_state": "TERMINATED", "result_state": "FAILED",
                               "state_message": "OOM error"},
                     "start_time": now_ms - 1000000,
                     "run_duration": 300000}
                ],
                "has_more": False
            })
        )
        result = await search_databricks_failed_runs(lookback_minutes=60)
        assert result["count"] == 1
        assert result["failed_runs"][0]["result_state"] == "FAILED"
