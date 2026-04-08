"""Web search and scraping via self-hosted SearXNG + Crawl4AI.

Provides two core functions:
  - web_search(query) → list of search results with URLs, titles, snippets
  - web_scrape(url) → clean markdown content from a page

Both hit the local Docker stack (started via `docker compose --profile search up -d`).
No API keys needed. Zero cost.

Usage:
    from langgraph_maestro.core.web import web_search, web_scrape, search_and_extract

    # Search
    results = await web_search("LangGraph checkpointing best practices")

    # Scrape a specific URL
    content = await web_scrape("https://docs.example.com/guide")

    # Search + scrape top results in one call
    findings = await search_and_extract("how to implement HITL in LangGraph", max_results=3)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Configurable via env vars
SEARXNG_URL = os.environ.get("MAESTRO_SEARXNG_URL", "http://localhost:8888")
CRAWL4AI_URL = os.environ.get("MAESTRO_CRAWL4AI_URL", "http://localhost:11235")

# Limits
DEFAULT_MAX_RESULTS = 5
MAX_CONTENT_LENGTH = 8000  # chars — prevents context blowup from huge pages


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    engine: str = ""
    score: float = 0.0


@dataclass
class ScrapedPage:
    """Scraped and cleaned page content."""
    url: str
    title: str
    content: str  # markdown
    content_length: int = 0
    truncated: bool = False
    error: Optional[str] = None


@dataclass
class SearchFinding:
    """A search result enriched with scraped content."""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    pages: list[ScrapedPage] = field(default_factory=list)
    error: Optional[str] = None


def _request_json(url: str, *, method: str = "GET", data: dict | None = None,
                  timeout: int = 30) -> dict:
    """Make an HTTP request and return parsed JSON."""
    if data is not None:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method,
                                    headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url, method=method)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def is_search_available() -> bool:
    """Check if the search stack (SearXNG + Crawl4AI) is reachable."""
    try:
        urllib.request.urlopen(f"{SEARXNG_URL}/healthz", timeout=3)
        return True
    except Exception:
        return False


def is_scrape_available() -> bool:
    """Check if Crawl4AI is reachable."""
    try:
        urllib.request.urlopen(f"{CRAWL4AI_URL}/health", timeout=3)
        return True
    except Exception:
        return False


def web_search(query: str, *, max_results: int = DEFAULT_MAX_RESULTS,
               engines: str = "") -> list[SearchResult]:
    """Search the web via SearXNG.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.
        engines: Comma-separated engine names (e.g. "google,duckduckgo").
                 Empty string uses all enabled engines.

    Returns:
        List of SearchResult objects.
    """
    params = {
        "q": query,
        "format": "json",
        "categories": "general",
    }
    if engines:
        params["engines"] = engines

    url = f"{SEARXNG_URL}/search?{urllib.parse.urlencode(params)}"

    try:
        data = _request_json(url, timeout=15)
    except urllib.error.URLError as e:
        logger.error("web_search: SearXNG not reachable at %s — %s", SEARXNG_URL, e)
        logger.info("web_search: start search stack with: "
                     "docker compose --profile search up -d")
        return []
    except Exception as e:
        logger.error("web_search: failed — %s", e)
        return []

    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
            engine=item.get("engine", ""),
            score=item.get("score", 0.0),
        ))

    logger.info("web_search: %d results for %r", len(results), query)
    return results


def web_scrape(url: str, *, max_length: int = MAX_CONTENT_LENGTH) -> ScrapedPage:
    """Scrape a URL and return clean markdown content via Crawl4AI.

    Args:
        url: The URL to scrape.
        max_length: Maximum content length in characters. Content beyond this
                    is truncated to prevent context window blowup.

    Returns:
        ScrapedPage with markdown content.
    """
    payload = {
        "urls": [url],
        "priority": 8,
        "word_count_threshold": 50,
    }

    try:
        data = _request_json(f"{CRAWL4AI_URL}/crawl", method="POST",
                             data=payload, timeout=60)
    except urllib.error.URLError as e:
        logger.error("web_scrape: Crawl4AI not reachable at %s — %s", CRAWL4AI_URL, e)
        return ScrapedPage(url=url, title="", content="",
                           error=f"Crawl4AI not reachable: {e}")
    except Exception as e:
        logger.error("web_scrape: failed for %s — %s", url, e)
        return ScrapedPage(url=url, title="", content="", error=str(e))

    # Crawl4AI v0.8+ returns: {"results": [{"markdown": {"raw_markdown": "..."}, "metadata": {...}}]}
    results_list = data.get("results", [])
    result = results_list[0] if results_list else data.get("result", data)
    if isinstance(result, list):
        result = result[0] if result else {}

    # markdown can be a string or a dict with raw_markdown
    md = result.get("markdown", "")
    if isinstance(md, dict):
        content = md.get("raw_markdown", "") or md.get("markdown_with_citations", "")
    else:
        content = md or ""
    if not content:
        content = result.get("cleaned_html", "") or ""

    title = result.get("metadata", {}).get("title", "") if isinstance(result.get("metadata"), dict) else ""

    truncated = len(content) > max_length
    if truncated:
        content = content[:max_length] + "\n\n[... truncated]"

    page = ScrapedPage(
        url=url,
        title=title,
        content=content,
        content_length=len(content),
        truncated=truncated,
    )

    logger.info("web_scrape: %d chars from %s%s", page.content_length, url,
                " (truncated)" if truncated else "")
    return page


def search_and_extract(query: str, *, max_results: int = 3,
                       max_length_per_page: int = MAX_CONTENT_LENGTH) -> SearchFinding:
    """Search the web and scrape the top results. One-call convenience.

    Args:
        query: Search query.
        max_results: Number of top results to scrape.
        max_length_per_page: Max content length per scraped page.

    Returns:
        SearchFinding with results and scraped pages.
    """
    finding = SearchFinding(query=query)

    results = web_search(query, max_results=max_results)
    finding.results = results

    if not results:
        finding.error = "No search results"
        return finding

    for result in results:
        page = web_scrape(result.url, max_length=max_length_per_page)
        finding.pages.append(page)

    logger.info("search_and_extract: %d pages scraped for %r",
                len(finding.pages), query)
    return finding


def format_findings_for_llm(finding: SearchFinding) -> str:
    """Format a SearchFinding into a string suitable for LLM context.

    Returns a concise summary with sources and key content.
    """
    if finding.error and not finding.results:
        return f"Web search failed: {finding.error}"

    parts = [f"## Web Research: {finding.query}\n"]

    for i, (result, page) in enumerate(zip(finding.results, finding.pages), 1):
        parts.append(f"### Source {i}: {result.title}")
        parts.append(f"URL: {result.url}")
        if page.error:
            parts.append(f"Scrape error: {page.error}")
            parts.append(f"Snippet: {result.snippet}")
        elif page.content:
            parts.append(page.content)
        else:
            parts.append(f"Snippet: {result.snippet}")
        parts.append("")

    return "\n".join(parts)
