# Shelfboost Remaining Implementation Plan

**Roadmap version:** 1.0  
**Execution trigger:** `build`  
**Scope:** Complete the remaining work from Phase 3C through a production-ready Phase 9 launch foundation.  
**Authority:** This file is the default execution contract for future autonomous implementation runs. It must be read and verified against the current repository before code is changed.

## 1. Honest remaining count

The repository has completed:

- Phase 0 — discovery system;
- Phase 1 — human-reviewed concierge pilot;
- Phase 2 — read-only Shopify synchronization, webhook reconciliation, and Phase 1 bridge;
- Phase 3A — publish planning;
- Phase 3B — live-preconditioned selected-field execution.

Phase 3 is not closed until rollback and the final audit bundle are implemented.

Therefore, the remaining work is:

1. **Phase 3C — rollback and publishing audit closure**
2. **Phase 4 — production application, identity, tenancy, and secure Shopify installation**
3. **Phase 5 — merchant-facing catalog, review, approval, publishing, and team experience**
4. **Phase 6 — production AI, brand intelligence, evaluation, and cost controls**
5. **Phase 7 — billing, entitlements, privacy, compliance, and Shopify distribution readiness**
6. **Phase 8 — measurement, experimentation, recurring optimization, and retention**
7. **Phase 9 — production hardening, observability, launch controls, and operating readiness**

This is **seven remaining build packages**: one unfinished Phase 3 package plus six complete phases.

An optional post-v1 scale program—additional commerce platforms, enterprise SSO, global localization, and very large catalog infrastructure—is explicitly outside this roadmap and is not counted as another required phase.

## 2. Definition of product completion

Shelfboost reaches the end of this roadmap only when a merchant can safely:

1. install or connect the Shopify application;
2. synchronize a catalog without exposing raw credentials;
3. see a credible catalog diagnosis;
4. establish a governed brand profile and product-fact source;
5. generate controlled, evaluated drafts;
6. review and approve individual fields or batches;
7. publish only approved fields with live conflict checks;
8. roll back Shelfboost changes without overwriting later merchant work;
9. understand usage, billing, permissions, history, and measured outcomes;
10. operate through a production UI backed by monitored, recoverable infrastructure.

Completion does not mean every possible feature exists. It means the end-to-end trust and commercial loop works in production with clear limits.

## 3. Meaning of the command `build`

When the user says **`build`**, the implementing agent must:

1. fetch and inspect the latest `main` branch;
2. read this roadmap and the current phase documentation;
3. identify the first incomplete package in the phase queue;
4. create the mandatory pre-implementation verification record;
5. implement every remaining package sequentially without asking for approval between phases;
6. use a separate branch and pull request for each independently reviewable increment;
7. run the full repository test suite and all new phase-specific tests;
8. merge only after CI succeeds;
9. verify the resulting `main` commit SHA after every merge;
10. continue automatically to the next package;
11. finish with a phase-by-phase confirmation containing implementation commits, PRs, merge commits, test results, and the final `main` SHA.

The phrase `build` authorizes implementation and repository writes described by this roadmap. It does **not** authorize destructive use of a real merchant store, fabrication of credentials, bypassing provider approval, or pretending an external integration was verified when it was only fixture-tested.

## 4. Mandatory pre-implementation verification record

Before changing code for each numbered phase, create or update:

```text
docs/phase-N/VERIFICATION.md
```

For Phase 3C, use `docs/phase-3/VERIFICATION.md`.

The record must include:

- roadmap version used;
- current `main` SHA;
- previous phase merge SHA and status;
- repository modules and schemas that will be touched;
- current official documentation checked for unstable external APIs;
- required scopes, permissions, webhooks, secrets, and environment variables;
- data migrations and backward-compatibility risks;
- threat model and abuse cases;
- failure and partial-failure states;
- fixtures, unit tests, contract tests, integration tests, and smoke tests to add;
- rollback or recovery method for the implementation itself;
- explicit non-goals;
- exit gates;
- final proceed/block decision.

The verification record is not ceremonial. If repository reality conflicts with this roadmap, the agent must update this roadmap or the phase plan in the same PR and explain the change.

## 5. Autonomous Git and merge contract

Every implementation increment must follow this sequence:

```text
latest main
→ agent/phase-X-description branch
→ implementation and tests
→ intentional commit
→ pull request to main
→ CI inspection
→ fixes on the same branch when needed
→ normal merge commit
→ verify merged PR and new main SHA
→ continue to the next increment
```

Rules:

- Branch from the latest merged `main`, never from a stale phase branch.
- Prefer one intentional implementation commit per increment. Correctness is more important than artificial one-commit purity; CI fixes must receive explicit follow-up commits.
- Do not force-push `main`.
- Do not merge red CI.
- Do not silently skip failing or unavailable tests.
- Use normal merge commits so phase boundaries remain visible.
- Preserve all earlier tests unless a documented contract intentionally changes.
- After every merge, resolve `main` again rather than assuming the merge SHA.
- A GitHub connector merge is the repository equivalent of commit, push, and merge when a local `gh` or Git remote is unavailable.

## 6. Hard blockers and autonomous behavior

The agent should not stop for ordinary implementation decisions. It should make the safest reasonable choice, document it, and continue.

A phase may stop only for a genuine hard blocker such as:

- a required secret or live merchant credential is unavailable;
- an external provider requires manual account approval;
- a production domain, signing key, billing account, or legal text requires owner action;
- a destructive migration cannot be safely tested or reversed;
- current official documentation materially invalidates the planned architecture;
- a security or compliance issue cannot be responsibly resolved in code alone.

When a hard blocker occurs:

1. complete all fixture-backed and non-destructive work possible;
2. merge only code that is safe and truthfully tested;
3. record the exact external verification still pending;
4. do not claim the phase fully verified;
5. continue to later phases only when they do not depend on the unresolved blocker.

## 7. Phase queue

| Package | Status at roadmap creation | Primary outcome |
|---|---|---|
| Phase 3C | Pending | Conflict-safe rollback and immutable publishing audit bundle |
| Phase 4 | Pending | Secure installed multi-tenant production application foundation |
| Phase 5 | Pending | Merchant-facing end-to-end operating experience |
| Phase 6 | Pending | Evaluated, governed, cost-controlled AI generation system |
| Phase 7 | Pending | Commercial entitlements, privacy, compliance, and app distribution readiness |
| Phase 8 | Pending | Measured outcomes and recurring optimization loop |
| Phase 9 | Pending | Production hardening, controlled launch, and operational readiness |

---

# Phase 3C — Rollback and audit closure

## Objective

Finish Phase 3 by restoring only fields that still contain the exact value Shelfboost previously published, verifying restoration, updating the mirror, and producing a complete tamper-evident audit package.

## Required increments

### 3C.1 Rollback planning

- Select a completed or partially completed publish batch.
- Include only items in verified success states.
- Read the immutable before and published-after snapshots.
- Build a deterministic rollback plan and idempotency key.
- Require active shop state and a clean refresh queue.
- Refuse rollback for uncertain, failed, conflicted, or never-published items.

### 3C.2 Conflict-safe rollback execution

- Read the live product immediately before rollback.
- Restore only the fields changed by Shelfboost.
- Require every rollback field to equal Shelfboost’s published value.
- Treat any later merchant or app edit as an external conflict.
- Send one mutation attempt; never blindly retry an ambiguous response.
- Reconcile ambiguous outcomes by a fresh live read.
- Verify returned and live values before marking rolled back.
- Update the Phase 2 mirror only after verification.

### 3C.3 Final audit bundle

Produce a self-contained audit directory containing:

- source bridge manifest and digest;
- Phase 1 approved changes and digest;
- publish plan and deterministic key;
- planned-before, live-before, published-after, rollback-before, and rollback-after snapshots;
- mutation requests and responses with secrets removed;
- Shopify `userErrors` and ambiguous outcomes;
- item and batch state transitions;
- final live verification report;
- SHA-256 manifest for every audit artifact.

## Tests

- successful rollback;
- selected-field-only restoration;
- external edit blocks rollback;
- already-rolled-back reconciliation;
- uncertain rollback response reconciliation;
- Shopify `userErrors`;
- partial batch rollback;
- audit manifest digest verification;
- mirror update only after verified restoration;
- no secret values in artifacts.

## Exit gate

Phase 3 is complete only when publish and rollback are both conflict-safe, resumable, auditable, and covered by fixture-backed tests.

## Non-goals

- automatic rollback based on performance;
- whole-product replacement;
- price, variant, inventory, media, tag, status, or metafield changes;
- force-overwriting a later merchant edit.

---

# Phase 4 — Production application, identity, and tenancy

## Objective

Move from local workspaces and operator-driven commands to a securely installed, multi-tenant Shopify application foundation without weakening the contracts proven in Phases 1–3.

## Required design decision

Before implementation, create an architecture decision record comparing the current Python/SQLite components with the candidate production stack—Cloudflare Workers or another service runtime, Hono or equivalent API layer, Supabase/Postgres or equivalent database, object storage, queues, and secret management.

Do not rewrite working domain logic merely for stack fashion. Preserve behavior through contract tests and migrate incrementally.

## Required increments

### 4A Production application shell

- Environment and configuration model.
- Local, test, staging, and production separation.
- Health, readiness, and version endpoints.
- Structured logging and request correlation.
- Database migration framework.

### 4B Shopify installation and OAuth

- Verify the current official Shopify authorization flow at implementation time.
- Signed state or nonce validation.
- Canonical shop-domain validation.
- Minimal read/write scopes justified by existing features.
- Secure callback handling.
- Online/offline token decision documented.
- Reauthorization and revoked-token handling.
- No token in logs, client state, URL query history, or repository.

### 4C Encrypted token and secret storage

- Envelope encryption or managed secret storage.
- Key rotation strategy.
- Tenant-specific credential isolation.
- Token access audit events.
- App-uninstall revocation and erasure workflow.

### 4D Multi-tenant data model

- Organizations, shops, users, memberships, roles, and sessions.
- Tenant ID on every merchant-owned record.
- Database-level isolation policies where supported.
- Migration of local Phase 1–3 domain records into tenant-scoped tables.
- No cross-tenant identifiers exposed through predictable URLs.

### 4E Deployed webhook and job infrastructure

- Public HTTPS webhook endpoint.
- Raw-body HMAC verification before parsing.
- Fast acknowledgement and durable queueing.
- Deduplication and replay handling.
- Dead-letter path and operator replay controls.
- Scheduled full reconciliation.
- Worker concurrency and Shopify rate-limit controls.

### 4F Privacy lifecycle

- App uninstall.
- Shop data deletion.
- Customer data request/deletion hooks if required by the current Shopify app model.
- Configurable retention and purge jobs.
- Exportable audit history without retaining unnecessary catalog payloads indefinitely.

## Tests

- OAuth state forgery rejection;
- cross-tenant access denial;
- encrypted token round trip and rotation;
- webhook replay and duplicate delivery;
- job retry and dead-letter behavior;
- uninstall and deletion flows;
- migration from representative Phase 2/3 fixtures;
- full end-to-end staging installation where credentials are available.

## Exit gate

A test merchant can install the application, synchronize through deployed infrastructure, survive webhook retries, and uninstall with tokens and tenant data handled according to the documented retention policy.

## Non-goals

- polished customer UI;
- autonomous generation;
- billing;
- public app-store launch.

---

# Phase 5 — Merchant-facing product experience

## Objective

Deliver a coherent embedded or web application that exposes the proven catalog workflow to merchants and teams without requiring command-line operation.

## Required increments

### 5A Onboarding and connection

- Installation completion and scope explanation.
- Read-only-first trust messaging where possible.
- Initial synchronization progress and recoverable errors.
- Store and user context.
- Guided first audit.

### 5B Catalog health dashboard

- Catalog-level score with methodology and limitations.
- Finding counts by severity and category.
- Product queues for missing, duplicate, risky, blocked, and high-priority listings.
- Search, filters, sorting, pagination, and large-catalog virtualization.
- Clear distinction between deterministic findings and model judgments.

### 5C Brand and fact governance

- Structured brand profile editor.
- Version history and activation.
- Product-fact source visibility.
- Missing-fact requests and blocked generation states.
- Category policies and prohibited claims.

### 5D Generation and review workspace

- Small-batch generation first.
- Original versus proposed field comparison.
- Facts used, warnings, abstentions, model/template version, and validation status.
- Field-level approve, edit, reject, defer, and regenerate.
- Revalidation of edits.
- Batch filtering by risk, confidence, category, and decision state.

### 5E Team workflow

- Roles such as owner, administrator, editor, reviewer, and viewer.
- Optional two-person approval for publishing.
- Comments and assignment.
- Immutable decision history.
- Session and permission checks on every mutation.

### 5F Publish and rollback experience

- Publish-plan preview.
- Changed-field summary.
- Stale-product and conflict display.
- Partial batch progress.
- Uncertain outcome reconciliation.
- Rollback eligibility and conflict explanation.
- Downloadable audit bundle.

### 5G Product quality

- Responsive desktop and tablet experience.
- Accessibility review.
- Keyboard operation for high-volume review.
- Performance budgets.
- Empty, loading, error, offline, and stale states.
- Analytics events that do not leak catalog content.

## Tests

- component and route tests;
- role and permission tests;
- accessibility checks;
- end-to-end onboarding, audit, review, publish, conflict, and rollback flows;
- large-catalog performance fixtures;
- browser and responsive smoke coverage.

## Exit gate

A qualified merchant can complete the full controlled workflow without operator CLI assistance, while every consequential action remains explicit and auditable.

## Non-goals

- automatic bulk approval;
- unrestricted auto-publish;
- mobile-native applications;
- every ecommerce platform.

---

# Phase 6 — Production AI and brand intelligence

## Objective

Replace the conservative demonstration provider with an evaluated, provider-independent generation system that remains subordinate to facts, policies, validation, and human approval.

## Required increments

### 6A Provider-independent structured generation contract

Every provider adapter must return:

- field value;
- exact fact IDs used;
- abstentions;
- warnings;
- model and provider version;
- prompt/template version;
- token and cost metadata;
- deterministic request correlation ID.

Adapters must not write to Shopify or bypass validation.

### 6B Evaluation corpus and harness

- Synthetic and permissioned anonymized product fixtures.
- Category coverage.
- Factual preservation scoring.
- Claim-safety scoring.
- Brand alignment rubric.
- Product specificity and duplicate-output checks.
- Merchant edit-distance and acceptance metrics.
- Regression thresholds blocking deployment.

### 6C Model routing and cost controls

- Low-cost model for routine structured products.
- Stronger model only for complex or low-confidence cases.
- Per-field and per-batch budgets.
- Rate limits and concurrency controls.
- Cached deterministic context.
- Usage metering without storing unnecessary sensitive prompts.

### 6D Brand intelligence

- Hybrid profile extraction from approved public and merchant-provided examples.
- Merchant confirmation before activation.
- Versioned brand rules.
- Product-, category-, and brand-level learning scopes.
- Repeated edit pattern detection.
- No automatic promotion of one correction into a global rule.

### 6E Category and claim policies

- Required facts by category.
- Prohibited inference rules.
- Regulated-category exclusions or specialist policies.
- Claim evidence registry.
- Human escalation for ambiguity.
- Provider output cannot lower a deterministic risk classification.

### 6F Production validation

- Claim extraction against the fact ledger.
- Supported, ambiguous, unsupported, and contradicted classifications.
- Duplicate and near-duplicate detection across batches and catalog history.
- HTML and format safety.
- Prompt-injection resistance for merchant catalog content.

## Tests

- provider contract tests;
- deterministic replay fixtures;
- evaluation threshold CI;
- prompt injection and malicious catalog strings;
- cost budget enforcement;
- provider outage and fallback behavior;
- model-version regression tests;
- no-generation and abstention paths.

## Exit gate

At least one production provider passes the fixed evaluation thresholds, operates within cost limits, and improves acceptance over the deterministic baseline without weakening fact or claim safety.

## Non-goals

- model-generated product facts;
- invisible autonomous publishing;
- training on merchant data without explicit policy and consent;
- claiming a proprietary foundation model moat.

---

# Phase 7 — Billing, entitlements, compliance, and distribution

## Objective

Make Shelfboost commercially operable and ready for the intended Shopify distribution model.

## Required decision

At implementation time, verify current official Shopify requirements for app billing and app-store distribution. Decide whether Shopify Billing, Stripe, or a hybrid is permissible and appropriate. Do not assume the original blueprint’s Stripe choice overrides current platform policy.

## Required increments

### 7A Product plans and entitlements

- Catalog-size and usage dimensions.
- Store and agency account models.
- Feature entitlements.
- Trial and pilot conversion.
- Upgrade, downgrade, cancellation, grace period, and reactivation.

### 7B Usage metering

- Audited products.
- Generated fields.
- Approved fields.
- Published fields.
- Model cost.
- Seat and store counts.
- Idempotent meter events and reconciliation.

### 7C Billing integration

- Signed checkout or billing approval.
- Subscription state webhooks.
- Failed-payment handling.
- Cancellation on uninstall where required.
- Invoice/receipt references.
- No entitlement solely from client-side state.

### 7D Privacy and legal readiness

- Privacy policy.
- Terms of service.
- Data-processing and subprocessors disclosure.
- Retention and deletion policy.
- Security contact and vulnerability reporting path.
- Consent and merchant-data usage boundaries.
- Required Shopify privacy webhooks or endpoints verified against current documentation.

### 7E Application review readiness

- App listing content and screenshots.
- Test credentials or review instructions.
- Scope justification.
- Billing test path.
- Uninstall and data deletion demonstration.
- Error-free onboarding.
- Support and documentation links.

### 7F Agency commercial workflow

- Multiple client stores.
- Client-specific billing and brand profiles.
- Usage allocation.
- Agency role boundaries.
- Export and reporting controls.

## Tests

- entitlement enforcement server-side;
- duplicate billing webhook handling;
- upgrade/downgrade transitions;
- cancellation and uninstall;
- usage reconciliation;
- privacy deletion workflows;
- app-review checklist automation where possible.

## Exit gate

A test merchant can activate a permitted plan, use only entitled features, see accurate usage, cancel cleanly, and complete the privacy lifecycle required for distribution.

## Non-goals

- complicated enterprise contracting;
- unsupported tax promises;
- unlimited generation without cost controls.

---

# Phase 8 — Measurement, experimentation, and retention

## Objective

Turn Shelfboost from a one-time content tool into a measurable recurring catalog-optimization system.

## Required increments

### 8A Internal event model

Track privacy-conscious events for:

- synchronization and audit completion;
- findings discovered and resolved;
- generation, validation, approval, editing, rejection, publication, conflict, and rollback;
- time spent in review;
- recurring catalog changes;
- usage and cost.

Events must carry tenant context but avoid raw product content unless strictly necessary.

### 8B External performance integrations

- Verify and implement the most appropriate current search and commerce analytics integrations.
- Search impressions, clicks, and click-through rate where authorized.
- Product-page traffic, add-to-cart, conversion, and revenue where data and consent permit.
- Clear distinction between correlation and causation.

### 8C Change attribution ledger

- Exact products and fields changed.
- Publish and rollback timestamps.
- Baseline and observation windows.
- Comparable untreated products where possible.
- Data-quality and sample-size warnings.

### 8D Experimentation

- Staged rollouts.
- Holdout groups.
- Category-level comparisons.
- Guardrails preventing simultaneous conflicting experiments.
- Statistical method documented; no misleading uplift claims.

### 8E Recurring optimization loop

- New-product detection.
- Content deterioration and duplication alerts.
- Missing-fact alerts.
- Seasonal review queues.
- Keyword or search-opportunity refresh where supported.
- Merchant-controlled schedules.

### 8F Outcome reporting

- Operational improvements such as completeness and review time.
- Search and conversion outcomes with confidence and caveats.
- Product and category drill-down.
- Exportable reports for agencies.
- No fabricated or over-attributed revenue.

## Tests

- event idempotency;
- attribution-window calculations;
- rollback exclusion from active treatment;
- missing analytics data;
- permission revocation;
- experiment assignment stability;
- misleading small-sample suppression;
- scheduled alert deduplication.

## Exit gate

Shelfboost can demonstrate recurring operational value and, where data permits, defensible outcome evidence without overstating causality.

## Non-goals

- guaranteed SEO ranking;
- automatic performance-based rollback without merchant approval;
- selling merchant analytics data.

---

# Phase 9 — Production hardening and controlled launch

## Objective

Make the system secure, observable, recoverable, supportable, and ready for a controlled real-customer launch.

## Required increments

### 9A Security hardening

- Threat model review.
- Dependency and secret scanning.
- Static analysis.
- Authorization test matrix.
- Rate limiting and abuse controls.
- Content-security and browser protections.
- Secure headers and cookie policy.
- Least-privilege infrastructure identities.
- Penetration-testing plan and remediation tracking.

### 9B Reliability and scale

- Queue backpressure.
- Shopify rate-limit budgeting.
- Database indexes and query budgets.
- Large-catalog load tests.
- Provider outage behavior.
- Retry, timeout, circuit-breaker, and dead-letter policies.
- Idempotent scheduled work.

### 9C Observability

- Structured logs.
- Metrics and traces.
- Correlation across webhook, sync, generation, review, publish, rollback, and billing.
- SLOs and alert thresholds.
- Secret and catalog-content redaction.
- Cost and usage anomaly alerts.

### 9D Backup and disaster recovery

- Automated database backups.
- Point-in-time recovery where supported.
- Object and audit-artifact retention.
- Restore drills.
- Key-loss and token-rotation procedures.
- Recovery time and recovery point objectives.

### 9E Deployment safety

- Staging parity.
- Migration dry runs.
- Feature flags.
- Canary release.
- Rollback of application releases.
- Backward-compatible job and webhook processing.
- No destructive migration without backup and tested recovery.

### 9F Operations and support

- Incident response runbook.
- Severity definitions.
- Merchant communication templates.
- Support triage and diagnostic bundle.
- Data deletion and security request handling.
- On-call ownership and escalation.

### 9G Controlled launch

- Internal fixture environment.
- One test store.
- Small design-partner cohort.
- Explicit launch gates for factual incidents, publish conflicts, rollback success, latency, support load, and gross margin.
- Kill switch for generation and publishing independently.
- Post-launch review and decision record.

## Tests and exercises

- load and soak tests;
- restore drill;
- token rotation drill;
- provider outage simulation;
- queue poison-message simulation;
- failed migration recovery;
- webhook replay storm;
- cross-tenant attack tests;
- publish and rollback incident game day;
- complete staging installation-to-deletion journey.

## Exit gate

Shelfboost may be called production-ready only when the controlled launch gates pass, rollback is proven, backups are restored successfully in a drill, alerts are actionable, and no critical security finding remains open.

## Non-goals

- instant global scale;
- every language and jurisdiction;
- every ecommerce platform;
- enterprise features not required by validated customers.

---

# 8. Phase completion record

After each phase, update this table in the same final merge or a dedicated roadmap-status PR.

| Package | Verification file | Implementation PRs | Merge SHAs | CI | External verification | Status |
|---|---|---|---|---|---|---|
| Phase 3C | Pending | — | — | — | — | Pending |
| Phase 4 | Pending | — | — | — | — | Pending |
| Phase 5 | Pending | — | — | — | — | Pending |
| Phase 6 | Pending | — | — | — | — | Pending |
| Phase 7 | Pending | — | — | — | — | Pending |
| Phase 8 | Pending | — | — | — | — | Pending |
| Phase 9 | Pending | — | — | — | — | Pending |

## 9. Required final confirmation after `build`

The final response must report:

- phases and increments completed;
- anything deliberately deferred;
- every implementation commit SHA;
- every pull request number and link;
- every merge commit SHA;
- CI workflow conclusions;
- external tests completed versus fixture-only tests;
- migrations performed;
- security or compliance blockers;
- final verified `main` SHA;
- statement that `main` was updated and no unmerged implementation PR remains.

Do not claim “done” when the repository is merged but a required live integration remains unverified. Use precise statuses such as **implemented and fixture-verified**, **staging-verified**, or **production-verified**.
