# Test engineering checklist

## Design
- Start with one failing test that expresses the user-visible contract.
- Prefer deterministic fakes at external boundaries and real wiring inside the application.
- Cover success, malformed input, authorization, timeout, cancellation, race, and restart.

## Layers
- Unit-test pure policy and parsing decisions.
- Integration-test persistence, migrations, APIs, and provider/tool adapters.
- Use browser tests for critical user journeys and responsive/accessibility behavior.

## Gate
- Run the focused test first, then adjacent suites, then the clean full gate.
- Record exact counts and commit; never report unexecuted tests as passed.
- Treat flaky tests as defects: synchronize on observable state instead of adding arbitrary sleeps.
