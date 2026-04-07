"""Style check node factory."""

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


def make_style_check_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a style check node.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def style_check_node(state: dict) -> dict:
        """Check code for style violations."""
        start = time.time()
        diff_content = state.get("diff_content", "")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("style_check", config)

        logger.info("style_check_start")

        if not diff_content:
            logger.warning("style_check_no_diff")
            return {
                "errors": state.get("errors", []) + ["No diff content to check"],
                "style_violations": [],
                "style_score": 100,
            }

        template = _load_prompt("style_check", prompts_path)
        prompt = template.replace("{diff_content}", diff_content)

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "style_check" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="style_check",
            config=config,
            system_prompt="You are a code style expert. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.warning("style_check_parse_failed")
            return {
                "style_violations": [],
                "style_score": 100,
                "errors": state.get("errors", []) + ["Failed to parse style check response"],
            }

        violations = parsed.get("violations", [])
        score = parsed.get("score", 100)

        elapsed = time.time() - start
        logger.info(f"style_check_done: {elapsed:.2f}s, violations={len(violations)}, score={score}")

        return {
            "style_violations": violations,
            "style_score": score,
            "phase_outputs": {
                **state.get("phase_outputs", {}),
                "style_check": {"violations": violations, "score": score, "elapsed": elapsed},
            },
        }

    return style_check_node
