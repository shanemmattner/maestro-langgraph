"""E2E test discovery — scans repos for LangGraph test workflows.

Finds tests at tests/llm_e2e/tests/*/graph.py, imports each build_graph(),
and returns metadata for the LLM test selector.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def discover_tests(repo_path: str) -> list[dict[str, Any]]:
    """Scan a repo for E2E test workflows.

    Looks for tests/llm_e2e/tests/*/graph.py, imports each module,
    and extracts the build_graph function + docstring.

    Args:
        repo_path: Absolute path to the repo root.

    Returns:
        List of {name, description, module_path, graph_builder}.
    """
    tests_dir = Path(repo_path) / "tests" / "llm_e2e" / "tests"
    if not tests_dir.is_dir():
        logger.info("no_e2e_tests", extra={"repo_path": repo_path})
        return []

    # Ensure repo is on sys.path for imports
    repo_str = str(Path(repo_path).resolve())
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    results = []
    for graph_file in sorted(tests_dir.glob("*/graph.py")):
        test_name = graph_file.parent.name
        module_path = str(graph_file)

        try:
            # Dynamic import
            spec = importlib.util.spec_from_file_location(
                f"llm_e2e_test_{test_name}", graph_file,
            )
            if spec is None or spec.loader is None:
                logger.warning("import_skip", extra={"test": test_name, "reason": "no spec"})
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            build_graph = getattr(module, "build_graph", None)
            if build_graph is None:
                logger.warning("import_skip", extra={"test": test_name, "reason": "no build_graph"})
                continue

            # Extract description from module or __init__.py docstring
            description = ""
            init_file = graph_file.parent / "__init__.py"
            if init_file.exists():
                init_spec = importlib.util.spec_from_file_location(
                    f"llm_e2e_init_{test_name}", init_file,
                )
                if init_spec and init_spec.loader:
                    init_module = importlib.util.module_from_spec(init_spec)
                    init_spec.loader.exec_module(init_module)
                    description = (init_module.__doc__ or "").strip()

            if not description:
                description = (module.__doc__ or "").strip()

            results.append({
                "name": test_name,
                "description": description,
                "module_path": module_path,
                "graph_builder": build_graph,
            })

            logger.info("test_discovered", extra={"test": test_name})

        except Exception as exc:
            logger.error("import_failed", extra={"test": test_name, "error": str(exc)})

    logger.info("discovery_complete", extra={"count": len(results), "repo": repo_path})
    return results


def list_test_summaries(repo_path: str) -> list[dict[str, str]]:
    """Return lightweight test metadata (no graph builders) for LLM consumption.

    Args:
        repo_path: Absolute path to the repo root.

    Returns:
        List of {name, description}.
    """
    tests = discover_tests(repo_path)
    return [{"name": t["name"], "description": t["description"]} for t in tests]
