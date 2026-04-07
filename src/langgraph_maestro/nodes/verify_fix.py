"""Verify fix node — shared by bug_hunter and refactor workflows."""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json
from langgraph_maestro.core.config import get_models_for_phase

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_verify_fix_node(config: Dict[str, Any], prompts_dir: str):
    """Factory function to create a verify fix node."""
    prompts_path = Path(prompts_dir)
    
    def verify_fix_node(state: Dict[str, Any]) -> Dict[str, Any]:
        # Support both bug_hunter and refactor workflows
        # Refactor workflow uses goal/plan/changes, bug_hunter uses bug_description/patch_content
        goal = state.get("goal", "")
        # Support both refactor (refactor_plan) and generic (plan) field names
        plan = state.get("plan", "") or str(state.get("refactor_plan", ""))
        # Use completed_changes from state (mapped to 'changes' in prompt)
        changes = state.get("completed_changes", state.get("changes", ""))
        failed_changes = state.get("failed_changes", "")
        
        # Bug hunter fields (for backward compatibility)
        bug_description = state.get("bug_description", "")
        patch_content = state.get("patch_content", "")
        patch_files = state.get("patch_files", [])
        reproduction_output = state.get("reproduction_output", "")
        repo_context = state.get("repo_context", {})
        
        # Load prompt template
        prompt_template = _load_prompt("verifier", prompts_path)
        
        # Build prompt - use refactor fields if available, otherwise bug_hunter fields
        # Check for refactor workflow by presence of goal OR refactor_plan in state
        is_refactor = bool(goal or state.get("refactor_plan"))
        if is_refactor:
            # Convert list fields to strings for prompt substitution
            changes_str = str(changes) if not isinstance(changes, str) else changes
            failed_changes_str = str(failed_changes) if not isinstance(failed_changes, str) else failed_changes
            prompt = (prompt_template
                      .replace("{goal}", goal)
                      .replace("{plan}", plan)
                      .replace("{changes}", changes_str)
                      .replace("{failed_changes}", failed_changes_str))
        else:
            prompt = (prompt_template
                      .replace("{bug_description}", bug_description)
                      .replace("{patch_content}", patch_content)
                      .replace("{patch_files}", ", ".join(patch_files))
                      .replace("{reproduction_output}", reproduction_output)
                      .replace("{repo_context}", str(repo_context)))
        
        # Call LLM
        models = get_models_for_phase("verify", config)
        response = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="verify",
            config=config,
            system_prompt="You are an expert QA engineer. Verify that the patch fixes the bug and doesn't introduce regressions."
        )

        # Extract result
        result = extract_json(response.get("content", "") if isinstance(response, dict) else response) or {}
        
        # Support both refactor and bug_hunter output formats
        if is_refactor:
            # Refactor workflow output
            tests_pass = result.get("tests_pass", False)
            verdict = result.get("verdict", "FAILED")
            summary = result.get("summary", "")
            issues = result.get("issues", [])
            
            new_state = {
                "tests_pass": tests_pass,
                "verdict": verdict,
                "verification_output": summary,
                "issues": issues,
                "next_phase": "end",
            }
        else:
            # Bug hunter workflow output
            fix_verified = result.get("fix_verified", False)
            verification_output = result.get("verification_output", "")
            test_results = result.get("test_results", "")
            
            new_state = {
                "fix_verified": fix_verified,
                "verification_output": verification_output,
                "test_results": test_results,
                "next_phase": "end",
            }
            
        return new_state
    
    return verify_fix_node
