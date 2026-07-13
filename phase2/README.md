# Shelfboost Phase 2 — Read-only Shopify sync and reconciliation

Phase 2 replaces repeated CSV exports with a read-only, version-pinned Shopify Admin GraphQL synchronization layer and authenticated webhook reconciliation.

## Phase 2A — Catalog synchronization

- Shopify Admin GraphQL API pinned to `2026-07`;
- cursor-based product pagination;
- separate completion of truncated variant connections;
- bounded retry for rate limits and server failures;
- API-version fall-forward rejection;
- immutable response snapshots with SHA-256 digests;
- full-sync deletion reconciliation;
- incremental syncs that never infer deletion from absence.

## Phase 2B — Webhook security and refresh

- verifies `X-Shopify-Hmac-SHA256` against the exact raw request body before parsing JSON;
- validates the `*.myshopify.com` shop domain and requires a registered shop;
- deduplicates deliveries with `X-Shopify-Webhook-Id`;
- correlates merchant actions with `X-Shopify-Event-Id`;
- queues `products/create` and `products/update` for read-only product refresh;
- soft-deletes products on `products/delete`;
- disables the shop and clears queued work on `app/uninstalled`;
- coalesces multiple pending deliveries for the same product into one API refresh;
- stores only the token environment-variable reference, never the token value.

## Live full sync

```bash
export SHOPIFY_ACCESS_TOKEN='...'
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  sync --shop store-a.myshopify.com --mode full
```

## Incremental sync

```bash
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  sync --shop store-a.myshopify.com \
  --mode incremental --since 2026-07-01T00:00:00Z
```

## Webhook ingestion

Capture the **raw request body** before any JSON middleware changes it, save the request headers as JSON, and then run:

```bash
export SHOPIFY_CLIENT_SECRET='...'
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  ingest-webhook --headers-json headers.json --body raw-body.json
```

Refresh verified product events:

```bash
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  refresh-queue --shop store-a.myshopify.com
```

This CLI is a secure processing core, not an HTTPS server. A deployment layer must pass the untouched raw body and headers into it.

## Synthetic demo and tests

```bash
./phase2/run-demo.sh /tmp/shelfboost-phase2-demo
PYTHONWARNINGS=error::ResourceWarning PYTHONPATH=phase2 \
  python3 -m unittest discover -s phase2/tests -v
```

## Scope intentionally deferred

- OAuth callback server and encrypted token vault;
- deployed HTTPS webhook endpoint;
- Phase 1 fact-ledger bridge;
- merchant UI;
- direct Shopify writes.

## Phase 2C — Phase 1 bridge

The bridge exports the current read-only mirror into the exact CSV contract consumed by Phase 1:

```bash
PYTHONPATH=phase2 python3 -m shelfboost_phase2 \
  --workspace /private/shelfboost/store-a \
  export-phase1 --shop store-a.myshopify.com \
  --output /private/shelfboost/store-a/exports/catalog.csv
```

It requires an active shop, a completed full baseline sync, complete variant data, and no pending, processing, or failed refresh work. Deleted products are excluded. Only allowlisted scalar `facts` metafields become `Metafield: facts.*` columns. The bridge writes a SHA-256 provenance manifest beside the CSV and does not write to Shopify.
