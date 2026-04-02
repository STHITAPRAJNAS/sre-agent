from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""

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

    # OpenSearch
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_code_index: str = "platform-code-chunks"

    # Code Agent (A2A)
    code_agent_a2a_url: str = "http://code-agent:8080"

    # Webhook HMAC secret (optional)
    webhook_secret: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
