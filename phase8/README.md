# Shelfboost Phase 8 — Measurement and recurring optimization

Phase 8 records publication changes and source-attributed metrics, distinguishes observational comparisons from controlled estimates, and creates reviewable recurring optimization cycles.

## Implemented

- idempotent publication-change and metric-observation records;
- required source, subject, unit, collection window, and source reference;
- before/after reports explicitly labeled `observational` with confounding limitations;
- predeclared experiments with immutable active objectives;
- deterministic stable control/treatment assignment;
- outcome unit/window validation and minimum-sample/control gates;
- controlled-estimate reports without unsupported significance or universal claims;
- recurring queues for new, stale, missing, and declining product content;
- deduplicated alerts and cycle items;
- zero automatic publishing or rollback from metrics.

## Boundary

No live Search Console, Shopify Analytics, ad-platform, scheduler, or notification credentials were available. Fixture tests validate data provenance, experiment semantics, and recurring-cycle behavior. Real sample size and connector quality remain staging gates.

## Validation

```bash
PYTHONPATH=phase4:phase8 python3 -m unittest discover -s phase8/tests -v
```
