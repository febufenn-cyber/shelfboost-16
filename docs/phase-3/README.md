# Phase 3 — Reversible selected-field publishing

## Complete implementation

### 3A — Publish planning

- Phase 1 approval, approved CSV, Phase 2 mirror, and bridge provenance must agree.
- Any stale product blocks the batch.
- Immutable planned-before snapshots and deterministic plan keys are recorded.

### 3B — Live-preconditioned execution

- A live product read precedes every write.
- Unchanged, already-applied, and externally modified states are distinguished.
- `productUpdate` receives only approved description or SEO fields.
- Mutations are sent once and never blindly retried.
- Ambiguous outcomes become `uncertain` and are reconciled by a later live read.
- Shopify `userErrors`, requests, responses, hashes, and snapshots are retained.
- Verified successes update the local mirror.

### 3C — Conflict-safe rollback and audit closure

- Only items with evidence that Shelfboost actually published are rollback-eligible.
- A deterministic rollback plan binds the source batch and immutable before/after snapshots.
- Every rollback reads the live product first.
- Changed fields must still equal Shelfboost's published values.
- Later merchant or app edits become `rollback_conflict`.
- Already-restored products reconcile without mutation.
- Ambiguous rollback outcomes require another live read before a later attempt.
- The mirror changes only after verified restoration.
- A tamper-evident audit directory records source digests, items, snapshots, attempts, rollback runs, and a SHA-256 manifest.
- Secret-like keys are redacted from exported audit artifacts.

## Commands

```bash
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store plan-rollback \
  --batch-id 1

export SHOPIFY_ACCESS_TOKEN='...'
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store rollback \
  --shop store.myshopify.com --rollback-run-id 1

PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store audit-bundle \
  --batch-id 1
```

## Trust boundary

Still prohibited:

- autonomous approval;
- variants, prices, inventory, tags, product status, media, or metafield writes;
- force-overwriting an external edit;
- performance-triggered automatic rollback;
- claiming live-store verification when only fixtures were used.

Phase 3 is complete under fixture-backed tests. A controlled development-store exercise remains required before production use.
