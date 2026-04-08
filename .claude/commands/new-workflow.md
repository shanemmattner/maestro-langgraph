Scaffold a new maestro workflow and guide the user through customization.

Workflow name: $ARGUMENTS

1. Run the scaffold command:
   ```
   uv run maestro init --dir "src/langgraph_maestro/workflows/$ARGUMENTS" --name "$ARGUMENTS"
   ```

2. Read the generated files: `config.yaml`, `graph.py`, `state.py`, and any prompt files.

3. Ask the user what this workflow should do. Based on their answer:
   - Update `config.yaml` with appropriate phases, models, and loop limits
   - Customize `graph.py` with the right node sequence and edges
   - Update `state.py` with the fields the workflow needs

4. Register the workflow by adding an import to `src/langgraph_maestro/workflows/__init__.py`.

5. Verify it appears in `uv run maestro list`.

Reference the existing workflows in `src/langgraph_maestro/workflows/` for patterns.
