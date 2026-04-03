from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from pydantic import BaseModel, Field

MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5-20251001")

TRIAGE_INSTRUCTION = """
You are the SRE Triage Agent for a large bank's data platform.

Your ONLY job is to analyze an incoming alert JSON and produce a structured triage assessment.
Do NOT call any external tools — reason solely from the alert payload provided.

The platform runs:
- Apache Flink streaming jobs (1000s) on EKS (Kubernetes/AWS)
- Databricks batch/ML jobs
- REST APIs on AWS (API Gateway, ECS, EKS)
- Supporting infra: Kafka, S3, RDS, ElastiCache

Analyze the alert and return a JSON object with exactly these fields:

{
  "severity": "<critical|high|medium|low>",
  "category": "<streaming_pipeline|batch_pipeline|api|infrastructure|database|unknown>",
  "primary_component": "<flink|databricks|eks|api_gateway|rds|kafka|s3|unknown>",
  "affected_job_name": "<job name string or null>",
  "suspect_code_change": <true|false>,
  "investigation_hints": ["<hint1>", "<hint2>", ...],
  "summary": "<one-line human-readable summary>"
}

Rules:
- Set `suspect_code_change: true` if the alert body/tags mention: deploy, release, rollout,
  version change, config update, PR, commit, or recent push.
- `investigation_hints` should list 2-5 specific things to check, e.g.:
  "check Flink checkpoint failure reason", "look for OOMKilled in EKS events",
  "query Splunk for NullPointerException in last 30 minutes"
- Always output ONLY valid JSON — no preamble, no explanation.
"""


class TriageResult(BaseModel):
    severity: str = Field(description="critical | high | medium | low")
    category: str = Field(
        description="streaming_pipeline | batch_pipeline | api | infrastructure | database | unknown"
    )
    primary_component: str = Field(
        description="flink | databricks | eks | api_gateway | rds | kafka | s3 | unknown"
    )
    affected_job_name: str | None = None
    suspect_code_change: bool = False
    investigation_hints: list[str] = Field(default_factory=list)
    summary: str = ""


triage_agent = Agent(
    name="triage_agent",
    model=MODEL,
    description=(
        "Classifies incoming SRE alerts into structured triage results: severity, "
        "category, primary component, and investigation hints. No external tool calls."
    ),
    instruction=TRIAGE_INSTRUCTION,
    output_schema=TriageResult,
    output_key="triage_result",
)
