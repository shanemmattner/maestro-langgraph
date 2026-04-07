"""E2E Test workflow state definition."""

from typing import TypedDict


class E2ETestState(TypedDict, total=False):
    """State for the E2E Test workflow.
    
    Flow: analyze -> design -> generate -> execute -> evaluate -> report
    With retry edge from evaluate back to generate (up to 3 retries).
    """
    
    # Input fields (as per task spec)
    diff_file: str          # Path to diff file or PR diff
    pr_number: str         # PR number
    cwd: str               # Working directory
    config_path: str
    
    # Analysis phase output
    changed_paths: list[str]  # List of changed file paths
    code_paths: list[dict]   # List of changed code paths with metadata
    
    # Design phase output
    test_specs: list[dict]   # List of test designs/specs
    
    # Generation phase output
    generated_test_file: str  # Path to generated test file
    
    # Execution phase output
    test_runner: str          # pytest, unittest, jest, etc.
    execution_results: list[dict]  # Results of test execution
    
    # Evaluation phase output (flattened from evaluation_result)
    verdict: str          # PASS, FAIL, RETRY
    passed: int           # Number of passed tests
    failed: int           # Number of failed tests
    total: int            # Total number of tests
    should_retry: bool    # Whether to retry
    issues: list[str]     # List of issues found
    
    # Report phase output
    report: str  # Markdown report
    
    # Retry tracking
    retry_count: int
    max_retries: int
    
    # Current phase for tracing
    phase: str
