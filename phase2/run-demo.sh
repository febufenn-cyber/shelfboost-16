#!/usr/bin/env bash
set -euo pipefail
workspace="${1:-/tmp/shelfboost-phase2-demo}"
rm -rf "$workspace"
PYTHONPATH=phase2 python3 -m shelfboost_phase2 --workspace "$workspace" init
PYTHONPATH=phase2 python3 -m shelfboost_phase2 --workspace "$workspace" sync-fixture \
  --fixture-dir phase2/sample \
  --shop fixture-store.myshopify.com
PYTHONPATH=phase2 python3 -m shelfboost_phase2 --workspace "$workspace" export-phase1 \
  --shop fixture-store.myshopify.com \
  --output "$workspace/exports/phase1-catalog.csv"
PYTHONPATH=phase2 python3 -m shelfboost_phase2 --workspace "$workspace" status
