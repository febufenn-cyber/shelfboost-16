# Phase 6 Verification — Governed production AI

- Roadmap version: 1.0
- Starting `main`: `384b7a08820b865946150129bb94b20faad7cc6d`
- Previous package: Phase 5 merged and CI-green
- Decision: **PROCEED with provider-agnostic, fixture-backed AI contracts; live provider credentials and external quality benchmarking remain pending.**

## Contracts preserved

- Phase 1 approved-fact ledger and abstention behavior;
- Phase 5 versioned brand profiles and human review;
- Phase 3 publish path remains downstream and cannot be invoked directly by a model;
- Phase 4 tenant, audit, and job boundaries.

## Threat model

- unsupported factual or regulated claims;
- prompt injection from catalog text or brand examples;
- malformed or partial structured output;
- duplicate/generic catalog copy;
- expensive model routing for routine work;
- unbounded retries and budget exhaustion;
- model or prompt changes silently degrading quality;
- merchant edits becoming global rules without confirmation;
- provider response content leaking secrets or cross-tenant data;
- generated content being treated as approved.

## Data additions

Tenant-scoped prompt versions, generation jobs/items, provider usage, evaluation cases/results, and feedback-rule proposals. Raw provider credentials are never stored in the AI tables.

## Tests

- strict structured-output schema;
- approved facts are the only factual source;
- unsupported claims and prohibited terms block output;
- abstention for missing required facts;
- risk/complexity model routing;
- per-tenant budget reservation and rejection;
- bounded retry and terminal failure;
- prompt-version traceability;
- deterministic evaluation thresholds;
- duplicate output detection;
- feedback remains proposed until merchant-confirmed;
- provider errors do not auto-approve or publish.

## External blockers

- production model-provider API key;
- provider data-processing terms and regional routing decision;
- real merchant evaluation corpus;
- production cost observations and latency SLOs.

## Non-goals

- autonomous publishing;
- internet keyword invention without approved source data;
- regulatory/legal advice;
- hidden model fallback that bypasses validation;
- claiming real-provider quality from fixture tests.

## Exit gate

Phase 6 is complete under fixture-backed tests when every draft is traceable to prompt/model/facts/brand versions, provider costs are budgeted, unsafe outputs fail closed, regression evaluations gate changes, and merchant feedback requires scoped confirmation.
