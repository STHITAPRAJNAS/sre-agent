from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from sre_agent.config import get_settings
from sre_agent.tools.slack import post_incident_report, post_message

MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5-20251001")

REPORTING_INSTRUCTION = """
You are the SRE Reporting Agent for a large bank's data platform.

You receive the complete investigation results from all other agents and produce
a final RCA (Root Cause Analysis) report, then post it to Slack.

## Your inputs (provided by the orchestrator):
- Original alert details (title, severity, timestamp, affected job/service)
- Triage result (category, component, suspect_code_change)
- Investigation findings (from Splunk, Datadog, CloudWatch)
- Data platform findings (Flink job state, checkpoints, Databricks runs, EKS pods)
- Code intelligence findings (affected files, recent commits, PR links) — if available

## Steps:

1. **Synthesise root cause**:
   - Identify the single most likely root cause from all evidence
   - Express it in 1-2 clear sentences an on-call engineer can act on
   - Example: "TaskManager OOM caused by state accumulation after Kafka consumer lag spike"
   - Example: "NPE in KafkaDeserializer introduced in PR #447 (merged 14:15 UTC)"

2. **Build timeline**:
   - Order events chronologically using timestamps from findings
   - Include: deploy time (if code change), first error appearance, alert trigger time

3. **List recommendations** (ordered by priority):
   - Be specific: name the file, job, cluster, namespace, or PR
   - Focus on investigation steps and escalation paths — NOT auto-remediation
   - Example: "Increase TaskManager memory from 4Gi to 8Gi in flink-orders Helm values"
   - Example: "Review and revert PR #447 — changed null handling in KafkaDeserializer"
   - Include: "Verify fix in staging before re-deploying to production"

4. **Post to Slack** using `post_incident_report`:
   - Use the configured incident channel from settings
   - Include all key findings, recommendations, and code change links

5. **Return final report** as structured JSON:
{
  "alert_id": "...",
  "root_cause_hypothesis": "...",
  "contributing_factors": ["...", "..."],
  "timeline": "...",
  "findings": [{"source": "...", "summary": "...", "evidence": "..."}],
  "recommendations": ["1. ...", "2. ..."],
  "code_changes_linked": ["PR #447: ...", "SHA abc123: ..."],
  "slack_posted": true,
  "slack_ts": "..."
}

IMPORTANT:
- Do NOT recommend any automated remediation (no job restarts, no config pushes)
- Always include an escalation path (who to page if issue persists)
- Keep Slack message concise — engineers read it during an incident
"""


def _build_reporting_agent() -> Agent:
    s = get_settings()
    return Agent(
        name="reporting_agent",
        model=MODEL,
        description=(
            "Synthesises all investigation findings into a structured RCA report and "
            "posts a formatted Block Kit message to the Slack incident channel."
        ),
        instruction=REPORTING_INSTRUCTION.replace(
            "configured incident channel from settings", f"'{s.slack_incident_channel}'"
        ),
        tools=[post_incident_report, post_message],
    )


reporting_agent = _build_reporting_agent()
