---
name: add-provider
description: Add a new LLM provider to the maestro call_llm() system. Use when integrating a new model API (e.g., Groq, Together, Fireworks).
---

# Add Provider

Use this skill when adding a new LLM provider so `call_llm()` can route to it.

## How Providers Work

The provider system lives in `src/langgraph_maestro/core/llm.py`:

- **`_providers`** -- a `Dict[str, Callable]` mapping provider names to call functions
- **`register_provider(name, fn)`** -- registers a provider function
- **`get_provider(model)`** -- routes a model string to the correct provider using pattern matching
- **`call_llm()`** -- the unified entry point; resolves provider, calls it, emits OTel spans

## Provider Function Signature

Every provider function must match this signature:

```python
def _call_my_provider(
    prompt: str,
    model: str,
    system_prompt: str = "You are a coding assistant.",
    cwd: str | None = None,
    timeout: int = 300,
    **kwargs,
) -> dict[str, Any]:
    """Return dict with keys: content, model, latency, input_tokens, output_tokens."""
    ...
```

Required return keys:
- `content` (str) -- the LLM response text
- `model` (str) -- actual model used
- `latency` (float) -- seconds elapsed

Optional return keys (for token tracking):
- `input_tokens` (int)
- `output_tokens` (int)

## Step by Step

1. **Write the provider function** in `src/langgraph_maestro/core/llm.py` near the other `_call_default_*` functions:
   ```python
   def _call_default_my_provider(prompt, model, system_prompt=..., cwd=None, timeout=300, **kwargs):
       # Make API call
       # Return {"content": ..., "model": ..., "latency": ...}
   ```

2. **Register it** at module level (bottom of llm.py, near existing registrations):
   ```python
   register_provider('my_provider', _call_default_my_provider)
   ```

3. **Add routing rule** in `get_provider()`. The function uses pattern matching on the model string:
   ```python
   # In get_provider(), before the default clause:
   if 'my_provider' in model.lower() or model.startswith('my-prefix/'):
       return 'my_provider', _providers['my_provider']
   ```
   Also supports explicit prefix syntax: `my_provider:model-name`.

4. **Add OTel tracing attributes** -- `call_llm()` automatically wraps your provider with OTel spans using GenAI semantic conventions. Your provider just needs to return the right keys. The tracing layer reads:
   - `gen_ai.system` -- set from provider name
   - `gen_ai.request.model` -- from model string
   - `gen_ai.usage.input_tokens` / `output_tokens` -- from return dict
   - `gen_ai.latency` -- from return dict

5. **Set the env var** -- add the API key to environment setup and document it in README.md.

6. **Add to mock_llm fixture** in `tests/conftest.py`:
   ```python
   with patch.dict('langgraph_maestro.core.llm._providers', {
       'claude_code': _mock,
       'local': _mock,
       'minimax': _mock,
       'my_provider': _mock,  # Add here
   }):
   ```

7. **Test** -- write a test that calls `call_llm(prompt, "my_provider:some-model")` with `mock_llm`.

## Existing Providers

| Name | Routing Pattern | Backend |
|------|----------------|---------|
| `claude_code` | Default fallback | Claude Code CLI subprocess |
| `minimax` | `minimax` in model name | MiniMax HTTP API |
| `local` | `mlx-community/` prefix or `local` | Local MLX via RAC |
| `codex` | `codex` or `gpt-` prefix | Codex CLI subprocess |

## Common Pitfalls

- **Missing return keys** -- `call_llm()` expects at least `content`, `model`, `latency`. Missing keys cause KeyError in tracing.
- **Forgot routing rule** -- without a `get_provider()` match, models fall through to `claude_code`.
- **Forgot mock registration** -- tests using `mock_llm` will route to the real provider if not added to the fixture.
- **Timeout handling** -- raise `TimeoutError` on timeout so `call_llm_with_fallback()` can try the next model.
- **API key not checked** -- check for the env var early and raise a clear error, not a cryptic HTTP 401.
