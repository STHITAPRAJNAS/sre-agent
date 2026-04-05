-- SRE Agent Database Schema
-- Run against PostgreSQL 15+ with pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- Incident memory — semantic search over past RCA reports
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incident_memory (
    id            BIGSERIAL PRIMARY KEY,
    app_name      VARCHAR(255)  NOT NULL,
    user_id       VARCHAR(255)  NOT NULL DEFAULT 'system',
    session_id    VARCHAR(255)  NOT NULL,
    alert_id      VARCHAR(255),
    alert_title   TEXT,
    summary       TEXT          NOT NULL,
    root_cause    TEXT,
    component     VARCHAR(100),
    severity      VARCHAR(50),
    embedding     vector(1536),          -- text-embedding-3-small / ada-002
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    metadata      JSONB         NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS incident_memory_embedding_idx
    ON incident_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS incident_memory_app_user_idx
    ON incident_memory (app_name, user_id);
CREATE INDEX IF NOT EXISTS incident_memory_component_idx
    ON incident_memory (component);

-- ─────────────────────────────────────────────────────────────────────────────
-- Runbook knowledge base — semantic search over known issue playbooks
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runbooks (
    id                  SERIAL PRIMARY KEY,
    title               TEXT          NOT NULL,
    component           VARCHAR(100)  NOT NULL,   -- flink | databricks | eks | api | kafka
    error_patterns      TEXT[]        NOT NULL DEFAULT '{}',
    description         TEXT          NOT NULL,   -- plain-text summary indexed for search
    steps               JSONB         NOT NULL,   -- ordered list of investigation/remediation steps
    severity_applicable TEXT[]        NOT NULL DEFAULT '{critical,high,medium,low}',
    tags                TEXT[]        NOT NULL DEFAULT '{}',
    embedding           vector(1536),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS runbooks_embedding_idx
    ON runbooks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX IF NOT EXISTS runbooks_component_idx ON runbooks (component);

-- ─────────────────────────────────────────────────────────────────────────────
-- Service catalog — ownership, SLOs, on-call, dashboards per service/job
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS service_catalog (
    id                  SERIAL PRIMARY KEY,
    service_name        VARCHAR(255)  UNIQUE NOT NULL,
    display_name        VARCHAR(255),
    team                VARCHAR(255),
    slack_channel       VARCHAR(255),
    oncall_schedule     VARCHAR(255),
    slo_uptime_pct      FLOAT         DEFAULT 99.9,
    slo_latency_p99_ms  INTEGER,
    dashboard_url       TEXT,
    runbook_url         TEXT,
    repository          VARCHAR(255),
    eks_namespace       VARCHAR(255),
    tags                TEXT[]        NOT NULL DEFAULT '{}',
    metadata            JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS service_catalog_team_idx ON service_catalog (team);
CREATE INDEX IF NOT EXISTS service_catalog_namespace_idx ON service_catalog (eks_namespace);

-- ─────────────────────────────────────────────────────────────────────────────
-- Alert deduplication window
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_dedup (
    dedup_key   VARCHAR(500) PRIMARY KEY,
    alert_id    VARCHAR(255) NOT NULL,
    alert_title TEXT,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    count       INTEGER      NOT NULL DEFAULT 1,
    suppressed  BOOLEAN      NOT NULL DEFAULT false
);

-- Auto-clean entries older than 2 hours (run via pg_cron or application)
-- DELETE FROM alert_dedup WHERE last_seen < NOW() - INTERVAL '2 hours';

-- ─────────────────────────────────────────────────────────────────────────────
-- Seed runbooks — known platform patterns
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO runbooks (title, component, error_patterns, description, steps, tags)
VALUES
(
  'Flink Job Checkpoint Timeout',
  'flink',
  ARRAY['checkpoint timeout', 'checkpoint failed', 'CheckpointException', 'failed to complete checkpoint'],
  'Flink job checkpoint is timing out or failing. Common causes: state backend I/O latency, insufficient parallelism, high state size, or slow downstream operators causing backpressure.',
  '[
    {"order": 1, "action": "Check checkpoint history", "detail": "Call get_flink_job_checkpoints(job_id). Look at last 10 checkpoints — is the duration trend increasing? What is the state size?"},
    {"order": 2, "action": "Check for backpressure", "detail": "Call get_flink_job_metrics(job_id, numRecordsInPerSecond,numRecordsOutPerSecond). If in >> out, there is backpressure."},
    {"order": 3, "action": "Check TaskManager health", "detail": "Use EKS MCP: get_pods(namespace=flink-prod). Look for OOMKilled, CrashLoopBackOff, or high CPU on TM pods."},
    {"order": 4, "action": "Check Kafka consumer lag", "detail": "Query Datadog: avg:kafka.consumer_lag{job_name:<name>}. High lag + backpressure = upstream pressure."},
    {"order": 5, "action": "Check state backend", "detail": "If RocksDB: look for slow disk I/O on TM pods. If in-memory: state size may exceed TM heap."},
    {"order": 6, "escalation": "If state size > 80% of configured limit: increase TM memory or reduce checkpoint interval. Page data-platform team."}
  ]'::jsonb,
  ARRAY['flink', 'checkpoint', 'state']
),
(
  'Flink TaskManager OOMKilled',
  'flink',
  ARRAY['OOMKilled', 'OutOfMemoryError', 'GC overhead limit exceeded', 'Java heap space', 'Direct buffer memory'],
  'Flink TaskManager pods are being OOMKilled by Kubernetes. State accumulation, memory leak, or misconfigured JVM heap are the common causes.',
  '[
    {"order": 1, "action": "Confirm OOM in EKS", "detail": "Use EKS MCP: get_events(namespace=flink-prod, reason=OOMKilling). Confirm which TM pods are affected."},
    {"order": 2, "action": "Check state size growth", "detail": "Call get_flink_job_checkpoints(job_id). Is state_size growing over time?"},
    {"order": 3, "action": "Check Kafka consumer lag", "detail": "Unbounded Kafka lag + no backpressure = state accumulation. Query Datadog for consumer lag."},
    {"order": 4, "action": "Check for memory leak in recent deploy", "detail": "Use Bitbucket MCP to find commits in last 24h. OpenSearch: search for state collection classes."},
    {"order": 5, "escalation": "Immediate: recommend increasing TM memory limit in Helm values. Do not restart without data-platform lead approval if job has large state."}
  ]'::jsonb,
  ARRAY['flink', 'oom', 'memory', 'eks']
),
(
  'Databricks Job Failure - Cluster Termination',
  'databricks',
  ARRAY['CLUSTER_NOT_FOUND', 'ClusterUnavailable', 'cluster terminated', 'autoscaling timeout'],
  'Databricks job failed because the cluster was terminated or unavailable. Causes: autoscale timeout, spot instance reclamation, idle timeout, or cluster policy changes.',
  '[
    {"order": 1, "action": "Get run output", "detail": "Call get_databricks_run_output(run_id). Read error and error_trace fields."},
    {"order": 2, "action": "Check cluster state", "detail": "Call get_databricks_cluster_info(cluster_id). If TERMINATED: check state_message for reason."},
    {"order": 3, "action": "Check for spot reclamation", "detail": "Look for node_provider_instance_terminated or spot_bid_price_too_low in cluster logs."},
    {"order": 4, "action": "Check Databricks job history", "detail": "Call list_databricks_job_runs(job_id, limit=10). Is this a recurring failure pattern?"},
    {"order": 5, "escalation": "For spot reclamation: recommend switching to on-demand for critical jobs or enabling spot fallback. Page data-engineering team."}
  ]'::jsonb,
  ARRAY['databricks', 'cluster', 'spot']
),
(
  'Databricks Job Failure - Python/Scala Exception',
  'databricks',
  ARRAY['Traceback', 'Exception', 'Error', 'java.lang.', 'scala.', 'AnalysisException', 'FileNotFoundException'],
  'Databricks job failed with an application exception. Likely a code bug, schema mismatch, or missing data file.',
  '[
    {"order": 1, "action": "Get full error trace", "detail": "Call get_databricks_run_output(run_id). Extract error_trace. Note the exception class and first application frame."},
    {"order": 2, "action": "Search code index", "detail": "Use search_code_chunks(error_class_name) in OpenSearch to find the relevant source file."},
    {"order": 3, "action": "Check for recent deploys", "detail": "Use Bitbucket MCP to find commits in last 24h touching the job notebook or library."},
    {"order": 4, "action": "Check input data", "detail": "If FileNotFoundException: verify source S3 path. If AnalysisException: schema may have changed upstream."},
    {"order": 5, "escalation": "Code change suspected: link PR in RCA report. Data issue: page data-quality team. Tag job owner from service catalog."}
  ]'::jsonb,
  ARRAY['databricks', 'code', 'schema']
),
(
  'EKS Pod CrashLoopBackOff',
  'eks',
  ARRAY['CrashLoopBackOff', 'BackOff', 'Error', 'pod failed', 'container failed'],
  'Kubernetes pods are in CrashLoopBackOff. The container exits immediately after starting, causing repeated restarts.',
  '[
    {"order": 1, "action": "Identify affected pods", "detail": "Use EKS MCP: get_pods(namespace). List all pods in CrashLoopBackOff with restart count."},
    {"order": 2, "action": "Get pod logs", "detail": "Use EKS MCP: get_pod_logs(pod_name, previous=true). Previous logs show the crash reason."},
    {"order": 3, "action": "Describe pod", "detail": "Use EKS MCP: describe_pod(pod_name). Check Events section for OOMKilled, Liveness probe failure, or config errors."},
    {"order": 4, "action": "Check recent deployment", "detail": "Use EKS MCP: get_deployment_history(namespace). Was there a recent rollout?"},
    {"order": 5, "escalation": "OOMKilled: recommend memory increase. Config error: check ConfigMap/Secret mounts. Image pull error: check ECR credentials."}
  ]'::jsonb,
  ARRAY['eks', 'kubernetes', 'pod', 'crashloop']
),
(
  'Kafka Consumer Lag Spike',
  'flink',
  ARRAY['consumer lag', 'lag spike', 'records behind', 'offset behind', 'consumer group lag'],
  'Kafka consumer group lag is spiking, indicating the Flink job is not processing messages fast enough. Causes: backpressure, slow UDF, or insufficient parallelism.',
  '[
    {"order": 1, "action": "Check current throughput", "detail": "Call get_flink_job_metrics(job_id, numRecordsInPerSecond,numRecordsOutPerSecond). Is throughput lower than baseline?"},
    {"order": 2, "action": "Check for backpressure", "detail": "Query Datadog: flink.task.backPressuredTimeMsPerSecond for each vertex. Identify the bottleneck operator."},
    {"order": 3, "action": "Check downstream systems", "detail": "If writing to a database/S3/Kafka: check write latency. Slow sink = backpressure."},
    {"order": 4, "action": "Check job parallelism vs partition count", "detail": "If Kafka has more partitions than job parallelism, some consumers are overloaded."},
    {"order": 5, "escalation": "If lag exceeds SLO threshold: page data-platform team to evaluate parallelism increase or topic rebalance."}
  ]'::jsonb,
  ARRAY['kafka', 'flink', 'lag', 'backpressure']
)
ON CONFLICT DO NOTHING;
