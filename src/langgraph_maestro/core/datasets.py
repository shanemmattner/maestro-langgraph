"""Golden dataset management via Langfuse REST API.

No SDK imports. Python 3.14 compatible.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable

from langgraph_maestro.core.tracing import _langfuse_auth_header, _langfuse_host

logger = logging.getLogger(__name__)


def _make_request(
    method: str,
    endpoint: str,
    data: dict | None = None,
    timeout: int = 30,
) -> dict | None:
    """Make a request to Langfuse REST API.

    Returns:
        dict: JSON response on success
        None: On 404 (not found) or other errors
    """
    host = _langfuse_host()
    url = f"{host}{endpoint}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": _langfuse_auth_header(),
    }

    payload = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug("langfuse_not_found", extra={"url": url})
            return None
        if e.code == 409:
            # Conflict - dataset already exists
            body = e.read()
            try:
                error_body = json.loads(body) if body else {}
                logger.debug("langfuse_conflict", extra={"error": error_body})
            except Exception:
                pass
            raise
        # Re-raise for other HTTP errors
        raise
    except Exception as e:
        logger.warning("langfuse_request_error", extra={"error": str(e), "url": url})
        return None


def create_dataset(name: str, description: str = "") -> dict:
    """Create a new dataset in Langfuse.

    Args:
        name: Dataset name
        description: Optional description

    Returns:
        dict: Created dataset from API response

    Raises:
        Exception: On 409 (already exists) or other HTTP errors
    """
    logger.info("creating_dataset", extra={"name": name})
    data = {"name": name}
    if description:
        data["description"] = description

    result = _make_request("POST", "/api/public/v2/datasets", data)
    if result:
        logger.info("dataset_created", extra={"name": name})
    return result or {}


def add_dataset_item(
    dataset_name: str,
    input: dict,
    expected_output: dict,
    metadata: dict | None = None,
) -> dict:
    """Add an item to a dataset.

    Args:
        dataset_name: Name of the dataset
        input: Input data dict
        expected_output: Expected output data dict
        metadata: Optional metadata dict

    Returns:
        dict: Created item from API response
    """
    logger.debug("adding_dataset_item", extra={"dataset": dataset_name})
    data = {
        "datasetName": dataset_name,
        "input": input,
        "expectedOutput": expected_output,
    }
    if metadata:
        data["metadata"] = metadata

    result = _make_request("POST", "/api/public/v2/dataset-items", data)
    if result:
        logger.debug("dataset_item_added", extra={"dataset": dataset_name})
    return result or {}


def get_dataset(name: str) -> dict | None:
    """Get a dataset by name.

    Args:
        name: Dataset name

    Returns:
        dict: Dataset data if found, None if not found (404)
    """
    logger.debug("getting_dataset", extra={"name": name})
    result = _make_request("GET", f"/api/public/v2/datasets/{name}")
    return result


def list_datasets() -> list[dict]:
    """List all datasets.

    Returns:
        list[dict]: List of datasets
    """
    logger.debug("listing_datasets")
    result = _make_request("GET", "/api/public/v2/datasets")
    if result and isinstance(result, dict):
        return result.get("data", [])
    return []


def run_eval(
    dataset_name: str,
    run_name: str,
    eval_fn: Callable[[dict], dict],
    model: str = "minimax:MiniMax-M2.5-highspeed",
) -> dict:
    """Run evaluation on a dataset.

    Iterates through all items in the dataset, calls eval_fn(item) for each,
    and logs results as dataset run items.

    Args:
        dataset_name: Name of the dataset
        run_name: Name for this evaluation run
        eval_fn: Function that takes a dataset item dict and returns evaluation result
        model: Model to use for evaluation (default: minimax:MiniMax-M2.5-highspeed)

    Returns:
        dict: Summary with run info and results
    """
    logger.info("starting_eval_run", extra={"dataset": dataset_name, "run": run_name})

    # Get dataset items
    dataset = get_dataset(dataset_name)
    if not dataset:
        logger.error("dataset_not_found", extra={"dataset": dataset_name})
        return {"error": "dataset_not_found", "dataset_name": dataset_name}

    items = dataset.get("datasetItems", {}).get("data", [])
    if not items:
        logger.warning("no_items_in_dataset", extra={"dataset": dataset_name})
        return {
            "dataset_name": dataset_name,
            "run_name": run_name,
            "total_items": 0,
            "results": [],
        }

    logger.info("evaluating_items", extra={"count": len(items), "dataset": dataset_name})

    results = []
    for item in items:
        item_id = item.get("id")
        item_input = item.get("input", {})
        expected_output = item.get("expectedOutput", {})

        # Call eval function
        try:
            eval_result = eval_fn(item)
        except Exception as e:
            logger.warning("eval_fn_failed", extra={"item_id": item_id, "error": str(e)})
            eval_result = {"error": str(e)}

        # Prepare run item data
        run_item_data = {
            "datasetName": dataset_name,
            "runName": run_name,
            "datasetItemId": item_id,
            "input": item_input,
            "expectedOutput": expected_output,
            "output": eval_result.get("output", {}),
            "score": eval_result.get("score"),
            "comment": eval_result.get("reason", ""),
            "model": model,
        }

        # Log result to Langfuse
        try:
            _make_request("POST", "/api/public/v2/dataset-run-items", run_item_data)
        except Exception as e:
            logger.warning("failed_to_log_run_item", extra={"error": str(e)})

        results.append({
            "item_id": item_id,
            "result": eval_result,
        })

    summary = {
        "dataset_name": dataset_name,
        "run_name": run_name,
        "model": model,
        "total_items": len(items),
        "results": results,
    }

    logger.info("eval_run_complete", extra={"dataset": dataset_name, "run": run_name, "count": len(results)})
    return summary


def get_run_results(dataset_name: str, run_name: str) -> dict | None:
    """Get results for a specific evaluation run.

    Args:
        dataset_name: Name of the dataset
        run_name: Name of the run

    Returns:
        dict: Run results if found, None if not found
    """
    logger.debug("getting_run_results", extra={"dataset": dataset_name, "run": run_name})
    result = _make_request(
        "GET",
        f"/api/public/v2/dataset-run-items?datasetName={dataset_name}&runName={run_name}",
    )
    return result
