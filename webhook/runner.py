from __future__ import annotations

import logging

from google.adk import types
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from sre_agent.agent import root_agent
from sre_agent.config import get_settings
from sre_agent.memory.pgvector_memory import PgVectorMemoryService
from sre_agent.schemas.alert import NormalizedAlert
from sre_agent.telemetry.tracing import get_tracer, trace_agent_event

logger = logging.getLogger(__name__)

_session_service: DatabaseSessionService | None = None
_memory_service: PgVectorMemoryService | None = None
_runner: Runner | None = None


def _get_runner() -> Runner:
    """Lazy-initialise the ADK Runner with DatabaseSessionService + PgVectorMemoryService.

    DatabaseSessionService persists all sessions (and session state / app-level KV pairs)
    to PostgreSQL via SQLAlchemy. PgVectorMemoryService stores RCA summaries as
    vector embeddings for semantic search in future incident investigations.
    """
    global _session_service, _memory_service, _runner
    if _runner is None:
        s = get_settings()
        _session_service = DatabaseSessionService(db_url=s.database_url)
        _memory_service = PgVectorMemoryService()
        _runner = Runner(
            agent=root_agent,
            session_service=_session_service,
            memory_service=_memory_service,
            app_name="sre_agent",
        )
        logger.info(
            "ADK Runner initialised with DatabaseSessionService + PgVectorMemoryService"
        )
    return _runner


async def invoke_sre_agent(alert: NormalizedAlert) -> None:
    """Invoke the SRE agent with a normalized alert.

    - Creates a PostgreSQL-persisted session with alert metadata pre-seeded into
      session state (accessible to all sub-agents via ADK state).
    - Streams all ADK events with structured logging + OpenTelemetry spans.
    - After the run, the Runner automatically calls memory_service.add_session_to_memory()
      so the RCA is stored in pgvector for future semantic search.

    Args:
        alert: Normalized alert to investigate.
    """
    tracer = get_tracer()
    runner = _get_runner()

    with tracer.start_as_current_span("sre_agent.investigate") as span:
        span.set_attribute("alert.id", alert.alert_id)
        span.set_attribute("alert.severity", alert.severity)
        span.set_attribute("alert.source", alert.source.value)
        span.set_attribute("alert.title", alert.title)

        # Seed session state so sub-agents can access alert metadata without re-parsing JSON.
        # ADK DatabaseSessionService persists this as a KV store per session.
        session = await runner.session_service.create_session(
            app_name="sre_agent",
            user_id="webhook",
            state={
                "alert_id": alert.alert_id,
                "alert_title": alert.title,
                "severity": alert.severity,
                "source": alert.source.value,
                "affected_job_name": alert.affected_job_name or "",
                "affected_service": alert.affected_service or "",
                "affected_namespace": alert.affected_namespace or "",
            },
        )

        logger.info(
            "SRE investigation started",
            extra={
                "alert_id": alert.alert_id,
                "severity": alert.severity,
                "source": alert.source.value,
                "title": alert.title,
                "session_id": session.id,
            },
        )

        message = types.Content(
            role="user",
            parts=[types.Part(text=alert.model_dump_json(indent=2))],
        )

        try:
            async for event in runner.run_async(
                user_id="webhook",
                session_id=session.id,
                new_message=message,
            ):
                _log_event(event, alert.alert_id)
                trace_agent_event(
                    type(event).__name__,
                    agent_name=getattr(event, "author", "unknown"),
                    alert_id=alert.alert_id,
                )

            span.set_attribute("investigation.completed", True)
            logger.info(
                "SRE investigation completed",
                extra={"alert_id": alert.alert_id, "session_id": session.id},
            )
        except Exception as exc:
            span.set_attribute("investigation.completed", False)
            span.set_attribute("investigation.error", str(exc)[:200])
            span.record_exception(exc)
            logger.exception(
                "SRE agent invocation failed",
                extra={"alert_id": alert.alert_id, "session_id": session.id},
            )


def _log_event(event: object, alert_id: str) -> None:
    """Structured log every ADK event for full observability."""
    extra = {"alert_id": alert_id, "event_type": type(event).__name__}
    content = getattr(event, "content", None)
    if content:
        for part in getattr(content, "parts", []):
            if getattr(part, "function_call", None):
                extra["tool"] = part.function_call.name
                extra["tool_args"] = str(part.function_call.args)[:200]
                logger.info("Tool call: %s", part.function_call.name, extra=extra)
            elif getattr(part, "function_response", None):
                logger.info("Tool response: %s", part.function_response.name, extra=extra)
            elif getattr(part, "text", None) and len(part.text) > 20:
                logger.debug("Agent text: %s", part.text[:300], extra=extra)
    if getattr(event, "is_final_response", lambda: False)():
        logger.info("Final RCA response received", extra=extra)
