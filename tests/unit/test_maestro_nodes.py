"""Tests for maestro workflow nodes."""

import json
import pytest
from unittest.mock import patch
from langgraph_maestro.workflows.default.nodes import decompose_node
from langgraph_maestro.nodes.execute import make_execute_node
from langgraph_maestro.nodes.review import make_review_node
from langgraph_maestro.core.config import workflow_config_path
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "langgraph_maestro" / "workflows" / "default"
_CONFIG = str(_DEFAULT_DIR / "config.yaml")
_PROMPTS = str(_DEFAULT_DIR / "prompts")

execute_node = make_execute_node(config_path_default=_CONFIG, prompts_dir=_PROMPTS)
review_node = make_review_node(config_path_default=_CONFIG, prompts_dir=_PROMPTS)


class TestDecomposeNode:
    def test_decomposes_task_into_subtasks(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "1-add-feature", "description": "Add the feature", "acceptance_criteria": "Feature works"},
                    {"id": "2-add-tests", "description": "Add tests", "acceptance_criteria": "Tests pass"},
                ],
                "strategy": "execute",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Add a new feature"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 2
        assert result["strategy"] == "execute"
        assert result["phase"] == "decompose"

    def test_handles_unparseable_response(self, mock_llm):
        """When JSON can't be parsed and rescue_json also fails,
        node returns empty subtasks gracefully (no crash)."""
        mock_llm.append({"content": "not json at all", "model": "mock", "latency": 0.1})

        with patch("langgraph_maestro.nodes.decompose.rescue_json", return_value=None):
            state = {"task": "Do something"}
            result = decompose_node(state)

        assert result["subtasks"] == []
        assert result["phase"] == "decompose"

    def test_handles_empty_subtasks(self, mock_llm):
        """Empty subtasks list is returned as-is (text-based parsing has no min_length)."""
        mock_llm.append({
            "content": json.dumps({"subtasks": [], "strategy": "execute"}),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Do something"}
        result = decompose_node(state)

        assert result["subtasks"] == []
        assert result["strategy"] == "execute"



class TestExecuteNode:
    def test_executes_subtasks(self):
        agent_response = {
            "content": json.dumps({
                "status": "COMPLETE",
                "files_modified": ["a.py"],
                "implementation_summary": "Created a.py",
            }),
            "provider": "claude_code",
            "model": "mock",
        }

        # Mock returns [] before agent runs, ["a.py"] after
        changed_responses = iter([[], ["a.py"]])

        def changed_side_effect(cwd):
            return next(changed_responses)

        with patch("langgraph_maestro.nodes.execute.call_agent", return_value=agent_response), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", side_effect=changed_side_effect):

            state = {
                "subtasks": [{"id": "1-task", "description": "Create a.py", "acceptance_criteria": "File exists", "status": "pending", "attempts": 0}],
                "config_path": "workflows/default/config.yaml",
                "cwd": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-task" in result["completed_tasks"]
        assert result["failed_tasks"] == []
        assert result["phase"] == "execute"

    def test_retries_failed_subtask(self):
        # First two attempts: no files changed; third attempt: files changed
        # Now uses before/after pattern: ([], []), ([], []), ([], ["b.py"])
        agent_response = {"content": "", "provider": "claude_code", "model": "mock"}

        def agent_side_effect(**kwargs):
            return agent_response

        # 6 calls: before,after pairs for 3 attempts
        changed_responses = [[], [], [], [], [], ["b.py"]]
        changed_iter = iter(changed_responses)

        def changed_side_effect(cwd):
            return next(changed_iter)

        with patch("langgraph_maestro.nodes.execute.call_agent", side_effect=agent_side_effect), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", side_effect=changed_side_effect):

            state = {
                "subtasks": [{"id": "1-fix", "description": "Fix b.py", "acceptance_criteria": "Fixed", "status": "pending", "attempts": 0}],
                "config_path": "workflows/default/config.yaml",
                "cwd": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-fix" in result["completed_tasks"]

    def test_marks_failed_on_exception(self):
        with patch("langgraph_maestro.nodes.execute.call_agent", side_effect=RuntimeError("agent crashed")), \
             patch("langgraph_maestro.nodes.execute._get_changed_files", return_value=[]):

            state = {
                "subtasks": [{"id": "1-fail", "description": "Will fail", "acceptance_criteria": "N/A", "status": "pending", "attempts": 0}],
                "config_path": "workflows/default/config.yaml",
                "cwd": "/fake/repo",
            }
            result = execute_node(state)

        assert "1-fail" in result["failed_tasks"]
        assert result["completed_tasks"] == []


class TestReviewNode:
    def test_approves_clean_work(self, mock_llm, tmp_config):
        path = tmp_config({"phases": {"review": ["mock-model"]}})
        mock_llm.append({
            "content": json.dumps({"verdict": "APPROVE", "issues": [], "summary": "All good"}),
            "model": "mock",
            "latency": 0.1,
        })

        state = {
            "task": "Add feature",
            "subtasks": [{"id": "1-task", "description": "Do it", "status": "complete", "result": {"status": "COMPLETE"}}],
            "config_path": path,
        }
        result = review_node(state)

        assert result["verdict"] == "APPROVE"
        assert result["review_issues"] == []

    def test_rejects_with_issues(self, mock_llm, tmp_config):
        path = tmp_config({"phases": {"review": ["mock-model"]}})
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
            "task": "Add feature",
            "subtasks": [{"id": "1-task", "description": "Do it", "status": "complete"}],
            "config_path": path,
        }
        result = review_node(state)

        assert result["verdict"] == "REJECT"
        assert len(result["review_issues"]) == 1

    def test_handles_parse_failure(self, mock_llm, tmp_config):
        path = tmp_config({"phases": {"review": ["mock-model"]}})
        mock_llm.append({"content": "not json", "model": "mock", "latency": 0.1})

        state = {
            "task": "Add feature",
            "subtasks": [],
            "config_path": path,
        }
        result = review_node(state)

        assert result["verdict"] == "REJECT"
