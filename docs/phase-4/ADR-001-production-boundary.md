# ADR-001 — Preserve domain logic behind portable production interfaces

## Decision

Keep the proven Python Phase 1–3 domain behavior and introduce portable Phase 4 application-boundary interfaces for tenancy, authorization state, token encryption, jobs, privacy, and health. Do not rewrite working logic into a fashionable runtime before equivalent contract tests exist.

## Production binding

- relational storage: Postgres or another transactionally equivalent managed database;
- credentials: managed KMS/envelope-encryption implementation of `EnvelopeCipher`;
- jobs: durable managed queue implementing the tested claim/retry/dead-letter semantics;
- application runtime: a supported Shopify app runtime capable of session-token authentication and Shopify-managed installation/token exchange;
- local/CI fixtures: SQLite and an isolated test cipher defined only in tests.

## Consequences

- domain behavior remains testable without cloud credentials;
- deployment adapters can change without weakening trust contracts;
- live installation, KMS, queue, and deletion verification remain staging gates;
- SQLite is not declared the production multi-tenant database.
