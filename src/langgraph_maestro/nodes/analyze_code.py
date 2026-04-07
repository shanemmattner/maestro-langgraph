"""Analyze code node — scans and analyzes codebase for refactoring goals."""

import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)

MAX_FILES = 10
MAX_LINES_PER_FILE = 200


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def _scan_python_files(cwd: str, max_files: int = MAX_FILES) -> list[str]:
    """Scan cwd for Python files, excluding __pycache__ and .venv."""
    py_files = []
    cwd_path = Path(cwd)
    
    if not cwd_path.exists():
        return []
    
    for root, dirs, files in os.walk(cwd_path):
        # Skip unwanted directories
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.venv', '.git', 'node_modules', '.pytest_cache')]
        
        for f in files:
            if f.endswith('.py') and not f.startswith('.'):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, cwd)
                py_files.append(rel_path)
                
                if len(py_files) >= max_files:
                    return py_files
    
    return py_files


def _read_file_content(path: Path, max_lines: int = MAX_LINES_PER_FILE) -> str:
    """Read file content with line limit."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        content = '\n'.join(lines[:max_lines])
        if len(lines) > max_lines:
            content += f"\n... ({len(lines) - max_lines} more lines)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def make_analyze_code_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create an analyze code node with the given configuration.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def analyze_code_node(state: dict) -> dict:
        """Analyze the codebase for the refactoring goal.
        
        If target_files is empty, auto-discovers Python files.
        Reads up to 10 files, 200 lines each.
        Returns analysis and discovered target_files.
        """
        start = time.time()
        cwd = state.get("cwd")
        goal = state.get("goal", "")
        target_files = state.get("target_files", [])
        
        if not cwd:
            return {"error": "cwd is required for analyze_code_node"}
        
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("analyze", config)
        
        logger.info("analyze_code_start", extra={"goal": goal, "cwd": cwd})
        
        # Auto-discover files if none specified
        if not target_files:
            target_files = _scan_python_files(cwd, MAX_FILES)
            logger.info("auto_discover_files", extra={"num_files": len(target_files)})
        
        # Read file contents
        file_contents = []
        cwd_path = Path(cwd)
        for rel_path in target_files[:MAX_FILES]:
            full_path = cwd_path / rel_path
            if full_path.exists():
                content = _read_file_content(full_path, MAX_LINES_PER_FILE)
                file_contents.append(f"## {rel_path}\n{content}\n")
        
        files_text = "\n\n".join(file_contents)
        
        # Build prompt
        template = _load_prompt("analyzer", prompts_path)
        if template:
            prompt = template.replace("{goal}", goal)
            prompt = prompt.replace("{files}", files_text)
        else:
            prompt = f"""Analyze this codebase for the refactoring goal: {goal}

What patterns exist in the code? What specific changes are needed to achieve this goal?

Files to analyze:
{files_text}

Provide a detailed analysis covering:
1. Current patterns and code structure
2. Specific issues that need to be addressed
3. Recommended approach for the refactor"""

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "analyze" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)
        
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="analyze",
            config=config,
            cwd=cwd,
        )
        
        analysis = result.get("content", "")
        
        elapsed = round(time.time() - start, 3)
        logger.info(
            "analyze_code_done",
            extra={
                "goal": goal,
                "num_files": len(target_files),
                "analysis_len": len(analysis),
                "elapsed": elapsed,
            },
        )
        
        return {
            "analysis": analysis,
            "target_files": target_files,
            "phase": "analyze",
        }

    return analyze_code_node
