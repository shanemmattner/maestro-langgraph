"""Workflow registry — register, discover, and list workflows."""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_workflows: dict[str, dict[str, Any]] = {}


def register_workflow(
    name: str,
    build_fn: Callable,
    default_config: str = "",
    description: str = "",
) -> None:
    """Register a workflow.

    Args:
        name: Unique workflow name.
        build_fn: Function that builds and returns compiled graph.
        default_config: Default config path for this workflow.
        description: Human-readable description.
    """
    _workflows[name] = {
        "build_fn": build_fn,
        "default_config": default_config,
        "description": description,
    }
    logger.debug("workflow_registered", extra={"workflow_name": name})


def get_workflow(name: str) -> dict[str, Any]:
    """Get a registered workflow by name. Raises KeyError if not found."""
    if name not in _workflows:
        raise KeyError(f"Workflow '{name}' not registered. Available: {list(_workflows.keys())}")
    return _workflows[name]


def list_workflows() -> list[dict[str, str]]:
    """List all registered workflows."""
    return [
        {"name": name, "description": w["description"], "default_config": w["default_config"]}
        for name, w in _workflows.items()
    ]
