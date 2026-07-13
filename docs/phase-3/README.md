# Phase 3 — Reversible selected-field publishing

## Goal

Publish only human-approved product description and SEO fields with live precondition checks, immutable snapshots, idempotent reconciliation, partial-failure recovery, and rollback.

## Increments

1. **3A — planning:** validate Phase 1 evidence against the current Phase 2 mirror and create immutable before snapshots.
2. **3B — execution:** read live state before each mutation, distinguish unchanged, already applied, and external conflict, execute `productUpdate` once, and verify the result.
3. **3C — rollback:** restore only products still matching the value Shelfboost published, verify restoration, and emit an audit report.

## Blind spots addressed

- approval may become stale before publication;
- a merchant or another app may modify the same field;
- a mutation response can fail after the server has applied a change;
- blindly repeating a write can overwrite later work;
- a partially successful batch needs item-level recovery;
- rollback is unsafe after an unrelated subsequent edit.

Phase 3 does not add autonomous approval, variant writes, prices, tags, statuses, media, or unrestricted product mutation.
