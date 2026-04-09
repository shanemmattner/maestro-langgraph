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


# ---------------------------------------------------------------------------
# Redesigned default workflow schemas
# ---------------------------------------------------------------------------

class TaskAnalysisOutput(BaseModel):
    """Output of the analyze_task node — understand what the user is asking."""
    task_type: Literal["code_change", "research", "analysis", "writing"] = Field(
        ..., description="Classification of the task type"
    )
    success_criteria: List[str] = Field(
        ..., min_length=1, description="Measurable definitions of done"
    )
    ambiguities: List[str] = Field(
        default_factory=list, description="Things that are unclear about the task"
    )
    search_queries: List[str] = Field(
        default_factory=list, description="Suggested web searches for domain context"
    )
    relevant_file_patterns: List[str] = Field(
        default_factory=list, description="Glob patterns for relevant files (if code task)"
    )


class ContextEngineeringOutput(BaseModel):
    """Output of the build_context node — synthesized domain knowledge."""
    domain_summary: str = Field(
        ..., description="2-3 paragraphs of synthesized domain knowledge from research"
    )
    key_constraints: List[str] = Field(
        default_factory=list, description="Hard constraints discovered from research"
    )
    recommended_approach: str = Field(
        ..., description="Evidence-backed approach with citations"
    )
    citations: List[dict] = Field(
        default_factory=list, description="List of {claim, source_url, source_title}"
    )
    tool_assignments: dict = Field(
        default_factory=dict, description="Phase-to-tool mapping: {phase_name: [tool_name]}"
    )


class PieceReviewOutput(BaseModel):
    """Output of per-piece review — focused correctness check."""
    verdict: Literal["APPROVE", "NITS", "REJECT"] = Field(
        ..., description="Verdict on this specific piece"
    )
    issues: List[dict] = Field(
        default_factory=list, description="Issues found: [{title, description, severity, fix}]"
    )
    criteria_met: List[str] = Field(
        default_factory=list, description="Which acceptance criteria are satisfied"
    )
    criteria_unmet: List[str] = Field(
        default_factory=list, description="Which acceptance criteria are NOT satisfied"
    )


class HolisticReviewOutput(BaseModel):
    """Output of holistic review — do all pieces fit together?"""
    verdict: Literal["APPROVE", "REJECT"] = Field(
        ..., description="Overall integration verdict"
    )
    integration_issues: List[dict] = Field(
        default_factory=list, description="Cross-piece problems: [{description, affected_subtasks, severity}]"
    )
    coverage_gaps: List[str] = Field(
        default_factory=list, description="Success criteria not fully addressed"
    )
    consistency_issues: List[str] = Field(
        default_factory=list, description="Contradictions between pieces"
    )


class AdversarialFinding(BaseModel):
    """A single finding from adversarial review."""
    finding: str = Field(..., description="What is wrong")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(
        ..., description="How bad is it"
    )
    evidence: str = Field(..., description="Why it's wrong — cite sources or edge cases")
    is_hallucination: bool = Field(
        False, description="Is this a hallucinated claim?"
    )


class AdversarialReviewOutput(BaseModel):
    """Output of adversarial review — hostile technical challenge."""
    verdict: Literal["PASS", "FAIL"] = Field(
        ..., description="Did the work survive adversarial challenge?"
    )
    findings: List[AdversarialFinding] = Field(
        default_factory=list, description="Issues found by the adversarial reviewer"
    )
    summary: str = Field(
        ..., description="One-paragraph summary of adversarial findings"
    )


class VerificationResult(BaseModel):
    """Result of verifying a single success criterion."""
    criterion: str = Field(..., description="The success criterion being verified")
    passed: bool = Field(..., description="Whether the criterion is satisfied")
    evidence: str = Field(..., description="Evidence for the verdict")
    method: Literal["test_execution", "ground_truth_comparison", "llm_assessment"] = Field(
        ..., description="How this was verified — higher is more trustworthy"
    )


class VerificationOutput(BaseModel):
    """Output of the verify node — concrete verification against success criteria."""
    verdict: Literal["PASS", "PARTIAL", "FAIL"] = Field(
        ..., description="Overall verification verdict"
    )
    results: List[VerificationResult] = Field(
        ..., min_length=1, description="Per-criterion verification results"
    )
    summary: str = Field(
        ..., description="One-paragraph summary of verification"
    )


class AAROutput(BaseModel):
    """Output of after-action review — self-improvement engine."""
    what_worked: List[str] = Field(
        default_factory=list, description="Things that went well"
    )
    what_failed: List[str] = Field(
        default_factory=list, description="Things that went wrong"
    )
    context_gaps: List[str] = Field(
        default_factory=list, description="What the agents didn't know"
    )
    tool_opportunities: List[dict] = Field(
        default_factory=list, description="LLM calls that could become deterministic tools"
    )
    prompt_improvements: List[dict] = Field(
        default_factory=list, description="Specific prompt changes for next run"
    )
    workflow_improvements: List[str] = Field(
        default_factory=list, description="Structural changes to the graph"
    )
