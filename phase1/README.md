# Shelfboost Phase 1

A private, local concierge-pilot system for turning a Shopify CSV into audited, fact-traceable, reviewer-approved changes.

## Quick demo

```bash
./phase1/run-demo.sh
```

The synthetic demo imports products, activates a brand profile, selects a priority batch, generates controlled drafts, blocks duplicate output, and writes a review pack. It never auto-approves or exports changes.

## Commands

```text
init
import-catalog CSV
brand PROFILE_JSON
select-batch --name NAME --limit N
generate
review-pack
apply-decisions DECISIONS_CSV
export OUTPUT_CSV
status
```

Run with:

```bash
PYTHONPATH=phase1 python3 -m shelfboost_phase1 --workspace /private/workspace COMMAND
```

## Security

The workspace may contain merchant catalog data and must be stored outside the repository. The root `.gitignore` excludes common workspace and database paths, but operators remain responsible for access control and retention.

## Generator warning

The included deterministic provider is intentionally conservative. It demonstrates safety, traceability, review, and export mechanics. It is not evidence that creative AI generation quality has been validated.
