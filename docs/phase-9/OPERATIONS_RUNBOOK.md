# Shelfboost Operations Runbook

## Immediate containment

1. Identify the affected tenant, shop, correlation ID, and operation.
2. Activate the narrowest applicable kill switch: generation, publishing, billing mutation, webhook processing, or analytics import.
3. Preserve logs, provider event IDs, publish/audit snapshots, and database state without copying secrets into tickets.
4. Declare an incident when customer data, catalog writes, billing, authentication, or availability may be affected.
5. Do not retry an uncertain Shopify mutation until the live resource is reconciled.

## Provider degradation

- Open the provider circuit breaker after the configured failure threshold.
- Keep read/export/history available.
- Queue only operations whose idempotency and replay contracts are documented.
- Move poison jobs to dead letter after bounded attempts.
- Resume through a canary cohort before broad enablement.

## Backup and restore

- Create backups from a quiesced or transactionally consistent source.
- Verify every file digest immediately.
- Restore only into a clean target.
- Verify restored digests and application migrations before cutover.
- Record restore evidence as a launch gate; backup existence alone is insufficient.

## Security incident

- Revoke and rotate affected tokens/keys through the provider.
- Disable writes and sensitive jobs.
- Search logs and audit artifacts using hashes and correlation IDs, not raw secrets.
- Preserve the incident timeline and decisions.
- Follow applicable notification and legal processes; this runbook is not legal advice.

## Launch and rollback

- Public launch requires every required gate to be `passed` with evidence.
- Start with an explicit canary percentage.
- Never expand the canary automatically from elapsed time alone.
- A kill switch overrides rollout configuration immediately.
- Product-content rollback still requires the Phase 3 live precondition check.
