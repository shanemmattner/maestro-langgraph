"""Tracing for Maestro — OTel → Langfuse OTLP + Langfuse REST API for scores.

No SDK imports. Python 3.14 compatible.
"""

import base64
import json
import logging
import os
import urllib.request
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# --- OTel Setup ---

def _disable_langsmith():
    """Suppress LangSmith auto-tracing from LangGraph's transitive dependency."""
    os.environ.pop("LANGSMITH_API_KEY", None)
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def setup_tracing():
    """Initialize tracing — Langfuse via OTel OTLP. Suppresses LangSmith."""
    _setup_langfuse()


def _setup_langfuse():
    """OTel → Langfuse OTLP tracing. Suppresses LangSmith."""
    _disable_langsmith()

    base_url = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3100")
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not pk or not sk:
        logger.info("tracing_disabled", extra={"reason": "LANGFUSE keys not set"})
        return

    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=f"{base_url}/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {auth}"},
        )
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("tracing_enabled", extra={"backend": "otel→langfuse"})
    except ImportError:
        logger.warning("tracing_otel_import_failed")


def get_tracer(name: str = "langgraph-maestro"):
    """Get an OTel tracer. Safe to call even if OTel not installed."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoopTracer()


def flush_traces():
    """Force-flush all pending spans."""
    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except ImportError:
        pass


class _NoopSpan:
    """No-op span for when OTel is not available."""

    def set_attribute(self, key, value):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoopTracer:
    """No-op tracer for when OTel is not available."""

    def start_as_current_span(self, name, **kwargs):
        return _NoopSpan()


# --- Langfuse REST API (scores/feedback) ---

def _langfuse_host() -> str:
    return os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3100")


def _langfuse_auth_header() -> str:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    creds = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    return f"Basic {creds}"


def _langfuse_post(events: list[dict]) -> bool:
    """Post events to Langfuse ingestion API. Returns True on success."""
    url = f"{_langfuse_host()}/api/public/ingestion"
    payload = json.dumps({"batch": events}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": _langfuse_auth_header(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 207)
            if not ok:
                logger.warning("langfuse_post_unexpected_status", extra={"status": resp.status, "url": url})
            return ok
    except Exception as e:
        logger.warning("langfuse_post_error", extra={
            "error": str(e),
            "url": url,
            "hint": "Is Langfuse running? Check LANGFUSE_BASE_URL and that the server is reachable.",
        })
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def is_langfuse_available() -> bool:
    """Check if Langfuse is configured."""
    return bool(os.environ.get("LANGFUSE_SECRET_KEY") and os.environ.get("LANGFUSE_PUBLIC_KEY"))


def record_feedback(trace_id: str, score: float, comment: str | None = None) -> bool:
    """Record a quality score for a trace via Langfuse REST API."""
    if not is_langfuse_available():
        return False
    event = {
        "id": _new_id(),
        "type": "score-create",
        "timestamp": _now_iso(),
        "body": {
            "id": _new_id(),
            "traceId": trace_id,
            "name": "quality",
            "value": score,
            "comment": comment,
        },
    }
    return _langfuse_post([event])


def langfuse_create_trace(name: str, input_data: dict | None = None) -> str | None:
    """Create a new Langfuse trace and return its ID. Returns None on failure."""
    if not is_langfuse_available():
        logger.warning("langfuse_create_trace_skipped", extra={"reason": "keys not set"})
        return None
    trace_id = _new_id()
    event = {
        "id": _new_id(),
        "type": "trace-create",
        "timestamp": _now_iso(),
        "body": {
            "id": trace_id,
            "name": name,
            "input": input_data,
        },
    }
    ok = _langfuse_post([event])
    if ok:
        logger.info("langfuse_trace_created", extra={"trace_id": trace_id, "name": name})
    else:
        logger.warning("langfuse_trace_create_failed", extra={"name": name})
        return None
    return trace_id


def langfuse_update_trace(trace_id: str, output: dict | None = None, metadata: dict | None = None) -> bool:
    """Update an existing Langfuse trace with output/metadata."""
    if not is_langfuse_available() or not trace_id:
        return False
    body = {"id": trace_id}
    if output:
        body["output"] = output
    if metadata:
        body["metadata"] = metadata
    event = {
        "id": _new_id(),
        "type": "trace-create",  # Langfuse uses trace-create for upserts
        "timestamp": _now_iso(),
        "body": body,
    }
    ok = _langfuse_post([event])
    if ok:
        logger.info("langfuse_trace_updated", extra={"trace_id": trace_id})
    else:
        logger.warning("langfuse_trace_update_failed", extra={"trace_id": trace_id})
    return ok


def langfuse_health_check() -> bool:
    """Check if Langfuse server is reachable. Logs the result."""
    if not is_langfuse_available():
        logger.info("langfuse_health_check", extra={"status": "skipped", "reason": "keys not set"})
        return False
    host = _langfuse_host()
    try:
        req = urllib.request.Request(f"{host}/api/public/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status == 200
            logger.info("langfuse_health_check", extra={"status": "ok" if ok else "unhealthy", "host": host})
            return ok
    except Exception as e:
        logger.warning("langfuse_health_check", extra={"status": "unreachable", "host": host, "error": str(e)})
        return False


_current_trace_id: str | None = None


def set_current_trace_id(trace_id: str) -> None:
    """Store the current OTel trace ID (called from runner)."""
    global _current_trace_id
    _current_trace_id = trace_id


def get_run_url() -> str | None:
    """Get the Langfuse deep-link URL for the current trace."""
    if not is_langfuse_available():
        return None
    host = _langfuse_host()
    if _current_trace_id:
        return f"{host}/traces/{_current_trace_id}"
    return f"{host}/traces"


# --- Node Tracing Decorator ---

def trace_node(name: str):
    """Decorator to trace a LangGraph node. No-op when OTel is unavailable."""
    def decorator(fn):
        import functools

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(name):
                return fn(*args, **kwargs)

        # Async support
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(name):
                return await fn(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper

    return decorator
