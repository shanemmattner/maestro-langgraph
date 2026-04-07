"""Skill injection system for model-specific prompt overlays.

Loads and applies:
- Model overlays: extra instructions for specific providers (e.g. MiniMax JSON formatting)
- Phase skills: skill content injected for specific workflow phases
- Always skills: injected into every call
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_skill(skill_name: str, search_paths: list[str] | None = None) -> str:
    """Load skill content from file.

    Searches for {skill_name}/instructions.md, {skill_name}.txt, {skill_name}.md
    in each search path.

    Returns file contents or empty string if not found.
    """
    if search_paths is None:
        search_paths = []

    # Add default search paths
    current = Path(__file__).resolve().parent
    while current != current.parent:
        candidate = current / ".claude" / "skills"
        if candidate.is_dir():
            search_paths.append(str(candidate))
            break
        current = current.parent

    patterns = [
        f"{skill_name}/instructions.md",
        f"{skill_name}.txt",
        f"{skill_name}.md",
    ]

    for base in search_paths:
        for pattern in patterns:
            path = Path(base) / pattern
            if path.is_file():
                content = path.read_text()
                logger.info("skill_loaded", extra={"skill": skill_name, "path": str(path)})
                return content

    logger.warning("skill_not_found", extra={"skill": skill_name, "search_paths": search_paths})
    return ""


def get_model_overlay(model: str, config: dict[str, Any]) -> str:
    """Get model-specific prompt overlay from config.

    Matches model string to overlay keys: minimax, local, claude.
    """
    overlays = config.get("skills", {}).get("model_overlays", {})
    if not overlays:
        return ""

    model_lower = model.lower()
    if "minimax" in model_lower:
        return overlays.get("minimax", "")
    if model.startswith("mlx-community/") or model.startswith("local"):
        return overlays.get("local", "")
    return overlays.get("claude", "")


def inject_skills(
    prompt: str,
    system_prompt: str,
    model: str,
    phase: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Apply skill injection to prompt and system_prompt.

    Appends model overlay, phase skills, and always-on skills to system_prompt.
    Returns (prompt, updated_system_prompt).
    """
    if config is None:
        return prompt, system_prompt

    parts = [system_prompt]
    skills_config = config.get("skills", {})
    search_paths = [skills_config["skill_source"]] if "skill_source" in skills_config else []

    # Model overlay
    overlay = get_model_overlay(model, config)
    if overlay:
        parts.append(overlay)
        logger.info("skill_overlay_injected", extra={"model": model})

    # Phase skills
    if phase:
        phase_skills = skills_config.get("phase_skills", {}).get(phase, [])
        for skill_name in phase_skills:
            content = load_skill(skill_name, search_paths)
            if content:
                parts.append(content)
                logger.info("skill_phase_injected", extra={"skill": skill_name, "phase": phase})

    # Always-on skills
    for skill_name in skills_config.get("always", []):
        content = load_skill(skill_name, search_paths)
        if content:
            parts.append(content)
            logger.info("skill_always_injected", extra={"skill": skill_name})

    return prompt, "\n\n".join(parts)
