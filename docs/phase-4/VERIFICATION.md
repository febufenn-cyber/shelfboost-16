# Phase 4 Verification — Production application, identity, tenancy, installation

- Roadmap version: 1.0
- Starting `main`: `c70341aed281727b356be80de964edf41104fb3d`
- Previous package: Phase 3C merged and CI-green
- Decision: **PROCEED with production contracts and fixture-backed adapters; deployed Shopify installation remains externally blocked.**

## Official platform check

Shopify currently recommends Shopify-managed installation and token exchange for apps rendered in the Shopify admin, with session tokens for incoming embedded-app requests. The implementation therefore separates the application identity/tenant contracts from any single OAuth transport, while retaining a signed, expiring, one-time state flow for standalone or fallback authorization. Minimal scopes remain `read_products` and `write_products`; further scopes require a later feature-specific justification.

## Architecture decision

Preserve the tested Python domain components and introduce a new production-boundary package rather than rewriting them. Phase 4 uses portable service interfaces, SQLite fixtures, and WSGI-compatible handlers for tests. Production deployment may bind the interfaces to Postgres, managed queues, a KMS/envelope-encryption provider, and a supported Shopify app runtime.

## Data model and migrations

Add tenant-scoped organizations, users, memberships, shops, installations, token envelopes, OAuth nonces, webhook deliveries, jobs, dead letters, audit events, and deletion requests. Every merchant-owned row carries `organization_id` and/or `shop_id`. Migrations are additive and versioned.

## Threat model

- OAuth state forgery, replay, expiration, and shop substitution.
- Token leakage through logs, URLs, database plaintext, or audit payloads.
- Cross-tenant record access through predictable IDs.
- Webhook replay and duplicate processing.
- Poison jobs causing infinite retry loops.
- Uninstall leaving active credentials or queued work.
- Retaining merchant data beyond documented policy.
- Health endpoints exposing secrets.

## Required secrets and external blockers

- Shopify client ID and secret;
- production app URL and callback registration;
- production key-management provider;
- deployed HTTPS endpoint;
- test/development Shopify store.

These are unavailable in this build. No live-install claim will be made.

## Tests

- forged, expired, replayed, and shop-substituted state rejection;
- tenant-scoped membership and shop access;
- encrypted token storage through a provider interface and key rotation;
- token value absent from database and logs;
- webhook dedupe, retry, dead-letter, replay, and correlation;
- uninstall credential revocation and queue cancellation;
- data-export and deletion lifecycle;
- health/readiness/version behavior;
- migration idempotency.

## Non-goals

- polished merchant UI;
- billing;
- production AI generation;
- public app-store submission;
- inventing a production encryption primitive in application code.

## Exit gate

Phase 4 is complete under fixture-backed tests when the app boundary has authenticated tenant context, one-time authorization state, encrypted-token interfaces, durable webhook/job semantics, privacy lifecycle controls, and deployable health/configuration contracts. Live installation and managed-KMS integration remain explicit staging gates.
