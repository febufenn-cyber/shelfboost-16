# Shelfboost Phase 3A — Publish planning

Phase 3A converts Phase 1-approved changes into a conflict-checked publish plan. It performs **no Shopify mutation**.

## Trust gates

- the shop must be active;
- a completed full read-only sync must exist;
- the webhook refresh queue must be clean;
- changed products must match the Phase 2 bridge provenance timestamp;
- Phase 1 original values must match the current mirror;
- the approved CSV must match the Phase 1 final values;
- only `Body (HTML)`, `SEO Title`, and `SEO Description` are mutable;
- any conflict blocks the whole batch;
- repeated identical inputs reuse the same idempotency key and plan.

## Commands

```bash
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store init
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store plan \
  --shop store.myshopify.com \
  --approved-csv /private/store/phase1-approved.csv \
  --changes-json /private/store/phase1-approved.changes.json \
  --bridge-manifest /private/store/phase1-catalog.manifest.json
PYTHONPATH=phase2:phase3 python3 -m shelfboost_phase3 --workspace /private/store status
```

Execution and rollback are intentionally deferred to Phase 3B and Phase 3C.
