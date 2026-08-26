"""Persistence-boundary PII probes."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.memory.scoped import ScopedEncryptedMemoryRepository
from app.security.audit_logger import StructuredAuditLogger
from app.security.persistence_redactor import PersistenceRedactor
from app.security.pii_detector import PIIEntity
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


@pytest.mark.unit
def test_overlapping_entities_are_redacted_once_and_metadata_has_no_values() -> None:
    result = PersistenceRedactor(OverlapDetector()).redact_text("abc@example.com")  # type: ignore[arg-type]

    assert result.text == "[EMAIL]"
    assert result.count == 1
    assert result.types == ("email",)
    assert "abc@example.com" not in repr(result)
    assert not hasattr(result, "values")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scoped_memory_redacts_content_and_provenance_before_encryption(tmp_path) -> None:
    database = tmp_path / "memory.db"
    store = DatabaseStore(f"sqlite+aiosqlite:///{database}")
    await store.initialize()
    repository = ScopedEncryptedMemoryRepository(store.session_factory, b"k" * 32)
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
            provenance={"source": f"ssn {secrets[2]}; card {secrets[3]}"},
        )
        combined = f"{fact.content} {fact.provenance['source']}"
        assert all(secret not in combined for secret in secrets)
        assert "[EMAIL]" in fact.content and "[PHONE]" in fact.content
        assert "[SSN]" in fact.provenance["source"]
        assert "[CREDIT_CARD]" in fact.provenance["source"]
    finally:
        await store.close()

    raw = database.read_bytes()
    assert all(secret.encode() not in raw for secret in secrets)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_raw_database_contains_redactions_and_no_detected_values(tmp_path) -> None:
    database = tmp_path / "audit.db"
    secrets = (
        "private.user@example.com",
        "202-555-0147",
        "123-45-6789",
        "4111-1111-1111-1111",
    )
    audit = StructuredAuditLogger(str(database))

    await audit.log(
        agent_id=secrets[0],
        action=f"call {secrets[1]}",
        resource=f"record/{secrets[2]}",
        parameters={"nested": [secrets[3], {"value": secrets[0]}]},
        result="sent to " + " ".join(secrets),
    )

    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT agent_id, action, resource, parameters, result FROM audit_log"
        ).fetchone()
    finally:
        connection.close()
    serialized = json.dumps(row)
    assert all(secret not in serialized for secret in secrets)
    assert all(tag in serialized for tag in ("[EMAIL]", "[PHONE]", "[SSN]", "[CREDIT_CARD]"))
