#!/usr/bin/env python3
"""Generate Archon's protected local Compose environment.

The default is deterministic mock mode. An optional provider env contributes only
an explicit LLM allowlist and is never evaluated as shell code.
"""

from __future__ import annotations

import argparse
import base64
import json
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
TELEMETRY_PROVIDER_KEYS = frozenset(
    {
        "ARCHON_OTEL_DESTINATIONS",
        "ARCHON_OTEL_CAPTURE_MESSAGE_CONTENT",
        "LOGFIRE_TOKEN",
        "LOGFIRE_BASE_URL",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "TEMPO_OTLP_ENDPOINT",
        "TEMPO_OTLP_INSECURE",
        "ARCHON_OTEL_GENERIC_ENDPOINT",
        "ARCHON_OTEL_GENERIC_INSECURE",
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
            "LOGFIRE_TOKEN",
            "LOGFIRE_BASE_URL",
        }
    )
    | EMBEDDING_PROVIDER_KEYS
    | TELEMETRY_PROVIDER_KEYS
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
OTEL_DESTINATIONS = frozenset(
    {"debug", "jaeger", "logfire", "azure-monitor", "tempo", "otlp"}
)
LEARNING_MEDIA_MARKER = "archon.learning-library/v1\n"


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

    raw_destinations = values.get("ARCHON_OTEL_DESTINATIONS")
    if raw_destinations is None:
        raw_destinations = "logfire" if values.get("LOGFIRE_TOKEN") else "debug"
        values["ARCHON_OTEL_DESTINATIONS"] = raw_destinations
    destinations = tuple(
        part.strip().lower() for part in raw_destinations.split(",") if part.strip()
    )
    if not destinations or len(set(destinations)) != len(destinations):
        raise ValueError("invalid OTel destination selection")
    if unknown := sorted(set(destinations) - OTEL_DESTINATIONS):
        raise ValueError("unsupported OTel destination: " + ", ".join(unknown))
    required_by_destination = {
        "logfire": ("LOGFIRE_TOKEN", "LOGFIRE_BASE_URL"),
        "azure-monitor": ("APPLICATIONINSIGHTS_CONNECTION_STRING",),
        "tempo": ("TEMPO_OTLP_ENDPOINT",),
        "otlp": ("ARCHON_OTEL_GENERIC_ENDPOINT",),
    }
    for destination in destinations:
        missing_destination_keys = [
            key for key in required_by_destination.get(destination, ()) if not values.get(key)
        ]
        if missing_destination_keys:
            raise ValueError(
                f"OTel destination {destination!r} is missing required keys: "
                + ", ".join(missing_destination_keys)
            )
    capture = values.get("ARCHON_OTEL_CAPTURE_MESSAGE_CONTENT", "false").lower()
    if capture not in {"true", "false"}:
        raise ValueError("ARCHON_OTEL_CAPTURE_MESSAGE_CONTENT must be true or false")
    values["ARCHON_OTEL_CAPTURE_MESSAGE_CONTENT"] = capture
    return values


def validate_learning_media_root(path: Path | None) -> Path | None:
    """Return a valid media root, or ``None`` when no library is installed."""
    if path is None:
        return None
    candidate = path.expanduser()
    if not candidate.exists():
        return None
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("learning-media root must be a real directory")
    if not any(candidate.iterdir()):
        return None

    marker = candidate / ".archon-learning-library"
    catalog = candidate / "catalog.json"
    published = candidate / "published"
    if (
        not marker.is_file()
        or marker.is_symlink()
        or marker.read_text(encoding="utf-8") != LEARNING_MEDIA_MARKER
        or not catalog.is_file()
        or catalog.is_symlink()
        or not published.is_dir()
        or published.is_symlink()
    ):
        raise ValueError("learning-media library is incomplete or invalid")
    try:
        payload = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("learning-media catalog is invalid") from exc
    if (
        payload.get("schema") != "archon.learning-library"
        or payload.get("version") != 1
        or not isinstance(payload.get("packs"), list)
        or not payload["packs"]
        or not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_commit", "")))
    ):
        raise ValueError("learning-media catalog is invalid")
    return candidate.resolve()


def generate_values(
    provider_env: Path | None = None,
    learning_media_root: Path | None = None,
) -> dict[str, str]:
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
        "ARCHON_AGENT_DEADLINE_SECONDS": "300",
        "ARCHON_VERIFIER_ENABLED": "false",
        "ARCHON_OTEL_DESTINATIONS": "debug",
        "ARCHON_OTEL_CAPTURE_MESSAGE_CONTENT": "false",
        "ARCHON_LEARNING_MEDIA_ENABLED": "false",
        "COMPOSE_PROFILES": "",
        "ARCHON_JAEGER_PORT": os.environ.get("ARCHON_JAEGER_PORT") or "16686",
        "ARCHON_LOCAL_PORT": os.environ.get("ARCHON_LOCAL_PORT")
        or str(18_000 + secrets.randbelow(20_000)),
        "ARCHON_RUNTIME_MODE": "mock",
        "ARCHON_LLM_PROVIDER": "mock",
        "ARCHON_LLM_MODEL": "mock-model",
    }
    if provider_env is not None:
        values.update(read_provider_env(provider_env))
        values["ARCHON_RUNTIME_MODE"] = "live-foundry"
        values["ARCHON_VERIFIER_ENABLED"] = "true"
        values["ARCHON_VERIFIER_MODEL"] = values["ARCHON_LLM_MODEL"]
    if media_root := validate_learning_media_root(learning_media_root):
        values["ARCHON_LEARNING_MEDIA_ENABLED"] = "true"
        values["ARCHON_LEARNING_MEDIA_HOST_DIR"] = str(media_root)
    if "jaeger" in values["ARCHON_OTEL_DESTINATIONS"].split(","):
        values["COMPOSE_PROFILES"] = "jaeger"
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
    parser.add_argument("--learning-media-root", type=Path)
    args = parser.parse_args()
    try:
        write_env(
            args.output,
            generate_values(args.provider_env, args.learning_media_root),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
