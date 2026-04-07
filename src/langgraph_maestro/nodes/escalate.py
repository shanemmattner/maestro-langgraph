"""Escalation node — human-in-the-loop when confidence is too low."""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def make_escalate_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create an escalation node that surfaces questions for human review.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """

    def escalate_node(state: dict) -> dict:
        """Extract questions from review issues and flag for human input."""
        review_issues = state.get("review_issues", [])

        # Extract unclear issues as questions
        questions = []
        for issue in review_issues:
            if issue.get("issue_type") == "unclear":
                questions.append(
                    f"[{issue.get('location', '?')}] {issue.get('title', '')}: "
                    f"{issue.get('description', '')}"
                )

        if not questions:
            questions = ["Review rejected with unclear issues but no specific questions extracted."]

        logger.info(
            "escalate",
            extra={
                "num_questions": len(questions),
                "verdict": state.get("verdict", "REJECT"),
            },
        )

        return {
            "needs_human_input": True,
            "escalation_questions": questions,
            "phase": "escalate",
        }

    return escalate_node
