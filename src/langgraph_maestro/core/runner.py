"""Unified workflow runner with OTel tracing and checkpointed invoke."""

import logging
import time

from langgraph_maestro.core.tracing import get_tracer, flush_traces, set_current_trace_id

logger = logging.getLogger(__name__)


def run_workflow(name: str, graph, initial_state: dict, thread_id: str) -> dict:
    """Universal runner: OTel trace + checkpointed invoke + flush.

    Args:
        name: Workflow name (for tracing span).
        graph: Compiled LangGraph StateGraph.
        initial_state: Initial state dict.
        thread_id: Thread ID for checkpointing.

    Returns:
        Final state dict from graph.invoke().
    """
    # Append timestamp to prevent checkpoint collision on re-runs
    unique_thread_id = f"{thread_id}-{int(time.time())}"

    tracer = get_tracer()
    with tracer.start_as_current_span(f"workflow:{name}") as span:
        span.set_attribute("workflow.name", name)
        span.set_attribute("workflow.thread_id", unique_thread_id)
        # Capture trace ID for deep-link URL
        try:
            from opentelemetry import trace as otel_trace
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                set_current_trace_id(format(ctx.trace_id, "032x"))
        except Exception:
            pass
        result = graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": unique_thread_id}},
        )
        span.set_attribute("workflow.verdict", result.get("verdict", ""))
        span.set_attribute("workflow.phase", result.get("phase", ""))
    flush_traces()
    return result
