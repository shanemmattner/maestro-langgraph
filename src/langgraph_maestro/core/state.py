"""Base workflow state shared by all workflows."""

from typing import TypedDict


class Subtask(TypedDict, total=False):
    id: str
    description: str
    files_to_modify: list[str]
    acceptance_criteria: str
    confidence: str  # HIGH | MEDIUM | LOW
    status: str  # pending | complete | failed
    result: dict  # implementer output
    attempts: int


class BaseWorkflowState(TypedDict, total=False):
    config_path: str
    phase: str
    errors: list[str]
    thread_id: str
    started_at: str
