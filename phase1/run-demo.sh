#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${1:-/tmp/shelfboost-phase1-demo}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$WORKSPACE"

PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" init
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" import-catalog "$ROOT/sample/shopify-products.csv"
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" brand "$ROOT/sample/brand-profile.json"
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" select-batch --name "Synthetic Phase 1 pilot" --limit 4
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" generate --template-dir "$ROOT/category_templates"
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" review-pack
PYTHONPATH="$ROOT" python3 -m shelfboost_phase1 --workspace "$WORKSPACE" status

echo "Review pack: $WORKSPACE/artifacts/batch-1-review/review.html"
echo "No decisions were auto-approved and no Shopify export was written."
