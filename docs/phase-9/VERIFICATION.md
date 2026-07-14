# Phase 9 Verification — Production hardening and controlled launch

- Roadmap version: 1.0
- Starting `main`: `4a219ee82aad548547ff377cb5b6e8528e14f668`
- Previous package: Phase 8 merged and CI-green
- Decision: **PROCEED with hardening, recovery, and launch-control contracts; public production launch remains blocked by external staging evidence.**

## Security and operations boundary

Phase 9 must make failure visible, bounded, and recoverable. It cannot manufacture evidence for a live penetration test, managed backup restore, cloud load test, payment-provider verification, Shopify app approval, or merchant acceptance. Fixture-backed tests may prove the application contracts; production launch gates must remain blocked until external evidence is attached.

## Threat model

- secrets in repository, logs, audit bundles, or exception text;
- abusive request bursts and expensive operation amplification;
- cascading provider failures;
- a feature flag enabling writes globally by mistake;
- rollback or billing kill switches that cannot be activated quickly;
- backups that exist but cannot restore;
- stale/tampered backup artifacts;
- misleading green health checks while dependencies fail;
- alert fatigue or missing SLO ownership;
- launching all merchants without a canary cohort;
- closing incidents without timeline/evidence;
- declaring production readiness with pending security, legal, provider, or staging gates.

## Data and artifacts

Feature flags and kill switches, launch gates/evidence, SLO definitions/observations, security findings, backup manifests, restore verifications, incidents, and final readiness report.

## Tests

- secret-pattern scanning and nested redaction;
- security headers;
- per-key rate limiting;
- circuit-breaker opening and recovery;
- deterministic canary assignment and immediate kill switch;
- SLO/error-budget calculation;
- backup manifest, tamper detection, and clean restore;
- launch gate blocks missing external evidence;
- incident lifecycle and timeline;
- final readiness report separates fixture-complete from production-verified;
- complete Phase 0–9 regression suite.

## Required external launch evidence

- deployed Shopify installation/token flow on a development store;
- managed KMS token round trip and rotation;
- deployed webhook retries and dead-letter replay;
- real AI provider evaluation, latency, cost, and data-processing decision;
- billing sandbox checkout/webhook lifecycle;
- analytics connector validation;
- managed backup restore drill;
- load/capacity test;
- dependency and container/runtime vulnerability scan;
- independent security review or penetration test appropriate to launch risk;
- privacy policy, terms, support, incident contacts, and Shopify approval.

## Non-goals

- bypassing a blocked gate;
- claiming production launch from unit tests;
- storing real secrets in fixtures;
- silent automatic canary expansion;
- destructive restore over an existing production database.

## Exit gate

Phase 9 code is complete when security, resilience, backup, incident, and controlled-launch contracts pass the full regression suite and `main` records a final readiness report. The product is publicly launchable only after all required external gates are independently marked passed with evidence.
