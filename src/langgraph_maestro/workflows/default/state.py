"""Default workflow state — the canonical embodiment of all 10 principles.

Extends BaseWorkflowState with fields for research, context engineering,
per-piece execution/review, adversarial review, verification, and
after-action review.
"""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState, Subtask


class DefaultState(BaseWorkflowState, total=False):
    # ── Input ──
    task: str                          # User's task description
    cwd: str                           # Working directory for code operations

    # ── Analysis (Principle 1: Start Simple — understand before acting) ──
    task_type: str                     # code_change | research | analysis | writing
    success_criteria: list[str]        # Measurable definitions of done
    ambiguities: list[str]             # Unclear aspects of the task
    search_queries: list[str]          # Suggested web searches for context

    # ── Research & Context (Principles 4, 6: Cite Sources, Context Engineering) ──
    domain_research: list[dict]        # [{query, sources: [{url, title, excerpt}]}]
    domain_context: str                # Synthesized domain knowledge for downstream prompts
    available_tools: list[dict]        # [{name, description, path, deterministic: bool}]
    tool_recommendations: dict         # {phase: [tool_name]} — curated tools per phase
    ground_truth: str                  # User-provided or LLM-generated reference output

    # ── Decompose ──
    subtasks: list[Subtask]
    strategy: str                      # execute | split | refine | blocked
    decompose_raw: str
    subtask_warnings: list[str]

    # ── Per-Piece Execution (inner loop) ──
    current_subtask_index: int         # Which subtask is being worked on
    completed_tasks: list[str]
    failed_tasks: list[str]
    execute_log: list[dict]            # Per-task execution records

    # ── Per-Piece Review ──
    piece_verdict: str                 # APPROVE | NITS | REJECT for current piece
    piece_review_issues: list[dict]
    piece_review_rounds: int           # Retry counter for current piece

    # ── Holistic Review (Principle 7: Adversarial Review) ──
    holistic_verdict: str              # APPROVE | REJECT
    holistic_issues: list[dict]        # Cross-piece integration problems
    holistic_review_rounds: int

    # ── Adversarial Review (Principle 7: Adversarial Review) ──
    adversarial_verdict: str           # PASS | FAIL
    adversarial_findings: list[dict]   # [{finding, severity, evidence}]
    adversarial_rounds: int

    # ── Verification (Principle 3: Closed-Loop Quality) ──
    verification_results: list[dict]   # [{criterion, passed, evidence, method}]
    verification_verdict: str          # PASS | PARTIAL | FAIL

    # ── After-Action Review (Principle 8: Self-Improving Workflows) ──
    aar_improvements: list[dict]       # [{finding, action, tool_candidate: bool}]
    aar_tool_proposals: list[dict]     # [{name, description, implementation_sketch}]

    # ── Control Flow ──
    stalls: list[dict]
    review_rounds: int                 # Global review loop counter
    max_review_rounds: int
    replan_rounds: int
    early_stop_reason: str             # Why the workflow stopped early
    needs_human_input: bool
    escalation_questions: list[str]

    # ── Legacy compatibility ──
    verdict: str                       # Overall final verdict
    review_issues: list[dict]
    review_raw: str
    baseline_failures: dict
    baseline_branch: str
    baseline_errors: list[str]
    critique_issues: list
    plan_approved: bool
    critique_rounds: int
    max_critique_rounds: int
    generated_tests: list
    current_wave: int
    verify_results: list[dict]


# Backwards-compatible alias — existing code imports MaestroState
MaestroState = DefaultState
