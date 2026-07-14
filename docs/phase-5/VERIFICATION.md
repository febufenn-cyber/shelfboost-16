# Phase 5 Verification — Merchant-facing product experience

- Roadmap version: 1.0
- Starting `main`: `af46ed4ce42abaa7a1ea2fc7df90b9ac2bbfeeb0`
- Previous package: Phase 4 merged and CI-green
- Decision: **PROCEED with tenant-aware server-rendered experience contracts; deployed embedded UI remains external.**

## Existing contracts preserved

- Phase 4 tenant roles and shop access checks;
- Phase 2 catalog provenance and findings separation;
- Phase 1 fact, brand, draft, validation, and review concepts;
- Phase 3 publish planning, execution, rollback, and audit history.

## Experience threat model

- showing one tenant another tenant's catalog or review records;
- allowing viewers to edit or publish;
- hiding warnings or fact-source uncertainty;
- approving fields in bulk without visibility into blocked items;
- publishing unapproved or stale fields;
- losing reviewer and publisher attribution;
- making destructive actions indistinguishable from drafts;
- inaccessible controls or status conveyed only through color;
- large-catalog pages loading unbounded result sets.

## Data additions

Tenant-scoped onboarding state, catalog cards/findings, brand-profile versions, review batches, field decisions, publish requests, and activity events. All records bind to organization and shop.

## Tests

- onboarding state progression and recoverable sync errors;
- tenant-scoped dashboard filters, sorting, search, and pagination;
- deterministic versus model finding labels;
- brand profile version activation and fact-source visibility;
- small-batch review enforcement;
- blocked warnings cannot be approved silently;
- per-field approve/edit/reject/defer decisions;
- viewer/editor/admin/owner role enforcement;
- optional two-person approval for high-risk batches;
- publish request contains approved fields only;
- activity history attribution;
- semantic HTML with labels, headings, tables, and non-color status text.

## External blockers

- deployed embedded-app shell and Shopify session-token authentication;
- visual browser testing against a real store;
- production CDN/assets and analytics consent.

## Non-goals

- production AI provider;
- billing;
- outcome attribution;
- automatic approval;
- hiding external verification limitations.

## Exit gate

Phase 5 is complete under fixture-backed tests when a tenant user can progress from onboarding through catalog diagnosis, brand/fact governance, field-level review, role-based publish request, and activity history without CLI access or trust-boundary bypass.
