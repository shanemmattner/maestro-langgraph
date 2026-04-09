"""Decompose node — breaks task into subtasks using decomposer LLM."""

import logging
import time
from pathlib import Path
from typing import Any, Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json, rescue_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_decompose_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a decompose node with the given configuration.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def decompose_node(state: dict) -> dict:
        """Break task into subtasks using decomposer LLM."""
        start = time.time()
        task = state.get("task", "")
        cwd = state.get("cwd") or state.get("repo_path")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("decompose", config)

        logger.info("decompose_start", extra={"task": task[:100]})

        template = _load_prompt("decomposer", prompts_path)
        prompt = template.replace("{task}", task)

        # PE pass: improve prompt before LLM call
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "decompose" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)

        try:
            response = call_llm_with_fallback(
                prompt=prompt,
                models=models,
                phase="decompose",
                config=config,
                cwd=cwd,
                system_prompt="You are a task decomposition agent. Return valid JSON only.",
            )
        except Exception as exc:
            logger.error("decompose_structured_failed", extra={"error": str(exc)})
            return {
                "errors": [f"Structured decompose failed: {exc}"],
                "phase": "decompose",
            }

        content = response.get("content", "")
        parsed = extract_json(content)
        if parsed is None:
            parsed = rescue_json(content) or {}

        raw_subtasks = parsed.get("subtasks", [])
        if not isinstance(raw_subtasks, list):
            raw_subtasks = []

        subtasks = []
        for item in raw_subtasks:
            if isinstance(item, dict):
                subtasks.append(item)

        # Normalize: ensure each subtask has runtime tracking fields
        for i, t in enumerate(subtasks):
            if not t.get("id"):
                t["id"] = f"{i+1}-task"
            t.setdefault("status", "pending")
            t.setdefault("attempts", 0)

        strategy = parsed.get("strategy", "execute")
        if strategy not in ("execute", "split", "refine", "blocked"):
            strategy = "execute"

        elapsed = round(time.time() - start, 3)

        logger.info(
            "decompose_done",
            extra={
                "num_subtasks": len(subtasks),
                "strategy": strategy,
                "elapsed": elapsed,
            },
        )

        return {
            "subtasks": subtasks,
            "strategy": strategy,
            "phase": "decompose",
        }

    return decompose_node
