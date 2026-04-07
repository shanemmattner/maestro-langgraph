"""CLI entry point for langgraph-maestro.

Usage:
    maestro run <workflow> --task "..." [--config PATH] [--cwd PATH] [--json]
    maestro init [--dir PATH] [--name NAME] [--model MODEL]
    maestro list
    maestro verify
    maestro mc "prompt" [--model MODEL] [--cwd PATH] [--timeout N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    """Run a registered workflow by name."""
    from langgraph_maestro.core.registry import get_workflow

    # Trigger workflow registration via side-effect imports
    import langgraph_maestro.workflows  # noqa: F401

    try:
        entry = get_workflow(args.workflow)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Import the run_workflow for the chosen workflow
    module_path = f"langgraph_maestro.workflows.{args.workflow}.graph"
    try:
        import importlib
        mod = importlib.import_module(module_path)
        run_workflow = mod.run_workflow
    except (ImportError, AttributeError) as exc:
        print(f"Error: could not load run_workflow from {module_path}: {exc}", file=sys.stderr)
        return 1

    # Build kwargs from the run_workflow signature
    import inspect
    sig = inspect.signature(run_workflow)
    kwargs: dict = {}

    # Map common CLI args to function parameters
    param_names = set(sig.parameters.keys())

    # The first positional param is typically the task/question/proposal/issue_url etc.
    # We pass --task as the first required positional argument
    first_param = list(sig.parameters.keys())[0]
    if args.task:
        kwargs[first_param] = args.task
    else:
        print(f"Error: --task is required (maps to '{first_param}' parameter)", file=sys.stderr)
        return 1

    if "config_path" in param_names and args.config:
        kwargs["config_path"] = args.config
    elif "config_path" in param_names and entry.get("default_config"):
        kwargs["config_path"] = entry["default_config"]

    if "cwd" in param_names and args.cwd:
        kwargs["cwd"] = args.cwd
    elif "repo_path" in param_names and args.cwd:
        kwargs["repo_path"] = args.cwd

    # Handle async workflows
    if inspect.iscoroutinefunction(run_workflow):
        import asyncio
        result = asyncio.run(run_workflow(**kwargs))
    else:
        result = run_workflow(**kwargs)

    # Output
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_result(args.workflow, result)

    return 0


def _print_result(workflow: str, result: dict) -> None:
    """Pretty-print a workflow result."""
    print(f"\n--- {workflow} result ---")

    if "verdict" in result:
        print(f"Verdict: {result['verdict']}")

    subtasks = result.get("subtasks", [])
    if subtasks:
        print(f"\nSubtasks ({len(subtasks)}):")
        for i, st in enumerate(subtasks, 1):
            status = st.get("status", "pending")
            title = st.get("title", st.get("description", "N/A"))
            print(f"  {i}. [{status}] {title}")

    if "answer" in result:
        print(f"\nAnswer:\n{result['answer']}")

    if "final_answer" in result:
        print(f"\nFinal answer:\n{result['final_answer']}")

    review_issues = result.get("review_issues", [])
    if review_issues:
        print(f"\nReview issues:")
        for issue in review_issues:
            issue_type = issue.get("issue_type", "unknown")
            desc = issue.get("description", "")
            print(f"  - [{issue_type}] {desc}")

    # Fallback: dump keys for workflows with non-standard output
    shown_keys = {"verdict", "subtasks", "answer", "final_answer", "review_issues"}
    remaining = {k: v for k, v in result.items() if k not in shown_keys and v}
    if remaining and not any(k in result for k in shown_keys):
        print(json.dumps(result, indent=2, default=str))


def _cmd_list(args: argparse.Namespace) -> int:
    """List all registered workflows."""
    # Trigger registration
    import langgraph_maestro.workflows  # noqa: F401
    from langgraph_maestro.core.registry import list_workflows

    workflows = list_workflows()
    if not workflows:
        print("No workflows registered.")
        return 0

    print(f"{'Name':<25} Description")
    print(f"{'----':<25} -----------")
    for w in workflows:
        name = w["name"]
        desc = w.get("description", "")
        print(f"{name:<25} {desc}")

    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Run setup verification checks."""
    checks_passed = 0
    checks_failed = 0

    def check(name: str, fn) -> None:
        nonlocal checks_passed, checks_failed
        try:
            result = fn()
            if result:
                print(f"  PASS  {name}")
                checks_passed += 1
            else:
                print(f"  FAIL  {name}")
                checks_failed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            checks_failed += 1

    print("langgraph-maestro setup checks\n")

    check("Python >= 3.11", lambda: sys.version_info >= (3, 11))
    check("import langgraph", lambda: __import__("langgraph") or True)
    check("import yaml", lambda: __import__("yaml") or True)
    check("import anthropic", lambda: __import__("anthropic") or True)

    # Check Langfuse keys (optional)
    import os
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if pk and sk:
        check("Langfuse keys", lambda: True)
    else:
        print("  SKIP  Langfuse keys (not set, optional)")

    # Check workflow registration
    def _check_workflows():
        import langgraph_maestro.workflows  # noqa: F401
        from langgraph_maestro.core.registry import list_workflows
        return len(list_workflows()) > 0
    check("Workflow registry", _check_workflows)

    # Check claude CLI
    def _check_claude_cli():
        import subprocess
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    check("claude CLI", _check_claude_cli)

    print(f"\n{checks_passed} passed, {checks_failed} failed")
    return 0 if checks_failed == 0 else 1


def _cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new workflow from templates."""
    from langgraph_maestro.templates import scaffold_workflow

    target_dir = Path(args.dir).resolve()
    name = args.name or target_dir.name.replace("-", "_")
    model = args.model
    description = args.description or ""

    created = scaffold_workflow(
        target_dir=target_dir,
        workflow_name=name,
        description=description,
        default_model=model,
    )

    print(f"Scaffolded workflow '{name}' in {target_dir}/\n")
    print("Created files:")
    for p in created:
        print(f"  {p.relative_to(target_dir)}")
    print(f"\nNext steps:")
    print(f"  1. Edit config.yaml to configure models and timeouts")
    print(f"  2. Customize prompts/ for your domain")
    print(f"  3. Copy into src/langgraph_maestro/workflows/{name}/ to register")

    return 0


def _cmd_customize(args: argparse.Namespace) -> int:
    """Run the interactive customization workflow."""
    from langgraph_maestro.workflows.customize.graph import run_workflow

    target_dir = Path(args.dir).resolve()
    model = args.model

    print("Starting interactive workflow customization...")
    print("Answer the questions to generate a workflow tailored to your needs.")
    print("Type 'done' at any time to finish early.\n")

    initial_state = {
        "target_dir": str(target_dir),
        "config_path": "",
        "phase": "start",
        "errors": [],
        "interview_history": [],
        "current_round": 0,
        "gathered_context": {},
        "confidence": 0.0,
        "generated_files": {},
        "validation_errors": [],
        "validation_attempts": 0,
    }

    if args.workflow:
        initial_state["source_workflow"] = str(Path(args.workflow).resolve())

    result = run_workflow(initial_state, model=model)

    summary = result.get("final_summary", "Workflow generated.")
    output_dir = result.get("output_dir", str(target_dir))
    print(f"\n{summary}")
    print(f"Output: {output_dir}")
    return 0


def _cmd_mc(args: argparse.Namespace) -> int:
    """Run the mc (minimal claude) agent."""
    from langgraph_maestro.core.mc import build_cmd, run_claude, parse_usage

    prompt = args.prompt
    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read()
        else:
            print("Error: prompt required. Provide as argument or pipe via stdin.", file=sys.stderr)
            return 1

    model = args.model
    if not model:
        print("Error: --model is required for mc subcommand.", file=sys.stderr)
        return 1

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    timeout = args.timeout

    cmd, prompt_text = build_cmd(prompt, model=model)
    print(f"model={model} cwd={cwd}", file=sys.stderr)

    final, elapsed, rc = run_claude(cmd, cwd, timeout=timeout, prompt_stdin=prompt_text)
    u = parse_usage(final)
    total = u["input"] + u["cache_new"] + u["cache_read"]

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final.get("result", ""))
        print(str(out_path))
        return rc

    print(f"tokens: {total:,} in / {u['output']:,} out | {elapsed:.1f}s | ${u['cost']:.4f}",
          file=sys.stderr)
    print()
    print(final.get("result", ""))
    return rc


def main() -> None:
    """CLI entry point for langgraph-maestro."""
    parser = argparse.ArgumentParser(
        prog="maestro",
        description="Multi-agent LLM workflow orchestration framework",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", type=str, help="Workflow name (e.g. default, pr_review)")
    run_parser.add_argument("--task", "-t", required=True, help="Task description or input for the workflow")
    run_parser.add_argument("--config", "-c", default=None, help="Path to workflow config YAML")
    run_parser.add_argument("--cwd", default=None, help="Working directory for code operations")
    run_parser.add_argument("--json", action="store_true", help="Output full result as JSON")
    run_parser.set_defaults(func=_cmd_run)

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List available workflows")
    list_parser.set_defaults(func=_cmd_list)

    # --- verify ---
    verify_parser = subparsers.add_parser("verify", help="Verify setup (dependencies, tracing, etc.)")
    verify_parser.set_defaults(func=_cmd_verify)

    # --- init ---
    init_parser = subparsers.add_parser("init", help="Scaffold a new workflow from templates")
    init_parser.add_argument("--dir", "-d", default=".", help="Target directory (default: current directory)")
    init_parser.add_argument("--name", "-n", default=None, help="Workflow name (default: directory basename)")
    init_parser.add_argument("--model", "-m", default="claude-sonnet-4-6", help="Default model (default: claude-sonnet-4-6)")
    init_parser.add_argument("--description", default="", help="One-line workflow description")
    init_parser.set_defaults(func=_cmd_init)

    # --- customize ---
    customize_parser = subparsers.add_parser("customize", help="Interactively customize a workflow via LLM interview")
    customize_parser.add_argument("--dir", "-d", default=".", help="Output directory for generated workflow")
    customize_parser.add_argument("--workflow", "-w", default=None, help="Existing workflow directory to use as starting point")
    customize_parser.add_argument("--model", "-m", default="claude-sonnet-4-6", help="Model for interview (default: claude-sonnet-4-6)")
    customize_parser.set_defaults(func=_cmd_customize)

    # --- mc ---
    mc_parser = subparsers.add_parser("mc", help="Run the minimal Claude agent")
    mc_parser.add_argument("prompt", nargs="?", help="Task description")
    mc_parser.add_argument("--model", "-m", default=None, help="Model ID (e.g. claude-sonnet-4-6)")
    mc_parser.add_argument("--cwd", default=None, help="Working directory")
    mc_parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds (default: 600)")
    mc_parser.add_argument("--output", "-o", metavar="FILE", help="Write agent result to FILE")
    mc_parser.set_defaults(func=_cmd_mc)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        rc = args.func(args)
        sys.exit(rc)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
