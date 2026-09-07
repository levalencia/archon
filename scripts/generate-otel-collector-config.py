#!/usr/bin/env python3
"""Generate an allowlisted, secret-free OpenTelemetry Collector trace pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

_ALLOWED = frozenset({"debug", "jaeger", "logfire", "azure-monitor", "tempo", "otlp"})
_LOCAL_ENDPOINT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[0-9]{1,5}")


def _required(env: Mapping[str, str], key: str, destination: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ValueError(f"destination {destination!r} requires {key}")
    return value


def _https_base_url(value: str, key: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{key} must be an absolute HTTPS base URL")
    return value.rstrip("/")


def _bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{key} must be true or false")


def parse_destinations(env: Mapping[str, str]) -> tuple[str, ...]:
    if "ARCHON_OTEL_DESTINATIONS" not in env:
        return ("debug",)
    raw = env.get("ARCHON_OTEL_DESTINATIONS", "")
    destinations = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not destinations:
        raise ValueError("at least one OTel destination is required")
    if len(set(destinations)) != len(destinations):
        raise ValueError("duplicate OTel destination")
    if unknown := sorted(set(destinations) - _ALLOWED):
        raise ValueError("unsupported OTel destination: " + ", ".join(unknown))
    return destinations


def generate_config(env: Mapping[str, str]) -> str:
    destinations = parse_destinations(env)
    exporters: dict[str, object] = {}
    pipeline_exporters: list[str] = []

    for destination in destinations:
        if destination == "debug":
            exporters["debug"] = {"verbosity": "basic"}
            pipeline_exporters.append("debug")
        elif destination == "jaeger":
            exporters["otlp/jaeger"] = {
                "endpoint": "jaeger:4317",
                "tls": {"insecure": True},
            }
            pipeline_exporters.append("otlp/jaeger")
        elif destination == "logfire":
            _required(env, "LOGFIRE_TOKEN", destination)
            endpoint = _https_base_url(
                _required(env, "LOGFIRE_BASE_URL", destination), "LOGFIRE_BASE_URL"
            )
            exporters["otlphttp/logfire"] = {
                "endpoint": endpoint,
                "compression": "gzip",
                "headers": {"Authorization": "Bearer ${env:LOGFIRE_TOKEN}"},
            }
            pipeline_exporters.append("otlphttp/logfire")
        elif destination == "azure-monitor":
            _required(env, "APPLICATIONINSIGHTS_CONNECTION_STRING", destination)
            exporters["azuremonitor"] = {
                "connection_string": "${env:APPLICATIONINSIGHTS_CONNECTION_STRING}"
            }
            pipeline_exporters.append("azuremonitor")
        elif destination == "tempo":
            endpoint = _required(env, "TEMPO_OTLP_ENDPOINT", destination)
            insecure = _bool(env.get("TEMPO_OTLP_INSECURE", "false"), "TEMPO_OTLP_INSECURE")
            if insecure and not _LOCAL_ENDPOINT.fullmatch(endpoint):
                raise ValueError("insecure Tempo endpoint must be a container-local host:port")
            exporters["otlp/tempo"] = {
                "endpoint": endpoint,
                "tls": {"insecure": insecure},
            }
            pipeline_exporters.append("otlp/tempo")
        else:
            endpoint = _required(env, "ARCHON_OTEL_GENERIC_ENDPOINT", destination)
            insecure = _bool(
                env.get("ARCHON_OTEL_GENERIC_INSECURE", "false"),
                "ARCHON_OTEL_GENERIC_INSECURE",
            )
            if insecure and not _LOCAL_ENDPOINT.fullmatch(endpoint):
                raise ValueError(
                    "insecure generic OTLP endpoint must be a container-local host:port"
                )
            exporters["otlp/generic"] = {
                "endpoint": endpoint,
                "tls": {"insecure": insecure},
            }
            pipeline_exporters.append("otlp/generic")

    config = {
        "extensions": {"health_check": {"endpoint": "0.0.0.0:13133"}},
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": "0.0.0.0:4317"},
                    "http": {"endpoint": "0.0.0.0:4318"},
                }
            }
        },
        "processors": {"batch": {}},
        "exporters": exporters,
        "service": {
            "extensions": ["health_check"],
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["batch"],
                    "exporters": pipeline_exporters,
                }
            },
        },
    }
    return json.dumps(config, indent=2) + "\n"


def write_config(path: Path, env: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(generate_config(env), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("collector config must be owner-only")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        write_config(args.output, os.environ)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
