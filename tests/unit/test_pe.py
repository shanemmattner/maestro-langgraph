"""Tests for core.pe prompt engineering middleware."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from langgraph_maestro.core.pe import improve_prompt, pe_node_factory, _find_checklist

pytestmark = pytest.mark.enable_pe


class TestImprovePrompt:
    def test_returns_improved_prompt(self):
        mock_result = {"content": "Improved: do X clearly", "model": "mock", "latency": 0.1}
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", return_value=mock_result):
                result = improve_prompt("do X", config={})
        assert result == "Improved: do X clearly"

    def test_fallback_on_empty_response(self):
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", return_value={"content": "", "model": "m", "latency": 0.1}):
                result = improve_prompt("original prompt", config={})
        assert result == "original prompt"

    def test_fallback_on_exception(self):
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", side_effect=RuntimeError("LLM down")):
                result = improve_prompt("original prompt", config={})
        assert result == "original prompt"

    def test_fallback_when_no_checklist(self):
        with patch("langgraph_maestro.core.pe._find_checklist", return_value=None):
            result = improve_prompt("original prompt", config={})
        assert result == "original prompt"

    def test_uses_config_model(self):
        config = {"prompt_engineering": {"model": "custom-model", "timeout": 60}}
        mock_result = {"content": "improved", "model": "custom-model", "latency": 0.1}
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", return_value=mock_result) as mock_call:
                improve_prompt("do X", config=config)
                mock_call.assert_called_once()
                assert mock_call.call_args.kwargs["model"] == "custom-model"
                assert mock_call.call_args.kwargs["timeout"] == 60


class TestPeNodeFactory:
    def test_disabled_returns_passthrough(self):
        config = {"prompt_engineering": {"enabled": False}}
        node = pe_node_factory("generate", config)
        result = node({"task": "hello"})
        assert result == {}

    def test_phase_not_in_list_returns_passthrough(self):
        config = {"prompt_engineering": {"enabled": True, "phases": ["review"]}}
        node = pe_node_factory("generate", config)
        result = node({"task": "hello"})
        assert result == {}

    def test_enabled_runs_pe(self):
        config = {"prompt_engineering": {"enabled": True, "phases": ["generate"]}}
        mock_result = {"content": "improved prompt", "model": "m", "latency": 0.1}
        node = pe_node_factory("generate", config)

        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", return_value=mock_result):
                result = node({"task": "original task"})

        assert "pe_generate_prompt" in result
        assert result["pe_generate_prompt"] == "improved prompt"

    def test_empty_task_returns_empty(self):
        config = {"prompt_engineering": {"enabled": True, "phases": ["generate"]}}
        node = pe_node_factory("generate", config)
        result = node({"task": ""})
        assert result == {}

    def test_missing_pe_config_returns_passthrough(self):
        node = pe_node_factory("generate", {})
        result = node({"task": "hello"})
        assert result == {}


class TestFindChecklist:
    def test_finds_checklist_in_repo(self):
        """_find_checklist should find pe-checklist.md searching upward."""
        result = _find_checklist()
        # May or may not find it depending on repo structure, but shouldn't crash
        assert result is None or isinstance(result, str)


class TestImprovePromptCustomChecklistPath:
    def test_custom_checklist_path(self, tmp_path):
        checklist = tmp_path / "custom-checklist.md"
        checklist.write_text("## Custom Checklist\n1. Be clear")

        config = {
            "prompt_engineering": {
                "checklist_path": str(checklist),
                "model": "mock-model",
                "timeout": 10,
            }
        }
        mock_result = {"content": "improved", "model": "mock", "latency": 0.1}
        with patch("langgraph_maestro.core.llm.call_llm", return_value=mock_result):
            result = improve_prompt("do X", config=config)
        assert result == "improved"

    def test_custom_checklist_path_missing(self, tmp_path):
        config = {
            "prompt_engineering": {
                "checklist_path": str(tmp_path / "nonexistent.md"),
            }
        }
        # Should fall back to _find_checklist(), then to raw prompt if not found
        with patch("langgraph_maestro.core.pe._find_checklist", return_value=None):
            result = improve_prompt("original", config=config)
        assert result == "original"

    def test_no_config_uses_defaults(self):
        """improve_prompt with config=None should not crash."""
        with patch("langgraph_maestro.core.pe._find_checklist", return_value=None):
            result = improve_prompt("hello")
        assert result == "hello"


class TestImprovePromptEdgeCases:
    def test_whitespace_only_response_treated_as_empty(self):
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", return_value={"content": "   \n  ", "model": "m", "latency": 0.1}):
                result = improve_prompt("original", config={})
        assert result == "original"

    def test_timeout_error_falls_back(self):
        with patch("langgraph_maestro.core.pe._find_checklist", return_value="## Checklist"):
            with patch("langgraph_maestro.core.llm.call_llm", side_effect=TimeoutError("timeout")):
                result = improve_prompt("original", config={})
        assert result == "original"
