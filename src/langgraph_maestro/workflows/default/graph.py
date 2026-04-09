"""Default workflow graph — 11-node config-driven conditional wiring.

Implements the full Maestro workflow with research, context engineering,
per-piece execution with inner-loop review, holistic review, adversarial
review, verification, and after-action review.

Flow:
  START -> analyze_task -> research -> build_context -> decompose -> validate_plan ->
    INNER LOOP: plan_piece -> execute_piece -> piece_review ->
      (APPROVE + more -> plan_piece, APPROVE + done -> holistic_review,
       REJECT + budget -> execute_piece, REJECT + exhausted -> escalate)
    -> holistic_review ->
      (APPROVE -> adversarial_review, REJECT + budget -> decompose, REJECT + exhausted -> escalate)
    -> adversarial_review ->
      (PASS -> verify, FAIL + budget -> plan_piece, FAIL + exhausted -> escalate)
    -> verify ->
      (PASS -> after_action_review, FAIL -> escalate)
    -> after_action_review -> END
    escalate -> END
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from langgraph_maestro.core.validation import validate_subtasks
from .state import DefaultState, MaestroState
from .nodes import (
    analyze_task_node, research_node, build_context_node,
    decompose_node, validate_plan_node,
    plan_piece_node, execute_piece_node, piece_review_node,
    holistic_review_node, adversarial_review_node,
    verify_node, after_action_review_node, escalate_node,
)

logger = logging.getLogger(__name__)

# Load config at module level for route functions
_config = load_config(workflow_config_path(__file__))
_loops_config = _config.get("loops", {})


# ── Routing functions ────────────────────────────────────────────────────────


def route_after_decompose(state: DefaultState) -> str:
    """Route after decompose: blocked -> escalate, otherwise -> validate_plan."""
    strategy = state.get("strategy", "execute")
    if strategy == "blocked":
        logger.warning("decompose_blocked", extra={"strategy": strategy})
        return "escalate"
    return "validate_plan"


def route_after_validate(state: DefaultState) -> str:
    """Route after validate_plan: critical warnings -> replan, budget exhausted -> escalate, else -> plan_piece."""
    warnings = state.get("subtask_warnings", [])
    replan_rounds = state.get("replan_rounds", 0)
    max_replan = _loops_config.get("max_replan_rounds", 1)

    # Check for critical warnings (DUPLICATE severity)
    has_critical = any("Duplicate" in w for w in warnings)
    if has_critical:
        if replan_rounds < max_replan:
            logger.info("validate_replan", extra={"replan_rounds": replan_rounds})
            return "decompose"
        logger.warning("validate_replan_exhausted", extra={"replan_rounds": replan_rounds})
        return "escalate"

    return "plan_piece"


def route_after_piece_review(state: DefaultState) -> str:
    """Route after piece_review: approve/reject with budget tracking.

    - APPROVE + more subtasks -> plan_piece
    - APPROVE + all done -> holistic_review
    - NITS + budget -> execute_piece (retry with feedback)
    - REJECT + budget -> execute_piece (retry with feedback)
    - REJECT + exhausted -> escalate
    """
    verdict = state.get("piece_verdict", "APPROVE")
    current_index = state.get("current_subtask_index", 0)
    subtasks = state.get("subtasks", [])
    piece_review_rounds = state.get("piece_review_rounds", 0)
    max_piece_retries = _loops_config.get("max_piece_retries", 2)

    if verdict == "APPROVE":
        # Check if there are more subtasks
        if current_index + 1 < len(subtasks):
            return "plan_piece"
        return "holistic_review"

    if verdict == "NITS":
        if piece_review_rounds < max_piece_retries:
            return "execute_piece"
        # Treat exhausted NITS as good enough — move forward
        if current_index + 1 < len(subtasks):
            return "plan_piece"
        return "holistic_review"

    # REJECT
    if piece_review_rounds < max_piece_retries:
        return "execute_piece"

    logger.warning("piece_review_retries_exhausted", extra={
        "index": current_index, "rounds": piece_review_rounds,
    })
    return "escalate"


def route_after_holistic(state: DefaultState) -> str:
    """Route after holistic_review: approve -> adversarial, reject -> replan or escalate."""
    verdict = state.get("holistic_verdict", "APPROVE")
    if verdict == "APPROVE":
        return "adversarial_review"

    holistic_rounds = state.get("holistic_review_rounds", 0)
    max_holistic = _loops_config.get("max_holistic_rounds", 1)
    if holistic_rounds < max_holistic:
        logger.info("holistic_replan", extra={"rounds": holistic_rounds})
        return "decompose"

    logger.warning("holistic_replan_exhausted", extra={"rounds": holistic_rounds})
    return "escalate"


def route_after_adversarial(state: DefaultState) -> str:
    """Route after adversarial_review: pass -> verify, fail -> re-enter inner loop or escalate."""
    verdict = state.get("adversarial_verdict", "PASS")
    if verdict == "PASS":
        return "verify"

    adversarial_rounds = state.get("adversarial_rounds", 0)
    max_adversarial = _loops_config.get("max_adversarial_rounds", 1)
    if adversarial_rounds < max_adversarial:
        logger.info("adversarial_retry", extra={"rounds": adversarial_rounds})
        return "plan_piece"

    logger.warning("adversarial_retries_exhausted", extra={"rounds": adversarial_rounds})
    return "escalate"


def route_after_verify(state: DefaultState) -> str:
    """Route after verify: pass/partial -> after_action_review, fail -> escalate."""
    verdict = state.get("verification_verdict", "PASS")
    if verdict in ("PASS", "PARTIAL"):
        return "after_action_review"
    return "escalate"


# ── Validation wrapper node ─────────────────────────────────────────────────


def validate_plan_wrapper(state: DefaultState) -> dict:
    """Validate subtasks before execution — quality gate."""
    subtasks = state.get("subtasks", [])
    result = validate_subtasks(subtasks)
    warning_messages = [w["message"] for w in result["warnings"]]
    return {
        "subtask_warnings": warning_messages,
        "phase": result["phase"],
    }


# ── Graph construction ───────────────────────────────────────────────────────


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build the 11-node default workflow graph with config-driven loop limits.

    Flow: analyze_task -> research -> build_context -> decompose -> validate_plan ->
          plan_piece <-> execute_piece <-> piece_review ->
          holistic_review -> adversarial_review -> verify -> after_action_review -> END

    Returns compiled StateGraph with checkpointer.
    """
    logger.info("graph_compile_start")

    config = load_config(config_path)

    # Read loop limits from config
    loops = config.get("loops", {})

    graph = StateGraph(DefaultState)

    # ── Add all nodes ──
    graph.add_node("analyze_task", analyze_task_node)
    graph.add_node("research", research_node)
    graph.add_node("build_context", build_context_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("validate_plan", validate_plan_wrapper)
    graph.add_node("plan_piece", plan_piece_node)
    graph.add_node("execute_piece", execute_piece_node)
    graph.add_node("piece_review", piece_review_node)
    graph.add_node("holistic_review", holistic_review_node)
    graph.add_node("adversarial_review", adversarial_review_node)
    graph.add_node("verify", verify_node)
    graph.add_node("after_action_review", after_action_review_node)
    graph.add_node("escalate", escalate_node)

    # ── Entry point ──
    graph.set_entry_point("analyze_task")

    # ── Static edges: linear pipeline ──
    graph.add_edge("analyze_task", "research")
    graph.add_edge("research", "build_context")
    graph.add_edge("build_context", "decompose")

    # ── Conditional: decompose -> validate_plan or escalate ──
    graph.add_conditional_edges("decompose", route_after_decompose)

    # ── Conditional: validate_plan -> plan_piece, decompose, or escalate ──
    graph.add_conditional_edges("validate_plan", route_after_validate)

    # ── Inner loop: plan_piece -> execute_piece -> piece_review ──
    graph.add_edge("plan_piece", "execute_piece")
    graph.add_edge("execute_piece", "piece_review")

    # ── Conditional: piece_review -> plan_piece, holistic_review, execute_piece, or escalate ──
    graph.add_conditional_edges("piece_review", route_after_piece_review)

    # ── Conditional: holistic_review -> adversarial_review, decompose, or escalate ──
    graph.add_conditional_edges("holistic_review", route_after_holistic)

    # ── Conditional: adversarial_review -> verify, plan_piece, or escalate ──
    graph.add_conditional_edges("adversarial_review", route_after_adversarial)

    # ── Conditional: verify -> after_action_review or escalate ──
    graph.add_conditional_edges("verify", route_after_verify)

    # ── Terminal edges ──
    graph.add_edge("after_action_review", END)
    graph.add_edge("escalate", END)

    compiled = graph.compile(checkpointer=get_checkpointer())
    logger.info("graph_compile_done")
    return compiled


def run_workflow(
    task: str,
    config_path: str = workflow_config_path(__file__),
    cwd: str | None = None,
) -> dict:
    """Run the default workflow end-to-end.

    Args:
        task: The task/problem description.
        config_path: Path to the workflow config YAML.
        cwd: Working directory for code operations.

    Returns:
        Final state dict with verdict, subtasks, and execution log.
    """
    graph = build_graph(config_path)
    initial_state = {"task": task, "config_path": config_path}
    if cwd:
        initial_state["cwd"] = cwd
    thread_id = f"default-{hash(task) & 0xFFFFFFFF:08x}"
    return _run_workflow("default", graph, initial_state, thread_id)
