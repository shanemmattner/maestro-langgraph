"""PR Review workflow state — fetch_pr -> analyze -> synthesize."""

import operator
from typing import Annotated, TypedDict

from langgraph_maestro.core.state import BaseWorkflowState


class Issue(TypedDict, total=False):
    file: str
    line: int
    title: str
    description: str
    severity: str  # HIGH | MEDIUM | LOW
    category: str


class PRReviewState(BaseWorkflowState, total=False):
    # Input
    pr_url: str
    repo_path: str  # local path to the repo for context

    # Fetch PR output
    pr_number: int
    pr_title: str
    pr_body: str
    pr_author: str
    base_branch: str
    head_branch: str
    pr_diff: str
    changed_files: list[str]

    # Analyze output
    findings: list[str]
    issues: list[Issue]
    analysis_summary: str

    # Reviewer fan-out state
    reviewers: list[str]  # List of reviewer personas from config
    current_persona: str  # Current persona being reviewed (fan-out)
    reviewer_results: Annotated[list[dict], operator.add]  # Individual reviewer outputs

    # Synthesize output
    verdict: str  # APPROVE | NITS | REQUEST_CHANGES
    review_summary: str
    review_comments: list[dict]

    # Escalation state
    escalated: bool  # True if review was escalated to stronger model
    escalation_verdict: str  # Final verdict after escalation
    escalation_summary: str  # Final summary after escalation
