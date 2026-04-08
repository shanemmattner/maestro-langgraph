Add a new LLM provider to langgraph-maestro.

Provider name: $ARGUMENTS

1. Read `src/langgraph_maestro/core/llm.py` to understand the provider registry pattern:
   - `register_provider(name, fn)` registers a callable
   - `get_provider(model)` routes model strings to providers
   - Each provider function takes `(model, prompt, system_prompt, **kwargs)` and returns `{"text": str, "usage": dict}`

2. Ask the user for:
   - API base URL and auth mechanism (API key env var name)
   - Model name format (how users will reference models from this provider)
   - Whether it supports streaming

3. Implement the provider function following the existing patterns (claude_code, minimax, codex, local).

4. Register it in llm.py by:
   - Adding the provider function
   - Calling `register_provider("$ARGUMENTS", _call_$ARGUMENTS)`
   - Adding routing logic in `get_provider()` for the model prefix

5. Add the API key env var to the verify checks in `src/langgraph_maestro/cli.py` `_cmd_verify()`.

6. Add a test in `tests/` that mocks the API call and verifies routing.

7. Update README.md environment variables section.
