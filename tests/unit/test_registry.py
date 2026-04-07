"""Tests for core/registry.py — workflow registration, lookup, listing."""

import pytest
from unittest.mock import patch
from langgraph_maestro.core.registry import register_workflow, get_workflow, list_workflows, _workflows


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the registry before each test."""
    _workflows.clear()
    yield
    _workflows.clear()


class TestRegisterWorkflow:
    """Test register_workflow() succeeds and logs correctly."""

    def test_registers_workflow(self):
        def build_fn():
            return "graph"

        register_workflow("hello", build_fn, default_config="hello.yaml", description="Hello world")

        assert "hello" in _workflows
        assert _workflows["hello"]["build_fn"] is build_fn
        assert _workflows["hello"]["default_config"] == "hello.yaml"
        assert _workflows["hello"]["description"] == "Hello world"

    def test_logs_with_workflow_name_extra(self, caplog):
        """register_workflow() logs with extra={'workflow_name': name}, not 'name'."""
        import logging
        with caplog.at_level(logging.DEBUG, logger="langgraph_maestro.core.registry"):
            register_workflow("test_wf", lambda: None)

        # The log record should have workflow_name in extra
        assert any(
            getattr(r, "workflow_name", None) == "test_wf"
            for r in caplog.records
        )

    def test_overwrites_existing_registration(self):
        register_workflow("wf", lambda: "v1")
        register_workflow("wf", lambda: "v2")
        assert _workflows["wf"]["build_fn"]() == "v2"


class TestGetWorkflow:
    """Test get_workflow() returns correct dict or raises KeyError."""

    def test_returns_registered_workflow(self):
        build_fn = lambda: "graph"
        register_workflow("hello", build_fn, description="test")
        result = get_workflow("hello")

        assert result["build_fn"] is build_fn
        assert result["description"] == "test"

    def test_raises_keyerror_for_unknown_name(self):
        with pytest.raises(KeyError, match="not registered"):
            get_workflow("nonexistent")

    def test_keyerror_message_lists_available(self):
        register_workflow("aaa", lambda: None)
        register_workflow("bbb", lambda: None)

        with pytest.raises(KeyError, match="Available:.*aaa.*bbb"):
            get_workflow("zzz")


class TestListWorkflows:
    """Test list_workflows() returns all registered workflows."""

    def test_returns_empty_list_when_none_registered(self):
        assert list_workflows() == []

    def test_returns_all_registered(self):
        register_workflow("a", lambda: None, default_config="a.yaml", description="Workflow A")
        register_workflow("b", lambda: None, default_config="b.yaml", description="Workflow B")

        result = list_workflows()
        assert len(result) == 2
        names = [w["name"] for w in result]
        assert "a" in names
        assert "b" in names

    def test_includes_name_description_config(self):
        register_workflow("hello", lambda: None, default_config="h.yaml", description="Hello")
        result = list_workflows()

        assert result[0] == {
            "name": "hello",
            "description": "Hello",
            "default_config": "h.yaml",
        }
