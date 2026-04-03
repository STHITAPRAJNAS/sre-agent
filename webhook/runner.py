from __future__ import annotations

import logging

from google.adk import types
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from sre_agent.agent import root_agent
from sre_agent.schemas.alert import NormalizedAlert

logger = logging.getLogger(__name__)

_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    session_service=_session_service,
    app_name="sre_agent",
)


async def invoke_sre_agent(alert: NormalizedAlert) -> None:
    """Invoke the SRE agent with a normalized alert.

    Creates a new session per alert invocation, streams all events from the
    agent (tool calls, sub-agent transfers, LLM responses), and logs them
    for observability. The final response is the RCA report.

    Args:
        alert: Normalized alert to investigate.
    """
    session = await _session_service.create_session(
        app_name="sre_agent",
        user_id="webhook",
    )

    logger.info(
        "Starting SRE investigation",
        extra={
            "alert_id": alert.alert_id,
            "severity": alert.severity,
            "source": alert.source,
            "title": alert.title,
            "session_id": session.id,
        },
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text=alert.model_dump_json(indent=2))],
    )

    try:
        async for event in _runner.run_async(
            user_id="webhook",
            session_id=session.id,
            new_message=message,
        ):
            _log_event(event, alert.alert_id)
    except Exception:
        logger.exception(
            "SRE agent invocation failed",
            extra={"alert_id": alert.alert_id, "session_id": session.id},
        )


def _log_event(event: object, alert_id: str) -> None:
    """Structured log each agent event for observability."""
    event_type = type(event).__name__
    extra = {"alert_id": alert_id, "event_type": event_type}

    if hasattr(event, "content") and event.content:
        parts = getattr(event.content, "parts", [])
        for part in parts:
            if hasattr(part, "function_call") and part.function_call:
                extra["tool"] = part.function_call.name
                extra["tool_args"] = str(part.function_call.args)[:200]
                logger.info("Tool call: %s", part.function_call.name, extra=extra)
            elif hasattr(part, "function_response") and part.function_response:
                extra["tool"] = part.function_response.name
                logger.info("Tool response: %s", part.function_response.name, extra=extra)
            elif hasattr(part, "text") and part.text:
                logger.debug("Agent text: %s", part.text[:300], extra=extra)

    if hasattr(event, "is_final_response") and event.is_final_response():
        logger.info("Final RCA response received", extra=extra)
