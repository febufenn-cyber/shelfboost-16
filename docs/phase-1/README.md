# Shelfboost Phase 1 — Concierge Catalog Optimization

## 1. Charter

Phase 1 turns the Phase 0 discovery method into a repeatable, paid, human-supervised workflow that converts a real Shopify CSV into approved, traceable, Shopify-compatible changes.

It is not a production Shopify application. It is the smallest operational system that can prove catalog intake, fact governance, controlled drafting, merchant review, safe export, repeat demand, and viable unit economics.

```text
private catalog intake
→ normalized products and variants
→ approved product-fact ledger
→ deterministic audit and prioritization
→ versioned brand profile
→ small pilot batch
→ controlled field drafts
→ validation and duplicate detection
→ internal/merchant review
→ approved-only export
→ commercial continuation decision
```

### Trust boundary

- no Shopify OAuth or live-store writes;
- no autonomous approval;
- no draft may be exported unless validation passes and a reviewer approves or edits it;
- missing facts create blocking, not invention;
- real merchant workspaces remain private and outside the repository;
- the system makes no ranking, conversion, or revenue claim.

### Explicit non-goals

- pretending the deterministic provider is market-ready creative copy;
- adding an LLM before the traceability contract is proven;
- production authentication, tenancy, billing, or cloud storage;
- direct publishing;
- regulated-claims support;
- automated ROI attribution.

## 2. Architecture

Phase 1 uses Python's standard library and SQLite to minimize infrastructure while preserving a realistic domain model.

### Catalog importer

- reads UTF-8 Shopify exports;
- stores every original row and the original header order;
- hashes the source file;
- groups rows by handle without discarding variants;
- creates a representative product record.

### Fact ledger

The ledger stores structural context separately and admits copy facts only from explicit merchant columns beginning `Fact:` or `Metafield: facts.`. Existing marketing prose is preserved but is not automatically trusted.

### Audit and selection

Mechanical findings create an operational priority score. Eligibility is separate: a product may have severe problems but remain blocked because identity or approved facts are missing.

### Brand profile

Profiles are JSON, validated, versioned, and activated explicitly. Drafts record the profile ID, provider, category template, and validation result.

### Draft provider

`deterministic-safe-v1` creates conservative descriptions and metadata from exact approved fact values. It exists to exercise the complete workflow safely; it is not the final creative-quality solution.

### Validator

Validation checks empty output, prohibited terms, risky claim language, HTML allowlist, SEO lengths, missing required facts, fact-rendering warnings, reviewer edits, and duplicate batch output.

### Review and export

The review pack shows original and proposed values, fact sources, warnings, and validation. Export reconstructs the original Shopify CSV, changes only approved fields on the primary row, preserves variants and untouched fields, and writes a JSON change log.

## 3. Data contract

### Recognised Shopify fields

`Handle`, `Title`, `Body (HTML)`, `Vendor`, `Type`/`Product Type`, `Tags`, `Status`, `SEO Title`, `SEO Description`, `Image Alt Text`, variant SKU, and option fields. Every remaining original column is preserved through raw-row storage.

### Approved fact columns

```text
Fact: Material
Fact: Dimensions
Fact: Care
```

or:

```text
Metafield: facts.material
Metafield: facts.dimensions
```

Do not place uncertain claims in approved fact columns.

### Brand profile required keys

- `brand_name`
- `tone` array
- `prohibited_terms` array
- `regional_language`

### Review decisions

- `approved`
- `edited` — requires non-empty edited value and revalidation
- `rejected`
- `deferred`

Blocked drafts cannot be approved or edited into acceptance.

### Mutable export fields

- `Body (HTML)`
- `SEO Title`
- `SEO Description`

All other original values are preserved.

## 4. Fact and generation policy

A fluent sentence is not evidence. Approved facts must originate from a governed source. Structural context is useful for routing but does not automatically authorize a marketing claim. Missing or inferred information must be blocked, warned, or requested from the merchant.

Any later AI provider must return structured output containing field value, fact IDs used, abstentions, warnings, model/provider version, and prompt/template version. It must pass the same validator and review gates.

Initial category templates cover apparel, home decor, jewelry, and general goods. Templates define required or recommended facts and prohibited inferences; they never create values.

Identical non-trivial output within a batch is blocked. Near-duplicate semantic detection remains required before high-volume generation.

## 5. Review and export policy

Approval is field-level. A merchant may accept metadata while rejecting a description.

Required review context:

- product handle and title;
- original and proposed values;
- validation status;
- exact facts and source fields;
- warnings and errors.

Export rules:

- blank, rejected, and deferred items remain unchanged;
- blocked drafts cannot be approved;
- edited values are revalidated;
- product-level changes affect only the primary Shopify row;
- variant rows and identifiers are preserved;
- every export writes a change log;
- importing the resulting CSV into Shopify remains a separate merchant-controlled action.

Before merchant import, inspect the change log, verify row/handle counts, sample edited overrides, verify identifiers, and retain the original CSV as the rollback source.

## 6. Pilot runbook

### Initialize

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store init
```

### Import

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store \
  import-catalog /private/products.csv
```

### Activate brand profile

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store \
  brand /private/brand-profile.json
```

### Select small pilot batch

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store \
  select-batch --name "Pilot 001" --limit 10
```

### Generate and review

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store generate
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store review-pack
```

Open `review.html`, complete `review-decisions.csv`, and retain review notes.

### Apply decisions and export

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store \
  apply-decisions /private/review-decisions.csv
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/store \
  export /private/approved-shopify.csv
```

Review the companion `.changes.json` before merchant use.

Record acceptance codes, review time, factual incidents, edits, operational cost, next-batch request, and payment outcome in the research trackers.

## 7. Phase 1 exit decision

Choose `ADVANCE_TO_PHASE_2`, `CONTINUE_PHASE_1`, `PIVOT`, or `PAUSE` only after reviewing real evidence.

| Gate | Target | Initial actual |
|---|---:|---:|
| Paid or binding pilots completed | ≥3 | 0 |
| Customers requesting/purchasing second batch | ≥2 | 0 |
| Fields accepted unchanged/light edit | ≥70% | — |
| Serious unsupported claims delivered | 0 | — |
| Median review time below prior workflow | Yes | — |
| Repeatable workflow across catalogs | Yes | — |
| Viable cost per approved field/product | Yes | — |
| Repeated demand for easier recurring sync | Yes | — |

The strongest next permission must be earned: continue CSV-only, Shopify read-only OAuth, scheduled read-only sync, or another bounded capability. Phase 1 does not automatically justify autonomous publishing.
