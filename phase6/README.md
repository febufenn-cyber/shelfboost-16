# Shelfboost Phase 6 — Governed production AI

Phase 6 replaces the deterministic workflow placeholder with provider-agnostic AI contracts that fail closed.

## Implemented

- versioned prompt templates requiring approved facts and brand profile inputs;
- tenant-scoped generation jobs and items;
- cheap/strong model routing based on risk, complexity, and missing facts;
- estimated and actual per-job budget checks;
- bounded provider attempts;
- strict field schema for description and SEO output;
- approved-fact references and abstention requirements;
- prohibited-language, risky-claim, field-length, and numeric-claim checks;
- duplicate-output fingerprinting within a batch;
- prompt/model/cost/usage traceability;
- regression evaluation cases and results;
- merchant feedback rules that remain proposed until owner/admin confirmation.

## Boundary

No provider credential or merchant evaluation corpus was available during CI. Fixture providers exercise the contracts, but real-provider quality, latency, data residency, and cost must be validated before production launch. AI output remains a draft and cannot bypass Phase 5 review or Phase 3 publishing controls.

## Validation

```bash
PYTHONPATH=phase4:phase6 python3 -m unittest discover -s phase6/tests -v
```
