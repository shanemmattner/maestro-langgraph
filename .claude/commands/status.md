Quick health check for the langgraph-maestro project.

Run these checks and report a summary:

1. Git status:
   ```
   cd /Users/shanemattner/Desktop/tuned_voice_repos/langgraph-maestro-oss
   git status --short
   git log --oneline -5
   ```

2. Setup verification:
   ```
   uv run maestro verify
   ```

3. Test count (without running them):
   ```
   uv run pytest tests/ --collect-only -q 2>/dev/null | tail -1
   ```

4. List available workflows:
   ```
   uv run maestro list
   ```

5. Check environment variables:
   - ANTHROPIC_API_KEY (set/unset, never print the value)
   - MINIMAX_API_KEY (set/unset)
   - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (set/unset)

Report one line per check: PASS/FAIL/WARN with details. Read-only -- do not modify anything.

$ARGUMENTS
