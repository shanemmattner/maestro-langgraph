"""Template scaffolding for new langgraph-maestro workflows.

Provides scaffold_workflow() which copies base templates into a target
directory, replacing placeholder tokens with user-supplied values.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Directory containing base template files
_BASE_DIR = Path(__file__).parent / "base"

# Tokens replaced via simple str.replace() to avoid conflicts with
# Python's own $ usage in f-strings, shell scripts, etc.
_TOKENS = {
    "WORKFLOW_NAME",
    "WORKFLOW_DESCRIPTION",
    "DEFAULT_MODEL",
}


def scaffold_workflow(
    target_dir: str | Path,
    workflow_name: str,
    description: str = "",
    default_model: str = "claude-sonnet-4-6",
) -> list[Path]:
    """Scaffold a new workflow from base templates.

    Args:
        target_dir: Directory to write the workflow files into.
        workflow_name: Snake-case workflow name (e.g. ``my_workflow``).
        description: One-line description for the workflow registry.
        default_model: Default LLM model identifier for config.yaml.

    Returns:
        List of absolute paths to created files.
    """
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    replacements = {
        "WORKFLOW_NAME": workflow_name,
        "WORKFLOW_DESCRIPTION": description or f"{workflow_name} workflow",
        "DEFAULT_MODEL": default_model,
    }

    created: list[Path] = []

    for src_path in sorted(_BASE_DIR.rglob("*")):
        if src_path.is_dir():
            continue

        # Compute relative path and strip any template extension
        rel = src_path.relative_to(_BASE_DIR)
        dest = target / rel

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Read and perform token replacement
        content = src_path.read_text(encoding="utf-8")
        for token, value in replacements.items():
            content = content.replace(token, value)

        dest.write_text(content, encoding="utf-8")
        created.append(dest)

    return created
