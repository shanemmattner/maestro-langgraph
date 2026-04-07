"""Tests for new nodes and routing functions in maestro workflow."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from langgraph_maestro.workflows.default.graph import route_review
from langgraph_maestro.core.verify import verify_subtask
from langgraph.graph import END


class TestRouteReview:
    """Tests for the route_review routing function."""

    def test_approve_goes_to_end(self):
        """When verdict is APPROVE, route to END."""
        state = {"verdict": "APPROVE"}
        result = route_review(state)
        assert result == END

    def test_nits_goes_to_end(self):
        """When verdict is NITS, route to END."""
        state = {"verdict": "NITS"}
        result = route_review(state)
        assert result == END

    def test_reject_plan_goes_to_decompose(self):
        """When verdict is REJECT with plan issue, route to decompose."""
        state = {
            "verdict": "REJECT",
            "review_issues": [{"issue_type": "plan", "title": "Missing step"}],
            "replan_rounds": 0,
        }
        result = route_review(state)
        assert result == "decompose"

    def test_reject_impl_goes_to_execute(self):
        """When verdict is REJECT with implementation issue, route to execute."""
        state = {
            "verdict": "REJECT",
            "review_issues": [{"issue_type": "implementation", "title": "Bug"}],
            "review_rounds": 0,
            "max_review_rounds": 2,
        }
        result = route_review(state)
        assert result == "execute"

    def test_max_review_rounds_reached_goes_to_end(self):
        """When review_rounds >= max, route to END."""
        state = {
            "verdict": "REJECT",
            "review_rounds": 2,
            "max_review_rounds": 2,
        }
        result = route_review(state)
        assert result == END

    def test_max_replan_rounds_reaches_limit(self):
        """When replan_rounds exhausted, fall back to execute."""
        state = {
            "verdict": "REJECT",
            "review_issues": [{"issue_type": "plan", "title": "Missing step"}],
            "replan_rounds": 1,  # max_replan is 1, so this is exhausted
            "review_rounds": 0,
            "max_review_rounds": 2,
        }
        result = route_review(state)
        # Should fall back to execute since replan budget is exhausted
        assert result == "execute"


class TestVerifySubtask:
    """Tests for the verify_subtask function."""

    def test_detects_syntax_error(self, tmp_path):
        """Verify detects syntax errors in Python files."""
        # Create a file with syntax error
        test_file = tmp_path / "bad.py"
        test_file.write_text("def broken():\n    print(unclosed\n")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=["bad.py"],
            generated_tests=None,
        )

        assert result["pass"] is False
        assert any("syntax error" in err.lower() for err in result["errors"])

    def test_passing_files(self, tmp_path):
        """Verify passes valid Python files."""
        # Create a valid Python file
        test_file = tmp_path / "good.py"
        test_file.write_text("def working():\n    print('ok')\n")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=["good.py"],
            generated_tests=None,
        )

        assert result["pass"] is True
        assert result["errors"] == []

    def test_no_py_files(self, tmp_path):
        """Verify handles no .py files gracefully."""
        # Create a non-Python file
        test_file = tmp_path / "readme.txt"
        test_file.write_text("Just some text")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=["readme.txt"],
            generated_tests=None,
        )

        assert result["pass"] is True
        assert result["errors"] == []

    def test_missing_file_ignored(self, tmp_path):
        """Verify ignores files that don't exist."""
        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=["nonexistent.py"],
            generated_tests=None,
        )

        # Should not fail, just skip missing files
        assert result["pass"] is True
        assert result["errors"] == []

    def test_runs_generated_tests(self, tmp_path):
        """Verify runs pytest on generated test files."""
        # Create a test file that passes
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_pass():\n    assert True\n")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=[],
            generated_tests=["test_example.py"],
        )

        assert result["pass"] is True

    def test_generated_tests_failure(self, tmp_path):
        """Verify reports test failures."""
        # Create a test file that fails
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_fail():\n    assert False, 'intentional failure'\n")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=[],
            generated_tests=["test_fail.py"],
        )

        assert result["pass"] is False
        assert any("test failure" in err.lower() for err in result["errors"])
