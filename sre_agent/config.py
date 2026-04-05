from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""

    # Embeddings (OpenAI text-embedding-3-small by default)
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # Datadog
    datadog_api_key: str = ""
    datadog_app_key: str = ""
    datadog_site: str = "datadoghq.com"

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Databricks
    databricks_host: str = ""
    databricks_token: str = ""

    # Flink
    flink_jobmanager_url: str = "http://localhost:8081"

    # Slack
    slack_bot_token: str = ""
    slack_incident_channel: str = "#sre-incidents"

    # MCP servers
    splunk_mcp_url: str = "http://splunk-mcp:8080/sse"
    eks_mcp_url: str = "http://eks-mcp:8080/sse"
    bitbucket_mcp_url: str = "http://bitbucket-mcp:8080/sse"

    # OpenSearch (AST code index)
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_code_index: str = "platform-code-chunks"

    # Code Agent (A2A)
    code_agent_a2a_url: str = "http://code-agent:8080"

    # PostgreSQL — sessions + pgvector memory + runbooks + service catalog + dedup
    database_url: str = "postgresql+asyncpg://sre:sre@localhost:5432/sre_agent"
    # Raw asyncpg DSN (without SQLAlchemy driver prefix, used by asyncpg directly)
    @property
    def asyncpg_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    # OpenTelemetry
    otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False

    # Alert deduplication
    alert_dedup_ttl_minutes: int = 15

    # Proactive health check scheduler
    health_check_interval_minutes: int = 5
    health_check_enabled: bool = True

    # Webhook HMAC secret (optional)
    webhook_secret: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
