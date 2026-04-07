"""Concrete verification — syntax check, import check, test execution."""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def verify_subtask(
    cwd: str,
    changed_files: list[str],
    generated_tests: list[str] | None = None,
) -> dict:
    """Verify a subtask's output with concrete checks.

    Runs:
    1. py_compile for each .py file
    2. pytest on generated tests if they exist

    Returns: {"pass": bool, "errors": [str]}
    """
    errors = []
    cwd_path = Path(cwd)

    # 1. Syntax check all changed .py files
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        fpath = cwd_path / f
        if not fpath.is_file():
            continue
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(fpath)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            errors.append(f"syntax error in {f}: {r.stderr.strip()}")

    # 2. Run generated tests if they exist
    if generated_tests:
        test_files = [str(cwd_path / t) for t in generated_tests if (cwd_path / t).is_file()]
        if test_files:
            r = subprocess.run(
                [sys.executable, "-m", "pytest"] + test_files + ["-x", "--tb=short", "-q"],
                cwd=cwd, capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                # Extract just the failure summary
                output = r.stdout[-500:] if len(r.stdout) > 500 else r.stdout
                errors.append(f"test failures: {output.strip()}")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
    }
