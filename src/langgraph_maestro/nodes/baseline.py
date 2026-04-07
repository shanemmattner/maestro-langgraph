"""Baseline node — runs baseline checks before starting work."""

import logging

logger = logging.getLogger(__name__)


def baseline_node(state: dict) -> dict:
    """Run baseline checks (tests, lint) before starting work."""
    logger.info("baseline_check_start")
    # Placeholder — runs no checks, just passes through
    return {"phase": "baseline_check", "baseline_errors": []}
