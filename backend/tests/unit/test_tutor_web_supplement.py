"""Tests for bounded official-source web supplementation."""

from __future__ import annotations

import pytest

from app.learning_tutor.web_supplement import (
    DEFAULT_ALLOWED_DOMAINS,
    WebEvidence,
    _resolves_to_public_host,
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

    async def _extract(results):
        extracted.extend(results)
        return [{**item, "content": item["snippet"]} for item in results]

    monkeypatch.setattr(ws_mod, "web_search_tool", _search)
    monkeypatch.setattr(ws_mod, "_safe_extract_content", _extract)

    evidence, _ = await ws_mod.search_official_web("python")

    assert [item["url"] for item in extracted] == ["https://docs.python.org/3/"]
    assert [item.url for item in evidence] == ["https://docs.python.org/3/"]
