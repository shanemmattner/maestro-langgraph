Run a maestro workflow.

Arguments: $ARGUMENTS
Format: `workflow_name task description here`

Parse the first word as the workflow name and the rest as the task description.

1. If no arguments provided, run `uv run maestro list` and ask the user which workflow to run.

2. Run the workflow:
   ```
   uv run maestro run <workflow_name> --task "<task_description>" --cwd . --json
   ```

3. Parse the JSON output and present a clear summary:
   - Verdict or final answer
   - Subtask statuses
   - Any review issues flagged

If the run fails, check `uv run maestro verify` to diagnose setup issues.
