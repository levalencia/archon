"""Persistence-boundary PII probes."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.memory.scoped import ScopedEncryptedMemoryRepository
from app.security.audit_logger import StructuredAuditLogger
from app.security.persistence_redactor import PersistenceRedactor, RedactionResult
from app.security.pii_detector import PIIEntity
from app.services.artifacts import Artifact
from app.services.db_store import DatabaseStore


class OverlapDetector:
    def detect(self, text: str) -> list[PIIEntity]:
        del text
        return [
            PIIEntity("email", "abc@example.com", 0, 15),
            PIIEntity("person_name", "abc", 0, 3),
            PIIEntity("organization", "example", 4, 11),
        ]

    @staticmethod
    def non_overlapping(entities: list[PIIEntity]) -> list[PIIEntity]:
        from app.security.pii_detector import PIIDetector

        return PIIDetector.non_overlapping(entities)

    def redact_entities(self, text: str, entities: list[PIIEntity]) -> str:
        from app.security.pii_detector import PIIDetector

        return PIIDetector.redact_entities(self, text, entities)  # type: ignore[arg-type]


class TrackingRedactor(PersistenceRedactor):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[str] = []

    def redact_text(self, text: str) -> RedactionResult:
        self.inputs.append(text)
        return super().redact_text(text)


@pytest.mark.unit
def test_overlapping_entities_are_redacted_once_and_metadata_has_no_values() -> None:
    result = PersistenceRedactor(OverlapDetector()).redact_text("abc@example.com")  # type: ignore[arg-type]

    assert result.text == "[EMAIL]"
    assert result.count == 1
    assert result.types == ("email",)
    assert "abc@example.com" not in repr(result)
    assert not hasattr(result, "values")


@pytest.mark.unit
def test_mapping_keys_are_recursively_redacted_and_collisions_preserve_entries() -> None:
    redacted = PersistenceRedactor().redact_value(
        {
            "first@example.com": {"nested@example.com": "call 202-555-0147"},
            "second@example.com": "123-45-6789",
            7: "safe",
        }
    )
    serialized = json.dumps(redacted)
    assert "first@example.com" not in serialized
    assert "second@example.com" not in serialized
    assert "nested@example.com" not in serialized
    assert redacted["[EMAIL]"]["[EMAIL]"] == "call [PHONE]"
    assert redacted["[EMAIL]__2"] == "[SSN]"
    assert redacted["7"] == "safe"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scoped_memory_redacts_content_and_provenance_before_encryption(tmp_path) -> None:
    database = tmp_path / "memory.db"
    store = DatabaseStore(f"sqlite+aiosqlite:///{database}")
    await store.initialize()
    repository = ScopedEncryptedMemoryRepository(
        store.session_factory, b"k" * 32, redactor=PersistenceRedactor()
    )
    secrets = (
        "private.user@example.com",
        "202-555-0147",
        "123-45-6789",
        "4111-1111-1111-1111",
    )
    try:
        fact = await repository.add(
            "owner",
            "project",
            f"contact {' '.join(secrets[:2])}",
            provenance={secrets[0]: f"ssn {secrets[2]}; card {secrets[3]}"},
        )
        combined = f"{fact.content} {fact.provenance['[EMAIL]']}"
        assert all(secret not in combined for secret in secrets)
        assert "[EMAIL]" in fact.content and "[PHONE]" in fact.content
        assert "[SSN]" in fact.provenance["[EMAIL]"]
        assert "[CREDIT_CARD]" in fact.provenance["[EMAIL]"]
    finally:
        await store.close()

    raw = database.read_bytes()
    assert all(secret.encode() not in raw for secret in secrets)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_raw_database_contains_redactions_and_no_detected_values(
    tmp_path, caplog
) -> None:
    database = tmp_path / "audit.db"
    secrets = (
        "private.user@example.com",
        "202-555-0147",
        "123-45-6789",
        "4111-1111-1111-1111",
    )
    audit = StructuredAuditLogger(PersistenceRedactor(), str(database))

    await audit.log(
        agent_id=secrets[0],
        action=f"call {secrets[1]}",
        resource=f"record/{secrets[2]}",
        parameters={secrets[0]: [secrets[3], {"value": secrets[0]}]},
        result="sent to " + " ".join(secrets),
        security_level=secrets[0],
        correlation_id=secrets[0],
    )

    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT agent_id, action, resource, parameters, result, "
            "security_level, correlation_id FROM audit_log"
        ).fetchone()
    finally:
        connection.close()
    serialized = json.dumps(row)
    assert all(secret not in serialized for secret in secrets)
    assert all(secret not in caplog.text for secret in secrets)
    assert all(tag in serialized for tag in ("[EMAIL]", "[PHONE]", "[SSN]", "[CREDIT_CARD]"))
    assert row[-2:] == ("warning", None)


@pytest.mark.unit
def test_two_apps_use_only_their_explicit_redactor_for_artifacts_and_audit(tmp_path) -> None:
    first_redactor, second_redactor = TrackingRedactor(), TrackingRedactor()
    first_app = create_app(
        Settings(
            llm_provider="mock",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'first.db'}",
        ),
        persistence_redactor_factory=lambda: first_redactor,
    )
    second_app = create_app(
        Settings(
            llm_provider="mock",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'second.db'}",
        ),
        persistence_redactor_factory=lambda: second_redactor,
    )

    with TestClient(first_app), TestClient(second_app):
        assert first_app.state.persistence_redactor is first_redactor
        assert second_app.state.persistence_redactor is second_redactor
        asyncio.run(first_app.state.artifacts.save(Artifact(title="first@example.com")))
        asyncio.run(second_app.state.audit_logger.log("second@example.com", "read", "resource"))

    assert "first@example.com" in first_redactor.inputs
    assert "first@example.com" not in second_redactor.inputs
    assert "second@example.com" in second_redactor.inputs
    assert "second@example.com" not in first_redactor.inputs
