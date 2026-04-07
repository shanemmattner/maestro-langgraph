"""Customize workflow graph — multi-round interview loop."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes import (
    collect_answers_node,
    generate_node,
    interview_node,
    synthesize_node,
    validate_node,
    write_output_node,
)
from .state import CustomizeState


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

_ALL_CATEGORIES = ("domain", "codebase", "testing", "models", "quality", "workflow")


def _route_after_collect(state: CustomizeState) -> str:
    """Decide whether to loop back to interview or proceed to synthesize.

    Proceeds when:
      - confidence >= 0.85 AND all 6 categories have data, OR
      - current_round >= 10 (hard cap).
    """
    confidence = state.get("confidence", 0.0)
    current_round = state.get("current_round", 0)
    gathered_context = state.get("gathered_context", {})

    if current_round >= 10:
        return "synthesize"

    covered = set()
    for cat in _ALL_CATEGORIES:
        val = gathered_context.get(cat)
        if isinstance(val, dict) and len(val) > 0:
            covered.add(cat)

    if confidence >= 0.85 and len(covered) >= len(_ALL_CATEGORIES):
        return "synthesize"

    return "interview"


def _route_after_validate(state: CustomizeState) -> str:
    """Decide whether to regenerate or write output.

    Clean or max retries reached -> write_output.
    Errors and retries remaining -> generate (retry).
    """
    errors = state.get("validation_errors", [])
    attempts = state.get("validation_attempts", 0)

    if not errors:
        return "write_output"
    if attempts >= 2:
        return "write_output"
    return "generate"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> Any:
    """Build and compile the customize workflow graph.

    Topology::

        START -> interview -> collect_answers -> route_after_collect
                                                   |             |
                                             (not enough)    (enough)
                                                   |             |
                                              interview     synthesize -> generate -> validate -> route_after_validate
                                                                                                    |            |
                                                                                                (errors)     (clean)
                                                                                                    |            |
                                                                                                generate    write_output -> END
    """
    graph = StateGraph(CustomizeState)

    # Nodes
    graph.add_node("interview", interview_node)
    graph.add_node("collect_answers", collect_answers_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("write_output", write_output_node)

    # Edges
    graph.set_entry_point("interview")
    graph.add_edge("interview", "collect_answers")

    graph.add_conditional_edges(
        "collect_answers",
        _route_after_collect,
        {"interview": "interview", "synthesize": "synthesize"},
    )

    graph.add_edge("synthesize", "generate")
    graph.add_edge("generate", "validate")

    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"generate": "generate", "write_output": "write_output"},
    )

    graph.add_edge("write_output", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

async def run_workflow(
    initial_state: dict[str, Any] | None = None,
    model: str = "claude-sonnet-4-6",
) -> dict[str, Any]:
    """Build and invoke the customize workflow.

    Args:
        initial_state: Optional pre-populated state dict.  At minimum should
            contain ``target_dir``.  Missing keys get sensible defaults.
        model: Default model (currently informational; models come from config).

    Returns:
        The final workflow state.
    """
    compiled = build_graph()

    defaults: dict[str, Any] = {
        "target_dir": "",
        "source_workflow": "",
        "interview_history": [],
        "current_round": 0,
        "current_questions": [],
        "gathered_context": {},
        "confidence": 0.0,
        "domain_profile": {},
        "workflow_spec": {},
        "generated_files": {},
        "validation_errors": [],
        "validation_attempts": 0,
        "output_dir": "",
        "final_summary": "",
    }

    state = {**defaults, **(initial_state or {})}
    result = await compiled.ainvoke(state)
    return result
