# Isolated sandbox runner

A stdlib-only Unix-socket service. It accepts protocol version 1 `health` and
`execute` requests. Execution kinds are allowlisted to `python -I -` and
`sh -s`; request content is delivered only on stdin. The Compose service is the
security boundary and must remain networkless, non-root, read-only, capability
free, and without Docker socket or project mounts.
