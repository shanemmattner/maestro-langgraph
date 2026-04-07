"""Fetch issue node — fetches GitHub issue via gh CLI."""

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: str | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        check=True,
        capture_output=capture,
    )


def _is_repo_archived(repo_slug: str) -> bool:
    """Check if a GitHub repository is archived using gh CLI."""
    try:
        result = _run(
            ["gh", "repo", "view", repo_slug, "--json", "isArchived"],
            capture=True,
        )
        data = json.loads(result.stdout)
        return data.get("isArchived", False)
    except Exception:
        return False


def make_fetch_issue_node() -> callable:
    """Create a fetch_issue_node that fetches GitHub issue via gh CLI."""
    
    def fetch_issue_node(state: dict) -> dict:
        """Fetch GitHub issue via gh CLI and prepare the task description."""
        issue_url = state.get("issue_url", "")

        m = re.match(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", issue_url)
        if not m:
            return {"errors": [f"Cannot parse issue URL: {issue_url}"], "phase": "fetch"}

        repo_slug, number = m.group(1), m.group(2)

        # Early check: fail fast if repository is archived (read-only)
        if _is_repo_archived(repo_slug):
            return {"errors": [f"Repository {repo_slug} is archived (read-only)"], "phase": "fetch"}

        logger.info("fetch_issue_start", extra={"issue_url": issue_url})

        try:
            result = _run(
                ["gh", "issue", "view", number, "--repo", repo_slug,
                 "--json", "number,title,body,labels,state"],
                capture=True,
            )
            data = json.loads(result.stdout)
        except Exception as exc:
            return {"errors": [f"gh issue fetch failed: {exc}"], "phase": "fetch"}

        title = data.get("title", "")
        body = data.get("body", "") or ""
        issue_number = data.get("number", int(number))

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
        branch_name = f"issue-{issue_number}-{slug}"

        # Guard against empty issue body (e.g., private issues or fetch failures)
        if not body.strip():
            return {
                "errors": [f"Issue #{issue_number} has empty body - cannot proceed with decomposition"],
                "phase": "fetch",
            }

        task = f"GitHub Issue #{issue_number}: {title}\n\n{body}".strip()

        logger.info("fetch_issue_done", extra={"issue_number": issue_number, "title": title})

        return {
            "issue_number": issue_number,
            "issue_title": title,
            "issue_body": body,
            "branch_name": branch_name,
            "task": task,
            "phase": "fetch",
        }

    return fetch_issue_node
