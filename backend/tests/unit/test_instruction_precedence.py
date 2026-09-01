from __future__ import annotations

import pytest

from app.instructions.loaders import InstructionFamily, InstructionSource
from app.instructions.resolver import (
    ContextLayer,
    InstructionConflictError,
    ResolvableBlock,
    resolve_effective_context,
)

pytestmark = pytest.mark.unit


def _block(
    layer: ContextLayer, identifier: str, content: str = "x", *, scope: str = "."
) -> ResolvableBlock:
    return ResolvableBlock(layer=layer, identifier=identifier, content=content, scope_path=scope)


def test_precedence_is_structural_and_deterministic() -> None:
    result = resolve_effective_context(
        system=[_block(ContextLayer.SYSTEM, "system")],
        project_instructions=[
            InstructionSource.from_content(
                "leaf", "pkg/.archon/instructions.md", "pkg", InstructionFamily.ARCHON
            ),
            InstructionSource.from_content(
                "root", ".archon/instructions.md", ".", InstructionFamily.ARCHON
            ),
        ],
        pinned_skills=[
            _block(ContextLayer.PINNED_SKILL, "z"),
            _block(ContextLayer.PINNED_SKILL, "a"),
        ],
        selected_skills=[_block(ContextLayer.SELECTED_SKILL, "selected")],
        user_task="do it",
    )
    assert [x.identifier for x in result.blocks] == [
        "system",
        ".archon/instructions.md",
        "pkg/.archon/instructions.md",
        "a",
        "z",
        "selected",
        "user-task",
    ]
    assert all(
        x.content_hash and x.context_cost_bytes == len(x.content.encode()) for x in result.blocks
    )
    assert result.blocks[1].source == "project_instruction"


def test_duplicate_layer_identifier_conflict_is_not_silently_merged() -> None:
    duplicate = [
        _block(ContextLayer.PINNED_SKILL, "same", "one"),
        _block(ContextLayer.PINNED_SKILL, "same", "two"),
    ]
    with pytest.raises(InstructionConflictError, match="duplicate"):
        resolve_effective_context(pinned_skills=duplicate, user_task="task")


def test_context_budget_omits_low_precedence_blocks_but_keeps_system() -> None:
    result = resolve_effective_context(
        system=[_block(ContextLayer.SYSTEM, "system", "1234")],
        selected_skills=[_block(ContextLayer.SELECTED_SKILL, "skill", "5678")],
        user_task="90",
        max_context_bytes=6,
    )
    assert [x.identifier for x in result.blocks] == ["system", "user-task"]
    assert result.omitted == ("skill",)
