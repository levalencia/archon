"""Security demo API: interactive testing of PII, guardrails, permissions.

POST /api/security/pii-scan     — Detect PII in text
POST /api/security/guardrail    — Test input/output guardrails
POST /api/security/permission   — Test permission checks
GET  /api/security/demo-report  — Security capabilities summary
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.security.auth import require_admin
from app.security.guardrails import InputGuardrail, OutputGuardrail
from app.security.permission_manager import SecurePermissionManager
from app.security.pii_detector import PIIDetector

router = APIRouter(
    prefix="/api/security", tags=["security"], dependencies=[Depends(require_admin)]
)

_pii_detector = PIIDetector()
_input_guardrail = InputGuardrail()
_output_guardrail = OutputGuardrail()
_temp_dir = Path(tempfile.mkdtemp(prefix="archon_demo_"))
_permission_manager = SecurePermissionManager(base_dir=_temp_dir)


class PIIScanRequest(BaseModel):
    text: str = Field(..., min_length=1)


class GuardrailRequest(BaseModel):
    text: str = Field(..., min_length=1)
    direction: str = Field(default="input", pattern="^(input|output)$")


class PermissionRequest(BaseModel):
    path: str
    action: str = "read_file"


@router.post("/pii-scan")
async def pii_scan(body: PIIScanRequest) -> dict:
    """Scan text for PII entities."""
    entities = _pii_detector.detect(body.text)
    redacted = _pii_detector.redact(body.text)
    risk = _pii_detector.assess_risk(body.text)

    return {
        "entities": [
            {
                "type": e.entity_type,
                "value": e.value,
                "start": e.start,
                "end": e.end,
                "risk_level": e.risk_level,
            }
            for e in entities
        ],
        "redacted_text": redacted,
        "risk_level": risk,
        "entity_count": len(entities),
    }


@router.post("/guardrail")
async def test_guardrail(body: GuardrailRequest) -> dict:
    """Test input or output guardrails."""
    if body.direction == "input":
        result = await _input_guardrail.check_input(body.text)
    else:
        result = await _output_guardrail.check_output(body.text)

    return {
        "direction": body.direction,
        "result": result,
    }


@router.post("/permission")
async def test_permission(body: PermissionRequest) -> dict:
    """Test permission checks."""
    allowed = await _permission_manager.check(
        agent_id="demo",
        resource=body.path,
        action=body.action,
        path=body.path,
    )

    return {
        "path": body.path,
        "action": body.action,
        "allowed": allowed,
        "base_dir": str(_temp_dir),
    }


@router.get("/demo-report")
async def security_demo_report() -> dict:
    """Summary of all security capabilities."""
    return {
        "capabilities": {
            "pii_detection": {
                "description": "Detect email, phone, SSN, credit card, IP, DOB",
                "patterns": list(_pii_detector._compiled.keys()),
                "endpoint": "POST /api/security/pii-scan",
            },
            "input_guardrails": {
                "description": "Block prompt injection, role override, system prefix",
                "patterns": 8,
                "endpoint": "POST /api/security/guardrail",
            },
            "output_guardrails": {
                "description": "Detect and redact PII in agent output",
                "auto_redact": True,
                "endpoint": "POST /api/security/guardrail",
            },
            "permission_manager": {
                "description": "Path.resolve + trailing slash fix, action allowlist",
                "fixes": ["sibling-prefix bypass (Day 3)", "symlink escape"],
                "endpoint": "POST /api/security/permission",
            },
            "circuit_breaker": {
                "description": "CLOSED/OPEN/HALF_OPEN state machine for dead services",
                "states": ["closed", "open", "half_open"],
            },
            "rate_limiter": {
                "description": "Sliding window with Redis sorted sets",
                "default_limit": "60 requests per 60 seconds",
            },
        },
        "total_security_features": 6,
    }
