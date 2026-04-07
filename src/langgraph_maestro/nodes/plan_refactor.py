"""Plan refactor node — creates a detailed refactoring plan."""

import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def make_plan_refactor_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a plan refactor node with the given configuration.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def plan_refactor_node(state: dict) -> dict:
        """Create a detailed refactoring plan based on analysis.
        
        Uses the analysis from analyze_code_node to create
        a step-by-step plan for refactoring the code.
        """
        start = time.time()
        goal = state.get("goal", "")
        analysis = state.get("analysis", "")
        target_files = state.get("target_files", [])
        cwd = state.get("cwd")
        
        if not cwd:
            return {"error": "cwd is required for plan_refactor_node"}
        
        if not analysis:
            return {"error": "analysis is required for plan_refactor_node"}
        
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("plan", config)
        
        logger.info("plan_refactor_start", extra={"goal": goal, "num_files": len(target_files)})
        
        files_list = "\n".join(f"- {f}" for f in target_files)
        
        # Build prompt
        template = _load_prompt("planner", prompts_path)
        if template:
            prompt = template.replace("{goal}", goal)
            prompt = prompt.replace("{analysis}", analysis)
            prompt = prompt.replace("{files}", files_list)
        else:
            prompt = f"""Based on this analysis, create a detailed refactoring plan:

Goal: {goal}

Analysis:
{analysis}

Files to refactor:
{files_list}

Create a step-by-step refactoring plan with:
1. Specific file changes needed
2. Order of operations
3. Code modifications to make
4. Any new files to create"""

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "plan" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)
        
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="plan",
            config=config,
            cwd=cwd,
        )
        
        plan = result.get("content", "")
        
        elapsed = round(time.time() - start, 3)
        logger.info(
            "plan_refactor_done",
            extra={
                "goal": goal,
                "plan_len": len(plan),
                "elapsed": elapsed,
            },
        )
        
        return {
            "plan": plan,
            "phase": "plan",
        }

    return plan_refactor_node
