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

## Remaining: 3C rollback and audit closure

Phase 3C must:

- plan rollback only for verified published items;
- read the live product immediately before restoration;
- restore only fields that still equal Shelfboost's published value;
- refuse to overwrite a later merchant or app edit;
- reconcile ambiguous mutation outcomes before another attempt;
- verify restoration before updating the mirror;
- emit a complete SHA-256-indexed audit bundle without secrets.

The detailed implementation, tests, exit gate, autonomous build behavior, Git workflow, and remaining Phases 4–9 are defined in [`../REMAINING_IMPLEMENTATION_PLAN.md`](../REMAINING_IMPLEMENTATION_PLAN.md).

## Still prohibited

- autonomous approval;
- variants, prices, inventory, tags, product status, media, or metafield writes;
- force-overwriting an external edit;
- rollback without a live precondition check;
- claiming Phase 3 complete before 3C is merged and verified.
