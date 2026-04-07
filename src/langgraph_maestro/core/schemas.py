"""Shared Pydantic schemas for workflow decompose outputs.

Each schema corresponds to the JSON structure returned by a workflow's
decompose node.  Using Pydantic ensures that the LLM response is fully
validated at parse time rather than failing silently at runtime.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

class SubtaskSchema(BaseModel):
    """A single unit of work produced by a decompose node."""

    id: str = Field(..., description="Unique kebab-case identifier, e.g. '1-add-feature'")
    description: str = Field(..., description="Human-readable description of the work")
    acceptance_criteria: str = Field(
        "", description="Definition of done / acceptance criteria"
    )
    files_to_modify: List[str] = Field(
        default_factory=list, description="Paths of existing files to modify"
    )
    files_to_create: List[str] = Field(
        default_factory=list, description="Paths of new files to create"
    )
    evidence: List[str] = Field(
        default_factory=list, description="Evidence from repo context supporting this subtask"
    )
    confidence: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = None

    @field_validator("id", mode="before")
    @classmethod
    def id_must_be_non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("Subtask id must not be empty")
        return str(v).strip()


# ---------------------------------------------------------------------------
# Workflow-specific decompose outputs
# ---------------------------------------------------------------------------

class DecomposeOutput(BaseModel):
    """Validated output of a workflow decompose node."""

    subtasks: List[SubtaskSchema] = Field(
        ..., min_length=1, description="Ordered list of subtasks to execute"
    )
    strategy: Literal["execute", "split", "refine", "blocked"] = Field(
        "execute", description="Execution strategy"
    )
    blocked_reason: Optional[str] = Field(
        None, description="Reason the plan cannot proceed (when strategy is blocked)"
    )

    @field_validator("subtasks")
    @classmethod
    def subtasks_must_be_non_empty(cls, v: List[SubtaskSchema]) -> List[SubtaskSchema]:
        if not v:
            raise ValueError("subtasks list must contain at least one item")
        return v


# Backwards-compatible aliases
MaestroDecomposeOutput = DecomposeOutput
IssueToPRDecomposeOutput = DecomposeOutput


class IssueRequirementSchema(BaseModel):
    id: str = Field(..., description="Requirement ID, e.g. R1, R2")
    text: str = Field(..., description="What must be done")
    kind: Literal["hard", "soft", "test", "operational", "non_goal"] = Field("hard")
    priority: Literal["HIGH", "MEDIUM", "LOW"] = Field("HIGH")
    file_hints: List[str] = Field(
        default_factory=list, description="Files mentioned or implied"
    )
    line_hints: List[str] = Field(
        default_factory=list, description="Line ranges if mentioned"
    )
    verification_hint: str = Field(
        "", description="How to verify this requirement is met"
    )


class IssueAnalysisOutput(BaseModel):
    requirements: List[IssueRequirementSchema] = Field(..., min_length=1)
    summary: str = Field(
        ..., description="One-paragraph summary of what the issue asks for"
    )
    test_expectations: List[str] = Field(default_factory=list)
    operational_notes: List[str] = Field(default_factory=list)
