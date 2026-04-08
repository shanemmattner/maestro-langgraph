"""Tests for the web search and scraping module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from langgraph_maestro.core.web import (
    SearchFinding,
    SearchResult,
    ScrapedPage,
    format_findings_for_llm,
    is_scrape_available,
    is_search_available,
    search_and_extract,
    web_scrape,
    web_search,
)


# ── Health checks ──────────────────────────────────────────────────

class TestHealthChecks:
    def test_search_available_when_reachable(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen") as mock:
            mock.return_value.__enter__ = MagicMock()
            mock.return_value.__exit__ = MagicMock()
            assert is_search_available() is True

    def test_search_unavailable_when_unreachable(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen", side_effect=Exception("conn refused")):
            assert is_search_available() is False

    def test_scrape_available_when_reachable(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen") as mock:
            mock.return_value.__enter__ = MagicMock()
            mock.return_value.__exit__ = MagicMock()
            assert is_scrape_available() is True

    def test_scrape_unavailable_when_unreachable(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen", side_effect=Exception("conn refused")):
            assert is_scrape_available() is False


# ── web_search ─────────────────────────────────────────────────────

class TestWebSearch:
    def _mock_response(self, results):
        """Create a mock urllib response with JSON data."""
        data = json.dumps({"results": results}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_returns_search_results(self):
        results = [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1", "engine": "google", "score": 0.9},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2", "engine": "bing", "score": 0.7},
        ]
        with patch("langgraph_maestro.core.web.urllib.request.urlopen", return_value=self._mock_response(results)):
            res = web_search("test query")
            assert len(res) == 2
            assert res[0].title == "Result 1"
            assert res[0].url == "https://example.com/1"
            assert res[0].snippet == "Snippet 1"
            assert res[1].engine == "bing"

    def test_respects_max_results(self):
        results = [{"title": f"R{i}", "url": f"https://e.com/{i}", "content": ""} for i in range(10)]
        with patch("langgraph_maestro.core.web.urllib.request.urlopen", return_value=self._mock_response(results)):
            res = web_search("test", max_results=3)
            assert len(res) == 3

    def test_returns_empty_on_connection_error(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   side_effect=Exception("conn refused")):
            res = web_search("test query")
            assert res == []

    def test_handles_empty_results(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   return_value=self._mock_response([])):
            res = web_search("test query")
            assert res == []


# ── web_scrape ─────────────────────────────────────────────────────

class TestWebScrape:
    def _mock_response(self, result):
        data = json.dumps(result).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_returns_markdown_content(self):
        response = {
            "result": {
                "markdown": "# Hello World\n\nSome content here.",
                "metadata": {"title": "Test Page"},
            }
        }
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   return_value=self._mock_response(response)):
            page = web_scrape("https://example.com")
            assert "Hello World" in page.content
            assert page.title == "Test Page"
            assert page.url == "https://example.com"
            assert page.error is None

    def test_truncates_long_content(self):
        long_content = "x" * 20000
        response = {"result": {"markdown": long_content, "metadata": {"title": "Big"}}}
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   return_value=self._mock_response(response)):
            page = web_scrape("https://example.com", max_length=100)
            assert len(page.content) < 200  # 100 + truncation notice
            assert page.truncated is True
            assert "[... truncated]" in page.content

    def test_returns_error_on_connection_failure(self):
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   side_effect=Exception("timeout")):
            page = web_scrape("https://example.com")
            assert page.error is not None
            assert page.content == ""

    def test_handles_list_result_format(self):
        response = {"result": [{"markdown": "Content", "metadata": {"title": "T"}}]}
        with patch("langgraph_maestro.core.web.urllib.request.urlopen",
                   return_value=self._mock_response(response)):
            page = web_scrape("https://example.com")
            assert page.content == "Content"


# ── search_and_extract ─────────────────────────────────────────────

class TestSearchAndExtract:
    def test_combines_search_and_scrape(self):
        search_results = [
            {"title": "Page 1", "url": "https://example.com/1", "content": "Snippet 1"},
        ]
        search_data = json.dumps({"results": search_results}).encode()
        scrape_data = json.dumps({"result": {"markdown": "Full content", "metadata": {"title": "Page 1"}}}).encode()

        def side_effect(req, timeout=30):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            url = req if isinstance(req, str) else req.full_url
            if "search" in url:
                mock_resp.read.return_value = search_data
            else:
                mock_resp.read.return_value = scrape_data
            return mock_resp

        with patch("langgraph_maestro.core.web.urllib.request.urlopen", side_effect=side_effect):
            finding = search_and_extract("test query", max_results=1)
            assert len(finding.results) == 1
            assert len(finding.pages) == 1
            assert finding.pages[0].content == "Full content"

    def test_returns_error_when_no_results(self):
        search_data = json.dumps({"results": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = search_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("langgraph_maestro.core.web.urllib.request.urlopen", return_value=mock_resp):
            finding = search_and_extract("test query")
            assert finding.error == "No search results"
            assert finding.pages == []


# ── format_findings_for_llm ────────────────────────────────────────

class TestFormatFindings:
    def test_formats_with_content(self):
        finding = SearchFinding(
            query="test",
            results=[SearchResult(title="Page 1", url="https://e.com", snippet="snip")],
            pages=[ScrapedPage(url="https://e.com", title="Page 1", content="Full content here")],
        )
        output = format_findings_for_llm(finding)
        assert "Web Research: test" in output
        assert "Source 1: Page 1" in output
        assert "Full content here" in output

    def test_formats_with_scrape_error(self):
        finding = SearchFinding(
            query="test",
            results=[SearchResult(title="Page 1", url="https://e.com", snippet="snip")],
            pages=[ScrapedPage(url="https://e.com", title="", content="", error="timeout")],
        )
        output = format_findings_for_llm(finding)
        assert "Scrape error: timeout" in output
        assert "Snippet: snip" in output

    def test_formats_total_failure(self):
        finding = SearchFinding(query="test", error="No search results")
        output = format_findings_for_llm(finding)
        assert "Web search failed" in output
