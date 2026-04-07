"""Tests for core.logging module."""

import json
import logging
import os

import pytest
from langgraph_maestro.core.logging import setup_logging, get_logger, JSONLineFormatter


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        log_file = setup_logging(level=logging.DEBUG, log_dir=str(tmp_path), workflow_name="test")
        assert os.path.exists(log_file)
        assert log_file.endswith(".jsonl")
        assert "test-" in log_file
        # Cleanup
        logging.getLogger().handlers.clear()

    def test_log_file_receives_entries(self, tmp_path):
        log_file = setup_logging(level=logging.DEBUG, log_dir=str(tmp_path), workflow_name="test")
        logger = logging.getLogger("test.module")
        logger.info("hello world")

        with open(log_file) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        # Should have at least the init message + our message
        assert len(lines) >= 2
        msgs = [l["msg"] for l in lines]
        assert "hello world" in msgs
        logging.getLogger().handlers.clear()

    def test_json_format_structure(self, tmp_path):
        log_file = setup_logging(level=logging.DEBUG, log_dir=str(tmp_path), workflow_name="test")
        logger = logging.getLogger("test.json")
        logger.info("structured", extra={"key": "value", "num": 42})

        with open(log_file) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        structured = [l for l in lines if l["msg"] == "structured"]
        assert len(structured) == 1
        entry = structured[0]
        assert entry["level"] == "INFO"
        assert entry["logger"] == "test.json"
        assert "ts" in entry
        assert entry["data"]["key"] == "value"
        assert entry["data"]["num"] == 42
        logging.getLogger().handlers.clear()

    def test_creates_log_dir(self, tmp_path):
        log_dir = str(tmp_path / "nested" / "dir")
        log_file = setup_logging(level=logging.INFO, log_dir=log_dir, workflow_name="test")
        assert os.path.isdir(log_dir)
        assert os.path.exists(log_file)
        logging.getLogger().handlers.clear()

    def test_no_duplicate_handlers_on_reinit(self, tmp_path):
        setup_logging(level=logging.INFO, log_dir=str(tmp_path), workflow_name="a")
        setup_logging(level=logging.INFO, log_dir=str(tmp_path), workflow_name="b")
        # Should have exactly 2 handlers (console + file), not 4
        assert len(logging.getLogger().handlers) == 2
        logging.getLogger().handlers.clear()


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.get")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.get"


class TestJSONLineFormatter:
    def test_formats_basic_record(self):
        fmt = JSONLineFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        line = fmt.format(record)
        data = json.loads(line)
        assert data["msg"] == "hello"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert "ts" in data
