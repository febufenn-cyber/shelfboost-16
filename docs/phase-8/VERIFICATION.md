# Phase 8 Verification — Measurement, experimentation, recurring optimization

- Roadmap version: 1.0
- Starting `main`: `38c6a9c9ad767fdee0f7fa0d3d37f0f61fdc900c`
- Previous package: Phase 7 merged and CI-green
- Decision: **PROCEED with source-attributed measurement and controlled-experiment contracts; live analytics connectors remain external.**

## Epistemic boundary

Shelfboost must not transform an observed before/after difference into a causal claim. Every metric stores its source, subject, unit, collection window, and idempotency key. Reports default to `observational`. A controlled estimate requires a predeclared primary metric, deterministic assignment, a holdout group, a minimum completed sample, and outcomes collected within the declared window. Even then, the report is an experiment estimate with assumptions—not a universal guarantee.

## Threat model

- fabricated or silently defaulted metrics;
- double-counted imports;
- mismatched time windows or currencies;
- survivorship bias from deleted products;
- changing experiment goals after results arrive;
- treatment contamination or missing control group;
- claiming causality from correlation;
- automatic rollback from noisy short-term performance;
- optimization cycles repeatedly targeting the same product;
- retention alerts exposing cross-tenant data.

## Data additions

Publication change events, metric observations, experiments, deterministic assignments, experiment outcomes, optimization cycles, cycle items, alerts, and report snapshots.

## Tests

- metric source/window/unit requirements;
- idempotent imports and no invented zero values;
- observational before/after report labeling;
- deterministic stable assignment;
- immutable experiment objective after activation;
- control/treatment and minimum-sample gates;
- outcome-window validation;
- experiment estimate calculation;
- recurring cycle detection for new, stale, missing, and declining products;
- deduplicated cycle items and tenant-scoped alerts;
- no automatic publish or rollback from measurement.

## External blockers

- Search Console, Shopify Analytics, ad platform, and conversion-source credentials;
- merchant consent and data-processing decisions for imported analytics;
- sufficient real traffic/sample sizes;
- production scheduler and notification channel.

## Non-goals

- guaranteed ranking, conversion, or revenue lift;
- hidden synthetic metrics;
- performance-triggered automatic publishing or rollback;
- cross-store benchmarking without explicit consent and anonymization.

## Exit gate

Phase 8 is complete under fixture-backed tests when changes and observations are traceable, reports preserve observational versus experimental meaning, experiments fail closed without control/sample/window requirements, and recurring cycles create reviewable—not autonomous—optimization work.
