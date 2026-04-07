"""Customize workflow state definition."""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState


class CustomizeState(BaseWorkflowState, total=False):
    """State for the interview-driven customize workflow."""

    # Input
    target_dir: str
    source_workflow: str

    # Interview
    interview_history: list[dict]
    current_round: int
    current_questions: list[dict]
    gathered_context: dict
    confidence: float

    # Synthesis
    domain_profile: dict
    workflow_spec: dict

    # Generation
    generated_files: dict
    validation_errors: list[str]
    validation_attempts: int

    # Output
    output_dir: str
    final_summary: str
