"""Summarize node factory."""

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


def make_summarize_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a summarize node.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def summarize_node(state: dict) -> dict:
        """Summarize code review results."""
        start = time.time()
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("summarize", config)

        logger.info("summarize_start")

        # Gather all review results
        security_findings = state.get("security_findings", [])
        logic_issues = state.get("logic_issues", [])
        style_violations = state.get("style_violations", [])
        
        security_score = state.get("security_score", 50)
        logic_score = state.get("logic_score", 50)
        style_score = state.get("style_score", 100)

        # Calculate overall score (weighted average)
        overall_score = int((security_score * 0.4) + (logic_score * 0.4) + (style_score * 0.2))

        template = _load_prompt("summarizer", prompts_path)
        prompt = template.replace("{security_findings}", str(security_findings))
        prompt = prompt.replace("{logic_issues}", str(logic_issues))
        prompt = prompt.replace("{style_violations}", str(style_violations))
        prompt = prompt.replace("{security_score}", str(security_score))
        prompt = prompt.replace("{logic_score}", str(logic_score))
        prompt = prompt.replace("{style_score}", str(style_score))
        prompt = prompt.replace("{overall_score}", str(overall_score))

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "summarize" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="summarize",
            config=config,
            system_prompt="You are a code review summarizer. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.warning("summarize_parse_failed")
            # Create a basic summary from the scores
            summary = f"Code Review Summary: Security: {security_score}/100, Logic: {logic_score}/100, Style: {style_score}/100, Overall: {overall_score}/100"
            return {
                "summary": summary,
                "overall_score": overall_score,
                "errors": state.get("errors", []) + ["Failed to parse summary response, using basic summary"],
            }

        summary = parsed.get("summary", "")
        
        elapsed = time.time() - start
        logger.info(f"summarize_done: {elapsed:.2f}s, overall_score={overall_score}")

        return {
            "summary": summary,
            "overall_score": overall_score,
            "phase_outputs": {
                **state.get("phase_outputs", {}),
                "summarize": {"summary": summary, "overall_score": overall_score, "elapsed": elapsed},
            },
        }

    return summarize_node
