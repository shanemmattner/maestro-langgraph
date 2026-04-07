#!/usr/bin/env python3
"""Minimal Claude Code Agent — 84% fewer tool-schema tokens.

Single file: runs as agent wrapper OR as MCP tool server.
Uses lightweight MCP tool schemas (~900 tokens) instead of
CC's built-in tools (~5,800 tokens) for 5 tools (bash, read, grep, edit, write).

    python -m core.mc "Fix the bug in auth.py" --model claude-sonnet-4-6
    python -m core.mc --mcp-server   # (CC spawns this automatically)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Local MLX model prefixes
_LOCAL_MODEL_PREFIXES = ("mlx-community/", "RepublicOfKorokke/", "arthurcollet/", "inferencerlabs/")


def _is_local_model(model: str) -> bool:
    """Return True if model should route to local MLX/RAC."""
    return model == "local" or any(model.startswith(p) for p in _LOCAL_MODEL_PREFIXES)


def _run_local_rac(prompt: str, agent_prompt: str, cwd: str, model: str,
                   timeout: int, output_path: str | None) -> int:
    """Run agent via RAC when a local MLX model is requested.

    RAC handles tool use (bash, read, grep, edit, write) natively.
    Returns the process exit code.
    """
    import urllib.request as _urllib

    # Find MLX server port (8800-8810) — verify via /v1/models, not just TCP
    mlx_url = None
    for port in range(8800, 8811):
        try:
            with _urllib.urlopen(f"http://localhost:{port}/v1/models", timeout=1) as resp:
                if resp.status == 200:
                    mlx_url = f"http://localhost:{port}"
                    break
        except Exception:
            pass

    if not mlx_url:
        print(f"ERROR: local MLX server not found on ports 8800-8810 — cannot route model={model}",
              file=sys.stderr)
        if output_path:
            Path(output_path).write_text(f"ERROR: local MLX server unavailable for model={model}")
        return 1

    # Resolve "local" to the actual model name from the server
    if model == "local":
        try:
            with _urllib.urlopen(f"{mlx_url}/v1/models", timeout=3) as resp:
                data = json.loads(resp.read())
                models = data.get("data", [])
                if models:
                    model = models[0]["id"]
        except Exception:
            pass  # keep "local" — RAC will handle it

    full_prompt = (agent_prompt + "\n\n" + prompt) if agent_prompt else prompt
    cmd = [
        "rac", "run",
        "-v",
        "-p", full_prompt,
        "-m", model,
        "--max-turns", "10",
        "--turn-timeout", "600",
        "--timeout", str(timeout),
        "--cwd", str(cwd),
    ]
    env = {**os.environ, "OPENROUTER_BASE_URL": mlx_url, "OPENROUTER_API_KEY": "local"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout + 30)
    result_text = proc.stdout.strip()

    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result_text)
        print(str(out_path))

    if proc.returncode != 0:
        print(f"ERROR: RAC failed (exit={proc.returncode}): {proc.stderr[-200:]}", file=sys.stderr)
    return proc.returncode


# ==========================================================================
# MCP Tool Server (newline-delimited JSON-RPC over stdio, zero deps)
# ==========================================================================

MCP_TOOLS = [
    {"name": "bash", "description": "Run a shell command",
     "inputSchema": {"type": "object",
         "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "default": 120}},
         "required": ["command"]}},
    {"name": "read", "description": "Read a file",
     "inputSchema": {"type": "object",
         "properties": {"path": {"type": "string"}, "offset": {"type": "integer", "default": 0}, "limit": {"type": "integer", "default": 2000}},
         "required": ["path"]}},
    {"name": "grep", "description": "Search files for a regex pattern",
     "inputSchema": {"type": "object",
         "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}, "glob": {"type": "string"}},
         "required": ["pattern"]}},
    {"name": "edit", "description": "Replace exact text in a file",
     "inputSchema": {"type": "object",
         "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
         "required": ["path", "old_string", "new_string"]}},
    {"name": "write", "description": "Write content to a file (creates or overwrites)",
     "inputSchema": {"type": "object",
         "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}},
    {"name": "web_search", "description": "Search the web for documentation, examples, and API references. Use this to research unfamiliar APIs or find code examples before implementing.",
     "inputSchema": {"type": "object",
         "properties": {"query": {"type": "string", "description": "Search query"}},
         "required": ["query"]}},
    {"name": "web_fetch", "description": "Fetch and extract content from a specific URL as markdown. Use for reading documentation pages, blog posts, or code examples.",
     "inputSchema": {"type": "object",
         "properties": {"url": {"type": "string", "description": "URL to fetch"}},
         "required": ["url"]}},
]


def _mcp_bash(a):
    t = a.get("timeout", 120)
    try:
        r = subprocess.run(a["command"], shell=True, capture_output=True, text=True, timeout=t)
        o = r.stdout + (f"\nSTDERR:\n{r.stderr}" if r.stderr else "")
        if r.returncode != 0:
            o += f"\nExit code: {r.returncode}"
        return o[:50000] or "(empty)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {t}s"


def _mcp_read(a):
    try:
        with open(a["path"]) as f:
            lines = f.readlines()
        s, n = a.get("offset", 0), a.get("limit", 2000)
        r = "".join(f"{i+s+1:6d}\t{l}" for i, l in enumerate(lines[s:s+n]))
        if s + n < len(lines):
            r += f"\n... ({len(lines)-s-n} more lines)"
        return r or "(empty)"
    except FileNotFoundError:
        return f"Not found: {a['path']}"


def _mcp_grep(a):
    cmd = ["grep", "-rn"] + ([f"--include={a['glob']}"] if a.get("glob") else [])
    cmd += [a["pattern"], a.get("path", ".")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout[:50000] or "(no matches)"
    except subprocess.TimeoutExpired:
        return "Timed out"


def _mcp_edit(a):
    try:
        with open(a["path"]) as f:
            c = f.read()
        n = c.count(a["old_string"])
        if n == 0:
            return f"Not found in {a['path']}"
        if n > 1:
            return f"Found {n} times (must be unique)"
        with open(a["path"], "w") as f:
            f.write(c.replace(a["old_string"], a["new_string"], 1))
        return f"Edited {a['path']}"
    except FileNotFoundError:
        return f"Not found: {a['path']}"


def _mcp_write(a):
    try:
        p = Path(a["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"])
        return f"Wrote {len(a['content'])} chars to {a['path']}"
    except OSError as e:
        return f"Error writing {a['path']}: {e}"


def _mcp_web_search(a):
    """Search the web via Firecrawl v1 search API."""
    import urllib.request
    import urllib.error
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        return "FIRECRAWL_API_KEY not set — web search unavailable"
    query = a.get("query", "")
    if not query:
        return "No query provided"
    payload = json.dumps({"query": query, "limit": 5})
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/search",
        data=payload.encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("data", [])
        if not results:
            return "No results found"
        parts = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            snippet = r.get("description", r.get("markdown", ""))[:300]
            parts.append(f"{i}. **{title}**\n   {url}\n   {snippet}")
        return "\n\n".join(parts)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return f"Web search failed: {e}"


def _mcp_web_fetch(a):
    """Fetch and extract content from a URL via Firecrawl scrape API."""
    import urllib.request
    import urllib.error
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        return "FIRECRAWL_API_KEY not set — web fetch unavailable"
    url = a.get("url", "")
    if not url:
        return "No URL provided"
    payload = json.dumps({"url": url, "formats": ["markdown"]})
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape",
        data=payload.encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        content = data.get("data", {}).get("markdown", "")
        if not content:
            return "No content extracted from URL"
        return content[:30000]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return f"Web fetch failed: {e}"


_MCP_HANDLERS = {"bash": _mcp_bash, "read": _mcp_read, "grep": _mcp_grep,
                 "edit": _mcp_edit, "write": _mcp_write,
                 "web_search": _mcp_web_search, "web_fetch": _mcp_web_fetch}


def run_mcp_server(only_tools: list[str] | None = None):
    """Stdio MCP server. CC spawns this process via --mcp-config.

    Args:
        only_tools: If set, only expose these tool names. None means all.
    """
    allowed = set(only_tools) if only_tools else None
    exposed_tools = [t for t in MCP_TOOLS if allowed is None or t["name"] in allowed]

    def respond(id, result):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": id, "result": result}) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        m, id, p = msg.get("method", ""), msg.get("id"), msg.get("params", {})
        if m == "initialize":
            respond(id, {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                         "serverInfo": {"name": "minimal-tools", "version": "1.0"}})
        elif m == "tools/list":
            respond(id, {"tools": exposed_tools})
        elif m == "tools/call":
            name = p.get("name", "")
            if allowed is not None and name not in allowed:
                respond(id, {"content": [{"type": "text", "text": f"Tool not available: {name}"}],
                             "isError": True})
                continue
            h = _MCP_HANDLERS.get(name)
            text = h(p.get("arguments", {})) if h else f"Unknown tool: {name}"
            respond(id, {"content": [{"type": "text", "text": text}],
                         **({"isError": True} if not h else {})})
        elif m == "ping":
            respond(id, {})


# ==========================================================================
# Agent Wrapper
# ==========================================================================

SYSTEM_PROMPT = """You are an engineering agent. Complete the task using the provided tools.

Workflow:
1. Read the task and break it into a checklist of concrete steps
2. For each step: define what success looks like before implementing
3. Work through each step — read relevant files before making changes
4. Verify each step against its success criteria before moving on

Rules:
- Never guess — use tools to read files and gather context first
- Plan before each action, reflect on the outcome after
- Keep going until the task is fully resolved
- Do not create summary, log, or report files — only source code and tests"""


def _get_env() -> dict[str, str]:
    """Return env dict for child claude processes.

    Strips CLAUDECODE to allow nested claude invocations from within
    a Claude Code session (otherwise claude CLI refuses to start).
    """
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"} | {"CLAUDE_CODE_SIMPLE": "true"}


def git_branch_context(cwd: str | Path) -> str:
    """Return git branch context string for safety guard — prevents branch switching."""
    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(cwd), timeout=5,
        )
    except Exception:
        return ""
    if branch_result.returncode != 0:
        return ""
    branch = branch_result.stdout.strip()
    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
        capture_output=True, text=True, cwd=str(cwd), timeout=5,
    )
    if upstream_result.returncode == 0:
        upstream = upstream_result.stdout.strip()
        return (
            f"\n\nGit context: you are on branch '{branch}' tracking '{upstream}'."
            " Do NOT switch branches or push to any other branch."
        )
    return (
        f"\n\nGit context: you are on branch '{branch}'."
        " Do NOT switch branches or push to any other branch."
    )


def build_cmd(prompt: str, *, model: str,
              system_prompt: str = SYSTEM_PROMPT,
              agent_prompt: str = "",
              max_budget_usd: float | None = None,
              tools: bool = True,
              only_tools: list[str] | None = None) -> tuple[list[str], str]:
    """Build claude CLI command.

    Args:
        tools: If True (default), attach MCP tool server (~900 tokens).
               If False, text-only LLM call (no tools).
        only_tools: If set, restrict the MCP tool server to these tools only
                    (e.g. ["bash", "read", "grep"] for read-only access).

    Returns (cmd, prompt) — prompt is passed via stdin to avoid ARG_MAX limits.
    """
    effective_prompt = (agent_prompt + "\n\n" + system_prompt if agent_prompt else system_prompt)
    # Strip provider prefix (e.g. "claude_code:opus" -> "opus")
    cli_model = model.split(":", 1)[1] if ":" in model else model
    cmd = ["claude", "-p",
           "--system-prompt", effective_prompt,
           "--model", cli_model,
           "--output-format", "stream-json",
           "--verbose",
           "--dangerously-skip-permissions",
           "--tools", "",
           "--setting-sources", "user"]
    if tools:
        me = str(Path(__file__).resolve())
        server_args = [me, "--mcp-server"]
        if only_tools:
            server_args += ["--only-tools", ",".join(only_tools)]
        mcp_cfg = json.dumps({"mcpServers": {"m": {
            "command": sys.executable,
            "args": server_args,
        }}})
        cmd += ["--mcp-config", mcp_cfg]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    return cmd, prompt


STREAM_LOG_DIR = Path(tempfile.gettempdir()) / 'mc-logs'


def run_claude(cmd: list[str], cwd: Path, timeout: int = 600,
               prompt_stdin: str | None = None) -> tuple[dict, float, int]:
    """Run claude CLI, returning parsed output and timing.

    Reads stdout line-by-line (stream-json NDJSON) and tees every event to a
    .jsonl log file in /tmp/mc-logs/ for debugging.

    Returns:
        Tuple of (final_message, elapsed, returncode).
    """
    import threading

    start = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE if prompt_stdin else None,
                                text=True, cwd=cwd, env=_get_env())
        if prompt_stdin:
            proc.stdin.write(prompt_stdin)
            proc.stdin.close()
    except FileNotFoundError:
        sys.exit("Error: claude CLI not found. Install: npm install -g @anthropic-ai/claude-code")

    # Set up JSONL log file for stream-json tee
    STREAM_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STREAM_LOG_DIR / f'mc-{proc.pid}-{int(start)}.jsonl'
    lines: list[str] = []
    final: dict = {}

    # Drain stderr in background thread to prevent deadlock
    stderr_lines: list[str] = []
    def _drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)
    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    deadline = start + timeout
    timed_out = False

    # Accumulate usage from every assistant turn (ccusage approach)
    accumulated_usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    }

    try:
        with open(log_path, 'w') as logf:
            for line in proc.stdout:
                lines.append(line)
                logf.write(line)
                logf.flush()
                stripped = line.strip()
                if stripped:
                    try:
                        obj = json.loads(stripped)
                        # Accumulate usage from every assistant turn (ccusage approach)
                        if obj.get("type") == "assistant":
                            u = obj.get("message", {}).get("usage", {})
                            accumulated_usage["input_tokens"] += u.get("input_tokens", 0)
                            accumulated_usage["cache_creation_input_tokens"] += u.get("cache_creation_input_tokens", 0)
                            accumulated_usage["cache_read_input_tokens"] += u.get("cache_read_input_tokens", 0)
                            accumulated_usage["output_tokens"] += u.get("output_tokens", 0)
                            cost = obj.get("costUSD") or 0.0
                            accumulated_usage["cost_usd"] += cost
                        if isinstance(obj, dict) and obj.get('role') == 'system' and 'cost_usd' in obj:
                            final = obj
                        elif isinstance(obj, dict) and obj.get('type') == 'result':
                            final = obj
                    except json.JSONDecodeError:
                        pass
                if time.time() > deadline:
                    timed_out = True
                    break
    except Exception as exc:
        print(f"Warning: stream read error: {exc}", file=sys.stderr)

    if timed_out:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        sys.exit(f"Error: timed out after {timeout}s")

    proc.wait()
    stderr_thread.join(timeout=2)
    returncode = proc.returncode
    elapsed = time.time() - start

    # Attach accumulated usage (sum across all turns) to final result
    final["_accumulated_usage"] = accumulated_usage

    # If we didn't find a system summary in the stream, try parsing all lines
    if not final:
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    final = obj
                    break
            except json.JSONDecodeError:
                continue

    print(f"Session log: {log_path} ({len(lines)} events, {elapsed:.1f}s)", file=sys.stderr)
    return final, elapsed, returncode


def parse_usage(final: dict) -> dict:
    """Extract token and cost metrics from a claude CLI session.

    Prefers _accumulated_usage (sum across all turns) over the final message's
    usage field (which is only the last turn). Approach adapted from ccusage
    (github.com/ryoppippi/ccusage) which uses the same per-turn accumulation.
    """
    acc = final.get("_accumulated_usage", {})
    u = acc if acc.get("input_tokens") or acc.get("output_tokens") else final.get("usage", {})
    return {
        "input": u.get("input_tokens", 0),
        "cache_new": u.get("cache_creation_input_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cost": acc.get("cost_usd", 0) or final.get("total_cost_usd", 0) or 0.0,
    }


# ==========================================================================
# CLI
# ==========================================================================

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Minimal Claude Code Agent — lean extraction for langgraph-maestro")
    p.add_argument("prompt", nargs="?", help="Task description")
    p.add_argument("--prompt-file", "-f", metavar="FILE", help="Read prompt from file")
    p.add_argument("--cwd", type=Path, default=Path.cwd())
    p.add_argument("--model", default=None, help="Full model ID (e.g. claude-sonnet-4-6)")
    p.add_argument("--max-budget-usd", type=float, default=None, help="Dollar cap per agent")
    p.add_argument("--output", "-o", metavar="FILE", help="Write agent result to FILE")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    p.add_argument("--mcp-server", action="store_true", help="Run as MCP server (used internally)")
    p.add_argument("--only-tools", help="Comma-separated tool names to expose (with --mcp-server)")

    a = p.parse_args()

    if a.mcp_server:
        only = a.only_tools.split(",") if a.only_tools else None
        run_mcp_server(only_tools=only)
        return

    # Resolve prompt: --prompt-file > positional arg > stdin
    if a.prompt_file:
        pf = Path(a.prompt_file)
        if not pf.exists():
            p.error(f"Prompt file not found: {a.prompt_file}")
        a.prompt = pf.read_text()
    elif not a.prompt:
        if not sys.stdin.isatty():
            a.prompt = sys.stdin.read()
        else:
            p.error("prompt required. Provide as argument, --prompt-file, or pipe via stdin.")

    if not a.model:
        print("ERROR: no model specified — pass --model", file=sys.stderr)
        sys.exit(1)

    cwd = a.cwd.resolve()

    # Local MLX routing — use RAC instead of claude -p
    if _is_local_model(a.model):
        print(f"model={a.model} tools=rac cwd={cwd}")
        rc = _run_local_rac(a.prompt, "", cwd, a.model, a.timeout, a.output)
        sys.exit(rc)

    cmd, prompt_text = build_cmd(a.prompt, model=a.model, max_budget_usd=a.max_budget_usd)
    print(f"model={a.model} tools=mcp cwd={cwd}")

    final, elapsed, rc = run_claude(cmd, cwd, timeout=a.timeout, prompt_stdin=prompt_text)
    u = parse_usage(final)
    total = u["input"] + u["cache_new"] + u["cache_read"]

    if a.output:
        out_path = Path(a.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final.get("result", ""))
        print(str(out_path))
        sys.exit(rc)

    print(f"tokens: {total:,} in / {u['output']:,} out | {elapsed:.1f}s | ${u['cost']:.4f}")
    print()
    print(final.get("result", ""))
    sys.exit(rc)


if __name__ == "__main__":
    main()
