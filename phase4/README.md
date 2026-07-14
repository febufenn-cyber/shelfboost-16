# Shelfboost Phase 4 — Production application boundary

Phase 4 converts the local pilot architecture into portable production contracts for identity, tenancy, Shopify installation, encrypted credential storage, durable webhook jobs, privacy lifecycle, and health/readiness reporting.

## Implemented contracts

- environment validation and version/health/readiness status;
- additive tenant-scoped database migrations;
- organizations, users, memberships, roles, shops, and access checks;
- signed, expiring, one-time authorization state with shop binding;
- installation service separated from the Shopify authorization transport;
- envelope-cipher provider interface for access tokens;
- token rotation without plaintext database storage;
- webhook delivery deduplication and correlation IDs;
- retryable jobs, bounded attempts, dead letters, and shop cancellation;
- uninstall credential revocation;
- tenant data export and explicit purge requests;
- audit events without access-token values.

## Important boundary

The repository includes a test cipher only inside the test suite. Production must bind `TokenVault` to a managed KMS or audited envelope-encryption provider. No live Shopify credentials, deployed callback URL, or managed key provider were available during CI, so the deployed installation exit gate remains external.

## Validation

```bash
PYTHONPATH=phase4 python3 -m unittest discover -s phase4/tests -v
```
