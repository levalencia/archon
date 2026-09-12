from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEGACY_BRAND = "arc" + "hon"


def _workspace_files() -> list[Path]:
    raw = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [ROOT / item.decode() for item in raw.split(b"\0") if item]


def test_tracked_and_candidate_files_use_only_cogentrex_identity() -> None:
    legacy_paths: list[str] = []
    legacy_content: list[str] = []
    for path in _workspace_files():
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if LEGACY_BRAND in relative.lower():
            legacy_paths.append(relative)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        if LEGACY_BRAND in text.lower():
            legacy_content.append(relative)

    assert legacy_paths == []
    assert legacy_content == []


def test_cogentrex_brand_assets_are_valid_svg() -> None:
    assets = ROOT / "frontend" / "static" / "brand"
    expected = {
        "cogentrex-icon.svg",
        "cogentrex-logo-dark.svg",
        "cogentrex-logo-light.svg",
        "cogentrex-mark-dark.svg",
        "cogentrex-mark-light.svg",
    }
    assert {path.name for path in assets.glob("*.svg")} == expected
    for name in expected:
        root = ET.parse(assets / name).getroot()
        assert root.tag.endswith("svg")
        assert root.find("{http://www.w3.org/2000/svg}title") is not None
        assert root.find("{http://www.w3.org/2000/svg}desc") is not None
