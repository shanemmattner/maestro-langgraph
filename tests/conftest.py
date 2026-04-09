import logging
import pytest
from unittest.mock import patch, MagicMock
from langgraph_maestro.core.logging import setup_logging


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
