"""Tests for issue_to_pr workflow nodes."""

import json
import pytest
from unittest.mock import patch, MagicMock
from langgraph_maestro.workflows.issue_to_pr.nodes import fetch_issue_node, decompose_node, execute_node, review_node, commit_pr_node


# ---------------------------------------------------------------------------
# fetch_issue_node
# ---------------------------------------------------------------------------

class TestFetchIssueNode:
    def _make_gh_output(self, number=42, title="Fix the bug", body="Steps to reproduce..."):
        return json.dumps({"number": number, "title": title, "body": body, "labels": [], "state": "open"})

    def test_parses_valid_issue_url(self):
        with patch("langgraph_maestro.nodes.fetch_issue._run") as mock_run:
            mock_run.return_value = MagicMock(stdout=self._make_gh_output())
            result = fetch_issue_node({
                "issue_url": "https://github.com/owner/repo/issues/42",
            })

        assert result["issue_number"] == 42
        assert result["issue_title"] == "Fix the bug"
        assert "42" in result["branch_name"]
        assert result["phase"] == "fetch"
        assert "GitHub Issue #42" in result["task"]

    def test_rejects_invalid_url(self):
        result = fetch_issue_node({"issue_url": "not-a-url"})
        assert "errors" in result
        assert result["phase"] == "fetch"

    def test_handles_gh_cli_failure(self):
        import subprocess
        with patch("langgraph_maestro.nodes.fetch_issue._run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
            result = fetch_issue_node({
                "issue_url": "https://github.com/owner/repo/issues/1",
            })
        assert "errors" in result

    def test_branch_name_slugifies_title(self):
        with patch("langgraph_maestro.nodes.fetch_issue._run") as mock_run:
            mock_run.return_value = MagicMock(stdout=self._make_gh_output(
                number=7, title="Add new feature: support multi-provider routing"
            ))
            result = fetch_issue_node({
                "issue_url": "https://github.com/owner/repo/issues/7",
            })
        branch = result["branch_name"]
        assert branch.startswith("issue-7-")
        assert " " not in branch


# ---------------------------------------------------------------------------
# decompose_node
# ---------------------------------------------------------------------------

class TestDecomposeNode:
    def test_decomposes_issue_into_subtasks(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "1-fix-bug", "description": "Fix the bug in foo.py", "acceptance_criteria": "Tests pass"},
                    {"id": "2-add-test", "description": "Add regression test", "acceptance_criteria": "Coverage"},
                ],
                "strategy": "execute",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "GitHub Issue #42: Fix the bug\n\nSteps to reproduce...", "config_path": "workflows/issue_to_pr/config.yaml"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 2
        assert result["strategy"] == "execute"
        assert result["phase"] == "decompose"
        assert result["subtasks"][0]["status"] == "pending"

    def test_returns_error_on_parse_failure(self, mock_llm):
        for _ in range(4):
            mock_llm.append({"content": "garbage", "model": "mock", "latency": 0.1})

        state = {"task": "Fix bug", "config_path": "workflows/issue_to_pr/config.yaml"}
        result = decompose_node(state)

        assert "errors" in result
        assert result["phase"] == "decompose"


# ---------------------------------------------------------------------------
# execute_node
# ---------------------------------------------------------------------------

class TestExecuteNode:
    def test_executes_subtasks(self):
        agent_response = {
            "content": json.dumps({
                "status": "COMPLETE",
                "files_modified": ["foo.py"],
                "implementation_summary": "Fixed foo",
            }),
            "provider": "claude_code",
            "model": "mock",
        }

        # Mock returns [] before agent runs, ["foo.py"] after
        # Provide enough responses for 3 attempts (MAX_RETRIES=2): before,after pairs
        changed_responses = iter([[], [], [], [], [], ["foo.py"]])

        def changed_side_effect(repo_path):
            return next(changed_responses)

        with patch("langgraph_maestro.nodes.execute.call_agent", return_value=agent_response), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", side_effect=changed_side_effect), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._create_worktree", return_value="/tmp/fake-wt"), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._cleanup_worktree"):

            state = {
                "subtasks": [{"id": "1-fix", "description": "Fix foo.py", "acceptance_criteria": "Tests pass", "status": "pending", "attempts": 0}],
                "config_path": "workflows/issue_to_pr/config.yaml",
                "repo_path": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-fix" in result["completed_tasks"]
        assert result["failed_tasks"] == []
        assert result["phase"] == "execute"

    def test_retries_failed_subtask(self):
        # First two attempts: no files changed; third attempt: files changed
        # Uses before/after pattern: ([], []), ([], []), ([], ["foo.py"])
        agent_response = {"content": "", "provider": "claude_code", "model": "mock"}

        # 6 calls: before,after pairs for 3 attempts
        changed_responses = [[], [], [], [], [], ["foo.py"]]
        changed_iter = iter(changed_responses)

        def changed_side_effect(repo_path):
            return next(changed_iter)

        with patch("langgraph_maestro.nodes.execute.call_agent", return_value=agent_response), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", side_effect=changed_side_effect), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._create_worktree", return_value="/tmp/fake-wt"), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._cleanup_worktree"):

            state = {
                "subtasks": [{"id": "1-retry", "description": "Fix foo.py", "acceptance_criteria": "Tests pass", "status": "pending", "attempts": 0}],
                "config_path": "workflows/issue_to_pr/config.yaml",
                "repo_path": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-retry" in result["completed_tasks"]

    def test_marks_failed_on_exception(self):
        with patch("langgraph_maestro.nodes.execute.call_agent", side_effect=RuntimeError("agent crashed")), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", return_value=[]), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._create_worktree", return_value="/tmp/fake-wt"), \
             patch("langgraph_maestro.workflows.issue_to_pr.nodes._cleanup_worktree"):

            state = {
                "subtasks": [{"id": "1-fail", "description": "Will fail", "acceptance_criteria": "N/A", "status": "pending", "attempts": 0}],
                "config_path": "workflows/issue_to_pr/config.yaml",
                "repo_path": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-fail" in result["failed_tasks"]
        assert result["completed_tasks"] == []


# ---------------------------------------------------------------------------
# review_node
# ---------------------------------------------------------------------------

class TestReviewNode:
    def test_approves_clean_work(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({"verdict": "APPROVE", "issues": [], "summary": "Looks good"}),
            "model": "mock",
            "latency": 0.1,
        })

        state = {
            "task": "Fix bug",
            "subtasks": [{"id": "1-fix", "description": "Fixed it", "status": "complete", "result": {"status": "COMPLETE"}}],
            "config_path": "workflows/issue_to_pr/config.yaml",
        }
        result = review_node(state)

        assert result["verdict"] == "APPROVE"
        assert result["review_issues"] == []

    def test_rejects_with_issues(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "verdict": "REJECT",
                "issues": [{"severity": "HIGH", "title": "Bug found", "location": "a.py:10", "description": "Logic error", "fix": "Fix it"}],
                "summary": "Has bugs",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {
            "task": "Fix bug",
            "subtasks": [],
            "config_path": "workflows/issue_to_pr/config.yaml",
        }
        result = review_node(state)

        assert result["verdict"] == "REJECT"
        assert len(result["review_issues"]) == 1

    def test_rejects_on_parse_failure(self, mock_llm):
        mock_llm.append({"content": "not json", "model": "mock", "latency": 0.1})

        state = {"task": "Fix bug", "subtasks": [], "config_path": "workflows/issue_to_pr/config.yaml"}
        result = review_node(state)

        assert result["verdict"] == "REJECT"


# ---------------------------------------------------------------------------
# commit_pr_node
# ---------------------------------------------------------------------------

class TestCommitPRNode:
    def _make_state(self):
        return {
            "repo_path": "/fake/repo",
            "branch_name": "issue-42-fix-bug",
            "issue_number": 42,
            "issue_title": "Fix the bug",
            "issue_url": "https://github.com/owner/repo/issues/42",
            "completed_tasks": ["1-fix"],
        }

    def test_commits_and_opens_pr(self):
        with patch("langgraph_maestro.nodes.commit_pr._run") as mock_run:
            # git checkout -b → success
            # git add -A → success
            # git status --porcelain → has changes
            # git commit → success
            # git rev-parse HEAD → sha
            # git push → success
            # gh pr create → pr url
            mock_run.side_effect = [
                MagicMock(),                              # checkout -b
                MagicMock(),                              # add -A
                MagicMock(stdout="M foo.py\n"),           # status --porcelain
                MagicMock(),                              # commit
                MagicMock(stdout="abc123\n"),             # rev-parse HEAD
                MagicMock(),                              # push
                MagicMock(stdout="https://github.com/owner/repo/pull/99\n"),  # gh pr create
            ]
            result = commit_pr_node(self._make_state())

        assert result["pr_url"] == "https://github.com/owner/repo/pull/99"
        assert result["commit_sha"] == "abc123"
        assert result["phase"] == "commit_pr"

    def test_returns_error_on_nothing_to_commit(self):
        with patch("langgraph_maestro.nodes.commit_pr._run") as mock_run:
            mock_run.side_effect = [
                MagicMock(),              # checkout -b
                MagicMock(),              # add -A
                MagicMock(stdout=""),     # status --porcelain (empty = nothing staged)
            ]
            result = commit_pr_node(self._make_state())

        assert "errors" in result

    def test_handles_existing_branch(self):
        import subprocess
        with patch("langgraph_maestro.nodes.commit_pr._run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "checkout" in cmd and "-b" in cmd:
                    raise subprocess.CalledProcessError(128, cmd)
                if "status" in cmd and "--porcelain" in cmd:
                    return MagicMock(stdout="M foo.py\n")
                if "rev-parse" in cmd:
                    return MagicMock(stdout="def456\n")
                if "pr" in cmd:
                    return MagicMock(stdout="https://github.com/owner/repo/pull/100\n")
                return MagicMock(stdout="")

            mock_run.side_effect = side_effect
            result = commit_pr_node(self._make_state())

        # Should fall back to git checkout (no -b) and succeed
        assert result.get("phase") == "commit_pr"
