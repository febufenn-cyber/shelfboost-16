# Phase 7 Verification — Billing, entitlements, privacy, compliance, distribution

- Roadmap version: 1.0
- Starting `main`: `039aac56fb63b9003828f34abfbb1302afe77d31`
- Previous package: Phase 6 merged and CI-green
- Decision: **PROCEED with provider-neutral commercial and compliance contracts; live billing and Shopify submission remain external gates.**

## Official platform check

Payment-provider webhook delivery must be authenticated against the exact raw body, handled idempotently, and tolerant of retries and event reordering. The implementation stores provider event IDs and effective timestamps, verifies signatures through an injected provider adapter, and recomputes subscription state rather than trusting arrival order. Shopify distribution requirements, mandatory privacy webhooks, listing assets, pricing disclosures, and scope review must be rechecked immediately before submission.

## Threat model

- forged or replayed billing webhooks;
- older events overwriting newer subscription state;
- granting entitlements before verified payment state;
- duplicate usage charging;
- blocking merchants from exporting data after cancellation;
- bypassing limits by concurrent reservations;
- hidden or unjustified Shopify scopes;
- incomplete privacy/data inventory;
- deletion requests that remove audit evidence prematurely or retain merchant content indefinitely;
- claiming app-review readiness without required owner/legal artifacts.

## Data additions

Plans, subscriptions, billing events, entitlement grants, usage ledger/reservations, consent records, data inventory, compliance requests, retention policies, and app-review checks. Provider secrets and raw payment credentials remain outside these tables.

## Tests

- webhook signature rejection and event deduplication;
- out-of-order subscription event handling;
- trial, active, past-due, cancelled, and expired entitlement behavior;
- generation/publish/team/catalog limits;
- concurrent usage reservation and idempotent settlement;
- read/export remain available after cancellation;
- consent versioning;
- privacy export, deletion, and retention eligibility;
- required scope justification and app-review checklist;
- no payment secrets in logs or persistence.

## External blockers

- Stripe or other production billing account and webhook secret;
- final legal entity, privacy policy, terms, refund policy, tax setup, and support contact;
- Shopify Partner app configuration, listing assets, pricing plans, and review submission;
- production mandatory privacy-webhook registration.

## Non-goals

- tax or legal advice;
- fabricated app approval;
- charging a real card during CI;
- preventing a cancelled merchant from reading/exporting their data;
- enabling paid features from an unsigned provider event.

## Exit gate

Phase 7 is complete under fixture-backed tests when verified billing events drive deterministic subscription state, every paid operation is entitlement-checked and metered idempotently, cancellation degrades safely, privacy requests are auditable, and the app-review readiness report truthfully separates code-complete checks from owner/provider actions.
