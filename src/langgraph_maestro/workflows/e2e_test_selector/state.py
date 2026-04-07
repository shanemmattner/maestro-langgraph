"""E2E test selector workflow state."""

from typing import TypedDict


class PhaseTimings(TypedDict, total=False):
    setup_s: float
    execute_s: float
    assert_s: float
    cleanup_s: float
    total_s: float


class TestResult(TypedDict, total=False):
    test_name: str
    passed: bool
    details: str
    checks: list[dict]
    response_time_s: float
    phase_timings: PhaseTimings
    error: str


class E2ETestSelectorState(TypedDict, total=False):
    """State for the E2E test selector workflow."""

    # Inputs
    pr_diff: str
    pr_number: str
    pr_url: str  # full GitHub PR URL for commenting
    repo_path: str
    config_path: str

    # Analysis phase
    changed_files: list[str]
    change_summary: str

    # Discovery phase
    available_tests: list[dict]  # [{name, description}]

    # Selection phase
    selected_tests: list[str]  # test names chosen by LLM
    selection_reasoning: str

    # Execution phase
    test_results: list[TestResult]

    # Report phase
    report: str
    overall_passed: bool
    results_file: str  # path to saved JSON results
    pr_comment_posted: bool  # whether GH comment was posted
    discord_notified: bool  # whether Discord was notified

    # Metadata
    phase: str
