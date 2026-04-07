"""Patch node for bug_hunter workflow."""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_patch_node(config: Dict[str, Any], prompts_dir: str):
    """Factory function to create a patch node."""
    prompts_path = Path(prompts_dir)
    
    def patch_node(state: Dict[str, Any]) -> Dict[str, Any]:
        bug_description = state.get("bug_description", "")
        root_cause = state.get("root_cause", "")
        affected_files = state.get("affected_files", [])
        repo_context = state.get("repo_context", {})
        attempt = state.get("patch_attempt", 0)
        max_attempts = config.get("loops", {}).get("max_patch_attempts", 2)
        
        # Load prompt template
        prompt_template = _load_prompt("patch", prompts_path)
        
        # Build prompt
        prompt = prompt_template.format(
            bug_description=bug_description,
            root_cause=root_cause,
            affected_files=", ".join(affected_files),
            repo_context=str(repo_context),
            attempt=attempt + 1,
            max_attempts=max_attempts
        )
        
        # Call LLM
        models = config.get("phases", {}).get("patch", ["MiniMax-M2.5-highspeed"])
        response = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="patch",
            config=config,
            system_prompt="You are an expert software engineer. Create a fix for the bug based on the root cause analysis."
        )

        # Extract result
        result = extract_json(response.get("content", "") if isinstance(response, dict) else response) or {}
        
        patch_content = result.get("patch_content", "")
        patch_files = result.get("patch_files", [])
        patch_description = result.get("patch_description", "")
        
        new_state = {
            "patch_content": patch_content,
            "patch_files": patch_files,
            "patch_description": patch_description,
            "patch_attempt": attempt + 1,
        }
        
        # Always go to verify after patching
        new_state["next_phase"] = "verify"
            
        return new_state
    
    return patch_node
