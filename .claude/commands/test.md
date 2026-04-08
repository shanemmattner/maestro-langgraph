Run the langgraph-maestro test suite.

Arguments: $ARGUMENTS

1. If no arguments given, run the full suite:
   ```
   uv run pytest tests/ -v --tb=short
   ```

2. If arguments specify a file or pattern:
   - File path: `uv run pytest $ARGUMENTS -v --tb=short`
   - Test name pattern: `uv run pytest tests/ -v --tb=short -k "$ARGUMENTS"`

3. Report results: total passed/failed/skipped, and list any failures with the relevant assertion or error message.

4. If tests fail, read the failing test file and the source it tests, then suggest a fix.

Tip: Use `-m "not slow"` to skip slow integration tests during development.
