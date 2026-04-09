"""Tests for routing functions and verify_subtask in the redesigned default workflow."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from langgraph_maestro.workflows.default.graph import (
    route_after_decompose,
    route_after_validate,
    route_after_piece_review,
    route_after_holistic,
    route_after_adversarial,
    route_after_verify,
)
from langgraph_maestro.core.verify import verify_subtask
from langgraph.graph import END


# ---------------------------------------------------------------------------
# Routing function tests
# ---------------------------------------------------------------------------


class TestRouteAfterDecompose:
    """Tests for the route_after_decompose routing function."""

    def test_blocked_goes_to_escalate(self):
        state = {"strategy": "blocked"}
        assert route_after_decompose(state) == "escalate"

    def test_execute_goes_to_validate(self):
        state = {"strategy": "execute"}
        assert route_after_decompose(state) == "validate_plan"

    def test_default_goes_to_validate(self):
        state = {}
        assert route_after_decompose(state) == "validate_plan"


class TestRouteAfterValidate:
    """Tests for the route_after_validate routing function."""

    def test_no_warnings_goes_to_plan_piece(self):
        state = {"subtask_warnings": []}
        assert route_after_validate(state) == "plan_piece"

    def test_critical_warning_with_budget_goes_to_decompose(self):
        state = {"subtask_warnings": ["Duplicate subtask found"], "replan_rounds": 0}
        assert route_after_validate(state) == "decompose"

    def test_critical_warning_exhausted_goes_to_escalate(self):
        state = {"subtask_warnings": ["Duplicate subtask found"], "replan_rounds": 1}
        assert route_after_validate(state) == "escalate"

    def test_non_critical_warning_goes_to_plan_piece(self):
        state = {"subtask_warnings": ["VAGUE: description too short"]}
        assert route_after_validate(state) == "plan_piece"


class TestRouteAfterPieceReview:
    """Tests for the route_after_piece_review routing function."""

    def test_approve_with_more_subtasks(self):
        state = {"piece_verdict": "APPROVE", "current_subtask_index": 0, "subtasks": [1, 2, 3]}
        assert route_after_piece_review(state) == "plan_piece"

    def test_approve_all_done(self):
        state = {"piece_verdict": "APPROVE", "current_subtask_index": 2, "subtasks": [1, 2, 3]}
        assert route_after_piece_review(state) == "holistic_review"

    def test_reject_with_budget(self):
        state = {"piece_verdict": "REJECT", "piece_review_rounds": 0}
        assert route_after_piece_review(state) == "execute_piece"

    def test_reject_exhausted(self):
        state = {"piece_verdict": "REJECT", "piece_review_rounds": 2}
        assert route_after_piece_review(state) == "escalate"

    def test_nits_with_budget(self):
        state = {"piece_verdict": "NITS", "piece_review_rounds": 0}
        assert route_after_piece_review(state) == "execute_piece"

    def test_nits_exhausted_moves_forward(self):
        state = {"piece_verdict": "NITS", "piece_review_rounds": 2, "current_subtask_index": 0, "subtasks": [1, 2]}
        assert route_after_piece_review(state) == "plan_piece"


class TestRouteAfterHolistic:
    """Tests for the route_after_holistic routing function."""

    def test_approve_goes_to_adversarial(self):
        state = {"holistic_verdict": "APPROVE"}
        assert route_after_holistic(state) == "adversarial_review"

    def test_reject_with_budget_goes_to_decompose(self):
        state = {"holistic_verdict": "REJECT", "holistic_review_rounds": 0}
        assert route_after_holistic(state) == "decompose"

    def test_reject_exhausted_goes_to_escalate(self):
        state = {"holistic_verdict": "REJECT", "holistic_review_rounds": 1}
        assert route_after_holistic(state) == "escalate"


class TestRouteAfterAdversarial:
    """Tests for the route_after_adversarial routing function."""

    def test_pass_goes_to_verify(self):
        state = {"adversarial_verdict": "PASS"}
        assert route_after_adversarial(state) == "verify"

    def test_fail_with_budget_goes_to_plan_piece(self):
        state = {"adversarial_verdict": "FAIL", "adversarial_rounds": 0}
        assert route_after_adversarial(state) == "plan_piece"

    def test_fail_exhausted_goes_to_escalate(self):
        state = {"adversarial_verdict": "FAIL", "adversarial_rounds": 1}
        assert route_after_adversarial(state) == "escalate"


class TestRouteAfterVerify:
    """Tests for the route_after_verify routing function."""

    def test_pass_goes_to_aar(self):
        state = {"verification_verdict": "PASS"}
        assert route_after_verify(state) == "after_action_review"

    def test_partial_goes_to_aar(self):
        state = {"verification_verdict": "PARTIAL"}
        assert route_after_verify(state) == "after_action_review"

    def test_fail_goes_to_escalate(self):
        state = {"verification_verdict": "FAIL"}
        assert route_after_verify(state) == "escalate"


# ---------------------------------------------------------------------------
# Verify subtask tests (unchanged from original)
# ---------------------------------------------------------------------------


class TestVerifySubtask:
    """Tests for the verify_subtask function."""

    def test_detects_syntax_error(self, tmp_path):
        """Verify detects syntax errors in Python files."""
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

        assert result["pass"] is True
        assert result["errors"] == []

    def test_runs_generated_tests(self, tmp_path):
        """Verify runs pytest on generated test files."""
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
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_fail():\n    assert False, 'intentional failure'\n")

        result = verify_subtask(
            cwd=str(tmp_path),
            changed_files=[],
            generated_tests=["test_fail.py"],
        )

        assert result["pass"] is False
        assert any("test failure" in err.lower() for err in result["errors"])
