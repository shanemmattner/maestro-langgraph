"""Adaptive workflow state — minimal TypedDict, no Pydantic."""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState


class AdaptiveState(BaseWorkflowState, total=False):
    # ── Input ──
    task: str                      # The original request
    cwd: str                       # Working directory

    # ── Think ──
    context: str                   # Gathered context from THINK phase

    # ── Plan ──
    plan: str                      # The plan text from PLAN phase
    pieces: list                   # list of dicts: {id, description, acceptance_criteria, status}

    # ── Adversarial Review ──
    adversarial_feedback: str      # What the reviewer said
    plan_approved: bool            # Whether adversarial review approved
    replan_rounds: int             # How many times we've replanned (max 2)

    # ── Act + Verify ──
    current_piece_index: int       # Which piece we're executing
    piece_results: list            # list of dicts: {piece_id, result, files_changed, verified}
    piece_retries: int             # Retries for current piece (max 2)

    # ── Output ──
    summary: str                   # Final summary
