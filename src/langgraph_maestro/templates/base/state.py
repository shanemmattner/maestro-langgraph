"""WORKFLOW_NAME workflow state."""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState, Subtask


class WorkflowState(BaseWorkflowState, total=False):
    # Input
    task: str
    cwd: str  # working directory for code operations

    # Decompose output
    subtasks: list[Subtask]
    strategy: str  # execute | split
    decompose_raw: str

    # Execute tracking
    current_wave: int
    completed_tasks: list[str]
    failed_tasks: list[str]
    execute_log: list[dict]

    # Review output
    verdict: str  # APPROVE | NITS | REJECT
    review_issues: list[dict]
    review_raw: str

    # Review loops
    review_rounds: int
    max_review_rounds: int
