"""Security scan node factory."""

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


def make_security_scan_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a security scan node.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def security_scan_node(state: dict) -> dict:
        """Scan code for security vulnerabilities."""
        start = time.time()
        diff_content = state.get("diff_content", "")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("security_scan", config)

        logger.info("security_scan_start")

        if not diff_content:
            logger.warning("security_scan_no_diff")
            return {
                "errors": state.get("errors", []) + ["No diff content to scan"],
                "security_findings": [],
                "security_score": 0,
            }

        template = _load_prompt("security_scan", prompts_path)
        prompt = template.replace("{diff_content}", diff_content)

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "security_scan" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="security_scan",
            config=config,
            system_prompt="You are a security expert. Return valid JSON only.",
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.warning("security_scan_parse_failed")
            return {
                "security_findings": [],
                "security_score": 0,
                "errors": state.get("errors", []) + ["Failed to parse security scan response"],
            }

        findings = parsed.get("findings", [])
        score = parsed.get("score", 50)

        elapsed = time.time() - start
        logger.info(f"security_scan_done: {elapsed:.2f}s, findings={len(findings)}, score={score}")

        return {
            "security_findings": findings,
            "security_score": score,
            "phase_outputs": {
                **state.get("phase_outputs", {}),
                "security_scan": {"findings": findings, "score": score, "elapsed": elapsed},
            },
        }

    return security_scan_node
