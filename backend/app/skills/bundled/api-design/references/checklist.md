# API design checklist

## Contract
- Identify callers, authorization scope, idempotency needs, and compatibility constraints.
- Define strict request/response schemas, stable error codes, size limits, and pagination.
- Keep secrets and internal exception details out of responses and logs.

## Implementation
- Separate transport models from domain services and persistence models.
- Enforce owner/project scope in the repository query, not only in route code.
- Apply authentication, CSRF protection, rate limits, and approval checks consistently.

## Verification
- Test success, malformed input, unauthorized, forbidden, missing, conflict, and retry cases.
- Verify OpenAPI matches runtime behavior and old clients remain compatible.
- Exercise the endpoint through the real application wiring, not only a service mock.
