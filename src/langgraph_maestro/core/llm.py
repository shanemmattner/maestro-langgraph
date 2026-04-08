"""LLM call module with provider registry and built-in providers.

GenAI Observability
-------------------
call_llm() emits OTel spans using GenAI semantic conventions (gen_ai.* attributes)
so Langfuse can capture full prompt/response content for pipeline replay and debugging.

Attributes follow the OTel GenAI semantic conventions specification:
- gen_ai.system: provider name (claude_code, minimax, local)
- gen_ai.operation.name: phase name if provided (decompose, execute, review, pe)
- gen_ai.request.model: model identifier
- gen_ai.input.messages / gen_ai.output.messages: JSON-encoded prompt/response (opt-in via MAESTRO_TRACE_CONTENT)
- gen_ai.usage.input_tokens / gen_ai.usage.output_tokens: token counts from provider
- gen_ai.latency: total call latency in seconds
- gen_ai.ttft: time to first token (streaming providers only)

Content tracing controlled by MAESTRO_TRACE_CONTENT env var (default: true).
Set to 'false' in production to reduce span size while keeping token usage metrics.

Dual-write strategy:
- OTel spans → Langfuse: full GenAI data for remote replay (this module)
- Python JSONL logger: metadata-only for local operational debugging (unchanged)
"""

import json
import logging
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from langgraph_maestro.core.tracing import get_tracer

logger = logging.getLogger(__name__)

# Content tracing: when True, full prompt/response text is included in OTel spans.
# Default ON for development; set MAESTRO_TRACE_CONTENT=false in prod to reduce span size.
_TRACE_CONTENT = os.environ.get("MAESTRO_TRACE_CONTENT", "true").lower() != "false"

# Per-model cost table (USD per 1M tokens). Used to compute gen_ai.usage.cost on spans.
# MiniMax M2.5 is currently $0 under subscription — set to 0 but track for when pricing changes.
_MODEL_COSTS: Dict[str, Dict[str, float]] = {
    # With date suffix (legacy)
    "claude-sonnet-4-6-20250501": {"input": 3.0, "output": 15.0},
    "claude-opus-4-6-20250501": {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Without date suffix (current usage)
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
    # MiniMax (free tier)
    "MiniMax-M2.5-highspeed": {"input": 0.0, "output": 0.0},
    "MiniMax-M2.5": {"input": 0.0, "output": 0.0},
}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Compute USD cost for a call. Returns None if model not in cost table."""
    # Strip provider prefix
    bare = model.split(":", 1)[1] if ":" in model else model
    # Strip date suffix (e.g. claude-sonnet-4-6-20250501 -> claude-sonnet-4-6)
    bare = re.sub(r'-\d{8}$', '', bare)
    costs = _MODEL_COSTS.get(bare)
    if costs is None:
        return None
    return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

# Provider registry
_providers: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register_provider(name: str, fn: Callable[..., Dict[str, Any]]) -> None:
    """Register a provider function."""
    _providers[name] = fn


def get_provider(model: str) -> Tuple[str, Callable[..., Dict[str, Any]]]:
    """Get provider name and function based on model string.

    Routing rules:
    - 'minimax' in model.lower() -> minimax
    - model starts with 'mlx-community/', 'arthurcollet/', 'RepublicOfKorokke/', 'inferencerlabs/' or 'local' -> local
    - 'codex' in model or starts with 'gpt-' or 'openai/' -> codex (Codex CLI)
    - Support explicit prefix: 'claude_code:sonnet' -> claude_code provider
    - else -> claude_code
    """
    # Check for explicit prefix
    if ':' in model:
        prefix, rest = model.split(':', 1)
        if prefix in _providers:
            return prefix, _providers[prefix]
    
    # Prefix mapping for local models
    _local_prefixes = ('mlx-community/', 'arthurcollet/', 'RepublicOfKorokke/', 'inferencerlabs/', 'local')
    if model.startswith(_local_prefixes):
        return 'local', _providers['local']
    
    # Check for minimax
    if 'minimax' in model.lower():
        return 'minimax', _providers['minimax']

    # Check for codex / gpt models
    if 'codex' in model.lower() or model.startswith('gpt-') or model.startswith('openai/'):
        return 'codex', _providers['codex']

    # Default to claude_code
    return 'claude_code', _providers['claude_code']


def _call_default_claude_code(
    prompt: str,
    model: str,
    system_prompt: str,
    cwd: Optional[str],
    timeout: int
) -> Dict[str, Any]:
    """Call Claude Code CLI for text-only LLM calls (no tools).

    Uses core.mc.build_cmd(tools=False) + run_claude() — single code path
    for all claude -p command construction.
    """
    from langgraph_maestro.core.mc import build_cmd, run_claude, parse_usage

    cmd, prompt_text = build_cmd(prompt, model=model, system_prompt=system_prompt, tools=False)
    work_cwd = Path(cwd) if cwd else Path.cwd()
    final, elapsed, rc = run_claude(cmd, work_cwd, timeout=timeout, prompt_stdin=prompt_text)
    usage = parse_usage(final)
    content = final.get('result', '')

    result: Dict[str, Any] = {
        'content': content,
        'model': model,
        'latency': elapsed,
    }
    if usage.get('input'):
        result['input_tokens'] = usage['input']
    if usage.get('output'):
        result['output_tokens'] = usage['output']
    if usage.get('cache_new'):
        result['cache_creation_tokens'] = usage['cache_new']
    if usage.get('cache_read'):
        result['cache_read_tokens'] = usage['cache_read']
    if usage.get('cost'):
        result['cost_usd'] = usage['cost']
    return result


def _call_default_local(
    prompt: str,
    model: str,
    system_prompt: str,
    cwd: Optional[str],
    timeout: int
) -> Dict[str, Any]:
    """Call local MLX server.
    
    Finds MLX server on ports 8800-8810 via /v1/models
    Calls /v1/chat/completions with streaming SSE
    Returns {content, model, latency, ttft}
    """
    # Find MLX server
    mlx_host = os.environ.get("MLX_HOST", "localhost")
    base_url = None
    for port in range(8800, 8811):
        try:
            url = f"http://{mlx_host}:{port}/v1/models"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    base_url = f"http://{mlx_host}:{port}"
                    break
        except Exception:
            continue

    if base_url is None:
        raise RuntimeError(f"MLX server not found on {mlx_host}:8800-8810")
    
    # Call chat completions
    url = f"{base_url}/v1/chat/completions"
    
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt}
        ],
        'stream': True,
        'stream_options': {'include_usage': True}
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    
    start_time = time.time()
    ttft = None
    content_parts = []
    usage = {}

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for line in response:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        if 'usage' in data:
                            usage = data['usage']
                        if 'choices' in data and len(data['choices']) > 0:
                            delta = data['choices'][0].get('delta', {})
                            if 'content' in delta:
                                if ttft is None:
                                    ttft = time.time() - start_time
                                content_parts.append(delta['content'])
                    except json.JSONDecodeError:
                        continue

        latency = time.time() - start_time
        content = ''.join(content_parts)

        result = {
            'content': content,
            'model': model,
            'latency': latency,
            'ttft': ttft
        }
        if usage.get('prompt_tokens'):
            result['input_tokens'] = usage['prompt_tokens']
        if usage.get('completion_tokens'):
            result['output_tokens'] = usage['completion_tokens']
        return result
        
    except Exception as e:
        raise RuntimeError(f"Local LLM call failed: {str(e)}")


def _strip_reasoning_tags(text: str) -> str:
    """Strip <think>...</think> reasoning tags from model output.

    Applies to MiniMax M2.5, DeepSeek R1, and any reasoning model that
    wraps chain-of-thought in <think> tags.
    """
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _load_minimax_api_key() -> str:
    """Load MINIMAX_API_KEY from environment."""
    key = os.environ.get("MINIMAX_API_KEY")
    if key:
        return key
    raise RuntimeError("MINIMAX_API_KEY not set in environment")


def _call_default_minimax(
    prompt: str,
    model: str,
    system_prompt: str,
    cwd: Optional[str],
    timeout: int
) -> Dict[str, Any]:
    """Call MiniMax API directly for text-only completions (no tools).

    Uses the OpenAI-compatible /v1/chat/completions endpoint.
    Returns {content, model, latency, input_tokens, output_tokens}.
    """
    api_key = _load_minimax_api_key()
    url = "https://api.minimax.io/v1/chat/completions"

    # Strip provider prefix (e.g. "minimax:MiniMax-M2.5-highspeed" -> "MiniMax-M2.5-highspeed")
    bare_model = model.split(":", 1)[1] if ":" in model else model

    payload = {
        "model": bare_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))

        latency = time.time() - start_time

        raw_content = body["choices"][0]["message"]["content"]
        content = _strip_reasoning_tags(raw_content)

        result: Dict[str, Any] = {
            "content": content,
            "model": model,
            "latency": latency,
        }
        usage = body.get("usage", {})
        if usage.get("prompt_tokens"):
            result["input_tokens"] = usage["prompt_tokens"]
        if usage.get("completion_tokens"):
            result["output_tokens"] = usage["completion_tokens"]
        return result

    except urllib.error.URLError as e:
        raise RuntimeError(f"MiniMax API call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"MiniMax API unexpected response: {e}")


def _call_minimax_agent(
    prompt: str,
    model: str,
    system_prompt: str,
    cwd: Optional[str],
    timeout: int
) -> Dict[str, Any]:
    """Call minimax-agent.py subprocess (tool-enabled agent).

    Used by call_agent() for tasks requiring file access and tools.
    """
    # Find minimax-agent.py
    current_dir = os.path.dirname(os.path.abspath(__file__))
    agent_path = None

    while True:
        candidate = os.path.join(current_dir, '.claude', 'skills', 'minimax-agent', 'minimax-agent.py')
        if os.path.exists(candidate):
            agent_path = candidate
            break
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent

    if agent_path is None:
        # Fall back to direct API when agent script is not found (e.g., in Docker)
        enhanced_system_prompt = system_prompt + "\n\nYou are a code implementation agent. Write complete, working code."
        logger.warning("minimax_agent_fallback", extra={"reason": "agent script not found, using direct API"})
        return _call_default_minimax(
            prompt=prompt,
            model=model,
            system_prompt=enhanced_system_prompt,
            cwd=cwd,
            timeout=timeout,
        )

    cmd = [
        'python3', agent_path,
        '--model', model,
        '--system', system_prompt,
        '--json',
    ]

    start_time = time.time()

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True
        )

        stdout, stderr = process.communicate(input=prompt, timeout=timeout)

        latency = time.time() - start_time

        result: Dict[str, Any] = {'model': model, 'latency': latency}
        try:
            data = json.loads(stdout)
            result['content'] = data.get('text', '')
            if data.get('input_tokens'):
                result['input_tokens'] = data['input_tokens']
            if data.get('output_tokens'):
                result['output_tokens'] = data['output_tokens']
            if data.get('ttft') is not None:
                result['ttft'] = data['ttft']
        except (json.JSONDecodeError, TypeError):
            result['content'] = stdout

        return result

    except subprocess.TimeoutExpired:
        process.kill()
        raise TimeoutError(f"Minimax agent timed out after {timeout} seconds")
    except Exception as e:
        raise RuntimeError(f"Minimax agent call failed: {str(e)}")


def call_llm(
    prompt: str,
    model: str,
    system_prompt: str = 'You are a coding assistant.',
    cwd: Optional[str] = None,
    timeout: int = 300,
    phase: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Call LLM with the specified model.

    Routes to provider based on model string.
    Applies skill injection if config is provided.
    Uses per-model timeout from config if available.
    Traces to Langfuse via OTel if configured.
    """
    # Skill injection + per-model timeout from config
    if config is not None:
        from langgraph_maestro.core.skills import inject_skills
        from langgraph_maestro.core.config import get_timeout_for_model
        prompt, system_prompt = inject_skills(prompt, system_prompt, model, phase, config)
        timeout = get_timeout_for_model(model, config)

    provider_name, provider_fn = get_provider(model)
    start = time.time()

    logger.info(
        "llm_call_start",
        extra={"provider": provider_name, "model": model,
               "prompt_len": len(prompt), "system_prompt_len": len(system_prompt)},
    )

    tracer = get_tracer()
    span_name = f"gen_ai.{phase}" if phase else "gen_ai.chat"

    with tracer.start_as_current_span(span_name) as span:
        # Static GenAI attributes
        span.set_attribute("gen_ai.system", provider_name)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.provider.name", provider_name)
        if phase:
            span.set_attribute("gen_ai.operation.name", phase)

        # Content attributes (opt-in)
        if _TRACE_CONTENT:
            messages = json.dumps([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ])
            span.set_attribute("gen_ai.input.messages", messages)

        try:
            result = provider_fn(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                cwd=cwd,
                timeout=timeout,
                **kwargs
            )

            # Post-call span attributes
            latency = round(time.time() - start, 3)
            span.set_attribute("gen_ai.latency", latency)
            if result.get("input_tokens"):
                span.set_attribute("gen_ai.usage.input_tokens", result["input_tokens"])
            if result.get("output_tokens"):
                span.set_attribute("gen_ai.usage.output_tokens", result["output_tokens"])
            if result.get("cache_creation_tokens"):
                span.set_attribute("gen_ai.usage.cache_creation_tokens", result["cache_creation_tokens"])
            if result.get("cache_read_tokens"):
                span.set_attribute("gen_ai.usage.cache_read_tokens", result["cache_read_tokens"])
            if result.get("ttft") is not None:
                span.set_attribute("gen_ai.ttft", result["ttft"])
            if _TRACE_CONTENT and result.get("content"):
                span.set_attribute("gen_ai.output.messages", json.dumps([
                    {"role": "assistant", "content": result["content"]},
                ]))

            # Cost tracking
            in_tok = result.get("input_tokens", 0)
            out_tok = result.get("output_tokens", 0)
            cost = _compute_cost(model, in_tok, out_tok)
            if cost is not None:
                span.set_attribute("gen_ai.usage.cost", cost)

            logger.info(
                "llm_call_ok",
                extra={
                    "provider": provider_name,
                    "model": model,
                    "content_len": len(result.get("content", "")),
                    "latency": latency,
                    "ttft": result.get("ttft"),
                    "input_tokens": result.get("input_tokens"),
                    "output_tokens": result.get("output_tokens"),
                    "cache_new": result.get("cache_creation_tokens"),
                    "cache_read": result.get("cache_read_tokens"),
                    "cost_usd": cost,
                },
            )

            return result
        except Exception as e:
            span.set_attribute("gen_ai.latency", round(time.time() - start, 3))
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(e))
            logger.error(
                "llm_call_error",
                extra={"provider": provider_name, "model": model,
                       "error": str(e), "latency": round(time.time() - start, 3)},
            )
            raise


def call_llm_with_fallback(
    prompt: str,
    models: List[str],
    phase: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Call LLM with fallback models.

    Tries each model in order, returns first success (non-empty content, no error).
    Adds 'fallback_attempts' key listing all attempts with model/success/error.
    Passes phase and config through to call_llm for skill injection and timeouts.
    """
    attempts = []
    logger.info("fallback_chain_start", extra={"models": models})

    tracer = get_tracer()
    span_name = f"gen_ai.fallback:{phase}" if phase else "gen_ai.fallback"

    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("gen_ai.fallback.models", json.dumps(models))
        if phase:
            span.set_attribute("gen_ai.operation.name", phase)

        for i, model in enumerate(models):
            try:
                result = call_llm(prompt, model, phase=phase, config=config, **kwargs)
                if result.get('content'):
                    result['fallback_attempts'] = attempts
                    span.set_attribute("gen_ai.fallback.selected_model", model)
                    span.set_attribute("gen_ai.fallback.attempt", i + 1)
                    logger.info(
                        "fallback_chain_ok",
                        extra={"model": model, "attempt": i + 1, "total_models": len(models)},
                    )
                    return result
                else:
                    attempts.append({
                        'model': model,
                        'success': False,
                        'error': 'Empty content'
                    })
                    logger.warning(
                        "fallback_attempt_empty",
                        extra={"model": model, "attempt": i + 1},
                    )
            except Exception as e:
                attempts.append({
                    'model': model,
                    'success': False,
                    'error': str(e)
                })
                logger.warning(
                    "fallback_attempt_failed",
                    extra={"model": model, "attempt": i + 1, "error": str(e)},
                )

        # All attempts failed
        span.set_attribute("error", True)
        span.set_attribute("gen_ai.fallback.exhausted", True)
        logger.error("fallback_chain_exhausted", extra={"attempts": attempts})
        raise RuntimeError(f"All fallback models failed. Attempts: {attempts}")


def rescue_json(
    content: str,
    model: str = "minimax:MiniMax-M2.5-highspeed",
    cwd: Optional[str] = None,
    timeout: int = 15,
) -> Optional[Dict[str, Any]]:
    """Extract structured JSON from raw agent text output using an LLM.

    Makes a cheap LLM call to convert plain-text agent output into a structured
    summary. Returns parsed dict or None on failure.

    Args:
        content: Raw agent text output
        model: Model to use for rescue (default: MiniMax-M2.5-highspeed)
        cwd: Working directory for the task
        timeout: Timeout in seconds (default: 15)

    Returns:
        Dict with keys: status, files_modified, implementation_summary, or None
    """
    prompt = f"""Extract a JSON summary from this agent output.
Return only a valid JSON object with these fields:
{{"status": "COMPLETE" or "INCOMPLETE", "files_modified": ["file1.py", "file2.py"], "implementation_summary": "brief description"}}

Agent output:
{content[:3000]}"""

    try:
        result = call_llm(
            prompt=prompt,
            model=model,
            system_prompt="You extract structured data from agent output. Return ONLY valid JSON, no explanation.",
            timeout=timeout,
            cwd=cwd,
        )
        parsed = extract_json(result.get("content", ""))
        if parsed and isinstance(parsed, dict):
            return parsed
    except Exception as e:
        logger.warning("rescue_json_failed", extra={"error": str(e)})

    return None


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from text using 5 strategies in order.

    Strategies:
    1. Direct parse
    2. Strip markdown fences
    3. Regex {}
    4. Trailing comma removal
    5. Single->double quotes

    Returns None if all fail.
    """
    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Strip markdown fences
    cleaned = re.sub(r'^```json\s*', '', text)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Regex extract {}
    match = re.search(r'\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Strategy 4: Trailing comma removal
    cleaned = re.sub(r',(\s*[\]\}])', r'\1', text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 5: Single to double quotes
    cleaned = text.replace("'", '"')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    return None


def _call_default_codex(
    prompt: str,
    model: str,
    system_prompt: str,
    cwd: Optional[str],
    timeout: int
) -> Dict[str, Any]:
    """Call Codex CLI (GPT-5.3-codex) directly.

    Supports reasoning levels via model suffix: gpt-5.3-codex, gpt-5.3-codex-high, gpt-5.3-codex-xhigh.
    Uses `codex exec --full-auto` for both text-only and tool-enabled calls.
    """
    import hashlib

    # Strip explicit provider prefix if present
    if model.startswith('codex:'):
        model = model.split(':', 1)[1]
    if model.startswith('openai/'):
        model = model.split('/', 1)[1]

    # Parse reasoning level from model string (e.g., gpt-5.3-codex-high -> model=gpt-5.3-codex, reasoning=high)
    reasoning = "medium"
    base_model = model
    for level in ("xhigh", "high", "medium"):
        if model.endswith(f"-{level}"):
            reasoning = level
            base_model = model[:-(len(level) + 1)]
            break

    # Build codex command — use --json for structured JSONL output
    cmd = [
        "codex", "exec", "--json", "--full-auto",
        "-m", base_model,
        "-c", f'model_reasoning_effort="{reasoning}"',
    ]
    if cwd:
        cmd.extend(["-C", cwd])

    # Combine system prompt and user prompt
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\n{prompt}"
    cmd.append(full_prompt)

    prompt_hash = hashlib.sha256(full_prompt.encode()).hexdigest()[:12]
    logger.info("codex_call_start", extra={
        "model": base_model, "reasoning": reasoning, "cwd": cwd,
        "prompt_len": len(full_prompt), "prompt_hash": prompt_hash,
    })
    start_time = time.time()

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        latency = time.time() - start_time
        raw_output = r.stdout or ""

        # Always log exit code and stderr (even on exit 0 — warnings matter)
        logger.info("codex_call_complete", extra={
            "model": base_model, "exit_code": r.returncode,
            "latency_s": round(latency, 1),
            "stdout_len": len(raw_output),
            "stderr_len": len(r.stderr or ""),
            "stderr_preview": (r.stderr or "")[:500],
        })

        if r.returncode != 0 and r.stderr:
            raw_output += f"\n\nSTDERR:\n{r.stderr}"

        # Save raw JSONL to session log (mirrors Claude Code's /tmp/mc-logs/ behavior)
        try:
            log_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "codex-logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"codex-{os.getpid()}-{int(start_time)}.jsonl"
            log_path.write_text(raw_output)
            logger.info("codex_session_log", extra={"path": str(log_path)})
        except Exception:
            pass  # non-critical

        # Parse JSONL output for agent text, tool usage, and apply_patch events.
        content_parts = []
        used_web_research = False
        tool_events = []
        apply_patch_events = []
        file_change_events = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                # Non-JSON line (e.g. startup messages) — include as text
                content_parts.append(line)
                continue

            evt_type = evt.get("type", "")
            item = evt.get("item", {})
            item_type = item.get("type", "")

            # Track apply_patch tool calls — the critical signal for edit failures
            if item_type in ("tool_call", "function_call"):
                fn_name = item.get("name", "") or item.get("function", {}).get("name", "")
                if fn_name == "apply_patch":
                    patch_evt = {
                        "type": "apply_patch",
                        "status": item.get("status", "unknown"),
                        "output_preview": str(item.get("output", ""))[:300],
                    }
                    apply_patch_events.append(patch_evt)
                    tool_events.append(patch_evt)

            # Track file_change events (Codex structured output for file operations)
            if item_type == "file_change" or evt_type == "file_change":
                fc_evt = {
                    "type": "file_change",
                    "file": item.get("file", evt.get("file", "")),
                    "status": item.get("status", evt.get("status", "unknown")),
                }
                file_change_events.append(fc_evt)

            # Detect web research from structured events
            if item_type == "web_search":
                used_web_research = True
                tool_events.append({"type": "web_search"})
            elif item_type == "mcp_tool_call":
                server = item.get("server", "")
                tool_name = item.get("tool", "")
                tool_events.append({"type": "mcp_tool_call", "server": server, "tool": tool_name})
                if server == "firecrawl" and tool_name in ("web_search", "web_fetch"):
                    used_web_research = True

            # Collect agent message text for content
            if item_type == "agent_message" and "content" in item:
                msg_content = item["content"]
                if isinstance(msg_content, list):
                    for part in msg_content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            content_parts.append(part.get("text", ""))
                elif isinstance(msg_content, str):
                    content_parts.append(msg_content)

        content = "\n".join(content_parts) if content_parts else raw_output

        # Log apply_patch summary — this is how we diagnose silent failures
        if apply_patch_events:
            logger.info("codex_apply_patch_summary", extra={
                "count": len(apply_patch_events),
                "events": apply_patch_events[:5],
            })
        if file_change_events:
            logger.info("codex_file_changes", extra={
                "count": len(file_change_events),
                "events": file_change_events[:10],
            })

        return {
            'content': content,
            'model': base_model,
            'latency': latency,
            'reasoning': reasoning,
            'exit_code': r.returncode,
            'stderr_preview': (r.stderr or "")[:500],
            'used_web_research': used_web_research,
            'tool_events': tool_events,
            'apply_patch_events': apply_patch_events,
            'file_change_events': file_change_events,
            'session_log': str(log_path) if 'log_path' in dir() else None,
        }

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex CLI timed out after {timeout}s ({base_model})")
    except FileNotFoundError:
        raise RuntimeError("Codex CLI not found — install with: npm install -g @openai/codex")


# Register built-in providers at module level
register_provider('claude_code', _call_default_claude_code)
register_provider('local', _call_default_local)
register_provider('minimax', _call_default_minimax)
register_provider('codex', _call_default_codex)


def _get_changed_files(cwd: str) -> List[str]:
    """Return list of files added/modified vs HEAD, relative to *cwd*.

    git status --porcelain always returns paths relative to the repo root.
    When cwd is a subdirectory (e.g. apps/ios inside a monorepo), we strip
    the prefix so callers get paths like ``Foo/Bar.swift`` instead of
    ``apps/ios/Foo/Bar.swift``.
    """
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return []
    if not r.stdout:
        return []

    # Detect the prefix between git root and cwd so we can strip it.
    prefix = ""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True,
        )
        if top.returncode == 0:
            import os
            git_root = os.path.realpath(top.stdout.strip())
            real_cwd = os.path.realpath(cwd)
            if real_cwd != git_root and real_cwd.startswith(git_root + "/"):
                prefix = real_cwd[len(git_root) + 1:] + "/"
    except Exception:
        pass  # fall back to no prefix stripping

    files = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        # Strip rename arrow (e.g. "old -> new")
        if " -> " in path:
            path = path.split(" -> ")[-1]
        # Strip prefix if present
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        files.append(path)
    return files


def _snapshot_file_hashes(cwd: str, files: List[str]) -> Dict[str, str]:
    """Return {relative_path: content_hash} for all dirty files.

    Uses content hashing to detect modifications to already-dirty files,
    which set-difference on git status cannot detect.
    """
    import hashlib
    hashes = {}
    for f in files:
        full = os.path.join(cwd, f)
        try:
            data = Path(full).read_bytes()
            hashes[f] = hashlib.sha256(data).hexdigest()[:16]
        except (OSError, FileNotFoundError):
            hashes[f] = "missing"
    return hashes


def detect_changed_files(cwd: str, before_files: List[str], before_hashes: Dict[str, str]) -> List[str]:
    """Detect files changed between before/after snapshots.

    Handles both new files (set difference) AND modifications to
    already-dirty files (content hash comparison). This fixes the race
    condition where subtask N modifies a file already dirtied by subtask N-1.
    """
    after_files = _get_changed_files(cwd)
    after_hashes = _snapshot_file_hashes(cwd, after_files)

    changed = []
    # New files (not in before set)
    before_set = set(before_files)
    for f in after_files:
        if f not in before_set:
            changed.append(f)
        elif after_hashes.get(f) != before_hashes.get(f):
            # File existed before but content changed — subtask modified it further
            changed.append(f)
    return changed


def call_agent(
    prompt: str,
    models: List[str],
    cwd: str,
    phase: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    timeout: int = 600,
    only_tools: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Call a tool-enabled agent that can read/write files. Falls back through model list.

    Args:
        only_tools: If set, restrict agent to these tools only (e.g. ["bash", "read", "grep"])
                    for read-only access). Only supported for claude_code provider.
    """
    config = config or {}
    last_error = None

    for model_str in models:
        provider_name, _ = get_provider(model_str)
        # Strip explicit prefix to get bare model name
        if ':' in model_str:
            _, model = model_str.split(':', 1)
        else:
            model = model_str

        try:
            if provider_name == "claude_code":
                from langgraph_maestro.core.mc import build_cmd, run_claude, parse_usage
                cmd, prompt_text = build_cmd(prompt, model=model, only_tools=only_tools)
                final, elapsed, rc = run_claude(cmd, Path(cwd), timeout=timeout,
                                                prompt_stdin=prompt_text)
                content = final.get("result", "")
                return {"content": content, "provider": provider_name, "model": model,
                        "usage": parse_usage(final), "elapsed": elapsed}

            elif provider_name == "minimax":
                # Use agent subprocess (tool-enabled) for call_agent
                result = _call_minimax_agent(
                    prompt=prompt,
                    model=model,
                    system_prompt="You are a code implementation agent.",
                    cwd=cwd,
                    timeout=timeout,
                )
                return {"content": result.get("content", ""), "provider": provider_name, "model": model}

            elif provider_name == "codex":
                # Use Codex CLI for GPT-5.3-codex tool-enabled implementation
                codex_system = (
                    "Default expectation: deliver working code, not analysis or plans.\n"
                    "Gather the minimum context needed, then implement in the same turn.\n"
                    "If the task is straightforward, write the code immediately.\n"
                    "Use web_search only when you need to verify an unfamiliar API or find a specific pattern.\n"
                    "Run relevant build/test commands to verify your changes.\n"
                    "Do not end with a plan unless explicitly asked for planning only.\n"
                    "If you find yourself rereading the same files without progress, stop and implement or report the blocker."
                )
                result = _call_default_codex(
                    prompt=prompt,
                    model=model,
                    system_prompt=codex_system,
                    cwd=cwd,
                    timeout=timeout,
                )
                return {
                    "content": result.get("content", ""),
                    "provider": "codex", "model": model,
                    "elapsed": result.get("latency", 0),
                    "used_web_research": result.get("used_web_research", False),
                    "tool_events": result.get("tool_events", []),
                }

            else:
                # local — text-only fallback
                result = call_llm(prompt=prompt, model=model_str, config=config)
                return {"content": result.get("content", ""), "provider": "local", "model": model, "text_only": True}

        except Exception as e:
            last_error = e
            logger.warning(f"call_agent failed for {model_str}: {e}")
            continue

    raise RuntimeError(f"All models failed in call_agent. Last error: {last_error}")
