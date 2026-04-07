"""Unit tests for chain_of_thought workflow."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from langgraph.graph import END


class TestChainOfThoughtWorkflow:
    """Tests for the chain_of_thought workflow."""

    def test_state_has_required_fields(self):
        from langgraph_maestro.workflows.chain_of_thought.state import ChainOfThoughtState
        fields = ChainOfThoughtState.__annotations__
        for f in ["question", "context", "domain", "sub_questions", "assumptions",
                  "reasoning_steps", "answer", "confidence", "verdict"]:
            assert f in fields, f"Missing field: {f}"

    def test_build_graph_compiles(self):
        from langgraph_maestro.workflows.chain_of_thought.graph import build_graph
        graph = build_graph(config_path=None)
        assert graph is not None

    def test_decompose_node_returns_sub_questions(self):
        from langgraph_maestro.workflows.chain_of_thought.nodes import make_decompose_node
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "langgraph_maestro.workflows.chain_of_thought.nodes._call",
            return_value={
                "sub_questions": ["What is A?", "What is B?"],
                "assumptions": ["Assume X"],
            }
        ):
            node = make_decompose_node({})
            result = node({"question": "test?", "context": "none", "domain": "general"})
            assert result["sub_questions"] == ["What is A?", "What is B?"]
            assert result["assumptions"] == ["Assume X"]

    def test_decompose_node_falls_back_to_original_question(self):
        from langgraph_maestro.workflows.chain_of_thought.nodes import make_decompose_node
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "langgraph_maestro.workflows.chain_of_thought.nodes._call",
            return_value={}  # empty response
        ):
            node = make_decompose_node({})
            result = node({"question": "What is 2+2?", "context": "none", "domain": "math"})
            # Should fall back to the original question
            assert "What is 2+2?" in result["sub_questions"]
