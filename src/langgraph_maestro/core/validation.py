"""Subtask validation — quality gate between decompose and execute phases."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_subtasks(subtasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate subtask quality before execution.

    Checks:
    - Description length >= 50 chars (warns if not)
    - Description contains file path or function name (warns if not)
    - Detects duplicate descriptions (warns if found)
    - Each subtask has non-empty "id" field (warns if not)

    Args:
        subtasks: List of subtask dicts with "id" and "description" keys.

    Returns:
        Dict with:
            - warnings: list of warning dicts with "severity" and "message"
            - valid: bool (True if no DUPLICATE warnings)
            - phase: "validate_subtasks"
    """
    warnings: list[dict[str, str]] = []

    # Track descriptions for duplicate detection
    seen_descriptions: dict[str, list[str]] = {}

    for i, subtask in enumerate(subtasks):
        task_id = subtask.get("id", "")
        description = subtask.get("description") or ""

        # Check 1: Description length >= 50 chars
        if len(description) < 50:
            warnings.append({
                "severity": "VAGUE",
                "message": f"Subtask {i + 1} description too short ({len(description)} chars): '{description[:30]}...'",
            })
            logger.warning(
                "subtask_description_too_short",
                extra={"index": i, "length": len(description), "task_id": task_id},
            )

        # Check 2: Description contains file path or function name
        has_file_path = "/" in description or ".py" in description or ".ts" in description or ".js" in description
        has_function = "()" in description
        if not (has_file_path or has_function):
            warnings.append({
                "severity": "VAGUE",
                "message": f"Subtask {i + 1} missing file path or function name: '{description[:50]}...'",
            })
            logger.warning(
                "subtask_missing_file_or_function",
                extra={"index": i, "task_id": task_id},
            )

        # Check 3: Duplicate descriptions (exact match)
        if description:
            if description in seen_descriptions:
                seen_descriptions[description].append(task_id or f"index_{i}")
            else:
                seen_descriptions[description] = [task_id or f"index_{i}"]

        # Check 4: Non-empty id field
        if not task_id:
            warnings.append({
                "severity": "VAGUE",
                "message": f"Subtask {i + 1} has empty 'id' field",
            })
            logger.warning(
                "subtask_empty_id",
                extra={"index": i},
            )

    # Process duplicates after collecting all
    for desc, task_ids in seen_descriptions.items():
        if len(task_ids) > 1:
            warnings.append({
                "severity": "DUPLICATE",
                "message": f"Duplicate subtask description: '{desc[:50]}...' (tasks: {', '.join(task_ids)})",
            })
            logger.warning(
                "subtask_duplicate_description",
                extra={"description": desc[:50], "task_ids": task_ids},
            )

    # Valid is True only if no DUPLICATE warnings
    has_duplicate = any(w["severity"] == "DUPLICATE" for w in warnings)

    result = {
        "warnings": warnings,
        "valid": not has_duplicate,
        "phase": "validate_subtasks",
    }

    logger.info(
        "validate_subtasks_done",
        extra={
            "num_subtasks": len(subtasks),
            "num_warnings": len(warnings),
            "valid": result["valid"],
        },
    )

    return result
