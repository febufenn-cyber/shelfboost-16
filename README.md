# Shelfboost

> Audit a Shopify catalog, find the listings most likely to need attention, and prepare fact-safe, brand-aligned improvements for human review.

Shelfboost began as a blueprint for bulk AI product copy. Phase 0 deliberately narrows the first move: validate the pain, buyer, trust requirements, pricing, and workflow before building Shopify OAuth, autonomous publishing, billing, or a full SaaS dashboard.

## Current status

| Phase | Status | Purpose |
|---|---|---|
| Phase 0 | **Implemented as a discovery system** | Prove the ICP, catalog pain, quality bar, trust boundary, recurring use, and willingness to pay |
| Phase 1 | Not started | Concierge audit and controlled draft-generation workflow |
| Phase 2+ | Not started | Shopify read-only integration, review, safe publishing, measurement, and moat |

## Phase 0 operating principle

Do not ask whether merchants like the idea. Ask whether they will provide a real catalog, review the output, request another batch, and pay to continue.

Phase 0 includes:

- binding hypotheses and kill criteria;
- an ICP scorecard for merchants and agencies;
- interview, audit, pilot, pricing, and decision templates;
- CSV evidence trackers;
- a deterministic, read-only Shopify CSV catalog-audit prototype;
- tests and CI for the prototype;
- explicit data-handling and trust rules.

## Run the catalog-audit prototype

The prototype uses only Python's standard library and never writes to Shopify.

```bash
python3 prototypes/catalog-audit/audit_catalog.py \
  prototypes/catalog-audit/sample/shopify-products.csv \
  --output-dir /tmp/shelfboost-audit
```

Outputs:

- `catalog-audit.csv` — product-level score, flags, and evidence;
- `catalog-summary.json` — aggregate findings and severity counts.

Run validation:

```bash
python3 -m unittest discover -s prototypes/catalog-audit/tests -v
python3 prototypes/catalog-audit/audit_catalog.py \
  prototypes/catalog-audit/sample/shopify-products.csv \
  --output-dir /tmp/shelfboost-audit-smoke
```

## Phase 0 documents

Start with [`docs/phase-0/00-phase-0-charter.md`](docs/phase-0/00-phase-0-charter.md), then use the interview, audit, pilot, and decision templates in order.

## Initial market thesis

The first two candidate segments are:

1. Shopify fashion, accessories, home-decor, and lifestyle brands with roughly 200–2,000 active products, frequent product launches, and a small content team.
2. Shopify or ecommerce SEO agencies managing at least five stores and repeating catalog-content work across clients.

The initial wedge is **read-only catalog diagnosis plus controlled draft preparation**, not mass autonomous publishing.

## Explicit non-goals for Phase 0

- Shopify OAuth or Admin API writes
- live-store publishing
- autonomous claims generation
- production auth, billing, or multi-tenant infrastructure
- a polished customer dashboard
- storing merchant CSVs in this public repository
- claiming SEO or revenue uplift without measured evidence

## Original blueprint

The longer-term product shape remains a Shopify application using Cloudflare Workers, Hono, Supabase, an AI generation layer, Shopify Admin API, and Stripe. That architecture is intentionally deferred until Phase 0 evidence earns it.
