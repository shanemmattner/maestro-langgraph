"""Tests for PR Review parallel reviewer execution using LangGraph Send()."""

import json
import operator
import pytest
from unittest.mock import patch, MagicMock
from langgraph.types import Send

from langgraph_maestro.workflows.pr_review.state import PRReviewState
from langgraph_maestro.workflows.pr_review.nodes import (
    fan_out_reviewers,
    reviewer_node,
    collect_reviews,
)
from langgraph_maestro.workflows.pr_review.graph import build_graph


class TestFanOutReviewers:
    """Test the fan_out_reviewers function that creates Send() calls."""

    def test_creates_send_for_each_persona(self):
        """Test that fan_out_reviewers creates one Send() per reviewer."""
        state: PRReviewState = {
            "pr_title": "Test PR",
            "pr_diff": "diff content",
            "changed_files": ["file1.py", "file2.py"],
            "config_path": "workflows/pr_review/config.yaml",
        }
        
        with patch("langgraph_maestro.workflows.pr_review.nodes.load_config") as mock_config:
            mock_config.return_value = {
                "reviewers": ["security", "correctness"],
                "phases": {},
            }
            
            result = fan_out_reviewers(state)
        
        assert len(result) == 2
        assert all(isinstance(r, Send) for r in result)
        
        # Check Send destinations
        assert result[0].node == "reviewer_node"
        assert result[1].node == "reviewer_node"
        
        # Check persona in state
        assert result[0].arg["current_persona"] == "security"
        assert result[1].arg["current_persona"] == "correctness"

    def test_handles_config_error_uses_defaults(self):
        """Test fallback to default reviewers on config error."""
        state: PRReviewState = {
            "pr_title": "Test PR",
            "config_path": "invalid/path.yaml",
        }
        
        with patch("langgraph_maestro.workflows.pr_review.nodes.load_config") as mock_config:
            mock_config.side_effect = Exception("Config not found")
            
            result = fan_out_reviewers(state)
        
        # Should use default reviewers
        assert len(result) == 4
        personas = [r.arg["current_persona"] for r in result]
        assert "security" in personas
        assert "correctness" in personas
        assert "tests" in personas
        assert "architecture" in personas


class TestReviewerNode:
    """Test the reviewer_node that processes a single persona."""

    @pytest.fixture
    def mock_llm(self):
        """Mock the LLM call."""
        with patch("langgraph_maestro.nodes.reviewer.call_llm_with_fallback") as mock:
            mock.return_value = {
                "content": json.dumps([
                    {"title": "Security issue", "severity": "HIGH"},
                    {"title": "Minor security concern", "severity": "LOW"},
                ])
            }
            yield mock

    @pytest.fixture
    def mock_extract_json(self):
        """Mock JSON extraction."""
        with patch("langgraph_maestro.nodes.reviewer.extract_json") as mock:
            mock.return_value = [
                {"title": "Security issue", "severity": "HIGH"},
                {"title": "Minor security concern", "severity": "LOW"},
            ]
            yield mock

    def test_processes_single_persona(self, mock_llm, mock_extract_json):
        """Test that reviewer_node processes a single persona correctly."""
        state: PRReviewState = {
            "pr_title": "Fix auth bug",
            "pr_diff": "diff content here",
            "changed_files": ["auth.py"],
            "current_persona": "security",
            "config_path": "workflows/pr_review/config.yaml",
        }
        
        with patch("langgraph_maestro.nodes.reviewer._load_prompt") as mock_prompt:
            mock_prompt.return_value = "Review as {reviewer_persona}: {pr_title}\n\n{pr_diff}\n\n{changed_files}"
            
            result = reviewer_node(state)
        
        assert "reviewer_results" in result
        assert len(result["reviewer_results"]) == 1
        
        reviewer_result = result["reviewer_results"][0]
        assert reviewer_result["persona"] == "security"
        assert len(reviewer_result["findings"]) == 2

    def test_handles_llm_failure_gracefully(self):
        """Test that reviewer_node handles LLM failures."""
        state: PRReviewState = {
            "pr_title": "Test PR",
            "pr_diff": "diff",
            "changed_files": ["file.py"],
            "current_persona": "correctness",
            "config_path": "workflows/pr_review/config.yaml",
        }
        
        with patch("langgraph_maestro.workflows.pr_review.nodes.call_llm_with_fallback") as mock:
            mock.side_effect = Exception("LLM error")
            
            result = reviewer_node(state)
        
        # Should return empty findings, not raise
        assert "reviewer_results" in result
        assert len(result["reviewer_results"]) == 1
        assert result["reviewer_results"][0]["findings"] == []

    def test_uses_correct_persona_in_prompt(self, mock_llm, mock_extract_json):
        """Test that the persona is correctly used in the prompt."""
        state: PRReviewState = {
            "pr_title": "Test PR",
            "pr_diff": "diff",
            "changed_files": ["test.py"],
            "current_persona": "tests",
            "config_path": "workflows/pr_review/config.yaml",
        }
        
        with patch("langgraph_maestro.nodes.reviewer._load_prompt") as mock_prompt:
            mock_prompt.return_value = "Review as {reviewer_persona}: {pr_title}"
            
            reviewer_node(state)
        
        # Verify LLM was called with correct system prompt
        call_kwargs = mock_llm.call_args[1]
        assert "tests" in call_kwargs["system_prompt"]


class TestCollectReviews:
    """Test the collect_reviews aggregation function."""

    def test_aggregates_findings_from_all_reviewers(self):
        """Test that findings from all reviewers are collected."""
        state: PRReviewState = {
            "reviewer_results": [
                {"persona": "security", "findings": [{"title": "Issue 1", "severity": "HIGH"}]},
                {"persona": "correctness", "findings": [{"title": "Issue 2", "severity": "MEDIUM"}]},
                {"persona": "tests", "findings": []},
            ]
        }
        
        result = collect_reviews(state)
        
        assert result["findings"] == [
            {"title": "Issue 1", "severity": "HIGH"},
            {"title": "Issue 2", "severity": "MEDIUM"},
        ]
        assert len(result["findings"]) == 2

    def test_handles_empty_reviewer_results(self):
        """Test collect_reviews with no reviewer results."""
        state: PRReviewState = {"reviewer_results": []}
        
        result = collect_reviews(state)
        
        assert result["findings"] == []
        assert result["phase"] == "analyze"


class TestGraphCompilation:
    """Test that the graph compiles with the new parallel structure."""

    def test_graph_compiles_successfully(self):
        """Test that build_graph() compiles without errors."""
        graph = build_graph()
        assert graph is not None

    def test_graph_has_correct_nodes(self):
        """Test that all required nodes are in the graph."""
        graph = build_graph()
        
        # Check nodes exist by looking at node names in the graph
        node_names = list(graph.nodes.keys())
        
        assert "fetch_pr" in node_names
        assert "reviewer_node" in node_names
        assert "collect_reviews" in node_names
        assert "synthesize" in node_names

    def test_graph_flow_is_correct(self):
        """Test the graph flow structure."""
        graph = build_graph()
        
        # Get the adjacency list to verify flow
        # The structure should be:
        # fetch_pr -> fan_out -> reviewer_node -> collect_reviews -> synthesize
        channels = graph.channels
        
        # Verify channels exist for the new nodes
        assert "reviewer_node" in channels or any("reviewer" in str(k) for k in channels.keys())
        assert "collect_reviews" in channels or any("collect" in str(k) for k in channels.keys())


class TestFanOutCreatesCorrectSendCalls:
    """Test that fan-out creates correct number of Send() calls."""

    def test_four_reviewers_creates_four_sends(self):
        """Test with 4 reviewers (security, correctness, tests, architecture)."""
        state: PRReviewState = {
            "pr_title": "Test PR",
            "pr_diff": "diff",
            "changed_files": ["a.py", "b.py"],
            "config_path": "workflows/pr_review/config.yaml",
        }
        
        with patch("langgraph_maestro.workflows.pr_review.nodes.load_config") as mock_config:
            mock_config.return_value = {
                "reviewers": ["security", "correctness", "tests", "architecture"],
                "phases": {},
            }
            
            result = fan_out_reviewers(state)
        
        assert len(result) == 4
        
        personas = [r.arg["current_persona"] for r in result]
        assert personas == ["security", "correctness", "tests", "architecture"]

    def test_send_includes_required_state(self):
        """Test that Send() includes all required state for reviewer_node."""
        state: PRReviewState = {
            "pr_title": "My PR Title",
            "pr_diff": "my diff",
            "changed_files": ["main.py", "utils.py"],
            "config_path": "custom/config.yaml",
        }
        
        with patch("langgraph_maestro.workflows.pr_review.nodes.load_config") as mock_config:
            mock_config.return_value = {"reviewers": ["security"], "phases": {}}
            
            result = fan_out_reviewers(state)
        
        send = result[0]
        arg = send.arg
        
        assert arg["pr_title"] == "My PR Title"
        assert arg["pr_diff"] == "my diff"
        assert arg["changed_files"] == ["main.py", "utils.py"]
        assert arg["config_path"] == "custom/config.yaml"
        assert arg["current_persona"] == "security"


class TestPRReviewStateReducer:
    """Test that PRReviewState.reviewer_results uses operator.add reducer."""

    def test_reviewer_results_has_add_reducer(self):
        """reviewer_results annotation uses operator.add for concurrent write merging."""
        import typing
        hints = typing.get_type_hints(PRReviewState, include_extras=True)
        annotation = hints["reviewer_results"]
        # Annotated[list[dict], operator.add] — metadata[0] should be operator.add
        metadata = annotation.__metadata__
        assert metadata[0] is operator.add

    def test_two_parallel_writes_merge_via_reducer(self):
        """Simulate two parallel reviewer writes merging correctly."""
        result_a = [{"persona": "security", "findings": [{"title": "XSS"}]}]
        result_b = [{"persona": "correctness", "findings": [{"title": "Off-by-one"}]}]

        # operator.add on lists concatenates them
        merged = operator.add(result_a, result_b)
        assert len(merged) == 2
        assert merged[0]["persona"] == "security"
        assert merged[1]["persona"] == "correctness"
