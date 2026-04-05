from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None


def setup_tracing(
    service_name: str = "sre-agent",
    otlp_endpoint: str | None = None,
    console_fallback: bool = False,
) -> None:
    """Configure OpenTelemetry tracing for the SRE agent.

    Exports spans to an OTLP-compatible backend (Datadog Agent, Jaeger,
    OTEL Collector). The Datadog Agent accepts OTLP on port 4317 by default.

    Call once at application startup (in webhook/server.py lifespan).

    Args:
        service_name: Service name tag on all spans.
        otlp_endpoint: OTLP gRPC endpoint, e.g. 'http://localhost:4317'.
                       If None, uses OTEL_EXPORTER_OTLP_ENDPOINT env var.
        console_fallback: If True and no OTLP endpoint, print spans to console.
    """
    global _tracer

    resource = Resource(
        attributes={
            "service.name": service_name,
            "service.version": "0.1.0",
        }
    )
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry OTLP exporter configured: %s", otlp_endpoint)
        except Exception:
            logger.warning("Failed to configure OTLP exporter", exc_info=True)
            if console_fallback:
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif console_fallback:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("OpenTelemetry tracing initialised for service: %s", service_name)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer (no-op if setup_tracing was not called)."""
    if _tracer is None:
        return trace.get_tracer("sre-agent")
    return _tracer


def traced_tool(name: str | None = None) -> Callable:
    """Decorator to wrap an async tool function in an OpenTelemetry span.

    Usage:
        @traced_tool()
        async def get_datadog_monitor_status(monitor_id: int) -> dict:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__name__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(f"tool.{span_name}") as span:
                # Record first arg as attribute (usually the primary ID)
                if args:
                    span.set_attribute("tool.primary_arg", str(args[0])[:100])
                for k, v in list(kwargs.items())[:3]:
                    span.set_attribute(f"tool.{k}", str(v)[:100])
                try:
                    result = await fn(*args, **kwargs)
                    span.set_attribute("tool.success", True)
                    return result
                except Exception as exc:
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(exc)[:200])
                    span.record_exception(exc)
                    raise

        return wrapper
    return decorator


def trace_agent_event(event_type: str, agent_name: str, alert_id: str = "") -> None:
    """Record a lightweight span for an ADK agent event (tool call, transfer, response)."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"agent.{event_type}") as span:
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("alert.id", alert_id)
