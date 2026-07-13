# Phase 3 — Reversible selected-field publishing

## Implemented

### 3A: planning

- Phase 1 approval, approved CSV, Phase 2 mirror, and bridge provenance must agree;
- any stale product blocks the batch;
- immutable planned-before snapshots and deterministic plan keys are recorded.

### 3B: execution

- a live product read precedes every write;
- unchanged, already-applied, and externally modified states are distinguished;
- `productUpdate` receives only the selected description or SEO fields;
- mutations are sent once, never blindly retried;
- ambiguous outcomes become `uncertain` and are reconciled by a later live read;
- Shopify `userErrors`, raw requests, responses, hashes, and snapshots are retained;
- verified successes update the local mirror;
- partial batches remain item-addressable.

## Still prohibited

- autonomous approval;
- variants, prices, inventory, tags, product status, media, or metafield writes;
- force-overwriting an external edit;
- rollback without a live precondition check.

Phase 3C adds rollback and a final audit bundle.
