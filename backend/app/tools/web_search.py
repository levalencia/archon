"""Web search via Brave Search API + content extraction.

Pipeline: Brave API → get URLs + snippets → extract full page content.
Fallback: SearXNG → DuckDuckGo scraping → mock.
"""
from __future__ import annotations

import re

import httpx
import structlog

logger = structlog.get_logger()

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


async def web_search_tool(query: str, num_results: int = 5) -> dict:
    """Search the web and extract content from top results."""
    import os

    brave_key = os.environ.get("ARCHON_BRAVE_API_KEY", "")

    # Try Brave Search API first
    if brave_key:
        try:
            results = await _brave_search(query, brave_key, num_results)
            if results:
                enriched = await _extract_content(results)
                return {
                    "query": query,
                    "results": enriched,
                    "total": len(enriched),
                    "source": "brave",
                }
        except Exception as e:
            logger.warning("brave_search_failed", error=str(e), query=query)

    # Fallback: SearXNG
    try:
        results = await _searxng_search(query, num_results)
        if results:
            enriched = await _extract_content(results)
            return {
                "query": query,
                "results": enriched,
                "total": len(enriched),
                "source": "searxng",
            }
    except Exception as e:
        logger.warning("searxng_search_failed", error=str(e))

    # Fallback: DuckDuckGo HTML scraping
    try:
        results = await _duckduckgo_search(query, num_results)
        if results:
            enriched = await _extract_content(results)
            return {
                "query": query,
                "results": enriched,
                "total": len(enriched),
                "source": "duckduckgo",
            }
    except Exception as e:
        logger.warning("duckduckgo_search_failed", error=str(e))

    logger.warning("web_search_no_results", query=query)
    return {"query": query, "results": [], "total": 0, "source": "none"}


async def _brave_search(query: str, api_key: str, num: int) -> list[dict]:
    """Search via Brave Search API."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            BRAVE_API_URL,
            params={"q": query, "count": num},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("web", {}).get("results", [])[:num]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })

    logger.info("brave_search", query=query, results=len(results))
    return results


async def _searxng_search(query: str, num: int) -> list[dict]:
    """Search via local SearXNG instance."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "http://localhost:8888/search",
            params={"q": query, "format": "json", "pageno": 1},
        )
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("results", [])[:num]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })

    logger.info("searxng_search", query=query, results=len(results))
    return results


async def _duckduckgo_search(query: str, num: int) -> list[dict]:
    """Fallback: scrape DuckDuckGo HTML."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        r = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )

    results = []
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.+?)</a>.*?'
        r'class="result__snippet"[^>]*>(.+?)</a>',
        r.text, re.DOTALL,
    ):
        url, title, snippet = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if url.startswith("//duckduckgo.com/l/?"):
            url_m = re.search(r"uddg=([^&]+)", url)
            if url_m:
                from urllib.parse import unquote
                url = unquote(url_m.group(1))
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= num:
            break

    return results


async def _extract_content(results: list[dict], max_chars: int = 3000) -> list[dict]:
    """Extract real page content from URLs."""
    async with httpx.AsyncClient(
        timeout=5.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ArchonBot/1.0)"},
    ) as client:
        for result in results:
            try:
                r = await client.get(result["url"])
                if r.status_code == 200:
                    text = r.text
                    # Strip HTML tags
                    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    result["content"] = text[:max_chars]
            except Exception:
                result["content"] = result.get("snippet", "")

    return results
