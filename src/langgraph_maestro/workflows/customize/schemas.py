"""Pydantic schemas for the customize workflow.

These schemas define the structured outputs for the interview-driven
customization flow: gathering context via questions, synthesizing answers
into a domain profile, and generating a workflow specification.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Interview phase
# ---------------------------------------------------------------------------

class InterviewQuestion(BaseModel):
    id: str
    category: Literal["domain", "codebase", "testing", "models", "quality", "workflow"]
    question: str
    why: str  # Helps user understand why this matters
    examples: list[str] = Field(default_factory=list)


class InterviewQuestions(BaseModel):
    questions: list[InterviewQuestion]
    reasoning: str
    estimated_completeness: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Answer synthesis
# ---------------------------------------------------------------------------

class AnswerSynthesis(BaseModel):
    """Structured extraction from freeform user answers."""

    domain_updates: dict = Field(default_factory=dict)
    codebase_updates: dict = Field(default_factory=dict)
    testing_updates: dict = Field(default_factory=dict)
    models_updates: dict = Field(default_factory=dict)
    quality_updates: dict = Field(default_factory=dict)
    workflow_updates: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflow specification
# ---------------------------------------------------------------------------

class PhaseSpec(BaseModel):
    name: str
    enabled: bool = True
    models: list[str] = Field(default_factory=lambda: ["claude-sonnet-4-6"])


class ConfigSpec(BaseModel):
    max_review_rounds: int = 2
    escalation_enabled: bool = False
    timeouts: dict[str, int] = Field(default_factory=lambda: {"default": 300})


class WorkflowSpec(BaseModel):
    workflow_name: str
    description: str = ""
    phases: list[PhaseSpec]
    config: ConfigSpec = Field(default_factory=ConfigSpec)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
