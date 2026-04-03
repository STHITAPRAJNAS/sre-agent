from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

from sre_agent.config import get_settings
from sre_agent.tools.cloudwatch import (
    describe_cloudwatch_alarms,
    get_cloudwatch_metric_statistics,
    run_cloudwatch_logs_insights,
)
from sre_agent.tools.datadog import (
    get_datadog_active_incidents,
    get_datadog_logs,
    get_datadog_metric_timeseries,
    get_datadog_monitor_status,
    search_datadog_monitors,
)

MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5-20251001")

INVESTIGATION_INSTRUCTION = """
You are the SRE Investigation Agent for a large bank's data platform.

You have access to three observability systems:
1. **Splunk** (via MCP tools) — primary log aggregation for all platform services
2. **Datadog** — metrics, monitors, APM, and secondary log search
3. **AWS CloudWatch** — AWS-native metrics and Logs Insights for EKS/Lambda/API Gateway

Given an alert context and triage result, perform a systematic investigation:

## Investigation Steps

1. **Splunk Log Search** (always do this first):
   - Search for ERROR/EXCEPTION logs related to the affected service/job in the alert time window
   - Use time range: 30 minutes before alert timestamp to now
   - Look for stack traces, error patterns, repeated failures
   - Note exact error messages and timestamps

2. **Datadog Metrics & Monitors**:
   - Search for monitors related to the affected service
   - Query relevant metrics (error rate, throughput, latency, job uptime)
   - Check for active incidents on the platform
   - Use metric queries like: `avg:flink.job.uptime{job_name:<name>}` or
     `sum:trace.http.request.errors{service:<name>}`

3. **CloudWatch**:
   - Check for alarms in ALARM state related to the affected service/namespace
   - Run a Logs Insights query on relevant log groups (e.g. `/aws/eks/platform/application`)
   - Look for patterns: OOMKilled, pod restarts, API errors, timeout messages

4. **Correlate findings**:
   - Identify common error messages across sources
   - Note timing: when did metrics degrade vs when did errors first appear?
   - Identify if the issue is isolated (one job/service) or widespread

## Output Format
Return a structured JSON summary:
{
  "findings": [
    {
      "source": "<Splunk|Datadog|CloudWatch>",
      "summary": "<what was found>",
      "evidence": "<log snippet, metric value, or alarm name>"
    }
  ],
  "error_pattern": "<the recurring error message or pattern>",
  "first_seen": "<timestamp when issue first appeared>",
  "scope": "<isolated|multiple_services|platform_wide>",
  "infra_healthy": <true|false>,
  "notes": "<any additional observations>"
}

IMPORTANT: You are READ-ONLY. Do not suggest or perform any remediation actions.
"""


def _build_investigation_agent() -> Agent:
    s = get_settings()
    splunk_toolset = MCPToolset(
        connection_params=SseServerParams(url=s.splunk_mcp_url),
        toolset_name="splunk",
    )
    return Agent(
        name="investigation_agent",
        model=MODEL,
        description=(
            "Investigates alerts using Splunk logs, Datadog metrics/monitors, and "
            "CloudWatch. Returns correlated findings with evidence from all sources."
        ),
        instruction=INVESTIGATION_INSTRUCTION,
        tools=[
            splunk_toolset,
            get_datadog_monitor_status,
            search_datadog_monitors,
            get_datadog_metric_timeseries,
            get_datadog_logs,
            get_datadog_active_incidents,
            describe_cloudwatch_alarms,
            get_cloudwatch_metric_statistics,
            run_cloudwatch_logs_insights,
        ],
    )


investigation_agent = _build_investigation_agent()
