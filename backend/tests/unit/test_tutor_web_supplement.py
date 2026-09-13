"""Tests for bounded official-source web supplementation."""

from __future__ import annotations

import pytest

from app.learning_tutor.web_supplement import (
    DEFAULT_ALLOWED_DOMAINS,
    WebEvidence,
    _resolves_to_public_host,
    build_concept_query,
    extract_relevant_sentences,
    filter_allowed_results,
    format_web_evidence_for_prompt,
    is_allowed_url,
)


class TestIsAllowedUrl:
    def test_https_official_domain(self):
        assert is_allowed_url("https://docs.python.org/3/library/asyncio.html") is True

    def test_https_subdomain_match(self):
        assert is_allowed_url("https://www.starlette.io/applications/") is True

    def test_https_unknown_domain_rejected(self):
        assert is_allowed_url("https://evil.example.com/page") is False

    def test_http_rejected(self):
        assert is_allowed_url("http://docs.python.org/3/library/asyncio.html") is False

    def test_empty_url(self):
        assert is_allowed_url("") is False

    def test_ftp_rejected(self):
        assert is_allowed_url("ftp://docs.python.org/file") is False

    def test_javascript_rejected(self):
        assert is_allowed_url("javascript:alert(1)") is False

    def test_file_scheme_rejected(self):
        assert is_allowed_url("file:///etc/passwd") is False

    def test_userinfo_rejected(self):
        assert is_allowed_url("https://attacker@docs.python.org/3/") is False

    def test_internal_ip_rejected(self):
        assert is_allowed_url("https://127.0.0.1/admin") is False
        assert is_allowed_url("https://169.254.169.254/metadata") is False

    def test_custom_allowlist(self):
        custom = frozenset({"example.com"})
        assert is_allowed_url("https://example.com/page", custom) is True
        assert is_allowed_url("https://sub.example.com/page", custom) is True
        assert is_allowed_url("https://other.com/page", custom) is False

    def test_all_default_domains_are_lowercase(self):
        for domain in DEFAULT_ALLOWED_DOMAINS:
            assert domain == domain.lower(), f"Domain {domain!r} is not lowercase"

    def test_trailing_dot_hostname(self):
        """Trailing dot in hostname should still match."""
        # urlparse may not strip trailing dots; verify our logic handles it
        assert is_allowed_url("https://docs.python.org./3/") is True


class TestFilterAllowedResults:
    def test_filters_to_allowed_only(self):
        results = [
            {"url": "https://docs.python.org/3/lib.html", "title": "Python", "snippet": "..."},
            {"url": "https://evil.com/hack", "title": "Evil", "snippet": "..."},
            {"url": "https://learn.microsoft.com/page", "title": "MS", "snippet": "..."},
        ]
        filtered = filter_allowed_results(results)
        assert len(filtered) == 2
        assert filtered[0]["url"] == "https://docs.python.org/3/lib.html"
        assert filtered[1]["url"] == "https://learn.microsoft.com/page"

    def test_respects_max_results(self):
        results = [
            {"url": f"https://docs.python.org/{i}", "title": f"P{i}", "snippet": "..."}
            for i in range(10)
        ]
        filtered = filter_allowed_results(results, max_results=2)
        assert len(filtered) == 2

    def test_empty_input(self):
        assert filter_allowed_results([]) == []


class TestFormatWebEvidence:
    def test_formats_evidence_block(self):
        evidence = [
            WebEvidence(
                id="W1",
                kind="web",
                title='Shared "services"',
                url="https://www.starlette.io/applications/",
                snippet="A shared service is...",
                content="A shared service is a common organizational model...",
                domain="www.starlette.io",
                retrieved_at=1000.0,
                search_source="brave",
            )
        ]
        result = format_web_evidence_for_prompt(evidence)
        assert "BEGIN SUPPLEMENTAL WEB EVIDENCE" in result
        assert "END SUPPLEMENTAL WEB EVIDENCE" in result
        assert "non-authoritative" in result
        assert "W1" in result
        assert "www.starlette.io" in result
        assert 'title="Shared \\"services\\""' in result

    def test_empty_evidence(self):
        assert format_web_evidence_for_prompt([]) == ""


@pytest.mark.asyncio
async def test_dns_resolution_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(
        "app.learning_tutor.web_supplement.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )

    assert await _resolves_to_public_host("https://docs.python.org/3/") is False


class TestWebEvidence:
    def test_public_excludes_content(self):
        """Public representation should not leak full page content."""
        ev = WebEvidence(
            id="W1",
            kind="web",
            title="Test",
            url="https://docs.python.org/3/",
            snippet="snippet",
            content="full page content that should not appear in public",
            domain="docs.python.org",
            retrieved_at=1000.0,
            search_source="brave",
        )
        public = ev.public()
        assert "content" not in public
        assert public["kind"] == "web"
        assert public["id"] == "W1"
        assert public["domain"] == "docs.python.org"
        assert "retrieved_at" in public
        assert "search_source" in public
        assert ev.content_hash == ev.content_hash
        assert len(ev.content_hash) == 16


@pytest.mark.asyncio
async def test_search_official_web_graceful_fallback(monkeypatch):
    """When web_search_tool fails, search_official_web returns empty with observability."""
    import app.learning_tutor.web_supplement as ws_mod

    original = ws_mod.web_search_tool

    async def _failing_search(*args, **kwargs):
        raise ConnectionError("no network")

    ws_mod.web_search_tool = _failing_search
    try:
        evidence, obs = await ws_mod.search_official_web("what is a shared service")
        assert evidence == []
        assert obs.get("search_source") == "error"
        assert "web_search_error" in obs
    finally:
        ws_mod.web_search_tool = original


@pytest.mark.asyncio
async def test_search_filters_urls_before_content_extraction(monkeypatch):
    import app.learning_tutor.web_supplement as ws_mod

    extracted: list[dict] = []

    async def _search(*args, **kwargs):
        assert kwargs["enrich_content"] is False
        return {
            "source": "test",
            "total": 2,
            "results": [
                {"url": "https://docs.python.org/3/", "title": "Python", "snippet": "safe"},
                {"url": "http://127.0.0.1/private", "title": "Private", "snippet": "unsafe"},
            ],
        }

    async def _extract(results, query=""):
        extracted.extend(results)
        return [{**item, "content": item["snippet"]} for item in results]

    monkeypatch.setattr(ws_mod, "web_search_tool", _search)
    monkeypatch.setattr(ws_mod, "_safe_extract_content", _extract)

    evidence, _ = await ws_mod.search_official_web("python")

    assert [item["url"] for item in extracted] == ["https://docs.python.org/3/"]
    assert [item.url for item in evidence] == ["https://docs.python.org/3/"]


# ── Tests for build_concept_query ──────────────────────────────────────────


class TestBuildConceptQuery:
    """Concept-aware query construction for targeted official-source search."""

    def test_plain_question_returned_as_is(self):
        """Without concepts, return a cleaned version of the question."""
        q = build_concept_query("What is a class?")
        assert "class" in q.lower()

    def test_search_operators_from_user_input_are_removed(self):
        q = build_concept_query(
            "What is OOP? site:evil.example filetype:html inurl:admin intitle:secrets"
        )

        assert "oop" in q.lower()
        assert "site:" not in q.lower()
        assert "filetype:" not in q.lower()
        assert "inurl:" not in q.lower()
        assert "intitle:" not in q.lower()

    def test_python_oop_concepts_add_python_keyword(self):
        q = build_concept_query(
            "What is OOP?",
            concepts=["object-oriented-programming", "python-architecture"],
        )
        lower = q.lower()
        assert "site:docs.python.org" in lower
        assert "python" in lower
        assert "oop" in lower or "object" in lower

    def test_async_concept_targets_asyncio(self):
        q = build_concept_query(
            "How does async work?",
            concepts=["async-programming"],
        )
        lower = q.lower()
        assert "asyncio" in lower or "async" in lower

    def test_fastapi_dependency_injection_concept(self):
        q = build_concept_query(
            "What is dependency injection?",
            concepts=["fastapi-dependency-injection"],
        )
        lower = q.lower()
        assert "site:fastapi.tiangolo.com" in lower
        assert "fastapi" in lower
        assert "dependency" in lower or "depends" in lower

    def test_opentelemetry_observability_concept(self):
        q = build_concept_query(
            "How do I add observability?",
            concepts=["opentelemetry-observability"],
        )
        lower = q.lower()
        assert "site:opentelemetry.io" in lower
        assert "opentelemetry" in lower

    def test_sse_concept_targets_mdn(self):
        q = build_concept_query(
            "What are server-sent events?",
            concepts=["server-sent-events"],
        )
        lower = q.lower()
        assert "server-sent events" in lower or "sse" in lower

    def test_safe_default_concept(self):
        q = build_concept_query(
            "How do I handle defaults?",
            concepts=["safe-default-patterns"],
        )
        lower = q.lower()
        assert "default" in lower

    def test_unknown_concept_passthrough(self):
        """Unknown concepts should not crash, just be ignored gracefully."""
        q = build_concept_query(
            "Explain quantum computing",
            concepts=["quantum-entanglement-magic"],
        )
        assert len(q) > 0

    def test_empty_question(self):
        q = build_concept_query("")
        assert q == ""

    def test_multiple_concepts_combined(self):
        q = build_concept_query(
            "Explain the factory pattern",
            concepts=["fastapi-dependency-injection", "python-architecture"],
        )
        lower = q.lower()
        assert "factory" in lower or "pattern" in lower
        assert "fastapi" in lower or "python" in lower

    def test_query_max_length_bounded(self):
        """Constructed queries should not be excessively long."""
        q = build_concept_query(
            "A very long question " * 20,
            concepts=[
                "object-oriented-programming",
                "async-programming",
                "fastapi-dependency-injection",
                "opentelemetry-observability",
            ],
        )
        assert len(q) <= 300


# ── Tests for extract_relevant_sentences ───────────────────────────────────


class TestExtractRelevantSentences:
    """Query-relevant sentence extraction from allowlisted fetched pages."""

    def test_extracts_matching_sentences(self):
        text = (
            "Python is a programming language. "
            "It supports object-oriented programming. "
            "The weather is nice today. "
            "Classes define the structure of objects in Python."
        )
        result = extract_relevant_sentences(text, "python classes object-oriented")
        assert "object-oriented" in result
        assert "Classes define" in result or "Python is" in result
        # Irrelevant sentence should be excluded or ranked lower
        assert result.count("weather") == 0 or len(result) < len(text)

    def test_returns_empty_for_no_matches(self):
        text = "The weather is nice. Rain is expected tomorrow."
        result = extract_relevant_sentences(text, "python asyncio")
        # Should still return something (fallback to first sentences)
        # but it should be bounded
        assert len(result) <= len(text)

    def test_respects_max_chars(self):
        text = "Sentence one about Python. " * 100
        result = extract_relevant_sentences(text, "python", max_chars=200)
        assert len(result) <= 200 + 50  # small tolerance for sentence boundaries

    def test_empty_text_returns_empty(self):
        assert extract_relevant_sentences("", "python") == ""

    def test_empty_query_returns_truncated_text(self):
        text = "Some content about things."
        result = extract_relevant_sentences(text, "")
        assert len(result) > 0

    def test_preserves_sentence_boundaries(self):
        """Sentences should not be cut mid-word."""
        text = (
            "asyncio is the standard library for async I/O. "
            "It provides coroutines and event loops. "
            "FastAPI uses asyncio under the hood."
        )
        result = extract_relevant_sentences(text, "asyncio")
        # Should contain complete sentences
        sentences = [s.strip() for s in result.split(".") if s.strip()]
        for s in sentences:
            # Each extracted piece should be a recognizable sentence fragment
            assert len(s) > 3

    def test_case_insensitive_matching(self):
        text = "ASYNCIO provides event loops. The FASTAPI framework is modern."
        result = extract_relevant_sentences(text, "asyncio fastapi")
        assert "ASYNCIO" in result or "FASTAPI" in result

    def test_snippet_fallback_when_no_sentences(self):
        """Short content without clear sentences should still work."""
        text = "asyncio event loop"
        result = extract_relevant_sentences(text, "asyncio")
        assert "asyncio" in result.lower()

    def test_does_not_inject_content(self):
        """Extraction must only select from existing text, never synthesize."""
        text = "Python has classes. Java has interfaces."
        result = extract_relevant_sentences(text, "python classes")
        # Every word in result must come from original text
        for word in result.split():
            clean = word.strip(".,;:!?")
            if clean:
                assert clean in text


# ── Integration: extraction used in search pipeline ────────────────────────


@pytest.mark.asyncio
async def test_search_uses_query_relevant_extraction(monkeypatch):
    """search_official_web should pass query to _safe_extract_content for relevance."""
    import app.learning_tutor.web_supplement as ws_mod

    captured_query = []

    async def _search(*args, **kwargs):
        return {
            "source": "test",
            "total": 1,
            "results": [
                {"url": "https://docs.python.org/3/", "title": "Python", "snippet": "snippet"},
            ],
        }

    async def _extract(results, query=""):
        captured_query.append(query)
        return [{**item, "content": "extracted content"} for item in results]

    monkeypatch.setattr(ws_mod, "web_search_tool", _search)
    monkeypatch.setattr(ws_mod, "_safe_extract_content", _extract)

    await ws_mod.search_official_web("python asyncio tutorial")

    assert len(captured_query) == 1
    assert captured_query[0] == "python asyncio tutorial"


@pytest.mark.asyncio
async def test_observability_includes_extraction_metadata(monkeypatch):
    """Observability dict should include extraction success metrics."""
    import app.learning_tutor.web_supplement as ws_mod

    async def _search(*args, **kwargs):
        return {
            "source": "test",
            "total": 2,
            "results": [
                {"url": "https://docs.python.org/3/a", "title": "A", "snippet": "s1"},
                {"url": "https://docs.python.org/3/b", "title": "B", "snippet": "s2"},
            ],
        }

    async def _extract(results, query=""):
        for r in results:
            r["content"] = "Full extracted content about Python."
        return results

    monkeypatch.setattr(ws_mod, "web_search_tool", _search)
    monkeypatch.setattr(ws_mod, "_safe_extract_content", _extract)

    _, obs = await ws_mod.search_official_web("python")

    assert "extraction_success_count" in obs
    assert obs["extraction_success_count"] >= 1
    assert "web_evidence_count" in obs


# ── Security: no domain leakage in concept queries ─────────────────────────


class TestBuildConceptQuerySecurity:
    """Ensure concept queries don't accidentally allow disallowed domains."""

    def test_no_url_in_query(self):
        """Query should not contain URLs that could be used for SSRF."""
        q = build_concept_query(
            "Explain https://evil.com/hack to me",
            concepts=["python-architecture"],
        )
        assert "evil.com" not in q

    def test_no_script_injection(self):
        q = build_concept_query(
            '<script>alert("xss")</script> What is OOP?',
            concepts=["object-oriented-programming"],
        )
        assert "<script>" not in q
        assert "alert" not in q
