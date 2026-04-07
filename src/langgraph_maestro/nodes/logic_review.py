"""Logic review node factory."""

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


def make_logic_review_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a logic review node.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def logic_review_node(state: dict) -> dict:
        """Review code for logic issues."""
        start = time.time()
        diff_content = state.get("diff_content", "")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("logic_review", config)

        logger.info("logic_review_start")

        if not diff_content:
            logger.warning("logic_review_no_diff")
            return {
                "errors": state.get("errors", []) + ["No diff content to review"],
                "logic_issues": [],
                "logic_score": 0,
            }

        template = _load_prompt("logic_review", prompts_path)
        prompt = template.replace("{diff_content}", diff_content)

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "logic_review" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="logic_review",
            config=config,
            system_prompt="You are a code logic expert. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.warning("logic_review_parse_failed")
            return {
                "logic_issues": [],
                "logic_score": 0,
                "errors": state.get("errors", []) + ["Failed to parse logic review response"],
            }

        issues = parsed.get("issues", [])
        score = parsed.get("score", 50)

        elapsed = time.time() - start
        logger.info(f"logic_review_done: {elapsed:.2f}s, issues={len(issues)}, score={score}")

        return {
            "logic_issues": issues,
            "logic_score": score,
            "phase_outputs": {
                **state.get("phase_outputs", {}),
                "logic_review": {"issues": issues, "score": score, "elapsed": elapsed},
            },
        }

    return logic_review_node
