"""Critique node — devil's advocate review of the decomposition plan."""

import json
import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_critique_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a critique node that reviews the decomposition plan.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def critique_node(state: dict) -> dict:
        """Review the plan and identify gaps, edge cases, security issues."""
        start = time.time()
        task = state.get("task", "")
        subtasks = state.get("subtasks", [])
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)

        # Check if critique phase is configured; if not, auto-approve
        phases = config.get("phases", {})
        if "critique" not in phases:
            return {
                "plan_approved": True,
                "critique_issues": [],
                "phase": "critique",
            }

        models = get_models_for_phase("critique", config)
        critique_rounds = state.get("critique_rounds", 0)

        logger.info("critique_start", extra={"round": critique_rounds})

        template = _load_prompt("critic", prompts_path)
        subtask_json = json.dumps(subtasks, indent=2)
        prompt = template.replace("{task}", task)
        prompt = prompt.replace("{subtasks}", subtask_json)

        # If this is a re-critique after decompose revision, include prior issues
        prior_issues = state.get("critique_issues", [])
        if prior_issues:
            prompt += f"\n\n## Prior Critique Issues (address these)\n{json.dumps(prior_issues, indent=2)}"

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="critique",
            config=config,
            system_prompt="You are a plan critic. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.warning("critique_parse_failed")
            return {
                "plan_approved": True,  # fail-open: don't block on parse failure
                "critique_issues": [],
                "critique_rounds": critique_rounds + 1,
                "phase": "critique",
            }

        issues = parsed.get("issues", [])
        approved = parsed.get("plan_approved", len(issues) == 0)

        elapsed = round(time.time() - start, 3)
        logger.info(
            "critique_done",
            extra={
                "approved": approved,
                "num_issues": len(issues),
                "round": critique_rounds,
                "elapsed": elapsed,
            },
        )

        return {
            "plan_approved": bool(approved),
            "critique_issues": issues,
            "critique_rounds": critique_rounds + 1,
            "phase": "critique",
        }

    return critique_node
