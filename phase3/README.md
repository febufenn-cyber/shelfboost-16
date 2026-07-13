# Shelfboost Phase 3 — Safe selected-field publishing

Phase 3A creates a conflict-checked publish plan. Phase 3B executes only ready items after a fresh live read.

## Write contract

- only `Body (HTML)`, `SEO Title`, and `SEO Description` can be changed;
- every product is read immediately before its mutation;
- if live fields equal the proposal, the item is marked already applied without writing;
- if live fields equal the approved original, one mutation attempt is allowed;
- any other live state is an external conflict;
- transport failures, 5xx responses, 429 responses, and unreadable success responses become `uncertain`;
- an uncertain item is read and reconciled before any later attempt;
- Shopify `userErrors` are stored as item-level failures;
- successful responses must contain the proposed values before the mirror is updated.

Shopify requires the `write_products` scope for `productUpdate`.

## Commands

```bash
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store plan \
  --shop store.myshopify.com \
  --approved-csv /private/store/phase1-approved.csv \
  --changes-json /private/store/phase1-approved.changes.json \
  --bridge-manifest /private/store/phase1-catalog.manifest.json

export SHOPIFY_ACCESS_TOKEN='...'
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store execute \
  --shop store.myshopify.com --batch-id 1
```

Rollback remains disabled until Phase 3C.
