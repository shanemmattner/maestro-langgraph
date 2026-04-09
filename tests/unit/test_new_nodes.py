"""Tests for core.verify — verify_subtask function."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from langgraph_maestro.core.verify import verify_subtask


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
