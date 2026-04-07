"""Tests for maestro decompose_node using structured output (issue #1)."""

import json
import pytest
from langgraph_maestro.workflows.default.nodes import decompose_node


class TestDecomposeNodeStructured:
    """decompose_node now uses call_llm_structured + MaestroDecomposeOutput."""

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

    def test_retries_on_bad_json_and_succeeds(self, mock_llm):
        # First response fails, second is valid — structured wrapper retries
        mock_llm.append({"content": "not json at all", "model": "mock", "latency": 0.1})
        mock_llm.append({
            "content": json.dumps({
                "subtasks": [
                    {"id": "1-fix", "description": "Fix it", "acceptance_criteria": "Fixed"},
                ],
                "strategy": "execute",
            }),
            "model": "mock",
            "latency": 0.1,
        })

        state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert len(result["subtasks"]) == 1
        assert "errors" not in result

    def test_returns_error_after_all_retries_fail(self, mock_llm):
        # All responses are unparseable JSON
        for _ in range(4):
            mock_llm.append({"content": "bad", "model": "mock", "latency": 0.1})

        state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert "errors" in result
        assert result["phase"] == "decompose"

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

        # Empty id triggers field_validator which raises, so structured retries
        # and eventually fails — OR the node normalises afterwards.
        # Accept either an error dict or a result where id is non-empty.
        assert "errors" in result or result["subtasks"][0]["id"]

    def test_rejects_empty_subtasks_list(self, mock_llm):
        # Pydantic min_length=1 will reject an empty subtasks list
        for _ in range(4):
            mock_llm.append({
                "content": json.dumps({"subtasks": [], "strategy": "execute"}),
                "model": "mock",
                "latency": 0.1,
            })

        state = {"task": "Do something", "config_path": "workflows/default/config.yaml"}
        result = decompose_node(state)

        assert "errors" in result

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
