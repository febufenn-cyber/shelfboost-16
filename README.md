# Shelfboost

> Find weak Shopify listings, prepare fact-traceable improvements, require human approval, publish selected fields with live conflict checks, and preserve a verified path back.

Shelfboost has completed the **Phase 0–9 fixture-backed software foundation**. The repository contains the complete trust loop from discovery and catalog diagnosis through governed AI, human review, reversible publishing, commercial controls, measurement, recovery, and controlled-launch gates.

**Code-complete is not the same as publicly production-ready.** Live deployment, Shopify installation, managed key storage, real AI/billing/analytics providers, restore drills, capacity tests, security review, legal artifacts, and Shopify approval remain external launch gates.

## Phase status

| Phase | Repository status | Outcome |
|---|---|---|
| 0 | Implemented | Evidence system, hypotheses, audits, pricing and kill gates |
| 1 | Implemented | Human-reviewed fact-safe catalog pilot workflow |
| 2 | Implemented | Read-only Shopify mirror, webhooks and Phase 1 bridge |
| 3 | Implemented | Conflict-safe selected-field publish, rollback and audit bundle |
| 4 | Implemented contracts | Tenant identity, installation state, encrypted-token interface, durable jobs and privacy lifecycle |
| 5 | Implemented contracts | Merchant onboarding, dashboard, brand/fact governance, review, approvals and activity history |
| 6 | Implemented contracts | Governed AI routing, budgets, validation, evaluations and confirmed feedback rules |
| 7 | Implemented contracts | Billing integrity, entitlements, usage metering, privacy/compliance and review readiness |
| 8 | Implemented contracts | Source-attributed measurement, controlled experiments and recurring review cycles |
| 9 | Implemented contracts | Security, resilience, backups, incidents, kill switches and launch gates |

“Implemented contracts” means behavior is covered by deterministic repository tests. It does not claim that unavailable external services were deployed or approved.

## End-to-end trust loop

```text
Shopify installation and tenant context
→ read-only catalog synchronization
→ authenticated webhook reconciliation
→ catalog audit and priority queues
→ governed facts and brand profile
→ evaluated AI drafts
→ field-level human review
→ entitlement and usage checks
→ immutable publish plan
→ live conflict read
→ selected-field mutation
→ verification and history
→ conflict-safe rollback
→ source-attributed measurement
→ recurring review cycle
→ controlled rollout, SLOs, incidents and recovery
```

## Hard safety boundaries

- No autonomous approval or direct model-to-publish path.
- No force overwrite after a merchant or another app edits a field.
- Only approved product description and SEO fields enter the Phase 3 write path.
- Ambiguous mutations are reconciled by a live read before another attempt.
- Billing access cannot be granted by unsigned events.
- Cancellation never removes read, export or privacy access.
- Before/after metrics remain observational; experiment estimates require declared controls and sample gates.
- Feature kill switches override rollout immediately.
- Backup existence is insufficient; restore verification is required.
- Public launch is blocked until every required external gate has evidence.
- No real merchant data or credentials belong in this public repository.

## Validate the complete foundation

```bash
make test
make phase1-demo
make phase2-demo
```

The demos and CI use synthetic fixtures. They do not connect to or modify a live merchant store.

## Production launch gates still required

- Deployed Shopify installation/token flow on a development store
- Managed KMS token encryption and rotation
- Deployed webhook retry/dead-letter exercise
- Real AI provider evaluation, latency, cost and data-processing decision
- Billing sandbox lifecycle and signed webhooks
- Analytics connector validation
- Managed backup and restore drill
- Capacity/load test
- Dependency/runtime vulnerability scanning
- Appropriate independent security review
- Privacy policy, terms, support and incident contacts
- Shopify app review and approval

## Documentation

- [`docs/REMAINING_IMPLEMENTATION_PLAN.md`](docs/REMAINING_IMPLEMENTATION_PLAN.md)
- [`docs/BUILD_COMPLETION_REPORT.md`](docs/BUILD_COMPLETION_REPORT.md)
- [`docs/phase-3/README.md`](docs/phase-3/README.md)
- [`docs/phase-4/ADR-001-production-boundary.md`](docs/phase-4/ADR-001-production-boundary.md)
- [`docs/phase-9/OPERATIONS_RUNBOOK.md`](docs/phase-9/OPERATIONS_RUNBOOK.md)
- Phase package READMEs under `phase1/` through `phase9/`
