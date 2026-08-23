"""Web search + content extraction. Search → Get URLs → Extract content → Return rich results.

Like professional agents (Hermes, Perplexity): search first, then visit top pages
and extract real content for the LLM to summarize.
"""

from __future__ import annotations

import re

import httpx
import structlog

logger = structlog.get_logger()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


async def web_search_tool(query: str, max_results: int = 3) -> dict:
    """Search the web and extract content from top results.

    Pipeline:
    1. DuckDuckGo HTML search → get URLs + snippets
    2. Visit top N URLs → extract main text content
    3. Return rich results with real page content

    This is how professional agents (Hermes, Perplexity) work:
    search first, then read the actual pages.
    """
    # Step 1: Search DuckDuckGo
    search_results = await _ddg_search(query, max_results)

    if not search_results:
        logger.warning("web_search_no_results", query=query)
        return {
            "query": query,
            "results": [],
            "total": 0,
            "source": "duckduckgo",
            "note": "No results found",
        }

    # Step 2: Extract content from top URLs (parallel)
    enriched = []
    for result in search_results:
        url = result.get("url", "")
        if not url or "example.com" in url:
            enriched.append(result)
            continue

        try:
            content = await _extract_page_content(url)
            result["content"] = content[:2000]  # Cap at 2K chars
            result["content_length"] = len(content)
        except Exception as e:
            logger.debug("extract_failed", url=url, error=str(e))
            result["content"] = result.get("snippet", "")
            result["content_length"] = 0

        enriched.append(result)

    total_content = sum(r.get("content_length", 0) for r in enriched)
    logger.info(
        "web_search_complete",
        query=query,
        results=len(enriched),
        total_content_chars=total_content,
    )

    return {
        "query": query,
        "results": enriched,
        "total": len(enriched),
        "source": "duckduckgo",
        "content_extracted": total_content > 0,
    }


async def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Search DuckDuckGo HTML lite."""
    url = "https://html.duckduckgo.com/html/"

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.post(url, data={"q": query}, headers=_HEADERS)
        response.raise_for_status()
        html = response.text

    results = []
    result_blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:td|span)',
        html,
        re.DOTALL,
    )

    for link, title, snippet in result_blocks[:max_results]:
        clean_url = link
        uddg_match = re.search(r"uddg=([^&]+)", link)
        if uddg_match:
            from urllib.parse import unquote

            clean_url = unquote(uddg_match.group(1))

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


async def _extract_page_content(url: str) -> str:
    """Extract main text content from a URL.

    Strips HTML tags, scripts, styles, nav, footer.
    Returns clean text suitable for LLM summarization.
    """
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        response = await client.get(url, headers=_HEADERS)
        response.raise_for_status()
        html = response.text

    # Remove scripts, styles, nav, footer, header
    for tag in ["script", "style", "nav", "footer", "header", "aside"]:
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Remove common boilerplate phrases
    for phrase in [
        "Accept cookies",
        "Cookie policy",
        "Privacy policy",
        "Subscribe to",
        "Sign up for",
        "Advertisement",
    ]:
        text = text.replace(phrase, "")

    return text.strip()
