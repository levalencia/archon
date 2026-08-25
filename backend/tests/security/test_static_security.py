"""Regression tests for static-analysis security fixes."""

from __future__ import annotations

import stat

import pytest

from app.services.chunker import EmbeddingService
from app.tools.builtin import calculator_tool
from app.tools.image_gen import image_gen_tool
from app.tools.image_storage import IMAGES_DIR, image_path


@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "(1).__class__.__mro__",
        "open('/etc/passwd').read()",
        "[x for x in (1, 2)]",
        "sqrt(x=4)",
        "2 ** 101",
    ],
)
async def test_calculator_rejects_non_whitelisted_expressions(expression: str) -> None:
    result = await calculator_tool(expression)
    assert "error" in result
    assert "result" not in result


@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14.0),
        ("2 ^ 8", 256.0),
        ("sqrt(81) + abs(-3)", 12.0),
        ("round(pi, 2)", 3.14),
    ],
)
async def test_calculator_whitelist_preserves_supported_math(
    expression: str, expected: float
) -> None:
    result = await calculator_tool(expression)
    assert result["result"] == expected


@pytest.mark.security
@pytest.mark.asyncio
async def test_sha256_mock_embedding_is_deterministic() -> None:
    service = EmbeddingService(provider="mock", dimensions=16)
    first = await service.embed("stable input")
    assert first == await service.embed("stable input")
    assert first != await service.embed("different input")


@pytest.mark.security
@pytest.mark.asyncio
async def test_generated_images_use_private_contained_temp_storage() -> None:
    assert stat.S_IMODE(IMAGES_DIR.stat().st_mode) == 0o700
    with pytest.raises(ValueError):
        image_path("../escape.svg")
    with pytest.raises(ValueError):
        image_path("nested/image.svg")

    result = await image_gen_tool("<script>alert(1)</script>", size="32x32")
    generated = image_path(result["url"].rsplit("/", 1)[-1])
    assert generated.parent == IMAGES_DIR.resolve()
    assert "<script>" not in generated.read_text(encoding="utf-8")
