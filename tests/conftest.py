import logging
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock
from langgraph_maestro.core.config import clear_cache
from langgraph_maestro.core.logging import setup_logging


@pytest.fixture
def tmp_config(tmp_path):
    def _make(content: dict):
        f = tmp_path / 'config.yaml'
        f.write_text(yaml.dump(content))
        clear_cache()
        return str(f)
    yield _make
    clear_cache()


@pytest.fixture(autouse=True)
def disable_pe(request):
    """Disable PE in all tests so it doesn't consume mock responses or hit real APIs.

    Tests that explicitly test PE should mark with @pytest.mark.enable_pe to skip this.
    """
    if 'enable_pe' in [m.name for m in request.node.iter_markers()]:
        yield
    else:
        with patch('langgraph_maestro.core.pe.improve_prompt', side_effect=lambda prompt, **kwargs: prompt):
            yield


@pytest.fixture(autouse=True)
def deterministic_eval(request):
    """No-op fixture — execute node no longer calls evaluate_subtask inline.

    Kept for backwards compatibility with tests marked @pytest.mark.enable_eval.
    """
    yield


@pytest.fixture
def mock_llm():
    responses = []
    def _mock(prompt, model, **kwargs):
        if responses:
            return responses.pop(0)
        return {'content': 'mock response', 'model': model, 'latency': 0.1}
    # Patch the _providers dict to replace all registered providers
    with patch.dict('langgraph_maestro.core.llm._providers', {
        'claude_code': _mock,
        'local': _mock,
        'minimax': _mock
    }):
        yield responses


@pytest.fixture
def mock_llm_json(mock_llm):
    import json
    def _set(data: dict):
        mock_llm.append({'content': json.dumps(data), 'model': 'mock', 'latency': 0.1})
    return _set


@pytest.fixture
def setup_test_logging(tmp_path):
    """Configure logging to write to tmp_path for test inspection."""
    log_file = setup_logging(
        level=logging.DEBUG,
        log_dir=str(tmp_path),
        workflow_name="test",
    )
    yield log_file
    # Clean up handlers after test
    root = logging.getLogger()
    root.handlers.clear()
