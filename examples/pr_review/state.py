"""PR Review workflow state."""

import operator
from typing import Annotated, TypedDict


class Issue(TypedDict, total=False):
    file: str
    line: int
    title: str
    description: str
    severity: str
    category: str


class PRReviewState(TypedDict, total=False):
    # ── Base ──
    phase: str
    errors: list
    # Input
    pr_url: str
    repo_path: str

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
    reviewers: list[str]
    current_persona: str
    reviewer_results: Annotated[list[dict], operator.add]

    # Synthesize output
    verdict: str
    review_summary: str
    review_comments: list[dict]

    # Escalation state
    escalated: bool
    escalation_verdict: str
    escalation_summary: str
