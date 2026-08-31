#!/usr/bin/env python3
"""Generate Archon's protected local Compose environment.

The default is deterministic mock mode. An optional provider env contributes only
an explicit LLM allowlist and is never evaluated as shell code.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import urlparse

EMBEDDING_PROVIDER_KEYS = frozenset(
    {
        "ARCHON_EMBEDDING_PROVIDER",
        "ARCHON_EMBEDDING_MODEL",
        "ARCHON_EMBEDDING_API_KEY",
        "ARCHON_EMBEDDING_BASE_URL",
        "ARCHON_EMBEDDING_ALLOWED_HOSTS",
        "ARCHON_EMBEDDING_DIMENSIONS",
        "ARCHON_EMBEDDING_API_VERSION",
    }
)
ALLOWED_PROVIDER_KEYS = (
    frozenset(
        {
            "ARCHON_LLM_PROVIDER",
            "ARCHON_LLM_MODEL",
            "ARCHON_LLM_API_KEY",
            "ARCHON_LLM_BASE_URL",
            "ARCHON_PROMPT_CACHING_ENABLED",
        }
    )
    | EMBEDDING_PROVIDER_KEYS
)
REQUIRED_PROVIDER_KEYS = frozenset(
    {
        "ARCHON_LLM_PROVIDER",
        "ARCHON_LLM_MODEL",
        "ARCHON_LLM_API_KEY",
        "ARCHON_LLM_BASE_URL",
    }
)
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_provider_env(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve(strict=True)
    if path.expanduser().is_symlink():
        raise ValueError("provider env must not be a symbolic link")
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("provider env must be a regular file")
    if metadata.st_uid != os.getuid():
        raise ValueError("provider env must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("provider env must not be group/world accessible")

    values: dict[str, str] = {}
    for raw in resolved.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_PROVIDER_KEYS:
            continue
        value = _unquote(value)
        if "\n" in value or "\r" in value:
            raise ValueError(f"invalid newline in {key}")
        values[key] = value

    missing = sorted(key for key in REQUIRED_PROVIDER_KEYS if not values.get(key))
    if missing:
        raise ValueError("provider env is missing required keys: " + ", ".join(missing))
    if values["ARCHON_LLM_PROVIDER"].lower() != "foundry":
        raise ValueError(
            "managed live mode currently requires ARCHON_LLM_PROVIDER=foundry"
        )
    if not MODEL_PATTERN.fullmatch(values["ARCHON_LLM_MODEL"]):
        raise ValueError("invalid managed live model name")
    endpoint = urlparse(values["ARCHON_LLM_BASE_URL"])
    if endpoint.scheme != "https" or not endpoint.hostname:
        raise ValueError("managed Foundry endpoint must be an absolute HTTPS URL")

    supplied_embeddings = {key for key in EMBEDDING_PROVIDER_KEYS if values.get(key)}
    if supplied_embeddings:
        required_embeddings = {
            "ARCHON_EMBEDDING_PROVIDER",
            "ARCHON_EMBEDDING_MODEL",
            "ARCHON_EMBEDDING_BASE_URL",
            "ARCHON_EMBEDDING_ALLOWED_HOSTS",
            "ARCHON_EMBEDDING_DIMENSIONS",
            "ARCHON_EMBEDDING_API_VERSION",
        }
        if missing_embeddings := sorted(
            key for key in required_embeddings if not values.get(key)
        ):
            raise ValueError(
                "embedding configuration is incomplete: "
                + ", ".join(missing_embeddings)
            )
        if values["ARCHON_EMBEDDING_PROVIDER"].lower() != "foundry":
            raise ValueError("managed embeddings currently require provider=foundry")
        if not MODEL_PATTERN.fullmatch(values["ARCHON_EMBEDDING_MODEL"]):
            raise ValueError("invalid managed embedding model name")
        embedding_endpoint = urlparse(values["ARCHON_EMBEDDING_BASE_URL"])
        if (
            embedding_endpoint.scheme != "https"
            or not embedding_endpoint.hostname
            or embedding_endpoint.username
            or embedding_endpoint.password
            or embedding_endpoint.query
            or embedding_endpoint.fragment
        ):
            raise ValueError("managed embedding endpoint must be an absolute HTTPS URL")
        allowed_hosts = {
            host.strip().lower()
            for host in values["ARCHON_EMBEDDING_ALLOWED_HOSTS"].split(",")
            if host.strip()
        }
        if embedding_endpoint.hostname.lower() not in allowed_hosts:
            raise ValueError(
                "managed embedding endpoint host must be explicitly allowed"
            )
        try:
            dimensions = int(values["ARCHON_EMBEDDING_DIMENSIONS"])
        except ValueError:
            raise ValueError("embedding dimensions must be an integer") from None
        if not 1 <= dimensions <= 4096:
            raise ValueError("embedding dimensions must be between 1 and 4096")
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-preview)?",
            values["ARCHON_EMBEDDING_API_VERSION"],
        ):
            raise ValueError("invalid embedding API version")
        values.setdefault("ARCHON_EMBEDDING_API_KEY", values["ARCHON_LLM_API_KEY"])
    return values


def generate_values(provider_env: Path | None = None) -> dict[str, str]:
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "ARCHON_SECRET_KEY": secrets.token_urlsafe(48),
        "ARCHON_ENCRYPTION_MASTER_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        )
        .decode()
        .rstrip("="),
        "ARCHON_EFFECT_IDENTITY_SECRET": secrets.token_urlsafe(48),
        "ARCHON_DELEGATION_SIGNING_KEY": secrets.token_urlsafe(48),
        "ARCHON_DURABLE_MONETARY_BUDGET_ENABLED": "true",
        "ARCHON_DURABLE_EFFECT_LEDGER_ENABLED": "true",
        "ARCHON_AGENT_DEADLINE_SECONDS": "90",
        "ARCHON_VERIFIER_ENABLED": "false",
        "ARCHON_LOCAL_PORT": str(18_000 + secrets.randbelow(20_000)),
        "ARCHON_RUNTIME_MODE": "mock",
        "ARCHON_LLM_PROVIDER": "mock",
        "ARCHON_LLM_MODEL": "mock-model",
    }
    if provider_env is not None:
        values.update(read_provider_env(provider_env))
        values["ARCHON_RUNTIME_MODE"] = "live-foundry"
        values["ARCHON_VERIFIER_ENABLED"] = "true"
        values["ARCHON_VERIFIER_MODEL"] = values["ARCHON_LLM_MODEL"]
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("output env must be a regular file owned by the current user")
    os.chmod(path, 0o600)
    with path.open("w", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--provider-env", type=Path)
    args = parser.parse_args()
    try:
        write_env(args.output, generate_values(args.provider_env))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
