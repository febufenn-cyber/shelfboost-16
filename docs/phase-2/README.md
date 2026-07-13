# Shelfboost Phase 2 — Read-only Shopify connection

## Strategic purpose

Phase 2 removes repeated CSV exports without weakening the Phase 1 trust contract. Shopify is treated as a read-only source of catalog truth. Shelfboost mirrors catalog state, verifies change notifications, reconciles deletions, and produces a provenance-bound Phase 1 input artifact.

The phase deliberately stops before publishing. Connecting a store and keeping a mirror current is a different risk class from changing live merchant content.

## Forcing sequence

```text
version-pinned full sync
→ immutable raw snapshots
→ normalized product and variant mirror
→ authenticated webhook intake
→ deduplicated refresh queue
→ read-only single-product reconciliation
→ completeness and freshness gates
→ Phase 1-compatible CSV plus provenance manifest
→ human-reviewed Phase 1 workflow
```

## Phase 2A — synchronization foundation

- Admin GraphQL API version is explicit and response fall-forward is rejected.
- Product and nested variant connections are fully paginated.
- Rate limits and transient server failures use bounded retries.
- Full syncs may mark unseen products deleted; incremental syncs may not.
- Every raw response page is stored privately with a SHA-256 digest.
- Access-token values remain outside SQLite.

## Phase 2B — webhook reconciliation

- HMAC is verified against the exact raw request body before JSON parsing.
- Deliveries are deduplicated by Shopify webhook ID.
- Product create/update events enqueue a canonical API refresh instead of trusting webhook fields as the mirror.
- Product delete events soft-delete the mirror record.
- App uninstall disables the shop, clears its token reference, and ignores pending work.
- Multiple pending events for one product are coalesced into one read request.

## Phase 2C — Phase 1 bridge

The bridge emits a Shopify-style CSV that Phase 1 already knows how to normalize and audit. It also writes a manifest containing source sync IDs, API versions, catalog timestamps, product-level provenance, row counts, warnings, and the CSV digest.

The export is blocked when:

- the shop is inactive or uninstalled;
- no completed full baseline sync exists;
- product variants are incomplete;
- refresh work is pending, processing, or failed;
- active handles are missing or duplicated;
- a `facts` metafield key is unsafe or conflicts with another value.

Only allowlisted scalar `facts` metafields become approved-fact input columns. Complex references are omitted and reported rather than flattened into misleading prose.

## Blind spots deliberately not hidden

### A read-only mirror can still be stale

Webhook delivery is not treated as the sole source of truth. Periodic full reconciliation remains necessary, and the bridge refuses export while known refresh work is unresolved.

### A webhook is a notification, not a catalog record

Product create/update payloads can differ from the GraphQL shape and may be retried. The system uses them only to identify what must be refreshed.

### “Connected” does not mean “complete”

A successful API request can still contain truncated nested connections. Variant completeness and metafield limits are explicit gates.

### Metafields are not automatically safe facts

Only the governed `facts` namespace and allowlisted scalar types are admitted. A merchant still owns the truth of those values.

### OAuth is deployment infrastructure, not product proof

The repository currently accepts an offline access token through a private environment variable. A production callback server, encrypted token vault, rotation, installation lifecycle, and tenant isolation remain future deployment work.

## Exit gates before Phase 3

Phase 3 should not introduce writes merely because Phase 2 code exists. Required evidence:

1. at least three permissioned stores complete a full sync and repeated webhook refresh cycle;
2. reconciliation produces no unexplained product or variant loss;
3. Phase 2 bridge artifacts import into Phase 1 without manual structural repair;
4. merchants complete review using synchronized data and request continued connection;
5. access scopes, data retention, deletion, and uninstall behavior are documented for deployment;
6. at least one paid pilot establishes that connected refresh materially improves the workflow;
7. the team can state which exact fields, if any, merchants want published back and under what approval boundary.

## Phase 3 candidate

The next earned phase is not unrestricted one-click publishing. It should be **reversible selected-field publishing**: precondition checks, per-field approval, original snapshots, idempotency, scheduled batches, partial-failure recovery, and one-click rollback.
