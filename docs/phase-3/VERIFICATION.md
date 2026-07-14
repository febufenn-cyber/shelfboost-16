# Phase 3C Verification — Rollback and audit closure

- Roadmap version: 1.0
- Starting `main`: `41b517eb3d19d15759b9f9a3cfa1a18d019354a3`
- Previous completed package: Phase 3B, merge `04677490182ba1e043cd1317d50535419faf67e6`
- Decision: **PROCEED with fixture-backed implementation; live merchant verification remains external.**

## Repository contracts inspected

- `phase3/shelfboost_phase3/db.py`
- `phase3/shelfboost_phase3/planning.py`
- `phase3/shelfboost_phase3/execution.py`
- `phase3/shelfboost_phase3/writer.py`
- `phase3/shelfboost_phase3/cli.py`
- Phase 2 mirror, shop state, and refresh-queue contracts

## Current external API verification

Shopify Admin GraphQL `2026-07` remains the current stable API version at implementation time. `productUpdate` requires `write_products`, returns `userErrors`, and does not provide a general mutation idempotency key. Rollback therefore reuses the Phase 3B single-attempt writer and performs a live read before every restoration attempt.

## Data migration

Add a `rollback_runs` table to the existing Phase 2/3 SQLite workspace. Existing publish batches, items, attempts, and snapshots remain unchanged. Migration is additive and idempotent.

## Threat model

- Rolling back a value later changed by a merchant or another app.
- Treating an initially `already_applied` item as Shelfboost-owned without mutation evidence.
- Blindly repeating an ambiguous rollback mutation.
- Restoring fields Shelfboost never changed.
- Omitting failed, uncertain, or conflicting events from the audit record.
- Leaking access tokens or secrets through audit artifacts.
- Updating the local mirror before live restoration is verified.

## Failure states

- shop inactive or uninstalled;
- dirty refresh queue;
- missing before/after snapshots;
- no evidence Shelfboost performed or may have performed the publish;
- live product missing;
- live changed fields no longer equal the Shelfboost-published values;
- Shopify `userErrors`;
- ambiguous transport or server outcome;
- returned fields fail verification;
- audit digest mismatch.

## Test plan

- deterministic rollback-plan reuse;
- successful selected-field rollback;
- later external edit blocks rollback;
- already-restored reconciliation without mutation;
- ambiguous mutation is reconciled through a later live read;
- item-level partial rollback;
- audit manifest verifies every artifact digest;
- secret-like keys are redacted;
- mirror updates only after verified restoration.

## Non-goals

- automatic performance-triggered rollback;
- whole-product replacement;
- price, variant, inventory, media, tag, status, or metafield writes;
- force-overwriting merchant changes;
- destructive execution against a real store during CI.

## Exit gate

Phase 3 closes when rollback is conflict-safe, resumable after ambiguous outcomes, selected-field-only, mirror-consistent after verification, and represented in a tamper-evident audit bundle under fixture-backed tests.
