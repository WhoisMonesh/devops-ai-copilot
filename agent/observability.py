# agent/observability.py - OpenTelemetry tracing + structured audit logging
# Provides:
#   - Distributed tracing (OTLP/gRPC or HTTP)
#   - Structured audit log to file (JSON Lines, SIEM-compatible)
#   - Correlation ID propagation across all tool calls
#   - Span creation for every tool invocation
from __future__ import annotations

import json
import logging
import os
import threading
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Context variable for correlation ID (propagates across async tasks)
corr_id_var: ContextVar[str] = ContextVar("corr_id", default="")
user_var: ContextVar[str] = ContextVar("user", default="anonymous")

# ---------------------------------------------------------------------------
# OpenTelemetry - only initialised if OTEL_* env vars are present
# ---------------------------------------------------------------------------
_tracer = None
_metrics_export = None


def _init_telemetry():
    """Lazily initialise OpenTelemetry tracing."""
    global _tracer, _metrics_export

    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not otel_endpoint:
        logger.info("OpenTelemetry disabled (no OTEL_EXPORTER_OTLP_ENDPOINT set)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.semconv.resource import ResourceAttributes

        service_name = os.getenv("OTEL_SERVICE_NAME", "devops-ai-copilot")

        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: service_name,
            ResourceAttributes.SERVICE_VERSION: "1.1.0",
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

        logger.info("OpenTelemetry tracing enabled → %s", otel_endpoint)
    except ImportError:
        logger.warning("opentelemetry not installed. Run: pip install opentelemetry-api")
    except Exception as exc:
        logger.warning("OpenTelemetry initialisation failed: %s", exc)


_init_telemetry()


def get_tracer():
    """Return the OpenTelemetry tracer (or a no-op if disabled)."""
    if _tracer is None:
        # Return a no-op tracer
        from opentelemetry import trace
        return trace.get_tracer("noop")
    return _tracer


# ---------------------------------------------------------------------------
# Structured audit log
# ---------------------------------------------------------------------------
class AuditEventType(Enum):
    # Tool events
    TOOL_INVOKED      = "TOOL_INVOKED"
    TOOL_DENIED       = "TOOL_DENIED"
    TOOL_FAILED       = "TOOL_FAILED"
    # Auth events
    AUTH_SUCCESS      = "AUTH_SUCCESS"
    AUTH_FAILURE      = "AUTH_FAILURE"
    AUTH_EXPIRED      = "AUTH_EXPIRED"
    # Config events
    CONFIG_CHANGED    = "CONFIG_CHANGED"
    CACHE_INVALIDATED = "CACHE_INVALIDATED"
    MODE_CHANGED      = "MODE_CHANGED"
    # Session events
    SESSION_START     = "SESSION_START"
    SESSION_END       = "SESSION_END"
    QUERY_EXECUTED    = "QUERY_EXECUTED"


@dataclass
class AuditEvent:
    """Structured audit log entry (JSON Lines format)."""
    timestamp: str
    event_type: str
    corr_id: str
    user: str
    tool: str          = ""
    mode: str          = ""
    operation: str     = ""
    allowed: bool      = True
    duration_ms: int   = 0
    error: str         = ""
    details: str       = ""
    session_id: str    = ""
    ip_address: str    = ""
    metadata: dict     = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v or k in (
            "event_type", "corr_id", "user", "tool", "allowed"
        )}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class StructuredAuditLogger:
    """
    Thread-safe structured audit logger that writes JSON Lines to a file.
    Suitable for ingestion by SIEM tools (Splunk, Elastic, Sumo Logic).
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.getenv(
            "AUDIT_LOG_PATH",
            "/var/log/devops-ai/audit.jsonl",
        )
        self._lock = threading.Lock()
        self._file = None

    def _ensure_file(self):
        if self._file is None:
            try:
                log_dir = os.path.dirname(self._path)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                self._file = open(self._path, "a", buffering=1)
            except Exception as exc:
                logger.error("Cannot open audit log %s: %s", self._path, exc)
                self._file = open(os.devnull, "w")

    def log(self, event: AuditEvent) -> None:
        """Write a single audit event to the log file."""
        with self._lock:
            try:
                self._ensure_file()
                self._file.write(event.to_json() + "\n")
                self._file.flush()
            except Exception as exc:
                logger.error("Audit log write failed: %s", exc)

    def log_tool_invoked(
        self,
        tool_name: str,
        allowed: bool,
        mode: str,
        operation: str = "",
        duration_ms: int = 0,
        error: str = "",
    ) -> None:
        self.log(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.TOOL_INVOKED.value if allowed else AuditEventType.TOOL_DENIED.value,
            corr_id=corr_id_var.get(""),
            user=user_var.get("anonymous"),
            tool=tool_name,
            mode=mode,
            operation=operation,
            allowed=allowed,
            duration_ms=duration_ms,
            error=error,
        ))

    def log_query(
        self,
        question: str,
        session_id: str,
        tool_used: Optional[str],
        cached: bool,
        latency_ms: int,
        error: str = "",
    ) -> None:
        self.log(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.QUERY_EXECUTED.value,
            corr_id=corr_id_var.get(""),
            user=user_var.get("anonymous"),
            tool=tool_used or "agent",
            allowed=True,
            duration_ms=latency_ms,
            error=error,
            details=question[:500],  # log truncated query
            session_id=session_id,
        ))

    def log_auth(self, success: bool, user: str, reason: str = "") -> None:
        self.log(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.AUTH_SUCCESS.value if success else AuditEventType.AUTH_FAILURE.value,
            corr_id=corr_id_var.get(""),
            user=user,
            allowed=success,
            error=reason,
        ))

    def log_config_change(self, changed_by: str, key: str, value: str) -> None:
        self.log(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.CONFIG_CHANGED.value,
            corr_id=corr_id_var.get(""),
            user=changed_by,
            details=f"{key}={value}",
        ))

    def log_mode_change(self, mode: str, changed_by: str) -> None:
        self.log(AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.MODE_CHANGED.value,
            corr_id=corr_id_var.get(""),
            user=changed_by,
            mode=mode,
            details=f"Changed to {mode}",
        ))


# Global audit logger instance
_audit_logger: Optional[StructuredAuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> StructuredAuditLogger:
    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                _audit_logger = StructuredAuditLogger()
    return _audit_logger


def set_corr_id(corr_id: str) -> None:
    corr_id_var.set(corr_id)


def get_corr_id() -> str:
    return corr_id_var.get("")


def set_user(user: str) -> None:
    user_var.set(user)


# ---------------------------------------------------------------------------
# Tool call tracing helper (used by orchestrator)
# ---------------------------------------------------------------------------
def trace_tool_call(
    tool_name: str,
    operation: str,
    mode: str,
    allowed: bool,
    duration_ms: int,
    error: str = "",
) -> None:
    """
    Create an OpenTelemetry span for a tool call + write audit log entry.
    Called by the orchestrator after each tool execution.
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"tool.{tool_name}") as span:
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.operation", operation)
        span.set_attribute("tool.mode", mode)
        span.set_attribute("tool.allowed", allowed)
        if error:
            span.set_attribute("tool.error", error)
        if duration_ms:
            span.set_attribute("tool.duration_ms", duration_ms)

        # Also write structured audit log
        get_audit_logger().log_tool_invoked(
            tool_name=tool_name,
            allowed=allowed,
            mode=mode,
            operation=operation,
            duration_ms=duration_ms,
            error=error,
        )
