"""Review node — reviews execution results and produces verdict."""

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


def make_review_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a review node with the given configuration.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def review_node(state: dict) -> dict:
        """Review execution results and produce verdict."""
        start = time.time()
        task = state.get("task", "")
        cwd = state.get("cwd") or state.get("repo_path")
        subtasks = state.get("subtasks", [])
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("review", config)

        logger.info("review_start")

        # Build subtask results summary for reviewer
        subtask_results = []
        for t in subtasks:
            entry = {
                "id": t.get("id"),
                "description": t.get("description", ""),
                "status": t.get("status", "unknown"),
                "acceptance_criteria": t.get("acceptance_criteria", ""),
            }
            if t.get("result"):
                entry["result"] = t["result"]
            subtask_results.append(entry)

        template = _load_prompt("reviewer", prompts_path)
        prompt = template.replace("{task}", task)
        prompt = prompt.replace("{subtask_results}", json.dumps(subtask_results, indent=2))

        # PE pass: improve prompt before LLM call
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "review" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="review",
            config=config,
            cwd=cwd,
            system_prompt="You are a code reviewer. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.error("review_parse_failed")
            return {
                "verdict": "REJECT",
                "review_issues": [{"severity": "HIGH", "title": "Review parse failed"}],
                "review_raw": content,
                "phase": "review",
            }

        verdict = parsed.get("verdict", "REJECT")
        issues = parsed.get("issues", [])
        review_rounds = state.get("review_rounds", 0) + 1

        elapsed = round(time.time() - start, 3)
        logger.info(
            "review_done",
            extra={
                "verdict": verdict,
                "num_issues": len(issues),
                "review_round": review_rounds,
                "elapsed": elapsed,
            },
        )

        return {
            "verdict": verdict,
            "review_issues": issues,
            "review_raw": content,
            "review_rounds": review_rounds,
            "phase": "review",
        }

    return review_node
