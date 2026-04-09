"""Tests for maestro decompose_node using text-based JSON extraction.

After refactoring from Pydantic structured output to call_llm_with_fallback +
extract_json, this file verifies the decompose node correctly parses JSON from
free-form LLM text responses.
"""

import json
import pytest
from unittest.mock import patch
from langgraph_maestro.workflows.default.nodes import decompose_node


class TestDecomposeNodeTextBased:
    """decompose_node now uses call_llm_with_fallback + extract_json."""

    def test_returns_typed_subtasks(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {
                        "id": "1-add-feature",
                        "description": "Add the feature",
                        "acceptance_criteria": "Feature works",
                    },
                    {
                        "id": "2-add-tests",
                        "description": "Add tests",
                        "acceptance_criteria": "Tests pass",
                    },
                ],
                "strategy": "execute",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Add a new feature", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 2
        assert result["strategy"] == "execute"
        assert result["phase"] == "decompose"
        # Confirm runtime tracking fields are injected
        assert result["subtasks"][0]["status"] == "pending"
        assert result["subtasks"][0]["attempts"] == 0

    def test_extracts_json_from_markdown_fenced_response(self, mock_llm):
        """LLMs often wrap JSON in markdown code fences — extract_json handles this."""
        raw = '```json\n' + json.dumps({
            "subtasks": [
                {"id": "1-fix", "description": "Fix it", "acceptance_criteria": "Fixed"},
            ],
            "strategy": "execute",
        }) + '\n```'
        mock_llm.append({"content": raw, "model": "mock", "latency": 0.1})

        state = {"task": "Fix something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 1
        assert result["subtasks"][0]["id"] == "1-fix"

    def test_extracts_json_embedded_in_prose(self, mock_llm):
        """extract_json can find JSON object embedded in surrounding text."""
        embedded = 'Here is my plan:\n' + json.dumps({
            "subtasks": [
                {"id": "1-do", "description": "Do task", "acceptance_criteria": "Done"},
            ],
            "strategy": "execute",
        }) + '\nLet me know if this works.'
        mock_llm.append({"content": embedded, "model": "mock", "latency": 0.1})

        state = {"task": "Do task", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 1

    def test_returns_empty_subtasks_on_bad_json(self, mock_llm):
        """When JSON can't be parsed, rescue_json is attempted.
        If rescue also fails, node returns empty subtasks (no crash)."""
        mock_llm.append({"content": "not json at all", "model": "mock", "latency": 0.1})
        # rescue_json would make an LLM call — mock it to return None
        with patch("langgraph_maestro.nodes.decompose.rescue_json", return_value=None):
            state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
            result = decompose_node(state)

        assert result["subtasks"] == []
        assert result["phase"] == "decompose"

    def test_returns_empty_subtasks_for_empty_list(self, mock_llm):
        """An empty subtasks list is returned as-is (no Pydantic min_length)."""
        mock_llm.append({
            "content": json.dumps({"subtasks": [], "strategy": "execute"}),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert result["subtasks"] == []
        assert result["strategy"] == "execute"

    def test_assigns_default_ids_for_missing_id(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "", "description": "First task", "acceptance_criteria": "Done"},
                ],
                "strategy": "execute",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        # Empty id is replaced with a generated one
        assert result["subtasks"][0]["id"] == "1-task"

    def test_strategy_defaults_to_execute(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "1-t", "description": "Task", "acceptance_criteria": "Done"},
                ],
                # no "strategy" key
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Task", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert result.get("strategy") == "execute"

    def test_invalid_strategy_defaults_to_execute(self, mock_llm):
        """Unrecognized strategy values are normalized to 'execute'."""
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "1-t", "description": "Task", "acceptance_criteria": "Done"},
                ],
                "strategy": "yolo",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Task", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert result["strategy"] == "execute"

    def test_returns_error_when_llm_call_fails(self, mock_llm):
        """When call_llm_with_fallback raises, node returns errors dict."""
        with patch(
            "langgraph_maestro.nodes.decompose.call_llm_with_fallback",
            side_effect=RuntimeError("All fallback models failed"),
        ):
            state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
            result = decompose_node(state)

        assert "errors" in result
        assert result["phase"] == "decompose"
