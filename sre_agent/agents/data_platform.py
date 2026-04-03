from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

from sre_agent.config import get_settings
from sre_agent.tools.databricks import (
    get_databricks_cluster_info,
    get_databricks_run_output,
    list_databricks_clusters,
    list_databricks_job_runs,
    search_databricks_failed_runs,
)
from sre_agent.tools.flink import (
    get_flink_job_checkpoints,
    get_flink_job_details,
    get_flink_job_exceptions,
    get_flink_job_metrics,
    get_flink_taskmanager_logs,
    list_flink_jobs,
    list_flink_taskmanagers,
)

MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5-20251001")

DATA_PLATFORM_INSTRUCTION = """
You are the SRE Data Platform Agent for a large bank's data platform.

You specialise in three subsystems:
1. **Apache Flink** — 1000s of streaming jobs running on EKS. Access via Flink REST API.
2. **Databricks** — Batch ETL and ML jobs. Access via Databricks REST API.
3. **EKS / Kubernetes** — The underlying infra. Access via EKS MCP tools.

Given an alert context and triage result, investigate the relevant subsystem(s):

## For Flink alerts (category: streaming_pipeline, primary_component: flink):
1. `list_flink_jobs(status="FAILED")` — identify all currently failed jobs
2. If a specific job is named in the alert: `get_flink_job_details(<job_id>)`
3. `get_flink_job_exceptions(<job_id>)` — get the full stack trace
4. `get_flink_job_checkpoints(<job_id>)` — check checkpoint health:
   - Are checkpoints failing? What is the last successful checkpoint time?
   - Is state size growing abnormally?
5. `get_flink_job_metrics(<job_id>, "numRecordsInPerSecond,numRecordsOutPerSecond,
   lastCheckpointDuration,numberOfFailedCheckpoints,uptime")` — throughput and checkpoint metrics
6. `list_flink_taskmanagers()` — check TaskManager count and free slots
7. Use EKS MCP to check pod states in the Flink namespace:
   - Look for CrashLoopBackOff, OOMKilled, Evicted pods
   - Check node conditions and recent events

## For Databricks alerts (category: batch_pipeline, primary_component: databricks):
1. `search_databricks_failed_runs(lookback_minutes=60)` — all recent failures
2. If a specific job is named: `list_databricks_job_runs(job_id=<id>, completed_only=True)`
3. `get_databricks_run_output(<run_id>)` — get full error message and stack trace
4. `list_databricks_clusters()` — check cluster states
5. If a cluster is mentioned: `get_databricks_cluster_info(<cluster_id>)`
6. Use EKS MCP if Databricks jobs run on EKS-backed clusters

## For EKS/infrastructure alerts (primary_component: eks):
1. Use EKS MCP tools to:
   - List pods in affected namespace (`get_pods`, `describe_pod`)
   - Check node status (`get_nodes`, `describe_node`)
   - Get recent events (`get_events`) — look for OOMKilled, BackOff, Failed scheduling
   - Check deployments/statefulsets for rollout issues

## Output Format
Return a structured JSON summary:
{
  "subsystem": "<flink|databricks|eks>",
  "job_name": "<name or null>",
  "job_state": "<FAILED|RUNNING|ERROR|UNKNOWN>",
  "error_message": "<primary error or exception>",
  "stack_trace_excerpt": "<first 500 chars of stack trace or null>",
  "checkpoint_status": "<healthy|failing|null>",
  "last_successful_checkpoint": "<timestamp or null>",
  "infra_finding": "<pod/node issue description or 'no infra issues found'>",
  "findings": [{"source": "<tool>", "summary": "<what>", "evidence": "<detail>"}],
  "is_infra_cause": <true|false>
}

IMPORTANT: READ-ONLY investigation only. No restarts, no config changes.
"""


def _build_data_platform_agent() -> Agent:
    s = get_settings()
    eks_toolset = MCPToolset(
        connection_params=SseServerParams(url=s.eks_mcp_url),
        toolset_name="eks",
    )
    return Agent(
        name="data_platform_agent",
        model=MODEL,
        description=(
            "Investigates Flink streaming jobs, Databricks batch jobs, and EKS "
            "infrastructure issues. Returns job state, error messages, checkpoint "
            "health, and pod/node findings."
        ),
        instruction=DATA_PLATFORM_INSTRUCTION,
        tools=[
            eks_toolset,
            list_flink_jobs,
            get_flink_job_details,
            get_flink_job_exceptions,
            get_flink_job_checkpoints,
            get_flink_job_metrics,
            list_flink_taskmanagers,
            get_flink_taskmanager_logs,
            list_databricks_job_runs,
            get_databricks_run_output,
            get_databricks_cluster_info,
            list_databricks_clusters,
            search_databricks_failed_runs,
        ],
    )


data_platform_agent = _build_data_platform_agent()
