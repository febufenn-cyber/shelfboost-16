# Shelfboost

> Find weak Shopify listings, prepare fact-traceable improvements, and export only the fields a human explicitly approves.

Shelfboost is being built in evidence-gated phases. The repository now contains both the Phase 0 discovery system and a working Phase 1 local concierge-pilot system. It is not yet a production Shopify application.

## Current status

| Phase | Status | Purpose |
|---|---|---|
| Phase 0 | Implemented foundation; real evidence still required | Prove buyer pain, trust requirements, recurring use, and willingness to pay |
| Phase 1 | **Implemented as a local pilot system** | Prove repeatable intake, fact governance, drafting, validation, review, approved-only export, and paid continuation |
| Phase 2+ | Not started | Shopify read-only integration, merchant-facing product, safe publishing, measurement, and moat |

## Phase 1 workflow

```text
Shopify CSV
→ product and variant normalization
→ approved fact ledger
→ audit and priority batch
→ versioned brand profile
→ controlled drafts
→ validation and duplicate blocking
→ HTML review pack and field decisions
→ approved-only Shopify CSV export
→ JSON change log
```

### What is implemented

- private SQLite pilot workspace;
- source-file hashing and complete original-row preservation;
- Shopify variant grouping by handle;
- facts admitted only from structured fields and explicit merchant fact columns;
- priority and eligibility separation;
- versioned brand profile JSON;
- conservative deterministic provider for safe workflow testing;
- prohibited-language, claim-language, HTML, length, required-fact, reviewer-edit, and duplicate validation;
- field-level approve/edit/reject/defer decisions;
- blocked drafts cannot be approved;
- approved-only export that preserves untouched fields and variant rows;
- tests, synthetic demo, documentation, and CI.

## Run the Phase 1 synthetic demo

```bash
./phase1/run-demo.sh
```

Or run each step manually:

```bash
export WORKSPACE=/tmp/shelfboost-pilot
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" init
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" import-catalog phase1/sample/shopify-products.csv
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" brand phase1/sample/brand-profile.json
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" select-batch --name "Synthetic pilot" --limit 4
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" generate
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" review-pack
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace "$WORKSPACE" status
```

The demo does not auto-approve or export anything. To complete a real pilot, review the generated decision CSV, import explicit decisions, and run the approved-only export flow in the [Phase 1 pilot runbook](docs/phase-1/README.md#6-pilot-runbook).

## Validation

```bash
make test
make phase1-demo
```

## Trust boundary

Phase 1 remains CSV-based and export-only:

- no Shopify OAuth;
- no live-store writes;
- no autonomous approval;
- no invented missing facts;
- no ranking, traffic, conversion, or revenue guarantees;
- no real merchant data in this public repository.

The included draft provider is deliberately conservative. A later AI provider must preserve the same fact-source, validation, review, and export contracts.

## Documentation

- [`docs/phase-0/00-phase-0-charter.md`](docs/phase-0/00-phase-0-charter.md)
- [`docs/phase-1/README.md`](docs/phase-1/README.md)
- [`phase1/README.md`](phase1/README.md)

## Long-term direction

The intended mature product is a Shopify catalog-optimization system with read-only audit, controlled generation, approval, reversible publishing, and measured outcomes. Cloudflare Workers, Hono, Supabase, Shopify Admin API, AI model adapters, and Stripe remain candidate production components—not commitments that override evidence.
