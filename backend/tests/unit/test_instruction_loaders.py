from __future__ import annotations

import os
from pathlib import Path

import pytest

import app.instructions.loaders as loaders
from app.instructions.loaders import (
    InstructionFamily,
    InstructionLimits,
    InstructionLoadError,
    load_project_instructions,
)

pytestmark = pytest.mark.unit


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_loads_canonical_root_to_leaf_with_typed_canonical_sources(tmp_path: Path) -> None:
    _write(tmp_path / ".archon/instructions.md", "root")
    _write(tmp_path / "src/.archon/instructions.md", "src")
    _write(tmp_path / "src/api/.archon/instructions.md", "api")

    loaded = load_project_instructions(tmp_path, "src/api/handler.py")

    assert [item.content for item in loaded] == ["root", "src", "api"]
    assert [item.scope_path for item in loaded] == [".", "src", "src/api"]
    assert all(item.family is InstructionFamily.ARCHON for item in loaded)
    assert [item.relative_path for item in loaded] == [
        ".archon/instructions.md",
        "src/.archon/instructions.md",
        "src/api/.archon/instructions.md",
    ]
    assert all(item.path.is_absolute() and item.path == item.path.resolve() for item in loaded)


def test_agents_override_replaces_normal_at_same_level(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "root")
    _write(tmp_path / "pkg/AGENTS.md", "normal")
    _write(tmp_path / "pkg/AGENTS.override.md", "override")

    loaded = load_project_instructions(tmp_path, "pkg/x.py", family="agents")

    assert [item.content for item in loaded] == ["root", "override"]
    assert loaded[-1].is_override is True


def test_configured_family_never_merges_other_ecosystems(tmp_path: Path) -> None:
    _write(tmp_path / ".archon/instructions.md", "archon")
    _write(tmp_path / "AGENTS.md", "agents")
    _write(tmp_path / "CLAUDE.md", "claude")

    assert [x.content for x in load_project_instructions(tmp_path, ".")] == ["archon"]
    assert [x.content for x in load_project_instructions(tmp_path, ".", family="agents")] == [
        "agents"
    ]
    assert [x.content for x in load_project_instructions(tmp_path, ".", family="claude")] == [
        "claude"
    ]


def test_imports_are_bounded_ordered_and_cycles_rejected(tmp_path: Path) -> None:
    _write(tmp_path / ".archon/instructions.md", "before\n@include ../shared/base.md\nafter")
    _write(tmp_path / "shared/base.md", "base\n@include detail.md")
    _write(tmp_path / "shared/detail.md", "detail")

    loaded = load_project_instructions(tmp_path, ".")
    assert [x.content for x in loaded] == ["before\nafter", "base", "detail"]
    assert [x.relative_path for x in loaded] == [
        ".archon/instructions.md",
        "shared/base.md",
        "shared/detail.md",
    ]

    _write(tmp_path / "shared/detail.md", "@include base.md")
    with pytest.raises(InstructionLoadError, match="cycle"):
        load_project_instructions(tmp_path, ".")


def test_rejects_target_and_import_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(InstructionLoadError, match="escapes workspace"):
        load_project_instructions(tmp_path, "../outside.md")

    _write(tmp_path / ".archon/instructions.md", "@include ../../outside.md")
    with pytest.raises(InstructionLoadError, match="escapes workspace"):
        load_project_instructions(tmp_path, ".")


def test_rejects_symlink_escape_and_limits(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-instructions.md"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / ".archon").mkdir()
    (tmp_path / ".archon/instructions.md").symlink_to(outside)
    with pytest.raises(InstructionLoadError, match="symlink|escapes"):
        load_project_instructions(tmp_path, ".")

    (tmp_path / ".archon/instructions.md").unlink()
    _write(tmp_path / ".archon/instructions.md", "12345")
    with pytest.raises(InstructionLoadError, match="bytes"):
        load_project_instructions(tmp_path, ".", limits=InstructionLimits(max_file_bytes=4))


def test_enforces_file_depth_total_bytes_and_directory_depth(tmp_path: Path) -> None:
    _write(tmp_path / ".archon/instructions.md", "@include a.md")
    _write(tmp_path / ".archon/a.md", "@include b.md")
    _write(tmp_path / ".archon/b.md", "b")
    with pytest.raises(InstructionLoadError, match="import depth"):
        load_project_instructions(tmp_path, ".", limits=InstructionLimits(max_import_depth=1))
    with pytest.raises(InstructionLoadError, match="file count"):
        load_project_instructions(tmp_path, ".", limits=InstructionLimits(max_files=2))
    with pytest.raises(InstructionLoadError, match="total bytes"):
        load_project_instructions(tmp_path, ".", limits=InstructionLimits(max_total_bytes=10))
    with pytest.raises(InstructionLoadError, match="directory depth"):
        load_project_instructions(
            tmp_path, "a/b/c/d.py", limits=InstructionLimits(max_directory_depth=2)
        )


def test_rejects_hardlinked_instruction_source(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    _write(source, "shared inode")
    target = tmp_path / ".archon/instructions.md"
    target.parent.mkdir()
    os.link(source, target)

    with pytest.raises(InstructionLoadError, match="hardlinks"):
        load_project_instructions(tmp_path, ".")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    target = tmp_path / ".archon/instructions.md"
    target.parent.mkdir()
    os.mkfifo(target)

    with pytest.raises(InstructionLoadError, match="regular file"):
        load_project_instructions(tmp_path, ".")


def test_fails_closed_without_descriptor_relative_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / ".archon/instructions.md", "safe")
    monkeypatch.setattr(loaders, "_SECURE_TRAVERSAL_AVAILABLE", False)

    with pytest.raises(InstructionLoadError, match="secure workspace traversal"):
        load_project_instructions(tmp_path, ".")
