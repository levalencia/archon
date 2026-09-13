"""Bounded official-source web supplementation for the learning tutor.

Web results are ephemeral, never persisted in the trusted corpus.
HTTPS official-domain allowlisting happens BEFORE any page content extraction
to prevent SSRF and untrusted fetches.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import structlog

from app.tools.web_search import web_search_tool

logger = structlog.get_logger()

# ── Official domain allowlist ──────────────────────────────────────────────
# Only HTTPS pages from these domains (and their subdomains) are fetched.
DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "docs.python.org",
        "learn.microsoft.com",
        "developer.mozilla.org",
        "docs.aws.amazon.com",
        "cloud.google.com",
        "kubernetes.io",
        "docs.docker.com",
        "fastapi.tiangolo.com",
        "starlette.io",
        "pydantic-docs.helpmanual.io",
        "docs.pydantic.dev",
        "www.postgresql.org",
        "redis.io",
        "opentelemetry.io",
        "swagger.io",
        "spec.openapis.org",
        "www.rfc-editor.org",
        "datatracker.ietf.org",
    }
)

_MAX_WEB_RESULTS = 3
_MAX_CONTENT_CHARS = 2000
_MAX_QUERY_LEN = 300
_STRIP_SCRIPT = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL)
_STRIP_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL)
_STRIP_TAGS = re.compile(r"<[^>]+>")
_COLLAPSE_WS = re.compile(r"\s+")
_STRIP_URL = re.compile(r"https?://\S+")
_STRIP_HTML_TAG = re.compile(r"<[^>]*>")
_STRIP_SEARCH_OPERATOR = re.compile(r"(?i)(?<!\S)(?:site|filetype|inurl|intitle):\S+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── Concept-to-keyword routing table ───────────────────────────────────────
# Maps concept slugs to search keywords added for better official-source targeting.
_CONCEPT_KEYWORDS: dict[str, list[str]] = {
    "object-oriented-programming": ["Python", "OOP", "classes"],
    "python-architecture": ["Python", "architecture", "modules"],
    "async-programming": ["Python", "asyncio", "async", "await"],
    "fastapi-dependency-injection": ["FastAPI", "Depends", "dependency injection"],
    "opentelemetry-observability": ["OpenTelemetry", "tracing", "observability"],
    "server-sent-events": ["server-sent events", "SSE", "EventSource"],
    "safe-default-patterns": ["Python", "safe defaults", "sentinel"],
    "fastapi-factory": ["FastAPI", "application factory", "create_app"],
    "pydantic-validation": ["Pydantic", "validation", "BaseModel"],
    "python-decorators": ["Python", "decorators", "@"],
    "python-type-hints": ["Python", "type hints", "typing"],
}


@dataclass(frozen=True, slots=True)
class WebEvidence:
    """Ephemeral, non-authoritative web evidence. Never persisted in the trusted corpus."""

    id: str
    kind: str  # always "web"
    title: str
    url: str
    snippet: str
    content: str
    domain: str
    retrieved_at: float  # epoch seconds
    search_source: str  # e.g. "brave", "searxng", "none"

    @property
    def content_hash(self) -> str:
        """Bind citations to the exact fetched excerpt used for verification."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "domain": self.domain,
            "retrieved_at": self.retrieved_at,
            "search_source": self.search_source,
        }


def is_allowed_url(url: str, allowed_domains: frozenset[str] | None = None) -> bool:
    """Check URL against the HTTPS official-domain allowlist BEFORE any fetch."""
    domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False
    # Exact match or subdomain match
    return any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in domains)


def filter_allowed_results(
    results: list[dict[str, Any]],
    allowed_domains: frozenset[str] | None = None,
    max_results: int = _MAX_WEB_RESULTS,
) -> list[dict[str, Any]]:
    """Filter search results to only HTTPS official-domain URLs, BEFORE content extraction."""
    filtered = []
    for result in results:
        url = result.get("url", "")
        if is_allowed_url(url, allowed_domains) and len(filtered) < max_results:
            filtered.append(result)
    return filtered


def build_concept_query(
    question: str,
    *,
    concepts: list[str] | None = None,
) -> str:
    """Build a concept-aware search query for official-source targeting.

    Sanitises the question (removes URLs, HTML tags) then enriches with
    concept-specific keywords so that search engines return relevant
    official documentation pages.
    """
    if not question or not question.strip():
        return ""

    # Sanitise: strip URLs, script/style blocks, and HTML tags to prevent injection
    cleaned = _STRIP_URL.sub("", question)
    cleaned = _STRIP_SCRIPT.sub("", cleaned)
    cleaned = _STRIP_STYLE.sub("", cleaned)
    cleaned = _STRIP_HTML_TAG.sub("", cleaned)
    cleaned = _STRIP_SEARCH_OPERATOR.sub("", cleaned)
    cleaned = _COLLAPSE_WS.sub(" ", cleaned).strip()

    if not cleaned:
        return ""

    if not concepts:
        return cleaned[:_MAX_QUERY_LEN]

    # Collect unique keywords from concept routing table
    seen: set[str] = set()
    extras: list[str] = []
    for concept in concepts:
        for kw in _CONCEPT_KEYWORDS.get(concept, []):
            kw_lower = kw.lower()
            # Only add keyword if not already present in the question
            if kw_lower not in cleaned.lower() and kw_lower not in seen:
                extras.append(kw)
                seen.add(kw_lower)

    enriched = cleaned + " " + " ".join(extras) if extras else cleaned

    return enriched[:_MAX_QUERY_LEN]


def extract_relevant_sentences(
    text: str,
    query: str,
    *,
    max_chars: int = _MAX_CONTENT_CHARS,
) -> str:
    """Extract query-relevant sentences from fetched page text.

    Uses token overlap scoring to rank sentences by relevance to the
    search query. Falls back to leading text when no strong matches.
    Only selects from existing text — never synthesises content.
    """
    if not text:
        return ""

    if not query or not query.strip():
        return text[:max_chars]

    # Tokenise query into lowercase words for matching
    query_tokens = {w.lower() for w in re.findall(r"\w+", query) if len(w) > 2}

    if not query_tokens:
        return text[:max_chars]

    # Split into sentences
    sentences = _SENTENCE_SPLIT.split(text.strip())

    if not sentences:
        return text[:max_chars]

    # Score each sentence by number of distinct query tokens it contains
    scored: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        score = sum(1 for t in query_tokens if t in sentence_lower)
        scored.append((score, idx, sentence))

    # Sort by score descending, then original order for ties
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Take top-scoring sentences, respecting max_chars
    selected: list[tuple[int, str]] = []
    total_len = 0
    for score, idx, sentence in scored:
        # Only include sentences with at least one matching token,
        # unless we have nothing yet (fallback)
        if score == 0 and selected:
            break
        if total_len + len(sentence) > max_chars and selected:
            break
        selected.append((idx, sentence))
        total_len += len(sentence) + 1  # +1 for space

    if not selected:
        return text[:max_chars]

    # Re-sort by original order so text reads naturally
    selected.sort(key=lambda x: x[0])
    return " ".join(s for _, s in selected)


async def search_official_web(
    query: str,
    *,
    allowed_domains: frozenset[str] | None = None,
    max_results: int = _MAX_WEB_RESULTS,
) -> tuple[list[WebEvidence], dict[str, Any]]:
    """Search the web and return only results from allowlisted official domains.

    Returns (evidence_list, observability_metadata).
    Domain allowlisting happens BEFORE page content extraction.
    """
    domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS
    obs: dict[str, Any] = {
        "web_search_attempted": True,
        "allowed_domains_count": len(domains),
    }
    start = time.monotonic()

    try:
        # Search for more results than needed since many will be filtered out
        raw = await web_search_tool(
            query,
            num_results=max_results * 3,
            enrich_content=False,
        )
        obs["search_source"] = raw.get("source", "none")
        obs["raw_result_count"] = raw.get("total", 0)
    except Exception as exc:
        logger.warning("tutor_web_search_failed", error_type=type(exc).__name__)
        obs["search_source"] = "error"
        obs["raw_result_count"] = 0
        obs["web_search_error"] = type(exc).__name__
        obs["web_search_duration_ms"] = round((time.monotonic() - start) * 1000, 1)
        return [], obs

    # Filter to allowlisted domains BEFORE any content extraction
    raw_results = raw.get("results", [])
    allowed = filter_allowed_results(raw_results, domains, max_results)
    obs["allowed_result_count"] = len(allowed)
    obs["filtered_out_count"] = len(raw_results) - len(allowed)

    if not allowed:
        obs["web_search_duration_ms"] = round((time.monotonic() - start) * 1000, 1)
        return [], obs

    # Extract content ONLY from allowlisted URLs
    enriched = await _safe_extract_content(allowed, query=query)

    evidence: list[WebEvidence] = []
    extraction_success = 0
    now = time.time()
    for idx, item in enumerate(enriched):
        url = item.get("url", "")
        parsed = urlparse(url)
        content = (item.get("content") or item.get("snippet", ""))[:_MAX_CONTENT_CHARS]
        if item.get("content") and item["content"] != item.get("snippet", ""):
            extraction_success += 1
        evidence.append(
            WebEvidence(
                id=f"W{idx + 1}",
                kind="web",
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                content=content,
                domain=(parsed.hostname or "").lower(),
                retrieved_at=now,
                search_source=raw.get("source", "none"),
            )
        )

    obs["web_evidence_count"] = len(evidence)
    obs["extraction_success_count"] = extraction_success
    obs["web_search_duration_ms"] = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        "tutor_web_supplement",
        evidence_count=len(evidence),
        search_source=raw.get("source", "none"),
    )
    return evidence, obs


async def _safe_extract_content(
    results: list[dict[str, Any]], max_chars: int = _MAX_CONTENT_CHARS, query: str = ""
) -> list[dict[str, Any]]:
    """Extract page content from pre-allowlisted URLs only.

    When *query* is provided, uses query-relevant sentence extraction
    to return the most pertinent excerpt rather than a blind truncation.
    """
    import httpx

    async with httpx.AsyncClient(
        timeout=5.0,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CogentrexBot/1.0)"},
    ) as client:
        for result in results:
            url = result["url"]
            # Double-check allowlist (defense in depth)
            if not is_allowed_url(url):
                result["content"] = result.get("snippet", "")
                continue
            if not await _resolves_to_public_host(url):
                result["content"] = result.get("snippet", "")
                continue
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    text = r.text
                    text = _STRIP_SCRIPT.sub("", text)
                    text = _STRIP_STYLE.sub("", text)
                    text = _STRIP_TAGS.sub(" ", text)
                    text = _COLLAPSE_WS.sub(" ", text).strip()
                    # Use query-relevant extraction when query is available
                    if query:
                        result["content"] = extract_relevant_sentences(
                            text, query, max_chars=max_chars
                        )
                    else:
                        result["content"] = text[:max_chars]
                else:
                    result["content"] = result.get("snippet", "")
            except Exception:
                result["content"] = result.get("snippet", "")
    return results


async def _resolves_to_public_host(url: str) -> bool:
    """Reject official-looking URLs that resolve to non-public network addresses."""
    parsed = urlparse(url)
    if parsed.hostname is None:
        return False
    try:
        infos = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            ),
            timeout=2.0,
        )
    except (TimeoutError, socket.gaierror):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def format_web_evidence_for_prompt(evidence: list[WebEvidence]) -> str:
    """Format web evidence as clearly-labeled supplemental context for the LLM prompt."""
    if not evidence:
        return ""
    parts = ["BEGIN SUPPLEMENTAL WEB EVIDENCE (non-authoritative, for general definitions only)"]
    for item in evidence:
        parts.append(
            f"<{item.id} kind=web domain={item.domain} url={item.url} "
            f"title={json.dumps(item.title)}>\n{item.content}\n</{item.id}>"
        )
    parts.append("END SUPPLEMENTAL WEB EVIDENCE")
    return "\n\n".join(parts)
