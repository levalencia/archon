"""Web search via SearXNG (self-hosted) + content extraction.

Pipeline: SearXNG JSON API → get URLs + snippets → extract full page content.
No API keys, no rate limits, self-hosted.

Fallback: DuckDuckGo HTML scraping if SearXNG is unavailable.
"""

from __future__ import annotations

import re

import httpx
import structlog

logger = structlog.get_logger()

SEARXNG_URL = "http://localhost:8888"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


async def web_search_tool(query: str, max_results: int = 5) -> dict:
    """Search the web via SearXNG + extract page content.

    1. SearXNG JSON API → URLs + snippets + content
    2. Visit top N URLs → extract full text
    3. Return rich results for LLM summarization
    """
    # Step 1: Search via SearXNG
    results = await _searxng_search(query, max_results)

    if not results:
        logger.warning("searxng_unavailable_trying_ddg", query=query)
        results = await _ddg_search(query, max_results)

    if not results:
        return {
            "query": query,
            "results": [],
            "total": 0,
            "source": "none",
            "note": "No results found",
        }

    # Step 2: Enrich with page content for results that lack it
    for result in results:
        if result.get("content") and len(result["content"]) > 200:
            continue  # SearXNG already gave good content
        url = result.get("url", "")
        if not url or "example.com" in url:
            continue
        try:
            content = await _extract_page_content(url)
            if len(content) > len(result.get("content", "")):
                result["content"] = content[:2000]
                result["content_length"] = len(content)
        except Exception:
            pass

    total_content = sum(len(r.get("content", "")) for r in results)
    logger.info(
        "web_search_complete",
        query=query,
        results=len(results),
        total_content_chars=total_content,
    )

    return {
        "query": query,
        "results": results,
        "total": len(results),
        "source": "searxng",
        "content_extracted": total_content > 0,
    }


async def _searxng_search(query: str, max_results: int) -> list[dict]:
    """Search via SearXNG JSON API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json"},
            )
            r.raise_for_status()
            data = r.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "engine": item.get("engine", ""),
                }
            )

        logger.info(
            "searxng_search",
            query=query,
            results=len(results),
        )
        return results

    except Exception as e:
        logger.warning("searxng_error", error=str(e))
        return []


async def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Fallback: DuckDuckGo HTML scraping."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers=_HEADERS,
            )
            response.raise_for_status()
            html = response.text

        results = []
        blocks = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(.*?)</(?:td|span)',
            html,
            re.DOTALL,
        )

        for link, title, snippet in blocks[:max_results]:
            clean_url = link
            m = re.search(r"uddg=([^&]+)", link)
            if m:
                from urllib.parse import unquote

                clean_url = unquote(m.group(1))

            results.append(
                {
                    "title": re.sub(r"<[^>]+>", "", title).strip(),
                    "url": clean_url,
                    "content": re.sub(r"<[^>]+>", "", snippet).strip(),
                }
            )

        return results
    except Exception:
        return []


async def _extract_page_content(url: str) -> str:
    """Extract main text from a URL."""
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        response = await client.get(url, headers=_HEADERS)
        response.raise_for_status()
        html = response.text

    for tag in [
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "aside",
        "noscript",
    ]:
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    return text
