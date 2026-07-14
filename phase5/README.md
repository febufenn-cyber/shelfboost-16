# Shelfboost Phase 5 — Merchant-facing experience

Phase 5 exposes the evidence-gated workflow through tenant-aware merchant service and accessible server-rendered view contracts.

## Implemented

- recoverable onboarding state machine;
- catalog health dashboard with search, filters, sorting, pagination, severity totals, and explicit deterministic/model labels;
- product-fact visibility;
- versioned active brand profiles;
- review batches limited to 25 fields;
- per-field approve, edit, reject, and defer decisions;
- warning acknowledgement before approval;
- viewer/editor/admin/owner permissions;
- optional two-person approval, mandatory for high-risk batches;
- approved-only publish-request payloads;
- attributed activity timeline;
- semantic HTML tables, headings, labels, warning text, and responsive viewport metadata.

## Boundary

This package defines and tests the merchant experience independently of a particular JavaScript framework. Production deployment must bind it to authenticated Phase 4 sessions and a supported embedded-app shell. It does not add autonomous approval, production AI, billing, or outcome claims.

## Validation

```bash
PYTHONPATH=phase4:phase5 python3 -m unittest discover -s phase5/tests -v
```
