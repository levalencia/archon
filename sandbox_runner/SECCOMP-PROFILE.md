# Sandbox runner outer seccomp profile

`sandbox_runner/seccomp-bootstrap.json` is vendored from the Moby default seccomp profile:

- Source: `https://github.com/moby/profiles/blob/main/seccomp/default.json`
- Raw source: `https://raw.githubusercontent.com/moby/profiles/main/seccomp/default.json`
- Retrieved: 2026-08-28
- Upstream file SHA-256: `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74`

The outer profile retains Moby's `SCMP_ACT_ERRNO` default and normal Docker allow rules, including the `seccomp` syscall required for the runner's pre-exec child to load a stricter application filter. It replaces neither the child filter nor the backend startup probe. If the child cannot load its filter or create a socket successfully when it should be blocked, backend startup fails closed.

Do not replace this profile with `seccomp=unconfined`. When updating it, record the new upstream revision/hash and rerun the nested-seccomp and local deployment acceptance tests.
