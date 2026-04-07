"""Prompt engineering middleware.

Runs a PE pass on prompts before they reach the actual LLM,
applying techniques from the PE checklist.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from langgraph_maestro.core.config import get_pe_enabled

logger = logging.getLogger(__name__)

_PE_SYSTEM_PROMPT = (
    "You are a prompt engineer. Apply the techniques from the PE checklist "
    "to improve the following prompt. Return ONLY the improved prompt text, "
    "nothing else."
)


def _find_checklist() -> str | None:
    """Search upward from this file for pe-checklist.md."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        candidate = current / ".claude" / "skills" / "prompt-eng-knowledge" / "pe-checklist.md"
        if candidate.is_file():
            return candidate.read_text()
        current = current.parent
    return None


def improve_prompt(
    raw_prompt: str,
    model: str = "MiniMax-M2.5-highspeed",
    config: dict[str, Any] | None = None,
) -> str:
    """Run PE pass on a prompt. Returns improved prompt or raw_prompt on failure."""
    pe_config = (config or {}).get("prompt_engineering", {})

    # Load checklist
    checklist_path = pe_config.get("checklist_path")
    if checklist_path and Path(checklist_path).is_file():
        checklist = Path(checklist_path).read_text()
    else:
        checklist = _find_checklist()

    if not checklist:
        logger.warning("pe_checklist_not_found")
        return raw_prompt

    pe_model = pe_config.get("model", model)
    pe_timeout = pe_config.get("timeout", 120)

    try:
        from langgraph_maestro.core.llm import call_llm

        result = call_llm(
            prompt=f"## PE Checklist\n{checklist}\n\n## Prompt to improve\n{raw_prompt}",
            model=pe_model,
            system_prompt=_PE_SYSTEM_PROMPT,
            timeout=pe_timeout,
        )

        content = result.get("content", "").strip()
        if content:
            logger.info(
                "pe_improved",
                extra={"original_len": len(raw_prompt), "improved_len": len(content)},
            )
            return content

        logger.warning("pe_empty_response")
        return raw_prompt

    except Exception as e:
        logger.warning("pe_failed", extra={"error": str(e)})
        return raw_prompt


def pe_node_factory(phase_name: str, config: dict[str, Any]) -> Callable:
    """Create a LangGraph node that runs PE on the prompt for a phase.

    If PE is disabled in config, returns a passthrough node.
    """
    enabled = get_pe_enabled(phase_name, config)

    if not enabled:
        def passthrough(state: dict) -> dict:
            return {}
        return passthrough

    def pe_node(state: dict) -> dict:
        task = state.get("task", "")
        if not task:
            return {}

        improved = improve_prompt(task, config=config)
        return {f"pe_{phase_name}_prompt": improved}

    return pe_node
