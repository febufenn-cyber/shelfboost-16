# Shelfboost Phase 2A — Read-only Shopify sync

Phase 2A replaces repeated CSV exports with a read-only, version-pinned Shopify Admin GraphQL synchronization layer.

## Safety boundary

- requests only catalog data;
- stores no access token in SQLite—only the environment-variable reference;
- never calls a Shopify mutation;
- rejects API-version fall-forward instead of silently accepting a different schema;
- records immutable raw response snapshots with SHA-256 digests;
- distinguishes full reconciliation from incremental refresh;
- never treats an incremental sync as proof that an unseen product was deleted;
- fails closed when the configured `facts` metafield connection is truncated.

## Live sync

```bash
export SHOPIFY_ACCESS_TOKEN='...'
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  sync --shop store-a.myshopify.com --mode full
```

Incremental syncs require an explicit timestamp:

```bash
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  sync --shop store-a.myshopify.com \
  --mode incremental --since 2026-07-01T00:00:00Z
```

## Synthetic demo

```bash
./phase2/run-demo.sh /tmp/shelfboost-phase2-demo
```

The fixture demo exercises product pagination, nested variant pagination, immutable snapshots, and reconciliation without network access or credentials.

## Scope intentionally deferred

- OAuth callback server and encrypted token vault;
- webhooks and deduplication;
- app-uninstall handling;
- Phase 1 fact-ledger bridge;
- direct Shopify writes.
