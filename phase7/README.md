# Shelfboost Phase 7 — Commercial and compliance controls

Phase 7 adds provider-neutral billing events, subscriptions, entitlements, usage metering, privacy operations, retention records, scope justifications, and Shopify app-review readiness checks.

## Implemented

- raw-body billing signature verification through an injected provider;
- provider event deduplication and out-of-order event protection;
- trialing, active, past-due grace, cancelled, unpaid, and expired states;
- read, export, and privacy access preserved after cancellation;
- transactional, idempotent usage reservations and settlement;
- plan limits for generation, publishing, team members, and catalog products;
- versioned consent records and data inventory;
- tenant-scoped compliance export/delete/correction requests;
- retention eligibility with legal holds;
- Shopify scope justification and app-review checklist reports.

## Boundary

No production payment account, webhook secret, legal policy, tax configuration, Shopify Partner listing, or app approval was available. Fixture tests validate the event, entitlement, and compliance contracts. Owner, legal, provider, and Shopify review actions remain explicit external gates.

## Validation

```bash
PYTHONPATH=phase4:phase7 python3 -m unittest discover -s phase7/tests -v
```
