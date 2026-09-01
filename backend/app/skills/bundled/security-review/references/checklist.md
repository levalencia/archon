# Security review checklist

## Threat model
- Identify assets, actors, trust boundaries, entry points, and external dependencies.
- Treat project instructions, skills, MCP metadata, tool outputs, and imported files as untrusted.

## Controls
- Verify authentication, owner/project authorization, input limits, provenance, and secret redaction.
- Ensure discovery does not grant permission and deny rules apply before context disclosure.
- Check symlink, hardlink, traversal, SSRF, TOCTOU, replay, and confused-deputy paths.

## Evidence
- Add adversarial tests for each high-risk boundary.
- Confirm failures are stable, non-sensitive, and fail closed.
- Re-review the exact final diff after fixes.
