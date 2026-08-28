"""Shared safety and reporting primitives for opt-in provider acceptance scripts."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import re
import secrets as secrets_module
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPORT_SCHEMA = "archon.provider-acceptance"
REPORT_VERSION = 1
MAX_REPORT_BYTES = 65536
_STATUSES = frozenset({"pass", "fail", "skipped"})
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|authorization|bearer|token|secret|password)\b\s*[:=]\s*[^,}\s]+"
    ),
    re.compile(r"\b(?:sk|key|token)-[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}\b", re.I),
    re.compile(r"https?://[^\s\"']+", re.I),
    re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{0,31}=[^\s,}&]+"),
)
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_PREFLIGHT_FIELDS = {
    "model": frozenset(
        {
            "execute_live",
            "execution_mode",
            "provider",
            "model",
            "base_host",
            "credential_present",
            "fallback_configured",
        }
    ),
    "multimodal": frozenset(
        {
            "execute_live",
            "execution_mode",
            "provider",
            "model",
            "base_host",
            "credential_present",
            "fallback_configured",
        }
    ),
    "embedding": frozenset(
        {
            "execute_live",
            "execution_mode",
            "provider",
            "model",
            "base_host",
            "credential_present",
            "dimensions",
        }
    ),
}
_REQUIRED_RESULTS = {
    "model": frozenset({"structured_output", "native_tool_call", "cache_metrics"}),
    "multimodal": frozenset({"image_input"}),
    "embedding": frozenset({"embedding", "ingest_query"}),
}
_OPTIONAL_RESULTS = {
    "model": frozenset({"provider_cleanup"}),
    "multimodal": frozenset({"provider_cleanup"}),
    "embedding": frozenset({"embedding_cleanup"}),
}
_PASS_METRICS = {
    "structured_output": {"schema_valid": bool},
    "native_tool_call": {"tool_calls": int},
    "cache_metrics": {"read_tokens": int, "write_tokens": int},
    "image_input": {"images": int, "width": int, "height": int},
    "embedding": {
        "dimensions": int,
        "finite": bool,
        "nonzero": bool,
        "norm_positive": bool,
    },
    "ingest_query": {
        "chunks_ingested": int,
        "chunks_retrieved": int,
        "query_nonzero": bool,
        "query_similarity_positive": bool,
        "retrieved_score_positive": bool,
        "dimensions": int,
    },
}


class AcceptanceError(ValueError):
    def __init__(self, code: str) -> None:
        if not re.fullmatch(r"[a-z0-9_]{1,64}", code):
            raise ValueError("invalid acceptance error code")
        super().__init__(code)
        self.code = code


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalized_identity(value: object) -> str:
    if isinstance(value, str) and _IDENTITY.fullmatch(value):
        return value.lower()
    return "unknown"


def normalized_host(base_url: str, provider: str) -> str:
    default = {
        "openai": "api.openai.com",
        "anthropic": "api.anthropic.com",
        "ollama": "localhost",
    }.get(provider, "not-configured")
    if not base_url:
        return default
    try:
        host = urlsplit(base_url).hostname
    except ValueError:
        return "invalid"
    if not host or len(host) > 253:
        return "invalid"
    return host.rstrip(".").lower()


def result(
    name: str,
    status: str,
    *,
    metrics: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_category: str | None = None,
) -> dict[str, Any]:
    if status not in _STATUSES:
        raise ValueError("invalid result status")
    item: dict[str, Any] = {"name": name, "status": status}
    if metrics:
        item["metrics"] = metrics
    if error_code is not None:
        item["error"] = {"category": error_category or "internal", "code": error_code[:64]}
    return item


def error_result(name: str, exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, TimeoutError):
        return result(name, "fail", error_code="timeout", error_category="timeout")
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
        code = "provider_failure"
    category = (
        "invalid_response"
        if code.startswith("invalid_") or code in {"malformed_json", "schema_mismatch"}
        else "provider"
    )
    return result(name, "fail", error_code=code, error_category=category)


def _overall_status(statuses: list[str]) -> str:
    return (
        "fail"
        if "fail" in statuses
        else ("pass" if statuses and all(status == "pass" for status in statuses) else "skipped")
    )


def make_report(
    *,
    kind: str,
    started_at: str,
    finished_at: str,
    preflight: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    statuses = [item["status"] for item in results]
    overall = _overall_status(statuses)
    report = {
        "schema": REPORT_SCHEMA,
        "version": REPORT_VERSION,
        "kind": kind,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": overall,
        "preflight": preflight,
        "results": results,
    }
    validate_report(report)
    return report


def _validate_preflight(kind: str, preflight: object) -> None:
    if type(preflight) is not dict or set(preflight) != _PREFLIGHT_FIELDS[kind]:
        raise ValueError("invalid report preflight")
    mode = preflight.get("execution_mode")
    execute_live = preflight.get("execute_live")
    if type(execute_live) is not bool or mode not in {
        "dry_run",
        "deterministic",
        "live",
        "configuration_error",
    }:
        raise ValueError("invalid report preflight")
    if (mode == "dry_run" and execute_live) or (
        mode in {"deterministic", "live"} and not execute_live
    ):
        raise ValueError("invalid report preflight")
    for field in ("provider", "model"):
        if type(preflight.get(field)) is not str or not _IDENTITY.fullmatch(preflight[field]):
            raise ValueError("invalid report preflight")
    host = preflight.get("base_host")
    if type(host) is not str or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise ValueError("invalid report preflight")
    if type(preflight.get("credential_present")) is not bool:
        raise ValueError("invalid report preflight")
    if kind == "embedding":
        dimensions = preflight.get("dimensions")
        if type(dimensions) is not int or not 1 <= dimensions <= 4096:
            raise ValueError("invalid report preflight")
    elif type(preflight.get("fallback_configured")) is not bool:
        raise ValueError("invalid report preflight")


def _validate_metrics(name: str, status: str, item: dict[str, Any]) -> None:
    metrics = item.get("metrics")
    error = item.get("error")
    if status == "pass":
        expected = _PASS_METRICS.get(name)
        if expected is None or type(metrics) is not dict or set(metrics) != set(expected) or error:
            raise ValueError("invalid report result")
        for field, expected_type in expected.items():
            value = metrics[field]
            if type(value) is not expected_type:
                raise ValueError("invalid report result")
            if expected_type is bool and value is not True:
                raise ValueError("invalid report result")
            if expected_type is int and (
                value < 0 or (field not in {"read_tokens", "write_tokens"} and value == 0)
            ):
                raise ValueError("invalid report result")
    elif metrics is not None or error is None:
        raise ValueError("invalid report result")


def _reject_disclosure_strings(value: object) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _reject_disclosure_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_disclosure_strings(nested)
    elif isinstance(value, str) and (
        "://" in value or "?" in value or re.search(r"\b[A-Za-z][A-Za-z0-9_-]{0,31}=\S+", value)
    ):
        raise ValueError("report contains URL or query material")


def validate_report(report: dict[str, Any]) -> None:
    required = {
        "schema",
        "version",
        "kind",
        "started_at",
        "finished_at",
        "status",
        "preflight",
        "results",
    }
    if (
        set(report) != required
        or report["schema"] != REPORT_SCHEMA
        or report["version"] != REPORT_VERSION
    ):
        raise ValueError("invalid report schema")
    kind = report.get("kind")
    if kind not in _PREFLIGHT_FIELDS:
        raise ValueError("invalid report kind")
    _validate_preflight(kind, report["preflight"])
    for timestamp_name in ("started_at", "finished_at"):
        timestamp = report[timestamp_name]
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError("invalid report timestamp")
        try:
            datetime.fromisoformat(timestamp.removesuffix("Z") + "+00:00")
        except ValueError:
            raise ValueError("invalid report timestamp") from None
    if report["status"] not in _STATUSES or not isinstance(report["results"], list):
        raise ValueError("invalid report status")
    names = [item.get("name") for item in report["results"] if isinstance(item, dict)]
    if (
        len(names) != len(report["results"])
        or len(names) != len(set(names))
        or not _REQUIRED_RESULTS[kind] <= set(names)
        or set(names) - _REQUIRED_RESULTS[kind] - _OPTIONAL_RESULTS[kind]
    ):
        raise ValueError("invalid report result names")
    for item in report["results"]:
        if (
            not isinstance(item, dict)
            or not {"name", "status"} <= set(item)
            or not isinstance(item["name"], str)
            or not item["name"]
            or set(item) - {"name", "status", "metrics", "error"}
            or item.get("status") not in _STATUSES
        ):
            raise ValueError("invalid report result")
        if "error" in item:
            error = item["error"]
            if (
                not isinstance(error, dict)
                or set(error) != {"category", "code"}
                or not all(
                    isinstance(error[field], str) and re.fullmatch(r"[a-z0-9_]{1,64}", error[field])
                    for field in ("category", "code")
                )
            ):
                raise ValueError("invalid report error")
        _validate_metrics(item["name"], item["status"], item)
    statuses = [item["status"] for item in report["results"]]
    if report["status"] != _overall_status(statuses):
        raise ValueError("invalid report status")
    _reject_disclosure_strings(report)


def scan_report(encoded: str, *, secrets: tuple[str, ...] = ()) -> None:
    """Reject credentials, URLs, query strings, and any known in-memory credential."""
    for secret in secrets:
        if secret and len(secret) >= 4 and secret in encoded:
            raise ValueError("report contains credential material")
    if any(pattern.search(encoded) for pattern in _SECRET_PATTERNS):
        raise ValueError("report failed secret scan")


def _secure_parent(path: str | Path) -> tuple[int, str]:
    lexical_root = Path(os.path.abspath(tempfile.gettempdir()))
    root = lexical_root.resolve()
    target = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    relative: Path | None = None
    for candidate_root in (lexical_root, root):
        try:
            relative = target.relative_to(candidate_root)
            break
        except ValueError:
            continue
    if relative is None:
        raise ValueError("report path must be under the system temporary directory")
    if not relative.parts or relative.name in {"", ".", ".."}:
        raise ValueError("report path must name a file")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for component in relative.parts[:-1]:
            if component in {"", ".", ".."}:
                raise ValueError("invalid report parent")
            nested = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = nested
        return descriptor, relative.name
    except OSError:
        os.close(descriptor)
        raise ValueError("invalid report parent") from None
    except BaseException:
        os.close(descriptor)
        raise


def write_report(
    path: str | Path, report: dict[str, Any], *, secrets: tuple[str, ...] = ()
) -> None:
    """Atomically write through a securely opened temp-directory descriptor."""
    validate_report(report)
    encoded = (
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    )
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds size limit")
    scan_report(encoded, secrets=secrets)
    parent_fd, name = _secure_parent(path)
    temporary = f".{name}.{secrets_module.token_hex(12)}"
    descriptor: int | None = None
    try:
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise ValueError("report target must be a regular file, not a symlink")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)
        raise
    finally:
        os.close(parent_fd)


def read_report(path: str | Path) -> dict[str, Any]:
    parent_fd, name = _secure_parent(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("report artifact must be a regular file")
        payload = os.read(descriptor, MAX_REPORT_BYTES + 1)
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError("report exceeds size limit")
        report = json.loads(payload.decode("utf-8"))
        if type(report) is not dict:
            raise ValueError("invalid report schema")
        validate_report(report)
        scan_report(payload.decode("utf-8"))
        return report
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid report artifact") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def remove_report(path: str | Path) -> None:
    parent_fd, name = _secure_parent(path)
    try:
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(existing.st_mode):
            raise ValueError("report target must be a regular file, not a symlink")
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def failure_report(kind: str, *, execute_live: bool, code: str) -> dict[str, Any]:
    if kind in {"model", "multimodal"}:
        preflight: dict[str, Any] = {
            "execute_live": execute_live,
            "execution_mode": "live" if execute_live else "dry_run",
            "provider": "unknown",
            "model": "unknown",
            "base_host": "invalid",
            "credential_present": False,
            "fallback_configured": False,
        }
    else:
        preflight = {
            "execute_live": execute_live,
            "execution_mode": "live" if execute_live else "dry_run",
            "provider": "unknown",
            "model": "unknown",
            "base_host": "invalid",
            "credential_present": False,
            "dimensions": 1,
        }
    return make_report(
        kind=kind,
        started_at=utc_now(),
        finished_at=utc_now(),
        preflight=preflight,
        results=[
            result(name, "fail", error_code=code, error_category="process")
            for name in sorted(_REQUIRED_RESULTS[kind])
        ],
    )


def run_cli_worker(
    script: str | Path,
    worker_arguments: list[str],
    *,
    output: str | Path,
    kind: str,
    execute_live: bool,
    operation_timeout: float,
    operation_count: int,
    hard_timeout: float | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run all provider code in a killable child with a hard wall-clock bound."""
    remove_report(output)
    wall_timeout = (
        hard_timeout
        if hard_timeout is not None
        else min(300.0, max(5.0, operation_timeout * operation_count + 10.0))
    )
    if not 0.05 <= wall_timeout <= 300.0:
        raise ValueError("invalid hard timeout")
    process = subprocess.Popen(
        [sys.executable, os.fspath(script), "--worker", *worker_arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        process.wait(timeout=wall_timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        report = failure_report(kind, execute_live=execute_live, code="hard_timeout")
        write_report(output, report)
        return 1, report
    try:
        report = read_report(output)
    except ValueError:
        report = failure_report(kind, execute_live=execute_live, code="worker_report_invalid")
        write_report(output, report)
        return 1, report
    return (1 if report["status"] == "fail" else 0), report


async def bounded_close(resource: object, timeout: float) -> BaseException | None:
    """Close an injected or real provider without letting cleanup hang the script."""
    closer = getattr(resource, "close", None) or getattr(
        getattr(resource, "_client", None), "aclose", None
    )
    if closer is None:
        return None
    try:
        value = closer()
        if inspect.isawaitable(value):
            await asyncio.wait_for(value, timeout=max(0.1, min(timeout, 5.0)))
    except BaseException as exc:
        return exc
    return None


def clock_pair(clock: Callable[[], str] = utc_now) -> tuple[str, Callable[[], str]]:
    return clock(), clock
