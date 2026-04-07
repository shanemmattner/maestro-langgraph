"""Maestro workflow state — decompose -> execute -> review pipeline."""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState, Subtask


class MaestroState(BaseWorkflowState, total=False):
    # Input
    task: str
    cwd: str  # working directory for code operations

    # Decompose output
    subtasks: list[Subtask]
    strategy: str  # execute | split
    decompose_raw: str  # raw LLM response
    subtask_warnings: list[str]  # validation warnings from validate_subtasks

    # Execute tracking
    current_wave: int
    completed_tasks: list[str]
    failed_tasks: list[str]
    execute_log: list[dict]  # per-task execution records

    # Review output
    verdict: str  # APPROVE | NITS | REJECT
    review_issues: list[dict]
    review_raw: str

    # Control flow
    stalls: list[dict]

    # Baseline checking
    baseline_failures: dict  # {test_name: error_message}
    baseline_branch: str
    baseline_errors: list[str]

    # Review loops
    review_rounds: int
    max_review_rounds: int
    replan_rounds: int

    # Verification
    verify_results: list[dict]

    # Critique phase (optional - enabled via config)
    critique_issues: list
    plan_approved: bool
    critique_rounds: int
    max_critique_rounds: int

    # Test generation (optional - enabled via config)
    generated_tests: list

    # Escalation (optional - enabled via config)
    needs_human_input: bool
    escalation_questions: list
