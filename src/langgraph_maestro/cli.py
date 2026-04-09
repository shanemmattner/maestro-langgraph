"""CLI entry point for langgraph-maestro.

Usage:
    maestro verify
    maestro mc "prompt" [--model MODEL] [--cwd PATH] [--timeout N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


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
    check("import anthropic", lambda: __import__("anthropic") or True)

    # Check Langfuse keys (optional)
    import os
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if pk and sk:
        check("Langfuse keys", lambda: True)
    else:
        print("  SKIP  Langfuse keys (not set, optional)")

    # Check claude CLI
    def _check_claude_cli():
        import subprocess
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    check("claude CLI", _check_claude_cli)

    # Check web search stack (optional)
    def _check_search():
        from langgraph_maestro.core.web import is_search_available
        return is_search_available()
    def _check_scrape():
        from langgraph_maestro.core.web import is_scrape_available
        return is_scrape_available()
    if _check_search():
        check("SearXNG (web search)", _check_search)
        check("Crawl4AI (web scrape)", _check_scrape)
    else:
        print("  SKIP  Web search stack (not running, optional)")
        print("        Start with: cd infrastructure && docker compose --profile search up -d")

    print(f"\n{checks_passed} passed, {checks_failed} failed")
    return 0 if checks_failed == 0 else 1


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

    # --- verify ---
    verify_parser = subparsers.add_parser("verify", help="Verify setup (dependencies, tracing, etc.)")
    verify_parser.set_defaults(func=_cmd_verify)

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
