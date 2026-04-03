# SRE Agent — Data Platform

A multi-agent SRE system built with [Google ADK](https://github.com/google/adk-python) for a
large bank's data platform. Investigates alerts across Flink streaming jobs, Databricks pipelines,
EKS infrastructure, and application code — then posts structured RCA reports to Slack.

## Architecture

```
Webhook (Datadog / PagerDuty / CloudWatch)
        ↓
  FastAPI Server  ←──  ADK Dev UI (/dev-ui)
        ↓
SRE Orchestrator Agent  (Claude Sonnet via LiteLLM)
  ├── Triage Agent          — classifies alert severity & component
  ├── Investigation Agent   — Splunk MCP + Datadog + CloudWatch
  ├── Data Platform Agent   — Flink REST + Databricks REST + EKS MCP
  ├── Code Intelligence     — OpenSearch AST index + Bitbucket MCP + Code Agent (A2A)
  └── Reporting Agent       — RCA synthesis → Slack Block Kit
```

## Tool Inventory

| Layer | Integration |
|-------|-------------|
| Logs | Splunk (MCP), CloudWatch Logs Insights |
| Metrics | Datadog REST API, CloudWatch Metrics |
| Streaming | Flink REST API |
| Batch | Databricks REST API |
| Infrastructure | EKS (MCP) |
| Code Search | Bitbucket (MCP), OpenSearch AST code index |
| Code Analysis | Remote Code Agent via ADK A2A |
| Notifications | Slack Block Kit |

## Quick Start

### 1. Install dependencies
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys and service URLs
```

### 3. Run the server
```bash
uvicorn webhook.server:app --reload --port 8000
```

### 4. Open the ADK Dev UI
```
http://localhost:8000/dev-ui
```
Use the dev UI to send test alerts interactively and trace agent reasoning.

### 5. Send a test alert
```bash
curl -X POST http://localhost:8000/webhook/manual \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Flink job kafka-flink-orders restarting",
    "severity": "critical",
    "affected_job_name": "kafka-flink-orders",
    "affected_namespace": "flink-prod",
    "body": "Job restarted 5 times in 10 minutes. Deploy happened at 14:15 UTC.",
    "tags": {"env": "prod", "team": "data-platform"}
  }'
```

## Webhook Endpoints

| Endpoint | Source |
|----------|--------|
| `POST /webhook/datadog` | Datadog monitor webhooks |
| `POST /webhook/cloudwatch` | CloudWatch SNS alarm notifications |
| `POST /webhook/pagerduty` | PagerDuty v3 webhooks |
| `POST /webhook/manual` | Manual / test alerts |
| `GET /health` | Health check |

## Agent Flow

```
Alert received
    → Triage Agent: classify severity, component, suspect_code_change
    → Investigation Agent: Splunk logs + Datadog metrics + CloudWatch
    → Data Platform Agent (if Flink/Databricks/EKS): job state + checkpoints + pods
    → Code Intelligence Agent (if code change suspected): OpenSearch + Bitbucket + A2A
    → Reporting Agent: synthesise RCA → post to Slack #sre-incidents
```

## Configuration

All configuration is via environment variables (see `.env.example`):

- `ANTHROPIC_API_KEY` — Claude Sonnet via LiteLLM
- `DATADOG_API_KEY` / `DATADOG_APP_KEY` — Datadog REST API
- `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — CloudWatch
- `DATABRICKS_HOST` / `DATABRICKS_TOKEN` — Databricks REST API
- `FLINK_JOBMANAGER_URL` — Flink JobManager REST endpoint
- `SLACK_BOT_TOKEN` / `SLACK_INCIDENT_CHANNEL` — Slack notifications
- `SPLUNK_MCP_URL` — Splunk MCP server SSE endpoint
- `EKS_MCP_URL` — EKS MCP server SSE endpoint
- `BITBUCKET_MCP_URL` — Bitbucket MCP server SSE endpoint
- `OPENSEARCH_URL` / `OPENSEARCH_CODE_INDEX` — AST code index
- `CODE_AGENT_A2A_URL` — Remote code analysis agent A2A endpoint

## Running Tests

```bash
pytest tests/ -v
```

## Read-Only by Design

This agent **investigates only** — it never auto-remediates. All recommendations are
surfaced to on-call engineers via Slack for human decision and action.
