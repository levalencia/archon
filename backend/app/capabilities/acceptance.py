"""Parse and validate the executable capability acceptance baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DimensionValue = Literal["yes", "partial", "no", "na"]
CapabilityStatus = Literal["implemented", "partial", "not-implemented", "deferred"]

REQUIRED_CAPABILITY_IDS = {
    "generic-self-reflection",
    "run-export-share",
    "learning-optimization-drift",
    "provider-capability-parity",
    "validated-structured-output",
    "prompt-cache-accounting",
    "effect-idempotency",
    "context-provenance",
    "online-key-rotation",
    "durable-monetary-budgets",
    "multimodal-e2e",
    "durable-background-jobs",
    "mandatory-compliance",
    "signed-agent-communication",
    "isolated-sandbox-live-target",
    "live-embedding-provider",
}


class AcceptanceDimensions(BaseModel):
    """Independent evidence dimensions; absent and unknown are never truthy."""

    model_config = ConfigDict(extra="forbid")

    exists: DimensionValue
    wired: DimensionValue
    tested: DimensionValue
    observed: DimensionValue
    ui: DimensionValue
    live_provider: DimensionValue
    deployed: DimensionValue


class CapabilityAcceptance(BaseModel):
    """One stable capability claim and its evidence pointers."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    owner_module: str = Field(min_length=1)
    status: CapabilityStatus
    dimensions: AcceptanceDimensions
    sources: list[str]
    tests: list[str]
    evidence: list[str]
    limitation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_claim(self) -> CapabilityAcceptance:
        if not self.limitation.strip():
            raise ValueError("limitation must not be blank")
        if self.status == "implemented" and not all((self.sources, self.tests, self.evidence)):
            raise ValueError("implemented capabilities require sources, tests, and evidence")
        for field_name in ("sources", "tests", "evidence"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain only non-blank paths")
        return self


class CapabilityAcceptanceManifest(BaseModel):
    """Versioned collection of capability acceptance claims."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    capabilities: list[CapabilityAcceptance] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> CapabilityAcceptanceManifest:
        seen: set[str] = set()
        for capability in self.capabilities:
            if capability.id in seen:
                raise ValueError(f"duplicate capability id: {capability.id}")
            seen.add(capability.id)
        return self


def load_capability_acceptance(
    path: Path, *, require_baseline: bool = False
) -> CapabilityAcceptanceManifest:
    """Load JSON-compatible YAML and validate its schema and baseline IDs."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: manifest must use JSON-compatible YAML: {exc}") from exc
    manifest = CapabilityAcceptanceManifest.model_validate(raw)
    if require_baseline:
        actual = {capability.id for capability in manifest.capabilities}
        missing = REQUIRED_CAPABILITY_IDS - actual
        unexpected = actual - REQUIRED_CAPABILITY_IDS
        if missing or unexpected:
            raise ValueError(
                f"baseline capability IDs differ: missing={sorted(missing)}, "
                f"unexpected={sorted(unexpected)}"
            )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = load_capability_acceptance(args.manifest, require_baseline=True)
    print(f"Validated {len(manifest.capabilities)} capability acceptance entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
