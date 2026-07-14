# Shelfboost

> Find weak Shopify listings, prepare fact-traceable improvements, publish only fields a human explicitly approves, and preserve a conflict-safe path back.

Shelfboost is being built in evidence-gated phases. The repository now contains a discovery system, a local human-reviewed pilot workflow, read-only Shopify synchronization and reconciliation, publish planning, and live-preconditioned selected-field execution. Phase 3 rollback is still pending, and the production application phases remain planned rather than complete.

## Current status

| Phase | Status | Purpose |
|---|---|---|
| Phase 0 | Implemented foundation; real evidence still required | Prove buyer pain, trust requirements, recurring use, and willingness to pay |
| Phase 1 | Implemented local pilot system | Prove fact governance, drafting, validation, review, approved-only export, and paid continuation |
| Phase 2 | Implemented read-only connection foundation | Mirror Shopify safely, reconcile changes, and feed synchronized data into Phase 1 |
| Phase 3 | **3A planning and 3B execution implemented; 3C rollback pending** | Publish selected approved fields with live conflict checks, then restore them safely |
| Phases 4–9 | Planned | Production tenancy, merchant UI, AI, billing/compliance, measurement, and launch hardening |

There are **seven remaining build packages**: Phase 3C plus Phases 4–9. The authoritative implementation and autonomous merge contract is in [`docs/REMAINING_IMPLEMENTATION_PLAN.md`](docs/REMAINING_IMPLEMENTATION_PLAN.md).

## End-to-end workflow

```text
Shopify Admin GraphQL synchronization
→ immutable snapshots and normalized mirror
→ authenticated webhook reconciliation
→ freshness and completeness gates
→ Phase 1-compatible bridge artifact
→ governed product-fact ledger
→ catalog audit and priority batch
→ controlled drafts and validation
→ human field-level decisions
→ immutable publish plan
→ live precondition read
→ selected-field productUpdate attempt
→ uncertain-outcome reconciliation
→ conflict-safe rollback (Phase 3C pending)
```

## Implemented write boundary

Phase 3B contains an explicit Shopify `productUpdate` execution path, but it is intentionally narrow:

- only `Body (HTML)`, SEO title, and SEO description;
- only fields approved through the Phase 1 evidence chain;
- a live product read immediately before every write;
- no blind mutation retry;
- already-applied proposals are reconciled without writing;
- later merchant or app edits become conflicts;
- transport ambiguity becomes `uncertain` and requires a later live read;
- no autonomous approval or force-overwrite path.

Rollback remains disabled until Phase 3C is implemented.

## Phase 2 capabilities

- API version pinning and response-version verification;
- cursor pagination for products and variants;
- bounded retry for read-side rate limits and transient server failures;
- immutable raw response snapshots with SHA-256 digests;
- full-sync deletion reconciliation and safe incremental refresh;
- raw-body webhook HMAC verification;
- delivery deduplication and product refresh coalescing;
- product deletion and app-uninstall handling;
- Phase 1-compatible CSV export with provenance manifest;
- freshness, active-shop, full-baseline, variant-completeness, and fact-type gates.

## Run validation

```bash
make test
make phase1-demo
make phase2-demo
```

The synthetic demos use fixtures. They do not publish to a live merchant store.

## Trust boundary

- no autonomous approval;
- no variant, price, inventory, tag, status, media, or metafield writes;
- no force overwrite of an external edit;
- access-token values are not stored in SQLite;
- invalid webhook HMACs are rejected before persistence;
- incremental absence is not interpreted as deletion;
- unresolved refresh work blocks bridging and publishing;
- deleted products are excluded;
- only allowlisted scalar `facts` metafields enter approved-fact columns;
- no ranking, traffic, conversion, or revenue guarantees;
- no real merchant data in this public repository.

## Documentation

- [`docs/REMAINING_IMPLEMENTATION_PLAN.md`](docs/REMAINING_IMPLEMENTATION_PLAN.md)
- [`docs/phase-0/00-phase-0-charter.md`](docs/phase-0/00-phase-0-charter.md)
- [`docs/phase-1/README.md`](docs/phase-1/README.md)
- [`docs/phase-2/README.md`](docs/phase-2/README.md)
- [`docs/phase-3/README.md`](docs/phase-3/README.md)
- [`phase1/README.md`](phase1/README.md)
- [`phase2/README.md`](phase2/README.md)
- [`phase3/README.md`](phase3/README.md)

## Long-term direction

The intended mature product is a Shopify catalog-optimization system with read-only diagnosis, controlled generation, human approval, reversible publishing, and measured outcomes. Cloudflare Workers, Hono, Supabase, encrypted token storage, AI model adapters, and a billing provider remain candidate production components—not commitments that override merchant evidence, current platform rules, or safety gates.
