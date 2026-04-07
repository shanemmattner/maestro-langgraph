"""Zero-LLM prompt quality linter with regex-based rules."""

import re
from pathlib import Path
from typing import Any


# Valid section headers (case-insensitive)
VALID_SECTIONS = {
    "ROLE",
    "TASK",
    "CONSTRAINTS",
    "RULES",
    "OUTPUT",
    "VERIFY",
    "BEHAVIOR",
}


def _check_constraints(text: str) -> bool:
    """Rule 1: Has CONSTRAINTS section (case-insensitive header search)."""
    pattern = r"(?m)^\s*#*\s*CONSTRAINTS\s*[:\-]?\s*$"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _check_behavior_or_rules(text: str) -> bool:
    """Rule 2: Has BEHAVIOR or RULES section."""
    pattern = r"(?m)^\s*#*\s*(BEHAVIOR|RULES)\s*[:\-]?\s*$"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _check_structured_sections(text: str) -> bool:
    """Rule 3: Has >= 3 structured sections from: ROLE, TASK, CONSTRAINTS, RULES, OUTPUT, VERIFY, BEHAVIOR."""
    found_sections = set()
    for section in VALID_SECTIONS:
        pattern = rf"(?m)^\s*#*\s*{section}\s*[:\-]?\s*$"
        if re.search(pattern, text, re.IGNORECASE):
            found_sections.add(section)
    return len(found_sections) >= 3


def _check_verify_section(text: str) -> bool:
    """Rule 4: Has VERIFY section."""
    pattern = r"(?m)^\s*#*\s*VERIFY\s*[:\-]?\s*$"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _check_no_expert_persona(text: str) -> bool:
    """Rule 5: No expert persona markers ('world-class', 'expert', '20 years', 'seasoned')."""
    expert_patterns = [
        r"world[-\s]class",
        r"\bexpert\b",
        r"\bexperts\b",
        r"20\s+years",
        r"\bseasoned\b",
    ]
    for pattern in expert_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False
    return True


def _check_uncertainty_signals(text: str) -> bool:
    """Rule 6: Has uncertainty signals ('CANNOT_ACCESS', 'UNCERTAIN', 'CONFLICT', or similar)."""
    uncertainty_patterns = [
        r"\bCANNOT_ACCESS\b",
        r"\bUNCERTAIN\b",
        r"\bCONFLICT\b",
        r"\bUNKNOWN\b",
        r"\bMAY_NOT_KNOW\b",
        r"\bLIMITED_CONTEXT\b",
        r"\bCANNOT_VERIFY\b",
    ]
    for pattern in uncertainty_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _check_security_boundaries(text: str) -> bool:
    """Rule 7: Has security boundaries if agent uses tools (mentions file/bash access limits)."""
    has_file_ops = bool(re.search(r"\b(file|read|write|edit)\b", text, re.IGNORECASE))
    has_bash_ops = bool(re.search(r"\b(bash|shell|execute|run command)\b", text, re.IGNORECASE))

    if not (has_file_ops or has_bash_ops):
        return True

    security_patterns = [
        r"\b(security|safe[ty]|restrict|limit|permission|access control)\b",
        r"\b(read[-\s]only|no[-\s]write|restricted)\b",
        r"\b(no bash|no shell|don't run|avoid executing)\b",
        r"\b(user confirm|ask first|permission)\b",
        r"\bwhite ?list|black ?list|allow ?list\b",
        r"\bsandbox\b",
    ]
    for pattern in security_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _check_no_cot_scaffolding(text: str) -> bool:
    """Rule 8: No CoT scaffolding ('think step by step', 'chain of thought', 'let's think')."""
    cot_patterns = [
        r"think\s+step\s+by\s+step",
        r"chain\s+of\s+thought",
        r"let'?s\s+think",
        r"reason\s+through",
        r"break\s+it\s+down",
        r"step[-\s]by[-\s]step",
    ]
    for pattern in cot_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False
    return True


def _check_no_banned_phrases(text: str) -> bool:
    """Rule 9: No banned phrases ('let me know if', 'would you like', 'feel free to')."""
    banned_patterns = [
        r"let\s+me\s+know\s+if",
        r"would\s+you\s+like",
        r"feel\s+free\s+to",
        r"do\s+you\s+want",
        r"shall\s+we",
        r"would\s+you\s+mind",
    ]
    for pattern in banned_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False
    return True


def _check_no_tmp_paths(text: str) -> bool:
    """Rule 10: No hardcoded /tmp/ paths."""
    tmp_pattern = r"/tmp/[^\s]*"
    return not bool(re.search(tmp_pattern, text))


def lint_prompt(text: str) -> dict[str, Any]:
    """Lint a prompt text against 10 regex-based rules.

    Args:
        text: The prompt text to lint.

    Returns:
        A dictionary with:
        - score: Number of passed rules (0-10)
        - max_score: Maximum possible score (10)
        - passed: List of passed rule names
        - failed: List of failed rule names
        - ok: True if score >= 7, False otherwise
    """
    rules = [
        ("has_constraints", _check_constraints),
        ("has_behavior_or_rules", _check_behavior_or_rules),
        ("has_structured_sections", _check_structured_sections),
        ("has_verify_section", _check_verify_section),
        ("no_expert_persona", _check_no_expert_persona),
        ("has_uncertainty_signals", _check_uncertainty_signals),
        ("has_security_boundaries", _check_security_boundaries),
        ("no_cot_scaffolding", _check_no_cot_scaffolding),
        ("no_banned_phrases", _check_no_banned_phrases),
        ("no_tmp_paths", _check_no_tmp_paths),
    ]

    passed = []
    failed = []

    for rule_name, rule_func in rules:
        if rule_func(text):
            passed.append(rule_name)
        else:
            failed.append(rule_name)

    score = len(passed)
    max_score = len(rules)

    return {
        "score": score,
        "max_score": max_score,
        "passed": passed,
        "failed": failed,
        "ok": score >= 7,
    }


def lint_all_prompts(directory: str | Path) -> list[dict[str, Any]]:
    """Lint all .txt files in a directory tree.

    Args:
        directory: The root directory to search for .txt files.

    Returns:
        A list of lint results, one per .txt file found.
        Each result includes the file path and lint output.
    """
    directory = Path(directory)
    results = []

    for txt_file in directory.rglob("*.txt"):
        try:
            text = txt_file.read_text(encoding="utf-8")
            lint_result = lint_prompt(text)
            results.append({
                "file": str(txt_file),
                **lint_result,
            })
        except Exception as e:
            results.append({
                "file": str(txt_file),
                "error": str(e),
                "score": 0,
                "max_score": 10,
                "passed": [],
                "failed": [],
                "ok": False,
            })

    return results
