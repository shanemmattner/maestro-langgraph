"""Fetch PR node — fetches PR details via gh CLI."""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: str | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        check=True,
        capture_output=capture,
    )


def make_fetch_pr_node() -> callable:
    """Create a fetch_pr_node that fetches PR details via gh CLI."""
    
    def fetch_pr_node(state: dict) -> dict:
        """Fetch PR details via gh CLI and prepare for analysis."""
        pr_url = state.get("pr_url", "")

        m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
        if not m:
            return {"errors": [f"Cannot parse PR URL: {pr_url}"], "phase": "fetch"}

        slug, number = m.group(1), m.group(2)

        logger.info("fetch_pr_start", extra={"pr_url": pr_url})

        try:
            # Get PR details via gh CLI
            result = _run(
                ["gh", "pr", "view", number, "--repo", slug,
                 "--json", "number,title,body,author,baseRefName,headRefName,files"],
                capture=True,
            )
            data = json.loads(result.stdout)

            # Get PR diff via gh CLI
            diff_result = _run(
                ["gh", "pr", "diff", number, "--repo", slug],
                capture=True,
            )
            pr_diff = diff_result.stdout

        except Exception as exc:
            return {"errors": [f"gh pr fetch failed: {exc}"], "phase": "fetch"}

        pr_number = data.get("number", int(number))
        pr_title = data.get("title", "")
        pr_body = data.get("body", "") or ""
        pr_author = data.get("author", {}).get("login", "")
        base_branch = data.get("baseRefName", "")
        head_branch = data.get("headRefName", "")
        changed_files = [f.get("path", "") for f in data.get("files", [])]

        logger.info("fetch_pr_done", extra={"pr_number": pr_number, "pr_title": pr_title})

        return {
            "pr_number": pr_number,
            "pr_title": pr_title,
            "pr_body": pr_body,
            "pr_diff": pr_diff,
            "pr_author": pr_author,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "changed_files": changed_files,
            "phase": "fetch",
        }

    return fetch_pr_node
