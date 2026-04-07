"""E2E test selector — node implementations."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from langgraph_maestro.core.config import load_config, get_models_for_phase, workflow_config_path
from langgraph_maestro.core.e2e_discovery import discover_tests, list_test_summaries
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json
from .state import E2ETestSelectorState, TestResult

logger = logging.getLogger(__name__)


def analyze_pr_node(state: E2ETestSelectorState) -> dict:
    """Parse the PR diff to identify changed files and summarize changes."""
    pr_diff = state.get("pr_diff", "")

    changed_files = re.findall(r"^\+\+\+ [ab]/(.+)$", pr_diff, re.MULTILINE)

    config = load_config(state.get("config_path", workflow_config_path(__file__)))
    models = get_models_for_phase("analyze", config)

    # Ask LLM for a brief change summary
    prompt = f"""Summarize these code changes in 2-3 sentences. Focus on what functionality is affected.

Changed files:
{chr(10).join(changed_files)}

Diff (truncated to 3000 chars):
{pr_diff[:3000]}"""

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="analyze",
            config=config,
            system_prompt="You are a code reviewer. Summarize changes concisely.",
        )
        change_summary = result.get("content", "No summary available.")
    except Exception as exc:
        logger.error("analyze_failed", extra={"error": str(exc)})
        change_summary = f"Changed files: {', '.join(changed_files)}"

    return {
        "changed_files": changed_files,
        "change_summary": change_summary,
        "phase": "analyze",
    }


def discover_tests_node(state: E2ETestSelectorState) -> dict:
    """Discover available E2E tests in the repo."""
    repo_path = state.get("repo_path", ".")
    available = list_test_summaries(repo_path)

    logger.info("tests_discovered", extra={"count": len(available)})

    return {
        "available_tests": available,
        "phase": "discover",
    }


def select_tests_node(state: E2ETestSelectorState) -> dict:
    """LLM selects which tests to run based on PR changes."""
    config = load_config(state.get("config_path", workflow_config_path(__file__)))
    models = get_models_for_phase("select", config)

    available = state.get("available_tests", [])
    if not available:
        return {
            "selected_tests": [],
            "selection_reasoning": "No tests available.",
            "phase": "select",
        }

    # Load example runs if available
    repo_path = state.get("repo_path", ".")
    examples_dir = Path(repo_path) / "tests" / "llm_e2e" / "examples"
    example_text = ""
    if examples_dir.is_dir():
        for f in sorted(examples_dir.glob("*.json"))[:3]:
            try:
                example_text += f"\n--- {f.name} ---\n{f.read_text()[:500]}\n"
            except Exception:
                pass

    tests_listing = json.dumps(available, indent=2)

    prompt = f"""Given a PR that changes the following, select which E2E tests should run.

## PR Changes
Changed files: {', '.join(state.get('changed_files', []))}
Summary: {state.get('change_summary', 'N/A')}

## Available E2E Tests
{tests_listing}

## Past Run Examples
{example_text or 'No past examples available.'}

## Instructions
- Select tests whose functionality could be affected by the PR changes.
- If the PR only changes documentation/README, select 0 tests.
- If the PR changes core bot logic, select all tests.
- If the PR changes a specific tool (e.g., gcal.py), select the corresponding test.

Return JSON: {{"selected_tests": ["test_name_1", "test_name_2"], "reasoning": "..."}}"""

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="select",
            config=config,
            system_prompt="You are a test selector. Pick relevant E2E tests for a PR. Return JSON only.",
        )
        parsed = extract_json(result.get("content", ""))

        if parsed and isinstance(parsed, dict):
            selected = parsed.get("selected_tests", [])
            reasoning = parsed.get("reasoning", "")
        else:
            selected = [t["name"] for t in available]
            reasoning = "LLM parse failed, running all tests."
    except Exception as exc:
        logger.error("select_failed", extra={"error": str(exc)})
        selected = [t["name"] for t in available]
        reasoning = f"Selection failed ({exc}), running all tests."

    # Validate selected tests exist
    valid_names = {t["name"] for t in available}
    selected = [s for s in selected if s in valid_names]

    logger.info("tests_selected", extra={"count": len(selected), "tests": selected})

    return {
        "selected_tests": selected,
        "selection_reasoning": reasoning,
        "phase": "select",
    }


def run_tests_node(state: E2ETestSelectorState) -> dict:
    """Run selected E2E tests and collect results with per-phase timing."""
    repo_path = state.get("repo_path", ".")
    selected = state.get("selected_tests", [])

    if not selected:
        return {
            "test_results": [],
            "overall_passed": True,
            "phase": "run",
        }

    # Import test graph builders
    all_tests = discover_tests(repo_path)
    test_map = {t["name"]: t for t in all_tests}

    results: list[TestResult] = []

    for test_name in selected:
        test_info = test_map.get(test_name)
        if not test_info:
            results.append({
                "test_name": test_name,
                "passed": False,
                "details": f"Test '{test_name}' not found in discovery",
                "error": "not_found",
            })
            continue

        logger.info("running_test", extra={"test": test_name})
        test_start = time.monotonic()

        try:
            graph = test_info["graph_builder"]()
            compiled = graph.compile()

            # Run the test workflow with phase timing via stream
            phase_timings = {}
            final_state = {}
            phase_start = time.monotonic()

            for event in compiled.stream(
                {
                    "test_name": test_name,
                    "pr_diff": state.get("pr_diff", ""),
                    "repo_path": repo_path,
                },
                stream_mode="updates",
            ):
                now = time.monotonic()
                for node_name, node_output in event.items():
                    phase_timings[f"{node_name}_s"] = round(now - phase_start, 2)
                    phase_start = now
                    final_state.update(node_output)

            phase_timings["total_s"] = round(time.monotonic() - test_start, 2)

            assertion = final_state.get("assertion_result", {})
            results.append({
                "test_name": test_name,
                "passed": assertion.get("passed", False),
                "details": assertion.get("details", ""),
                "checks": assertion.get("checks", []),
                "response_time_s": final_state.get("response_time_s"),
                "phase_timings": phase_timings,
            })

        except Exception as exc:
            logger.error("test_failed", extra={"test": test_name, "error": str(exc)})
            elapsed = round(time.monotonic() - test_start, 2)
            results.append({
                "test_name": test_name,
                "passed": False,
                "details": str(exc),
                "error": str(exc),
                "phase_timings": {"total_s": elapsed},
            })

    overall = all(r.get("passed") for r in results) if results else True

    return {
        "test_results": results,
        "overall_passed": overall,
        "phase": "run",
    }


def report_node(state: E2ETestSelectorState) -> dict:
    """Generate markdown report of E2E test results."""
    pr_number = state.get("pr_number", "?")
    results = state.get("test_results", [])
    selected = state.get("selected_tests", [])
    overall = state.get("overall_passed", True)

    passed_count = sum(1 for r in results if r.get("passed"))
    failed_count = len(results) - passed_count

    lines = [
        f"# E2E Test Report: PR #{pr_number}",
        "",
        f"## Selection",
        f"- **Tests available**: {len(state.get('available_tests', []))}",
        f"- **Tests selected**: {len(selected)}",
        f"- **Reasoning**: {state.get('selection_reasoning', 'N/A')}",
        "",
        f"## Results: {passed_count} passed, {failed_count} failed {'✅' if overall else '❌'}",
        "",
    ]

    if not results:
        lines.append("No tests were selected for this PR.")
    else:
        # Summary table
        lines.append("| Test | Status | Response | Total |")
        lines.append("|------|--------|----------|-------|")
        for r in results:
            icon = "✅" if r.get("passed") else "❌"
            resp = f"{r['response_time_s']:.1f}s" if r.get("response_time_s") else "—"
            timings = r.get("phase_timings", {})
            total = f"{timings['total_s']:.1f}s" if timings.get("total_s") else "—"
            lines.append(f"| {r['test_name']} | {icon} | {resp} | {total} |")

        # Detailed results for failures
        failures = [r for r in results if not r.get("passed")]
        if failures:
            lines.append("")
            lines.append("## Failure Details")
            for r in failures:
                lines.append(f"\n### ❌ {r['test_name']}")
                if r.get("checks"):
                    for check in r["checks"]:
                        c_icon = "✅" if check.get("passed") else "❌"
                        lines.append(f"- {c_icon} {check.get('detail', '')}")
                if r.get("error"):
                    lines.append(f"- **Error**: {r['error']}")

                # Phase timing breakdown
                timings = r.get("phase_timings", {})
                if timings:
                    timing_parts = [f"{k}: {v}s" for k, v in timings.items() if k != "total_s"]
                    if timing_parts:
                        lines.append(f"- **Timing**: {', '.join(timing_parts)}")

    report = "\n".join(lines)

    return {
        "report": report,
        "phase": "report",
    }


def publish_node(state: E2ETestSelectorState) -> dict:
    """Publish results: save JSON to disk, post GitHub PR comment, notify Discord."""
    pr_number = state.get("pr_number", "?")
    pr_url = state.get("pr_url", "")
    repo_path = state.get("repo_path", ".")
    report = state.get("report", "")
    results = state.get("test_results", [])
    overall = state.get("overall_passed", True)

    output = {
        "phase": "publish",
        "results_file": "",
        "pr_comment_posted": False,
        "discord_notified": False,
    }

    # --- 1. Save results JSON to examples/ ---
    try:
        examples_dir = Path(repo_path) / "tests" / "llm_e2e" / "examples"
        examples_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        results_file = examples_dir / f"{date_str}_pr{pr_number}.json"

        results_data = {
            "pr_number": pr_number,
            "pr_url": pr_url,
            "timestamp": datetime.now().isoformat(),
            "overall_passed": overall,
            "tests_selected": state.get("selected_tests", []),
            "selection_reasoning": state.get("selection_reasoning", ""),
            "changed_files": state.get("changed_files", []),
            "change_summary": state.get("change_summary", ""),
            "results": results,
        }

        results_file.write_text(json.dumps(results_data, indent=2, default=str))
        output["results_file"] = str(results_file)
        logger.info("results_saved", extra={"path": str(results_file)})
    except Exception as exc:
        logger.error("results_save_failed", extra={"error": str(exc)})

    # --- 2. Post GitHub PR comment ---
    if pr_url and report:
        try:
            # Extract owner/repo and PR number from URL
            parts = pr_url.rstrip("/").split("/")
            gh_pr_number = parts[-1]
            gh_repo = f"{parts[-4]}/{parts[-3]}"

            # Check for existing bot comment to update (avoid spam)
            existing = subprocess.run(
                ["gh", "pr", "view", gh_pr_number, "--repo", gh_repo,
                 "--json", "comments", "--jq",
                 '.comments[] | select(.body | startswith("# E2E Test Report")) | .url'],
                capture_output=True, text=True, timeout=15,
            )

            # Append a footer
            comment_body = report + "\n\n---\n*Generated by langgraph-maestro e2e_test_selector*"

            if existing.returncode == 0 and existing.stdout.strip():
                # Update existing comment
                comment_url = existing.stdout.strip().split("\n")[0]
                # gh doesn't support editing comments directly, just add new one
                # (GitHub will collapse older ones)
                pass

            result = subprocess.run(
                ["gh", "pr", "comment", gh_pr_number, "--repo", gh_repo,
                 "--body", comment_body],
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0:
                output["pr_comment_posted"] = True
                logger.info("pr_comment_posted", extra={"pr": pr_number, "repo": gh_repo})
            else:
                logger.warning("pr_comment_failed", extra={"stderr": result.stderr[:200]})

        except Exception as exc:
            logger.error("pr_comment_error", extra={"error": str(exc)})

    # --- 3. Discord notification via webhook ---
    discord_webhook = _get_discord_webhook()
    if discord_webhook and results:
        try:
            import urllib.request

            passed = sum(1 for r in results if r.get("passed"))
            total = len(results)
            icon = "✅" if overall else "❌"
            summary = f"{icon} **E2E Tests for PR #{pr_number}**: {passed}/{total} passed"

            if not overall:
                failed_names = [r["test_name"] for r in results if not r.get("passed")]
                summary += f"\nFailed: {', '.join(failed_names)}"

            payload = json.dumps({"content": summary}).encode()
            req = urllib.request.Request(
                discord_webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            output["discord_notified"] = True
            logger.info("discord_notified", extra={"pr": pr_number})

        except Exception as exc:
            logger.error("discord_notify_failed", extra={"error": str(exc)})

    return output


def _get_discord_webhook() -> str | None:
    """Get Discord webhook URL from env."""
    import os
    return os.environ.get("DISCORD_WEBHOOK_URL")
