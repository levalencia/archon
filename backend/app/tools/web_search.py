"""Real web search tool using DuckDuckGo HTML scraping. No API key needed.

Falls back to mock results if network is unavailable.
"""

from __future__ import annotations

import re

import httpx
import structlog

logger = structlog.get_logger()


async def web_search_tool(query: str, max_results: int = 3) -> dict:
    """Search the web using DuckDuckGo HTML. No API key required.

    Scrapes DuckDuckGo's HTML lite page for search results.
    Falls back to mock results if scraping fails.
    """
    try:
        results = await _ddg_search(query, max_results)
        if results:
            logger.info("web_search_real", query=query, results=len(results))
            return {
                "query": query,
                "results": results,
                "total": len(results),
                "source": "duckduckgo",
            }
    except Exception as e:
        logger.warning("web_search_fallback", query=query, error=str(e))

    # Fallback to mock
    return {
        "query": query,
        "results": [
            {
                "title": f"Result for: {query}",
                "url": f"https://example.com/search?q={query}",
                "snippet": f"Mock result about {query}. Real search unavailable.",
            }
        ],
        "total": 1,
        "source": "mock",
    }


async def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Scrape DuckDuckGo HTML lite for search results."""
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.post(url, data={"q": query}, headers=headers)
        response.raise_for_status()
        html = response.text

    results = []
    # Parse results from DuckDuckGo HTML lite
    # Each result has class="result" with a link and snippet
    result_blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:td|span)',
        html,
        re.DOTALL,
    )

    for link, title, snippet in result_blocks[:max_results]:
        # Clean URL (DuckDuckGo wraps in redirect)
        clean_url = link
        uddg_match = re.search(r"uddg=([^&]+)", link)
        if uddg_match:
            from urllib.parse import unquote

            clean_url = unquote(uddg_match.group(1))

        # Clean HTML tags from title and snippet
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()

        if clean_title and clean_url:
            results.append(
                {
                    "title": clean_title,
                    "url": clean_url,
                    "snippet": clean_snippet,
                }
            )

    return results
