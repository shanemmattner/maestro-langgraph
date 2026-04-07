"""Issue-to-PR workflow state — fetch -> decompose -> execute -> review -> commit_pr."""

from typing import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState, Subtask


class IssueToPRState(BaseWorkflowState, total=False):
    # Input
    issue_url: str
    repo_path: str  # local path to the repo to modify

    # Fetch output
    issue_number: int
    issue_title: str
    issue_body: str
    branch_name: str
    task: str  # synthesized from issue title + body

    # Decompose output
    subtasks: list[Subtask]
    strategy: str  # execute | split

    # Execute tracking
    completed_tasks: list[str]
    failed_tasks: list[str]
    execute_log: list[dict]

    # Review output
    verdict: str  # APPROVE | NITS | REJECT
    review_issues: list[dict]

    # Commit/PR output
    pr_url: str
    commit_sha: str

    # Worktree isolation
    worktree_path: str  # git worktree for isolated execution

    # Control flow
    stalls: list[dict]
