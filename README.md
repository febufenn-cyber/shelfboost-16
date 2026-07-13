# Shelfboost

> Find weak Shopify listings, prepare fact-traceable improvements, and export only the fields a human explicitly approves.

Shelfboost is being built in evidence-gated phases. The repository now contains a discovery system, a local human-reviewed pilot workflow, and a read-only Shopify synchronization and reconciliation layer. It is not yet authorized to publish changes to a live store.

## Current status

| Phase | Status | Purpose |
|---|---|---|
| Phase 0 | Implemented foundation; real evidence still required | Prove buyer pain, trust requirements, recurring use, and willingness to pay |
| Phase 1 | Implemented local pilot system | Prove fact governance, drafting, validation, review, approved-only export, and paid continuation |
| Phase 2 | **Implemented read-only connection foundation** | Mirror Shopify safely, reconcile changes, and feed synchronized data into Phase 1 |
| Phase 3+ | Not started | Reversible selected-field publishing, measurement, merchant product, and moat |

## End-to-end workflow

```text
Shopify Admin GraphQL read-only sync
→ immutable snapshots and normalized mirror
→ authenticated webhook reconciliation
→ freshness and completeness gates
→ Phase 1-compatible bridge artifact
→ approved product-fact ledger
→ catalog audit and priority batch
→ controlled drafts and validation
→ human field-level decisions
→ approved-only CSV export
```

No part of this repository currently calls a Shopify mutation.

## Phase 2 capabilities

- API version pinning and response-version verification;
- cursor pagination for products and variants;
- bounded retry for rate limits and transient server failures;
- immutable raw response snapshots with SHA-256 digests;
- full-sync deletion reconciliation and safe incremental refresh;
- raw-body webhook HMAC verification;
- delivery deduplication and product refresh coalescing;
- product deletion and app-uninstall handling;
- Phase 1-compatible CSV export with provenance manifest;
- freshness, active-shop, full-baseline, variant-completeness, and fact-type gates.

## Run the synthetic connected workflow

```bash
./phase2/run-demo.sh /tmp/shelfboost-phase2-demo
```

The demo uses deterministic fixtures. It produces:

- a private SQLite read-only mirror;
- immutable GraphQL page snapshots;
- `exports/phase1-catalog.csv`;
- `exports/phase1-catalog.manifest.json`.

Run all validation:

```bash
make test
make phase1-demo
make phase2-demo
```

## Trust boundary

- no Shopify Admin API mutations;
- no live publishing or automatic approval;
- access-token values are not stored in SQLite;
- invalid webhook HMACs are rejected before persistence;
- incremental absence is not interpreted as deletion;
- unresolved refresh work blocks the Phase 1 bridge;
- deleted products are excluded;
- only allowlisted scalar `facts` metafields enter the approved-fact columns;
- no ranking, traffic, conversion, or revenue guarantees;
- no real merchant data in this public repository.

## Documentation

- [`docs/phase-0/00-phase-0-charter.md`](docs/phase-0/00-phase-0-charter.md)
- [`docs/phase-1/README.md`](docs/phase-1/README.md)
- [`docs/phase-2/README.md`](docs/phase-2/README.md)
- [`phase1/README.md`](phase1/README.md)
- [`phase2/README.md`](phase2/README.md)

## Long-term direction

The intended mature product is a Shopify catalog-optimization system with read-only diagnosis, controlled generation, human approval, reversible publishing, and measured outcomes. Cloudflare Workers, Hono, Supabase, encrypted token storage, AI model adapters, and Stripe remain candidate production components—not commitments that override merchant evidence or safety gates.
