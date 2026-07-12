# Trust and Risk Map

## Principle

Shelfboost earns write access only after proving read-only value. Human review remains the authority during Phase 0 and Phase 1.

| Risk | Early control | Evidence to capture | Deferred production control |
|---|---|---|---|
| Invented fact | Use only supplied product facts; show facts used | Fact-error and rejection codes | Structured source graph and validator |
| Unsupported claim | Flag risky language; abstain when source is absent | Claim-review incidents | Category policy and governed claims registry |
| Wrong brand voice | Structured profile plus approved examples | Repeated merchant edits | Versioned brand memory |
| Bad bulk change | No live writes in Phase 0 | Publishing objections | Per-field approval, idempotency, rollback |
| Lost original copy | Preserve source export and comparison | Demand for restoration | Versioned snapshots |
| Wrong product/variant | Group and identify by Shopify handle | Mapping defects | Stable Shopify IDs and reconciliation |
| Permission fear | CSV or read-only workflow | Scope concerns | Minimal OAuth scopes and clear consent |
| Private-data leak | Keep merchant data outside public repo | Data requests and retention needs | Encryption, tenant isolation, deletion workflows |
| False ROI claim | Report observed content issues only | Measurement expectations | Controlled attribution and holdouts |
| Reviewer fatigue | Prioritize small batches | Time and abandonment | Confidence filters and staged approvals |

## Phase 0 prohibited behavior

- publishing to a live Shopify store;
- generating missing product facts as if known;
- guaranteeing ranking, traffic, conversion, or revenue improvement;
- committing merchant exports or identifiable interview notes;
- using regulated categories as the first generalized pilot;
- treating a model confidence score as proof.

## Incident template

For every factual, claim, mapping, privacy, or trust incident, record:

1. item and field;
2. source inputs available;
3. expected behavior;
4. observed behavior;
5. whether the issue reached the participant;
6. containment action;
7. root-cause category;
8. prevention change;
9. owner and decision date.
