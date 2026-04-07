"""Unit tests for core/datasets module.

Mocks all HTTP calls to Langfuse REST API.
"""

import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from langgraph_maestro.core import datasets


class TestDatasets(unittest.TestCase):
    """Test cases for datasets module."""

    def _mock_response(self, status: int = 200, body: dict | list | None = None):
        """Create a mock HTTP response."""
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.read.return_value = json.dumps(body).encode() if body else b""
        return mock_resp

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_create_dataset_success(self, mock_urlopen, mock_auth, mock_host):
        """Test successful dataset creation."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        expected = {"id": "ds-123", "name": "test-dataset", "description": "Test dataset"}
        mock_urlopen.return_value.__enter__.return_value = self._mock_response(200, expected)

        result = datasets.create_dataset("test-dataset", "Test dataset")

        self.assertEqual(result["name"], "test-dataset")
        self.assertEqual(result["description"], "Test dataset")

        # Verify the request was made
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        self.assertIn("/api/public/v2/datasets", call_args[0][0].full_url)

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_create_dataset_already_exists(self, mock_urlopen, mock_auth, mock_host):
        """Test dataset creation when dataset already exists (409)."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        # Create an HTTPError for 409
        error = urllib.error.HTTPError(
            url="http://localhost:3100/api/public/v2/datasets/test",
            code=409,
            msg="Conflict",
            hdrs={},
            fp=None,
        )
        error.read = lambda: json.dumps({"error": "Dataset already exists"}).encode()
        mock_urlopen.side_effect = error

        with self.assertRaises(Exception) as context:
            datasets.create_dataset("existing-dataset")

        # Should raise on 409
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_add_dataset_item(self, mock_urlopen, mock_auth, mock_host):
        """Test adding an item to a dataset."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        expected = {"id": "item-123", "datasetName": "test-dataset"}
        mock_urlopen.return_value.__enter__.return_value = self._mock_response(200, expected)

        result = datasets.add_dataset_item(
            "test-dataset",
            input={"question": "What is 2+2?"},
            expected_output={"answer": "4"},
        )

        self.assertEqual(result["datasetName"], "test-dataset")

        # Verify POST request was made
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertIn("/api/public/v2/dataset-items", req.full_url)
        self.assertEqual(req.method, "POST")

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_get_dataset_success(self, mock_urlopen, mock_auth, mock_host):
        """Test successful dataset retrieval."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        expected = {
            "id": "ds-123",
            "name": "test-dataset",
            "datasetItems": {"data": []},
        }
        mock_urlopen.return_value.__enter__.return_value = self._mock_response(200, expected)

        result = datasets.get_dataset("test-dataset")

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "test-dataset")

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_get_dataset_not_found(self, mock_urlopen, mock_auth, mock_host):
        """Test getting a non-existent dataset returns None."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        # 404 error - must raise actual HTTPError, not MagicMock
        error = urllib.error.HTTPError(
            url="http://localhost:3100/api/public/v1/datasets/non-existent",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None
        )
        mock_urlopen.side_effect = error

        result = datasets.get_dataset("non-existent")

        self.assertIsNone(result)

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_list_datasets_empty(self, mock_urlopen, mock_auth, mock_host):
        """Test listing datasets when none exist."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        expected = {"data": []}
        mock_urlopen.return_value.__enter__.return_value = self._mock_response(200, expected)

        result = datasets.list_datasets()

        self.assertEqual(result, [])

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_list_datasets_with_items(self, mock_urlopen, mock_auth, mock_host):
        """Test listing datasets with items."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        expected = {
            "data": [
                {"id": "ds-1", "name": "dataset-1"},
                {"id": "ds-2", "name": "dataset-2"},
            ]
        }
        mock_urlopen.return_value.__enter__.return_value = self._mock_response(200, expected)

        result = datasets.list_datasets()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "dataset-1")
        self.assertEqual(result[1]["name"], "dataset-2")

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_run_eval_iterates_items(self, mock_urlopen, mock_auth, mock_host):
        """Test that run_eval iterates through all dataset items."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        # First call: get_dataset
        dataset_response = {
            "id": "ds-123",
            "name": "test-dataset",
            "datasetItems": {
                "data": [
                    {"id": "item-1", "input": {"q": "1"}, "expectedOutput": {"a": "1"}},
                    {"id": "item-2", "input": {"q": "2"}, "expectedOutput": {"a": "2"}},
                    {"id": "item-3", "input": {"q": "3"}, "expectedOutput": {"a": "3"}},
                ]
            },
        }
        # Subsequent calls: add_dataset_run_items
        run_item_response = {"id": "run-item-1"}

        mock_urlopen.return_value.__enter__.side_effect = [
            self._mock_response(200, dataset_response),  # get_dataset
            self._mock_response(200, run_item_response),  # run item 1
            self._mock_response(200, run_item_response),  # run item 2
            self._mock_response(200, run_item_response),  # run item 3
        ]

        eval_fn = MagicMock(return_value={"score": 1.0, "passed": True, "reason": "OK"})

        result = datasets.run_eval("test-dataset", "run-1", eval_fn)

        # Verify eval_fn was called 3 times
        self.assertEqual(eval_fn.call_count, 3)

        # Verify total_items
        self.assertEqual(result["total_items"], 3)

    @patch("langgraph_maestro.core.datasets._langfuse_host")
    @patch("langgraph_maestro.core.datasets._langfuse_auth_header")
    @patch("urllib.request.urlopen")
    def test_run_eval_logs_results(self, mock_urlopen, mock_auth, mock_host):
        """Test that run_eval logs results to dataset-run-items endpoint."""
        mock_host.return_value = "http://localhost:3100"
        mock_auth.return_value = "Basic dGVzdDp0ZXN0"

        # First call: get_dataset
        dataset_response = {
            "id": "ds-123",
            "name": "test-dataset",
            "datasetItems": {
                "data": [
                    {"id": "item-1", "input": {"q": "test"}, "expectedOutput": {"a": "expected"}},
                ]
            },
        }
        run_item_response = {"id": "run-item-1"}

        mock_urlopen.return_value.__enter__.side_effect = [
            self._mock_response(200, dataset_response),  # get_dataset
            self._mock_response(200, run_item_response),  # POST dataset-run-items
        ]

        def eval_fn(item):
            return {"score": 0.8, "passed": True, "reason": "Good", "output": {"result": "ok"}}

        result = datasets.run_eval("test-dataset", "run-1", eval_fn, model="test-model")

        # Verify POST to dataset-run-items was made
        # call.args[0] is the urllib.request.Request object — check its full_url
        post_calls = [
            call for call in mock_urlopen.call_args_list
            if "/api/public/v2/dataset-run-items" in getattr(call.args[0], "full_url", "")
        ]

        self.assertGreaterEqual(len(post_calls), 1)

        # Verify result contains expected data
        self.assertEqual(result["dataset_name"], "test-dataset")
        self.assertEqual(result["run_name"], "run-1")
        self.assertEqual(result["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
