# Cogentrex Namespace Cutover

## Scope

This rebrand is a clean namespace cutover, not a compatibility release. It changes
configuration prefixes, local state paths, database names, browser storage,
cryptographic domain separation, telemetry names, container identities, and
learning-media schemas.

Do not point the Cogentrex runtime at state produced by a pre-rebrand build.

## Before switching revisions

1. Use the currently deployed revision's documented backup procedure.
2. Verify the backup independently before stopping the existing stack.
3. Record which external provider and observability settings must be recreated,
   without copying secrets into documentation or logs.
4. Stop the existing stack using the script from the same revision that started it.

## First Cogentrex start

1. Generate a fresh protected environment using the Cogentrex scripts and
   `COGENTREX_*` variable names.
2. Start with fresh PostgreSQL and Redis volumes under the `cogentrex-local`
   Compose project.
3. Use the `.cogentrex/instructions.md` project-instruction convention.
4. Install or mount a library carrying the `.cogentrex-learning-library` marker
   and `cogentrex.learning-library` schema.
5. Reissue API keys and sign in again; pre-cutover browser storage and key prefixes
   are intentionally not consumed.
6. Verify readiness through the canonical local-stack status and HTTP checks before
   claiming that the application is running.

## Data boundary

Encrypted memory, signed envelopes, share tokens, Redis keys, and provider/runtime
state are namespace-bound. They are not silently reinterpreted under the new
identity because doing so would weaken domain separation and make migration claims
that have not been tested.

If historical user data must be retained, design and test a separate export/import
migration before deployment. A database backup alone does not prove that encrypted
or signed records remain usable after the namespace change.

## External systems

The following actions are separate release operations and require explicit approval:

- rename or replace the GitHub repository;
- publish new release assets;
- update CI/CD secrets and deployment variables;
- replace Helm releases or Kubernetes resources;
- replace the retained local stack;
- redirect domains or public documentation.
