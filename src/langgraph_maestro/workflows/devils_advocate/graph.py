"""Devil's Advocate workflow graph — adversarial design review.

Flow: START -> research_counter_evidence -> find_alternatives -> build_critique
      -> defend_proposal -> judge_verdict -> write_report -> END
"""

import logging
import time

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph_maestro.core.config import load_config, workflow_config_path
from .state import DevilsAdvocateState
from .nodes import (
    research_counter_evidence_node,
    find_alternatives_node,
    build_critique_node,
    defend_proposal_node,
    judge_verdict_node,
    write_report_node,
)

logger = logging.getLogger(__name__)


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build and compile the devils_advocate LangGraph workflow."""
    logger.info("graph_compile_start")

    graph = StateGraph(DevilsAdvocateState)

    graph.add_node("research_counter_evidence", research_counter_evidence_node)
    graph.add_node("find_alternatives", find_alternatives_node)
    graph.add_node("build_critique", build_critique_node)
    graph.add_node("defend_proposal", defend_proposal_node)
    graph.add_node("judge_verdict", judge_verdict_node)
    graph.add_node("write_report", write_report_node)

    graph.set_entry_point("research_counter_evidence")
    graph.add_edge("research_counter_evidence", "find_alternatives")
    graph.add_edge("find_alternatives", "build_critique")
    graph.add_edge("build_critique", "defend_proposal")
    graph.add_edge("defend_proposal", "judge_verdict")
    graph.add_edge("judge_verdict", "write_report")
    graph.add_edge("write_report", END)

    compiled = graph.compile(checkpointer=MemorySaver())
    logger.info("graph_compile_done")
    return compiled


def run_workflow(
    proposal: str,
    proposal_type: str = "pricing",
    context_path: str | None = None,
    config_path: str = workflow_config_path(__file__),
) -> dict:
    """Run the devils_advocate workflow end-to-end.

    Args:
        proposal: The proposal to stress-test.
        proposal_type: One of pricing/architecture/positioning/features/go-to-market.
        context_path: Optional path to docs for additional context.
        config_path: Path to the workflow config YAML.

    Returns:
        Final state dict with verdict, confidence_score, critique, defense, report_path.
    """
    start = time.time()
    logger.info("workflow_start", extra={"proposal": proposal[:80], "type": proposal_type})

    lf_trace_id = None
    try:
        from langgraph_maestro.core.tracing import is_langfuse_available, langfuse_create_trace
        if is_langfuse_available():
            lf_trace_id = langfuse_create_trace(
                "devils_advocate_workflow", input_data={"proposal": proposal, "type": proposal_type}
            )
    except Exception:
        pass

    graph = build_graph(config_path)

    initial_state = {
        "proposal": proposal,
        "proposal_type": proposal_type,
        "config_path": config_path,
    }
    if context_path:
        initial_state["context_path"] = context_path

    # Create a thread ID from the proposal for checkpointing
    thread_slug = proposal[:30].lower().replace(" ", "-")
    result = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": f"devils-advocate-{thread_slug}"}},
    )

    elapsed = round(time.time() - start, 3)
    logger.info(
        "workflow_done",
        extra={
            "verdict": result.get("verdict"),
            "confidence": result.get("confidence_score"),
            "report_path": result.get("report_path"),
            "elapsed": elapsed,
        },
    )

    if lf_trace_id is not None:
        try:
            from langgraph_maestro.core.tracing import langfuse_update_trace
            langfuse_update_trace(
                lf_trace_id,
                output={"verdict": result.get("verdict"), "confidence": result.get("confidence_score")},
                metadata={"elapsed": elapsed},
            )
        except Exception:
            pass

    return result
