"""Static safety and evidence contracts for local PostgreSQL DR."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / "scripts"


def test_backup_is_private_atomic_and_refuses_overwrite() -> None:
    text = (SCRIPTS / "local-backup.sh").read_text()
    assert "set -Eeuo pipefail" in text
    assert "Refusing to overwrite" in text
    assert "pg_dump" in text and "-Fc --no-owner --no-acl" in text
    assert "mktemp" in text and 'mv "$tmp_dump" "$OUTPUT_DUMP"' in text
    assert 'chmod 600 "$OUTPUT_DUMP"' in text
    assert "sha256" in text.lower()
    assert "created_at_utc" in text
    assert "alembic_revision" in text


def test_restore_verifies_checksum_and_guards_clean_target() -> None:
    text = (SCRIPTS / "local-restore.sh").read_text()
    assert "set -Eeuo pipefail" in text
    assert "Backup SHA256 verification failed" in text
    assert "ALLOW_REPLACE" in text
    assert "pg_catalog.pg_tables" in text
    for option in ("--clean", "--if-exists", "--no-owner", "--no-acl", "--exit-on-error"):
        assert option in text


def test_dr_smoke_covers_required_persisted_categories_without_fixed_secrets() -> None:
    text = (SCRIPTS / "local-dr-smoke.sh").read_text()
    for category in (
        "/api/auth/login",
        "/api/conversations",
        "/api/chat",
        "/api/runs/",
        "/api/documents",
        "approval_requests",
        "vector_chunks",
        "runtime_events",
        "rpo_records",
        "rto_seconds",
        "20260828_14",
    ):
        assert category in text
    assert "secrets.token" in text
    assert "ALLOW_REPLACE=1" not in text
    assert "mktemp -u" not in text
    assert "json_list_length" in text
    assert "docker info --format '{{.Architecture}}'" in text
    assert 'ARCHON_SANDBOX_PLATFORM="linux/arm64"' in text
    assert 'ARCHON_SANDBOX_PLATFORM="linux/amd64"' in text
    assert "127.0.0.1" in text


def test_committed_dr_evidence_is_current_and_secret_free() -> None:
    path = ROOT / "docs" / "evidence" / "local-dr-report.json"
    report = json.loads(path.read_text())
    assert report["result"] == "passed"
    assert report["schema_revision"] == "20260828_14"
    assert report["rpo_records"] == 0
    assert report["rto_seconds"] >= 0
    assert report["restored_counts"] == {
        "approved_terminal_approvals": 1,
        "documents": 1,
        "run_events": 5,
        "vector_chunks": 1,
    }
    encoded = path.read_text().lower()
    assert "password" not in encoded
    assert "access_token" not in encoded
    assert "authorization" not in encoded


def test_scripts_parse_and_are_executable() -> None:
    for name in ("local-backup.sh", "local-restore.sh", "local-dr-smoke.sh"):
        path = SCRIPTS / name
        assert os.access(path, os.X_OK)
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_local_database_is_never_published() -> None:
    compose = (ROOT / "docker-compose.local.yml").read_text()
    postgres_section = compose.split("  postgres:", 1)[1].split("  redis:", 1)[0]
    assert "ports:" not in postgres_section
